import os

from slowapi import Limiter
from slowapi.util import get_remote_address

from cache import _InMemoryRedis, check_rate_limit, get_rate_limit_retry_after, redis_client
from env import REDIS_URL

# Share rate-limit counters across worker processes via Redis when it's actually
# available. Falls back to per-process in-memory storage otherwise, mirroring how
# cache.py degrades when Redis can't be reached.
_use_redis = not isinstance(redis_client, _InMemoryRedis)
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=REDIS_URL if _use_redis else None,
)

# Per-IP ceilings for endpoints to stop one scripted laptop saturating the box.
# Sized coarsely for NAT safety (office/conference sharing one IP).
CATALOG_LIMIT = os.getenv("CATALOG_RATE_LIMIT", "6000/minute")
NOTIFICATION_STREAM_LIMIT = os.getenv("NOTIFICATION_STREAM_RATE_LIMIT", "2000/minute")
CHECKOUT_LIMIT = os.getenv("CHECKOUT_RATE_LIMIT", "600/minute")
ACCOUNT_LIMIT = os.getenv("ACCOUNT_RATE_LIMIT", "1000/minute")
CHAT_STREAM_LIMIT = os.getenv("CHAT_STREAM_RATE_LIMIT", "300/minute")
DEFAULT_LIMIT = os.getenv("DEFAULT_RATE_LIMIT", "10000/minute")


def parse_rate_limit(limit_str: str) -> tuple[int, int]:
    """Parse string format like '6000/minute' or '10/second' into (max_requests, window_seconds)."""
    count_str, _, unit = limit_str.partition("/")
    count = int(count_str.strip())
    unit = unit.strip().lower()
    if unit in ("s", "sec", "second"):
        window = 1
    elif unit in ("m", "min", "minute"):
        window = 60
    elif unit in ("h", "hr", "hour"):
        window = 3600
    elif unit in ("d", "day"):
        window = 86400
    else:
        window = 60
    return count, window


def resolve_route_limit(path: str) -> tuple[str, str]:
    """Map request path to bucket name and rate limit string."""
    if path.startswith("/chat/stream"):
        return "chat_stream", CHAT_STREAM_LIMIT
    if path.startswith("/payment/checkout"):
        return "checkout", CHECKOUT_LIMIT
    if path.startswith("/chat/notifications"):
        return "notifications", NOTIFICATION_STREAM_LIMIT
    if path.startswith("/user"):
        return "user", ACCOUNT_LIMIT
    if path.startswith("/items"):
        return "items", CATALOG_LIMIT
    return "default", DEFAULT_LIMIT


def check_ip_rate_limit(path: str, ip: str) -> tuple[bool, int]:
    """
    Check if IP has exceeded the limit for a path.
    Returns (is_allowed, retry_after_seconds).
    """
    bucket, limit_str = resolve_route_limit(path)
    max_requests, window = parse_rate_limit(limit_str)
    key = f"ip:{bucket}:{ip}"
    allowed = check_rate_limit(key, max_requests=max_requests, window=window)
    if not allowed:
        retry_after = get_rate_limit_retry_after(key, default=window)
        return False, retry_after
    return True, 0
