"""
Tests for notifications.py.

The broker has two modes and both matter:

- **in-process** (no REDIS_URL — local dev and most of this suite): queues are
  fed directly, which is correct for a single process.
- **distributed** (Redis pub/sub): what production runs under
  `uvicorn --workers N`. A buyer's SSE stream lives on one worker while the
  seller's POST lands on another, so publishing has to go through Redis and
  `has_subscribers()` has to see connections held by other workers.

Distributed mode is faked here rather than requiring a live Redis: `distributed`
is true whenever a listener task is running, so the tests install a parked task
and a stub Redis client.
"""

import asyncio
import contextlib
import json
from unittest.mock import MagicMock

import pytest

import notifications
from notifications import MAX_QUEUED_EVENTS, NotificationBroker, channel_for


@contextlib.asynccontextmanager
async def distributed(broker: NotificationBroker, redis_stub):
    """Run the block with `broker` believing it is Redis-backed."""
    parked = asyncio.create_task(asyncio.Event().wait())
    broker._listener = parked
    import cache

    original = cache.redis_client
    cache.redis_client = redis_stub
    try:
        yield
    finally:
        cache.redis_client = original
        parked.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await parked
        broker._listener = None


class FakePubSub:
    def __init__(self):
        self.subscribed: set[str] = set()
        self.closed = False

    async def subscribe(self, *channels):
        self.subscribed.update(channels)

    async def unsubscribe(self, *channels):
        self.subscribed.difference_update(channels)

    async def aclose(self):
        self.closed = True


# ---------------------------------------------------------------------------
# In-process delivery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_notification_broker_pub_sub():
    broker = NotificationBroker()
    user_id = "test-user-123"

    assert broker.has_subscribers(user_id) is False

    queue = await broker.subscribe(user_id)
    assert broker.has_subscribers(user_id) is True

    payload = {"type": "new_message", "message": "Hello there!", "source": "admin"}
    broker.publish(user_id, payload)

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received == payload

    await broker.unsubscribe(user_id, queue)
    assert broker.has_subscribers(user_id) is False


@pytest.mark.asyncio
async def test_notification_broker_multiple_subscribers():
    broker = NotificationBroker()
    user_id = "test-user-multi"

    q1 = await broker.subscribe(user_id)
    q2 = await broker.subscribe(user_id)

    payload = {"type": "new_message", "message": "Broadcast"}
    broker.publish(user_id, payload)

    r1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    r2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert r1 == payload
    assert r2 == payload

    await broker.unsubscribe(user_id, q1)
    assert broker.has_subscribers(user_id) is True
    await broker.unsubscribe(user_id, q2)
    assert broker.has_subscribers(user_id) is False


@pytest.mark.asyncio
async def test_publish_reaches_only_the_addressed_user():
    broker = NotificationBroker()
    mine = await broker.subscribe("buyer-1")
    theirs = await broker.subscribe("buyer-2")

    broker.publish("buyer-1", {"message": "for buyer 1"})

    assert (await asyncio.wait_for(mine.get(), timeout=1.0)) == {"message": "for buyer 1"}
    assert theirs.empty()


# ---------------------------------------------------------------------------
# Bounded queues
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_queue_is_bounded_and_drops_the_oldest_event():
    """A client that stops draining must not grow the server's memory."""
    broker = NotificationBroker()
    queue = await broker.subscribe("slow-client")

    for i in range(MAX_QUEUED_EVENTS + 5):
        broker.publish("slow-client", {"n": i})

    assert queue.qsize() == MAX_QUEUED_EVENTS

    drained = [queue.get_nowait() for _ in range(MAX_QUEUED_EVENTS)]
    # The newest survived; the first five were dropped to make room.
    assert drained[-1] == {"n": MAX_QUEUED_EVENTS + 4}
    assert drained[0] == {"n": 5}


@pytest.mark.asyncio
async def test_a_stalled_subscriber_does_not_block_its_peers():
    broker = NotificationBroker()
    stalled = await broker.subscribe("shared-user")
    healthy = await broker.subscribe("shared-user")

    for i in range(MAX_QUEUED_EVENTS + 2):
        broker.publish("shared-user", {"n": i})
        # The healthy client keeps up.
        healthy.get_nowait()

    assert stalled.qsize() == MAX_QUEUED_EVENTS
    assert healthy.empty()


# ---------------------------------------------------------------------------
# Distributed (multi-worker) delivery
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_goes_through_redis_when_distributed():
    """Otherwise only streams on the publishing worker would ever be fed."""
    broker = NotificationBroker()
    queue = await broker.subscribe("buyer-1")
    redis_stub = MagicMock()

    async with distributed(broker, redis_stub):
        broker.publish("buyer-1", {"message": "hi"})

    redis_stub.publish.assert_called_once_with(
        channel_for("buyer-1"), json.dumps({"message": "hi"})
    )
    # Not delivered twice: the worker's own listener will feed this queue when
    # the message comes back around.
    assert queue.empty()


@pytest.mark.asyncio
async def test_listener_delivery_feeds_local_queues_exactly_once():
    broker = NotificationBroker()
    queue = await broker.subscribe("buyer-1")

    broker.deliver_local("buyer-1", {"message": "from another worker"})

    assert (await asyncio.wait_for(queue.get(), timeout=1.0)) == {"message": "from another worker"}
    assert queue.empty()


@pytest.mark.asyncio
async def test_publish_falls_back_in_process_when_redis_publish_fails():
    broker = NotificationBroker()
    queue = await broker.subscribe("buyer-1")
    redis_stub = MagicMock()
    redis_stub.publish.side_effect = RuntimeError("redis down")

    async with distributed(broker, redis_stub):
        broker.publish("buyer-1", {"message": "still delivered"})

    assert (await asyncio.wait_for(queue.get(), timeout=1.0)) == {"message": "still delivered"}


@pytest.mark.asyncio
async def test_has_subscribers_sees_streams_held_by_other_workers():
    """The email fallback keys off this: a false 'offline' emails a live user."""
    broker = NotificationBroker()
    redis_stub = MagicMock()

    async with distributed(broker, redis_stub):
        redis_stub.pubsub_numsub.return_value = [(channel_for("elsewhere"), 1)]
        assert broker.has_subscribers("elsewhere") is True

        redis_stub.pubsub_numsub.return_value = [(channel_for("nobody"), 0)]
        assert broker.has_subscribers("nobody") is False

        redis_stub.pubsub_numsub.side_effect = RuntimeError("redis down")
        assert broker.has_subscribers("nobody") is False


@pytest.mark.asyncio
async def test_local_subscribers_short_circuit_the_redis_lookup():
    broker = NotificationBroker()
    queue = await broker.subscribe("here")
    redis_stub = MagicMock()

    async with distributed(broker, redis_stub):
        assert broker.has_subscribers("here") is True
        redis_stub.pubsub_numsub.assert_not_called()

    await broker.unsubscribe("here", queue)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_stays_in_process_without_a_redis_url(monkeypatch):
    monkeypatch.setattr(notifications, "REDIS_URL", "")
    broker = NotificationBroker()

    assert await broker.start() is False
    assert broker.distributed is False

    # Still fully functional for a single process.
    queue = await broker.subscribe("solo")
    broker.publish("solo", {"message": "works"})
    assert (await asyncio.wait_for(queue.get(), timeout=1.0)) == {"message": "works"}


@pytest.mark.asyncio
async def test_start_degrades_gracefully_when_redis_is_unreachable(monkeypatch):
    monkeypatch.setattr(notifications, "REDIS_URL", "redis://127.0.0.1:6399/0")

    class Boom:
        @staticmethod
        def from_url(*_args, **_kwargs):
            raise ConnectionError("no route to redis")

    monkeypatch.setitem(__import__("sys").modules, "redis.asyncio", Boom)
    broker = NotificationBroker()

    assert await broker.start() is False
    assert broker.distributed is False


@pytest.mark.asyncio
async def test_start_gives_up_rather_than_hanging_on_a_wedged_redis(monkeypatch):
    """Startup runs inside the FastAPI lifespan: a Redis that accepts the TCP
    connection but never answers would leave uvicorn listening and unresponsive
    (and wedge `--reload`), so the connect has to be bounded."""
    monkeypatch.setattr(notifications, "REDIS_URL", "redis://10.255.255.1:6379/0")
    monkeypatch.setattr(notifications, "CONNECT_TIMEOUT_SECONDS", 0.2)

    class NeverAnswers:
        @staticmethod
        def from_url(*_args, **_kwargs):
            client = MagicMock()

            async def _hang():
                await asyncio.sleep(30)

            client.ping = _hang
            client.aclose = _hang
            return client

    monkeypatch.setitem(__import__("sys").modules, "redis.asyncio", NeverAnswers)
    broker = NotificationBroker()

    started = await asyncio.wait_for(broker.start(), timeout=3)

    assert started is False
    assert broker.distributed is False
    # And teardown of a half-open connection is bounded too.
    await asyncio.wait_for(broker.stop(), timeout=3)


@pytest.mark.asyncio
async def test_resubscribe_restores_every_active_channel():
    """After a Redis restart the worker must re-register its live streams."""
    broker = NotificationBroker()
    await broker.subscribe("buyer-1")
    await broker.subscribe("buyer-2")

    fresh = FakePubSub()
    stale = FakePubSub()
    broker._pubsub = stale
    broker._redis = MagicMock(pubsub=MagicMock(return_value=fresh))

    assert await broker._resubscribe() is True

    assert stale.closed is True
    assert fresh.subscribed == {
        notifications.KEEPALIVE_CHANNEL,
        channel_for("buyer-1"),
        channel_for("buyer-2"),
    }


@pytest.mark.asyncio
async def test_stop_cancels_the_listener_and_closes_the_connection():
    broker = NotificationBroker()
    pubsub = FakePubSub()
    broker._pubsub = pubsub
    broker._redis = MagicMock(aclose=MagicMock(side_effect=lambda: asyncio.sleep(0)))
    broker._listener = asyncio.create_task(asyncio.Event().wait())

    await broker.stop()

    assert broker.distributed is False
    assert broker._listener is None
    assert pubsub.closed is True


@pytest.mark.asyncio
async def test_subscribing_registers_the_users_channel_when_distributed():
    broker = NotificationBroker()
    pubsub = FakePubSub()
    broker._pubsub = pubsub

    async with distributed(broker, MagicMock()):
        queue = await broker.subscribe("buyer-1")
        assert pubsub.subscribed == {channel_for("buyer-1")}

        # A second stream for the same user reuses the channel...
        second = await broker.subscribe("buyer-1")
        assert pubsub.subscribed == {channel_for("buyer-1")}

        # ...and the channel is only released once the last one goes.
        await broker.unsubscribe("buyer-1", queue)
        assert pubsub.subscribed == {channel_for("buyer-1")}
        await broker.unsubscribe("buyer-1", second)
        assert pubsub.subscribed == set()
