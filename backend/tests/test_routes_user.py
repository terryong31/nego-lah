"""Tests for routes/user.py — account status, password/email/profile updates, and deletion.

routes/user.py imports `admin_supabase` and `user_supabase` from `connector` at
module import time, so both are patched via `patch_supabase("routes.user", ...)`
per conftest.py's guidance. `Depends(verify_user_token)` is bypassed with the
`auth_user` fixture; the "User ID mismatch" 403 path is exercised by calling
`auth_user()` with one id and hitting a different `{user_id}` in the URL.
"""

from unittest.mock import MagicMock

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


async def test_change_password_success(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_user = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    patch_supabase("routes.user", admin=fake_admin, user=fake_user)

    resp = await client.put(
        "/user/user-1/password",
        json={"current_password": "oldpass123", "new_password": "newpass456"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"message": "Password changed successfully"}
    fake_user.auth.sign_in_with_password.assert_called_once_with(
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


async def test_change_password_wrong_current_password(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_user = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    fake_user.auth.sign_in_with_password.side_effect = Exception("invalid credentials")
    patch_supabase("routes.user", admin=fake_admin, user=fake_user)

    resp = await client.put(
        "/user/user-1/password",
        json={"current_password": "wrongpass", "new_password": "newpass456"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Current password is incorrect"
    fake_admin.auth.admin.update_user_by_id.assert_not_called()


async def test_change_password_update_fails(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_user = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _user_by_id_result("user@example.com")
    fake_admin.auth.admin.update_user_by_id.side_effect = Exception("db down")
    patch_supabase("routes.user", admin=fake_admin, user=fake_user)

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

async def test_change_email_success(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put("/user/user-1/email", json={"new_email": "new@example.com"})

    assert resp.status_code == 200
    assert resp.json() == {"message": "Email changed successfully", "email": "new@example.com"}
    fake_admin.auth.admin.update_user_by_id.assert_called_once_with(
        "user-1", {"email": "new@example.com", "email_confirm": True}
    )


async def test_change_email_id_mismatch(client, auth_user, patch_supabase):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    resp = await client.put("/user/other-user/email", json={"new_email": "new@example.com"})
    assert resp.status_code == 403


async def test_change_email_update_fails(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.update_user_by_id.side_effect = Exception("boom")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put("/user/user-1/email", json={"new_email": "new@example.com"})

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

    small_file = b"x" * 100
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


async def test_update_profile_avatar_too_large(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    big_file = b"x" * (2 * 1024 * 1024 + 1)
    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("big.png", big_file, "image/png")},
    )

    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()
    fake_admin.storage.from_.return_value.upload.assert_not_called()
    fake_admin.auth.admin.update_user_by_id.assert_not_called()


async def test_update_profile_avatar_exactly_2mb_allowed(client, auth_user, patch_supabase):
    """Boundary check: exactly 2MB should NOT trigger the 'too large' rejection."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result()
    fake_admin.storage.from_.return_value.get_public_url.return_value = "https://cdn/x.png"
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    exact_file = b"x" * (2 * 1024 * 1024)
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
        files={"avatar": ("photo.png", b"small", "image/png")},
    )

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to upload avatar"
    fake_admin.auth.admin.update_user_by_id.assert_not_called()


async def test_update_profile_avatar_filename_without_extension(client, auth_user, patch_supabase):
    """When the uploaded filename has no dot, the whole filename is (naively) used as the ext."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.get_user_by_id.return_value = _existing_user_result()
    fake_admin.storage.from_.return_value.get_public_url.return_value = "https://cdn/x.png"
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.put(
        "/user/user-1/profile",
        files={"avatar": ("avatar", b"small", "image/png")},
    )

    assert resp.status_code == 200
    upload_args = fake_admin.storage.from_.return_value.upload.call_args[0]
    file_path = upload_args[0]
    # No "." in "avatar" means rsplit(".", 1)[-1] falls back to the whole filename.
    assert file_path.endswith(".avatar")


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

async def test_delete_account_success(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.delete(
        "/user/user-1", headers={"Authorization": "Bearer sometoken123"}
    )

    assert resp.status_code == 200
    assert resp.json() == {"message": "Account deleted successfully"}
    fake_admin.auth.admin.delete_user.assert_called_once_with("user-1")
    # cleanup ran against all three tables
    cleaned_tables = [call.args[0] for call in fake_admin.table.call_args_list]
    assert cleaned_tables == ["chat_settings", "conversations", "user_profiles"]


async def test_delete_account_invalidates_token(client, auth_user, patch_supabase, monkeypatch):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    fake_invalidate = MagicMock()
    monkeypatch.setattr("routes.user.invalidate_token", fake_invalidate)

    resp = await client.delete(
        "/user/user-1", headers={"Authorization": "Bearer abc.def.ghi"}
    )

    assert resp.status_code == 200
    fake_invalidate.assert_called_once_with("abc.def.ghi")


async def test_delete_account_no_auth_header_skips_invalidate(client, auth_user, patch_supabase, monkeypatch):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    fake_invalidate = MagicMock()
    monkeypatch.setattr("routes.user.invalidate_token", fake_invalidate)

    resp = await client.delete("/user/user-1")

    assert resp.status_code == 200
    fake_invalidate.assert_not_called()


async def test_delete_account_cleanup_failures_are_non_fatal(client, auth_user, patch_supabase):
    """Cleanup errors on app-side tables should be swallowed; the account is still deleted."""
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.table.return_value.delete.return_value.eq.return_value.execute.side_effect = (
        Exception("table missing")
    )
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.delete("/user/user-1")

    assert resp.status_code == 200
    assert resp.json() == {"message": "Account deleted successfully"}
    fake_admin.auth.admin.delete_user.assert_called_once_with("user-1")


async def test_delete_account_auth_delete_fails(client, auth_user, patch_supabase):
    auth_user("user-1")
    fake_admin = MagicMock()
    fake_admin.auth.admin.delete_user.side_effect = Exception("boom")
    patch_supabase("routes.user", admin=fake_admin, user=MagicMock())

    resp = await client.delete("/user/user-1")

    assert resp.status_code == 500
    assert resp.json()["detail"] == "Failed to delete account"


async def test_delete_account_id_mismatch(client, auth_user, patch_supabase):
    auth_user("user-1")
    patch_supabase("routes.user", admin=MagicMock(), user=MagicMock())
    resp = await client.delete("/user/other-user")
    assert resp.status_code == 403
