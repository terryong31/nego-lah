"""
Tests for the operator CLI scripts: scripts/create_admin.py, scripts/promote_admin.py,
and scripts/unban_user.py.

These are not imported by the FastAPI app -- they're invoked directly as
`python -m scripts.<name> ...`. We import them as modules and call main()/helper
functions directly, mocking `admin_supabase` (module-level `from connector import
admin_supabase` binding, so we patch the name on the *consuming* script module) and
`grant_admin`/`revoke_admin` (same story, `from admin_session import ...`) plus
`sys.argv` and capturing stdout via `capsys`.
"""
import sys
from types import SimpleNamespace

import pytest

import scripts.create_admin as create_admin
import scripts.promote_admin as promote_admin
import scripts.unban_user as unban_user


class FakeUser:
    """Minimal stand-in for a supabase-py gotrue User object."""

    def __init__(self, id, email, app_metadata=None):
        self.id = id
        self.email = email
        self.app_metadata = app_metadata


# ---------------------------------------------------------------------------
# scripts/create_admin.py
# ---------------------------------------------------------------------------


def test_create_admin_find_user_returns_none_when_first_page_empty(monkeypatch, fake_supabase):
    fake_supabase.auth.admin.list_users.return_value = []
    monkeypatch.setattr(create_admin, "admin_supabase", fake_supabase)

    assert create_admin._find_user("nobody@example.com") is None
    fake_supabase.auth.admin.list_users.assert_called_once_with(page=1, per_page=200)


def test_create_admin_find_user_matches_on_first_page(monkeypatch, fake_supabase):
    target = FakeUser("u-1", "Match@Example.com")
    fake_supabase.auth.admin.list_users.return_value = [FakeUser("u-0", "other@example.com"), target]
    monkeypatch.setattr(create_admin, "admin_supabase", fake_supabase)

    # Case-insensitive match against a lowercase query.
    found = create_admin._find_user("match@example.com")
    assert found is target


def test_create_admin_find_user_paginates_across_pages(monkeypatch, fake_supabase):
    page1 = [FakeUser(f"u-{i}", f"user{i}@example.com") for i in range(200)]
    target = FakeUser("u-target", "target@example.com")
    page2 = [target]
    fake_supabase.auth.admin.list_users.side_effect = [page1, page2]
    monkeypatch.setattr(create_admin, "admin_supabase", fake_supabase)

    found = create_admin._find_user("target@example.com")
    assert found is target
    assert fake_supabase.auth.admin.list_users.call_count == 2
    fake_supabase.auth.admin.list_users.assert_any_call(page=1, per_page=200)
    fake_supabase.auth.admin.list_users.assert_any_call(page=2, per_page=200)


def test_create_admin_find_user_stops_when_full_last_page_has_no_match(monkeypatch, fake_supabase):
    # A page of exactly 200 with no match still triggers another fetch; when
    # that next page comes back empty, _find_user gives up and returns None.
    page1 = [FakeUser(f"u-{i}", f"user{i}@example.com") for i in range(200)]
    fake_supabase.auth.admin.list_users.side_effect = [page1, []]
    monkeypatch.setattr(create_admin, "admin_supabase", fake_supabase)

    assert create_admin._find_user("missing@example.com") is None
    assert fake_supabase.auth.admin.list_users.call_count == 2


def test_create_admin_find_user_handles_none_email_on_user(monkeypatch, fake_supabase):
    # A user record with no email set at all should not blow up the comparison.
    fake_supabase.auth.admin.list_users.return_value = [FakeUser("u-1", None)]
    monkeypatch.setattr(create_admin, "admin_supabase", fake_supabase)

    assert create_admin._find_user("someone@example.com") is None


def test_create_admin_find_user_handles_envelope_response(monkeypatch, fake_supabase):
    """A newer SDK may return an object with a `.users` attribute instead of a
    bare list; _find_user should unwrap it rather than silently break."""
    target = FakeUser("u-9", "boss@example.com")
    envelope = SimpleNamespace(users=[FakeUser("u-8", "other@example.com"), target])
    fake_supabase.auth.admin.list_users.return_value = envelope
    monkeypatch.setattr(create_admin, "admin_supabase", fake_supabase)

    assert create_admin._find_user("boss@example.com") is target


def test_create_admin_main_wrong_argv_prints_usage_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["create_admin.py", "only-one-arg"])

    with pytest.raises(SystemExit) as exc_info:
        create_admin.main()

    assert exc_info.value.code == 2
    out = capsys.readouterr().out
    assert create_admin.__doc__ in out


def test_create_admin_main_creates_new_user_when_not_found(monkeypatch, capsys, fake_supabase):
    fake_supabase.auth.admin.list_users.return_value = []
    created_return = fake_supabase.auth.admin.create_user.return_value
    created_return.user.id = "new-user-id"

    from unittest.mock import MagicMock

    grant_mock = MagicMock()
    monkeypatch.setattr(create_admin, "admin_supabase", fake_supabase)
    monkeypatch.setattr(create_admin, "grant_admin", grant_mock)
    monkeypatch.setattr(sys, "argv", ["create_admin.py", "New@Example.com", "s3cret"])

    create_admin.main()

    fake_supabase.auth.admin.create_user.assert_called_once_with({
        "email": "new@example.com",
        "password": "s3cret",
        "email_confirm": True,
        "app_metadata": {"role": "admin"},
    })
    grant_mock.assert_called_once_with("new-user-id", "new@example.com")

    out = capsys.readouterr().out
    assert "Created user new@example.com (new-user-id)" in out
    assert "Admin allowlist updated" in out
    assert "/_console/login" in out


def test_create_admin_main_updates_existing_user_and_merges_app_metadata(monkeypatch, capsys, fake_supabase):
    existing = FakeUser("existing-id", "existing@example.com", app_metadata={"plan": "pro"})
    fake_supabase.auth.admin.list_users.return_value = [existing]

    from unittest.mock import MagicMock
    grant_mock = MagicMock()
    monkeypatch.setattr(create_admin, "admin_supabase", fake_supabase)
    monkeypatch.setattr(create_admin, "grant_admin", grant_mock)
    monkeypatch.setattr(sys, "argv", ["create_admin.py", "existing@example.com", "newpass"])

    create_admin.main()

    fake_supabase.auth.admin.update_user_by_id.assert_called_once_with("existing-id", {
        "password": "newpass",
        "email_confirm": True,
        "app_metadata": {"plan": "pro", "role": "admin"},
    })
    grant_mock.assert_called_once_with("existing-id", "existing@example.com")

    out = capsys.readouterr().out
    assert "Updated existing user existing@example.com (existing-id)" in out


def test_create_admin_main_existing_user_with_none_app_metadata(monkeypatch, capsys, fake_supabase):
    # existing.app_metadata is None -> {**(None or {}), "role": "admin"} == {"role": "admin"}
    existing = FakeUser("existing-id-2", "noattrs@example.com", app_metadata=None)
    fake_supabase.auth.admin.list_users.return_value = [existing]

    from unittest.mock import MagicMock
    monkeypatch.setattr(create_admin, "admin_supabase", fake_supabase)
    monkeypatch.setattr(create_admin, "grant_admin", MagicMock())
    monkeypatch.setattr(sys, "argv", ["create_admin.py", "noattrs@example.com", "pw"])

    create_admin.main()

    fake_supabase.auth.admin.update_user_by_id.assert_called_once_with("existing-id-2", {
        "password": "pw",
        "email_confirm": True,
        "app_metadata": {"role": "admin"},
    })


# ---------------------------------------------------------------------------
# scripts/promote_admin.py
# ---------------------------------------------------------------------------


def test_promote_admin_find_user_paginates_and_matches(monkeypatch, fake_supabase):
    page1 = [FakeUser(f"u-{i}", f"user{i}@example.com") for i in range(200)]
    target = FakeUser("u-target", "Target@Example.com")
    fake_supabase.auth.admin.list_users.side_effect = [page1, [target]]
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)

    found = promote_admin._find_user("target@example.com")
    assert found is target
    assert fake_supabase.auth.admin.list_users.call_count == 2


def test_promote_admin_find_user_returns_none_when_no_pages(monkeypatch, fake_supabase):
    fake_supabase.auth.admin.list_users.return_value = []
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)

    assert promote_admin._find_user("nobody@example.com") is None


def test_promote_admin_find_user_returns_none_when_partial_last_page_has_no_match(monkeypatch, fake_supabase):
    # A page with fewer than 200 users (the "last page") and no match should
    # return None directly, without requesting a further page.
    fake_supabase.auth.admin.list_users.return_value = [FakeUser("u-1", "someone-else@example.com")]
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)

    assert promote_admin._find_user("nobody@example.com") is None
    fake_supabase.auth.admin.list_users.assert_called_once_with(page=1, per_page=200)


def test_promote_admin_find_user_handles_envelope_response(monkeypatch, fake_supabase):
    """Envelope-wrapped list_users response should be unwrapped, same as create_admin."""
    target = FakeUser("u-3", "lead@example.com")
    envelope = SimpleNamespace(users=[target])
    fake_supabase.auth.admin.list_users.return_value = envelope
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)

    assert promote_admin._find_user("lead@example.com") is target


def test_promote_admin_grant_user_not_found_exits_1(monkeypatch, capsys, fake_supabase):
    fake_supabase.auth.admin.list_users.return_value = []
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)

    with pytest.raises(SystemExit) as exc_info:
        promote_admin.grant("ghost@example.com")

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "No Supabase user found for ghost@example.com" in out
    fake_supabase.auth.admin.update_user_by_id.assert_not_called()


def test_promote_admin_grant_success_merges_app_metadata(monkeypatch, capsys, fake_supabase):
    user = FakeUser("u-1", "user@example.com", app_metadata={"plan": "pro"})
    fake_supabase.auth.admin.list_users.return_value = [user]

    from unittest.mock import MagicMock
    grant_mock = MagicMock()
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)
    monkeypatch.setattr(promote_admin, "grant_admin", grant_mock)

    promote_admin.grant("user@example.com")

    fake_supabase.auth.admin.update_user_by_id.assert_called_once_with(
        "u-1", {"app_metadata": {"plan": "pro", "role": "admin"}}
    )
    grant_mock.assert_called_once_with("u-1", "user@example.com")
    out = capsys.readouterr().out
    assert "Granted admin to user@example.com (u-1)" in out


def test_promote_admin_grant_success_with_no_existing_app_metadata(monkeypatch, capsys, fake_supabase):
    user = FakeUser("u-2", "bare@example.com", app_metadata=None)
    fake_supabase.auth.admin.list_users.return_value = [user]

    from unittest.mock import MagicMock
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)
    monkeypatch.setattr(promote_admin, "grant_admin", MagicMock())

    promote_admin.grant("bare@example.com")

    fake_supabase.auth.admin.update_user_by_id.assert_called_once_with(
        "u-2", {"app_metadata": {"role": "admin"}}
    )


def test_promote_admin_revoke_user_not_found_exits_1(monkeypatch, capsys, fake_supabase):
    fake_supabase.auth.admin.list_users.return_value = []
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)

    with pytest.raises(SystemExit) as exc_info:
        promote_admin.revoke("ghost@example.com")

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "No Supabase user found for ghost@example.com" in out


def test_promote_admin_revoke_success_pops_role(monkeypatch, capsys, fake_supabase):
    user = FakeUser("u-3", "admin@example.com", app_metadata={"role": "admin", "plan": "pro"})
    fake_supabase.auth.admin.list_users.return_value = [user]

    from unittest.mock import MagicMock
    revoke_mock = MagicMock()
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)
    monkeypatch.setattr(promote_admin, "revoke_admin", revoke_mock)

    promote_admin.revoke("admin@example.com")

    fake_supabase.auth.admin.update_user_by_id.assert_called_once_with(
        "u-3", {"app_metadata": {"plan": "pro"}}
    )
    revoke_mock.assert_called_once_with("u-3")
    out = capsys.readouterr().out
    assert "Revoked admin from admin@example.com (u-3)" in out


def test_promote_admin_revoke_success_when_role_absent(monkeypatch, capsys, fake_supabase):
    # meta.pop("role", None) shouldn't blow up when there was no role key to begin with.
    user = FakeUser("u-4", "norole@example.com", app_metadata={"plan": "pro"})
    fake_supabase.auth.admin.list_users.return_value = [user]

    from unittest.mock import MagicMock
    monkeypatch.setattr(promote_admin, "admin_supabase", fake_supabase)
    monkeypatch.setattr(promote_admin, "revoke_admin", MagicMock())

    promote_admin.revoke("norole@example.com")

    fake_supabase.auth.admin.update_user_by_id.assert_called_once_with(
        "u-4", {"app_metadata": {"plan": "pro"}}
    )


def test_promote_admin_main_wrong_argv_count_prints_usage(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["promote_admin.py", "grant"])

    with pytest.raises(SystemExit) as exc_info:
        promote_admin.main()

    assert exc_info.value.code == 2
    out = capsys.readouterr().out
    assert promote_admin.__doc__ in out


def test_promote_admin_main_invalid_action_prints_usage(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["promote_admin.py", "delete", "user@example.com"])

    with pytest.raises(SystemExit) as exc_info:
        promote_admin.main()

    assert exc_info.value.code == 2
    out = capsys.readouterr().out
    assert promote_admin.__doc__ in out


def test_promote_admin_main_dispatches_to_grant(monkeypatch):
    from unittest.mock import MagicMock

    grant_mock = MagicMock()
    revoke_mock = MagicMock()
    monkeypatch.setattr(promote_admin, "grant", grant_mock)
    monkeypatch.setattr(promote_admin, "revoke", revoke_mock)
    monkeypatch.setattr(sys, "argv", ["promote_admin.py", "grant", "user@example.com"])

    promote_admin.main()

    grant_mock.assert_called_once_with("user@example.com")
    revoke_mock.assert_not_called()


def test_promote_admin_main_dispatches_to_revoke(monkeypatch):
    from unittest.mock import MagicMock

    grant_mock = MagicMock()
    revoke_mock = MagicMock()
    monkeypatch.setattr(promote_admin, "grant", grant_mock)
    monkeypatch.setattr(promote_admin, "revoke", revoke_mock)
    monkeypatch.setattr(sys, "argv", ["promote_admin.py", "revoke", "user@example.com"])

    promote_admin.main()

    revoke_mock.assert_called_once_with("user@example.com")
    grant_mock.assert_not_called()


# ---------------------------------------------------------------------------
# scripts/unban_user.py
# ---------------------------------------------------------------------------


def test_unban_user_find_user_by_email_plain_list_response(monkeypatch, fake_supabase):
    target = FakeUser("u-1", "Someone@Example.com")
    fake_supabase.auth.admin.list_users.return_value = [target]
    monkeypatch.setattr(unban_user, "admin_supabase", fake_supabase)

    found = unban_user.find_user_by_email("someone@example.com")
    assert found is target


def test_unban_user_find_user_by_email_object_with_users_attribute(monkeypatch, fake_supabase):
    from unittest.mock import MagicMock

    target = FakeUser("u-2", "wrapped@example.com")
    resp = MagicMock(spec=["users"])
    resp.users = [target]
    fake_supabase.auth.admin.list_users.return_value = resp
    monkeypatch.setattr(unban_user, "admin_supabase", fake_supabase)

    found = unban_user.find_user_by_email("wrapped@example.com")
    assert found is target


def test_unban_user_find_user_by_email_returns_none_on_empty_page(monkeypatch, fake_supabase):
    fake_supabase.auth.admin.list_users.return_value = []
    monkeypatch.setattr(unban_user, "admin_supabase", fake_supabase)

    assert unban_user.find_user_by_email("nobody@example.com") is None


def test_unban_user_find_user_by_email_paginates_across_pages(monkeypatch, fake_supabase):
    page1 = [FakeUser(f"u-{i}", f"user{i}@example.com") for i in range(200)]
    target = FakeUser("u-target", "target@example.com")
    fake_supabase.auth.admin.list_users.side_effect = [page1, [target]]
    monkeypatch.setattr(unban_user, "admin_supabase", fake_supabase)

    found = unban_user.find_user_by_email("target@example.com")
    assert found is target
    assert fake_supabase.auth.admin.list_users.call_count == 2


def test_unban_user_find_user_by_email_stops_after_full_page_with_no_further_match(monkeypatch, fake_supabase):
    page1 = [FakeUser(f"u-{i}", f"user{i}@example.com") for i in range(200)]
    fake_supabase.auth.admin.list_users.side_effect = [page1, []]
    monkeypatch.setattr(unban_user, "admin_supabase", fake_supabase)

    assert unban_user.find_user_by_email("missing@example.com") is None
    assert fake_supabase.auth.admin.list_users.call_count == 2


def test_unban_user_find_user_by_email_handles_none_email(monkeypatch, fake_supabase):
    fake_supabase.auth.admin.list_users.return_value = [FakeUser("u-1", None)]
    monkeypatch.setattr(unban_user, "admin_supabase", fake_supabase)

    assert unban_user.find_user_by_email("someone@example.com") is None


def test_unban_user_main_wrong_argv_prints_usage_and_exits(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["unban_user.py"])

    with pytest.raises(SystemExit) as exc_info:
        unban_user.main()

    assert exc_info.value.code == 2
    out = capsys.readouterr().out
    assert unban_user.__doc__ in out


def test_unban_user_main_user_not_found_returns_without_exit(monkeypatch, capsys, fake_supabase):
    fake_supabase.auth.admin.list_users.return_value = []
    monkeypatch.setattr(unban_user, "admin_supabase", fake_supabase)
    monkeypatch.setattr(sys, "argv", ["unban_user.py", "ghost@example.com"])

    result = unban_user.main()

    assert result is None
    out = capsys.readouterr().out
    assert "No user found for ghost@example.com" in out
    fake_supabase.auth.admin.update_user_by_id.assert_not_called()


def test_unban_user_main_success_lifts_ban_and_invalidates_cache(monkeypatch, capsys, fake_supabase):
    from unittest.mock import MagicMock

    user = FakeUser("u-1", "banned@example.com")
    fake_supabase.auth.admin.list_users.return_value = [user]
    monkeypatch.setattr(unban_user, "admin_supabase", fake_supabase)

    invalidate_mock = MagicMock()
    monkeypatch.setattr("cache.invalidate_ban_status", invalidate_mock)
    monkeypatch.setattr(sys, "argv", ["unban_user.py", "banned@example.com"])

    unban_user.main()

    fake_supabase.auth.admin.update_user_by_id.assert_called_once_with("u-1", {"ban_duration": "none"})
    fake_supabase.table.assert_called_once_with("user_profiles")
    fake_supabase.table.return_value.upsert.assert_called_once_with(
        {"id": "u-1", "is_banned": False, "updated_at": "now()"}
    )
    fake_supabase.table.return_value.upsert.return_value.execute.assert_called_once()
    invalidate_mock.assert_called_once_with("u-1")

    out = capsys.readouterr().out
    assert "Found user banned@example.com -> id=u-1" in out
    assert "Supabase auth ban lifted (ban_duration=none)" in out
    assert "user_profiles.is_banned = False" in out
    assert "cache invalidated" in out
    assert "Done. You can log in again." in out


def test_unban_user_main_cache_invalidate_failure_is_caught(monkeypatch, capsys, fake_supabase):
    user = FakeUser("u-2", "banned2@example.com")
    fake_supabase.auth.admin.list_users.return_value = [user]
    monkeypatch.setattr(unban_user, "admin_supabase", fake_supabase)

    def _boom(_user_id):
        raise RuntimeError("redis is down")

    monkeypatch.setattr("cache.invalidate_ban_status", _boom)
    monkeypatch.setattr(sys, "argv", ["unban_user.py", "banned2@example.com"])

    # Should not raise -- the script wraps cache invalidation in try/except.
    unban_user.main()

    out = capsys.readouterr().out
    assert "cache invalidate skipped: redis is down" in out
    assert "Done. You can log in again." in out
