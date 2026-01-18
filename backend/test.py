import supabase
from env import SUPABASE_URL, USER_SUPABASE_KEY, ADMIN_SUPABASE_KEY

try:
    user_supabase = supabase.create_client(SUPABASE_URL, USER_SUPABASE_KEY)
    admin_supabase = supabase.create_client(SUPABASE_URL, ADMIN_SUPABASE_KEY)

    try:
        response = user_supabase.table("items").select("*").execute()
        print(response.data)
    except Exception as e:
        print(f"An error has occured! Error: {e}")
except Exception as e:
    print(f"An error has occured! Error: {e}")