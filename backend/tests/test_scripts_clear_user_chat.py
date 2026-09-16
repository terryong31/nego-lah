"""Guard tests for scripts/clear_user_chat.py (SPEC-076).

The script is a manual, data-deleting ops run through `infisical run`. What
is worth pinning: dry-run is the default and touches nothing, `--apply`
deletes exactly the target user's rows and nothing else, and an unknown email
fails with guidance rather than a traceback.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_supabase():
    fake = MagicMock()
    user = SimpleNamespace(id="uuid-123", email="User@Example.com")
    fake.auth.admin.list_users.return_value = SimpleNamespace(users=[user])
    return fake


def _run(monkeypatch, fake_supabase, argv):
    import importlib

    mod = importlib.import_module("scripts.clear_user_chat")
    monkeypatch.setattr(mod, "admin_supabase", fake_supabase)
    rc = mod.main(argv)
    return mod, rc


def test_dry_run_counts_but_never_deletes(monkeypatch, fake_supabase, capsys):
    counted = MagicMock()
    counted.count = 7
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = counted

    mod, rc = _run(monkeypatch, fake_supabase, ["user@example.com"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "7" in out
    assert "DRY RUN" in out
    fake_supabase.table.return_value.delete.assert_not_called()


def test_apply_deletes_only_that_users_rows_and_verifies_empty(monkeypatch, fake_supabase, capsys):
    before, after = MagicMock(), MagicMock()
    before.count, after.count = 7, 0
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect = [before, after]

    mod, rc = _run(monkeypatch, fake_supabase, ["user@example.com", "--apply"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "7" in out and "0" in out
    # The one and only delete filter is the user id.
    fake_supabase.table.return_value.delete.return_value.eq.assert_called_once_with("user_id", "uuid-123")
    fake_supabase.table.return_value.delete.return_value.eq.return_value.execute.assert_called_once()


def test_unknown_email_exits_nonzero_and_deletes_nothing(monkeypatch, fake_supabase, capsys):
    fake_supabase.auth.admin.list_users.return_value = SimpleNamespace(users=[])

    mod, rc = _run(monkeypatch, fake_supabase, ["nobody@example.com"])

    out = capsys.readouterr().out
    assert rc == 1
    assert "No user found" in out
    fake_supabase.table.return_value.delete.assert_not_called()


def test_email_match_is_case_insensitive(monkeypatch, fake_supabase, capsys):
    counted = MagicMock()
    counted.count = 0
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = counted

    mod, rc = _run(monkeypatch, fake_supabase, ["USER@example.com"])

    assert rc == 0
    assert "uuid-123" in capsys.readouterr().out


def test_missing_email_arg_prints_usage(monkeypatch, fake_supabase, capsys):
    mod, rc = _run(monkeypatch, fake_supabase, [])

    out = capsys.readouterr().out
    assert rc == 2
    assert "Usage" in out
    fake_supabase.auth.admin.list_users.assert_not_called()
