"""Pushing a message into a user's live chat.

Realtime fan-out, not a billing or negotiation concern: fulfillment announces a
sale here, the admin console speaks here, and both want the same delivery. It
sits in `core/` so neither domain has to import the other to say something.

SPEC-094 removed the second transport. This used to POST every message to the
Supabase Realtime topic `chat:{user_id}` as well, on a channel created with no
`private: true` and with no policy on `realtime.messages` — so the anon key that
ships in the JavaScript bundle was enough to subscribe to any user id and read
their negotiation as it happened. The notification broker was already carrying
the same events, per user, behind an authenticated stream. Now it is the only
one that does.
"""

from typing import Any

from core.logger import logger

# Messages the buyer sent themselves (`human`, echoed only so the admin console
# stays in sync) and the system separators are not "someone messaged you". They
# still go to every open stream — that is how the conversation stays live on
# both sides — but they do not raise a toast or a badge.
_SILENT_SOURCES = ("human", "system")


def _publish(user_id: str, payload: dict[str, Any]) -> None:
    """Hand an event to every live stream for this user, on any worker."""
    try:
        from core.notifications import notification_broker

        notification_broker.publish(user_id, payload)
    except Exception as e:
        # A dropped realtime event is a cosmetic failure: the message itself is
        # already persisted, and the next page load renders it.
        logger.warning(f"❌ Broadcast error: {e}")


def broadcast_to_chat(user_id: str, content: str, role: str = "ai", source: str = "ai"):
    """Push a chat message to the buyer's open tab and the admin console."""
    _publish(
        user_id,
        {
            "type": "new_message",
            "message": content,
            "role": role,
            "source": source,
            "notify": source not in _SILENT_SOURCES,
        },
    )
    logger.info(f"📡 Broadcasted message to user {user_id}")


def broadcast_typing(user_id: str, role: str):
    """Push a typing indicator. Fire-and-forget by design.

    Nothing is persisted and nothing is queued for later: a typing ping that
    arrives after the other side stopped waiting for it is worse than one that
    was dropped. `role` is who is typing — the receiving side ignores its own.
    """
    _publish(user_id, {"type": "typing", "role": role})


# Postgres SQLSTATE for unique_violation. This is the idempotency anchor for the
# whole payment webhook: orders.stripe_payment_id is UNIQUE, so a duplicate
# insert means "already processed", not "broken".
UNIQUE_VIOLATION_SQLSTATE = "23505"
