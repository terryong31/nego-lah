"""
Request-scoped context for agent tools.

Tools (evaluate_offer, create_checkout_link, etc.) need to know which user and
item the current conversation is about. Previously this was injected by mutating
attributes on the tool functions themselves (e.g. ``evaluate_offer._current_item_id``),
which is GLOBAL state shared across every concurrent request - one user's context
could leak into another user's tool call.

ContextVars are isolated per-thread / per-async-task, so each in-flight request
sees only its own values. ``bot.chat()`` sets these at the start of each call.
"""

import contextvars

current_user_id: contextvars.ContextVar = contextvars.ContextVar(
    "current_user_id", default=None
)
current_item_id: contextvars.ContextVar = contextvars.ContextVar(
    "current_item_id", default=None
)

# Set by evaluate_offer when it commits a negotiated price to Redis.
# The SSE stream loop in routes/chat.py drains this once per turn and emits
# a `data-discount` frame. Using a ContextVar keeps it isolated per async
# request — two concurrent negotiations never bleed into each other.
pending_discount: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "pending_discount", default=None
)


def set_context(user_id=None, item_id=None):
    """Set the request-scoped user/item context for the current execution."""
    current_user_id.set(user_id)
    current_item_id.set(item_id)
    pending_discount.set(None)


def get_user_id():
    return current_user_id.get()


def get_item_id():
    return current_item_id.get()
