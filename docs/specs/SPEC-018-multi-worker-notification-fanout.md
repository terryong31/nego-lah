---
id: SPEC-018
title: Multi-Worker Notification Fan-out and SSE Concurrency Hardening
status: complete
priority: high
created: 2026-09-05
tags: [backend, notifications, sse, redis, concurrency, scalability]
assigned: agent
---

# Context & Objectives
The API serves under `uvicorn --workers ${WEB_CONCURRENCY:-4}` (four processes), but `NotificationBroker` keeps its subscriber queues in a plain in-process dict. A buyer's SSE stream is pinned to whichever worker accepted it, while the seller's `POST /admin/chats/{id}/message` lands on any worker:

- ~3 in 4 seller messages never reach the buyer's live stream.
- `has_subscribers()` answers for one process only, so the same messages are also mis-classified as "buyer offline" and trigger an unread-message **email** to someone who is online.
- Local dev runs a single process (`--reload`), which is why this is invisible until production.

Two further concurrency hazards in the same path: subscriber queues are unbounded (a stalled client accumulates events until its disconnect is noticed, up to ~15s later), and the SSE handshake calls the **synchronous** `admin_supabase.auth.get_user()` on the event loop, stalling every other request on that worker for the duration of a Supabase round trip.

Objective: correct, once-only delivery to every live stream regardless of worker, with bounded memory per client, sized to serve well beyond 15 concurrent users.

# Acceptance Criteria
- [x] A notification published on any worker reaches every live SSE stream for that user, exactly once per stream.
- [x] `has_subscribers()` reflects connections held by *any* worker, so the email fallback only fires when the buyer is genuinely offline.
- [x] Redis is optional: with no `REDIS_URL` (dev, tests) the broker degrades to correct in-process delivery.
- [x] The pub/sub listener survives a Redis restart — it reconnects and re-subscribes every active channel.
- [x] Per-subscriber queues are bounded; on overflow the oldest event is dropped, never the newest, and never the connection.
- [x] No blocking I/O on the event loop in the SSE handshake or the chat endpoints.
- [x] A stream that is never iterated leaves no subscription behind.

# Technical Design & Contracts
### `backend/notifications.py`
Redis pub/sub on per-user channels `notify:{user_id}`.
- `await start()` / `await stop()` — owned by the FastAPI lifespan; open one `redis.asyncio` pub/sub connection per worker plus a listener task. Falls back to in-process mode when Redis is absent or unreachable.
- `await subscribe(user_id) -> asyncio.Queue` / `await unsubscribe(user_id, queue)` — local bookkeeping plus channel subscribe/unsubscribe on the first/last local stream.
- `publish(user_id, payload)` stays **sync** (callers are sync): publishes to Redis when distributed — the worker's own listener delivers it back, so there is exactly one local delivery — otherwise delivers in-process.
- `has_subscribers(user_id)` = local queues **or** `PUBSUB NUMSUB notify:{user_id} > 0`. Redis maintains that count itself, so a crashed worker stops counting the moment its connection drops — no TTL bookkeeping to get wrong.
- `MAX_QUEUED_EVENTS = 100` per queue, drop-oldest on overflow.

### `backend/routes/chat.py`
`await` the broker's subscribe/unsubscribe, and subscribe **inside** the response generator so it is always paired with the `finally` that releases it. Every synchronous Supabase/Realtime call in the `async def` handlers (`broadcast_to_chat`, `conversation_memory.*`, `chat_settings` reads/writes, the token lookup) now runs through `asyncio.to_thread` — these were multi-hundred-millisecond HTTP round trips executing *on* the event loop, which is what actually caps concurrent users.

### `backend/main.py`
`await notification_broker.start()` in the lifespan, `await notification_broker.stop()` on shutdown.

# Test-Driven Development (TDD) Scenarios
- [x] **Scenario 1:** In-process mode still fans one publish out to every subscriber of that user and to no one else.
- [x] **Scenario 2:** A full queue drops its oldest event and still accepts the newest; the subscriber is never disconnected.
- [x] **Scenario 3:** In distributed mode `publish()` writes to Redis instead of delivering locally, and the listener's delivery path puts the event on local queues exactly once.
- [x] **Scenario 4:** `has_subscribers()` is true for a user whose only stream lives on another worker (`PUBSUB NUMSUB > 0`), and false when nothing is subscribed anywhere.
- [x] **Scenario 5:** `start()` degrades to in-process mode when Redis is unreachable, and the listener re-subscribes active channels after a dropped connection.
- [x] **Scenario 6:** With a 200ms synchronous token lookup, a concurrent ticker keeps advancing — the loop is not blocked — and no subscription exists until the body is iterated.
- [x] **Scenario 7 (manual):** Two broker instances against a live Redis: a publish on "worker B" reaches "worker A"'s queue exactly once, and B's `has_subscribers` tracks A's connection in both directions.

# Implementation Files
- `backend/notifications.py` - Redis-backed broker.
- `backend/routes/chat.py` - async subscribe/unsubscribe, non-blocking auth.
- `backend/main.py` - lifespan wiring.
- `backend/tests/test_notifications.py`, `backend/tests/test_routes_chat_notifications.py` - coverage.
