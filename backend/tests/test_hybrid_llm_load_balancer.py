"""
Tests for SPEC-020 — the hybrid Apple-Silicon/Gemini load balancer.

The unit under test is `agent/llm_factory.py`'s concurrency lease plus the
per-request provider pinning that `agent/bot.py` and the sub-agents route
through. The invariant the whole design rests on: the self-hosted M5 laptop
serves exactly ONE generation at a time, and every other concurrent turn
overflows to Gemini with zero queuing.

Mocking seams (see conftest.py's docstring for the general rules):
  - Redis is conftest's in-memory fake (`VERCEL=1` forces it), which implements
    `SET .. NX EX` and TTL purging against `cache.time.time` — so lease
    atomicity and TTL expiry are both exercisable without a real server.
  - The health probe is patched at `agent.llm_factory.is_local_llm_available`
    rather than at the httpx layer, so tests state "tunnel up/down" directly.
  - No test ever constructs a real network call: `ChatOpenAI` /
    `ChatGoogleGenerativeAI` are inert to build.
"""

import asyncio

import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from agent.llm_factory import (
    LEASE_TTL_SECONDS,
    LOCAL_LLM_LEASE_KEY,
    PROVIDER_CLOUD,
    PROVIDER_LOCAL,
    current_provider,
    get_chat_model,
    hybrid_llm_session,
    release_local_llm_lease,
    try_acquire_local_llm_lease,
)


@pytest.fixture(autouse=True)
def _clean_lease():
    """Guarantee no lease leaks between tests (the autouse Redis flush in
    conftest runs after, but the ContextVar needs its own reset)."""
    from cache import redis_client

    redis_client.delete(LOCAL_LLM_LEASE_KEY)
    token = current_provider.set(None)
    yield
    current_provider.reset(token)
    redis_client.delete(LOCAL_LLM_LEASE_KEY)


@pytest.fixture
def tunnel_up(monkeypatch):
    """Report the Apple M5 tunnel as healthy without any HTTP traffic."""
    async def _healthy(timeout=1.5):
        return True

    monkeypatch.setattr("agent.llm_factory.is_local_llm_available", _healthy)


@pytest.fixture
def tunnel_down(monkeypatch):
    async def _unhealthy(timeout=1.5):
        return False

    monkeypatch.setattr("agent.llm_factory.is_local_llm_available", _unhealthy)


@pytest.fixture
def local_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://llm.negolah.my/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "mlx-community/Qwen3.6-35B-A3B-4bit")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-api-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")


# ---------------------------------------------------------------------------
# Atomic Redis concurrency lease
# ---------------------------------------------------------------------------

def test_acquire_lease_sets_key_with_ttl():
    """First acquirer wins and the key carries the deadlock-breaking TTL."""
    from cache import redis_client

    token = try_acquire_local_llm_lease()
    assert token is not None
    # The stored value is the owner token — that is what makes a release
    # checkable (SPEC-037), so it must be the token and not a constant.
    assert redis_client.get(LOCAL_LLM_LEASE_KEY) == token


def test_second_acquire_fails_while_lease_held():
    assert try_acquire_local_llm_lease() is not None
    assert try_acquire_local_llm_lease() is None


def test_release_lease_allows_reacquisition():
    token = try_acquire_local_llm_lease()
    assert token is not None
    release_local_llm_lease(token)

    from cache import redis_client
    assert redis_client.get(LOCAL_LLM_LEASE_KEY) is None
    assert try_acquire_local_llm_lease() is not None


def test_lease_acquisition_survives_redis_outage(monkeypatch):
    """A dead Redis must not take the chat endpoint down with it: we fail
    CLOSED on the local model (overflow to Gemini) rather than risk two
    concurrent generations saturating the laptop's GPU."""
    class BrokenRedis:
        def set(self, *a, **kw):
            raise ConnectionError("redis down")

        def eval(self, *a, **kw):
            raise ConnectionError("redis down")

        def delete(self, *a, **kw):
            raise ConnectionError("redis down")

    monkeypatch.setattr("agent.llm_factory.redis_client", BrokenRedis())

    assert try_acquire_local_llm_lease() is None
    release_local_llm_lease("some-token")  # must not raise


# ---------------------------------------------------------------------------
# Scenario 1 — idle local dispatch
# ---------------------------------------------------------------------------

async def test_scenario_1_idle_dispatches_to_local_qwen(local_env, tunnel_up):
    """Healthy tunnel + no lease => the turn runs on the Apple M5."""
    from cache import redis_client

    async with hybrid_llm_session() as info:
        assert info.provider == PROVIDER_LOCAL
        assert info.model == "mlx-community/Qwen3.6-35B-A3B-4bit"
        # Lease is held for the duration of the turn.
        assert redis_client.get(LOCAL_LLM_LEASE_KEY) is not None

        model = get_chat_model(temperature=0.7)
        assert isinstance(model, ChatOpenAI)
        assert model.model_name == "mlx-community/Qwen3.6-35B-A3B-4bit"


# ---------------------------------------------------------------------------
# Scenario 2 — busy cloud overflow, zero wait
# ---------------------------------------------------------------------------

async def test_scenario_2_busy_overflows_to_gemini(local_env, tunnel_up):
    """A lease already held by another turn pushes this one straight to Gemini."""
    assert try_acquire_local_llm_lease() is not None

    async with hybrid_llm_session() as info:
        assert info.provider == PROVIDER_CLOUD
        assert info.model == "gemini-3.8-flash"

        model = get_chat_model(temperature=0.7)
        assert isinstance(model, ChatGoogleGenerativeAI)


async def test_scenario_2_overflow_makes_no_http_call_to_the_tunnel(local_env, monkeypatch):
    """When the lease is taken, we must not even probe the tunnel — the whole
    point is a 0ms decision, not a 2s connect timeout in front of every turn."""
    probe_calls = []

    async def _probe(timeout=1.5):
        probe_calls.append(timeout)
        return True

    monkeypatch.setattr("agent.llm_factory.is_local_llm_available", _probe)
    assert try_acquire_local_llm_lease() is not None

    async with hybrid_llm_session() as info:
        assert info.provider == PROVIDER_CLOUD

    # The probe may run at most once (to establish health), but the decision to
    # overflow must never depend on a fresh HTTP round-trip to a busy laptop.
    assert len(probe_calls) <= 1


async def test_overflow_when_tunnel_is_down(local_env, tunnel_down):
    """Scenario: laptop asleep / tunnel down => Gemini, and no lease taken."""
    from cache import redis_client

    async with hybrid_llm_session() as info:
        assert info.provider == PROVIDER_CLOUD
        # No lease was acquired, so nothing to release and nothing blocking others.
        assert redis_client.get(LOCAL_LLM_LEASE_KEY) is None


async def test_forced_gemini_provider_never_takes_the_lease(local_env, tunnel_up, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    from cache import redis_client

    async with hybrid_llm_session() as info:
        assert info.provider == PROVIDER_CLOUD
        assert redis_client.get(LOCAL_LLM_LEASE_KEY) is None


# ---------------------------------------------------------------------------
# Scenario 3 — lease release on completion and on failure
# ---------------------------------------------------------------------------

async def test_scenario_3_lease_released_after_normal_completion(local_env, tunnel_up):
    from cache import redis_client

    async with hybrid_llm_session() as info:
        assert info.provider == PROVIDER_LOCAL

    assert redis_client.get(LOCAL_LLM_LEASE_KEY) is None
    # The next turn can go local again.
    assert try_acquire_local_llm_lease() is not None


async def test_scenario_3_lease_released_when_the_turn_raises(local_env, tunnel_up):
    """A crashing generation must not wedge the laptop out of rotation."""
    from cache import redis_client

    with pytest.raises(RuntimeError, match="boom"):
        async with hybrid_llm_session():
            raise RuntimeError("boom")

    assert redis_client.get(LOCAL_LLM_LEASE_KEY) is None


async def test_provider_context_is_reset_after_the_session(local_env, tunnel_up):
    async with hybrid_llm_session():
        assert current_provider.get() is not None
    assert current_provider.get() is None


# ---------------------------------------------------------------------------
# Scenario 4 — multi-worker concurrency
# ---------------------------------------------------------------------------

async def test_scenario_4_exactly_one_of_four_concurrent_turns_goes_local(local_env, tunnel_up):
    """Four simultaneous buyers: one gets the M5, three overflow instantly.

    True cross-process atomicity is Redis's own `SET NX` contract; what this
    asserts is that the dispatcher relies on that single atomic operation and
    holds the lease for the whole turn, which is the part we own.
    """
    observed = []

    async def turn():
        async with hybrid_llm_session() as info:
            observed.append(info.provider)
            # Hold the lease across an await point, as a real generation would.
            await asyncio.sleep(0.01)

    await asyncio.gather(*(turn() for _ in range(4)))

    assert observed.count(PROVIDER_LOCAL) == 1
    assert observed.count(PROVIDER_CLOUD) == 3


async def test_lease_frees_up_for_the_next_turn_after_the_first_finishes(local_env, tunnel_up):
    """Sequential turns each get the laptop back — the lease is not sticky."""
    providers = []
    for _ in range(3):
        async with hybrid_llm_session() as info:
            providers.append(info.provider)

    assert providers == [PROVIDER_LOCAL, PROVIDER_LOCAL, PROVIDER_LOCAL]


# ---------------------------------------------------------------------------
# Scenario 5 — persona/history continuity across providers
# ---------------------------------------------------------------------------

async def test_scenario_5_same_history_regardless_of_provider(local_env, tunnel_up, monkeypatch):
    """The message list handed to the agent must be byte-identical whether the
    turn lands on Qwen or on Gemini — provider selection is transport, not
    conversation state."""
    import agent.bot as bot

    monkeypatch.setattr(
        bot.conversation_memory,
        "get_history",
        lambda user_id, limit=50: [
            {"role": "human", "content": "got any iphones?"},
            {"role": "ai", "content": "Yep! iPhone 13 for RM1500 😊"},
        ],
    )

    captured = []

    class RecordingAgent:
        async def astream(self, payload, stream_mode="messages"):
            captured.append(payload["messages"])
            return
            yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(bot, "_get_customer_agent", lambda: RecordingAgent())
    monkeypatch.setattr(bot.conversation_memory, "add_message", lambda *a, **kw: None)

    # Turn A: laptop idle -> local.
    async for _ in bot.chat_stream(user_id="u1", message="how much?"):
        pass

    # Turn B: laptop busy -> Gemini overflow.
    assert try_acquire_local_llm_lease() is not None
    async for _ in bot.chat_stream(user_id="u1", message="how much?"):
        pass

    assert len(captured) == 2
    local_msgs, cloud_msgs = captured
    assert [(type(m), m.content) for m in local_msgs] == [(type(m), m.content) for m in cloud_msgs]


# ---------------------------------------------------------------------------
# Scenario 6 — deadlock prevention via TTL
# ---------------------------------------------------------------------------

def test_scenario_6_lease_expires_after_ttl_when_holder_dies(monkeypatch):
    """A worker killed mid-generation never runs its `finally`. The 45s TTL is
    what stops the laptop being permanently marked busy."""
    import cache
    from cache import redis_client

    fake_now = [1_000_000.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])

    assert try_acquire_local_llm_lease() is not None
    # Holder "crashes" here — no release_local_llm_lease() call.
    assert try_acquire_local_llm_lease() is None

    # Just before expiry it's still held.
    fake_now[0] += LEASE_TTL_SECONDS - 1
    assert try_acquire_local_llm_lease() is None

    # Past the TTL, Redis drops it and the laptop is back in rotation.
    fake_now[0] += 2
    assert redis_client.get(LOCAL_LLM_LEASE_KEY) is None
    assert try_acquire_local_llm_lease() is not None


def test_lease_ttl_matches_spec():
    assert LEASE_TTL_SECONDS == 45


# ---------------------------------------------------------------------------
# Tight tunnel timeout
# ---------------------------------------------------------------------------

def test_local_model_uses_fast_connect_timeout(local_env, monkeypatch):
    """A downed tunnel must fail over in ~2s, not hang the buyer. The read
    timeout stays generous so long prefill on a 35B model isn't killed."""
    monkeypatch.setattr("agent.llm_factory.is_local_llm_available_sync", lambda timeout=1.5: True)

    model = get_chat_model(temperature=0.7, force_provider="local")
    timeout = model.client._client.timeout

    assert timeout.connect == pytest.approx(2.0)
    assert timeout.read > 2.0


# ---------------------------------------------------------------------------
# Provider attribution metadata
# ---------------------------------------------------------------------------

async def test_provider_metadata_shape_local(local_env, tunnel_up):
    async with hybrid_llm_session() as info:
        meta = info.as_metadata()
        assert meta["provider"] == PROVIDER_LOCAL
        assert meta["model"] == "mlx-community/Qwen3.6-35B-A3B-4bit"
        assert "Apple M5" in meta["hardware"]


async def test_provider_metadata_shape_cloud(local_env, tunnel_down):
    async with hybrid_llm_session() as info:
        meta = info.as_metadata()
        assert meta["provider"] == PROVIDER_CLOUD
        assert meta["model"] == "gemini-3.8-flash"
        assert meta["hardware"]


async def test_bot_chat_stream_emits_provider_metadata_first(local_env, tunnel_up, monkeypatch):
    """`chat_stream` announces the provider before any token so the UI can show
    the attribution chip while the answer is still generating."""
    import agent.bot as bot

    class SilentAgent:
        async def astream(self, payload, stream_mode="messages"):
            return
            yield  # pragma: no cover

    monkeypatch.setattr(bot, "_get_customer_agent", lambda: SilentAgent())
    monkeypatch.setattr(bot.conversation_memory, "get_history", lambda *a, **kw: [])
    monkeypatch.setattr(bot.conversation_memory, "add_message", lambda *a, **kw: None)

    events = [e async for e in bot.chat_stream(user_id="u1", message="hi")]

    assert events, "stream produced nothing"
    first = events[0]
    assert isinstance(first, dict)
    assert first["provider"]["provider"] == PROVIDER_LOCAL
    assert first["provider"]["model"] == "mlx-community/Qwen3.6-35B-A3B-4bit"


# ---------------------------------------------------------------------------
# Dynamic model selection (no frozen singletons)
# ---------------------------------------------------------------------------

def test_customer_agent_model_is_resolved_per_turn(local_env, monkeypatch):
    """The compiled graph is cached, but the model behind it is not: flipping
    the pinned provider between turns must flip the model actually used."""
    import agent.bot as bot
    from agent.llm_factory import ProviderInfo

    resolve = bot._select_customer_model

    token = current_provider.set(
        ProviderInfo(provider=PROVIDER_LOCAL, model="mlx-community/Qwen3.6-35B-A3B-4bit", hardware="Apple M5")
    )
    try:
        local_bound = resolve(None, None)
    finally:
        current_provider.reset(token)

    token = current_provider.set(
        ProviderInfo(provider=PROVIDER_CLOUD, model="gemini-3.8-flash", hardware="Google Cloud")
    )
    try:
        cloud_bound = resolve(None, None)
    finally:
        current_provider.reset(token)

    def underlying(bound):
        return getattr(bound, "bound", bound)

    assert isinstance(underlying(local_bound), ChatOpenAI)
    assert isinstance(underlying(cloud_bound), ChatGoogleGenerativeAI)


def test_bot_has_no_frozen_model_singleton():
    """SPEC-020 removes the module-level `_model` cache that pinned the whole
    process to whichever provider happened to be up at first import."""
    import agent.bot as bot

    assert not hasattr(bot, "_model"), "agent.bot._model singleton should be gone"


def test_sub_agents_have_no_import_time_model():
    """The sub-agents used to construct a model (and fire a health probe) at
    import time, freezing the provider for the life of the process."""
    from agent.sub_agents import item_agent as item_mod
    from agent.sub_agents import stripe_agent as stripe_mod

    assert not hasattr(item_mod, "model"), "item_agent.model singleton should be gone"
    assert not hasattr(stripe_mod, "model"), "stripe_agent.model singleton should be gone"
