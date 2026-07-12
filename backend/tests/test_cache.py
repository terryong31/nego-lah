import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock

import cache
from cache import _InMemoryRedis

# =====================================================================
# Direct unit tests of the _InMemoryRedis fake (TTL / data-structure semantics)
# =====================================================================

def test_inmemory_setex_and_get_roundtrip():
    r = _InMemoryRedis()
    r.setex("k", 100, "v")
    assert r.get("k") == "v"


def test_inmemory_get_missing_key_returns_none():
    r = _InMemoryRedis()
    assert r.get("missing") is None


def test_inmemory_setex_expiry_purges_all_stores(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    r = _InMemoryRedis()
    r.setex("k", 10, "v")
    assert r.get("k") == "v"
    fake_now[0] = 11.0
    assert r.get("k") is None
    # purge should have fully removed bookkeeping, not just hidden the value
    assert "k" not in r._store
    assert "k" not in r._exp


def test_inmemory_setex_not_yet_expired_is_kept(monkeypatch):
    fake_now = [100.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    r = _InMemoryRedis()
    r.setex("k", 10, "v")
    fake_now[0] = 109.999
    assert r.get("k") == "v"


def test_inmemory_delete_clears_string_hash_and_zset_state():
    r = _InMemoryRedis()
    r.setex("k", 100, "v")
    r.hset("k", {"a": "1"})
    r.zadd("k", {"m": 1.0})
    r.delete("k")
    assert r.get("k") is None
    assert r.hgetall("k") == {}
    assert r.zrangebyscore("k", 0, 10) == []
    assert "k" not in r._exp


def test_inmemory_delete_missing_key_is_noop():
    r = _InMemoryRedis()
    r.delete("does-not-exist")  # should not raise


def test_inmemory_hset_and_hgetall_merges_fields():
    r = _InMemoryRedis()
    r.hset("h", {"a": "1"})
    r.hset("h", {"b": "2"})
    assert r.hgetall("h") == {"a": "1", "b": "2"}


def test_inmemory_hgetall_returns_copy_not_live_reference():
    r = _InMemoryRedis()
    r.hset("h", {"a": "1"})
    snapshot = r.hgetall("h")
    snapshot["a"] = "mutated"
    assert r.hgetall("h") == {"a": "1"}


def test_inmemory_hgetall_missing_key_returns_empty_dict():
    r = _InMemoryRedis()
    assert r.hgetall("nope") == {}


def test_inmemory_expire_on_hash_then_purge(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    r = _InMemoryRedis()
    r.hset("h", {"a": "1"})
    r.expire("h", 5)
    assert r.hgetall("h") == {"a": "1"}
    fake_now[0] = 6.0
    assert r.hgetall("h") == {}


def test_inmemory_keys_pattern_matching():
    r = _InMemoryRedis()
    r.setex("a:1", 100, "v")
    r.setex("a:2", 100, "v")
    r.setex("b:1", 100, "v")
    assert sorted(r.keys("a:*")) == ["a:1", "a:2"]
    assert sorted(r.keys()) == ["a:1", "a:2", "b:1"]


def test_inmemory_keys_default_pattern_is_wildcard():
    r = _InMemoryRedis()
    r.setex("only-key", 100, "v")
    assert r.keys() == ["only-key"]


def test_inmemory_keys_purges_expired_entries_first(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    r = _InMemoryRedis()
    r.setex("short", 5, "v")
    r.setex("long", 100, "v")
    fake_now[0] = 6.0
    assert r.keys("*") == ["long"]
    assert "short" not in r._store


def test_inmemory_keys_includes_hash_and_zset_keys():
    r = _InMemoryRedis()
    r.hset("hkey", {"a": "1"})
    r.zadd("zkey", {"m": 1.0})
    assert sorted(r.keys("*")) == ["hkey", "zkey"]


def test_inmemory_zadd_and_zrangebyscore_orders_by_score():
    r = _InMemoryRedis()
    r.zadd("z", {"m1": 5.0, "m2": 1.0, "m3": 10.0})
    assert r.zrangebyscore("z", 0, 10) == ["m2", "m1", "m3"]


def test_inmemory_zrangebyscore_filters_by_bounds_inclusive():
    r = _InMemoryRedis()
    r.zadd("z", {"m1": 1.0, "m2": 5.0, "m3": 10.0})
    assert r.zrangebyscore("z", 1.0, 5.0) == ["m1", "m2"]


def test_inmemory_zrangebyscore_missing_key_returns_empty_list():
    r = _InMemoryRedis()
    assert r.zrangebyscore("nope", 0, 10) == []


def test_inmemory_zrem_removes_specific_members():
    r = _InMemoryRedis()
    r.zadd("z", {"m1": 1.0, "m2": 2.0, "m3": 3.0})
    r.zrem("z", "m1", "m3")
    assert r.zrangebyscore("z", 0, 10) == ["m2"]


def test_inmemory_zrem_on_nonexistent_key_is_noop():
    r = _InMemoryRedis()
    r.zrem("nonexistent", "m1")  # should not raise


def test_inmemory_zset_expires_and_purges(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    r = _InMemoryRedis()
    r.zadd("z", {"m1": 1.0})
    r.expire("z", 5)
    fake_now[0] = 6.0
    assert r.zrangebyscore("z", 0, 10) == []


def test_inmemory_pipeline_incr_starts_at_one_and_increments():
    r = _InMemoryRedis()
    pipe = r.pipeline()
    pipe.incr("c")
    pipe.execute()
    assert r.get("c") == "1"

    pipe2 = r.pipeline()
    pipe2.incr("c")
    pipe2.execute()
    assert r.get("c") == "2"


def test_inmemory_pipeline_incrby_accumulates():
    r = _InMemoryRedis()
    pipe = r.pipeline()
    pipe.incrby("c", 5)
    pipe.execute()
    assert r.get("c") == "5"

    pipe2 = r.pipeline()
    pipe2.incrby("c", 3)
    pipe2.execute()
    assert r.get("c") == "8"


def test_inmemory_pipeline_expire_sets_expiry():
    r = _InMemoryRedis()
    pipe = r.pipeline()
    pipe.incr("c")
    pipe.expire("c", 100)
    pipe.execute()
    assert "c" in r._exp


def test_inmemory_pipeline_ops_reset_after_execute():
    r = _InMemoryRedis()
    pipe = r.pipeline()
    pipe.incr("c")
    assert pipe.ops != []
    pipe.execute()
    assert pipe.ops == []


def test_inmemory_pipeline_continues_after_expire_op():
    # Regression coverage for the loop continuing past an "expire" op to a
    # later op in the same pipeline (real call sites always put expire last).
    r = _InMemoryRedis()
    pipe = r.pipeline()
    pipe.incr("a")
    pipe.expire("a", 10)
    pipe.incr("b")
    pipe.execute()
    assert r.get("a") == "1"
    assert r.get("b") == "1"
    assert "a" in r._exp


def test_inmemory_pipeline_execute_silently_skips_unrecognized_ops():
    # `.ops` only ever contains ("incr"|"incrby"|"expire", ...) tuples via the
    # public incr()/incrby()/expire() methods, so this branch of execute()'s
    # if/elif chain (an op matching none of them) is unreachable through the
    # public API. Exercise it directly to document that execute() just skips
    # unknown ops rather than raising.
    r = _InMemoryRedis()
    pipe = r.pipeline()
    pipe.ops.append(("noop", "x", None))
    pipe.execute()  # should not raise
    assert r.get("x") is None
    assert pipe.ops == []


def test_inmemory_pipeline_chaining_returns_self():
    r = _InMemoryRedis()
    pipe = r.pipeline()
    result = pipe.incr("c").expire("c", 10)
    assert result is pipe


# =====================================================================
# _create_redis_client branch coverage (no real network calls: redis.from_url
# and .ping() are mocked so nothing ever touches an actual socket)
# =====================================================================

def test_create_redis_client_returns_inmemory_when_no_url(monkeypatch):
    monkeypatch.setattr(cache, "REDIS_URL", None)
    client = cache._create_redis_client()
    assert isinstance(client, _InMemoryRedis)


def test_create_redis_client_returns_real_client_on_success(monkeypatch):
    fake_client = MagicMock()
    fake_client.ping.return_value = True
    monkeypatch.setattr(cache, "REDIS_URL", "redis://fake-host:6379")
    monkeypatch.setattr(cache.redis, "from_url", MagicMock(return_value=fake_client))
    client = cache._create_redis_client()
    assert client is fake_client


def test_create_redis_client_falls_back_to_inmemory_on_exception(monkeypatch):
    broken_client = MagicMock()
    broken_client.ping.side_effect = Exception("connection refused")
    monkeypatch.setattr(cache, "REDIS_URL", "redis://fake-host:6379")
    monkeypatch.setattr(cache.redis, "from_url", MagicMock(return_value=broken_client))
    client = cache._create_redis_client()
    assert isinstance(client, _InMemoryRedis)


def test_module_level_redis_client_is_inmemory_in_tests():
    # conftest.py forces VERCEL=1 and strips REDIS_URL, so this must always be
    # the in-memory fallback for the whole test suite.
    assert isinstance(cache.redis_client, _InMemoryRedis)


# =====================================================================
# cache_token_user / get_cached_user_by_token / invalidate_token
# =====================================================================

def test_cache_and_get_token_user():
    cache.cache_token_user("tok-1", "user-1")
    assert cache.get_cached_user_by_token("tok-1") == "user-1"


def test_get_cached_user_by_token_missing_returns_none():
    assert cache.get_cached_user_by_token("no-such-token") is None


def test_invalidate_token_removes_mapping():
    cache.cache_token_user("tok-2", "user-2")
    assert cache.get_cached_user_by_token("tok-2") == "user-2"
    cache.invalidate_token("tok-2")
    assert cache.get_cached_user_by_token("tok-2") is None


def test_invalidate_token_on_missing_token_is_noop():
    cache.invalidate_token("never-cached")  # should not raise


def test_cache_token_user_respects_ttl_expiry(monkeypatch):
    fake_now = [1000.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    cache.cache_token_user("tok-ttl", "user-ttl", ttl=10)
    assert cache.get_cached_user_by_token("tok-ttl") == "user-ttl"
    fake_now[0] += 11
    assert cache.get_cached_user_by_token("tok-ttl") is None


# =====================================================================
# cache_ban_status / get_cached_ban_status / invalidate_ban_status
# =====================================================================

def test_cache_ban_status_true():
    cache.cache_ban_status("user-a", True)
    assert cache.get_cached_ban_status("user-a") is True


def test_cache_ban_status_false():
    cache.cache_ban_status("user-b", False)
    assert cache.get_cached_ban_status("user-b") is False


def test_get_cached_ban_status_uncached_returns_none():
    assert cache.get_cached_ban_status("never-cached-user") is None


def test_invalidate_ban_status_clears_cache():
    cache.cache_ban_status("user-c", True)
    cache.invalidate_ban_status("user-c")
    assert cache.get_cached_ban_status("user-c") is None


def test_cache_ban_status_ttl_expiry(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    cache.cache_ban_status("user-ttl", True, ttl=300)
    assert cache.get_cached_ban_status("user-ttl") is True
    fake_now[0] = 301.0
    assert cache.get_cached_ban_status("user-ttl") is None


# =====================================================================
# cache_items_with_hash / get_cached_items_with_hash
# =====================================================================

def test_cache_and_get_items_with_hash():
    items = [{"id": "1", "name": "Widget"}, {"id": "2", "name": "Gadget"}]
    cache.cache_items_with_hash(items, "hash-abc")
    cached_items, cached_hash = cache.get_cached_items_with_hash()
    assert cached_items == items
    assert cached_hash == "hash-abc"


def test_get_cached_items_with_hash_when_empty_returns_none_none():
    cached_items, cached_hash = cache.get_cached_items_with_hash()
    assert cached_items is None
    assert cached_hash is None


def test_get_cached_items_with_hash_missing_data_field_returns_none_none():
    # Simulate a hash entry that exists but has no "data" field (defensive branch).
    cache.redis_client.hset("items:all", mapping={"hash": "only-hash-no-data"})
    cached_items, cached_hash = cache.get_cached_items_with_hash()
    assert cached_items is None
    assert cached_hash is None


def test_cache_items_with_hash_overwrites_previous_value():
    cache.cache_items_with_hash([{"id": "1"}], "hash-1")
    cache.cache_items_with_hash([{"id": "2"}], "hash-2")
    cached_items, cached_hash = cache.get_cached_items_with_hash()
    assert cached_items == [{"id": "2"}]
    assert cached_hash == "hash-2"


def test_cache_items_with_hash_respects_ttl_expiry(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    cache.cache_items_with_hash([{"id": "1"}], "hash-1", ttl=60)
    fake_now[0] = 61.0
    cached_items, cached_hash = cache.get_cached_items_with_hash()
    assert cached_items is None
    assert cached_hash is None


# =====================================================================
# cache_item / get_cached_item / invalidate_item_cache
# =====================================================================

def test_cache_and_get_item_roundtrip():
    item = {"id": "item-1", "name": "Chair", "price": 100}
    cache.cache_item("item-1", item)
    assert cache.get_cached_item("item-1") == item


def test_get_cached_item_missing_returns_none():
    assert cache.get_cached_item("no-such-item") is None


def test_cache_item_ttl_expiry(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    cache.cache_item("item-ttl", {"id": "item-ttl"}, ttl=10)
    assert cache.get_cached_item("item-ttl") == {"id": "item-ttl"}
    fake_now[0] = 11.0
    assert cache.get_cached_item("item-ttl") is None


def test_invalidate_item_cache_with_item_id_clears_item_and_list_state():
    cache.cache_item("item-2", {"id": "item-2"})
    cache.cache_items_with_hash([{"id": "item-2"}], "some-hash")
    cache.redis_client.setex("items:last_validation", 100, "1")

    cache.invalidate_item_cache("item-2")

    assert cache.get_cached_item("item-2") is None
    assert cache.get_cached_items_with_hash() == (None, None)
    assert cache.redis_client.get("items:last_validation") is None


def test_invalidate_item_cache_without_item_id_only_clears_list_state():
    cache.cache_item("item-3", {"id": "item-3"})
    cache.cache_items_with_hash([{"id": "item-3"}], "some-hash")
    cache.redis_client.setex("items:last_validation", 100, "1")

    cache.invalidate_item_cache()

    # Specific item cache is untouched when no item_id is given.
    assert cache.get_cached_item("item-3") == {"id": "item-3"}
    assert cache.get_cached_items_with_hash() == (None, None)
    assert cache.redis_client.get("items:last_validation") is None


# =====================================================================
# check_rate_limit / get_rate_limit_remaining
# =====================================================================

def test_check_rate_limit_allows_up_to_max_then_blocks():
    key = "rl-user-1"
    for _ in range(3):
        assert cache.check_rate_limit(key, max_requests=3, window=60) is True
    assert cache.check_rate_limit(key, max_requests=3, window=60) is False


def test_check_rate_limit_independent_keys_have_independent_counters():
    assert cache.check_rate_limit("rl-a", max_requests=1, window=60) is True
    assert cache.check_rate_limit("rl-a", max_requests=1, window=60) is False
    # a different key must not be affected by rl-a's limit
    assert cache.check_rate_limit("rl-b", max_requests=1, window=60) is True


def test_check_rate_limit_resets_after_window_expires(monkeypatch):
    fake_now = [2000.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    key = "rl-window"
    for _ in range(2):
        assert cache.check_rate_limit(key, max_requests=2, window=30) is True
    assert cache.check_rate_limit(key, max_requests=2, window=30) is False

    fake_now[0] += 31
    assert cache.check_rate_limit(key, max_requests=2, window=30) is True


def test_get_rate_limit_remaining_when_uncached_returns_max():
    assert cache.get_rate_limit_remaining("rl-fresh", max_requests=10) == 10


def test_get_rate_limit_remaining_decrements_as_requests_are_made():
    key = "rl-remaining"
    cache.check_rate_limit(key, max_requests=5, window=60)
    assert cache.get_rate_limit_remaining(key, max_requests=5) == 4
    cache.check_rate_limit(key, max_requests=5, window=60)
    assert cache.get_rate_limit_remaining(key, max_requests=5) == 3


def test_get_rate_limit_remaining_floors_at_zero_when_over_limit():
    key = "rl-over"
    for _ in range(3):
        cache.check_rate_limit(key, max_requests=3, window=60)
    # one more attempt is blocked and does not increment the counter further
    cache.check_rate_limit(key, max_requests=3, window=60)
    assert cache.get_rate_limit_remaining(key, max_requests=3) == 0


# =====================================================================
# track_ai_tokens / check_ai_token_limit / get_ai_token_usage
# =====================================================================

def test_get_ai_token_usage_when_uncached_is_zero():
    assert cache.get_ai_token_usage("ai-fresh-user") == 0


def test_check_ai_token_limit_when_uncached_is_within_limit():
    is_ok, usage = cache.check_ai_token_limit("ai-fresh-user-2")
    assert is_ok is True
    assert usage == 0


def test_track_ai_tokens_accumulates_input_and_output():
    user = "ai-user-1"
    cache.track_ai_tokens(user, input_tokens=100, output_tokens=50)
    assert cache.get_ai_token_usage(user) == 150
    cache.track_ai_tokens(user, input_tokens=25, output_tokens=25)
    assert cache.get_ai_token_usage(user) == 200


def test_check_ai_token_limit_within_limit():
    user = "ai-user-2"
    cache.track_ai_tokens(user, input_tokens=100, output_tokens=100)
    is_ok, usage = cache.check_ai_token_limit(user, limit=1000)
    assert is_ok is True
    assert usage == 200


def test_check_ai_token_limit_exceeded():
    user = "ai-user-3"
    cache.track_ai_tokens(user, input_tokens=900, output_tokens=200)
    is_ok, usage = cache.check_ai_token_limit(user, limit=1000)
    assert is_ok is False
    assert usage == 1100


def test_track_ai_tokens_respects_window_expiry(monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(cache.time, "time", lambda: fake_now[0])
    user = "ai-user-window"
    cache.track_ai_tokens(user, input_tokens=500, output_tokens=0, window=60)
    assert cache.get_ai_token_usage(user) == 500
    fake_now[0] = 61.0
    assert cache.get_ai_token_usage(user) == 0


def test_check_ai_token_limit_boundary_is_exclusive():
    # usage == limit should NOT count as "within limit" (uses strict `<`).
    user = "ai-user-boundary"
    cache.track_ai_tokens(user, input_tokens=1000, output_tokens=0)
    is_ok, usage = cache.check_ai_token_limit(user, limit=1000)
    assert is_ok is False
    assert usage == 1000
