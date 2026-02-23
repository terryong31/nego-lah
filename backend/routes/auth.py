from fastapi import APIRouter, HTTPException, status
from schemas import UserSchema
from connector import admin_supabase
from cache import cache_session
from logger import logger

router = APIRouter(prefix="", tags=["Auth"])


@router.post('/login')
def login(user: UserSchema) -> dict:
    username = user.username
    password = user.password
    response = admin_supabase.auth.sign_in_with_password({
        "email": username,
        "password": password
    })
    if response:
        # Cache the session
        cache_session(response.user.id, response.session.access_token)
        return {"access_token": response.session.access_token, "token_type": "bearer"}
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unauthorized")


@router.post('/register')
def register(user: UserSchema) -> dict:
    username = user.username
    password = user.password
    response = admin_supabase.auth.sign_up({
        "email": username,
        "password": password
    })
    if response:
        return {"message": "User registered", "user_id": response.user.id}
    else:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Registration failed")


@router.get('/user/{user_id}/ban-status')
def get_ban_status(user_id: str) -> dict:
    """Check if a user is banned. Used by frontend AuthContext on login."""
    try:
        result = admin_supabase.table('user_profiles').select('is_banned').eq('id', user_id).execute()
        if result.data and len(result.data) > 0:
            return {"is_banned": result.data[0].get('is_banned', False)}
        return {"is_banned": False}  # Not in profiles table = not banned
    except Exception as e:
        logger.error(f"Error checking ban status: {e}")
        return {"is_banned": False}  # Default to not banned on error

