"""
Tests for domains/identity/user_session.py — SPEC-093.

The buyer's Supabase tokens live in Redis behind an opaque cookie id. What is
worth testing is everything that could put a token back in the browser's reach,
and everything that could sign a buyer out who did nothing wrong:

- the cookie is httpOnly, and the id is not the token
- a revoked session stops resolving immediately
- an expiring access token is refreshed server-side, exactly once under
  concurrency (Supabase rotates refresh tokens; a second attempt spends a token
  that has already been rotated away and kills the session)
- a refresh that genuinely fails revokes rather than serving 401s forever

`new_user_client` is bound at import time in user_session, so it is patched
there. Redis is the in-memory fake, flushed between tests by conftest.
"""

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import Response
from supabase_auth.errors import AuthApiError, AuthRetryableError

import domains.identity.user_session as user_session
from core.cache import redis_client
from core.env import USER_COOKIE_NAME, USER_SESSION_TTL
from domains.identity.user_session import (
    _SESS_KEY,
    _SIDS_KEY,
    access_token_for,
    create_session,
    destroy_session,
    new_pkce_pair,
    open_session_for,
    read_session,
    resolve_session,
    resolve_user_id,
    revoke_other_sessions,
    set_session_cookies,
)


def make_supabase_session(user_id="user-1", access="access-1", refresh="refresh-1", expires_at=None):
    return SimpleNamespace(
        access_token=access,
        refresh_token=refresh,
        expires_at=int(expires_at if expires_at is not None else time.time() + 3600),
        user=SimpleNamespace(id=user_id, email="buyer@example.com", user_metadata={}),
    )


def set_cookie_headers(response: Response):
    return [v.decode() for k, v in response.raw_headers if k == b"set-cookie"]


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_create_session_stores_tokens_server_side_and_returns_an_opaque_id():
    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 3600)

    assert sid not in ("access-1", "refresh-1")
    assert "access-1" not in sid

    stored = json.loads(redis_client.get(f"{_SESS_KEY}{sid}"))
    assert stored["user_id"] == "user-1"
    assert stored["access_token"] == "access-1"
    assert stored["refresh_token"] == "refresh-1"


def test_read_session_returns_none_for_unknown_or_revoked_ids():
    assert read_session("") is None
    assert read_session("never-existed") is None

    sid = create_session("user-1", "a", "r", int(time.time()) + 3600)
    destroy_session(sid)
    assert read_session(sid) is None


def test_a_corrupt_entry_is_dropped_rather_than_raising():
    redis_client.setex(f"{_SESS_KEY}bad", 60, "{not json")
    assert read_session("bad") is None
    assert redis_client.get(f"{_SESS_KEY}bad") is None


def test_destroy_session_also_drops_the_csrf_token():
    sid = create_session("user-1", "a", "r", int(time.time()) + 3600)
    response = Response()
    set_session_cookies(response, sid)
    assert redis_client.get(f"ucsrf:{sid}") is not None

    destroy_session(sid)
    assert redis_client.get(f"ucsrf:{sid}") is None


# ---------------------------------------------------------------------------
# Per-user index — a password change has to find every device (SPEC-110)
# ---------------------------------------------------------------------------


def _live(sid: str) -> bool:
    return redis_client.get(f"{_SESS_KEY}{sid}") is not None


def test_create_session_indexes_the_sid_under_its_user():
    sid = create_session("user-1", "a", "r", int(time.time()) + 3600)
    assert sid in redis_client.zrangebyscore(f"{_SIDS_KEY}user-1", 0, time.time() + 1)


def test_revoke_other_sessions_keeps_the_caller_and_other_users():
    expires = int(time.time()) + 3600
    phone, laptop, stolen = (create_session("user-1", "a", "r", expires) for _ in range(3))
    someone_else = create_session("user-2", "a", "r", expires)
    set_session_cookies(Response(), stolen)

    assert revoke_other_sessions("user-1", keep_sid=phone) == 2

    assert _live(phone)
    assert not _live(laptop) and not _live(stolen)
    assert redis_client.get(f"ucsrf:{stolen}") is None
    assert _live(someone_else)
    assert redis_client.zrangebyscore(f"{_SIDS_KEY}user-1", 0, time.time() + 1) == [phone]


def test_revoke_other_sessions_for_a_user_with_none_is_a_no_op():
    assert revoke_other_sessions("nobody", keep_sid=None) == 0


def test_destroy_session_drops_the_sid_from_the_index():
    sid = create_session("user-1", "a", "r", int(time.time()) + 3600)
    destroy_session(sid)
    assert redis_client.zrangebyscore(f"{_SIDS_KEY}user-1", 0, time.time() + 1) == []


def test_the_index_slides_with_the_session():
    """A session kept alive past the index's TTL would be one a password change cannot reach."""
    sid = create_session("user-1", "a", "r", int(time.time()) + 3600)
    redis_client.expire(f"{_SESS_KEY}{sid}", 100)
    redis_client.expire(f"{_SIDS_KEY}user-1", 100)

    resolve_user_id(sid)

    assert redis_client.ttl(f"{_SIDS_KEY}user-1") > USER_SESSION_TTL - 5


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------


def test_the_session_cookie_is_httponly_and_carries_no_token():
    response = Response()
    sid = open_session_for(response, make_supabase_session())

    cookies = set_cookie_headers(response)
    session_cookie = next(c for c in cookies if c.startswith(f"{USER_COOKIE_NAME}="))

    assert "HttpOnly" in session_cookie
    assert "access-1" not in session_cookie
    assert "refresh-1" not in session_cookie
    assert sid in session_cookie


def test_the_csrf_cookie_is_readable_because_javascript_has_to_echo_it():
    response = Response()
    open_session_for(response, make_supabase_session())

    csrf_cookie = next(c for c in set_cookie_headers(response) if c.startswith("nl_csrf="))
    assert "HttpOnly" not in csrf_cookie


def test_samesite_is_lax_so_the_stripe_return_still_carries_the_session():
    """Strict would withhold the cookie on the top-level redirect back from
    Stripe and from every Supabase email link, which reads as a logout."""
    response = Response()
    open_session_for(response, make_supabase_session())

    session_cookie = next(c for c in set_cookie_headers(response) if c.startswith(f"{USER_COOKIE_NAME}="))
    assert "samesite=lax" in session_cookie.lower()


def test_session_cookies_are_host_only_by_default():
    """SEC-13: only the API reads the session, so no other subdomain is sent it."""
    response = Response()
    open_session_for(response, make_supabase_session())

    session_cookie = next(c for c in set_cookie_headers(response) if c.startswith(f"{USER_COOKIE_NAME}="))
    assert "domain=" not in session_cookie.lower()


def test_signing_in_expires_the_cookie_left_under_the_old_shared_domain(monkeypatch):
    monkeypatch.setattr(user_session, "LEGACY_SESSION_COOKIE_DOMAIN", ".negolah.my")
    response = Response()
    open_session_for(response, make_supabase_session())

    legacy = [c for c in set_cookie_headers(response) if "domain=.negolah.my" in c.lower()]
    assert len(legacy) == 1
    assert legacy[0].startswith(f"{USER_COOKIE_NAME}=") and "max-age=0" in legacy[0].lower()


def test_no_legacy_cleanup_when_the_session_cookie_still_uses_that_domain(monkeypatch):
    """An operator who pins USER_COOKIE_DOMAIN back to the shared domain must not
    have the login response expire the cookie it has just set."""
    monkeypatch.setattr(user_session, "LEGACY_SESSION_COOKIE_DOMAIN", ".negolah.my")
    monkeypatch.setattr(user_session, "USER_COOKIE_DOMAIN", ".negolah.my")
    response = Response()
    open_session_for(response, make_supabase_session())

    session_cookies = [c for c in set_cookie_headers(response) if c.startswith(f"{USER_COOKIE_NAME}=")]
    assert len(session_cookies) == 1
    assert "max-age=0" not in session_cookies[0].lower()


def test_signing_out_expires_both_the_host_only_and_the_legacy_cookie(monkeypatch):
    monkeypatch.setattr(user_session, "LEGACY_SESSION_COOKIE_DOMAIN", ".negolah.my")
    sid = create_session("user-1", "a", "r", int(time.time()) + 3600)
    request = SimpleNamespace(cookies={USER_COOKIE_NAME: sid})
    response = Response()

    user_session.clear_session_cookies(request, response)

    expired = [c for c in set_cookie_headers(response) if c.startswith(f"{USER_COOKIE_NAME}=")]
    assert len(expired) == 2
    assert any("domain=.negolah.my" in c.lower() for c in expired)
    assert not _live(sid)


def test_open_session_for_rejects_a_supabase_session_with_no_user():
    broken = SimpleNamespace(access_token="a", refresh_token="r", expires_at=0, user=None)
    with pytest.raises(ValueError):
        open_session_for(Response(), broken)


# ---------------------------------------------------------------------------
# Resolution and refresh
# ---------------------------------------------------------------------------


def test_resolve_user_id_returns_the_user_behind_the_cookie():
    sid = create_session("user-42", "a", "r", int(time.time()) + 3600)
    assert resolve_user_id(sid) == "user-42"
    assert access_token_for(sid) == "a"


def test_a_live_token_is_not_refreshed(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(user_session, "new_user_client", lambda: client)

    sid = create_session("user-1", "a", "r", int(time.time()) + 3600)
    assert resolve_user_id(sid) == "user-1"
    client.auth.refresh_session.assert_not_called()


def test_an_expiring_token_is_refreshed_server_side(monkeypatch):
    client = MagicMock()
    client.auth.refresh_session.return_value = SimpleNamespace(
        session=SimpleNamespace(
            access_token="access-2",
            refresh_token="refresh-2",
            expires_at=int(time.time()) + 3600,
        )
    )
    monkeypatch.setattr(user_session, "new_user_client", lambda: client)

    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 10)
    session = resolve_session(sid)

    assert session["access_token"] == "access-2"
    assert session["refresh_token"] == "refresh-2"
    client.auth.refresh_session.assert_called_once_with("refresh-1")
    # And it is persisted, so the next request does not refresh again.
    assert read_session(sid)["access_token"] == "access-2"


def test_concurrent_requests_refresh_once_not_once_each(monkeypatch):
    """The tab-count bug: Supabase rotates the refresh token on use, so a second
    concurrent refresh presents one that no longer exists and the buyer is signed
    out for having four tabs open."""
    calls = []
    barrier_released = threading.Event()

    def slow_refresh(refresh_token):
        calls.append(refresh_token)
        # Hold the lock long enough that every other thread is definitely inside
        # resolve_session and losing the race.
        barrier_released.wait(timeout=2)
        return SimpleNamespace(
            session=SimpleNamespace(
                access_token="access-2",
                refresh_token="refresh-2",
                expires_at=int(time.time()) + 3600,
            )
        )

    client = MagicMock()
    client.auth.refresh_session.side_effect = slow_refresh
    monkeypatch.setattr(user_session, "new_user_client", lambda: client)

    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 10)

    results = []
    threads = [threading.Thread(target=lambda: results.append(resolve_session(sid))) for _ in range(6)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    barrier_released.set()
    for t in threads:
        t.join(timeout=5)

    assert len(calls) == 1, f"refreshed {len(calls)} times; Supabase would have revoked the session"
    assert all(r and r["user_id"] == "user-1" for r in results)
    assert all(r["access_token"] == "access-2" for r in results)


def test_a_failed_refresh_revokes_rather_than_401ing_forever(monkeypatch):
    client = MagicMock()
    client.auth.refresh_session.side_effect = Exception("refresh_token_not_found")
    monkeypatch.setattr(user_session, "new_user_client", lambda: client)

    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 10)

    assert resolve_session(sid) is None
    assert read_session(sid) is None


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectTimeout("timed out"),
        AuthRetryableError("upstream unavailable", 503),
        AuthApiError("bad gateway", 502, None),
    ],
)
def test_a_transient_refresh_failure_keeps_the_session(monkeypatch, error):
    """Audit REL-3: a timeout or 5xx never spent the refresh token, so revoking
    signed buyers out for Supabase's outage rather than their own."""
    client = MagicMock()
    client.auth.refresh_session.side_effect = error
    monkeypatch.setattr(user_session, "new_user_client", lambda: client)

    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 10)

    assert resolve_session(sid)["user_id"] == "user-1"
    assert read_session(sid)["refresh_token"] == "refresh-1"


def test_a_rejected_refresh_token_still_revokes(monkeypatch):
    client = MagicMock()
    client.auth.refresh_session.side_effect = AuthApiError("Invalid Refresh Token", 400, None)
    monkeypatch.setattr(user_session, "new_user_client", lambda: client)

    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 10)

    assert resolve_session(sid) is None


def test_the_refresh_lock_is_released_even_when_the_refresh_fails(monkeypatch):
    client = MagicMock()
    client.auth.refresh_session.side_effect = Exception("boom")
    monkeypatch.setattr(user_session, "new_user_client", lambda: client)

    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 10)
    resolve_session(sid)

    assert redis_client.get(f"{user_session._LOCK_KEY}{sid}") is None


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


def test_pkce_pair_is_a_verifier_and_its_s256_challenge():
    import base64
    import hashlib

    verifier, challenge = new_pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

    assert challenge == expected
    assert "=" not in challenge
    assert 43 <= len(verifier) <= 128
