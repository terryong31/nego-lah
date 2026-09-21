"""
CSRF protection for cookie-authenticated sessions (double-submit cookie pattern).

Both the admin console and — since SPEC-093 — the buyer app authenticate with an
httpOnly session cookie. A cookie is auto-sent by the browser on cross-site
requests, which is exactly what an ``Authorization`` header is not: moving the
buyer off bearer tokens is what creates the CSRF exposure this module closes.

Defence: on login we generate a random CSRF token, store it in Redis keyed to the
session, and set it as a non-httpOnly cookie so the frontend JS can read it.
Every mutating request must echo the token back as an ``X-CSRF-Token`` header. An
attacker on a different origin can't read the cookie (SameSite + CORS) and
therefore can't forge the header.

The two surfaces are separate `CsrfScope`s rather than one shared token. An
operator is usually signed in as both an admin and a buyer in the same browser,
on the same registrable domain — one cookie name would mean whichever session
authenticated last silently invalidated the other's token.
"""

import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response

from core.cache import redis_client
from core.env import (
    ADMIN_COOKIE_NAME,
    ADMIN_COOKIE_PATH,
    ADMIN_SESSION_TTL,
    CSRF_COOKIE_DOMAIN,
    CSRF_COOKIE_NAME,
    CSRF_COOKIE_SAMESITE,
    CSRF_COOKIE_SECURE,
    USER_COOKIE_NAME,
    USER_CSRF_COOKIE_NAME,
    USER_SESSION_TTL,
)

_CSRF_HEADER = "X-CSRF-Token"


@dataclass(frozen=True)
class CsrfScope:
    """One session surface's CSRF binding.

    `session_cookie` is the httpOnly cookie whose value keys the Redis entry, so
    a token is only ever valid for the session it was minted for.
    """

    cookie_name: str
    session_cookie: str
    redis_prefix: str
    ttl: int


ADMIN_SCOPE = CsrfScope(
    cookie_name=CSRF_COOKIE_NAME,
    session_cookie=ADMIN_COOKIE_NAME,
    redis_prefix="csrf:",
    ttl=ADMIN_SESSION_TTL,
)

USER_SCOPE = CsrfScope(
    cookie_name=USER_CSRF_COOKIE_NAME,
    session_cookie=USER_COOKIE_NAME,
    redis_prefix="ucsrf:",
    ttl=USER_SESSION_TTL,
)


# ---------------------------------------------------------------------------
# Token lifecycle
# ---------------------------------------------------------------------------


def generate_csrf_token(session_id: str, scope: CsrfScope = ADMIN_SCOPE) -> str:
    """Create a CSRF token, store it in Redis, and return it."""
    token = secrets.token_urlsafe(32)
    redis_client.setex(f"{scope.redis_prefix}{session_id}", scope.ttl, token)
    return token


def set_csrf_cookie(response: Response, token: str, scope: CsrfScope = ADMIN_SCOPE) -> None:
    """Set the CSRF token as a readable (non-httpOnly) cookie."""
    response.set_cookie(
        key=scope.cookie_name,
        value=token,
        max_age=scope.ttl,
        httponly=False,  # JS must be able to read this
        secure=CSRF_COOKIE_SECURE,
        samesite=CSRF_COOKIE_SAMESITE,
        path=ADMIN_COOKIE_PATH,
        domain=CSRF_COOKIE_DOMAIN,
    )


def clear_csrf(session_id: str | None, response: Response, scope: CsrfScope = ADMIN_SCOPE) -> None:
    """Delete the CSRF token from Redis and clear the cookie."""
    if session_id:
        redis_client.delete(f"{scope.redis_prefix}{session_id}")
    response.delete_cookie(key=scope.cookie_name, path=ADMIN_COOKIE_PATH, domain=CSRF_COOKIE_DOMAIN)


# ---------------------------------------------------------------------------
# Verification dependency (used on the protected routers)
# ---------------------------------------------------------------------------


def _verify(request: Request, scope: CsrfScope) -> None:
    """
    Verify that the ``X-CSRF-Token`` header matches the token stored in Redis
    for the current session. Raises 403 on mismatch or missing token.

    Safe (GET/HEAD/OPTIONS) methods are exempt — they must not cause side-effects
    and don't need CSRF protection.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return

    sid = request.cookies.get(scope.session_cookie)
    if not sid:
        # No session cookie at all — this request is either unauthenticated or
        # bearer-authenticated. A bearer token is not auto-sent by the browser,
        # so it is not forgeable cross-site and needs no CSRF token; the auth
        # dependency is what decides whether it is allowed through.
        return

    expected = redis_client.get(f"{scope.redis_prefix}{sid}")
    if not expected:
        raise HTTPException(status_code=403, detail="CSRF token missing from server — please log in again")

    header_token = request.headers.get(_CSRF_HEADER)
    if not header_token or not secrets.compare_digest(header_token, expected):
        raise HTTPException(status_code=403, detail="CSRF token validation failed")


async def verify_csrf_token(request: Request) -> None:
    """CSRF gate for the admin console."""
    _verify(request, ADMIN_SCOPE)


async def verify_user_csrf_token(request: Request) -> None:
    """CSRF gate for the buyer app (SPEC-093)."""
    _verify(request, USER_SCOPE)
