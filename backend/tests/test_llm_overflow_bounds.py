"""SPEC-043 Workstream A — bounds on the Gemini overflow path.

SPEC-020 gave the local Qwen client a deliberate 2.0s connect / 120s read
timeout. The Gemini model three lines below it got neither a timeout nor a
retry policy, and nothing capped how many overflow turns could be in flight at
once. That matters more than it looks: the local laptop serves one turn per
45s lease, so at real concurrency *nearly every* turn is a Gemini turn. A slow
or rate-limited Gemini therefore isn't an edge case on this path — it's the
common case, and it had nothing catching it but a generic `except Exception`.
"""

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.llm_factory import (  # noqa: E402
    current_provider,
    hybrid_llm_session,
)


@pytest.fixture(autouse=True)
def _clean_provider_context():
    from agent.llm_factory import LOCAL_LLM_LEASE_KEY
    from cache import redis_client

    redis_client.delete(LOCAL_LLM_LEASE_KEY)
    token = current_provider.set(None)
    yield
    current_provider.reset(token)
    redis_client.delete(LOCAL_LLM_LEASE_KEY)


@pytest.fixture
def gemini_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-api-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")


@pytest.fixture
def tunnel_down(monkeypatch):
    async def _unhealthy(timeout=1.5):
        return False

    monkeypatch.setattr("agent.llm_factory.is_local_llm_available", _unhealthy)


@pytest.fixture(autouse=True)
def _clear_model_cache():
    """Models are cached per configuration; a stale entry would mask a config change."""
    import agent.llm_factory as factory

    factory._model_cache.clear()
    yield
    factory._model_cache.clear()


# ---------------------------------------------------------------------------
# A1 — the cloud model is built with a timeout and a bounded retry policy
# ---------------------------------------------------------------------------

def test_gemini_model_is_built_with_an_explicit_request_timeout(gemini_env):
    from agent.llm_factory import GEMINI_REQUEST_TIMEOUT, _build_gemini_model

    model = _build_gemini_model(temperature=0.7)

    assert model.timeout == GEMINI_REQUEST_TIMEOUT
    assert model.timeout is not None
    assert model.timeout > 0


def test_gemini_model_is_built_with_bounded_retries(gemini_env):
    """`max_retries` is what turns a 429/ResourceExhausted burst into a retry
    with backoff instead of an immediate failure — but it has to be bounded,
    or a rate-limited provider becomes an unbounded stall."""
    from agent.llm_factory import GEMINI_MAX_RETRIES, _build_gemini_model

    model = _build_gemini_model(temperature=0.7)

    assert model.max_retries == GEMINI_MAX_RETRIES
    assert 1 <= GEMINI_MAX_RETRIES <= 3


def test_local_model_keeps_its_own_timeouts(monkeypatch):
    """Regression guard: SPEC-020's local timeouts must not be disturbed."""
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://llm.negolah.my/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "mlx-community/Qwen3.6-35B-A3B-4bit")

    from agent.llm_factory import (
        LOCAL_CONNECT_TIMEOUT,
        LOCAL_READ_TIMEOUT,
        _build_local_model,
    )

    model = _build_local_model(temperature=0.7)

    assert model.request_timeout.connect == LOCAL_CONNECT_TIMEOUT
    assert model.request_timeout.read == LOCAL_READ_TIMEOUT


# ---------------------------------------------------------------------------
# A2 — concurrent overflow turns are capped per worker
# ---------------------------------------------------------------------------

def test_a_gemini_concurrency_cap_is_configured():
    from agent.llm_factory import GEMINI_MAX_CONCURRENCY

    assert GEMINI_MAX_CONCURRENCY >= 1


@pytest.mark.asyncio
async def test_overflow_turns_beyond_the_cap_wait_their_turn(
    gemini_env, tunnel_down, monkeypatch
):
    """Past the cap, a turn queues instead of piling onto an already-saturated
    box. Sized generously in production, so this only engages under real
    overload — SPEC-020's '0ms overflow' still holds below the cap."""
    import agent.llm_factory as factory

    monkeypatch.setattr(factory, "_gemini_semaphore", asyncio.Semaphore(2))

    started = []
    release = asyncio.Event()

    async def turn(name):
        async with hybrid_llm_session():
            started.append(name)
            await release.wait()

    tasks = [asyncio.create_task(turn(i)) for i in range(3)]
    await asyncio.sleep(0.05)

    # Two hold the cap; the third is still waiting to enter.
    assert len(started) == 2

    release.set()
    await asyncio.gather(*tasks)
    assert len(started) == 3


@pytest.mark.asyncio
async def test_the_cap_is_released_when_a_turn_raises(gemini_env, tunnel_down, monkeypatch):
    """A turn that blows up must not leak a permit, or the worker slowly
    strangles itself one failed turn at a time."""
    import agent.llm_factory as factory

    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(factory, "_gemini_semaphore", semaphore)

    with pytest.raises(RuntimeError):
        async with hybrid_llm_session():
            raise RuntimeError("turn exploded")

    assert not semaphore.locked()

    # And the next turn can still get in.
    async with hybrid_llm_session():
        pass
    assert not semaphore.locked()


@pytest.mark.asyncio
async def test_a_timed_out_turn_releases_the_lease_and_the_permit(
    gemini_env, tunnel_down, monkeypatch, client, patch_supabase, fake_supabase
):
    """The deadline in `/chat/stream` abandons a hung turn — but abandoning a
    generator mid-`await` only runs its cleanup if someone closes it. Miss that
    and every timed-out turn strands the laptop's lease for its full TTL and
    burns a cloud permit for the life of the process, so the worker quietly
    throttles itself one bad turn at a time.
    """
    import agent.bot as bot_module
    import agent.llm_factory as factory
    import routes.chat as chat_routes
    from agent.llm_factory import hybrid_llm_session

    semaphore = asyncio.Semaphore(1)
    monkeypatch.setattr(factory, "_gemini_semaphore", semaphore)

    async def _fake_verify(_request):
        return "u-timeout"

    monkeypatch.setattr(chat_routes, "verify_user_token", _fake_verify)
    monkeypatch.setattr(chat_routes, "check_rate_limit", lambda *a, **k: True)
    monkeypatch.setattr(chat_routes, "check_ai_token_limit", lambda *a, **k: (True, 0))
    monkeypatch.setattr(chat_routes, "get_rate_limit_remaining", lambda *a, **k: 9)
    monkeypatch.setattr(chat_routes, "track_ai_tokens", lambda *a, **k: None)
    monkeypatch.setattr(chat_routes, "CHAT_TURN_DEADLINE_SECONDS", 0.15)
    patch_supabase("routes.chat", admin=fake_supabase)
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .execute.return_value
    ) = SimpleNamespace(data=[])

    import payment.fulfillment as fulfillment
    monkeypatch.setattr(fulfillment, "broadcast_to_chat", lambda *a, **k: None)

    # A turn that takes the session (and therefore a permit) and then hangs,
    # exactly like a provider that accepted the request and never answered.
    async def hanging_turn(user_id, message, item_id=None, files=None):
        async with hybrid_llm_session() as provider:
            yield {"provider": provider.as_metadata()}
            await asyncio.sleep(30)

    monkeypatch.setattr(bot_module, "chat_stream", hanging_turn)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": "u-timeout", "message": "hi"},
        headers={"Authorization": "Bearer t"},
    )
    assert "data-turn-timeout" in resp.text

    # The permit is back, so the next buyer isn't queued behind a dead turn.
    assert not semaphore.locked()


@pytest.mark.asyncio
async def test_local_turns_are_not_gated_by_the_cloud_cap(monkeypatch):
    """The cap exists to bound *Gemini* fan-out. The laptop already has its own
    lease of exactly one; making it also wait on the cloud permit would be a
    second, redundant queue."""
    import agent.llm_factory as factory

    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://llm.negolah.my/v1")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-api-key")

    async def _healthy(timeout=1.5):
        return True

    monkeypatch.setattr(factory, "is_local_llm_available", _healthy)

    # A fully-exhausted cloud cap must not stop a local turn.
    exhausted = asyncio.Semaphore(1)
    await exhausted.acquire()
    monkeypatch.setattr(factory, "_gemini_semaphore", exhausted)

    async with asyncio.timeout(1.0):
        async with hybrid_llm_session() as info:
            assert info.is_local
