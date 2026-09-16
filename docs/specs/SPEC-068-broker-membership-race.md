---
id: SPEC-068
title: A Live Stream Attached To A Channel Nobody Publishes To
status: complete
priority: high
created: 2026-09-10
tags: [chat, notifications, backend, sse, concurrency]
assigned: agent
---

# Context & Objectives

The buyer sends a message, goes back to the storefront, and the agent's reply
two seconds later produces no toast and no chip. Reload and the chip is there.
A seller's message, over the same stream, usually arrives fine.

Everything measurable said the parts worked. `_deliver` publishes even when the
client hangs up mid-turn (verified against the real ASGI stack over a real
socket). The SSE endpoint holds a stream for 200s untouched and survives 60
concurrent requests. CORS is right. `GET /chat/unread` is right, which is why a
reload always looks right.

What gave it away was a pair of lines in the Redis command log:

    22:02:36  SETEX  sse:ticket:kzmPvRw…  30
    23:04:13  GETDEL sse:ticket:kzmPvRw…        # 61 minutes later

That stream was open the whole hour. So `PUBSUB NUMSUB notify:<uid>` reading
**0** during that hour never meant "the buyer has no stream" — it meant the
server's pub/sub connection was not subscribed to the channel, while a
perfectly healthy SSE connection sat attached to it receiving nothing.

`unsubscribe` dropped the local entry and *then* awaited the Redis command:

    del self._subscribers[user_id]
    await self._pubsub.unsubscribe(channel_for(user_id))   # yields here

A reload overlaps the two by design — the new page's stream subscribes while
the old page's is still tearing down. The subscribe landing in that window found
an empty set, believed it was the first stream for the user, and subscribed;
then the older unsubscribe reached Redis and took the channel away underneath
it.

This is the worst shape the failure could take. There is no error, no
disconnect, nothing for the client to react to — so no client-side retry,
backoff or liveness check can see it (SPEC-067 added all three and none of them
fire). The buyer holds a healthy stream and is never told anything again, until
some later subscribe happens to re-subscribe the channel. Every reload is
another coin flip, which is exactly what "if I'm lucky I see the toast" is.

# Acceptance Criteria

- [x] A stream opening while another closes leaves the channel subscribed for
      as long as any local queue remains.
- [x] The local queue set and the Redis channel it stands for are never
      observable in disagreement.
- [x] Unchanged: the last stream leaving still unsubscribes, and in-process
      (no-Redis) mode still needs no locking of consequence.

# Technical Design & Contracts

One `asyncio.Lock` on the broker guarding both mutators. Both of them await in
the middle of a two-part change — a local set and a remote subscription — and
correctness needs those two parts to move as one.

Deliberately not a per-user lock: membership changes are rare (one per stream
open or close), the critical section is a single Redis round trip, and one lock
cannot deadlock against itself.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** `unsubscribe` and `subscribe` for the same user, run
      concurrently against a pub/sub that actually awaits, leave the channel
      subscribed. Fails pre-fix: the channel is dropped under the live stream.
      Needs `SlowPubSub` — the existing fake resolves without yielding, which
      quietly made every membership change atomic.

# Implementation Files

- `backend/notifications.py`
- `backend/tests/test_notifications.py`
