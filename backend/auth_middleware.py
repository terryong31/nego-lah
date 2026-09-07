"""
Auth middleware for JWT token validation.
Uses Supabase for verification with Redis caching for performance.
"""

import asyncio

from fastapi import HTTPException, Request

from cache import (
    cache_ban_status,
    cache_token_user,
    get_cached_ban_status,
    get_cached_user_by_token,
)
from connector import admin_supabase
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

    # Check Redis cache first. The client is synchronous, and this runs on
    # every authenticated request, so it goes through a thread for the same
    # reason the Supabase call below does (SPEC-023): an `async def` dependency
    # runs on the event loop, and a slow Redis — a co-located one under CPU
    # pressure, say — would otherwise stall every other request on this worker.
    cached_user_id = await asyncio.to_thread(get_cached_user_by_token, token)
    if cached_user_id:
        user_id = cached_user_id
    else:
        # Validate with Supabase. FastAPI runs `def` *endpoints* in a threadpool
        # but always runs `async def` *dependencies* on the event loop, so this
        # synchronous round trip would stall every other in-flight request on
        # this worker — on every authenticated endpoint in the API.
        try:
            user_response = await asyncio.to_thread(admin_supabase.auth.get_user, token)
            if user_response and user_response.user:
                user_id = user_response.user.id
                # Cache the token -> user_id mapping
                cache_token_user(token, user_id)
            else:
                raise HTTPException(status_code=401, detail="Invalid token")
        except HTTPException:
            raise
        except Exception as e:
            # Handle Supabase auth errors
            error_msg = str(e)
            if "expired" in error_msg.lower():
                raise HTTPException(status_code=401, detail="Token expired") from e
            raise HTTPException(status_code=401, detail="Invalid token") from e

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
    """Extract user_id from Authorization header or ?token= if present; return None if unauthenticated."""
    auth_header = request.headers.get("Authorization") if hasattr(request, "headers") else None
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    if not token and hasattr(request, "query_params"):
        token = request.query_params.get("token")
    if not token:
        return None

    try:
        cached_user_id = await asyncio.to_thread(get_cached_user_by_token, token)
        if cached_user_id:
            return cached_user_id
        user_response = await asyncio.to_thread(admin_supabase.auth.get_user, token)
        if user_response and user_response.user:
            uid = user_response.user.id
            cache_token_user(token, uid)
            return uid
    except Exception as e:
        # An unusable token is a 401, not a 500 — but a *broken* Supabase looks
        # identical from here, so leave a trace to tell them apart.
        logger.debug(f"Token verification failed: {e}")
        return None
    return None


