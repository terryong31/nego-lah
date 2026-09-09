"""Buffered unread-message digests (SPEC-052).

Every seller message sent from the admin console to an offline buyer used to
fire its own email. The seller persona actively encourages short consecutive
bubbles — "Great choice! / This one's mint btw / I can do 10% off" — so saying
one thing sent three emails inside a minute. That reads as spam, trains the
buyer to mute the sender, and costs three Resend credits for one thought.

So a message to an offline buyer is *queued* instead. A sweeper checks the
queues once a minute and, for any buyer whose OLDEST pending message has been
waiting `UNREAD_DIGEST_DELAY_SECONDS`, drains the whole queue and sends exactly
one email containing all of it.

"Still hasn't seen it" is answered by two signals, both of which clear the
queue: the buyer opening their chat history, and the buyer sending a message.
Presence on the SSE stream is checked at *queue* time rather than here — a
message that reached a live stream was already delivered and is never queued.

Under `--workers N` every worker runs the sweep loop, so the drain has to be
the thing that decides ownership: it is a single MULTI/EXEC read-then-delete, so
whichever worker gets there first takes the messages and the rest find nothing.
No separate lock, and no window where a digest could go out twice.
"""

import json
import os
import time

from cache import redis_client
from logger import logger

DIGEST_KEY_PREFIX = "unread:digest:"

# How long a buyer gets to come back and read before the email is sent.
UNREAD_DIGEST_DELAY_SECONDS = int(os.getenv("UNREAD_DIGEST_DELAY_SECONDS", "300"))

# How often the sweeper looks for due queues. Finer than the delay, so a digest
# goes out within a minute of becoming due rather than up to five late.
UNREAD_DIGEST_SWEEP_SECONDS = int(os.getenv("UNREAD_DIGEST_SWEEP_SECONDS", "60"))

# A queue nobody ever drains (Redis restarted mid-sweep, a user deleted) must
# not live forever. Generous multiple of the delay: long enough that a slow
# sweep never loses real messages, short enough to be self-cleaning.
DIGEST_TTL_SECONDS = max(UNREAD_DIGEST_DELAY_SECONDS * 12, 3600)

# Cap on how many messages one digest carries. A runaway loop must not build an
# unbounded email; past this the newest are kept, since an email opened later
# is more useful ending on the latest offer than the first one.
MAX_DIGEST_MESSAGES = 50


def _key(user_id: str) -> str:
    return f"{DIGEST_KEY_PREFIX}{user_id}"


def queue_unread_message(user_id: str, content: str, item_name: str | None = None) -> int:
    """Add a seller message to this buyer's pending digest.

    Returns the queue depth (0 if the queue could not be written — the caller is
    a best-effort notification path and must not fail the send because of it).
    """
    entry = json.dumps({
        "content": content,
        "item_name": item_name,
        "queued_at": time.time(),
    })
    try:
        depth = redis_client.rpush(_key(user_id), entry)
        redis_client.expire(_key(user_id), DIGEST_TTL_SECONDS)
        logger.info(f"📥 Queued unread message for {user_id} (pending: {depth})")
        return int(depth or 0)
    except Exception as e:
        logger.warning(f"⚠️ Could not queue unread message for {user_id}: {e}")
        return 0


def mark_conversation_seen(user_id: str) -> bool:
    """Drop any pending digest — the buyer is looking at the conversation.

    Returns True when something was actually pending, which is only used for
    logging: the call is idempotent and safe on every read of the chat.
    """
    try:
        had_pending = bool(redis_client.llen(_key(user_id)))
        if had_pending:
            redis_client.delete(_key(user_id))
            logger.info(f"👀 {user_id} read the chat; pending digest dropped")
        return had_pending
    except Exception as e:
        logger.debug(f"Could not clear unread digest for {user_id}: {e}")
        return False


def _decode(raw) -> dict | None:
    """Parse one queued entry, or None if it isn't one.

    A malformed entry is dropped rather than raised on: one bad write must not
    strand every other message in the same queue behind it.
    """
    try:
        entry = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return entry if isinstance(entry, dict) else None


def due_digest_user_ids(now: float | None = None) -> list[str]:
    """Buyers whose oldest pending message has waited out the delay.

    Deliberately keyed on the OLDEST entry: a seller who keeps typing must not
    push the digest further and further away, or a talkative thread would never
    send at all.
    """
    now = time.time() if now is None else now
    cutoff = now - UNREAD_DIGEST_DELAY_SECONDS
    due = []
    try:
        for key in redis_client.scan_iter(match=f"{DIGEST_KEY_PREFIX}*", count=100):
            head = redis_client.lrange(key, 0, 0)
            if not head:
                continue
            entry = _decode(head[0])
            if entry is None:
                # Undatable head: treat as due so the queue drains rather than
                # wedging behind one bad row.
                due.append(key[len(DIGEST_KEY_PREFIX):])
                continue
            if float(entry.get("queued_at") or 0) <= cutoff:
                due.append(key[len(DIGEST_KEY_PREFIX):])
    except Exception as e:
        logger.warning(f"⚠️ Could not scan unread digests: {e}")
    return due


def drain_digest(user_id: str) -> list[dict]:
    """Atomically take everything pending for this buyer, oldest first.

    Read-and-delete in one MULTI/EXEC: this is what makes the sweep safe to run
    on every worker at once. The loser of the race gets an empty list, not a
    duplicate email.
    """
    try:
        pipe = redis_client.pipeline()
        pipe.lrange(_key(user_id), 0, -1)
        pipe.delete(_key(user_id))
        raw_entries = pipe.execute()[0] or []
    except Exception as e:
        logger.warning(f"⚠️ Could not drain unread digest for {user_id}: {e}")
        return []

    entries = [e for e in (_decode(r) for r in raw_entries) if e is not None]
    return entries[-MAX_DIGEST_MESSAGES:]


def _resolve_buyer_email(user_id: str) -> str | None:
    from connector import admin_supabase

    user_res = admin_supabase.auth.admin.get_user_by_id(user_id)
    if user_res and hasattr(user_res, "user") and user_res.user:
        return user_res.user.email
    if isinstance(user_res, dict):
        return user_res.get("email") or (user_res.get("user") or {}).get("email")
    return None


def flush_due_digests() -> int:
    """Send one digest per buyer whose queue has come due. Returns emails sent."""
    sent = 0
    for user_id in due_digest_user_ids():
        try:
            messages = drain_digest(user_id)
            if not messages:
                continue

            buyer_email = _resolve_buyer_email(user_id)
            if not buyer_email:
                # Already drained, deliberately: an address we cannot resolve
                # will not resolve on the next sweep either, and re-queuing it
                # would retry forever every 60 seconds.
                logger.warning(f"⚠️ No email for {user_id}; dropped {len(messages)} queued message(s)")
                continue

            from services.email_service import send_unread_digest_email

            # Every message in one digest belongs to the same conversation, so
            # the first named item is the subject's item.
            item_name = next((m.get("item_name") for m in messages if m.get("item_name")), None)
            if send_unread_digest_email(buyer_email, messages, item_name=item_name):
                sent += 1
        except Exception as e:
            # One buyer's failure must not abandon the rest of this sweep.
            logger.warning(f"⚠️ Failed to flush unread digest for {user_id}: {e}")
    return sent
