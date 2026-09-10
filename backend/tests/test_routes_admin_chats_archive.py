"""SPEC-063 — conversations can leave the list without being destroyed.

Threads accumulate forever: a finished negotiation has no way out of the console
list, so the list only grows. Archiving is one nullable timestamp on the
`chat_settings` row the list already reads in bulk — deliberately not a delete,
because a transcript is the record of what was agreed and no triage gesture in a
list UI should be able to destroy one.

Seam notes match tests/test_routes_admin_chats_read_state.py: the handlers do a
lazy `from connector import admin_supabase` inside the function body, so the
patch target is `connector.admin_supabase`, and `write_audit` is patched on
`routes.admin.chats`.
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


def make_user(user_id, email=None, metadata=None, created_at="2024-01-01T00:00:00Z"):
    return SimpleNamespace(
        id=user_id, email=email, user_metadata=metadata or {}, created_at=created_at
    )


def _admin_session_with_csrf(client, sid="sid-archive", token="csrf-token-archive"):
    from cache import redis_client
    from env import ADMIN_SESSION_TTL
    redis_client.setex(f"csrf:{sid}", ADMIN_SESSION_TTL, token)
    client.cookies.set("admin_sid", sid)
    return token


@pytest.fixture
def archive_env(monkeypatch, fake_supabase, patch_supabase):
    def _setup():
        patch_supabase("connector", admin=fake_supabase)
        monkeypatch.setattr(admin_chats, "write_audit", MagicMock())
        return fake_supabase
    return _setup


# ---------------------------------------------------------------------------
# POST /admin/chats/{user_id}/archive
# ---------------------------------------------------------------------------

async def test_archiving_stamps_the_timestamp_and_audits(client, admin_user, archive_env):
    admin_user()
    supabase = archive_env()

    resp = await client.post("/admin/chats/user-a/archive", json={"archived": True})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "user-a"
    assert body["archived"] is True
    assert body["archived_at"]

    written = supabase.table.return_value.upsert.call_args[0][0]
    assert written["user_id"] == "user-a"
    assert written["archived_at"] == body["archived_at"]
    admin_chats.write_audit.assert_called_once()
    assert admin_chats.write_audit.call_args[0][2] == "chat.archive"


async def test_unarchiving_clears_the_timestamp(client, admin_user, archive_env):
    admin_user()
    supabase = archive_env()

    resp = await client.post("/admin/chats/user-a/archive", json={"archived": False})

    assert resp.status_code == 200
    assert resp.json()["archived"] is False
    assert resp.json()["archived_at"] is None
    assert supabase.table.return_value.upsert.call_args[0][0]["archived_at"] is None
    assert admin_chats.write_audit.call_args[0][2] == "chat.unarchive"


async def test_a_failed_write_is_surfaced_not_swallowed(client, admin_user, archive_env):
    """A click that silently does nothing is worse than one that says no."""
    admin_user()
    supabase = archive_env()
    supabase.table.return_value.upsert.return_value.execute.side_effect = RuntimeError("nope")

    resp = await client.post("/admin/chats/user-a/archive", json={"archived": True})

    assert resp.status_code == 503


async def test_archive_requires_an_admin_session(client, archive_env):
    archive_env()
    resp = await client.post("/admin/chats/user-a/archive", json={"archived": True})
    assert resp.status_code in (401, 403)


async def test_archive_is_csrf_gated(client, admin_user, archive_env):
    """Every mutating admin endpoint goes through the same gate (AGENTS.md)."""
    admin_user()
    supabase = archive_env()
    _admin_session_with_csrf(client)

    resp = await client.post("/admin/chats/user-a/archive", json={"archived": True})

    assert resp.status_code == 403
    supabase.table.return_value.upsert.assert_not_called()


async def test_archive_succeeds_with_a_valid_csrf_token(client, admin_user, archive_env):
    admin_user()
    archive_env()
    token = _admin_session_with_csrf(client)

    resp = await client.post(
        "/admin/chats/user-a/archive",
        json={"archived": True},
        headers={"X-CSRF-Token": token},
    )

    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /admin/chats — archived rows, and the fields the info panel needs
# ---------------------------------------------------------------------------

def _chats_tables(settings=None, profiles=None):
    profiles_mock = MagicMock()
    profiles_mock.select.return_value.execute.return_value = make_supabase_result(profiles or [])
    settings_mock = MagicMock()
    settings_mock.select.return_value.execute.return_value = make_supabase_result(settings or [])
    messages_mock = MagicMock()
    messages_mock.select.return_value.order.return_value.execute.return_value = make_supabase_result([])
    return table_router({
        "user_profiles": profiles_mock,
        "chat_settings": settings_mock,
        "messages": messages_mock,
    })


async def _list_chats(client, admin_user, fake_supabase, patch_supabase, monkeypatch,
                      *, settings=None, profiles=None, users=None, query=""):
    admin_user()
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.table.side_effect = _chats_tables(settings=settings, profiles=profiles)
    fake_supabase.auth.admin.list_users.return_value = users or [
        make_user("user-a", email="a@example.com"),
        make_user("user-b", email="b@example.com"),
    ]
    monkeypatch.setattr(
        conversation_memory, "get_all_histories",
        MagicMock(return_value={
            "user-a": [{"role": "human", "content": "hi", "source": "human"}],
            "user-b": [{"role": "human", "content": "yo", "source": "human"}],
        }),
    )
    resp = await client.get(f"/admin/chats{query}")
    assert resp.status_code == 200
    return {c["user_id"]: c for c in resp.json()}


async def test_archived_conversations_are_hidden_by_default(
    client, admin_user, fake_supabase, patch_supabase, monkeypatch
):
    chats = await _list_chats(
        client, admin_user, fake_supabase, patch_supabase, monkeypatch,
        settings=[{"user_id": "user-b", "archived_at": "2026-09-10T09:00:00Z"}],
    )

    assert set(chats) == {"user-a"}
    assert chats["user-a"]["archived"] is False


async def test_archived_conversations_are_reachable_on_request(
    client, admin_user, fake_supabase, patch_supabase, monkeypatch
):
    chats = await _list_chats(
        client, admin_user, fake_supabase, patch_supabase, monkeypatch,
        settings=[{"user_id": "user-b", "archived_at": "2026-09-10T09:00:00Z"}],
        query="?include_archived=true",
    )

    assert set(chats) == {"user-a", "user-b"}
    assert chats["user-b"]["archived"] is True


async def test_chat_rows_carry_what_the_info_panel_shows(
    client, admin_user, fake_supabase, patch_supabase, monkeypatch
):
    """The list handler already holds every user and profile, so the customer
    panel costs no extra round trip and no new endpoint."""
    chats = await _list_chats(
        client, admin_user, fake_supabase, patch_supabase, monkeypatch,
        profiles=[{"id": "user-a", "display_name": "Alice", "avatar_url": None, "is_banned": True}],
        users=[make_user("user-a", email="alice@example.com", created_at="2025-03-04T05:06:07Z")],
    )

    row = chats["user-a"]
    assert row["email"] == "alice@example.com"
    assert row["created_at"] == "2025-03-04T05:06:07Z"
    assert row["is_banned"] is True
