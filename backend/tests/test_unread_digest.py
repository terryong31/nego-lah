"""SPEC-052 — seller messages to an offline buyer batch into one email.

Every seller message used to fire its own email. The persona actively encourages
short consecutive bubbles, so saying one thing in four bubbles sent four emails
in under a minute — which reads as spam and costs four Resend credits.

Now a message to an offline buyer is *queued*, and an email goes out only if the
buyer still hasn't read the conversation five minutes later, carrying everything
queued in that window.

Redis is the fake in-memory double here (see conftest), which is exactly the
single-process behaviour these functions have to keep working under.
"""

import json
import time
from unittest.mock import MagicMock

import pytest

from cache import redis_client
from services import unread_digest

pytestmark = pytest.mark.asyncio


def _key(user_id: str) -> str:
    return f"{unread_digest.DIGEST_KEY_PREFIX}{user_id}"


def _queue_at(user_id: str, content: str, age_seconds: float, item_name=None):
    """Put an entry on the queue as though it had been sitting there a while."""
    redis_client.rpush(_key(user_id), json.dumps({
        "content": content,
        "item_name": item_name,
        "queued_at": time.time() - age_seconds,
    }))


# ---------------------------------------------------------------------------
# Queue mechanics
# ---------------------------------------------------------------------------

async def test_queue_appends_in_order_and_reports_depth():
    assert unread_digest.queue_unread_message("u1", "first") == 1
    assert unread_digest.queue_unread_message("u1", "second") == 2

    pending = unread_digest.drain_digest("u1")
    assert [m["content"] for m in pending] == ["first", "second"]


async def test_queue_records_the_item_name_for_the_subject_line():
    unread_digest.queue_unread_message("u1", "still available?", item_name="iPhone 13")
    assert unread_digest.drain_digest("u1")[0]["item_name"] == "iPhone 13"


async def test_mark_conversation_seen_empties_the_queue():
    unread_digest.queue_unread_message("u1", "hello")
    assert unread_digest.mark_conversation_seen("u1") is True
    assert unread_digest.drain_digest("u1") == []
    # Nothing pending: a second call is a no-op, not an error.
    assert unread_digest.mark_conversation_seen("u1") is False


async def test_drain_is_atomic_so_a_second_worker_gets_nothing():
    """Two workers sweep on the same cycle; only one may send the digest."""
    unread_digest.queue_unread_message("u1", "hello")
    assert len(unread_digest.drain_digest("u1")) == 1
    assert unread_digest.drain_digest("u1") == []


async def test_a_malformed_entry_is_dropped_not_raised():
    redis_client.rpush(_key("u1"), "{not json")
    unread_digest.queue_unread_message("u1", "good one")
    drained = unread_digest.drain_digest("u1")
    assert [m["content"] for m in drained] == ["good one"]


# ---------------------------------------------------------------------------
# Due detection — the five-minute buffer itself
# ---------------------------------------------------------------------------

async def test_a_fresh_queue_is_not_due():
    unread_digest.queue_unread_message("u1", "just now")
    assert unread_digest.due_digest_user_ids() == []


async def test_a_queue_older_than_the_delay_is_due():
    _queue_at("u1", "six minutes ago", age_seconds=360)
    assert unread_digest.due_digest_user_ids() == ["u1"]


async def test_due_is_decided_by_the_OLDEST_message_not_the_newest():
    """A seller still typing must not push the digest out forever."""
    _queue_at("u1", "old", age_seconds=360)
    unread_digest.queue_unread_message("u1", "brand new")
    assert unread_digest.due_digest_user_ids() == ["u1"]


async def test_an_empty_queue_is_never_due():
    assert unread_digest.due_digest_user_ids() == []


# ---------------------------------------------------------------------------
# Flushing
# ---------------------------------------------------------------------------

def _patch_email(monkeypatch, user_email="buyer@example.com"):
    fake_user = MagicMock()
    fake_user.user.email = user_email
    monkeypatch.setattr("connector.admin_supabase.auth.admin.get_user_by_id", lambda uid: fake_user)
    sender = MagicMock(return_value=True)
    monkeypatch.setattr("services.email_service.send_unread_digest_email", sender)
    return sender


async def test_flush_sends_one_email_carrying_every_queued_message(monkeypatch):
    sender = _patch_email(monkeypatch)
    for text in ("hey", "you still keen?", "can do RM90"):
        _queue_at("u1", text, age_seconds=360)

    assert unread_digest.flush_due_digests() == 1

    sender.assert_called_once()
    to_email, messages = sender.call_args[0][0], sender.call_args[0][1]
    assert to_email == "buyer@example.com"
    assert [m["content"] for m in messages] == ["hey", "you still keen?", "can do RM90"]


async def test_flush_skips_a_queue_that_is_not_due_yet(monkeypatch):
    sender = _patch_email(monkeypatch)
    unread_digest.queue_unread_message("u1", "just sent")

    assert unread_digest.flush_due_digests() == 0
    sender.assert_not_called()
    # And it is still pending, waiting for its turn.
    assert unread_digest.drain_digest("u1")


async def test_flush_sends_nothing_after_the_buyer_reads_the_chat(monkeypatch):
    sender = _patch_email(monkeypatch)
    _queue_at("u1", "hey", age_seconds=360)

    unread_digest.mark_conversation_seen("u1")

    assert unread_digest.flush_due_digests() == 0
    sender.assert_not_called()


async def test_flush_drops_the_queue_when_the_buyer_has_no_email(monkeypatch):
    """An address we can't resolve is not worth retrying every 60s forever."""
    sender = _patch_email(monkeypatch, user_email=None)
    _queue_at("u1", "hey", age_seconds=360)

    assert unread_digest.flush_due_digests() == 0
    sender.assert_not_called()
    assert unread_digest.drain_digest("u1") == []


async def test_one_failing_digest_does_not_abort_the_others(monkeypatch):
    _queue_at("u1", "for user one", age_seconds=360)
    _queue_at("u2", "for user two", age_seconds=360)

    def _lookup(uid):
        if uid == "u1":
            raise RuntimeError("supabase blip")
        user = MagicMock()
        user.user.email = "two@example.com"
        return user

    monkeypatch.setattr("connector.admin_supabase.auth.admin.get_user_by_id", _lookup)
    sender = MagicMock(return_value=True)
    monkeypatch.setattr("services.email_service.send_unread_digest_email", sender)

    assert unread_digest.flush_due_digests() == 1
    assert sender.call_args[0][0] == "two@example.com"


async def test_flush_passes_the_item_name_through(monkeypatch):
    sender = _patch_email(monkeypatch)
    _queue_at("u1", "still there?", age_seconds=360, item_name="iPhone 13")

    unread_digest.flush_due_digests()

    assert sender.call_args.kwargs.get("item_name") == "iPhone 13"


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------

async def test_console_send_queues_instead_of_emailing_an_offline_buyer(client, admin_user, monkeypatch):
    admin_user()
    monkeypatch.setattr("agent.memory.conversation_memory", MagicMock(), raising=False)
    direct_send = MagicMock()
    monkeypatch.setattr("services.email_service.send_unread_message_email", direct_send)

    res = await client.post("/admin/chats/offline-buyer/message", json={"message": "Special deal!"})

    assert res.status_code == 200
    direct_send.assert_not_called()
    assert [m["content"] for m in unread_digest.drain_digest("offline-buyer")] == ["Special deal!"]


async def test_console_send_queues_nothing_for_a_live_buyer(client, admin_user, monkeypatch):
    from notifications import notification_broker

    admin_user()
    monkeypatch.setattr("agent.memory.conversation_memory", MagicMock(), raising=False)

    q = await notification_broker.subscribe("live-buyer")
    try:
        res = await client.post("/admin/chats/live-buyer/message", json={"message": "you there?"})
        assert res.status_code == 200
        assert unread_digest.drain_digest("live-buyer") == []
    finally:
        await notification_broker.unsubscribe("live-buyer", q)


async def test_buyer_reading_history_marks_the_conversation_seen(client, auth_user, monkeypatch):
    auth_user("buyer-1")
    unread_digest.queue_unread_message("buyer-1", "queued while they were away")
    monkeypatch.setattr(
        "agent.memory.conversation_memory.get_history_page",
        MagicMock(return_value={"messages": [], "has_more": False, "next_offset": 0}),
    )

    res = await client.get("/chat/history/buyer-1")

    assert res.status_code == 200
    assert unread_digest.drain_digest("buyer-1") == []
