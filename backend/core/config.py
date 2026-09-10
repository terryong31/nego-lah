import os
from pathlib import Path

from dotenv import load_dotenv

# Scoped .env loading
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
ADMIN_SUPABASE_KEY = os.getenv("ADMIN_SUPABASE_KEY")
# No fallback to ADMIN_SUPABASE_KEY (SPEC-051, re-applied here by SPEC-056 #8):
# an unset anon key must fail closed, never silently promote client-facing reads
# to service-role privileges that bypass RLS.
USER_SUPABASE_KEY = os.getenv("USER_SUPABASE_KEY") or os.getenv("SUPABASE_KEY")
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

# AI & LLM Providers
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8001/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "mlx-community/Qwen3.6-35B-A3B-4bit")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "dummy-local-key")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto")

# Payments & Stripe
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Cloudflare Turnstile
TURNSTILE_SITE_KEY = os.getenv("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY", "")

# Email & Resend
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_WEBHOOK_SECRET = os.getenv("RESEND_WEBHOOK_SECRET")
RESEND_FORWARD_TO = os.getenv("RESEND_FORWARD_TO")
RESEND_FORWARD_FROM = os.getenv("RESEND_FORWARD_FROM")
RESEND_ALLOWED_RECIPIENTS = {
    addr.strip().lower()
    for addr in os.getenv("RESEND_ALLOWED_RECIPIENTS", "").split(",")
    if addr.strip()
}

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
ADMIN_PREFIX = "/admin"

_is_https = FRONTEND_URL.startswith("https://")

_default_cookie_domain = ".negolah.my" if "negolah.my" in FRONTEND_URL else None

ADMIN_COOKIE_NAME = os.getenv("ADMIN_COOKIE_NAME", "admin_sid")
ADMIN_COOKIE_SECURE = (
    os.getenv("ADMIN_COOKIE_SECURE", "true" if _is_https else "false").lower() == "true"
    and _is_https
)
ADMIN_COOKIE_SAMESITE = os.getenv("ADMIN_COOKIE_SAMESITE", "lax").lower()
ADMIN_COOKIE_PATH = os.getenv("ADMIN_COOKIE_PATH", "/")
ADMIN_COOKIE_DOMAIN = os.getenv("ADMIN_COOKIE_DOMAIN", _default_cookie_domain)
ADMIN_SESSION_TTL = int(os.getenv("ADMIN_SESSION_TTL", "7200"))
ADMIN_PREAUTH_TTL = int(os.getenv("ADMIN_PREAUTH_TTL", "300"))

CSRF_COOKIE_NAME = os.getenv("CSRF_COOKIE_NAME", "csrf_token")
CSRF_COOKIE_SECURE = (
    os.getenv("CSRF_COOKIE_SECURE", "true" if _is_https else "false").lower() == "true"
    and _is_https
)
CSRF_COOKIE_SAMESITE = os.getenv("CSRF_COOKIE_SAMESITE", "lax").lower()
CSRF_COOKIE_DOMAIN = os.getenv("CSRF_COOKIE_DOMAIN", _default_cookie_domain)

STORAGE_BUCKET = os.getenv("STORAGE_BUCKET", "images")
