"""
Real-Time Notification Broker

Fans "you have a new message" events out to every live SSE stream for a user.

Delivery goes through Redis pub/sub so it survives multiple uvicorn workers: a
buyer's SSE connection is pinned to whichever worker accepted it, while the
seller's POST lands on any of them. A purely in-process broker only delivers
when both happen to hit the same worker — a 1-in-N coin flip under
`--workers N` — and reports the buyer as offline the rest of the time, which
emails someone who is sitting right there with the tab open.

Redis is optional. Without it (local dev, tests) the broker degrades to
in-process delivery, which is exactly correct for a single process.
"""

import asyncio
import contextlib
import json
from collections import defaultdict
from typing import Any

from env import REDIS_URL
from logger import logger

CHANNEL_PREFIX = "notify:"

# Keeps the pub/sub connection alive while no user channels are subscribed —
# `listen()` on a subscription-less pub/sub has nothing to wait on.
KEEPALIVE_CHANNEL = f"{CHANNEL_PREFIX}__keepalive__"

# A stalled client (backgrounded phone, half-open TCP) must not grow its queue
# without bound: its disconnect is only noticed between events, up to the SSE
# ping interval later. 100 events is far more than a conversation produces in
# that window; past it we drop the OLDEST, since a notification's value decays
# with age and the newest one is the one worth showing.
MAX_QUEUED_EVENTS = 100

# How long to wait before rebuilding a dropped pub/sub connection.
RECONNECT_DELAY_SECONDS = 2.0

# Startup must not hang on Redis: the app is fully functional without it, just
# single-worker for notifications.
CONNECT_TIMEOUT_SECONDS = 3.0


def channel_for(user_id: str) -> str:
    return f"{CHANNEL_PREFIX}{user_id}"


class NotificationBroker:
    """Manages active SSE subscriber queues per user, across workers."""

    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._redis = None
        self._pubsub = None
        self._listener: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # Lifecycle (owned by the FastAPI lifespan)
    # ------------------------------------------------------------------

    @property
    def distributed(self) -> bool:
        """True when events are travelling through Redis rather than staying in-process."""
        return self._listener is not None and not self._listener.done()

    @property
    def _receiving(self) -> bool:
        """True when this worker's listener will actually get the message back.

        `distributed` only says a listener task exists. A task that is alive but
        holds no subscription receives nothing, so publishing through Redis
        would drop the event -- and `has_subscribers()` would still report the
        user online from the local queue set, suppressing the digest email too.
        Derived rather than tracked, so it cannot drift from the connection.
        """
        return self.distributed and bool(getattr(self._pubsub, "subscribed", False))

    async def start(self) -> bool:
        """Open the pub/sub connection for this worker. Returns True if distributed."""
        if self.distributed:
            return True

        if not REDIS_URL:
            logger.info("🔔 Notification broker running in-process (no REDIS_URL configured)")
            return False

        try:
            import redis.asyncio as redis_asyncio

            # Bounded connect: notifications are a nice-to-have, so a slow or
            # unreachable Redis must never hold the app's startup hostage.
            # No `socket_timeout` — the pub/sub connection sits idle by design,
            # and a read deadline would tear it down every few seconds;
            # `health_check_interval` keeps it honest instead.
            self._redis = redis_asyncio.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
                health_check_interval=30,
            )
            await asyncio.wait_for(self._redis.ping(), timeout=CONNECT_TIMEOUT_SECONDS)
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            await asyncio.wait_for(
                self._pubsub.subscribe(KEEPALIVE_CHANNEL, *self._active_channels()),
                timeout=CONNECT_TIMEOUT_SECONDS,
            )
            self._listener = asyncio.create_task(self._listen())
            logger.info("🔔 Notification broker connected to Redis pub/sub (multi-worker fan-out)")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Notification broker falling back to in-process delivery: {e}")
            await self._close_redis()
            return False

    async def stop(self):
        """Tear the pub/sub connection down; queued subscribers simply stop receiving."""
        if self._listener:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        await self._close_redis()

    async def _close_redis(self):
        # Bounded, because shutdown runs on the path uvicorn waits for: a close
        # that blocks on a wedged socket would hang the reload/restart itself.
        if self._pubsub is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._pubsub.aclose(), timeout=CONNECT_TIMEOUT_SECONDS)
            self._pubsub = None
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._redis.aclose(), timeout=CONNECT_TIMEOUT_SECONDS)
            self._redis = None

    def _active_channels(self) -> list[str]:
        return [channel_for(uid) for uid, queues in self._subscribers.items() if queues]

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    async def subscribe(self, user_id: str) -> asyncio.Queue:
        """Register a new subscriber queue for a user."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUED_EVENTS)
        first_for_user = not self._subscribers[user_id]
        self._subscribers[user_id].add(queue)

        if first_for_user and self.distributed:
            try:
                await self._pubsub.subscribe(channel_for(user_id))
            except Exception as e:
                logger.warning(f"⚠️ Could not subscribe to {channel_for(user_id)}: {e}")

        logger.info(
            f"🔔 User {user_id} subscribed to notification stream "
            f"(local: {len(self._subscribers[user_id])})"
        )
        return queue

    async def unsubscribe(self, user_id: str, queue: asyncio.Queue):
        """Remove a subscriber queue when its client disconnects."""
        queues = self._subscribers.get(user_id)
        if queues is not None:
            queues.discard(queue)
            if not queues:
                del self._subscribers[user_id]
                if self.distributed:
                    with contextlib.suppress(Exception):
                        await self._pubsub.unsubscribe(channel_for(user_id))
        logger.info(f"🔕 User {user_id} unsubscribed from notification stream")

    def has_subscribers(self, user_id: str) -> bool:
        """Return True if this user has a live stream on ANY worker.

        Redis maintains the subscriber count itself, so a worker that died with
        streams open stops counting the instant its connection drops — no TTL
        bookkeeping of our own to get wrong.
        """
        if self._subscribers.get(user_id):
            return True
        if not self.distributed:
            return False
        try:
            from cache import redis_client

            counts = redis_client.pubsub_numsub(channel_for(user_id))
            return bool(counts and counts[0][1] > 0)
        except Exception as e:
            logger.debug(f"Could not read subscriber count for {user_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, user_id: str, payload: dict[str, Any]):
        """Publish an event to every live stream for this user, on any worker.

        Stays synchronous because its callers are (broadcast_to_chat runs from
        both sync routes and agent threads). When distributed, this worker's own
        listener receives the message back and delivers it locally, so every
        stream is fed exactly once.
        """
        if self._receiving:
            try:
                from cache import redis_client

                redis_client.publish(channel_for(user_id), json.dumps(payload))
                logger.info(f"📢 Published notification to {channel_for(user_id)}")
                return
            except Exception as e:
                logger.warning(f"⚠️ Redis publish failed, delivering in-process: {e}")

        self.deliver_local(user_id, payload)

    def deliver_local(self, user_id: str, payload: dict[str, Any]):
        """Put an event on this worker's queues for a user, dropping the oldest when full."""
        queues = self._subscribers.get(user_id, set())
        for q in list(queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # The client is not draining; keep the newest event, not the stalest.
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(payload)
                logger.warning(f"⚠️ Notification queue full for user {user_id}; dropped oldest event")
            except Exception as e:
                logger.warning(f"⚠️ Failed to deliver to queue for user {user_id}: {e}")
        logger.info(f"📬 Delivered notification to user {user_id} ({len(queues)} local connections)")

    # ------------------------------------------------------------------
    # Listener
    # ------------------------------------------------------------------

    async def _listen(self):
        """Fan Redis messages out to this worker's queues, reconnecting as needed."""
        while True:
            try:
                async for message in self._pubsub.listen():
                    if message.get("type") != "message":
                        continue
                    channel = message.get("channel") or ""
                    if not channel.startswith(CHANNEL_PREFIX):
                        continue
                    user_id = channel[len(CHANNEL_PREFIX):]
                    try:
                        payload = json.loads(message.get("data") or "{}")
                    except (TypeError, ValueError):
                        logger.warning(f"⚠️ Discarding malformed notification on {channel}")
                        continue
                    self.deliver_local(user_id, payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"🔁 Notification pub/sub dropped ({e}); reconnecting")
            else:
                # `listen()` is `while self.subscribed:` -- with no channels left
                # it RETURNS rather than raising, so this is a disconnect that
                # never throws. Falling straight back into `while True` would
                # re-enter it with nothing to await: a hot spin that pegs the
                # event loop, blocks even SIGTERM, and never reconnects.
                logger.warning("🔁 Notification pub/sub ended with no active subscription; reconnecting")

            # Reached from both paths, so neither can respin without awaiting.
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
            if not await self._resubscribe():
                # Redis is still down; back off and try again on the next pass.
                await asyncio.sleep(RECONNECT_DELAY_SECONDS)

    async def _resubscribe(self) -> bool:
        """Rebuild the pub/sub connection and re-subscribe every active channel."""
        try:
            if self._pubsub is not None:
                with contextlib.suppress(Exception):
                    await self._pubsub.aclose()
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            await self._pubsub.subscribe(KEEPALIVE_CHANNEL, *self._active_channels())
            logger.info("🔔 Notification pub/sub reconnected")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Notification pub/sub reconnect failed: {e}")
            return False


notification_broker = NotificationBroker()
