"""
Admin authentication using Supabase instead of SQLite.
"""
import bcrypt
from connector import admin_supabase


def hash_password(password: str) -> str:
    """Hash password with bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def verify_admin(username: str, password: str) -> bool:
    """Verify admin credentials against Supabase."""
    try:
        result = admin_supabase.table('admin_users').select('password_hash').eq('username', username).single().execute()
        
        if not result.data:
            return False
        
        stored_hash = result.data.get('password_hash')
        return verify_password(password, stored_hash)
    except Exception as e:
        print(f"Admin auth error: {e}")
        return False


def create_admin(username: str, password: str) -> bool:
    """Create a new admin user."""
    try:
        password_hash = hash_password(password)
        admin_supabase.table('admin_users').insert({
            'username': username,
            'password_hash': password_hash
        }).execute()
        return True
    except Exception as e:
        print(f"Create admin error: {e}")
        return False
