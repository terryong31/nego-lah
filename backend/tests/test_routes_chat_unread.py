"""SPEC-061 — the buyer's unread badge has to survive the tab that saw it.

`useNotifications` kept `hasUnread` in a `useState` written only by a live SSE
event, so a reply that arrived while the buyer was away left no trace anywhere
the next page load could find it. These endpoints are that trace: a watermark
the buyer writes when they read, and a count derived from it.
"""

from datetime import UTC, datetime, timedelta

from conftest import make_supabase_result

NOW = datetime.now(UTC)


def set_settings(fake_supabase, rows):
    """admin_supabase.table('chat_settings').select(...).eq(...).execute()"""
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .execute.return_value
    ) = make_supabase_result(rows)


def fake_memory(monkeypatch, *, newest_human=None, unread=0):
    """Record the cutoff the route derives, and answer with a fixed count."""
    seen = {}

    def _newest_at(user_id, role):
        seen.setdefault("newest_at", []).append((user_id, role))
        return newest_human if role == "human" else None

    def _count_since(user_id, role, after, cap):
        seen["count_since"] = (user_id, role, after, cap)
        return unread

    monkeypatch.setattr("agent.memory.conversation_memory.newest_at", _newest_at)
    monkeypatch.setattr("agent.memory.conversation_memory.count_since", _count_since)
    return seen


# ---------------------------------------------------------------------------
# GET /chat/unread
# ---------------------------------------------------------------------------

async def test_unread_counts_seller_messages_after_the_watermark(
    client, auth_user, monkeypatch, patch_supabase, fake_supabase
):
    auth_user("buyer-1")
    read_at = (NOW - timedelta(minutes=5)).isoformat()
    set_settings(fake_supabase, [{"user_last_read_at": read_at}])
    patch_supabase("routes.chat", admin=fake_supabase)
    seen = fake_memory(monkeypatch, newest_human=(NOW - timedelta(hours=1)).isoformat(), unread=3)

    resp = await client.get("/chat/unread")

    assert resp.status_code == 200
    assert resp.json() == {"count": 3, "has_unread": True}
    user_id, role, after, _cap = seen["count_since"]
    assert (user_id, role) == ("buyer-1", "ai"), "only agent/seller rows are unread"
    assert after == read_at, "the watermark is newer than the buyer's last message"


async def test_unread_falls_back_to_the_buyers_own_last_message(
    client, auth_user, monkeypatch, patch_supabase, fake_supabase
):
    """No watermark yet. Counting from the start of time would mark an existing
    user's entire history unread the day this ships."""
    auth_user("buyer-2")
    set_settings(fake_supabase, [{"user_last_read_at": None}])
    patch_supabase("routes.chat", admin=fake_supabase)
    last_human = (NOW - timedelta(minutes=2)).isoformat()
    seen = fake_memory(monkeypatch, newest_human=last_human, unread=1)

    resp = await client.get("/chat/unread")

    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert seen["count_since"][2] == last_human


async def test_unread_uses_the_later_of_watermark_and_last_message(
    client, auth_user, monkeypatch, patch_supabase, fake_supabase
):
    """The buyer typing is proof of presence, and it can be newer than the last
    time anything stamped the watermark."""
    auth_user("buyer-3")
    stale = (NOW - timedelta(hours=2)).isoformat()
    fresh_human = (NOW - timedelta(minutes=1)).isoformat()
    set_settings(fake_supabase, [{"user_last_read_at": stale}])
    patch_supabase("routes.chat", admin=fake_supabase)
    seen = fake_memory(monkeypatch, newest_human=fresh_human, unread=0)

    resp = await client.get("/chat/unread")

    assert resp.json() == {"count": 0, "has_unread": False}
    assert seen["count_since"][2] == fresh_human


async def test_unread_is_capped(client, auth_user, monkeypatch, patch_supabase, fake_supabase):
    """It is a badge, not a ledger."""
    from routes.chat import UNREAD_COUNT_CAP

    auth_user("buyer-4")
    set_settings(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)
    fake_memory(monkeypatch, unread=UNREAD_COUNT_CAP)

    resp = await client.get("/chat/unread")

    assert resp.json()["count"] == UNREAD_COUNT_CAP


async def test_unread_requires_a_token(client):
    resp = await client.get("/chat/unread")
    assert resp.status_code in (401, 403)


async def test_unread_survives_a_settings_read_failure(
    client, auth_user, monkeypatch, patch_supabase, fake_supabase
):
    """A chip is not worth a 500. Degrade to the fallback rule."""
    auth_user("buyer-5")
    fake_supabase.table.side_effect = RuntimeError("postgrest down")
    patch_supabase("routes.chat", admin=fake_supabase)
    fake_memory(monkeypatch, newest_human=NOW.isoformat(), unread=0)

    resp = await client.get("/chat/unread")

    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "has_unread": False}


# ---------------------------------------------------------------------------
# POST /chat/read
# ---------------------------------------------------------------------------

async def test_read_stamps_the_watermark(client, auth_user, patch_supabase, fake_supabase):
    auth_user("buyer-6")
    patch_supabase("routes.chat", admin=fake_supabase)

    resp = await client.post("/chat/read")

    assert resp.status_code == 200
    stamped = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert stamped["user_id"] == "buyer-6"
    assert stamped["user_last_read_at"] == resp.json()["read_at"]
    assert datetime.fromisoformat(resp.json()["read_at"]) <= datetime.now(UTC)


async def test_read_covers_messages_the_clock_cannot_reach(
    client, auth_user, monkeypatch, patch_supabase, fake_supabase
):
    """SPEC-066. `now` is this process's opinion; the newest message was dated
    by whoever wrote it, and two clocks that both believe they are on UTC can
    still disagree. A mark that stops short of the message it claims to have
    read is a chip that comes back on the next load."""
    auth_user("buyer-10")
    patch_supabase("routes.chat", admin=fake_supabase)
    skewed = (NOW + timedelta(seconds=30)).isoformat()
    monkeypatch.setattr(
        "agent.memory.conversation_memory.newest_at",
        lambda user_id, role: skewed if role == "ai" else None,
    )

    resp = await client.post("/chat/read")

    assert resp.json()["read_at"] == skewed
    stamped = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert stamped["user_last_read_at"] == skewed


async def test_read_surfaces_a_failed_write(client, auth_user, patch_supabase, fake_supabase):
    """A click that silently does nothing is the bug this exists to fix."""
    auth_user("buyer-7")
    fake_supabase.table.return_value.upsert.return_value.execute.side_effect = RuntimeError("nope")
    patch_supabase("routes.chat", admin=fake_supabase)

    resp = await client.post("/chat/read")

    assert resp.status_code == 503


async def test_read_requires_a_token(client):
    resp = await client.post("/chat/read")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# reading the transcript IS reading it
# ---------------------------------------------------------------------------

async def test_history_stamps_the_watermark(
    client, auth_user, monkeypatch, patch_supabase, fake_supabase
):
    auth_user("buyer-8")
    patch_supabase("routes.chat", admin=fake_supabase)
    monkeypatch.setattr(
        "agent.memory.conversation_memory.get_history_page",
        lambda *a, **k: {"messages": [], "has_more": False, "next_offset": 0},
    )

    resp = await client.get("/chat/history/buyer-8")

    assert resp.status_code == 200
    stamped = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert stamped["user_id"] == "buyer-8"
    assert stamped["user_last_read_at"]


async def test_history_still_returns_when_the_stamp_fails(
    client, auth_user, monkeypatch, patch_supabase, fake_supabase
):
    auth_user("buyer-9")
    fake_supabase.table.side_effect = RuntimeError("postgrest down")
    patch_supabase("routes.chat", admin=fake_supabase)
    page = {"messages": [], "has_more": False, "next_offset": 0}
    monkeypatch.setattr("agent.memory.conversation_memory.get_history_page", lambda *a, **k: page)

    resp = await client.get("/chat/history/buyer-9")

    assert resp.status_code == 200
    assert resp.json() == page
