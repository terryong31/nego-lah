# ADR 0016: Buffered Notification Digests over Per-Message Email

## Status
Accepted

## Context

`routes/admin/chats.py` emailed the buyer on every seller message that arrived while
they had no live SSE stream. The gate was correct — a buyer sitting in the app is
notified in-band and must not also be mailed — but the granularity was wrong.

The seller persona in `agent/config.py` explicitly instructs short, consecutive
bubbles ("Write like you're texting a friend — SHORT messages, one thought each"),
and the console mirrors that: a human seller types the same way. So one thought,
delivered as four bubbles, sent four emails inside a minute. Three costs follow:

1. **Deliverability.** Four near-identical emails in sixty seconds is the shape of
   spam. Recipients mute the sender, and mailbox providers notice the pattern —
   which puts the *transactional* mail (receipts, SPEC-048) at risk too.
2. **Relevance.** The buyer who reopens the tab thirty seconds later has read
   everything, and the emails are already sent and already wrong.
3. **Cost.** Four Resend credits and four API round trips to say one thing.

The obvious fix — debounce on the send path — does not work: the send handler is a
request that returns, so there is nowhere for it to wait, and holding the request
open to find out whether more messages arrive is the wrong trade entirely.

## Decision

Queue instead of send, and sweep.

1. **Queue on the send path.** A seller message to a buyer with no live stream is
   pushed onto a per-buyer Redis list, `unread:digest:<user_id>`, carrying its text
   and the time it was queued. The send handler returns immediately, as before.

2. **Flush on a delay measured from the OLDEST entry.** A background sweeper in the
   FastAPI lifespan checks every 60 s for queues whose head has waited
   `UNREAD_DIGEST_DELAY_SECONDS` (300 s). Anchoring on the oldest rather than the
   newest entry is what stops a still-typing seller from postponing the digest
   indefinitely — a debounce would have exactly that failure mode.

3. **Two "seen" signals, both of which drop the queue.** The buyer reading their
   chat history (`GET /chat/history/{user_id}`) and the buyer sending a message
   (`POST /chat/stream`). Either proves they are looking at the conversation, so the
   pending email is not merely delayed, it is cancelled.

4. **Ownership by atomic drain, not by lock.** Every uvicorn worker runs the sweep.
   `drain_digest` is a single MULTI/EXEC `LRANGE` + `DEL`, so the first worker to
   reach a queue takes its contents and the others find it empty. The alternative —
   a Redis slot lock like the payment cleanup worker's — would serialise the sweep
   without making it safer, because the drain has to be atomic regardless.

## Consequences

- **One email per burst.** N seller bubbles inside the window become one email with
  N quoted messages, rendered on the same Ledger template system as everything else
  (ADR-0013).
- **A buyer who comes back gets nothing**, which is the correct outcome and was not
  previously achievable at all.
- **Notification latency is now up to 5 minutes.** Deliberate: the buyer with the app
  open already has real-time SSE, so this path only ever serves someone who is away,
  for whom five minutes is indistinguishable from instant.
- **Redis is now load-bearing for a user-visible behaviour**, not just for caches.
  Without it the in-memory double keeps the feature working per-process (correct for
  single-worker dev), and a Redis outage loses pending digests rather than sending
  them twice — the failure mode we prefer.
- **A message queued for a buyer whose email cannot be resolved is dropped**, not
  retried: the address will not resolve on the next sweep either, and retrying every
  60 s forever is worse than losing a notification.
- `DISABLE_UNREAD_DIGEST=1` opts out, mirroring `DISABLE_PAYMENT_CLEANUP`.

## Alternatives considered

- **Debounce on the send path.** Rejected: a request handler cannot wait, and the
  reset-on-every-message behaviour means an active seller never triggers a send.
- **A cron/external scheduler.** Rejected for the same reason `_payment_cleanup_loop`
  runs in-process: it would add an operational dependency to a single Lightsail box
  for a job that costs one Redis scan a minute.
- **Sending on the buyer's reconnect instead.** Rejected: it inverts the semantics —
  a buyer who reconnects has *seen* the messages, which is precisely when no email
  should go out.
