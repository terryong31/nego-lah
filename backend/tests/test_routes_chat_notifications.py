import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from notifications import notification_broker
from routes.chat import notifications_stream


@pytest.mark.asyncio
async def test_notifications_stream_requires_auth(client):
    res = await client.get("/chat/notifications/stream")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_notifications_stream_connects_with_token(monkeypatch):
    # Mock token validation
    monkeypatch.setattr("cache.get_cached_user_by_token", lambda t: "user-sse-1" if t == "valid-token" else None)

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.query_params = {"token": "valid-token"}
    mock_request.is_disconnected = AsyncMock(return_value=False)

    response = await notifications_stream(mock_request)
    assert response.status_code == 200
    assert response.media_type == "text/event-stream"

    # Read chunks from iterator; the subscription is registered as the body
    # starts, so that it is always torn down with it.
    gen = response.body_iterator
    chunk1 = await gen.__anext__()
    assert chunk1 == ": connected\n\n"
    assert notification_broker.has_subscribers("user-sse-1") is True

    # Publish message to this user
    notification_broker.publish("user-sse-1", {"type": "new_message", "message": "Hi!"})

    chunk2 = await gen.__anext__()
    assert "event: message" in chunk2
    assert "new_message" in chunk2

    # Close generator and ensure cleanup
    await gen.aclose()
    assert notification_broker.has_subscribers("user-sse-1") is False


@pytest.mark.asyncio
async def test_stream_handshake_does_not_block_the_event_loop(monkeypatch):
    """A token cache miss calls Supabase, whose client is synchronous.

    Run on the event loop it would freeze every other request on this worker for
    the length of that round trip — the real ceiling on concurrent users. This
    asserts the loop keeps ticking while the lookup is in flight.
    """
    import time

    monkeypatch.setattr("cache.get_cached_user_by_token", lambda _t: None)
    monkeypatch.setattr("cache.cache_token_user", lambda *_a, **_k: None)

    def slow_lookup(_token):
        time.sleep(0.2)
        user = MagicMock()
        user.user.id = "user-sse-slow"
        return user

    # `routes.chat` binds `admin_supabase` at import time, so patch it there
    # (conftest.py's mocking-seam rule) rather than on `connector`.
    fake_supabase = MagicMock()
    fake_supabase.auth.get_user = slow_lookup
    monkeypatch.setattr("routes.chat.admin_supabase", fake_supabase)

    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.query_params = {"token": "cold-token"}
    mock_request.is_disconnected = AsyncMock(return_value=False)

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(ticker())
    try:
        response = await notifications_stream(mock_request)
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
async def test_admin_send_message_triggers_notification_and_email(client, admin_user, monkeypatch):
    admin_user(user_id="admin-1", email="admin@example.com", ip="127.0.0.1")

    # Mock buyer user lookup
    fake_user = MagicMock()
    fake_user.user.email = "buyer@example.com"
    monkeypatch.setattr("connector.admin_supabase.auth.admin.get_user_by_id", lambda uid: fake_user)

    fake_send_email = MagicMock()
    monkeypatch.setattr("services.email_service.send_unread_message_email", fake_send_email)

    fake_memory = MagicMock()
    monkeypatch.setattr("agent.memory.conversation_memory", fake_memory, raising=False)

    # Case 1: Buyer is offline (no subscribers)
    assert notification_broker.has_subscribers("offline-buyer") is False
    res = await client.post(
        "/admin/chats/offline-buyer/message",
        json={"message": "Special deal for you!"}
    )
    assert res.status_code == 200
    fake_send_email.assert_called_once_with("buyer@example.com", "Special deal for you!")

    # Case 2: Buyer is online (subscribed)
    fake_send_email.reset_mock()
    q = await notification_broker.subscribe("online-buyer")
    try:
        res = await client.post(
            "/admin/chats/online-buyer/message",
            json={"message": "Are you there?"}
        )
        assert res.status_code == 200
        # Email should NOT be sent when user is online/subscribed
        fake_send_email.assert_not_called()

        # Message should be delivered to queue -- exactly once. It used to be
        # published twice (once by broadcast_to_chat, once here), which is what
        # duplicated every seller message in the buyer's toast stack.
        event = q.get_nowait()
        assert event["message"] == "Are you there?"
        assert q.qsize() == 0
    finally:
        await notification_broker.unsubscribe("online-buyer", q)
