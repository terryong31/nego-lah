"""
Tests for scripts/backfill_custom_avatar.py (SPEC-029).

The script does `from connector import admin_supabase` at import time, so — per
conftest.py's guidance — we patch `scripts.backfill_custom_avatar.admin_supabase`
directly; patching `connector.admin_supabase` would have no effect on the name
this module already bound.

conftest pins SUPABASE_URL=https://test-project.supabase.co and
STORAGE_BUCKET=test-images, which is what makes SELF_HOSTED below a "ours"
URL and the googleusercontent one a provider photo.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from scripts import backfill_custom_avatar as backfill

SELF_HOSTED = (
    "https://test-project.supabase.co/storage/v1/object/public/"
    "test-images/avatars/user-1/abc.png"
)
GOOGLE_PHOTO = "https://lh3.googleusercontent.com/a/google-photo"


def make_user(user_id, metadata=None, email=None):
    return SimpleNamespace(
        id=user_id,
        email=email or f"{user_id}@example.com",
        user_metadata=metadata or {},
    )


def fake_admin(*pages):
    """An admin_supabase whose list_users() returns each page in turn."""
    admin = MagicMock()
    admin.auth.admin.list_users.side_effect = list(pages)
    return admin


# ---------------------------------------------------------------------------
# is_self_hosted_avatar
# ---------------------------------------------------------------------------

def test_recognises_our_own_storage_url():
    assert backfill.is_self_hosted_avatar(SELF_HOSTED) is True


def test_rejects_provider_photos_and_junk():
    assert backfill.is_self_hosted_avatar(GOOGLE_PHOTO) is False
    assert backfill.is_self_hosted_avatar("") is False
    assert backfill.is_self_hosted_avatar(None) is False
    assert backfill.is_self_hosted_avatar(12345) is False
    # Right host and bucket, but not the avatars/ folder — an item image.
    assert backfill.is_self_hosted_avatar(
        "https://test-project.supabase.co/storage/v1/object/public/test-images/items/x.png"
    ) is False
    # A different Supabase project must never be treated as ours.
    assert backfill.is_self_hosted_avatar(
        "https://other-project.supabase.co/storage/v1/object/public/test-images/avatars/x.png"
    ) is False


# ---------------------------------------------------------------------------
# backfill()
# ---------------------------------------------------------------------------

def test_dry_run_reports_without_writing(monkeypatch):
    admin = fake_admin([make_user("u1", {"avatar_url": SELF_HOSTED})])
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    result = backfill.backfill(apply_changes=False)

    admin.auth.admin.update_user_by_id.assert_not_called()
    assert result["migrated"] == 1
    assert result["scanned"] == 1


def test_apply_copies_upload_to_custom_key_preserving_everything_else(monkeypatch):
    admin = fake_admin([
        make_user("u1", {
            "avatar_url": SELF_HOSTED,
            "display_name": "Terry",
            "preferred_language": "en",
        }),
    ])
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    result = backfill.backfill(apply_changes=True)

    admin.auth.admin.update_user_by_id.assert_called_once()
    user_id, payload = admin.auth.admin.update_user_by_id.call_args[0]
    assert user_id == "u1"
    meta = payload["user_metadata"]
    assert meta["custom_avatar_url"] == SELF_HOSTED
    # The provider-owned key is left exactly as it was, and so is the rest.
    assert meta["avatar_url"] == SELF_HOSTED
    assert meta["display_name"] == "Terry"
    assert meta["preferred_language"] == "en"
    assert result["migrated"] == 1
    assert result["failed"] == 0


def test_skips_users_already_backfilled(monkeypatch):
    admin = fake_admin([
        make_user("u1", {"avatar_url": SELF_HOSTED, "custom_avatar_url": SELF_HOSTED}),
    ])
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    result = backfill.backfill(apply_changes=True)

    admin.auth.admin.update_user_by_id.assert_not_called()
    assert result["migrated"] == 0
    assert result["skipped"] == 1


def test_skips_provider_photos_and_users_with_no_avatar(monkeypatch):
    admin = fake_admin([
        make_user("u1", {"avatar_url": GOOGLE_PHOTO}),
        make_user("u2", {}),
        make_user("u3", {"display_name": "No Avatar"}),
    ])
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    result = backfill.backfill(apply_changes=True)

    admin.auth.admin.update_user_by_id.assert_not_called()
    assert result["scanned"] == 3
    assert result["skipped"] == 3
    assert result["migrated"] == 0


def test_paginates_until_a_short_page(monkeypatch):
    full_page = [make_user(f"u{i}", {"avatar_url": SELF_HOSTED}) for i in range(backfill.PAGE_SIZE)]
    admin = fake_admin(full_page, [make_user("last", {"avatar_url": SELF_HOSTED})])
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    result = backfill.backfill(apply_changes=False)

    assert admin.auth.admin.list_users.call_count == 2
    assert result["scanned"] == backfill.PAGE_SIZE + 1


def test_stops_on_an_empty_page(monkeypatch):
    admin = fake_admin([make_user(f"u{i}", {}) for i in range(backfill.PAGE_SIZE)], [])
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    result = backfill.backfill(apply_changes=False)

    assert admin.auth.admin.list_users.call_count == 2
    assert result["scanned"] == backfill.PAGE_SIZE


def test_a_failing_user_does_not_abort_the_run(monkeypatch):
    admin = fake_admin([
        make_user("u1", {"avatar_url": SELF_HOSTED}),
        make_user("u2", {"avatar_url": SELF_HOSTED}),
    ])
    admin.auth.admin.update_user_by_id.side_effect = [RuntimeError("supabase down"), None]
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    result = backfill.backfill(apply_changes=True)

    assert admin.auth.admin.update_user_by_id.call_count == 2
    assert result["failed"] == 1
    assert result["migrated"] == 1


def test_handles_a_paginated_response_object(monkeypatch):
    """Older supabase-py returns an object with `.users` rather than a list."""
    admin = fake_admin(SimpleNamespace(users=[make_user("u1", {"avatar_url": SELF_HOSTED})]))
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    result = backfill.backfill(apply_changes=False)

    assert result["scanned"] == 1
    assert result["migrated"] == 1


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_defaults_to_dry_run(monkeypatch):
    admin = fake_admin([make_user("u1", {"avatar_url": SELF_HOSTED})])
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    assert backfill.main([]) == 0
    admin.auth.admin.update_user_by_id.assert_not_called()


def test_main_writes_only_with_apply(monkeypatch):
    admin = fake_admin([make_user("u1", {"avatar_url": SELF_HOSTED})])
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    assert backfill.main(["--apply"]) == 0
    admin.auth.admin.update_user_by_id.assert_called_once()


def test_main_exits_nonzero_when_a_user_failed(monkeypatch):
    admin = fake_admin([make_user("u1", {"avatar_url": SELF_HOSTED})])
    admin.auth.admin.update_user_by_id.side_effect = RuntimeError("supabase down")
    monkeypatch.setattr(backfill, "admin_supabase", admin)

    assert backfill.main(["--apply"]) == 1
