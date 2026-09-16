# Background Workers & Lifespan Tasks

To maintain low operating overhead and stay within the **2 GB RAM envelope** of the AWS Lightsail instance, Nego-Lah avoids heavyweight external workers (like Celery or Celery Beat). 

Instead, background maintenance tasks are structured as **in-process asynchronous loops** bound to the FastAPI application lifespan in `backend/main.py`.

---

## 1. Active Worker Loops

| Worker Name | File Location | Cadence | Primary Responsibility | Concurrency Guard | Opt-Out Flag |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`_payment_cleanup_loop`** | `backend/main.py` | 30 minutes | Scans for expired Stripe payment links in Redis (>3 days old). Deactivates the `PaymentLink` and archives the `Product` in Stripe. | Distributed Redis slot lock (idempotent; only one worker claims execution per cycle). | `DISABLE_PAYMENT_CLEANUP=1` |
| **`_unread_digest_loop`** | `backend/services/unread_digest.py` | 60 seconds | Flushes unread seller messages to offline buyers as a single consolidated digest email after 5 minutes of inactivity ([SPEC-052](../specs/SPEC-052-buffered-unread-message-digest.md), [ADR-0016](../adr/0016-buffered-notification-digests.md)). | Atomic Redis `LRANGE` + `DEL` drain (queue ownership without distributed lock contention). | `DISABLE_UNREAD_DIGEST=1` |

---

## 2. Worker Execution Details

### 2.1 Abandoned Payment Cleanup Loop (`_payment_cleanup_loop`)
When the AI agent generates a negotiated Stripe PaymentLink, pending state is stored in Redis with a 3-day expiration queue. If the buyer never completes the payment within 3 days:
1. The cleanup worker claims the execution slot via Redis lock (`payment:cleanup:lock`).
2. Iterates over expired entries in `payment:cleanup_queue`.
3. Calls Stripe to deactivate the `PaymentLink` (`stripe.PaymentLink.modify(active=False)`) and archives the Stripe `Product`.
4. Deletes the pending payment entry from Redis so stale links cannot be paid later.

### 2.2 Unread Message Digest Loop (`_unread_digest_loop`)
Rather than sending an email for every single chat bubble sent by a seller to an offline buyer (which creates inbox spam):
1. When a seller replies to an unread chat, the message payload is pushed onto a Redis buffer queue: `unread_digest:{user_id}`.
2. Every 60 seconds, `_unread_digest_loop` checks the timestamp of the oldest message in each buffer.
3. If the oldest message is older than 5 minutes (`UNREAD_DIGEST_DELAY_SECONDS=300`) and the buyer has not opened the chat, all buffered messages are drained atomically via `LRANGE` + `DEL`.
4. A single consolidated "Ledger" email digest is rendered and dispatched via Resend.
5. If the buyer reads the conversation or replies before the 5 minutes expire, the queue is dropped immediately without sending an email.

---

## 3. Lifespan Integration & Graceful Shutdown

Workers are launched on application startup and gracefully terminated on SIGTERM/SIGINT:

```python
# backend/main.py lifespan handler
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: spawn tasks on event loop
    task = None
    digest_task = None
    if not os.environ.get("DISABLE_PAYMENT_CLEANUP"):
        task = asyncio.create_task(_payment_cleanup_loop())
    if not os.environ.get("DISABLE_UNREAD_DIGEST"):
        digest_task = asyncio.create_task(_unread_digest_loop())

    yield

    # Shutdown: cancel cleanly and await finish
    for background in (task, digest_task):
        if background:
            background.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await background
```
