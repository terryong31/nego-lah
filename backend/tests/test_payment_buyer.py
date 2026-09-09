"""Tests for payment/buyer.py::account_email (SPEC-047 / SPEC-048).

`account_email` lazily does `from connector import admin_supabase` inside the
function, so patching `connector.admin_supabase` takes effect at call time.
"""

from unittest.mock import MagicMock

from payment.buyer import account_email


def test_returns_none_for_falsy_user_id():
    assert account_email(None) is None
    assert account_email("") is None


def test_reads_email_from_a_supabase_user_object(monkeypatch):
    fake = MagicMock()
    fake.auth.admin.get_user_by_id.return_value = MagicMock(user=MagicMock(email="buyer@example.com"))
    monkeypatch.setattr("connector.admin_supabase", fake)

    assert account_email("user-1") == "buyer@example.com"
    fake.auth.admin.get_user_by_id.assert_called_once_with("user-1")


def test_reads_email_from_a_dict_shaped_response(monkeypatch):
    fake = MagicMock()
    fake.auth.admin.get_user_by_id.return_value = {"user": {"email": "dict@example.com"}}
    monkeypatch.setattr("connector.admin_supabase", fake)

    assert account_email("user-2") == "dict@example.com"


def test_returns_none_and_does_not_raise_when_the_lookup_fails(monkeypatch, caplog):
    fake = MagicMock()
    fake.auth.admin.get_user_by_id.side_effect = RuntimeError("supabase down")
    monkeypatch.setattr("connector.admin_supabase", fake)

    assert account_email("user-3") is None
    assert "Could not resolve account email for buyer user-3" in caplog.text


def test_returns_none_when_the_user_has_no_email(monkeypatch):
    fake = MagicMock()
    fake.auth.admin.get_user_by_id.return_value = MagicMock(user=None)
    monkeypatch.setattr("connector.admin_supabase", fake)

    assert account_email("user-4") is None
