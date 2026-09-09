"""SPEC-053 — the console's unread dot becomes a real, writable read watermark.

`GET /admin/chats` used to derive `unread` from `last_role == 'human'`, which
means the only act that can clear the dot is *replying*. Opening the thread,
reading it, deciding it needs no answer — none of those could mark it read,
which is why "mark as read" did not work: there was no read state to mark.

These cover the watermark's three states (absent, ahead of the last customer
message, behind it), the endpoint that writes it, and the two console actions
that stamp it.

Seam notes match tests/test_routes_admin_auth.py: `/admin/chats/*` handlers do a
lazy `from connector import admin_supabase` inside the function body, so the
patch target is `connector.admin_supabase`, and `write_audit` is patched on
`routes.admin.chats` (the module that resolves the name).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import routes.admin.chats as admin_chats
from agent.memory import conversation_memory
from conftest import make_supabase_result

pytestmark = pytest.mark.asyncio


def table_router(mapping):
    def _side_effect(name, *_a, **_kw):
        return mapping.get(name, MagicMock())
    return _side_effect


def make_user(user_id, email=None, metadata=None):
    return SimpleNamespace(id=user_id, email=email, user_metadata=metadata or {}, created_at="2024-01-01T00:00:00Z")


def _chats_tables(settings=None, messages=None):
    profiles_mock = MagicMock()
    profiles_mock.select.return_value.execute.return_value = make_supabase_result([])
    settings_mock = MagicMock()
    settings_mock.select.return_value.execute.return_value = make_supabase_result(settings or [])
    messages_mock = MagicMock()
    messages_mock.select.return_value.order.return_value.execute.return_value = make_supabase_result(messages or [])
    return table_router({
        "user_profiles": profiles_mock,
        "chat_settings": settings_mock,
        "messages": messages_mock,
    }), settings_mock


async def _get_chats(client, admin_user, fake_supabase, patch_supabase, monkeypatch,
                     *, settings=None, messages=None, history=None):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    router, settings_mock = _chats_tables(settings=settings, messages=messages)
    fake_supabase.table.side_effect = router
    fake_supabase.auth.admin.list_users.return_value = [make_user("user-a", email="a@example.com")]
    monkeypatch.setattr(
        conversation_memory, "get_all_histories",
        MagicMock(return_value={"user-a": history or [{"role": "human", "content": "hi", "source": "human"}]}),
    )
    resp = await client.get("/admin/chats")
    assert resp.status_code == 200
    return resp.json()[0], settings_mock


# ---------------------------------------------------------------------------
# Scenario 1-3 — the watermark decides `unread`
# ---------------------------------------------------------------------------

async def test_no_watermark_falls_back_to_last_role(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    """A conversation predating the migration behaves exactly as it always did."""
    chat, _ = await _get_chats(
        client, admin_user, fake_supabase, patch_supabase, monkeypatch,
        messages=[{"user_id": "user-a", "role": "human", "created_at": "2026-09-09T12:00:00Z"}],
    )
    assert chat["unread"] is True
    assert chat["admin_last_read_at"] is None


async def test_watermark_after_last_customer_message_marks_read(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    chat, _ = await _get_chats(
        client, admin_user, fake_supabase, patch_supabase, monkeypatch,
        settings=[{"user_id": "user-a", "admin_last_read_at": "2026-09-09T13:00:00Z"}],
        messages=[{"user_id": "user-a", "role": "human", "created_at": "2026-09-09T12:00:00Z"}],
    )
    assert chat["unread"] is False
    assert chat["admin_last_read_at"] == "2026-09-09T13:00:00Z"


async def test_newer_customer_message_re_arms_unread(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    chat, _ = await _get_chats(
        client, admin_user, fake_supabase, patch_supabase, monkeypatch,
        settings=[{"user_id": "user-a", "admin_last_read_at": "2026-09-09T12:00:00Z"}],
        messages=[{"user_id": "user-a", "role": "human", "created_at": "2026-09-09T14:00:00Z"}],
    )
    assert chat["unread"] is True


async def test_seller_reply_after_the_watermark_stays_read(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    """Only CUSTOMER messages re-arm the dot — the seller's own reply must not."""
    chat, _ = await _get_chats(
        client, admin_user, fake_supabase, patch_supabase, monkeypatch,
        settings=[{"user_id": "user-a", "admin_last_read_at": "2026-09-09T13:00:00Z"}],
        messages=[
            {"user_id": "user-a", "role": "ai", "created_at": "2026-09-09T15:00:00Z"},
            {"user_id": "user-a", "role": "human", "created_at": "2026-09-09T12:00:00Z"},
        ],
    )
    assert chat["unread"] is False
    # last_activity still tracks the newest message of any role.
    assert chat["last_activity"] == "2026-09-09T15:00:00Z"


async def test_unparseable_watermark_falls_back_to_last_role(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    chat, _ = await _get_chats(
        client, admin_user, fake_supabase, patch_supabase, monkeypatch,
        settings=[{"user_id": "user-a", "admin_last_read_at": "not-a-timestamp"}],
        messages=[{"user_id": "user-a", "role": "human", "created_at": "2026-09-09T12:00:00Z"}],
    )
    assert chat["unread"] is True


# ---------------------------------------------------------------------------
# Scenario 4-5 — the endpoint that writes it
# ---------------------------------------------------------------------------

async def test_mark_read_writes_a_watermark_and_audits(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    audit = MagicMock()
    monkeypatch.setattr(admin_chats, "write_audit", audit)

    resp = await client.post("/admin/chats/user-a/read", json={"read": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "user-a"
    assert body["unread"] is False
    assert body["admin_last_read_at"]

    written = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert written["user_id"] == "user-a"
    assert written["admin_last_read_at"] == body["admin_last_read_at"]
    assert audit.called
    assert audit.call_args[0][2] == "chat.read"


async def test_mark_unread_clears_the_watermark(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_chats, "write_audit", MagicMock())

    resp = await client.post("/admin/chats/user-a/read", json={"read": False})

    assert resp.status_code == 200
    body = resp.json()
    assert body["unread"] is True
    assert body["admin_last_read_at"] is None
    written = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert written["admin_last_read_at"] is None


async def test_mark_read_defaults_to_read_with_an_empty_body(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_chats, "write_audit", MagicMock())

    resp = await client.post("/admin/chats/user-a/read", json={})

    assert resp.status_code == 200
    assert resp.json()["unread"] is False


async def test_mark_read_requires_admin(client):
    resp = await client.post("/admin/chats/user-a/read", json={"read": True})
    assert resp.status_code == 401


async def test_mark_read_survives_a_failing_write(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    """A console click must not 500 because chat_settings is briefly unavailable."""
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_chats, "write_audit", MagicMock())
    fake_supabase.table.return_value.upsert.side_effect = Exception("postgrest down")

    resp = await client.post("/admin/chats/user-a/read", json={"read": True})

    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Scenario 6 — replying from the console counts as having read it
# ---------------------------------------------------------------------------

async def test_console_send_stamps_the_watermark(client, admin_user, fake_supabase, patch_supabase, monkeypatch):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    monkeypatch.setattr(admin_chats, "write_audit", MagicMock())
    monkeypatch.setattr(conversation_memory, "add_message", MagicMock())
    monkeypatch.setattr("agent.memory.conversation_memory", conversation_memory)

    settings_mock = MagicMock()
    fake_supabase.table.side_effect = table_router({"chat_settings": settings_mock})

    resp = await client.post("/admin/chats/user-a/message", json={"message": "on its way"})

    assert resp.status_code == 200
    assert settings_mock.upsert.called
    assert settings_mock.upsert.call_args[0][0]["admin_last_read_at"]
