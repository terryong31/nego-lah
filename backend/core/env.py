import os
from pathlib import Path

from dotenv import load_dotenv

# The backend's OWN .env — `backend/.env`, resolved from this file's package
# rather than its directory. This module used to live at `backend/env.py` and
# computed the path with `dirname(__file__)`; SPEC-092 moved it into `core/`
# without adjusting that, so it spent its life loading `backend/core/.env`,
# which has never existed (SPEC-097). Production never noticed — Infisical
# injects the variables directly — but local development without Infisical is
# the entire reason a `.env` exists.
#
# Still deliberately NOT `find_dotenv`: the tree is not walked, so the backend
# can never pick up a stray repo-root or frontend env file.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_FILE)

SUPABASE_URL = os.getenv("SUPABASE_URL")
ADMIN_SUPABASE_KEY = os.getenv("ADMIN_SUPABASE_KEY")
USER_SUPABASE_KEY = os.getenv("USER_SUPABASE_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

REDIS_URL = os.getenv("REDIS_URL")
if not REDIS_URL:
    redis_host = os.getenv("REDIS_HOST")
    redis_port = os.getenv("REDIS_PORT")
    redis_password = os.getenv("REDIS_PASSWORD")
    redis_username = os.getenv("REDIS_USERNAME", "default")
    redis_ssl = os.getenv("REDIS_SSL", "true").lower() == "true"

    if redis_host and redis_port and redis_password:
        protocol = "rediss" if redis_ssl else "redis"
        REDIS_URL = f"{protocol}://{redis_username}:{redis_password}@{redis_host}:{redis_port}"
    elif not os.getenv("VERCEL"):
        REDIS_URL = "redis://localhost:6379"

# Upper bound on the shared Redis connection pool, per worker process. Left
# unbounded, a burst of concurrent requests can open connections without limit;
# the ceiling here is sized for the 32-thread default executor `main.py`
# installs (`ASYNCIO_EXECUTOR_THREADS`) plus headroom.
REDIS_MAX_CONNECTIONS = int(os.getenv("REDIS_MAX_CONNECTIONS", "50"))

# Every request makes synchronous Redis round trips (rate limit, session, ban
# check). Without a socket timeout a network stall parks the calling thread
# forever, and with it, eventually, the whole worker (audit REL-1).
REDIS_SOCKET_TIMEOUT = float(os.getenv("REDIS_SOCKET_TIMEOUT", "2"))

# The loop's default executor is what `asyncio.to_thread` runs on. Python sizes
# it at min(32, cpu_count + 4) — five or six threads on a Lightsail box — which
# one slow dependency can exhaust. Sized explicitly in the lifespan.
ASYNCIO_EXECUTOR_THREADS = int(os.getenv("ASYNCIO_EXECUTOR_THREADS", "32"))

IS_PROD = (os.getenv("ENV") or "development").lower() in ("production", "prod")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET")
# Inbound mail (e.g. support@negolah.my) has no real mailbox yet — forward it
# to a real inbox instead of standing up a full mail server.
RESEND_FORWARD_TO = os.getenv("RESEND_FORWARD_TO")
RESEND_FORWARD_FROM = os.getenv("RESEND_FORWARD_FROM")
# Only these recipient addresses get forwarded. Inbound receiving is domain-wide
# (any address @negolah.my hits the webhook), so this allowlist keeps bounces/
# auto-replies to RESEND_FORWARD_FROM (and anything else unexpected) from being
# forwarded — which would otherwise risk a mail loop.
RESEND_ALLOWED_RECIPIENTS = {
    addr.strip().lower() for addr in os.getenv("RESEND_ALLOWED_RECIPIENTS", "").split(",") if addr.strip()
}

# SPEC-074: local dev email sink. When SMTP_HOST is set, every outbound email
# goes to that SMTP server (Mailpit in dev) instead of the Resend API —
# catch-all, instant, and nothing ever leaves the machine. Production never
# sets it, so the Resend path there is untouched. SMTP_PORT tolerates an
# empty-string override (present-but-falsy, the conftest pattern).
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT") or 1025)
SMTP_FROM = os.getenv("SMTP_FROM")

# SPEC-074 Phase 2: the admin inbox for operational alerts (sale alerts,
# human-handoff pings, sandbox-free receipt alerts). This used to be overloaded
# onto RESEND_FORWARD_TO — the inbound-mail forwarding target — which conflated
# two concerns. ADMIN_NOTIFY_EMAIL is the honest name; the Resend var remains
# the fallback so existing deployments keep working without a new secret.
ADMIN_NOTIFY_EMAIL = os.getenv("ADMIN_NOTIFY_EMAIL") or RESEND_FORWARD_TO

# Public URL of the frontend, used for Stripe redirect URLs etc.
# Defaults to the local dev server; set FRONTEND_URL=https://negolah.my in
# staging/production. Trailing slash is stripped so we can build paths safely.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")

# Public origin of this API, used to build the OAuth callback and the links in
# Supabase auth emails. Mirrors FRONTEND_URL's derivation rather than hardcoding
# a host, so a fork or a staging domain needs one variable, not two.
API_BASE_URL = os.getenv("API_BASE_URL") or (
    "https://api.negolah.my" if "negolah.my" in FRONTEND_URL else "http://localhost:8000"
)

# Admin API namespace. Fixed, not secret — the admin endpoints are protected by
# 2FA + the verify_admin session gate + rate limiting, not by hiding the path.
ADMIN_PREFIX = "/admin"

_is_https = FRONTEND_URL.startswith("https://")

_default_cookie_domain = ".negolah.my" if "negolah.my" in FRONTEND_URL else None

# Admin session / 2FA configuration.
ADMIN_COOKIE_NAME = os.getenv("ADMIN_COOKIE_NAME", "admin_sid")
ADMIN_COOKIE_SECURE = os.getenv("ADMIN_COOKIE_SECURE", "true" if _is_https else "false").lower() == "true" and _is_https
ADMIN_COOKIE_SAMESITE = os.getenv("ADMIN_COOKIE_SAMESITE", "lax").lower()
ADMIN_COOKIE_PATH = os.getenv("ADMIN_COOKIE_PATH", "/")
ADMIN_COOKIE_DOMAIN = os.getenv("ADMIN_COOKIE_DOMAIN", _default_cookie_domain)
ADMIN_SESSION_TTL = int(os.getenv("ADMIN_SESSION_TTL", "7200"))  # sliding session, seconds
ADMIN_PREAUTH_TTL = int(os.getenv("ADMIN_PREAUTH_TTL", "300"))  # 2FA pre-auth handle, seconds

# Buyer session (SPEC-093). The same opaque-sid-in-Redis model as the admin
# cookie above, under its own names so an admin who is also a buyer holds both
# sessions in one browser without either clobbering the other.
#
# SameSite=lax, not strict, and deliberately: the Stripe return to
# /checkout/success and every Supabase email link are top-level cross-site GET
# navigations. Strict withholds the cookie on exactly those, which arrives at
# the app as a logout the moment someone pays or confirms an address.
USER_COOKIE_NAME = os.getenv("USER_COOKIE_NAME", "nl_sid")
USER_COOKIE_SECURE = os.getenv("USER_COOKIE_SECURE", "true" if _is_https else "false").lower() == "true" and _is_https
USER_COOKIE_SAMESITE = os.getenv("USER_COOKIE_SAMESITE", "lax").lower()
USER_COOKIE_PATH = os.getenv("USER_COOKIE_PATH", "/")
USER_COOKIE_DOMAIN = os.getenv("USER_COOKIE_DOMAIN", _default_cookie_domain)
# 30 days, sliding. Long on purpose: prod's managed Redis (Upstash) runs
# `noeviction` and rejects writes at the cap instead of dropping keys, so a long
# TTL costs nothing in eviction — what it buys is not asking people to sign in
# again every week. See ADR-0028.
USER_SESSION_TTL = int(os.getenv("USER_SESSION_TTL", str(30 * 24 * 3600)))
# The buyer's readable CSRF cookie, and the short-lived PKCE holder that carries
# the OAuth code verifier across the Google -> Supabase -> API redirect chain.
USER_CSRF_COOKIE_NAME = os.getenv("USER_CSRF_COOKIE_NAME", "nl_csrf")
USER_PKCE_COOKIE_NAME = os.getenv("USER_PKCE_COOKIE_NAME", "nl_pkce")
USER_PKCE_TTL = int(os.getenv("USER_PKCE_TTL", "600"))

# CSRF double-submit cookie configuration (admin console only).
CSRF_COOKIE_NAME = os.getenv("CSRF_COOKIE_NAME", "csrf_token")
CSRF_COOKIE_SECURE = os.getenv("CSRF_COOKIE_SECURE", "true" if _is_https else "false").lower() == "true" and _is_https
CSRF_COOKIE_SAMESITE = os.getenv("CSRF_COOKIE_SAMESITE", "lax").lower()
CSRF_COOKIE_DOMAIN = os.getenv("CSRF_COOKIE_DOMAIN", _default_cookie_domain)

# Supabase Storage bucket for item images and avatars.
# Must match an existing bucket in your Supabase project.
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "images")
