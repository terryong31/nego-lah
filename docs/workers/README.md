# Background Work

Nego-Lah runs on one 2 GB instance, so there is no Celery, cron container or worker fleet.
Everything that is not a request runs inside the FastAPI process, started and stopped by the
`lifespan` handler in [`backend/main.py`](../../backend/main.py). Living document.

Each uvicorn worker (two in production) runs its own copy of everything below, so every loop is
written to be safe when several run at once.

## Long-running tasks

| Task | Code | Cadence | Does | Safe to run on every worker because | Disable |
|------|------|---------|------|-------------------------------------|---------|
| **Notification broker** | `core/notifications.py` | Continuous | Holds one Redis pub/sub connection per worker, so a message published by any worker reaches SSE streams held by all of them. | Each worker delivers only to its own streams. | — |
| **Payment cleanup** | `main.py` → `domains/billing/payment_state.py` | Hourly (`CLEANUP_INTERVAL_SECONDS`, default 3600) | Finds payment links past their 3-day expiry in the `payment:cleanup_queue` sorted set, deactivates the Stripe Payment Link, archives its product, and deletes the pending state so a stale link cannot be paid. | A `payment:cleanup:lock` key (`SET NX`) lets one worker run per cycle; the job is idempotent regardless. | `DISABLE_PAYMENT_CLEANUP=1` |
| **Unread digest** | `main.py` → `domains/negotiation/unread_digest.py` | Every 60 s (`UNREAD_DIGEST_SWEEP_SECONDS`) | When the seller writes to a buyer who is not reading, messages queue in `unread:digest:{user_id}`. Five minutes after the oldest (`UNREAD_DIGEST_DELAY_SECONDS`), the queue is drained and sent as one email. Reading the chat first cancels it ([ADR-0016](../adr/0016-buffered-notification-digests.md)). | The drain is one `MULTI/EXEC` read-and-delete; the first worker to reach a queue takes it. | `DISABLE_UNREAD_DIGEST=1` |

Both loops wait 30 s after startup before their first run, and catch and log every error so one
bad cycle never kills the loop.

## Detached agent turns

A buyer's message starts an agent turn as an `asyncio` task that is not tied to the HTTP request,
so closing the tab does not lose the reply ([ADR-0021](../adr/0021-agent-turns-outlive-their-http-response.md)).

## Shutdown

On `SIGTERM` the lifespan handler:

1. waits up to `SHUTDOWN_TURN_GRACE_SECONDS` (20 s) for in-flight agent turns to finish;
2. stops the notification broker;
3. cancels the two loops.

Docker's `stop_grace_period` is 30 s, which leaves room for all three. Open SSE streams are cut;
the SPA reconnects on its own ([SPEC-067](../specs/SPEC-067-notification-stream-recovery.md)).
