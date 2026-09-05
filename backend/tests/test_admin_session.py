"""
Tests for admin_session.py:
- Redis-backed admin allowlist (grant/revoke/is_allowed) and instant revocation.
- Rate limiting for the login and OTP factors.
- Two-factor login flow: password_then_send_otp -> verify_otp_and_open_session.
- Opaque session store, the verify_admin dependency, and clear_session/logout.
- Audit logging (write_audit).

admin_session.py mints its own throwaway anon Supabase client per call via
`_auth_client()` (`create_client(SUPABASE_URL, USER_SUPABASE_KEY)`), so we
monkeypatch `admin_session.create_client` to return a configurable MagicMock
instead of hitting real Supabase. Redis-backed state uses the real in-memory
fake from cache.py (flushed automatically after every test by conftest.py).
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Response

import admin_session
from admin_session import (
    _ALLOW_KEY,
    _PREAUTH_KEY,
    _SESS_KEY,
    _create_session,
    clear_session,
    client_ip,
    enforce_login_rate_limit,
    enforce_otp_rate_limit,
    grant_admin,
    is_allowed_admin,
    password_then_send_otp,
    revoke_admin,
    verify_admin,
    verify_otp_and_open_session,
    write_audit,
)
from cache import redis_client
from conftest import make_supabase_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_request(cookies=None, headers=None, ip="127.0.0.1"):
    """Minimal stand-in for fastapi.Request -- everything admin_session.py
    touches on a request is `.cookies.get`, `.headers.get`, and `.client.host`,
    all of which a SimpleNamespace over plain dicts supports."""
    return SimpleNamespace(
        cookies=cookies or {},
        headers=headers or {},
        client=SimpleNamespace(host=ip) if ip is not None else None,
    )


def make_admin_user(user_id="admin-user-1"):
    return SimpleNamespace(id=user_id, app_metadata={"role": "admin"})


def set_cookie_values(response: Response):
    return [v for k, v in response.raw_headers if k == b"set-cookie"]


@pytest.fixture
def fake_auth_client(monkeypatch):
    """Replace the client admin_session._auth_client() would build with a
    configurable MagicMock exposing .auth.sign_in_with_password / sign_in_with_otp
    / verify_otp / sign_out."""
    mock_client = MagicMock()
    monkeypatch.setattr(admin_session, "create_client", lambda *a, **kw: mock_client)
    return mock_client


# ---------------------------------------------------------------------------
# Admin allowlist
# ---------------------------------------------------------------------------

def test_grant_revoke_allow_roundtrip():
    assert is_allowed_admin("user-round-trip") is False
    grant_admin("user-round-trip", "a@example.com")
    assert is_allowed_admin("user-round-trip") is True
    assert redis_client.get(f"{_ALLOW_KEY}user-round-trip") == "a@example.com"
    revoke_admin("user-round-trip")
    assert is_allowed_admin("user-round-trip") is False


def test_grant_admin_without_email_stores_sentinel_value():
    grant_admin("user-no-email")
    assert redis_client.get(f"{_ALLOW_KEY}user-no-email") == "1"
    assert is_allowed_admin("user-no-email") is True


def test_revoke_admin_on_unknown_user_is_a_no_op():
    revoke_admin("never-granted-user")  # must not raise
    assert is_allowed_admin("never-granted-user") is False


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_enforce_login_rate_limit_allows_up_to_max_then_blocks():
    email, ip = "ratelimit@example.com", "10.0.0.1"
    for _ in range(admin_session._LOGIN_MAX):
        enforce_login_rate_limit(email, ip)  # should not raise

    with pytest.raises(HTTPException) as exc_info:
        enforce_login_rate_limit(email, ip)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Too many attempts. Try again later."


def test_enforce_login_rate_limit_scoped_per_email_and_ip():
    for _ in range(admin_session._LOGIN_MAX):
        enforce_login_rate_limit("used-up@example.com", "10.0.0.2")
    # A different email/IP pair has its own independent bucket.
    enforce_login_rate_limit("fresh@example.com", "10.0.0.3")


def test_enforce_otp_rate_limit_allows_up_to_max_then_blocks():
    handle = "handle-rate-limit-test"
    for _ in range(admin_session._OTP_MAX):
        enforce_otp_rate_limit(handle)

    with pytest.raises(HTTPException) as exc_info:
        enforce_otp_rate_limit(handle)
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Too many attempts. Try again later."


# ---------------------------------------------------------------------------
# Factor 1: password_then_send_otp
# ---------------------------------------------------------------------------

def test_password_then_send_otp_happy_path(fake_auth_client):
    user = make_admin_user("admin-happy")
    fake_auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(user=user)

    handle = password_then_send_otp("admin@example.com", "correct-password")

    assert isinstance(handle, str) and len(handle) > 20
    fake_auth_client.auth.sign_in_with_password.assert_called_once_with(
        {"email": "admin@example.com", "password": "correct-password"}
    )
    fake_auth_client.auth.sign_out.assert_called_once()
    fake_auth_client.auth.sign_in_with_otp.assert_called_once()
    assert is_allowed_admin("admin-happy") is True
    assert redis_client.get(f"{_PREAUTH_KEY}{handle}") == "admin@example.com"


def test_password_then_send_otp_otp_send_failure_still_returns_handle(fake_auth_client):
    """Factor-2 email failures are logged but must not block issuing a handle --
    the response shape can't be allowed to leak account existence."""
    user = make_admin_user("admin-otp-fail")
    fake_auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(user=user)
    fake_auth_client.auth.sign_in_with_otp.side_effect = Exception("smtp down")

    handle = password_then_send_otp("admin2@example.com", "pw")
    assert redis_client.get(f"{_PREAUTH_KEY}{handle}") == "admin2@example.com"


def test_password_then_send_otp_invokes_resend_fallback(fake_auth_client, monkeypatch):
    """When sign_in_with_otp fails, fallback to generate_link + Resend dispatch."""
    user = make_admin_user("admin-fallback")
    fake_auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(user=user)
    fake_auth_client.auth.sign_in_with_otp.side_effect = Exception("Domain not verified")

    mock_generate = MagicMock(return_value=("87654321", "https://example.com/magic"))
    mock_send = MagicMock(return_value=True)

    monkeypatch.setattr(admin_session, "_generate_otp_link", mock_generate)
    monkeypatch.setattr(admin_session, "_send_otp_via_resend", mock_send)

    handle = password_then_send_otp("admin-fallback@example.com", "pw")
    assert handle
    mock_generate.assert_called_once_with("admin-fallback@example.com")
    mock_send.assert_called_once_with("admin-fallback@example.com", "87654321", "https://example.com/magic")


def test_render_otp_email_html():
    """Verify OTP code is injected into the rendered HTML."""
    html = admin_session._render_otp_email_html("44556677", "https://example.com/action")
    assert "44556677" in html
    assert "https://example.com/action" in html
    assert "Nego" in html


def test_password_then_send_otp_sign_out_failure_is_swallowed(fake_auth_client):
    user = make_admin_user("admin-signout-fail")
    fake_auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(user=user)
    fake_auth_client.auth.sign_out.side_effect = Exception("already signed out")

    handle = password_then_send_otp("admin3@example.com", "pw")
    assert handle


def test_password_then_send_otp_missing_user_raises_generic_401(fake_auth_client):
    fake_auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(user=None)

    with pytest.raises(HTTPException) as exc_info:
        password_then_send_otp("nouser@example.com", "pw")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"


def test_password_then_send_otp_bad_password_raises_generic_401(fake_auth_client):
    fake_auth_client.auth.sign_in_with_password.side_effect = Exception("invalid grant")

    with pytest.raises(HTTPException) as exc_info:
        password_then_send_otp("baduser@example.com", "wrong-pw")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"


def test_password_then_send_otp_non_admin_raises_generic_401(fake_auth_client):
    non_admin = SimpleNamespace(id="regular-user", app_metadata={"role": "user"})
    fake_auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(user=non_admin)

    with pytest.raises(HTTPException) as exc_info:
        password_then_send_otp("regular@example.com", "pw")
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid credentials"
    # Must never be granted admin access just for having a valid password.
    assert is_allowed_admin("regular-user") is False


def test_password_then_send_otp_missing_app_metadata_treated_as_non_admin(fake_auth_client):
    """_is_admin_user must tolerate a user object with no app_metadata attribute at all."""
    user = SimpleNamespace(id="no-metadata-user")
    fake_auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(user=user)

    with pytest.raises(HTTPException) as exc_info:
        password_then_send_otp("nometa@example.com", "pw")
    assert exc_info.value.detail == "Invalid credentials"


def test_password_then_send_otp_error_message_identical_for_missing_and_non_admin(fake_auth_client):
    """Deliberate security property: the 401 must not differ whether the email
    doesn't exist at all vs. exists but isn't an admin."""
    fake_auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(user=None)
    with pytest.raises(HTTPException) as missing_exc:
        password_then_send_otp("ghost@example.com", "pw")

    non_admin = SimpleNamespace(id="regular-user-2", app_metadata={"role": "user"})
    fake_auth_client.auth.sign_in_with_password.return_value = SimpleNamespace(user=non_admin)
    with pytest.raises(HTTPException) as non_admin_exc:
        password_then_send_otp("regular2@example.com", "pw")

    assert missing_exc.value.status_code == non_admin_exc.value.status_code == 401
    assert missing_exc.value.detail == non_admin_exc.value.detail == "Invalid credentials"


# ---------------------------------------------------------------------------
# Factor 2: verify_otp_and_open_session
# ---------------------------------------------------------------------------

def test_verify_otp_and_open_session_happy_path(fake_auth_client, patch_supabase, fake_supabase):
    patch_supabase("admin_session", admin=fake_supabase)
    handle = "preauth-handle-happy"
    redis_client.setex(f"{_PREAUTH_KEY}{handle}", 300, "otp-admin@example.com")

    user = make_admin_user("otp-admin-user")
    fake_auth_client.auth.verify_otp.return_value = SimpleNamespace(user=user)

    response = Response()
    request = make_request(ip="9.9.9.9")

    result = verify_otp_and_open_session(handle, "123456", response, request)

    assert result == {"user_id": "otp-admin-user", "email": "otp-admin@example.com"}

    cookies = set_cookie_values(response)
    assert len(cookies) == 2
    cookie_names = b" ".join(cookies)
    assert admin_session.ADMIN_COOKIE_NAME.encode() in cookie_names
    assert b"csrf_token" in cookie_names

    # One-time handle: consumed from Redis.
    assert redis_client.get(f"{_PREAUTH_KEY}{handle}") is None
    assert is_allowed_admin("otp-admin-user") is True
    fake_auth_client.auth.sign_out.assert_called_once()

    # Audit log entry was written for the login.
    fake_supabase.table.assert_called_with("admin_audit_log")


def test_verify_otp_and_open_session_sign_out_failure_is_swallowed(
    fake_auth_client, patch_supabase, fake_supabase
):
    patch_supabase("admin_session", admin=fake_supabase)
    handle = "preauth-handle-signout-fail"
    redis_client.setex(f"{_PREAUTH_KEY}{handle}", 300, "signoutfail@example.com")

    user = make_admin_user("otp-signout-fail-user")
    fake_auth_client.auth.verify_otp.return_value = SimpleNamespace(user=user)
    fake_auth_client.auth.sign_out.side_effect = Exception("already signed out")

    response = Response()
    request = make_request()

    result = verify_otp_and_open_session(handle, "123456", response, request)
    assert result["user_id"] == "otp-signout-fail-user"


def test_verify_otp_missing_or_expired_handle_raises_401():
    response = Response()
    request = make_request()

    with pytest.raises(HTTPException) as exc_info:
        verify_otp_and_open_session("nonexistent-handle", "123456", response, request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired code"


def test_verify_otp_bad_code_raises_401_and_preserves_handle(fake_auth_client):
    handle = "preauth-handle-badcode"
    redis_client.setex(f"{_PREAUTH_KEY}{handle}", 300, "otp2@example.com")
    fake_auth_client.auth.verify_otp.side_effect = Exception("invalid token")

    response = Response()
    request = make_request()
    with pytest.raises(HTTPException) as exc_info:
        verify_otp_and_open_session(handle, "000000", response, request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired code"
    # The handle is only consumed on success, so a bad code leaves it alone
    # (still subject to its original TTL and the OTP rate limit).
    assert redis_client.get(f"{_PREAUTH_KEY}{handle}") == "otp2@example.com"


def test_verify_otp_no_user_in_response_raises_401(fake_auth_client):
    handle = "preauth-handle-nouser"
    redis_client.setex(f"{_PREAUTH_KEY}{handle}", 300, "nouser2@example.com")
    fake_auth_client.auth.verify_otp.return_value = SimpleNamespace(user=None)

    response = Response()
    request = make_request()
    with pytest.raises(HTTPException) as exc_info:
        verify_otp_and_open_session(handle, "123456", response, request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired code"


def test_verify_otp_valid_code_but_non_admin_user_raises_401(fake_auth_client):
    handle = "preauth-handle-nonadmin"
    redis_client.setex(f"{_PREAUTH_KEY}{handle}", 300, "nonadmin@example.com")
    non_admin = SimpleNamespace(id="non-admin-id", app_metadata={"role": "user"})
    fake_auth_client.auth.verify_otp.return_value = SimpleNamespace(user=non_admin)

    response = Response()
    request = make_request()
    with pytest.raises(HTTPException) as exc_info:
        verify_otp_and_open_session(handle, "123456", response, request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Invalid or expired code"


def test_verify_otp_rate_limit_exceeded_raises_429(fake_auth_client):
    handle = "preauth-handle-ratelimited"
    redis_client.setex(f"{_PREAUTH_KEY}{handle}", 300, "rl@example.com")
    for _ in range(admin_session._OTP_MAX):
        enforce_otp_rate_limit(handle)

    response = Response()
    request = make_request()
    with pytest.raises(HTTPException) as exc_info:
        verify_otp_and_open_session(handle, "123456", response, request)
    assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# verify_admin dependency
# ---------------------------------------------------------------------------

async def test_verify_admin_missing_cookie_raises_401():
    request = make_request(cookies={})
    with pytest.raises(HTTPException) as exc_info:
        await verify_admin(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Not authenticated"


async def test_verify_admin_unknown_session_raises_401():
    request = make_request(cookies={admin_session.ADMIN_COOKIE_NAME: "nonexistent-sid"})
    with pytest.raises(HTTPException) as exc_info:
        await verify_admin(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Not authenticated"


async def test_verify_admin_valid_session_returns_data_and_uses_forwarded_ip():
    sid = _create_session("admin-valid", "valid@example.com")
    grant_admin("admin-valid", "valid@example.com")

    request = make_request(
        cookies={admin_session.ADMIN_COOKIE_NAME: sid},
        headers={"X-Forwarded-For": "5.6.7.8, 9.9.9.9"},
    )
    result = await verify_admin(request)

    assert result["user_id"] == "admin-valid"
    assert result["email"] == "valid@example.com"
    assert result["ip"] == "5.6.7.8"
    # Session must survive a valid check (sliding TTL, not deleted).
    assert redis_client.get(f"{_SESS_KEY}{sid}") is not None


async def test_verify_admin_falls_back_to_client_host_without_forwarded_header():
    sid = _create_session("admin-directip", "directip@example.com")
    grant_admin("admin-directip")

    request = make_request(cookies={admin_session.ADMIN_COOKIE_NAME: sid}, ip="203.0.113.5")
    result = await verify_admin(request)
    assert result["ip"] == "203.0.113.5"


async def test_verify_admin_revoked_user_raises_401_and_kills_session():
    sid = _create_session("admin-revoked", "revoked@example.com")
    # Deliberately do NOT grant_admin -- simulates a revoked/self-heal-lost admin.
    request = make_request(cookies={admin_session.ADMIN_COOKIE_NAME: sid})

    with pytest.raises(HTTPException) as exc_info:
        await verify_admin(request)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Not authenticated"
    # Instant revocation: the opaque session itself is destroyed too.
    assert redis_client.get(f"{_SESS_KEY}{sid}") is None


async def test_verify_admin_corrupted_session_json_raises_401():
    sid = "corrupted-sid"
    redis_client.setex(f"{_SESS_KEY}{sid}", 100, "not-valid-json{{{")
    request = make_request(cookies={admin_session.ADMIN_COOKIE_NAME: sid})

    with pytest.raises(HTTPException) as exc_info:
        await verify_admin(request)
    assert exc_info.value.status_code == 401


async def test_verify_admin_session_missing_user_id_raises_401():
    sid = "no-user-id-sid"
    redis_client.setex(f"{_SESS_KEY}{sid}", 100, json.dumps({"email": "onlyemail@example.com"}))
    request = make_request(cookies={admin_session.ADMIN_COOKIE_NAME: sid})

    with pytest.raises(HTTPException) as exc_info:
        await verify_admin(request)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# clear_session
# ---------------------------------------------------------------------------

def test_clear_session_deletes_redis_key_and_issues_delete_cookie():
    sid = _create_session("clear-me", "clear@example.com")
    assert redis_client.get(f"{_SESS_KEY}{sid}") is not None

    request = make_request(cookies={admin_session.ADMIN_COOKIE_NAME: sid})
    response = Response()
    clear_session(request, response)

    assert redis_client.get(f"{_SESS_KEY}{sid}") is None
    cookies = set_cookie_values(response)
    assert len(cookies) == 2
    cookie_names = b" ".join(cookies)
    assert admin_session.ADMIN_COOKIE_NAME.encode() in cookie_names
    assert b"csrf_token" in cookie_names


def test_clear_session_without_cookie_is_a_no_op_but_still_deletes_cookie():
    request = make_request(cookies={})
    response = Response()
    clear_session(request, response)  # must not raise

    cookies = set_cookie_values(response)
    assert len(cookies) == 2


# ---------------------------------------------------------------------------
# client_ip
# ---------------------------------------------------------------------------

def test_client_ip_prefers_first_x_forwarded_for_entry():
    request = make_request(headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2"})
    assert client_ip(request) == "1.1.1.1"


def test_client_ip_falls_back_to_request_client_host():
    request = make_request(ip="7.7.7.7")
    assert client_ip(request) == "7.7.7.7"


def test_client_ip_returns_unknown_when_no_client_info():
    request = make_request(ip=None)
    assert client_ip(request) == "unknown"


# ---------------------------------------------------------------------------
# write_audit
# ---------------------------------------------------------------------------

def test_write_audit_success_calls_supabase_insert(patch_supabase, fake_supabase):
    patch_supabase("admin_session", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.return_value = (
        make_supabase_result([{"id": 1}])
    )

    write_audit("actor-1", "actor@example.com", "login", None, "1.2.3.4")

    fake_supabase.table.assert_called_with("admin_audit_log")
    fake_supabase.table.return_value.insert.assert_called_once_with({
        "actor_user_id": "actor-1",
        "actor_email": "actor@example.com",
        "action": "login",
        "target": None,
        "ip": "1.2.3.4",
    })
    fake_supabase.table.return_value.insert.return_value.execute.assert_called_once()


def test_write_audit_swallows_exception(patch_supabase):
    mock = MagicMock()
    mock.table.return_value.insert.return_value.execute.side_effect = Exception("db unreachable")
    patch_supabase("admin_session", admin=mock)

    write_audit("actor-2", "actor2@example.com", "logout", "target-id", "5.5.5.5")  # must not raise
