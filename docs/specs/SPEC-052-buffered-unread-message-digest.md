---
id: SPEC-052
title: Buffered Unread-Message Digest Email
status: complete
priority: medium
created: 2026-09-09
tags: [notifications, email, chat]
assigned: agent
---

# Context & Objectives

Every seller message sent from the admin console to an offline buyer fires its own
email (`routes/admin/chats.py` → `send_unread_message_email`). A seller typing four
short bubbles — which the persona actively encourages — sends four emails in under a
minute. That reads as spam, trains buyers to mute the sender, and costs four Resend
credits to say one thing.

Replace per-message sends with a **buffered digest**: a seller message to an offline
buyer is queued, and only if the buyer still has not read the conversation
`UNREAD_DIGEST_DELAY_SECONDS` (5 min) later does one email go out containing every
message queued in that window.

# Acceptance Criteria

- [x] A seller message to a buyer with **no live SSE stream** is queued, not emailed.
- [x] A seller message to a buyer **with** a live stream is neither queued nor emailed
      (unchanged behaviour — the stream already delivered it).
- [x] A digest flushes only once its **oldest** queued message is ≥ 5 minutes old;
      newer messages queued in the meantime ride along in the same email.
- [x] The buyer reading their chat (`GET /chat/history/{user_id}`) or sending a message
      (`POST /chat/stream`) clears the pending digest — no email is sent for messages
      they have already seen.
- [x] One email carries N messages, oldest first, and states how many there are.
- [x] Flushing is idempotent and safe under multiple uvicorn workers: the queue is
      drained atomically, so two workers cannot send the same digest twice.
- [x] Redis being absent (local dev / tests) degrades to the in-process cache double
      rather than raising.

# Technical Design & Contracts

`backend/services/unread_digest.py` — Redis-backed queue keyed per buyer.

```
KEY  unread:digest:<user_id>   (list)  JSON-encoded {content, item_name, queued_at}
TTL  refreshed on every push; expires well after the flush delay so an orphan
     queue cannot outlive its usefulness.
```

| Function | Behaviour |
| --- | --- |
| `queue_unread_message(user_id, content, item_name=None)` | RPUSH + refresh TTL. Returns queue depth. |
| `mark_conversation_seen(user_id)` | DELETE the key. Returns True when something was pending. |
| `due_digest_user_ids(now)` | SCAN `unread:digest:*`, return users whose oldest entry is ≥ delay old. |
| `drain_digest(user_id)` | Atomically read + delete; returns the queued messages. |
| `flush_due_digests()` | For each due user: drain, resolve the buyer's email, send one digest. Returns count sent. |

`services/email_service.send_unread_digest_email(buyer_email, messages, item_name=None)`
renders `templates/emails/unread_digest.html` — the Ledger design system, one
`quote_box` per message. `send_unread_message_email` is kept: the digest is a
generalisation of it, and a single-message digest still reads naturally.

`main.py` lifespan starts `_unread_digest_loop()` alongside the payment cleanup
worker, sweeping every `UNREAD_DIGEST_SWEEP_SECONDS` (60 s) behind the same
`SETNX` slot lock the cleanup loop uses, so only one worker sweeps per cycle.
`DISABLE_UNREAD_DIGEST=1` opts out.

# Test-Driven Development (TDD) Scenarios

- [x] **Scenario 1 (offline queues, live does not):** `admin_send_message` with no
      subscribers queues one entry and sends no email; with subscribers it queues nothing.
- [x] **Scenario 2 (batching):** three messages queued 6 minutes ago flush as exactly
      one email whose body contains all three.
- [x] **Scenario 3 (not yet due):** a message queued 60 s ago is not flushed.
- [x] **Scenario 4 (seen clears):** `mark_conversation_seen` empties the queue, and a
      subsequent sweep sends nothing.
- [x] **Scenario 5 (buyer read/write clears):** `GET /chat/history/{id}` and a
      `POST /chat/stream` turn both mark the conversation seen.
- [x] **Scenario 6 (drain is atomic):** a second `drain_digest` for the same user
      returns empty, so a concurrent worker cannot re-send.

# Implementation Files

- `backend/services/unread_digest.py` - Queue, due-detection, drain, flush
- `backend/services/email_service.py` - `send_unread_digest_email`
- `backend/templates/emails/unread_digest.html` - Multi-message Ledger template
- `backend/routes/admin/chats.py` - Queue instead of send
- `backend/routes/chat.py` - Mark seen on buyer read / buyer message
- `backend/main.py` - Sweeper task in the lifespan
- `backend/tests/test_unread_digest.py` - Scenarios 1-6
- `backend/cache.py` - List commands + transactional pipeline on the in-memory double
- `docs/adr/0016-buffered-notification-digests.md` - Architecture decision record
