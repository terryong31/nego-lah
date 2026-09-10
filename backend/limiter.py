import os

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

# Per-IP ceilings for the endpoints a burst actually lands on. They exist to
# stop one scripted laptop saturating the box (SPEC-043 workstream D) — NOT to
# pace normal use, which `cache.check_rate_limit` already does per authenticated
# user and which NAT cannot distort.
#
# They are coarse on purpose. "Per IP" is only "per person" on the open
# internet: behind NAT — conference wifi, an office, a campus, a mobile
# carrier — one address is the entire room. Sized per-person, these would lock
# a venue out of its own demo, and load testing showed exactly that: 40
# notification-stream opens from one simulated NAT address produced 10 × 429,
# i.e. the 31st attendee to open the app was refused.
#
# So the numbers below assume one address may legitimately be hundreds of
# people, and are set to catch only traffic no roomful of humans could produce.
# All three are env-overridable so a busier-than-expected venue can be retuned
# without a rebuild.
CATALOG_LIMIT = os.getenv("CATALOG_RATE_LIMIT", "6000/minute")
NOTIFICATION_STREAM_LIMIT = os.getenv("NOTIFICATION_STREAM_RATE_LIMIT", "2000/minute")
CHECKOUT_LIMIT = os.getenv("CHECKOUT_RATE_LIMIT", "600/minute")

# SPEC-056 #7. `/user/*` mutations had no per-IP ceiling at all. Sized to the
# same rule as the rest of this file — one address may be a whole room, and the
# language switcher on that page writes here on every toggle — so this is the
# coarse "one scripted laptop" backstop, nothing finer.
#
# The actual brute-force defence for the password those endpoints now demand is
# NOT here: it is `cache.check_rate_limit` keyed on the account being attacked,
# in `routes/user._reauthenticate`. Guessing a password is an attack on one
# account from anywhere, so the counter belongs on the account, not the address.
ACCOUNT_LIMIT = os.getenv("ACCOUNT_RATE_LIMIT", "1000/minute")
