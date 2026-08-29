"""
CSRF protection for the admin console (double-submit cookie pattern).

The admin console authenticates via an httpOnly session cookie. Unlike the
user-facing API (which uses Authorization headers that browsers never auto-send),
the cookie IS auto-sent on every request — making the admin routes susceptible to
cross-site request forgery.

Defence: on login we generate a random CSRF token, store it in Redis keyed to the
session, and set it as a non-httpOnly cookie so the frontend JS can read it.
Every mutating admin request must echo the token back as an ``X-CSRF-Token``
header. An attacker on a different origin can't read the cookie (SameSite + CORS)
and therefore can't forge the header.
"""

import secrets

from fastapi import HTTPException, Request, Response

from cache import redis_client
from env import (
    ADMIN_COOKIE_NAME,
    ADMIN_COOKIE_PATH,
    ADMIN_SESSION_TTL,
    CSRF_COOKIE_NAME,
    CSRF_COOKIE_SAMESITE,
    CSRF_COOKIE_SECURE,
)

_CSRF_KEY = "csrf:"  # Redis key prefix: csrf:{session_id} -> token

_CSRF_HEADER = "X-CSRF-Token"


# ---------------------------------------------------------------------------
# Token lifecycle
# ---------------------------------------------------------------------------

def generate_csrf_token(session_id: str) -> str:
    """Create a CSRF token, store it in Redis, and return it."""
    token = secrets.token_urlsafe(32)
    redis_client.setex(f"{_CSRF_KEY}{session_id}", ADMIN_SESSION_TTL, token)
    return token


def set_csrf_cookie(response: Response, token: str) -> None:
    """Set the CSRF token as a readable (non-httpOnly) cookie."""
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=ADMIN_SESSION_TTL,
        httponly=False,  # JS must be able to read this
        secure=CSRF_COOKIE_SECURE,
        samesite=CSRF_COOKIE_SAMESITE,
        path=ADMIN_COOKIE_PATH,
    )


def clear_csrf(session_id: str | None, response: Response) -> None:
    """Delete the CSRF token from Redis and clear the cookie."""
    if session_id:
        redis_client.delete(f"{_CSRF_KEY}{session_id}")
    response.delete_cookie(key=CSRF_COOKIE_NAME, path=ADMIN_COOKIE_PATH)


# ---------------------------------------------------------------------------
# Verification dependency (used on the protected admin router)
# ---------------------------------------------------------------------------

async def verify_csrf_token(request: Request) -> None:
    """
    Verify that the ``X-CSRF-Token`` header matches the token stored in Redis
    for the current admin session. Raises 403 on mismatch or missing token.

    Safe (GET/HEAD/OPTIONS) methods are exempt — they must not cause side-effects
    and don't need CSRF protection.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    sid = request.cookies.get(ADMIN_COOKIE_NAME)
    if not sid:
        # No session cookie at all — verify_admin will reject this anyway.
        return

    expected = redis_client.get(f"{_CSRF_KEY}{sid}")
    if not expected:
        raise HTTPException(status_code=403, detail="CSRF token missing from server — please log in again")

    header_token = request.headers.get(_CSRF_HEADER)
    if not header_token or header_token != expected:
        raise HTTPException(status_code=403, detail="CSRF token validation failed")

