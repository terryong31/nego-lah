"""
Auth middleware for JWT token validation.
Uses Supabase for verification with Redis caching for performance.
"""
from fastapi import HTTPException, Request
from typing import Optional
from connector import admin_supabase
from cache import get_cached_user_by_token, cache_token_user


async def verify_user_token(request: Request) -> str:
    """
    Validates Authorization header and returns user_id.
    
    Flow:
    1. Extract token from 'Authorization: Bearer <token>'
    2. Check Redis cache for token -> user_id mapping
    3. If not cached, validate with Supabase and cache result
    4. Return user_id or raise 401
    """
    # Extract Authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    # Parse Bearer token
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    
    token = parts[1]
    
    # Check Redis cache first
    cached_user_id = get_cached_user_by_token(token)
    if cached_user_id:
        return cached_user_id
    
    # Validate with Supabase
    try:
        user_response = admin_supabase.auth.get_user(token)
        if user_response and user_response.user:
            user_id = user_response.user.id
            # Cache the token -> user_id mapping
            cache_token_user(token, user_id)
            return user_id
        else:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception as e:
        # Handle Supabase auth errors
        error_msg = str(e)
        if "expired" in error_msg.lower():
            raise HTTPException(status_code=401, detail="Token expired")
        raise HTTPException(status_code=401, detail="Invalid token")


def get_user_id_from_body_or_token(body_user_id: Optional[str], token_user_id: Optional[str]) -> str:
    """
    Validate that body user_id matches token user_id.
    This prevents users from sending requests on behalf of other users.
    """
    if not token_user_id:
        # If no token, only allow if body_user_id is a guest
        if body_user_id and body_user_id.startswith("guest-"):
            return body_user_id
        raise HTTPException(status_code=401, detail="Authentication required")
        
    if body_user_id and body_user_id != token_user_id:
        raise HTTPException(
            status_code=403, 
            detail="User ID mismatch: cannot act on behalf of another user"
        )
    return token_user_id


async def verify_user_token_optional(request: Request) -> Optional[str]:
    """
    Same as verify_user_token but returns None if no header/invalid instead of raising 401.
    Used for endpoints that support both authenticated users and guests.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None
        
    try:
        return await verify_user_token(request)
    except HTTPException:
        return None

