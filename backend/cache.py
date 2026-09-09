import fnmatch
import json
import time

import redis

from env import REDIS_MAX_CONNECTIONS, REDIS_URL
from logger import logger


class _InMemoryRedis:
    def __init__(self):
        self._store: dict[str, str] = {}
        self._hash_store: dict[str, dict[str, str]] = {}
        self._zset_store: dict[str, dict[str, float]] = {}
        self._list_store: dict[str, list[str]] = {}
        self._exp: dict[str, float] = {}

    def _purge(self, key: str):
        exp = self._exp.get(key)
        if exp is not None and time.time() > exp:
            self._store.pop(key, None)
            self._hash_store.pop(key, None)
            self._zset_store.pop(key, None)
            self._list_store.pop(key, None)
            self._exp.pop(key, None)

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False) -> bool:
        self._purge(key)
        if nx and key in self._store:
            return False
        self._store[key] = value
        if ex is not None:
            self._exp[key] = time.time() + ex
        else:
            self._exp.pop(key, None)
        return True

    def setex(self, key: str, ttl: int, value: str):
        self._store[key] = value
        self._exp[key] = time.time() + ttl

    def get(self, key: str) -> str | None:
        self._purge(key)
        return self._store.get(key)

    def delete(self, key: str):
        self._store.pop(key, None)
        self._hash_store.pop(key, None)
        self._zset_store.pop(key, None)
        self._list_store.pop(key, None)
        self._exp.pop(key, None)

    def hset(self, key: str, mapping: dict[str, str]):
        self._purge(key)
        self._hash_store.setdefault(key, {}).update(mapping)

    def expire(self, key: str, ttl: int):
        self._exp[key] = time.time() + ttl

    def ttl(self, key: str) -> int:
        """Mirrors Redis: -2 when the key is gone, -1 when it never expires."""
        self._purge(key)
        if not any(key in store for store in
                   (self._store, self._hash_store, self._zset_store, self._list_store)):
            return -2
        exp = self._exp.get(key)
        if exp is None:
            return -1
        return max(0, int(round(exp - time.time())))

    def hgetall(self, key: str) -> dict[str, str]:
        self._purge(key)
        return dict(self._hash_store.get(key, {}))

    def keys(self, pattern: str = "*") -> list[str]:
        for key in list(self._exp.keys()):
            self._purge(key)
        all_keys = set(self._store) | set(self._hash_store) | set(self._zset_store) | set(self._list_store)
        return [k for k in all_keys if fnmatch.fnmatch(k, pattern)]

    def scan_iter(self, match: str = "*", count: int | None = None):
        """Cursored scan. Production code must use this rather than `keys()`,
        which is O(N) over the whole keyspace and blocks the real server.

        The double has nothing to page over, so it yields the same set in one
        go — the point of matching the API here is that the call sites are
        exercised as written."""
        yield from self.keys(match)

    def eval(self, script: str, numkeys: int, *keys_and_args: str):
        """Run one of the Lua scripts this codebase ships.

        Real Redis executes these atomically server-side, which is the whole
        reason they are Lua and not two round trips. The double cannot run Lua,
        so it recognises the exact scripts in use and reproduces their
        semantics; an unknown script raises rather than silently no-opping, so
        adding one without teaching this double fails loudly in tests.
        """
        keys = list(keys_and_args[:numkeys])
        args = list(keys_and_args[numkeys:])
        normalized = " ".join(script.split())

        # Compare-and-delete (agent/llm_factory.RELEASE_LEASE_SCRIPT): release a
        # lease only while it still carries the caller's token.
        if normalized == (
            "if redis.call('get', KEYS[1]) == ARGV[1] then "
            "return redis.call('del', KEYS[1]) end return 0"
        ):
            key, token = keys[0], args[0]
            if self.get(key) == token:
                self.delete(key)
                return 1
            return 0

        raise NotImplementedError(
            f"_InMemoryRedis.eval does not know this script: {normalized!r}"
        )

    def rpush(self, key: str, *values: str) -> int:
        """Append to a list, creating it if absent — the digest queue (SPEC-052)."""
        self._purge(key)
        bucket = self._list_store.setdefault(key, [])
        bucket.extend(str(v) for v in values)
        return len(bucket)

    def lrange(self, key: str, start: int, end: int) -> list[str]:
        """Redis slice semantics: `end` is INCLUSIVE, and -1 means the last item."""
        self._purge(key)
        bucket = self._list_store.get(key, [])
        stop = None if end == -1 else end + 1
        return bucket[start:stop]

    def llen(self, key: str) -> int:
        self._purge(key)
        return len(self._list_store.get(key, []))

    def zadd(self, key: str, mapping: dict[str, float]):
        self._purge(key)
        self._zset_store.setdefault(key, {}).update(mapping)

    def zrangebyscore(self, key: str, min_score: float, max_score: float) -> list[str]:
        self._purge(key)
        members = self._zset_store.get(key, {})
        ranked = sorted(members.items(), key=lambda kv: kv[1])
        return [m for m, score in ranked if min_score <= score <= max_score]

    def zrem(self, key: str, *members: str):
        zset = self._zset_store.get(key)
        if zset:
            for member in members:
                zset.pop(member, None)

    def pipeline(self):
        return _InMemoryPipeline(self)


class _InMemoryPipeline:
    def __init__(self, client: _InMemoryRedis):
        self.client = client
        self.ops = []

    def incr(self, key: str):
        self.ops.append(("incr", key, None))
        return self

    def lrange(self, key: str, start: int, end: int):
        self.ops.append(("lrange", key, (start, end)))
        return self

    def delete(self, key: str):
        self.ops.append(("delete", key, None))
        return self

    def incrby(self, key: str, amount: int):
        self.ops.append(("incrby", key, amount))
        return self

    def expire(self, key: str, ttl: int):
        self.ops.append(("expire", key, ttl))
        return self

    def execute(self):
        """Run the queued ops in order, returning one result per op.

        Real redis-py pipelines are MULTI/EXEC by default and return a list of
        results; the read-then-delete drain in services/unread_digest.py depends
        on both properties, so the double reproduces them.
        """
        results = []
        for op, key, val in self.ops:
            if op == "incr":
                current = self.client.get(key)
                next_val = int(current) + 1 if current else 1
                self.client._store[key] = str(next_val)
                results.append(next_val)
            elif op == "incrby":
                current = self.client.get(key)
                next_val = int(current) + int(val) if current else int(val)
                self.client._store[key] = str(next_val)
                results.append(next_val)
            elif op == "expire":
                self.client.expire(key, int(val))
                results.append(True)
            elif op == "lrange":
                results.append(self.client.lrange(key, val[0], val[1]))
            elif op == "delete":
                self.client.delete(key)
                results.append(1)
            else:
                results.append(None)
        self.ops = []
        return results


def _create_redis_client():
    if not REDIS_URL:
        return _InMemoryRedis()
    try:
        client = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=REDIS_MAX_CONNECTIONS,
        )
        client.ping()
        return client
    except Exception as e:
        # Falling back to the in-memory double means caches, rate limits and
        # leases stop being shared between workers — degraded, not broken, but
        # never something to discover by accident.
        logger.warning(f"Redis unavailable at startup, falling back to in-memory cache: {e}")
        return _InMemoryRedis()


redis_client = _create_redis_client()


# ============================================
# TOKEN -> USER_ID CACHING (for auth middleware)
# ============================================

def cache_token_user(token: str, user_id: str, ttl: int = 7200):
    """Cache token -> user_id mapping (2 hours default)"""
    redis_client.setex(f"token:{token}", ttl, user_id)


def get_cached_user_by_token(token: str) -> str | None:
    """Get user_id from cached token"""
    return redis_client.get(f"token:{token}")


def invalidate_token(token: str):
    """Remove token from cache"""
    redis_client.delete(f"token:{token}")


# ============================================
# BAN STATUS CACHING (for auth middleware)
# ============================================

def cache_ban_status(user_id: str, banned: bool, ttl: int = 300):
    """Cache a user's ban status (5 min default) to avoid a DB hit per request."""
    redis_client.setex(f"banned:{user_id}", ttl, "1" if banned else "0")


def get_cached_ban_status(user_id: str) -> bool | None:
    """Return cached ban status, or None if not cached."""
    val = redis_client.get(f"banned:{user_id}")
    if val is None:
        return None
    return val == "1"


def invalidate_ban_status(user_id: str):
    """Drop cached ban status so the next request re-reads from the DB."""
    redis_client.delete(f"banned:{user_id}")


# ============================================
# ITEM CACHING (with SHA validation)
# ============================================

def cache_items_with_hash(items: list[dict], data_hash: str, ttl: int = 3600):
    """
    Cache all items list with a hash for validation.
    Hash is computed from count + max timestamp to detect changes.
    """
    redis_client.hset("items:all", mapping={
        "data": json.dumps(items),
        "hash": data_hash
    })
    redis_client.expire("items:all", ttl)


def get_cached_items_with_hash() -> tuple[list[dict] | None, str | None]:
    """Get cached items list and its hash"""
    result = redis_client.hgetall("items:all")
    if result and "data" in result:
        return json.loads(result["data"]), result.get("hash")
    return None, None


def cache_item(item_id: str, item: dict, ttl: int = 7200):
    """Cache single item (2 hours default - images use Supabase CDN caching)"""
    redis_client.setex(f"item:{item_id}", ttl, json.dumps(item))


def get_cached_item(item_id: str) -> dict | None:
    """Get cached item by ID"""
    data = redis_client.get(f"item:{item_id}")
    return json.loads(data) if data else None


def invalidate_item_cache(item_id: str = None):
    """Clear item cache (single or all) and reset validation timer"""
    if item_id:
        redis_client.delete(f"item:{item_id}")
    redis_client.delete("items:all")
    redis_client.delete("items:last_validation")  # Force re-validation on next request


# ============================================
# RATE LIMITING
# ============================================

def check_rate_limit(key: str, max_requests: int = 10, window: int = 60) -> bool:
    """
    Check if rate limit exceeded.

    Args:
        key: Unique identifier (e.g., user_id or IP)
        max_requests: Max requests allowed in window
        window: Time window in seconds

    Returns:
        True if OK to proceed, False if limit exceeded
    """
    rate_key = f"rate:{key}"
    current = redis_client.get(rate_key)

    if current and int(current) >= max_requests:
        return False

    pipe = redis_client.pipeline()
    pipe.incr(rate_key)
    pipe.expire(rate_key, window)
    pipe.execute()
    return True


def get_rate_limit_remaining(key: str, max_requests: int = 10) -> int:
    """Get remaining requests in current window"""
    current = redis_client.get(f"rate:{key}")
    if current:
        return max(0, max_requests - int(current))
    return max_requests


def get_rate_limit_retry_after(key: str, default: int = 60) -> int:
    """Seconds until the current window resets — what a client should wait.

    Reads the counter's own TTL, so the countdown a caller shows matches when
    the limiter will actually let them through. Redis returns -2 for a missing
    key and -1 for one with no expiry; both mean "no useful TTL", so callers
    get `default` rather than a nonsensical negative countdown.
    """
    try:
        ttl = redis_client.ttl(f"rate:{key}")
    except Exception:
        return default
    if ttl is None or ttl < 0:
        return default
    return int(ttl)


# ============================================
# AI TOKEN RATE LIMITING
# ============================================

def track_ai_tokens(user_id: str, input_tokens: int, output_tokens: int, window: int = 1800):
    """
    Track AI token usage for a user.

    Args:
        user_id: The user ID
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens used
        window: Time window in seconds (default 30 minutes)
    """
    key = f"ai_tokens:{user_id}"
    total_tokens = input_tokens + output_tokens

    # Use Redis INCRBY to atomically add tokens
    pipe = redis_client.pipeline()
    pipe.incrby(key, total_tokens)
    pipe.expire(key, window)
    pipe.execute()


def check_ai_token_limit(user_id: str, limit: int = 1_000_000, window: int = 1800) -> tuple[bool, int]:
    """
    Check if user has exceeded AI token limit.

    Args:
        user_id: The user ID
        limit: Maximum tokens allowed in window (default 1M)
        window: Time window in seconds (default 30 minutes)

    Returns:
        Tuple of (is_within_limit, current_usage)
    """
    key = f"ai_tokens:{user_id}"
    current = redis_client.get(key)

    if current:
        usage = int(current)
        return usage < limit, usage
    return True, 0


def get_ai_token_usage(user_id: str) -> int:
    """Get current AI token usage for a user."""
    key = f"ai_tokens:{user_id}"
    current = redis_client.get(key)
    return int(current) if current else 0
