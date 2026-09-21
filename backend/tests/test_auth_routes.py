"""
Tests for the buyer auth routes — SPEC-093.

These routes are the whole point of the migration: every Supabase call the SPA
used to make now happens here, and the browser gets a cookie instead of a token.
So the assertions are mostly about what is NOT in the response.

`new_user_client` is bound at import time in auth_routes, so it is patched there.
"""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import domains.identity.auth_routes as auth_routes
from core.cache import redis_client
from core.env import USER_COOKIE_NAME
from domains.identity.user_session import _SESS_KEY, create_session


def make_session(user_id="user-1", access="access-1", refresh="refresh-1"):
    return SimpleNamespace(
        access_token=access,
        refresh_token=refresh,
        expires_at=int(time.time()) + 3600,
        user=SimpleNamespace(id=user_id, email="buyer@example.com", user_metadata={"name": "Buyer"}),
    )


@pytest.fixture
def fake_auth(monkeypatch):
    """Stand in for the throwaway anon client auth_routes builds per call."""
    client = MagicMock()
    monkeypatch.setattr(auth_routes, "new_user_client", lambda: client)
    return client


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


async def test_login_sets_an_httponly_cookie_and_returns_no_token(client, fake_auth):
    fake_auth.auth.sign_in_with_password.return_value = SimpleNamespace(session=make_session())

    res = await client.post("/auth/login", json={"email": "Buyer@Example.com ", "password": "hunter2"})

    assert res.status_code == 200
    body = res.json()
    assert body["user"]["id"] == "user-1"
    assert "access_token" not in str(body)
    assert "refresh-1" not in str(body)

    set_cookie = res.headers.get_list("set-cookie")
    session_cookie = next(c for c in set_cookie if c.startswith(f"{USER_COOKIE_NAME}="))
    assert "HttpOnly" in session_cookie
    assert "access-1" not in session_cookie

    # The address is normalised before it reaches Supabase.
    fake_auth.auth.sign_in_with_password.assert_called_once()
    assert fake_auth.auth.sign_in_with_password.call_args[0][0]["email"] == "buyer@example.com"


async def test_login_with_bad_credentials_is_401_and_says_nothing_useful(client, fake_auth):
    fake_auth.auth.sign_in_with_password.side_effect = Exception("Invalid login credentials")

    res = await client.post("/auth/login", json={"email": "b@example.com", "password": "wrong"})

    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"
    assert not [c for c in res.headers.get_list("set-cookie") if c.startswith(f"{USER_COOKIE_NAME}=")]


async def test_login_rejects_a_response_with_no_session(client, fake_auth):
    fake_auth.auth.sign_in_with_password.return_value = SimpleNamespace(session=None)

    res = await client.post("/auth/login", json={"email": "b@example.com", "password": "x"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------


async def test_register_opens_no_session_even_when_supabase_returns_one(client, fake_auth):
    """Confirmation is the emailed link's job. Exactly one route mints a cookie."""
    fake_auth.auth.sign_up.return_value = SimpleNamespace(session=make_session())

    res = await client.post("/auth/register", json={"email": "new@example.com", "password": "hunter2"})

    assert res.status_code == 200
    assert res.json() == {"confirmation_sent": True}
    assert not [c for c in res.headers.get_list("set-cookie") if c.startswith(f"{USER_COOKIE_NAME}=")]


async def test_register_does_not_disclose_an_existing_account(client, fake_auth):
    fake_auth.auth.sign_up.side_effect = Exception("User already registered")

    res = await client.post("/auth/register", json={"email": "taken@example.com", "password": "hunter2"})

    assert res.status_code == 200
    assert res.json() == {"confirmation_sent": True}


async def test_register_points_the_confirmation_link_at_the_api_callback(client, fake_auth):
    fake_auth.auth.sign_up.return_value = SimpleNamespace(session=None)

    await client.post("/auth/register", json={"email": "new@example.com", "password": "hunter2"})

    options = fake_auth.auth.sign_up.call_args[0][0]["options"]
    assert options["email_redirect_to"].endswith("/auth/callback")


# ---------------------------------------------------------------------------
# Session / logout
# ---------------------------------------------------------------------------


async def test_session_is_401_without_a_cookie(client):
    res = await client.get("/auth/session")
    assert res.status_code == 401


async def test_session_returns_the_user_behind_the_cookie(client, fake_auth):
    sid = create_session("user-7", "access-1", "refresh-1", int(time.time()) + 3600)
    fake_auth.auth.get_user.return_value = SimpleNamespace(
        user=SimpleNamespace(id="user-7", email="b@example.com", user_metadata={})
    )

    res = await client.get("/auth/session", cookies={USER_COOKIE_NAME: sid})

    assert res.status_code == 200
    assert res.json()["user"]["id"] == "user-7"
    # A fresh CSRF token rides along, for a browser that dropped the cookie.
    assert [c for c in res.headers.get_list("set-cookie") if c.startswith("nl_csrf=")]


async def test_session_is_401_once_the_key_is_deleted(client, fake_auth):
    """Instant revocation — the property the opaque id exists for."""
    sid = create_session("user-7", "access-1", "refresh-1", int(time.time()) + 3600)
    redis_client.delete(f"{_SESS_KEY}{sid}")

    res = await client.get("/auth/session", cookies={USER_COOKIE_NAME: sid})
    assert res.status_code == 401


async def test_logout_revokes_the_session_server_side(client):
    sid = create_session("user-7", "access-1", "refresh-1", int(time.time()) + 3600)
    csrf = redis_client.get(f"ucsrf:{sid}") or _mint_csrf(sid)

    res = await client.post("/auth/logout", cookies={USER_COOKIE_NAME: sid}, headers={"X-CSRF-Token": csrf})

    assert res.status_code == 200
    assert redis_client.get(f"{_SESS_KEY}{sid}") is None


def _mint_csrf(sid: str) -> str:
    from core.csrf import USER_SCOPE, generate_csrf_token

    return generate_csrf_token(sid, USER_SCOPE)


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------


async def test_oauth_start_redirects_to_supabase_with_a_challenge_and_stashes_the_verifier(client):
    res = await client.get("/auth/oauth/start?provider=google", follow_redirects=False)

    assert res.status_code == 302
    location = res.headers["location"]
    assert "/auth/v1/authorize" in location
    assert "provider=google" in location
    assert "code_challenge=" in location
    assert "code_challenge_method=s256" in location

    pkce = next(c for c in res.headers.get_list("set-cookie") if c.startswith("nl_pkce="))
    assert "HttpOnly" in pkce
    # The verifier itself must not be the challenge that just went on the wire.
    assert "code_challenge" not in pkce


async def test_oauth_start_rejects_an_unknown_provider(client):
    res = await client.get("/auth/oauth/start?provider=evilcorp", follow_redirects=False)
    assert res.status_code == 400


async def test_oauth_start_refuses_an_offsite_next(client):
    res = await client.get("/auth/oauth/start?next=https://evil.example", follow_redirects=False)
    assert res.status_code == 302
    pkce = next(c for c in res.headers.get_list("set-cookie") if c.startswith("nl_pkce="))
    assert "evil.example" not in pkce


async def test_callback_without_a_verifier_sets_no_session(client, fake_auth):
    """A code that did not start here is not redeemable. That is PKCE."""
    res = await client.get("/auth/callback?code=stolen-code", follow_redirects=False)

    assert res.status_code == 302
    assert "/login?error=link_invalid" in res.headers["location"]
    assert not [c for c in res.headers.get_list("set-cookie") if c.startswith(f"{USER_COOKIE_NAME}=")]
    fake_auth.auth.exchange_code_for_session.assert_not_called()


async def test_callback_exchanges_a_code_and_lands_in_the_spa(client, fake_auth):
    fake_auth.auth.exchange_code_for_session.return_value = SimpleNamespace(session=make_session("user-9"))

    start = await client.get("/auth/oauth/start?next=/orders", follow_redirects=False)
    pkce_value = _cookie_value(start, "nl_pkce")

    res = await client.get(
        "/auth/callback?code=good-code",
        cookies={"nl_pkce": pkce_value},
        follow_redirects=False,
    )

    assert res.status_code == 302
    assert res.headers["location"].endswith("/orders")
    session_cookie = next(c for c in res.headers.get_list("set-cookie") if c.startswith(f"{USER_COOKIE_NAME}="))
    assert "HttpOnly" in session_cookie
    assert "access-1" not in session_cookie


async def test_callback_verifies_an_email_token_hash(client, fake_auth):
    fake_auth.auth.verify_otp.return_value = SimpleNamespace(session=make_session("user-3"))

    res = await client.get("/auth/callback?token_hash=abc&type=signup", follow_redirects=False)

    assert res.status_code == 302
    assert [c for c in res.headers.get_list("set-cookie") if c.startswith(f"{USER_COOKIE_NAME}=")]
    fake_auth.auth.verify_otp.assert_called_once_with({"token_hash": "abc", "type": "signup"})


async def test_a_recovery_link_lands_on_the_reset_form(client, fake_auth):
    fake_auth.auth.verify_otp.return_value = SimpleNamespace(session=make_session("user-3"))

    res = await client.get("/auth/callback?token_hash=abc&type=recovery", follow_redirects=False)

    assert res.headers["location"].endswith("/reset-password")


async def test_an_expired_link_lands_on_login_with_no_session(client, fake_auth):
    fake_auth.auth.verify_otp.side_effect = Exception("Token has expired")

    res = await client.get("/auth/callback?token_hash=stale&type=signup", follow_redirects=False)

    assert "/login?error=link_invalid" in res.headers["location"]
    assert not [c for c in res.headers.get_list("set-cookie") if c.startswith(f"{USER_COOKIE_NAME}=")]


def _cookie_value(response, name: str) -> str:
    raw = next(c for c in response.headers.get_list("set-cookie") if c.startswith(f"{name}="))
    return raw.split(";")[0].split("=", 1)[1]


# ---------------------------------------------------------------------------
# Password recovery
# ---------------------------------------------------------------------------


async def test_forgot_password_always_reports_sent(client, fake_auth):
    fake_auth.auth.reset_password_email.side_effect = Exception("User not found")

    res = await client.post("/auth/password/forgot", json={"email": "ghost@example.com"})

    assert res.status_code == 200
    assert res.json() == {"sent": True}


async def test_reset_password_requires_the_recovery_session(client, fake_auth, auth_user):
    auth_user("user-1")
    res = await client.post("/auth/password/reset", json={"new_password": "a-new-password"})
    assert res.status_code == 401


async def test_reset_password_updates_through_the_recovery_session(client, fake_auth, auth_user):
    auth_user("user-1")
    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 3600)

    res = await client.post(
        "/auth/password/reset",
        json={"new_password": "a-new-password"},
        cookies={USER_COOKIE_NAME: sid},
        headers={"X-CSRF-Token": _mint_csrf(sid)},
    )

    assert res.status_code == 200
    fake_auth.auth.set_session.assert_called_once_with("access-1", "refresh-1")
    fake_auth.auth.update_user.assert_called_once_with({"password": "a-new-password"})


async def test_reset_password_rejects_a_short_password(client, fake_auth, auth_user):
    auth_user("user-1")
    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 3600)

    res = await client.post(
        "/auth/password/reset",
        json={"new_password": "short"},
        cookies={USER_COOKIE_NAME: sid},
        headers={"X-CSRF-Token": _mint_csrf(sid)},
    )

    assert res.status_code == 400
    fake_auth.auth.update_user.assert_not_called()


async def test_a_signup_link_lands_on_the_confirmation_screen(client, fake_auth):
    """An email link starts in the inbox, not in this browser, so there is no
    `next` to return to — without an explicit landing the visitor would be
    dropped on the homepage with no sign that anything happened."""
    fake_auth.auth.verify_otp.return_value = SimpleNamespace(session=make_session("user-3"))

    res = await client.get("/auth/callback?token_hash=abc&type=signup", follow_redirects=False)

    assert res.headers["location"].endswith("/confirm?status=confirmed")


async def test_an_email_change_link_lands_on_the_profile(client, fake_auth):
    fake_auth.auth.verify_otp.return_value = SimpleNamespace(session=make_session("user-3"))

    res = await client.get("/auth/callback?token_hash=abc&type=email_change", follow_redirects=False)

    assert res.headers["location"].endswith("/profile?status=email_updated")
