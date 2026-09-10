---
id: SPEC-058
title: Notification Listener Reconnect (Hot-Spin Fix)
status: complete
priority: high
created: 2026-09-10
tags: [notifications, redis, reliability, performance]
assigned: agent
---

# Context & Objectives

`NotificationBroker._listen()` wraps `redis.asyncio.PubSub.listen()` in
`while True`, and puts its sleep + `_resubscribe()` **only in the `except`
branch**. But `listen()` is implemented as `while self.subscribed:` — when the
pub/sub has no channels left it **returns normally instead of raising**. The
`except` branch never runs, so the loop respins with nothing to await.

Observed on a dev machine after the laptop slept and Redis restarted: the
uvicorn worker pegged one core at 100% for minutes. Measured at **3.6 million
no-op iterations per second**.

Two failures, not one:

1. **CPU**: the event loop spins, starving every request the worker serves.
2. **Silent notification loss**: `distributed` only checks that the listener
   task is alive, and a spinning task is alive. So `publish()` kept routing to
   Redis and returning early, while nothing was subscribed — every event was
   discarded. `has_subscribers()` still reported the user online from the local
   queue set, so `routes/admin/chats.py` also skipped the unread-digest email.
   A buyer with the tab open received neither the live event nor the catch-up
   email.

Recovery never happened either: the reconnect code is unreachable from this
state, so the broker stayed dead after Redis came back.

# Acceptance Criteria

- [x] A `listen()` that returns without raising is treated as a disconnect:
      logged, then throttled by `RECONNECT_DELAY_SECONDS` and reconnected via
      the same path as an exception.
- [x] The listener never iterates without awaiting — no code path re-enters
      `listen()` without an intervening sleep.
- [x] `asyncio.CancelledError` still propagates, so `stop()` remains immediate.
- [x] `publish()` delivers in-process whenever this worker's pub/sub is not
      actually subscribed, rather than dropping the event into Redis.
- [x] Recovery is automatic once Redis returns; no restart required.

# Technical Design & Contracts

`_listen()` gains an `else:` branch for the normal-return case and moves the
sleep + `_resubscribe()` **below** the `try`, so exception and clean-exit paths
share one throttled reconnect. No public API changes.

`publish()` gates on a new private `_receiving` property — `distributed` **and**
`self._pubsub.subscribed` — derived state, not a flag, so it cannot drift.
`distributed` keeps its current meaning (Redis mode is active) because `start()`
and `stop()` are specified in terms of it.

Trade-off: during a reconnect window a publish reaches only the local worker's
streams instead of all workers. Strictly better than reaching nobody.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1:** With a pub/sub whose `listen()` returns immediately, run
      `_listen()` for 200ms — `listen()` is called a handful of times, not
      millions, and `_resubscribe()` runs. Fails pre-fix (hot spin).
- [x] **Scenario 2:** A `listen()` that returns normally still triggers
      reconnection, restoring every active user channel.
- [x] **Scenario 3:** Cancelling the listener task remains immediate.
- [x] **Scenario 4:** `publish()` with a connected-but-unsubscribed pub/sub
      delivers to the local queue and does **not** call `redis.publish`.
- [x] **Scenario 5:** Existing distributed-mode behaviour is unchanged when the
      pub/sub is genuinely subscribed.

# Implementation Files

- `backend/notifications.py` - `_listen()` reconnect path, `_receiving` gate on `publish()`
- `backend/tests/test_notifications.py` - regression coverage; `distributed()` helper
  now installs a subscribed pub/sub so the fake matches the real invariant
