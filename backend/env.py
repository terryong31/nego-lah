import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
ADMIN_SUPABASE_KEY = os.getenv("ADMIN_SUPABASE_KEY")
USER_SUPABASE_KEY = os.getenv("USER_SUPABASE_KEY")
REDIS_URL = os.getenv("REDIS_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
