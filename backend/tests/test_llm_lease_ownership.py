"""
SPEC-037 — the local-LLM lease must be released only by its owner.

The old release was a bare `DELETE`. The 45s TTL exists so a crashed holder
can't wedge the laptop forever, which means a *slow* holder can outlive its own
lease: generation runs past 45s, the key expires, worker B legitimately acquires
the slot, worker A's `finally` fires and deletes B's lease. A third worker then
acquires the laptop while B is still generating — the exact "one generation at a
time" invariant the whole balancer exists to hold.

The fix is the standard one: store a random token as the lease value and
compare-and-delete atomically, so a release can only ever remove your own lease.
"""

import pytest

from agent.llm_factory import (
    LOCAL_LLM_LEASE_KEY,
    current_provider,
    release_local_llm_lease,
    try_acquire_local_llm_lease,
)


@pytest.fixture
def tunnel_up(monkeypatch):
    """Report the Apple M5 tunnel as healthy without any HTTP traffic."""
    async def _healthy(timeout=1.5):
        return True

    monkeypatch.setattr("agent.llm_factory.is_local_llm_available", _healthy)


@pytest.fixture
def local_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "https://llm.negolah.my/v1")
    monkeypatch.setenv("LOCAL_LLM_MODEL", "mlx-community/Qwen3.6-35B-A3B-4bit")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-api-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.8-flash")


@pytest.fixture(autouse=True)
def _clean_lease():
    from cache import redis_client

    redis_client.delete(LOCAL_LLM_LEASE_KEY)
    token = current_provider.set(None)
    yield
    current_provider.reset(token)
    redis_client.delete(LOCAL_LLM_LEASE_KEY)


def test_acquire_returns_an_opaque_owner_token():
    token = try_acquire_local_llm_lease()

    assert isinstance(token, str) and token
    # The token IS the stored value — that's what makes the release checkable.
    from cache import redis_client
    assert redis_client.get(LOCAL_LLM_LEASE_KEY) == token


def test_each_acquisition_gets_a_distinct_token():
    first = try_acquire_local_llm_lease()
    release_local_llm_lease(first)
    second = try_acquire_local_llm_lease()

    assert first != second


def test_owner_can_release_its_own_lease():
    from cache import redis_client

    token = try_acquire_local_llm_lease()
    release_local_llm_lease(token)

    assert redis_client.get(LOCAL_LLM_LEASE_KEY) is None
    assert try_acquire_local_llm_lease() is not None


def test_expired_holder_cannot_release_the_next_workers_lease():
    """The regression this spec exists for.

    Worker A acquires, generation overruns, the TTL expires the key, worker B
    acquires the now-free slot. A's `finally` must be a no-op, not a theft.
    """
    from cache import redis_client

    token_a = try_acquire_local_llm_lease()

    # TTL fires mid-generation.
    redis_client.delete(LOCAL_LLM_LEASE_KEY)

    token_b = try_acquire_local_llm_lease()
    assert token_b != token_a

    # A finally block finally runs — far too late.
    release_local_llm_lease(token_a)

    assert redis_client.get(LOCAL_LLM_LEASE_KEY) == token_b, (
        "worker A deleted worker B's lease"
    )
    assert try_acquire_local_llm_lease() is None, (
        "the slot was handed out while worker B still held it"
    )


def test_release_with_a_token_that_was_never_issued_is_a_noop():
    from cache import redis_client

    token = try_acquire_local_llm_lease()
    release_local_llm_lease("not-a-real-token")

    assert redis_client.get(LOCAL_LLM_LEASE_KEY) == token


def test_release_without_a_token_is_a_noop():
    from cache import redis_client

    token = try_acquire_local_llm_lease()
    release_local_llm_lease(None)

    assert redis_client.get(LOCAL_LLM_LEASE_KEY) == token


def test_redis_outage_fails_closed_on_acquire_and_swallows_on_release(monkeypatch):
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


async def test_session_releases_only_its_own_lease(monkeypatch, local_env, tunnel_up):
    """End to end through `hybrid_llm_session`: the token has to be threaded
    from `resolve_provider` into the `finally`, or the fix doesn't reach the
    code path that actually runs in production."""
    from agent.llm_factory import hybrid_llm_session
    from cache import redis_client

    async with hybrid_llm_session():
        held = redis_client.get(LOCAL_LLM_LEASE_KEY)
        assert held is not None
        # The slot expires under us and the next worker takes it.
        redis_client.delete(LOCAL_LLM_LEASE_KEY)
        stolen = try_acquire_local_llm_lease()

    assert redis_client.get(LOCAL_LLM_LEASE_KEY) == stolen
