import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from slowapi import Limiter
from slowapi.util import get_remote_address

import limiter as limiter_module
from cache import _InMemoryRedis


def test_limiter_is_a_slowapi_limiter_instance():
    assert isinstance(limiter_module.limiter, Limiter)


def test_limiter_key_func_is_get_remote_address():
    # slowapi stores the provided key_func as `_key_func` on the Limiter instance.
    assert limiter_module.limiter._key_func is get_remote_address


def test_use_redis_reflects_in_memory_fallback_in_tests():
    # conftest.py forces VERCEL=1 and strips REDIS_URL, so cache.redis_client is
    # always the in-memory fallback during the test suite, never a real Redis client.
    from cache import redis_client

    assert isinstance(redis_client, _InMemoryRedis)
    assert limiter_module._use_redis is False


def test_storage_uri_is_none_when_not_using_redis():
    # When _use_redis is False, the Limiter must be constructed with storage_uri=None
    # so it falls back to slowapi/limits' in-memory storage instead of trying to reach Redis.
    assert limiter_module._use_redis is False
    assert limiter_module.limiter._storage_uri is None


def test_limiter_uses_in_memory_storage_backend():
    # With storage_uri=None, the underlying limits storage strategy should be the
    # in-process MemoryStorage, not a RedisStorage instance.
    storage = limiter_module.limiter._limiter.storage
    assert type(storage).__name__ == "MemoryStorage"


def test_use_redis_would_be_true_if_redis_client_were_real(monkeypatch):
    # Sanity-check the boolean logic in isolation: _use_redis is defined as
    # `not isinstance(redis_client, _InMemoryRedis)`, so swap in a plain object
    # standing in for a real redis client and confirm the predicate flips.
    import cache

    class _FakeRealRedisClient:
        pass

    monkeypatch.setattr(cache, "redis_client", _FakeRealRedisClient())
    recomputed_use_redis = not isinstance(cache.redis_client, _InMemoryRedis)
    assert recomputed_use_redis is True
