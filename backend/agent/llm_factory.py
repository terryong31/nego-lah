"""
Hybrid LLM dispatcher: self-hosted Apple Silicon Qwen + Google Gemini overflow.

SPEC-020. The self-hosted `Qwen3.6-35B-A3B-4bit` runs on a single M5 laptop
reached over a Cloudflare Tunnel. Apple Silicon serves ONE generation stream at
full speed; unbatched parallel streams saturate GPU bandwidth and collapse
latency to single-digit tokens/sec. So the laptop is treated as a pool of
exactly one worker, guarded by an atomic Redis lease:

  - lease free + tunnel healthy -> the turn runs on the M5
  - lease held (someone is generating) -> overflow to Gemini, 0ms wait
  - tunnel down / laptop asleep     -> overflow to Gemini

The provider is resolved ONCE per request by `hybrid_llm_session()` and pinned
in a ContextVar for the duration. Every model consumer in that turn — the
supervisor and both sub-agents — then reads the pinned choice instead of
re-probing, so one conversation never gets split across two models mid-turn,
and one turn never holds two leases.
"""

import os
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from cache import redis_client
from logger import logger

# --- Health probe -----------------------------------------------------------
LOCAL_LLM_PROBE_KEY = "health:local_llm"
PROBE_CACHE_TTL = 30  # seconds

# --- Concurrency lease ------------------------------------------------------
LOCAL_LLM_LEASE_KEY = "llm:qwen:busy"
# Backstop against a worker that dies mid-generation without running its
# `finally`. Long enough to cover a slow 35B turn, short enough that a crash
# doesn't strand the laptop out of rotation for long.
LEASE_TTL_SECONDS = 45

# --- Provider identifiers (also the wire values sent to the UI) -------------
PROVIDER_LOCAL = "local_qwen"
PROVIDER_CLOUD = "cloud_gemini"

LOCAL_HARDWARE_LABEL = "Apple M5 (Self-Hosted)"
CLOUD_HARDWARE_LABEL = "Google Cloud (Overflow)"

DEFAULT_LOCAL_MODEL = "mlx-community/Qwen3.6-35B-A3B-4bit"
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

# A downed tunnel is a *connect* failure, so a tight connect timeout is what
# makes failover instant. The read timeout stays generous on purpose: prefill on
# a 35B model with a long persona prompt and item images legitimately takes more
# than a couple of seconds, and killing that would be a self-inflicted outage.
LOCAL_CONNECT_TIMEOUT = 2.0
LOCAL_READ_TIMEOUT = float(os.getenv("LOCAL_LLM_READ_TIMEOUT", "120"))


@dataclass(frozen=True)
class ProviderInfo:
    """Which engine is serving the current turn, for logging and UI attribution."""

    provider: str
    model: str
    hardware: str

    @property
    def is_local(self) -> bool:
        return self.provider == PROVIDER_LOCAL

    def as_metadata(self) -> dict:
        """Serializable payload for the `/chat/stream` attribution event."""
        return {"provider": self.provider, "model": self.model, "hardware": self.hardware}


# The provider chosen for the in-flight turn. ContextVars are isolated per async
# task, so concurrent buyers never see each other's choice (same mechanism
# `agent/context.py` uses for user/item scoping).
current_provider: ContextVar[ProviderInfo | None] = ContextVar("current_provider", default=None)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _local_config() -> tuple[str, str, str]:
    return (
        os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8001/v1"),
        os.getenv("LOCAL_LLM_MODEL", DEFAULT_LOCAL_MODEL),
        os.getenv("LOCAL_LLM_API_KEY", "dummy-local-key"),
    )


def _gemini_model_name() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)


def local_provider_info() -> ProviderInfo:
    _, model_name, _ = _local_config()
    return ProviderInfo(provider=PROVIDER_LOCAL, model=model_name, hardware=LOCAL_HARDWARE_LABEL)


def cloud_provider_info() -> ProviderInfo:
    return ProviderInfo(provider=PROVIDER_CLOUD, model=_gemini_model_name(), hardware=CLOUD_HARDWARE_LABEL)


# ---------------------------------------------------------------------------
# Health probing
# ---------------------------------------------------------------------------

def _probe_url() -> str:
    base_url = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8001/v1").rstrip("/")
    return f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/health"


def _check_cache() -> bool | None:
    try:
        cached = redis_client.get(LOCAL_LLM_PROBE_KEY)
        if cached is not None:
            val = cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
            return val == "1"
    except Exception as e:
        logger.debug(f"Redis probe cache lookup failed: {e}")
    return None


def _set_cache(is_up: bool) -> None:
    try:
        redis_client.set(LOCAL_LLM_PROBE_KEY, "1" if is_up else "0", ex=PROBE_CACHE_TTL)
    except Exception as e:
        logger.debug(f"Redis probe cache set failed: {e}")


def is_local_llm_available_sync(timeout: float = 1.5) -> bool:
    """Synchronously check if the self-hosted local model or Cloudflare Tunnel is reachable."""
    cached = _check_cache()
    if cached is not None:
        return cached

    url = _probe_url()
    is_up = False
    try:
        with httpx.Client(timeout=timeout) as client:
            res = client.get(url)
            is_up = res.status_code == 200
    except Exception as e:
        logger.debug(f"Local LLM probe failed at {url}: {e}")
        is_up = False

    _set_cache(is_up)
    return is_up


async def is_local_llm_available(timeout: float = 1.5) -> bool:
    """Asynchronously check if the self-hosted local model or Cloudflare Tunnel is reachable."""
    cached = _check_cache()
    if cached is not None:
        return cached

    url = _probe_url()
    is_up = False
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.get(url)
            is_up = res.status_code == 200
    except Exception as e:
        logger.debug(f"Local LLM probe failed at {url}: {e}")
        is_up = False

    _set_cache(is_up)
    return is_up


# ---------------------------------------------------------------------------
# Atomic concurrency lease
# ---------------------------------------------------------------------------

def try_acquire_local_llm_lease() -> bool:
    """Claim the laptop's single generation slot. Never blocks.

    `SET key 1 NX EX 45` is one atomic round-trip, so this is correct across
    uvicorn workers and processes. Returns False when the slot is already taken
    — the caller must then overflow to the cloud rather than queue.

    A Redis failure returns False (fail-closed): losing the lease guarantee is
    worse than overflowing, because two concurrent streams would tank the
    laptop's throughput for both buyers.
    """
    try:
        acquired = redis_client.set(LOCAL_LLM_LEASE_KEY, "1", nx=True, ex=LEASE_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"⚠️ Redis unavailable for local LLM lease, overflowing to cloud: {e}")
        return False
    return bool(acquired)


def release_local_llm_lease() -> None:
    """Hand the laptop's generation slot back. Safe to call when not held."""
    try:
        redis_client.delete(LOCAL_LLM_LEASE_KEY)
    except Exception as e:
        logger.warning(f"⚠️ Failed to release local LLM lease (TTL will reclaim it): {e}")


# ---------------------------------------------------------------------------
# Per-request provider selection
# ---------------------------------------------------------------------------

async def resolve_provider() -> tuple[ProviderInfo, bool]:
    """Pick the engine for this turn. Returns (info, holds_lease).

    Order matters: the cheap checks (explicit override, cached health) run
    before the lease is touched, so we never acquire a lease we won't use.
    """
    preference = os.getenv("LLM_PROVIDER", "auto").lower()

    if preference not in ("local", "auto"):
        return cloud_provider_info(), False

    if not await is_local_llm_available():
        logger.warning("⚠️ Local LLM endpoint unreachable or tunnel down. Overflowing to Gemini.")
        return cloud_provider_info(), False

    if not try_acquire_local_llm_lease():
        logger.info("🔁 Local Qwen busy generating — overflowing this turn to Gemini (0ms wait).")
        return cloud_provider_info(), False

    info = local_provider_info()
    logger.info(f"🧠 Routing turn to Local Multimodal LLM: {info.model} on {info.hardware}")
    return info, True


@asynccontextmanager
async def hybrid_llm_session():
    """Own the provider decision for one chat turn.

    Pins the choice in `current_provider` so every model built inside the turn
    agrees, and releases the lease in `finally` so a crashed or client-cancelled
    generation frees the laptop immediately rather than waiting out the TTL.
    """
    info, holds_lease = await resolve_provider()
    token = current_provider.set(info)
    try:
        yield info
    finally:
        current_provider.reset(token)
        if holds_lease:
            release_local_llm_lease()


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------

# Chat model objects are immutable config wrappers around a pooled HTTP client,
# so they're cached per resolved configuration. The key includes every env-derived
# value, which means changing configuration yields a new instance rather than a
# stale one — this caches *clients*, not the routing decision the spec removed.
_model_cache: dict[tuple, BaseChatModel] = {}


def _build_local_model(temperature: float) -> ChatOpenAI:
    base_url, model_name, api_key = _local_config()
    key = (PROVIDER_LOCAL, base_url, model_name, api_key, temperature)

    cached = _model_cache.get(key)
    if cached is not None:
        return cached

    model = ChatOpenAI(
        model_name=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        streaming=True,
        max_retries=1,
        timeout=httpx.Timeout(
            LOCAL_READ_TIMEOUT,
            connect=LOCAL_CONNECT_TIMEOUT,
        ),
    )
    _model_cache[key] = model
    return model


def _build_gemini_model(temperature: float) -> ChatGoogleGenerativeAI:
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    model_name = _gemini_model_name()
    key = (PROVIDER_CLOUD, model_name, gemini_key, temperature)

    cached = _model_cache.get(key)
    if cached is not None:
        return cached

    model = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=gemini_key,
        temperature=temperature,
    )
    _model_cache[key] = model
    return model


def _model_for(info: ProviderInfo, temperature: float) -> BaseChatModel:
    return _build_local_model(temperature) if info.is_local else _build_gemini_model(temperature)


def get_chat_model(
    temperature: float = 0.7,
    force_provider: str | None = None,
    use_sync_probe: bool = True
) -> BaseChatModel:
    """Get the chat model for the current turn.

    Inside a `hybrid_llm_session()` this returns the pinned provider's model with
    no probe and no lease work — the decision was already made for the whole turn.
    Outside one (standalone tool calls, scripts) it falls back to probe-and-fail-over,
    which is best-effort and takes no lease.
    """
    pinned = current_provider.get()
    if force_provider is None and pinned is not None:
        return _model_for(pinned, temperature)

    provider = (force_provider or os.getenv("LLM_PROVIDER", "auto")).lower()

    if provider in ("local", "auto"):
        is_up = is_local_llm_available_sync() if use_sync_probe else False
        if is_up:
            logger.info(f"🧠 Routing to Local Multimodal LLM: {_local_config()[1]}")
            return _build_local_model(temperature)
        logger.warning("⚠️ Local LLM endpoint unreachable or tunnel down. Falling back to Gemini.")

    logger.info(f"✨ Routing to Google Gemini: {_gemini_model_name()}")
    return _build_gemini_model(temperature)


async def aget_chat_model(
    temperature: float = 0.7,
    force_provider: str | None = None
) -> BaseChatModel:
    """Asynchronous variant of `get_chat_model` (async health probe)."""
    pinned = current_provider.get()
    if force_provider is None and pinned is not None:
        return _model_for(pinned, temperature)

    provider = (force_provider or os.getenv("LLM_PROVIDER", "auto")).lower()

    if provider in ("local", "auto"):
        if await is_local_llm_available():
            logger.info(f"🧠 Routing to Local Multimodal LLM: {_local_config()[1]}")
            return _build_local_model(temperature)
        logger.warning("⚠️ Local LLM endpoint unreachable or tunnel down. Falling back to Gemini.")

    logger.info(f"✨ Routing to Google Gemini: {_gemini_model_name()}")
    return _build_gemini_model(temperature)
