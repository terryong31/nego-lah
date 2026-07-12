from slowapi import Limiter
from slowapi.util import get_remote_address

from cache import _InMemoryRedis, redis_client
from env import REDIS_URL

# Share rate-limit counters across worker processes via Redis when it's actually
# available. Falls back to per-process in-memory storage otherwise, mirroring how
# cache.py degrades when Redis can't be reached.
_use_redis = not isinstance(redis_client, _InMemoryRedis)
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=REDIS_URL if _use_redis else None,
)
