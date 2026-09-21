"""One realtime transport, authenticated per user — SPEC-094.

The app used to run two. Messages went to the notification broker (per user,
behind an authenticated SSE stream) *and* to the Supabase Realtime topic
`chat:{user_id}`, created with no `private: true` and with no policy on
`realtime.messages`. That second one was readable by anything holding the anon
key — which ships in the JavaScript bundle — for any user id it cared to name.

These tests hold the line on the fix: nothing leaves the process to Supabase
Realtime, and a subscriber only ever receives their own conversation.
"""

from unittest.mock import MagicMock

import pytest

from core.broadcast import broadcast_to_chat, broadcast_typing
from core.notifications import notification_broker


@pytest.fixture
def no_http(monkeypatch):
    """Fail loudly if anything here tries to reach the network."""
    import requests

    post = MagicMock(side_effect=AssertionError("broadcast made an outbound HTTP call"))
    monkeypatch.setattr(requests, "post", post)
    return post


# ---------------------------------------------------------------------------
# Nothing leaves the process
# ---------------------------------------------------------------------------


async def test_broadcasting_makes_no_outbound_http_call(no_http):
    queue = await notification_broker.subscribe("user-1")
    try:
        broadcast_to_chat("user-1", "hello", role="ai", source="ai")
        broadcast_typing("user-1", "seller")
    finally:
        await notification_broker.unsubscribe("user-1", queue)

    no_http.assert_not_called()


def test_no_module_still_posts_to_the_supabase_broadcast_api():
    """A grep test, deliberately: the leak was one `requests.post` away from
    coming back, in whichever module next wanted to say something live."""
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    offenders = [
        path.relative_to(backend)
        for path in backend.rglob("*.py")
        if ".venv" not in path.parts
        and "tests" not in path.parts
        and "realtime/v1/api/broadcast" in path.read_text()
    ]

    assert offenders == [], f"these still publish to a public Supabase Realtime topic: {offenders}"


# ---------------------------------------------------------------------------
# A subscriber receives their own conversation and no one else's
# ---------------------------------------------------------------------------


async def test_two_buyers_receive_only_their_own_events():
    alice = await notification_broker.subscribe("alice")
    bob = await notification_broker.subscribe("bob")
    try:
        broadcast_to_chat("alice", "alice's negotiation", role="ai", source="ai")

        assert alice.get_nowait()["message"] == "alice's negotiation"
        assert bob.empty(), "bob received a conversation that is not his"
    finally:
        await notification_broker.unsubscribe("alice", alice)
        await notification_broker.unsubscribe("bob", bob)


async def test_typing_reaches_only_the_conversation_it_names():
    alice = await notification_broker.subscribe("alice")
    bob = await notification_broker.subscribe("bob")
    try:
        broadcast_typing("alice", "seller")

        assert alice.get_nowait() == {"type": "typing", "role": "seller"}
        assert bob.empty()
    finally:
        await notification_broker.unsubscribe("alice", alice)
        await notification_broker.unsubscribe("bob", bob)


async def test_a_typing_ping_with_no_listener_is_dropped_not_queued():
    """Fire-and-forget: a ping delivered late is worse than one never delivered."""
    broadcast_typing("nobody-here", "customer")

    queue = await notification_broker.subscribe("nobody-here")
    try:
        assert queue.empty()
    finally:
        await notification_broker.unsubscribe("nobody-here", queue)


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------


async def test_a_buyer_can_only_ping_their_own_conversation(client, auth_user, monkeypatch):
    """The conversation is not a parameter — it is whoever the session says you
    are, so there is no id to tamper with."""
    auth_user("buyer-9")
    published = []
    monkeypatch.setattr(
        notification_broker, "publish", lambda user_id, payload: published.append((user_id, payload))
    )

    res = await client.post("/chat/typing")

    assert res.status_code == 204
    assert published == [("buyer-9", {"type": "typing", "role": "customer"})]


async def test_an_anonymous_typing_ping_is_refused(client):
    res = await client.post("/chat/typing")
    assert res.status_code == 401


async def test_the_admin_stream_requires_an_admin_session(client):
    res = await client.get("/admin/chats/buyer-9/stream")
    assert res.status_code in (401, 403)


async def test_admin_typing_requires_an_admin_session(client):
    res = await client.post("/admin/chats/buyer-9/typing")
    assert res.status_code in (401, 403)


async def test_the_admin_types_as_the_seller(client, admin_user, monkeypatch):
    admin_user()
    published = []
    monkeypatch.setattr(
        notification_broker, "publish", lambda user_id, payload: published.append((user_id, payload))
    )

    res = await client.post("/admin/chats/buyer-9/typing")

    assert res.status_code == 204
    assert published == [("buyer-9", {"type": "typing", "role": "seller"})]


async def test_the_takeover_separator_reaches_the_buyers_stream(client, admin_user, monkeypatch, patch_supabase, fake_supabase):
    """Both sides read the same per-user channel, so one publish serves both."""
    from domains.identity import admin_users
    from domains.negotiation.memory import conversation_memory

    admin_user()
    patch_supabase("core.connector", admin=fake_supabase)
    monkeypatch.setattr(conversation_memory, "add_message", MagicMock())
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())

    queue = await notification_broker.subscribe("buyer-9")
    try:
        res = await client.put("/admin/users/buyer-9/ai", json={"ai_enabled": False})
        assert res.status_code == 200

        event = queue.get_nowait()
        assert "Terry has joined the chat" in event["message"]
        assert event["source"] == "system"
    finally:
        await notification_broker.unsubscribe("buyer-9", queue)
