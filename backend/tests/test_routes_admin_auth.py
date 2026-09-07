"""
Tests for the admin router -- ONLY the auth section (public /admin/auth/*),
/admin/users/*, and /admin/chats/*.

routes/admin is a PACKAGE, one module per concern (SPEC-037). This file covers
`routes/admin/auth.py`, `routes/admin/users.py` and `routes/admin/chats.py`;
the aliases `admin_auth` / `admin_users` / `admin_chats` below are the patch
targets, one per module. Patching `routes.admin` (the package) does nothing:
a handler resolves `write_audit` in ITS OWN module namespace, so the patch has
to land on the module that defines the route under test.

/admin/orders, /admin/items, /admin/analyze-image, /admin/market-valuation,
/admin/summary, /admin/cleanup-stripe are covered by a separate test file --
deliberately not duplicated here.

Mocking seam notes specific to this file:
- The auth endpoints (`/auth/login`, `/auth/verify-2fa`) call
  `password_then_send_otp` / `verify_otp_and_open_session`, which
  routes/admin/auth.py imports at module level (`from admin_session import ...`),
  binding those names directly into `routes.admin.auth`'s namespace.
  admin_session.py's own internals (password/OTP verification, session store,
  rate limiting) already have deep unit coverage in tests/test_admin_session.py,
  so here we only verify the *route wiring*: monkeypatch
  `admin_auth.password_then_send_otp` / `admin_auth.verify_otp_and_open_session`
  / `admin_auth.clear_session` / `admin_auth.write_audit` directly.
  `write_audit` for a /users/* route is patched on `admin_users`, and for a
  /chats/* route on `admin_chats` -- same reason.
  `enforce_login_rate_limit` is left real
  (it's cheap and backed by the safe in-memory fake redis) so we can also
  exercise the 429 path for free.
- Every `/admin/users/*` and `/admin/chats/*` handler does a *lazy*
  `from connector import admin_supabase` inside the function body, so we patch
  `connector.admin_supabase` via `patch_supabase("connector", admin=...)`
  (NOT `patch_supabase("routes.admin.users", ...)`, which would be a no-op
  since those modules never bind that name at module scope).
- `agent.memory.conversation_memory` is a process-wide singleton with a lazily
  memoized `.supabase` property (`self._supabase` is cached after first
  access). If some earlier test let that property resolve for real, patching
  `connector.admin_supabase` afterwards would NOT be picked up by an already
  -cached instance. To sidestep this entirely we never touch that property:
  we monkeypatch `conversation_memory.add_message` / `.get_history` /
  `.get_all_histories` directly on the singleton object every time.
- `ban_user`'s admin-protection check does a lazy
  `from admin_session import _is_admin_user` -- patched as
  `admin_session._is_admin_user` directly.
- `toggle_user_ai`'s realtime-broadcast side effect imports `ADMIN_SUPABASE_KEY`
  / `SUPABASE_URL` from env.py and POSTs to Supabase's broadcast endpoint via
  `requests.post`. We monkeypatch `requests.post` so the broadcast path is
  exercised without a real network call (see test_toggle_user_ai_* below).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException

import admin_session
import routes.admin.auth as admin_auth
import routes.admin.chats as admin_chats
import routes.admin.users as admin_users
from agent.memory import conversation_memory
from conftest import PNG_BYTES, make_supabase_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def table_router(mapping):
    """Build a callable for `fake_supabase.table.side_effect` that returns a
    distinct (already-configured) MagicMock per table name, e.g.:

        profiles_mock = MagicMock()
        profiles_mock.select.return_value.execute.return_value = make_supabase_result([...])
        fake_supabase.table.side_effect = table_router({"user_profiles": profiles_mock})
    """
    def _side_effect(name, *_a, **_kw):
        return mapping.get(name, MagicMock())
    return _side_effect


def make_user(user_id, email=None, metadata=None, created_at="2024-01-01T00:00:00Z"):
    return SimpleNamespace(
        id=user_id,
        email=email,
        user_metadata=metadata or {},
        created_at=created_at,
    )


# ===========================================================================
# Auth: POST /admin/auth/login
# ===========================================================================

async def test_admin_login_success_returns_handle(client, monkeypatch):
    mock_send_otp = MagicMock(return_value="preauth-handle-xyz")
    monkeypatch.setattr(admin_auth, "password_then_send_otp", mock_send_otp)

    resp = await client.post(
        "/admin/auth/login",
        json={"email": "Admin@Example.com", "password": "correct-horse"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["handle"] == "preauth-handle-xyz"
    assert "verification code" in body["message"].lower()
    # Email is normalized (stripped + lowered) before being handed off.
    mock_send_otp.assert_called_once_with("admin@example.com", "correct-horse")


async def test_admin_login_invalid_credentials_returns_401(client, monkeypatch):
    monkeypatch.setattr(
        admin_auth,
        "password_then_send_otp",
        MagicMock(side_effect=HTTPException(status_code=401, detail="Invalid credentials")),
    )

    resp = await client.post(
        "/admin/auth/login",
        json={"email": "nobody@example.com", "password": "wrong"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"


async def test_admin_login_rate_limited_after_max_attempts(client, monkeypatch):
    # Leave enforce_login_rate_limit real (backed by the safe in-memory fake
    # redis) and only stub out the OTP-sending side effect, so we can drive
    # the real 429 path for free.
    monkeypatch.setattr(admin_auth, "password_then_send_otp", MagicMock(return_value="h"))

    email = "ratelimited-route@example.com"
    last_resp = None
    for _ in range(admin_session._LOGIN_MAX + 1):
        last_resp = await client.post(
            "/admin/auth/login",
            json={"email": email, "password": "pw"},
        )

    assert last_resp.status_code == 429
    assert "too many attempts" in last_resp.json()["detail"].lower()


# ===========================================================================
# Auth: POST /admin/auth/verify-2fa
# ===========================================================================

async def test_admin_verify_2fa_success(client, monkeypatch):
    monkeypatch.setattr(
        admin_auth,
        "verify_otp_and_open_session",
        MagicMock(return_value={"user_id": "admin-1", "email": "admin@example.com"}),
    )

    resp = await client.post(
        "/admin/auth/verify-2fa",
        json={"handle": "some-handle", "code": " 123456 "},
    )

    assert resp.status_code == 200
    assert resp.json() == {"valid": True, "email": "admin@example.com"}


async def test_admin_verify_2fa_strips_code_before_verifying(client, monkeypatch):
    mock_verify = MagicMock(return_value={"user_id": "admin-1", "email": "a@example.com"})
    monkeypatch.setattr(admin_auth, "verify_otp_and_open_session", mock_verify)

    await client.post("/admin/auth/verify-2fa", json={"handle": "h1", "code": " 000111 "})

    args = mock_verify.call_args[0]
    assert args[0] == "h1"
    assert args[1] == "000111"


async def test_admin_verify_2fa_invalid_code_returns_401(client, monkeypatch):
    monkeypatch.setattr(
        admin_auth,
        "verify_otp_and_open_session",
        MagicMock(side_effect=HTTPException(status_code=401, detail="Invalid or expired code")),
    )

    resp = await client.post(
        "/admin/auth/verify-2fa",
        json={"handle": "bad-handle", "code": "000000"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid or expired code"


# ===========================================================================
# Auth: POST /admin/auth/logout, GET /admin/auth/session
# ===========================================================================

async def test_admin_logout_success(client, admin_user, monkeypatch):
    admin_user(user_id="admin-42", email="admin42@example.com", ip="1.2.3.4")
    mock_clear = MagicMock()
    mock_audit = MagicMock()
    monkeypatch.setattr(admin_auth, "clear_session", mock_clear)
    monkeypatch.setattr(admin_auth, "write_audit", mock_audit)

    resp = await client.post("/admin/auth/logout")

    assert resp.status_code == 200
    assert resp.json() == {"message": "Logged out"}
    mock_clear.assert_called_once()
    mock_audit.assert_called_once_with("admin-42", "admin42@example.com", "logout", None, "1.2.3.4")


async def test_admin_logout_requires_authentication(client):
    resp = await client.post("/admin/auth/logout")
    assert resp.status_code == 401


async def test_admin_session_check_success(client, admin_user):
    admin_user(email="sessioncheck@example.com")

    resp = await client.get("/admin/auth/session")

    assert resp.status_code == 200
    assert resp.json() == {"valid": True, "email": "sessioncheck@example.com"}


async def test_admin_session_check_requires_authentication(client):
    resp = await client.get("/admin/auth/session")
    assert resp.status_code == 401


# ===========================================================================
# GET /admin/users
# ===========================================================================

async def test_get_all_users_requires_admin(client):
    resp = await client.get("/admin/users")
    assert resp.status_code == 401


async def test_get_all_users_merges_auth_profile_and_settings(client, admin_user, fake_supabase, patch_supabase):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)

    user1 = make_user("u1", email="alice@example.com", metadata={"display_name": "Alice A", "avatar_url": "http://a/x.png"})
    user2 = make_user("u2", email="bob@example.com", metadata={})
    fake_supabase.auth.admin.list_users.return_value = [user1, user2]

    profiles_mock = MagicMock()
    profiles_mock.select.return_value.execute.return_value = make_supabase_result(
        [{"id": "u2", "display_name": "Bobby", "avatar_url": "http://b/y.png", "is_banned": True}]
    )
    settings_mock = MagicMock()
    settings_mock.select.return_value.execute.return_value = make_supabase_result(
        [{"user_id": "u1", "ai_enabled": False, "admin_intervening": True}]
    )
    fake_supabase.table.side_effect = table_router(
        {"user_profiles": profiles_mock, "chat_settings": settings_mock}
    )

    resp = await client.get("/admin/users")

    assert resp.status_code == 200
    body = {u["id"]: u for u in resp.json()}
    assert len(body) == 2

    # user1: metadata wins for display_name/avatar; no profile row -> is_banned defaults False;
    # settings row present -> ai_enabled/admin_intervening reflect it.
    assert body["u1"]["display_name"] == "Alice A"
    assert body["u1"]["avatar_url"] == "http://a/x.png"
    assert body["u1"]["is_banned"] is False
    assert body["u1"]["ai_enabled"] is False
    assert body["u1"]["admin_intervening"] is True

    # user2: empty metadata -> falls back to profile display_name/avatar; profile says banned;
    # no settings row -> ai_enabled defaults True, admin_intervening defaults False.
    assert body["u2"]["display_name"] == "Bobby"
    assert body["u2"]["avatar_url"] == "http://b/y.png"
    assert body["u2"]["is_banned"] is True
    assert body["u2"]["ai_enabled"] is True
    assert body["u2"]["admin_intervening"] is False


async def test_get_all_users_prefers_custom_avatar_over_provider_avatar(client, admin_user, fake_supabase, patch_supabase):
    """A self-uploaded avatar outranks the Google photo Supabase re-syncs on login."""
    admin_user()
    patch_supabase("connector", admin=fake_supabase)

    user1 = make_user("u1", email="alice@example.com", metadata={
        "custom_avatar_url": "http://cdn/uploaded.png",
        "avatar_url": "https://lh3.googleusercontent.com/a/google-photo",
    })
    fake_supabase.auth.admin.list_users.return_value = [user1]

    profiles_mock = MagicMock()
    profiles_mock.select.return_value.execute.return_value = make_supabase_result([])
    settings_mock = MagicMock()
    settings_mock.select.return_value.execute.return_value = make_supabase_result([])
    fake_supabase.table.side_effect = table_router(
        {"user_profiles": profiles_mock, "chat_settings": settings_mock}
    )

    resp = await client.get("/admin/users")

    assert resp.status_code == 200
    assert resp.json()[0]["avatar_url"] == "http://cdn/uploaded.png"


async def test_get_all_users_email_local_part_fallback_when_no_display_name(client, admin_user, fake_supabase, patch_supabase):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)

    user = make_user("u3", email="noname@example.com", metadata={})
    fake_supabase.auth.admin.list_users.return_value = [user]
    fake_supabase.table.side_effect = table_router({})  # no profile/settings rows at all

    resp = await client.get("/admin/users")

    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["display_name"] == "noname"


async def test_get_all_users_exception_returns_500(client, admin_user, fake_supabase, patch_supabase):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.auth.admin.list_users.side_effect = Exception("supabase is down")

    resp = await client.get("/admin/users")

    assert resp.status_code == 500
    assert "supabase is down" in resp.json()["detail"]


# ===========================================================================
# PUT /admin/users/{user_id}/profile
# ===========================================================================

async def test_update_user_profile_with_both_fields(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user(user_id="admin-1", email="admin@example.com", ip="9.9.9.9")
    patch_supabase("connector", admin=fake_supabase)
    mock_audit = MagicMock()
    monkeypatch.setattr(admin_users, "write_audit", mock_audit)

    resp = await client.put(
        "/admin/users/target-user/profile",
        json={"display_name": "New Name", "avatar_url": "http://cdn/avatar.png"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"message": "User profile updated successfully"}
    upsert_call = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert upsert_call["id"] == "target-user"
    assert upsert_call["display_name"] == "New Name"
    assert upsert_call["avatar_url"] == "http://cdn/avatar.png"
    mock_audit.assert_called_once_with(
        "admin-1", "admin@example.com", "user.profile_update", "target-user", "9.9.9.9"
    )


async def test_update_user_profile_no_fields_provided_omits_optional_keys(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())

    resp = await client.put("/admin/users/target-user/profile", json={})

    assert resp.status_code == 200
    upsert_call = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert set(upsert_call.keys()) == {"id", "updated_at"}


async def test_update_user_profile_requires_admin(client):
    resp = await client.put("/admin/users/target-user/profile", json={"display_name": "X"})
    assert resp.status_code == 401


# ===========================================================================
# POST /admin/users/{user_id}/avatar
# ===========================================================================

async def test_upload_user_avatar_storage_success(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/avatars/x.png"

    resp = await client.post(
        "/admin/users/target-user/avatar",
        files={"avatar": ("photo.png", PNG_BYTES, "image/png")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_url"] == "https://cdn.example.com/avatars/x.png"
    assert body["message"] == "Avatar uploaded successfully"
    fake_supabase.storage.from_.return_value.upload.assert_called_once()
    upload_args = fake_supabase.storage.from_.return_value.upload.call_args[0]
    assert upload_args[0].startswith("avatars/target-user_")
    assert upload_args[1] == PNG_BYTES


async def test_upload_user_avatar_storage_failure_falls_back_to_base64(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())
    fake_supabase.storage.from_.return_value.upload.side_effect = Exception("storage unavailable")

    resp = await client.post(
        "/admin/users/target-user/avatar",
        files={"avatar": ("photo.png", PNG_BYTES, "image/png")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "Avatar uploaded (base64)"
    assert body["avatar_url"].startswith("data:image/png;base64,")


async def test_upload_user_avatar_requires_admin(client):
    resp = await client.post(
        "/admin/users/target-user/avatar",
        files={"avatar": ("photo.png", PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 401


# ===========================================================================
# PUT /admin/users/{user_id}/ban
# ===========================================================================

async def test_ban_user_cannot_ban_self(client, admin_user, monkeypatch):
    admin_user(user_id="admin-self")
    mock_audit = MagicMock()
    monkeypatch.setattr(admin_users, "write_audit", mock_audit)

    resp = await client.put("/admin/users/admin-self/ban", json={"is_banned": True})

    assert resp.status_code == 400
    assert "cannot ban your own account" in resp.json()["detail"].lower()
    mock_audit.assert_not_called()


async def test_ban_user_cannot_ban_another_admin(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user(user_id="admin-self")
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_session, "_is_admin_user", MagicMock(return_value=True))
    fake_supabase.auth.admin.get_user_by_id.return_value = SimpleNamespace(
        user=make_user("other-admin", email="other-admin@example.com")
    )
    mock_audit = MagicMock()
    monkeypatch.setattr(admin_users, "write_audit", mock_audit)

    resp = await client.put("/admin/users/other-admin/ban", json={"is_banned": True})

    assert resp.status_code == 403
    assert "cannot ban an admin" in resp.json()["detail"].lower()
    mock_audit.assert_not_called()
    fake_supabase.table.return_value.upsert.assert_not_called()


async def test_ban_user_success_bans_normal_user(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user(user_id="admin-self", email="admin@example.com", ip="8.8.8.8")
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_session, "_is_admin_user", MagicMock(return_value=False))
    fake_supabase.auth.admin.get_user_by_id.return_value = SimpleNamespace(
        user=make_user("normal-user")
    )
    mock_audit = MagicMock()
    monkeypatch.setattr(admin_users, "write_audit", mock_audit)

    resp = await client.put("/admin/users/normal-user/ban", json={"is_banned": True})

    assert resp.status_code == 200
    assert resp.json() == {"message": "User banned successfully"}
    upsert_call = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert upsert_call == {"id": "normal-user", "is_banned": True, "updated_at": "now()"}
    fake_supabase.auth.admin.update_user_by_id.assert_called_once_with(
        "normal-user", {"ban_duration": "876000h"}
    )
    mock_audit.assert_called_once_with("admin-self", "admin@example.com", "user.ban", "normal-user", "8.8.8.8")


async def test_ban_user_unban_lifts_ban(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())

    resp = await client.put("/admin/users/normal-user/ban", json={"is_banned": False})

    assert resp.status_code == 200
    assert resp.json() == {"message": "User unbanned successfully"}
    # Unbanning never triggers the self-ban/admin-ban lookup at all.
    fake_supabase.auth.admin.get_user_by_id.assert_not_called()
    fake_supabase.auth.admin.update_user_by_id.assert_called_once_with(
        "normal-user", {"ban_duration": "none"}
    )


async def test_ban_user_admin_lookup_exception_is_swallowed_and_ban_still_proceeds(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.auth.admin.get_user_by_id.side_effect = Exception("lookup service down")
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())

    resp = await client.put("/admin/users/some-user/ban", json={"is_banned": True})

    # A non-HTTPException failure while checking admin status is logged and
    # does NOT block the ban from proceeding.
    assert resp.status_code == 200
    fake_supabase.table.return_value.upsert.assert_called_once()


async def test_ban_user_requires_admin(client):
    resp = await client.put("/admin/users/some-user/ban", json={"is_banned": True})
    assert resp.status_code == 401


# ===========================================================================
# PUT /admin/users/{user_id}/ai
# ===========================================================================

async def test_toggle_user_ai_enable_broadcasts_via_supabase(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    """Enabling AI upserts chat_settings, records the system message, and
    broadcasts it to the user's realtime channel via Supabase's REST broadcast
    endpoint, authenticated with the service-role key (ADMIN_SUPABASE_KEY)."""
    admin_user(user_id="admin-1", email="admin@example.com", ip="1.1.1.1")
    patch_supabase("connector", admin=fake_supabase)
    mock_add_message = MagicMock()
    monkeypatch.setattr(conversation_memory, "add_message", mock_add_message)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())

    import requests
    mock_post = MagicMock(return_value=SimpleNamespace(status_code=200, text="ok"))
    monkeypatch.setattr(requests, "post", mock_post)

    resp = await client.put("/admin/users/target-user/ai", json={"ai_enabled": True})

    assert resp.status_code == 200
    assert resp.json() == {"message": "AI enabled for user"}

    upsert_call = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert upsert_call["user_id"] == "target-user"
    assert upsert_call["ai_enabled"] is True
    assert upsert_call["admin_intervening"] is False

    mock_add_message.assert_called_once_with(
        "target-user", "system",
        "--- Terry has retired from the chat and the AI will take over now ---",
        source="system",
    )

    # The broadcast now actually fires (the old SUPABASE_KEY ImportError is
    # fixed), authenticated with the service-role key and targeting the user's
    # channel with the system message.
    mock_post.assert_called_once()
    _args, kwargs = mock_post.call_args
    assert kwargs["headers"]["apikey"] == "test-admin-service-role-key"
    assert kwargs["headers"]["Authorization"] == "Bearer test-admin-service-role-key"
    broadcast_msg = kwargs["json"]["messages"][0]
    assert broadcast_msg["topic"] == "chat:target-user"
    assert broadcast_msg["event"] == "new_message"
    assert broadcast_msg["payload"]["content"] == (
        "--- Terry has retired from the chat and the AI will take over now ---"
    )


async def test_toggle_user_ai_disable_sets_admin_intervening(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    mock_add_message = MagicMock()
    monkeypatch.setattr(conversation_memory, "add_message", mock_add_message)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())

    import requests
    monkeypatch.setattr(requests, "post", MagicMock(return_value=SimpleNamespace(status_code=200, text="ok")))

    resp = await client.put("/admin/users/target-user/ai", json={"ai_enabled": False})

    assert resp.status_code == 200
    assert resp.json() == {"message": "AI disabled for user"}
    upsert_call = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert upsert_call["ai_enabled"] is False
    assert upsert_call["admin_intervening"] is True
    mock_add_message.assert_called_once_with(
        "target-user", "system",
        "--- Terry has joined the chat, the AI will retire for now ---",
        source="system",
    )


async def test_toggle_user_ai_requires_admin(client):
    resp = await client.put("/admin/users/target-user/ai", json={"ai_enabled": True})
    assert resp.status_code == 401


async def test_get_user_ai_status_success(client, admin_user, fake_supabase, patch_supabase):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    settings_mock = MagicMock()
    settings_mock.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"user_id": "target-user", "ai_enabled": False}]
    )
    fake_supabase.table.return_value = settings_mock

    resp = await client.get("/admin/users/target-user/ai")
    assert resp.status_code == 200
    assert resp.json() == {"user_id": "target-user", "ai_enabled": False}


async def test_get_user_ai_status_requires_admin(client):
    resp = await client.get("/admin/users/target-user/ai")
    assert resp.status_code == 401


# ===========================================================================
# DELETE /admin/users/{user_id}
# ===========================================================================

async def test_admin_delete_user_success(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user(user_id="admin-1", email="admin@example.com", ip="2.2.2.2")
    patch_supabase("connector", admin=fake_supabase)
    mock_audit = MagicMock()
    monkeypatch.setattr(admin_users, "write_audit", mock_audit)

    resp = await client.delete("/admin/users/doomed-user")

    assert resp.status_code == 200
    assert resp.json() == {"message": "User deleted successfully"}
    fake_supabase.auth.admin.delete_user.assert_called_once_with("doomed-user")
    mock_audit.assert_called_once_with("admin-1", "admin@example.com", "user.delete", "doomed-user", "2.2.2.2")


async def test_admin_delete_user_cleanup_exceptions_are_swallowed(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())
    # One of the three best-effort cleanup tables blows up.
    fake_supabase.table.return_value.delete.return_value.eq.return_value.execute.side_effect = Exception("row locked")

    resp = await client.delete("/admin/users/doomed-user")

    assert resp.status_code == 200
    fake_supabase.auth.admin.delete_user.assert_called_once_with("doomed-user")


async def test_admin_delete_user_auth_delete_failure_returns_500(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())
    fake_supabase.auth.admin.delete_user.side_effect = Exception("cannot delete")

    resp = await client.delete("/admin/users/doomed-user")

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to delete user"


async def test_admin_delete_user_requires_admin(client):
    resp = await client.delete("/admin/users/doomed-user")
    assert resp.status_code == 401


# ===========================================================================
# GET /admin/chats
# ===========================================================================

async def test_get_all_chats_marks_unread_when_last_message_from_human(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result(
        [{"id": "user-a", "display_name": "Profile Name", "avatar_url": "http://p/a.png"}]
    )
    user_a = make_user("user-a", email="a@example.com", metadata={})
    fake_supabase.auth.admin.list_users.return_value = [user_a]

    monkeypatch.setattr(
        conversation_memory,
        "get_all_histories",
        MagicMock(return_value={
            "user-a": [
                {"role": "ai", "content": "hello", "source": "ai"},
                {"role": "human", "content": "still waiting on a reply here", "source": "human"},
            ],
            "user-empty": [],
        }),
    )

    resp = await client.get("/admin/chats")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1  # empty history excluded
    chat = body[0]
    assert chat["user_id"] == "user-a"
    assert chat["display_name"] == "Profile Name"
    assert chat["message_count"] == 2
    assert chat["last_role"] == "human"
    assert chat["unread"] is True


async def test_get_all_chats_prefers_custom_avatar_over_provider_avatar(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result([])
    user_a = make_user("user-a", email="a@example.com", metadata={
        "display_name": "Alice",
        "custom_avatar_url": "http://cdn/uploaded.png",
        "avatar_url": "https://lh3.googleusercontent.com/a/google-photo",
    })
    fake_supabase.auth.admin.list_users.return_value = [user_a]

    monkeypatch.setattr(
        conversation_memory,
        "get_all_histories",
        MagicMock(return_value={"user-a": [{"role": "human", "content": "hi", "source": "human"}]}),
    )

    resp = await client.get("/admin/chats")

    assert resp.status_code == 200
    assert resp.json()[0]["avatar_url"] == "http://cdn/uploaded.png"


async def test_get_all_chats_not_unread_when_last_message_from_ai(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result([])
    fake_supabase.auth.admin.list_users.return_value = []

    monkeypatch.setattr(
        conversation_memory,
        "get_all_histories",
        MagicMock(return_value={
            "user-b": [{"role": "ai", "content": "already replied", "source": "ai"}],
        }),
    )

    resp = await client.get("/admin/chats")

    assert resp.status_code == 200
    chat = resp.json()[0]
    assert chat["unread"] is False
    assert chat["display_name"] == "Unknown user"  # no user/profile match at all


async def test_get_all_chats_enrichment_failure_falls_back_gracefully(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.execute.side_effect = Exception("profiles table down")

    monkeypatch.setattr(
        conversation_memory,
        "get_all_histories",
        MagicMock(return_value={"user-c": [{"role": "human", "content": "hi", "source": "human"}]}),
    )

    resp = await client.get("/admin/chats")

    assert resp.status_code == 200
    chat = resp.json()[0]
    assert chat["user_id"] == "user-c"
    assert chat["display_name"] == "Unknown user"
    assert chat["unread"] is True


async def test_get_all_chats_requires_admin(client):
    resp = await client.get("/admin/chats")
    assert resp.status_code == 401


# ===========================================================================
# GET /admin/chats/{user_id}
# ===========================================================================

async def test_get_user_chat_returns_history_with_paging_params(client, admin_user, monkeypatch):
    admin_user()
    mock_get_history = MagicMock(return_value=[{"role": "human", "content": "hi", "source": "human"}])
    monkeypatch.setattr(conversation_memory, "get_history", mock_get_history)

    resp = await client.get("/admin/chats/user-x?limit=5&offset=2")

    assert resp.status_code == 200
    assert resp.json() == {
        "user_id": "user-x",
        "messages": [{"role": "human", "content": "hi", "source": "human"}],
    }
    mock_get_history.assert_called_once_with("user-x", limit=5, offset=2)


async def test_get_user_chat_defaults(client, admin_user, monkeypatch):
    admin_user()
    mock_get_history = MagicMock(return_value=[])
    monkeypatch.setattr(conversation_memory, "get_history", mock_get_history)

    resp = await client.get("/admin/chats/user-x")

    assert resp.status_code == 200
    mock_get_history.assert_called_once_with("user-x", limit=10, offset=0)


async def test_get_user_chat_requires_admin(client):
    resp = await client.get("/admin/chats/user-x")
    assert resp.status_code == 401


# ===========================================================================
# POST /admin/chats/{user_id}/message
# ===========================================================================

async def test_admin_send_message_success(client, admin_user, monkeypatch):
    admin_user(user_id="admin-1", email="admin@example.com", ip="3.3.3.3")
    mock_add_message = MagicMock()
    monkeypatch.setattr(conversation_memory, "add_message", mock_add_message)
    mock_audit = MagicMock()
    monkeypatch.setattr(admin_chats, "write_audit", mock_audit)

    resp = await client.post("/admin/chats/user-x/message", json={"message": "Hi from the seller"})

    assert resp.status_code == 200
    assert resp.json() == {"message": "Message sent successfully"}
    mock_add_message.assert_called_once_with("user-x", "ai", "Hi from the seller", source="admin")
    mock_audit.assert_called_once_with("admin-1", "admin@example.com", "chat.message", "user-x", "3.3.3.3")


async def test_admin_send_message_requires_admin(client):
    resp = await client.post("/admin/chats/user-x/message", json={"message": "hi"})
    assert resp.status_code == 401
