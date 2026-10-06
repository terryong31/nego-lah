"""
Buyer sessions: the Supabase tokens live here, never in the browser (SPEC-093).

The browser holds one opaque, random session id in an httpOnly cookie. This
module holds the Supabase access and refresh tokens that id stands for, in Redis,
and hands back a `user_id` on demand. Nothing a script can read in the page is
worth anything against the API.

This is the admin model from SPEC-018 pointed at the buyer app — same opaque sid,
same instant revocation by deleting a key, same double-submit CSRF token — with
one addition the admin surface never needed: the Supabase access token expires
hourly, so the refresh has to happen server-side, and it has to happen exactly
once no matter how many tabs ask at the same moment.
"""

import base64
import hashlib
import json
import secrets
import time

import httpx
from fastapi import Request, Response
from supabase_auth.errors import AuthApiError, AuthRetryableError

from core.cache import redis_client
from core.connector import new_user_client
from core.csrf import USER_SCOPE, clear_csrf, generate_csrf_token, set_csrf_cookie
from core.env import (
    USER_COOKIE_DOMAIN,
    USER_COOKIE_NAME,
    USER_COOKIE_PATH,
    USER_COOKIE_SAMESITE,
    USER_COOKIE_SECURE,
    USER_PKCE_COOKIE_NAME,
    USER_PKCE_TTL,
    USER_SESSION_TTL,
)
from core.logger import logger

_SESS_KEY = "user:sess:"
_LOCK_KEY = "user:refreshlock:"

# Refresh this far ahead of expiry, so a request that arrives mid-flight is not
# the one that discovers the token is already dead.
_REFRESH_SKEW = 60
# How long a refresh may hold the lock before another worker assumes it died.
_LOCK_TTL = 15
# A loser of the lock race waits this long, in these steps, for the winner's
# result to land in Redis before giving up and using what it has.
_WAIT_STEP = 0.05
_WAIT_STEPS = 60

# Re-sliding the cookie TTL on literally every request would be a Redis write per
# API call for no benefit. Slide only once the session has aged an hour.
_SLIDE_AFTER = 3600


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def _key(sid: str) -> str:
    return f"{_SESS_KEY}{sid}"


def create_session(user_id: str, access_token: str, refresh_token: str, expires_at: int) -> str:
    """Persist a Supabase session behind a fresh opaque id and return the id."""
    sid = secrets.token_urlsafe(32)
    redis_client.setex(
        _key(sid),
        USER_SESSION_TTL,
        json.dumps(
            {
                "user_id": user_id,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": int(expires_at or 0),
            }
        ),
    )
    return sid


def read_session(sid: str) -> dict | None:
    """The stored session, or None if the id is unknown, expired, or revoked."""
    if not sid:
        return None
    raw = redis_client.get(_key(sid))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        # A corrupt entry is not a session. Drop it rather than 500 on every
        # request the browser makes with that cookie.
        redis_client.delete(_key(sid))
        return None


def _save_session(sid: str, data: dict) -> None:
    redis_client.setex(_key(sid), USER_SESSION_TTL, json.dumps(data))


def destroy_session(sid: str | None) -> None:
    """Revoke a session. The next request carrying this cookie is anonymous."""
    if sid:
        redis_client.delete(_key(sid))
        redis_client.delete(f"{USER_SCOPE.redis_prefix}{sid}")


# ---------------------------------------------------------------------------
# Refresh — single-flight
# ---------------------------------------------------------------------------


def _refresh(sid: str, session: dict) -> dict:
    """Exchange the refresh token for a new access token, at most once per session.

    Supabase rotates the refresh token on every use and only tolerates a reuse of
    the previous one inside a short grace window. Without a lock, four tabs
    waking together send four refreshes, three of them present a token that has
    just been rotated away, and the buyer is signed out for having too many tabs
    open. The winner writes the new pair; the losers read it back.
    """
    lock = f"{_LOCK_KEY}{sid}"
    if not redis_client.set(lock, "1", ex=_LOCK_TTL, nx=True):
        for _ in range(_WAIT_STEPS):
            time.sleep(_WAIT_STEP)
            fresh = read_session(sid)
            if fresh is None:
                # Signed out (or revoked) while we waited.
                return session
            if fresh.get("expires_at", 0) - time.time() > _REFRESH_SKEW:
                return fresh
        # The winner never landed a result. Fall through with what we have: the
        # token may still have seconds left, and if it doesn't, the request 401s
        # and the client re-authenticates — which is strictly better than every
        # waiting request piling a second refresh onto a struggling upstream.
        return session

    try:
        client = new_user_client()
        result = client.auth.refresh_session(session["refresh_token"])
        new = getattr(result, "session", None)
        if not new or not getattr(new, "access_token", None):
            raise ValueError("Supabase returned no session on refresh")

        session = {
            **session,
            "access_token": new.access_token,
            "refresh_token": getattr(new, "refresh_token", session["refresh_token"]),
            "expires_at": int(getattr(new, "expires_at", 0) or 0),
        }
        _save_session(sid, session)
        return session
    except Exception as e:
        # A timeout or a 5xx never reached the point of spending the refresh
        # token, so revoking would sign out every buyer whose hourly token
        # happened to expire during a Supabase Auth blip (audit REL-3). Keep
        # the session; the next request tries again.
        if _is_transient(e):
            logger.warning(f"Session refresh for {session.get('user_id')} hit a transient error; keeping it: {e}")
            return session
        # Anything else is a dead session: the refresh token is single-use and
        # was rejected. Revoke, so the buyer is asked to sign in once rather
        # than served 401s forever.
        logger.info(f"Session refresh failed for {session.get('user_id')}; revoking: {e}")
        destroy_session(sid)
        return {}
    finally:
        redis_client.delete(lock)


def _is_transient(error: Exception) -> bool:
    if isinstance(error, (AuthRetryableError, httpx.TransportError)):
        return True
    return isinstance(error, AuthApiError) and (error.status or 0) >= 500


def resolve_session(sid: str) -> dict | None:
    """The live session for this cookie, refreshed if it is about to expire."""
    session = read_session(sid)
    if not session:
        return None

    expires_at = session.get("expires_at", 0)
    if expires_at and expires_at - time.time() <= _REFRESH_SKEW:
        session = _refresh(sid, session)
        if not session:
            return None

    ttl = redis_client.ttl(_key(sid))
    if isinstance(ttl, int) and 0 < ttl < USER_SESSION_TTL - _SLIDE_AFTER:
        redis_client.expire(_key(sid), USER_SESSION_TTL)

    return session


def resolve_user_id(sid: str) -> str | None:
    """The user this cookie authenticates, or None."""
    session = resolve_session(sid)
    return session.get("user_id") if session else None


def access_token_for(sid: str) -> str | None:
    """The live Supabase access token, for the few server-side calls that must act
    AS the user (`new_user_client().postgrest.auth(...)`). It never leaves the
    backend — nothing returns this to the browser."""
    session = resolve_session(sid)
    return session.get("access_token") if session else None


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------


def set_session_cookies(response: Response, sid: str) -> str:
    """Attach the session cookie and a matching CSRF token. Returns the token."""
    response.set_cookie(
        key=USER_COOKIE_NAME,
        value=sid,
        max_age=USER_SESSION_TTL,
        httponly=True,
        secure=USER_COOKIE_SECURE,
        samesite=USER_COOKIE_SAMESITE,
        path=USER_COOKIE_PATH,
        domain=USER_COOKIE_DOMAIN,
    )
    token = generate_csrf_token(sid, USER_SCOPE)
    set_csrf_cookie(response, token, USER_SCOPE)
    return token


def clear_session_cookies(request: Request, response: Response) -> None:
    """End the session on the server and remove both cookies from the browser."""
    sid = request.cookies.get(USER_COOKIE_NAME)
    destroy_session(sid)
    response.delete_cookie(key=USER_COOKIE_NAME, path=USER_COOKIE_PATH, domain=USER_COOKIE_DOMAIN)
    clear_csrf(sid, response, USER_SCOPE)


def open_session_for(response: Response, supabase_session) -> str:
    """Store a fresh Supabase session and hand the browser its opaque id."""
    user = getattr(supabase_session, "user", None)
    user_id = getattr(user, "id", None)
    if not user_id:
        raise ValueError("Supabase session carries no user")

    sid = create_session(
        user_id=user_id,
        access_token=supabase_session.access_token,
        refresh_token=getattr(supabase_session, "refresh_token", ""),
        expires_at=int(getattr(supabase_session, "expires_at", 0) or 0),
    )
    set_session_cookies(response, sid)
    return sid


# ---------------------------------------------------------------------------
# PKCE — carrying the code verifier across the OAuth redirect chain
# ---------------------------------------------------------------------------


def new_pkce_pair() -> tuple[str, str]:
    """A (verifier, challenge) pair for Supabase's PKCE authorization flow."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def set_pkce_cookie(response: Response, verifier: str, redirect_to: str) -> None:
    """Stash the verifier for the duration of the round trip.

    It goes in a cookie rather than Redis-keyed-by-state because GoTrue owns the
    `state` parameter on the authorize URL and will not round-trip one of ours —
    the cookie is the only thing guaranteed to come back with the callback. It is
    httpOnly and lives ten minutes; the return path consumes it.
    """
    response.set_cookie(
        key=USER_PKCE_COOKIE_NAME,
        value=json.dumps({"v": verifier, "r": redirect_to}),
        max_age=USER_PKCE_TTL,
        httponly=True,
        secure=USER_COOKIE_SECURE,
        samesite=USER_COOKIE_SAMESITE,
        path=USER_COOKIE_PATH,
        domain=USER_COOKIE_DOMAIN,
    )


def clear_pkce_cookie(response: Response) -> None:
    """Expire the PKCE cookie. The verifier is good for exactly one callback, so
    the return path drops it whether the exchange succeeded or not."""
    response.delete_cookie(key=USER_PKCE_COOKIE_NAME, path=USER_COOKIE_PATH, domain=USER_COOKIE_DOMAIN)
