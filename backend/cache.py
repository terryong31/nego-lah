import json
import time
from typing import Dict, List, Optional

import redis

from env import REDIS_URL


class _InMemoryRedis:
    def __init__(self):
        self._store: Dict[str, str] = {}
        self._hash_store: Dict[str, Dict[str, str]] = {}
        self._exp: Dict[str, float] = {}

    def _purge(self, key: str):
        exp = self._exp.get(key)
        if exp is not None and time.time() > exp:
            self._store.pop(key, None)
            self._hash_store.pop(key, None)
            self._exp.pop(key, None)

    def setex(self, key: str, ttl: int, value: str):
        self._store[key] = value
        self._exp[key] = time.time() + ttl

    def get(self, key: str) -> Optional[str]:
        self._purge(key)
        return self._store.get(key)

    def delete(self, key: str):
        self._store.pop(key, None)
        self._hash_store.pop(key, None)
        self._exp.pop(key, None)

    def hset(self, key: str, mapping: Dict[str, str]):
        self._purge(key)
        self._hash_store.setdefault(key, {}).update(mapping)

    def expire(self, key: str, ttl: int):
        self._exp[key] = time.time() + ttl

    def hgetall(self, key: str) -> Dict[str, str]:
        self._purge(key)
        return dict(self._hash_store.get(key, {}))

    def pipeline(self):
        return _InMemoryPipeline(self)


class _InMemoryPipeline:
    def __init__(self, client: _InMemoryRedis):
        self.client = client
        self.ops = []

    def incr(self, key: str):
        self.ops.append(("incr", key, None))
        return self

    def incrby(self, key: str, amount: int):
        self.ops.append(("incrby", key, amount))
        return self

    def expire(self, key: str, ttl: int):
        self.ops.append(("expire", key, ttl))
        return self

    def execute(self):
        for op, key, val in self.ops:
            if op == "incr":
                current = self.client.get(key)
                next_val = int(current) + 1 if current else 1
                self.client._store[key] = str(next_val)
            elif op == "incrby":
                current = self.client.get(key)
                next_val = int(current) + int(val) if current else int(val)
                self.client._store[key] = str(next_val)
            elif op == "expire":
                self.client.expire(key, int(val))
        self.ops = []


def _create_redis_client():
    if not REDIS_URL:
        return _InMemoryRedis()
    try:
        client = redis.from_url(REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return _InMemoryRedis()


redis_client = _create_redis_client()


# ============================================
# USER SESSIONS
# ============================================

def cache_session(user_id: str, token: str, ttl: int = 7200):
    """Cache user session (2 hours default - auto logout after TTL)"""
    redis_client.setex(f"session:{user_id}", ttl, token)
    # Also cache reverse lookup for token validation
    redis_client.setex(f"token:{token}", ttl, user_id)


def get_session(user_id: str) -> Optional[str]:
    """Get cached session token"""
    return redis_client.get(f"session:{user_id}")


def invalidate_session(user_id: str):
    """Logout - remove session"""
    # Get token first to remove reverse lookup
    token = redis_client.get(f"session:{user_id}")
    if token:
        redis_client.delete(f"token:{token}")
    redis_client.delete(f"session:{user_id}")


# ============================================
# TOKEN -> USER_ID CACHING (for auth middleware)
# ============================================

def cache_token_user(token: str, user_id: str, ttl: int = 7200):
    """Cache token -> user_id mapping (2 hours default)"""
    redis_client.setex(f"token:{token}", ttl, user_id)


def get_cached_user_by_token(token: str) -> Optional[str]:
    """Get user_id from cached token"""
    return redis_client.get(f"token:{token}")


def invalidate_token(token: str):
    """Remove token from cache"""
    redis_client.delete(f"token:{token}")


# ============================================
# ITEM CACHING (with SHA validation)
# ============================================

def cache_items_with_hash(items: List[Dict], data_hash: str, ttl: int = 3600):
    """
    Cache all items list with a hash for validation.
    Hash is computed from count + max timestamp to detect changes.
    """
    redis_client.hset("items:all", mapping={
        "data": json.dumps(items),
        "hash": data_hash
    })
    redis_client.expire("items:all", ttl)


def get_cached_items_with_hash() -> tuple[Optional[List[Dict]], Optional[str]]:
    """Get cached items list and its hash"""
    result = redis_client.hgetall("items:all")
    if result and "data" in result:
        return json.loads(result["data"]), result.get("hash")
    return None, None


def cache_items(items: List[Dict], ttl: int = 3600):
    """Cache all items list (1 hour default - legacy function for compatibility)"""
    redis_client.setex("items:all:legacy", ttl, json.dumps(items))


def get_cached_items() -> Optional[List[Dict]]:
    """Get cached items list (legacy - without hash validation)"""
    data = redis_client.get("items:all:legacy")
    return json.loads(data) if data else None


def cache_item(item_id: str, item: Dict, ttl: int = 7200):
    """Cache single item (2 hours default - images use Supabase CDN caching)"""
    redis_client.setex(f"item:{item_id}", ttl, json.dumps(item))


def get_cached_item(item_id: str) -> Optional[Dict]:
    """Get cached item by ID"""
    data = redis_client.get(f"item:{item_id}")
    return json.loads(data) if data else None


def invalidate_item_cache(item_id: str = None):
    """Clear item cache (single or all) and reset validation timer"""
    if item_id:
        redis_client.delete(f"item:{item_id}")
    redis_client.delete("items:all")
    redis_client.delete("items:all:legacy")
    redis_client.delete("items:last_validation")  # Force re-validation on next request


# ============================================
# CHAT HISTORY CACHE
# ============================================

def cache_chat_history(user_id: str, history: List[Dict], ttl: int = 3600):
    """Cache chat history (1 hour default)"""
    redis_client.setex(f"chat:{user_id}", ttl, json.dumps(history))


def get_cached_chat_history(user_id: str) -> Optional[List[Dict]]:
    """Get cached chat history"""
    data = redis_client.get(f"chat:{user_id}")
    return json.loads(data) if data else None


def append_chat_message(user_id: str, role: str, message: str):
    """Add message to cached chat (also refreshes TTL)"""
    history = get_cached_chat_history(user_id) or []
    history.append({"role": role, "content": message})
    # Keep last 20 messages to prevent bloat
    cache_chat_history(user_id, history[-20:])


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
