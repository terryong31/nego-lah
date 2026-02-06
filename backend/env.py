import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
ADMIN_SUPABASE_KEY = os.getenv("ADMIN_SUPABASE_KEY")
USER_SUPABASE_KEY = os.getenv("USER_SUPABASE_KEY")

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
