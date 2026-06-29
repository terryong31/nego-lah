import os
from dotenv import load_dotenv

# Load the backend's OWN .env, scoped to this directory by design.
# We deliberately do NOT walk up the tree (no find_dotenv) so the backend never
# picks up a stray repo-root or frontend env file — backend and frontend each
# own a distinct .env.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Public URL of the frontend, used for Stripe redirect URLs etc.
# Defaults to the local dev server; set FRONTEND_URL=https://negolah.my in
# staging/production. Trailing slash is stripped so we can build paths safely.
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")

# Admin API namespace. Fixed, not secret — the admin endpoints are protected by
# 2FA + the verify_admin session gate + rate limiting, not by hiding the path.
ADMIN_PREFIX = "/admin"

# Admin session / 2FA configuration.
ADMIN_COOKIE_NAME = os.getenv("ADMIN_COOKIE_NAME", "admin_sid")
ADMIN_COOKIE_SECURE = os.getenv("ADMIN_COOKIE_SECURE", "true").lower() == "true"
# "strict" is safest and requires the admin UI + API to be same-site (same
# registrable domain; ports/subdomains are fine). Use "none" only if the admin UI
# and API live on different domains (then ADMIN_COOKIE_SECURE must be true).
ADMIN_COOKIE_SAMESITE = os.getenv("ADMIN_COOKIE_SAMESITE", "strict").lower()
# Cookie Path. Keep "/" when the backend sits behind a reverse proxy that strips a
# path prefix (e.g. Caddy strips /api before forwarding): the browser sees the full
# /api/admin/... URL, so a cookie scoped to the backend's internal /admin path would
# never be sent back. "/" sidesteps the mismatch.
ADMIN_COOKIE_PATH = os.getenv("ADMIN_COOKIE_PATH", "/")
ADMIN_SESSION_TTL = int(os.getenv("ADMIN_SESSION_TTL", "7200"))  # sliding session, seconds
ADMIN_PREAUTH_TTL = int(os.getenv("ADMIN_PREAUTH_TTL", "300"))   # 2FA pre-auth handle, seconds

# Supabase Storage bucket for item images and avatars.
# Must match an existing bucket in your Supabase project.
STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "images")
