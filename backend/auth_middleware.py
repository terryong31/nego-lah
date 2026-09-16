"""
Auth middleware for JWT token validation.
Uses Supabase for verification with Redis caching for performance.
"""

import asyncio
import time

from fastapi import HTTPException, Request

from cache import (
    cache_ban_status,
    cache_token_user,
    get_cached_ban_status,
    get_cached_user_by_token,
)
from connector import admin_supabase
from core.jwt_auth import InvalidTokenError, TokenExpiredError, jwt_verifier
from logger import logger


def _is_user_banned(user_id: str) -> bool:
    """
    Check whether a user is banned, backed by a short-lived Redis cache so we
    don't hit the DB on every authenticated request. Fails open (treats the
    user as not banned) if the lookup errors, to avoid locking everyone out.
    """
    cached = get_cached_ban_status(user_id)
    if cached is not None:
        return cached

    try:
        res = (
            admin_supabase.table("user_profiles")
            .select("is_banned")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        banned = bool(res.data and res.data[0].get("is_banned"))
    except Exception as e:
        # Fail open: a ban lookup that errors must not lock every user out. But
        # it does mean a banned user gets through, so it is not a silent event.
        logger.warning(f"Ban lookup failed for {user_id}, treating as not banned: {e}")
        banned = False

    cache_ban_status(user_id, banned)
    return banned


async def _resolve_token_to_user_id(token: str) -> str:
    """Resolve a Bearer token to user_id via Redis cache or local cryptographic verification."""
    cached_user_id = await asyncio.to_thread(get_cached_user_by_token, token)
    if cached_user_id:
        return cached_user_id

    # SPEC-077 / TODO 65: If token is a JWT (3 dot parts), verify locally in microseconds
    if token.count(".") == 2:
        try:
            payload = jwt_verifier.verify(token)
            user_id = payload["sub"]
            exp = payload.get("exp")
            now = int(time.time())
            ttl = max(1, min(7200, exp - now)) if exp else 7200
            await asyncio.to_thread(cache_token_user, token, user_id, ttl)
            return user_id
        except TokenExpiredError as e:
            raise HTTPException(status_code=401, detail="Token expired") from e
        except InvalidTokenError as e:
            raise HTTPException(status_code=401, detail="Invalid token") from e

    # Fallback for mock test environments passing non-JWT dummy strings to fake_supabase.auth.get_user
    try:
        user_response = await asyncio.to_thread(admin_supabase.auth.get_user, token)
        if user_response and user_response.user:
            user_id = user_response.user.id
            await asyncio.to_thread(cache_token_user, token, user_id)
            return user_id
        raise HTTPException(status_code=401, detail="Invalid token")
    except HTTPException:
        raise
    except Exception as e:
        error_msg = str(e)
        if "expired" in error_msg.lower():
            raise HTTPException(status_code=401, detail="Token expired") from e
        raise HTTPException(status_code=401, detail="Invalid token") from e


async def verify_user_token(request: Request) -> str:
    """
    Validates Authorization header and returns user_id.

    Flow:
    1. Extract token from 'Authorization: Bearer <token>'
    2. Check Redis cache for token -> user_id mapping
    3. If not cached, verify cryptographically via local JWKS (no network call)
    4. Return user_id or raise 401
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    token = parts[1]
    user_id = await _resolve_token_to_user_id(token)

    # Block banned users from every authenticated endpoint.
    if await asyncio.to_thread(_is_user_banned, user_id):
        raise HTTPException(status_code=403, detail="Your account has been banned")

    return user_id


def get_user_id_from_body_or_token(body_user_id: str | None, token_user_id: str) -> str:
    """
    Validate that body user_id matches token user_id.
    This prevents users from sending requests on behalf of other users.
    """
    if body_user_id and body_user_id != token_user_id:
        raise HTTPException(
            status_code=403,
            detail="User ID mismatch: cannot act on behalf of another user"
        )
    return token_user_id


async def get_optional_user_id(request: Request) -> str | None:
    """Extract user_id from the Authorization header; return None if unauthenticated."""
    auth_header = request.headers.get("Authorization") if hasattr(request, "headers") else None
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    token = auth_header.split(" ", 1)[1]
    if not token:
        return None

    try:
        return await _resolve_token_to_user_id(token)
    except Exception as e:
        logger.debug(f"Optional token verification failed: {e}")
        return None


