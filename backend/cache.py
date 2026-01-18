import redis
import json
from typing import Optional, Any, List, Dict
from env import REDIS_URL

# Connect to Redis
redis_client = redis.from_url(REDIS_URL, decode_responses=True)


# ============================================
# USER SESSIONS
# ============================================

def cache_session(user_id: str, token: str, ttl: int = 1800):
    """Cache user session (30 min default)"""
    redis_client.setex(f"session:{user_id}", ttl, token)


def get_session(user_id: str) -> Optional[str]:
    """Get cached session token"""
    return redis_client.get(f"session:{user_id}")


def invalidate_session(user_id: str):
    """Logout - remove session"""
    redis_client.delete(f"session:{user_id}")


# ============================================
# ITEM CACHING
# ============================================

def cache_items(items: List[Dict], ttl: int = 300):
    """Cache all items list (5 min default)"""
    redis_client.setex("items:all", ttl, json.dumps(items))


def get_cached_items() -> Optional[List[Dict]]:
    """Get cached items list"""
    data = redis_client.get("items:all")
    return json.loads(data) if data else None


def cache_item(item_id: str, item: Dict, ttl: int = 600):
    """Cache single item (10 min default)"""
    redis_client.setex(f"item:{item_id}", ttl, json.dumps(item))


def get_cached_item(item_id: str) -> Optional[Dict]:
    """Get cached item by ID"""
    data = redis_client.get(f"item:{item_id}")
    return json.loads(data) if data else None


def invalidate_item_cache(item_id: str = None):
    """Clear item cache (single or all)"""
    if item_id:
        redis_client.delete(f"item:{item_id}")
    redis_client.delete("items:all")


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