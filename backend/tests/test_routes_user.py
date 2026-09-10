"""Tests for routes/user.py — account status, password/email/profile updates, and deletion.

routes/user.py imports `admin_supabase` and `user_supabase` from `connector` at
module import time, so both are patched via `patch_supabase("routes.user", ...)`
per conftest.py's guidance. `Depends(verify_user_token)` is bypassed with the
`auth_user` fixture; the "User ID mismatch" 403 path is exercised by calling
`auth_user()` with one id and hitting a different `{user_id}` in the URL.
"""

from unittest.mock import MagicMock

import pytest

from conftest import PNG_BYTES
from core.uploads import MAX_AVATAR_IMAGE_BYTES

# ---------------------------------------------------------------------------
# GET /user/{id}/account
# ---------------------------------------------------------------------------

async def test_account_status_ok(client, auth_user):
    auth_user("user-1")
    resp = await client.get("/user/user-1/account")
    assert resp.status_code == 200
    assert resp.json() == {"banned": False}


async def test_account_status_id_mismatch(client, auth_user):
    auth_user("user-1")
    resp = await client.get("/user/someone-else/account")
    assert resp.status_code == 403
    assert "User ID mismatch" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# PUT /user/{id}/password
# ---------------------------------------------------------------------------

def _user_by_id_result(email="user@example.com"):
    result = MagicMock()
    result.user.email = email
    return result


@pytest.fixture
def session_client(monkeypatch):
    """Stand in for the per-request anon client `routes.user` builds to re-auth.

    SPEC-056 #3/#7: password verification (and, for an email change, the update
    that follows it) runs on a client created for that one request, never on the
    shared `user_supabase` singleton. Returns the mock so a test can make the
    sign-in fail or assert what was called on it.
    """
    client = MagicMock()

    def _apply():
        monkeypatch.setattr("routes.user.new_user_client", lambda: client)
        return client

    return _apply


async def _delete_account(client, user_id="user-1", password="oldpass123", **kwargs):
    """DELETE carries a body here — the re-auth password (SPEC-056 #7)."""
    body = {} if password is None else {"current_password": password}
    return await client.request("DELETE", f"/user/{user_id}", json=body, **kwargs)


async def test_change_password_success(client, auth_user, patch_supabase, session_client):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session = session_client()

    resp = await client.put(
        "/user/user-1/password",
        json={"current_password": "oldpass123", "new_password": "newpass456"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"message": "Password changed successfully"}
    session.auth.sign_in_with_password.assert_called_once_with(
        {"email": "user@example.com", "password": "oldpass123"}
    )
    fake_admin.auth.admin.update_user_by_id.assert_called_once_with(
        "user-1", {"password": "newpass456"}
    )


async def test_change_password_id_mismatch(client, auth_user, patch_supabase):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    resp = await client.put(
        "/user/other-user/password",
        json={"current_password": "oldpass123", "new_password": "newpass456"},
    )
    assert resp.status_code == 403


async def test_change_password_user_not_found(client, auth_user, patch_supabase):
    """_get_user_email raises 404 when admin_supabase reports no user."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = MagicMock(user=None)
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/password",
        json={"current_password": "oldpass123", "new_password": "newpass456"},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"


async def test_change_password_wrong_current_password(client, auth_user, patch_supabase, session_client):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session_client().auth.sign_in_with_password.side_effect = Exception("invalid credentials")

    resp = await client.put(
        "/user/user-1/password",
        json={"current_password": "wrongpass", "new_password": "newpass456"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Current password is incorrect"
    fake_admin.auth.admin.update_user_by_id.assert_not_called()


async def test_change_password_update_fails(client, auth_user, patch_supabase, session_client):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    fake_admin.auth.admin.update_user_by_id.side_effect = Exception("db down")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session_client()

    resp = await client.put(
        "/user/user-1/password",
        json={"current_password": "oldpass123", "new_password": "newpass456"},
    )

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to change password"


async def test_change_password_validation_error(client, auth_user, patch_supabase):
    """Missing required fields should trigger FastAPI/pydantic validation, not reach supabase."""
    auth_user("user-1")
    fake_admin = MagicMock()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put("/user/user-1/password", json={"current_password": "onlyone"})

    assert resp.status_code == 422
    fake_admin.auth.admin.get_user_by_id.assert_not_called()


# ---------------------------------------------------------------------------
# PUT /user/{id}/email
# ---------------------------------------------------------------------------

async def test_change_email_requires_the_current_password(client, auth_user, patch_supabase):
    """SPEC-056 #3. Identity is the one field a stolen access token must not be
    able to rewrite on its own — rewriting it locks the real owner out for good."""
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())

    resp = await client.put("/user/user-1/email", json={"new_email": "attacker@evil.test"})

    assert resp.status_code == 422


async def test_change_email_rejects_a_wrong_current_password(client, auth_user, patch_supabase, session_client):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session = session_client()
    session.auth.sign_in_with_password.side_effect = Exception("invalid credentials")

    resp = await client.put(
        "/user/user-1/email",
        json={"new_email": "attacker@evil.test", "current_password": "guess"},
    )

    assert resp.status_code == 401
    assert "incorrect" in resp.json()["detail"].lower()
    session.auth.update_user.assert_not_called()
    fake_admin.auth.admin.update_user_by_id.assert_not_called()


async def test_change_email_asks_supabase_to_confirm_instead_of_flipping_it(
    client, auth_user, patch_supabase, session_client
):
    """`email_confirm: True` on the admin API marks the new address verified with
    no mail sent to either party. The change must instead run on the user's own
    session, which is what makes Supabase send the confirmation link."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session = session_client()

    resp = await client.put(
        "/user/user-1/email",
        json={"new_email": "new@example.com", "current_password": "oldpass123"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert body["confirmation_required"] is True
    session.auth.sign_in_with_password.assert_called_once_with(
        {"email": "user@example.com", "password": "oldpass123"}
    )
    session.auth.update_user.assert_called_once_with({"email": "new@example.com"})
    fake_admin.auth.admin.update_user_by_id.assert_not_called()


def test_the_module_holds_no_shared_anon_client():
    """`user_supabase` is a module-level singleton, so signing in on it writes the
    session into state shared by every concurrent request — an operation that
    then *acts as* that user could act as somebody else instead. routes/user.py
    re-authenticates on a per-request client and must not keep the singleton
    around for someone to reach for by accident."""
    import routes.user

    assert not hasattr(routes.user, "user_supabase")


async def test_change_email_id_mismatch(client, auth_user, patch_supabase):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    resp = await client.put(
        "/user/other-user/email",
        json={"new_email": "new@example.com", "current_password": "oldpass123"},
    )
    assert resp.status_code == 403


async def test_change_email_update_fails(client, auth_user, patch_supabase, session_client):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session = session_client()
    session.auth.update_user.side_effect = Exception("boom")

    resp = await client.put(
        "/user/user-1/email",
        json={"new_email": "new@example.com", "current_password": "oldpass123"},
    )

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to change email"


async def test_change_email_validation_error(client, auth_user, patch_supabase):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    resp = await client.put("/user/user-1/email", json={})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PUT /user/{id}/profile
# ---------------------------------------------------------------------------

def _existing_user_result(metadata=None):
    result = MagicMock()
    result.user.user_metadata = metadata or {}
    return result


async def test_update_profile_display_name_only(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result({"foo": "bar"})
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        data={"display_name": "New Name"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "New Name"
    assert body["avatar_url"] is None
    fake_admin.storage.from_.assert_not_called()
    updated_metadata = fake_admin.auth.admin.update_user_by_id.call_args[0][1]["user_metadata"]
    assert updated_metadata["display_name"] == "New Name"
    assert updated_metadata["foo"] == "bar"  # existing metadata preserved


async def test_update_profile_with_avatar_success(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result()
    fake_admin.storage.from_.return_value.get_public_url.return_value = (
        "https://cdn.example.com/avatars/user-1/abc.png"
    )
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    small_file = PNG_BYTES
    resp = await client.put(
        "/user/user-1/profile",
        data={"display_name": "Avatar User"},
        files={"avatar": ("photo.png", small_file, "image/png")},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["avatar_url"] == "https://cdn.example.com/avatars/user-1/abc.png"
    assert body["display_name"] == "Avatar User"

    fake_admin.storage.from_.return_value.upload.assert_called_once()
    upload_args = fake_admin.storage.from_.return_value.upload.call_args[0]
    file_path = upload_args[0]
    assert file_path.startswith("avatars/user-1/")
    assert file_path.endswith(".png")
    assert upload_args[1] == small_file
    upload_opts = upload_args[2]
    assert upload_opts["content-type"] == "image/png"
    assert upload_opts["upsert"] == "true"

    # The uploaded URL goes to `custom_avatar_url`, NOT `avatar_url`. Supabase
    # refreshes user_metadata from the identity provider on every OAuth
    # sign-in, so anything written to a key Google also sets (`avatar_url`,
    # `picture`) is silently replaced by the Google photo on the next login.
    updated_metadata = fake_admin.auth.admin.update_user_by_id.call_args[0][1]["user_metadata"]
    assert updated_metadata["custom_avatar_url"] == "https://cdn.example.com/avatars/user-1/abc.png"


async def test_update_profile_avatar_preserves_google_avatar_url(client, auth_user, patch_supabase):
    """Uploading an avatar must not clobber the provider-owned `avatar_url` key."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result({
        "avatar_url": "https://lh3.googleusercontent.com/a/google-photo",
        "picture": "https://lh3.googleusercontent.com/a/google-photo",
    })
    fake_admin.storage.from_.return_value.get_public_url.return_value = (
        "https://cdn.example.com/avatars/user-1/uploaded.png"
    )
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("photo.png", PNG_BYTES, "image/png")},
    )

    assert resp.status_code == 200
    updated_metadata = fake_admin.auth.admin.update_user_by_id.call_args[0][1]["user_metadata"]
    assert updated_metadata["custom_avatar_url"] == "https://cdn.example.com/avatars/user-1/uploaded.png"
    assert updated_metadata["avatar_url"] == "https://lh3.googleusercontent.com/a/google-photo"

    # The response reports the *effective* avatar, which is now the upload.
    assert resp.json()["avatar_url"] == "https://cdn.example.com/avatars/user-1/uploaded.png"


async def test_update_profile_reports_provider_avatar_when_no_upload(client, auth_user, patch_supabase):
    """A user who never uploaded still gets their provider photo back."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result({
        "avatar_url": "https://lh3.googleusercontent.com/a/google-photo",
    })
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put("/user/user-1/profile", data={"display_name": "No Upload"})

    assert resp.status_code == 200
    assert resp.json()["avatar_url"] == "https://lh3.googleusercontent.com/a/google-photo"


async def test_update_profile_avatar_too_large(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    big_file = PNG_BYTES + b"\x00" * (MAX_AVATAR_IMAGE_BYTES + 1 - len(PNG_BYTES))
    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("big.png", big_file, "image/png")},
    )

    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()
    fake_admin.storage.from_.return_value.upload.assert_not_called()
    fake_admin.auth.admin.update_user_by_id.assert_not_called()


async def test_update_profile_avatar_exactly_at_the_ceiling_allowed(client, auth_user, patch_supabase):
    """Boundary check: exactly at the ceiling should NOT be rejected.

    SPEC-054 raised that ceiling from 2 MB to 8 MB, because the limit is
    measured on the bytes that arrive and a raw HEIC frame off a modern phone
    clears 2 MB on its own — the old limit rejected the very format the
    conversion pipeline exists to accept. What gets *stored* is the normalized
    output, which is a fraction of this."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result()
    fake_admin.storage.from_.return_value.get_public_url.return_value = "https://cdn/x.png"
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    exact_file = PNG_BYTES + b"\x00" * (MAX_AVATAR_IMAGE_BYTES - len(PNG_BYTES))
    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("exact.png", exact_file, "image/png")},
    )

    assert resp.status_code == 200


async def test_update_profile_avatar_upload_failure(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result()
    fake_admin.storage.from_.return_value.upload.side_effect = Exception("storage down")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("photo.png", PNG_BYTES, "image/png")},
    )

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to upload avatar"
    fake_admin.auth.admin.update_user_by_id.assert_not_called()


async def test_update_profile_avatar_filename_is_never_used_for_the_extension(
    client, auth_user, patch_supabase
):
    """The extension used to be `filename.rsplit(".", 1)[-1]`, so a filename
    with no dot became the extension in its entirety ("avatar" -> ".avatar")
    and a filename with slashes walked out of the user's prefix. SPEC-044 C
    takes the extension from the sniffed type instead, so the filename no
    longer reaches the storage key by any route."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result()
    fake_admin.storage.from_.return_value.get_public_url.return_value = "https://cdn/x.png"
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("avatar", PNG_BYTES, "image/png")},
    )

    assert resp.status_code == 200
    upload_args = fake_admin.storage.from_.return_value.upload.call_args[0]
    file_path = upload_args[0]
    assert file_path.endswith(".png")
    assert "avatar" not in file_path.removeprefix("avatars/")


async def test_update_profile_user_not_found(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = MagicMock(user=None)
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put("/user/user-1/profile", data={"display_name": "X"})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"


async def test_update_profile_update_call_fails(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result()
    fake_admin.auth.admin.update_user_by_id.side_effect = Exception("boom")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put("/user/user-1/profile", data={"display_name": "X"})

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to update profile"


async def test_update_profile_id_mismatch(client, auth_user, patch_supabase):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    resp = await client.put("/user/other-user/profile", data={"display_name": "X"})
    assert resp.status_code == 403


async def test_update_profile_no_fields_changed(client, auth_user, patch_supabase):
    """Neither display_name nor avatar provided: existing metadata is resubmitted unchanged."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result({"display_name": "Old"})
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put("/user/user-1/profile")

    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "Old"
    assert body["avatar_url"] is None


# ---------------------------------------------------------------------------
# DELETE /user/{id}
# ---------------------------------------------------------------------------

async def test_delete_account_success(client, auth_user, patch_supabase, session_client):
    auth_user("user-1")
    fake_admin = MagicMock()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session_client()

    resp = await _delete_account(client, headers={"Authorization": "Bearer sometoken123"})

    assert resp.status_code == 200
    assert resp.json() == {"message": "Account deleted successfully"}
    fake_admin.auth.admin.delete_user.assert_called_once_with("user-1")
    # Cleanup covers every table holding this user's data. `messages` is the
    # SPEC-043 history table; `conversations` still holds whatever was written
    # before that cutover, so deleting an account has to clear both or a
    # deleted user's transcript outlives their account.
    cleaned_tables = [call.args[0] for call in fake_admin.table.call_args_list]
    assert cleaned_tables == ["chat_settings", "conversations", "messages", "user_profiles"]


async def test_delete_account_invalidates_token(client, auth_user, patch_supabase, monkeypatch, session_client):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    session_client()
    fake_invalidate = MagicMock()
    monkeypatch.setattr("routes.user.invalidate_token", fake_invalidate)

    resp = await _delete_account(client, headers={"Authorization": "Bearer abc.def.ghi"})

    assert resp.status_code == 200
    fake_invalidate.assert_called_once_with("abc.def.ghi")


async def test_delete_account_no_auth_header_skips_invalidate(client, auth_user, patch_supabase, monkeypatch, session_client):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    session_client()
    fake_invalidate = MagicMock()
    monkeypatch.setattr("routes.user.invalidate_token", fake_invalidate)

    resp = await _delete_account(client)

    assert resp.status_code == 200
    fake_invalidate.assert_not_called()


async def test_delete_account_cleanup_failures_are_non_fatal(client, auth_user, patch_supabase, session_client):
    """Cleanup errors on app-side tables should be swallowed; the account is still deleted."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.table.return_value.delete.return_value.eq.return_value.execute.side_effect = (
        Exception("table missing")
    )
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session_client()

    resp = await _delete_account(client)

    assert resp.status_code == 200
    assert resp.json() == {"message": "Account deleted successfully"}
    fake_admin.auth.admin.delete_user.assert_called_once_with("user-1")


async def test_delete_account_auth_delete_fails(client, auth_user, patch_supabase, session_client):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.delete_user.side_effect = Exception("boom")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session_client()

    resp = await _delete_account(client)

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to delete account"


async def test_delete_account_id_mismatch(client, auth_user, patch_supabase, session_client):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    session_client()
    resp = await _delete_account(client, user_id="other-user")
    assert resp.status_code == 403


async def test_delete_account_requires_the_current_password(client, auth_user, patch_supabase, session_client):
    """SPEC-056 #7. Deletion is irreversible and wipes the transcript, so an
    access token alone must not be enough to trigger it."""
    auth_user("user-1")
    fake_admin = MagicMock()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session_client()

    resp = await _delete_account(client, password=None)

    assert resp.status_code == 422
    fake_admin.auth.admin.delete_user.assert_not_called()


async def test_delete_account_rejects_a_wrong_password(client, auth_user, patch_supabase, session_client):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session_client().auth.sign_in_with_password.side_effect = Exception("invalid credentials")

    resp = await _delete_account(client, password="guess")

    assert resp.status_code == 401
    fake_admin.auth.admin.delete_user.assert_not_called()
    fake_admin.table.assert_not_called(), "no cleanup may run before re-auth succeeds"


async def test_repeated_wrong_passwords_lock_the_account_not_the_address(
    client, auth_user, patch_supabase, session_client
):
    """SPEC-056 #7. The counter is keyed on the account under attack, so it holds
    however many addresses the guessing comes from — and a roomful of people
    behind one NAT address never trips it for each other."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())
    session_client().auth.sign_in_with_password.side_effect = Exception("invalid credentials")

    from routes.user import REAUTH_MAX_ATTEMPTS

    for _ in range(REAUTH_MAX_ATTEMPTS):
        assert (await _delete_account(client, password="guess")).status_code == 401

    blocked = await _delete_account(client, password="guess")
    assert blocked.status_code == 429

    # A different account is unaffected — the limit is not a global or per-IP one.
    auth_user("user-2")
    assert (await _delete_account(client, user_id="user-2", password="guess")).status_code == 401
