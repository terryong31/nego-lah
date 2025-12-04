import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connector import supabase
import bcrypt
from datetime import datetime

def authentication(username: str, password: str) -> bool:
    response = supabase.table('credentials').select("password").eq("username", username).execute()
    if not response.data:
        return False
    stored_hash = response.data[0]["password"]
    if isinstance(stored_hash, str):
        stored_hash = stored_hash.encode("utf-8")
    if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
        return True
    else:
        return False
    
def register_new_user(username: str, password: str) -> bool:
    response = supabase.table('credentials').select('username').eq("username", username).execute()
    
    if response.data:
        return False

    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_password = bcrypt.hashpw(pwd_bytes, salt)
    hashed_password_str = hashed_password.decode('utf-8')
    try:
        supabase.table('credentials').insert({'username' : username, 'password': hashed_password_str, 'created_at': datetime.now().isoformat()}).execute()
        return True
    except Exception as e:
        print(f"An error has occured: {e}")
        return False