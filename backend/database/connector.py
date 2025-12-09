import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client, Client
import os
from environmental.env import SUPABASE_URL, USER_SUPABASE_KEY, ADMIN_SUPABASE_KEY

user_supabase: Client = create_client(supabase_url=SUPABASE_URL, supabase_key=USER_SUPABASE_KEY)
admin_supabase: Client = create_client(supabase_url=SUPABASE_URL, supabase_key=ADMIN_SUPABASE_KEY)