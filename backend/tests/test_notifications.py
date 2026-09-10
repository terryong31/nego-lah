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
    # A distributed broker always holds a subscribed pub/sub -- that is what
    # makes its own listener feed the local queues. Tests that install their
    # own pub/sub keep it.
    previous_pubsub = broker._pubsub
    if broker._pubsub is None:
        broker._pubsub = FakePubSub()
        await broker._pubsub.subscribe(notifications.KEEPALIVE_CHANNEL)
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
        broker._pubsub = previous_pubsub


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


# ---------------------------------------------------------------------------
# SPEC-058: listener reconnect (hot-spin regression)
# ---------------------------------------------------------------------------

class SpinDetected(BaseException):
    """Raised by the fake once the listener has clearly stopped throttling.

    Deliberately a BaseException: the broker catches `Exception`, and this has
    to escape that handler to end the test instead of feeding the very loop it
    is diagnosing.
    """


class ExhaustedPubSub(FakePubSub):
    """A pub/sub whose subscription is gone.

    This is the shape redis-py leaves behind after a dropped connection:
    `PubSub.listen()` is `while self.subscribed:`, so with no channels it
    *returns* instead of raising. A `while True` that only reconnects in its
    `except` branch therefore respins with nothing to await.

    `listen()` yields to the event loop before returning. The real one does not,
    which is why the unfixed broker wedges the loop outright -- a test written
    against that hangs instead of failing, so the fake keeps the loop breathing
    and counts instead.
    """

    SPIN_LIMIT = 200

    def __init__(self):
        super().__init__()
        self.listen_calls = 0

    async def listen(self):
        self.listen_calls += 1
        if self.listen_calls > self.SPIN_LIMIT:
            raise SpinDetected(f"listen() re-entered {self.listen_calls} times without throttling")
        await asyncio.sleep(0)
        return
        yield  # pragma: no cover - makes this an async generator


async def _run_listener_briefly(broker, seconds=0.2):
    task = asyncio.create_task(broker._listen())
    await asyncio.sleep(seconds)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, SpinDetected):
        await task


@pytest.mark.asyncio
async def test_listener_does_not_spin_when_listen_returns_without_raising(monkeypatch):
    """The bug this pins: a normally-returning `listen()` skipped the `except`
    branch, so the loop re-entered it with no sleep -- measured at ~3.6M
    iterations/sec, pegging the event loop and starving the worker's requests.
    SIGTERM could not even land, because the task never yielded."""
    monkeypatch.setattr(notifications, "RECONNECT_DELAY_SECONDS", 0.05)
    broker = NotificationBroker()
    exhausted = ExhaustedPubSub()
    broker._pubsub = exhausted
    broker._redis = MagicMock(pubsub=MagicMock(return_value=exhausted))

    await _run_listener_briefly(broker)

    # Roughly one attempt per reconnect delay. Unthrottled, this runs away.
    assert exhausted.listen_calls <= 10, (
        f"listener re-entered listen() {exhausted.listen_calls} times in 200ms -- not awaiting"
    )
    assert exhausted.listen_calls >= 1, "listener never called listen() at all"


@pytest.mark.asyncio
async def test_listener_reconnects_after_listen_returns_without_raising(monkeypatch):
    """Recovery must not depend on an exception being raised, or the broker
    stays dead after Redis comes back -- which is what stranded it in the wild."""
    monkeypatch.setattr(notifications, "RECONNECT_DELAY_SECONDS", 0.05)
    broker = NotificationBroker()
    await broker.subscribe("buyer-1")

    stale = ExhaustedPubSub()
    fresh = ExhaustedPubSub()
    broker._pubsub = stale
    broker._redis = MagicMock(pubsub=MagicMock(return_value=fresh))

    await _run_listener_briefly(broker)

    assert stale.closed is True, "the dead pub/sub was never torn down"
    assert notifications.KEEPALIVE_CHANNEL in fresh.subscribed
    assert channel_for("buyer-1") in fresh.subscribed


@pytest.mark.asyncio
async def test_listener_cancellation_stays_immediate(monkeypatch):
    """`stop()` runs on the path uvicorn waits for, so the new reconnect path
    must not swallow CancelledError."""
    monkeypatch.setattr(notifications, "RECONNECT_DELAY_SECONDS", 30)
    broker = NotificationBroker()
    exhausted = ExhaustedPubSub()
    broker._pubsub = exhausted
    broker._redis = MagicMock(pubsub=MagicMock(return_value=exhausted))

    task = asyncio.create_task(broker._listen())
    await asyncio.sleep(0.05)  # let it reach the reconnect sleep
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_publish_delivers_locally_when_the_pubsub_is_not_subscribed():
    """Redis being reachable is not enough: if this worker's pub/sub holds no
    channels, nothing will ever feed the local queues, so publishing into Redis
    discards the event. Observed live -- the buyer got neither the SSE event nor
    the unread-digest email, because `has_subscribers()` still saw them online.
    """
    broker = NotificationBroker()
    queue = await broker.subscribe("buyer-1")
    redis_stub = MagicMock()

    async with distributed(broker, redis_stub):
        broker._pubsub = FakePubSub()  # connected, but zero channels
        broker.publish("buyer-1", {"message": "must not vanish"})

    redis_stub.publish.assert_not_called()
    assert (await asyncio.wait_for(queue.get(), timeout=1.0)) == {"message": "must not vanish"}
