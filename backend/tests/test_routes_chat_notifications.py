import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.notifications import notification_broker
from domains.negotiation.routes import notifications_stream


@pytest.mark.asyncio
async def test_notifications_stream_requires_auth(client):
    """What authorises the stream lives in tests/test_sse_stream_auth.py."""
    res = await client.get("/chat/notifications/stream")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_resolving_the_session_does_not_block_the_event_loop(monkeypatch):
    """Resolving the session cookie is a Redis round trip, and redis-py is synchronous.

    Run on the event loop it would freeze every other request on this worker for
    the length of that round trip — the real ceiling on concurrent users. This
    asserts the loop keeps ticking while the lookup is in flight. (The credential
    has changed twice — Supabase `get_user`, then an SSE ticket, now the session
    cookie — but the property being defended is the same one, so the test moves
    with it.)
    """
    import time

    from core.env import USER_COOKIE_NAME
    from domains.identity.auth_middleware import verify_user_token

    def slow_resolve(_sid):
        time.sleep(0.2)
        return "user-sse-slow"

    monkeypatch.setattr("domains.identity.auth_middleware.resolve_user_id", slow_resolve)
    monkeypatch.setattr("domains.identity.auth_middleware._is_user_banned", lambda _uid: False)

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.cookies = {USER_COOKIE_NAME: "a-session-id"}
    mock_request.query_params = {}
    mock_request.is_disconnected = AsyncMock(return_value=False)

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(ticker())
    try:
        user_id = await verify_user_token(mock_request)
        response = await notifications_stream(mock_request, user_id)
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat

    assert response.status_code == 200
    # A blocked loop would leave this at 0.
    assert ticks > 5

    # Nothing is subscribed until the body is actually iterated, so a client
    # that vanishes after the handshake leaks neither a queue nor a channel.
    assert notification_broker.has_subscribers("user-sse-slow") is False

    gen = response.body_iterator
    assert await gen.__anext__() == ": connected\n\n"
    assert notification_broker.has_subscribers("user-sse-slow") is True

    await gen.aclose()
    assert notification_broker.has_subscribers("user-sse-slow") is False


@pytest.mark.asyncio
async def test_admin_send_message_notifies_live_buyers_and_queues_for_offline_ones(client, admin_user, monkeypatch):
    """SPEC-052 changed the offline half of this: the seller's message is now
    QUEUED for a digest rather than emailed on the spot. The live half is
    unchanged — a buyer with a stream gets the event and nothing else."""
    from domains.negotiation.unread_digest import drain_digest

    admin_user(user_id="admin-1", email="admin@example.com", ip="127.0.0.1")

    # No email may leave on the send path at all any more.
    fake_send_email = MagicMock()
    monkeypatch.setattr("core.email_service.send_unread_message_email", fake_send_email)
    monkeypatch.setattr("core.email_service.send_unread_digest_email", fake_send_email)

    fake_memory = MagicMock()
    monkeypatch.setattr("domains.negotiation.memory.conversation_memory", fake_memory, raising=False)

    # Case 1: Buyer is offline (no subscribers) -> queued, not emailed.
    assert notification_broker.has_subscribers("offline-buyer") is False
    res = await client.post("/admin/chats/offline-buyer/message", json={"message": "Special deal for you!"})
    assert res.status_code == 200
    fake_send_email.assert_not_called()
    assert [m["content"] for m in drain_digest("offline-buyer")] == ["Special deal for you!"]

    # Case 2: Buyer is online (subscribed) -> delivered live, nothing queued.
    q = await notification_broker.subscribe("online-buyer")
    try:
        res = await client.post("/admin/chats/online-buyer/message", json={"message": "Are you there?"})
        assert res.status_code == 200
        fake_send_email.assert_not_called()
        assert drain_digest("online-buyer") == []

        # Message should be delivered to queue -- exactly once. It used to be
        # published twice (once by broadcast_to_chat, once here), which is what
        # duplicated every seller message in the buyer's toast stack.
        event = q.get_nowait()
        assert event["message"] == "Are you there?"
        assert q.qsize() == 0
    finally:
        await notification_broker.unsubscribe("online-buyer", q)
