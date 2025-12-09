import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
SUPABASE_URL = os.getenv("SUPABASE_URL")
ADMIN_SUPABASE_KEY = os.getenv("ADMIN_SUPABASE_KEY")
USER_SUPABASE_KEY = os.getenv("USER_SUPABASE_KEY")