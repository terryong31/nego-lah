from fastapi import APIRouter, HTTPException, status
from schemas import UserSchema
from connector import admin_supabase
from cache import cache_session

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
