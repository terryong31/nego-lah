"""
Request-scoped context for agent tools.

Tools (evaluate_offer, create_checkout_link, etc.) need to know which user and
item the current conversation is about. Previously this was injected by mutating
attributes on the tool functions themselves (e.g. ``evaluate_offer._current_item_id``),
which is GLOBAL state shared across every concurrent request - one user's context
could leak into another user's tool call.

ContextVars are isolated per-thread / per-async-task, so each in-flight request
sees only its own values. ``bot.chat()`` sets these at the start of each call.

Values travel *into* a tool that way. They cannot travel back out the same way:
LangChain wraps every tool body in ``copy_context()`` (``set_config_context``,
sync and async paths alike), so a ``ContextVar.set()`` inside a tool writes to a
copy the request never reads. What survives is mutation of an object the copy
already holds — which is what ``_TurnSignal`` below is.
"""

import contextvars

current_user_id: contextvars.ContextVar = contextvars.ContextVar(
    "current_user_id", default=None
)
current_item_id: contextvars.ContextVar = contextvars.ContextVar(
    "current_item_id", default=None
)
current_user_language: contextvars.ContextVar = contextvars.ContextVar(
    "current_user_language", default="en"
)

# One box per turn, seeded by set_context() before any tool runs. The tools'
# copied contexts all hold a reference to this same dict, so what they write
# into it is visible to the request that started the turn.
_turn_signals: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "turn_signals", default=None
)


class _TurnSignal:
    """One value a tool leaves behind for the request driving the turn.

    Shaped like the ContextVar it replaces (``get``/``set``) because that is
    all the call sites ever wanted; the value itself lives in the shared
    per-turn box rather than in a variable, which is the only way back out of
    a tool. Isolation is unchanged — the box belongs to the turn's own context,
    so two concurrent negotiations still never see each other's signals.
    """

    def __init__(self, name: str) -> None:
        self._name = name

    def get(self):
        signals = _turn_signals.get()
        return signals.get(self._name) if signals else None

    def set(self, value) -> None:
        signals = _turn_signals.get()
        if signals is None:
            # No turn has been started in this context (a tool exercised on its
            # own). Nothing is waiting on the signal, but keep the write local
            # rather than dropping it silently.
            signals = {}
            _turn_signals.set(signals)
        signals[self._name] = value


# Set by evaluate_offer when it commits a negotiated price to Redis. The SSE
# stream loop in routes/chat.py drains it once per turn and emits a
# `data-discount` frame (SPEC-041).
pending_discount = _TurnSignal("discount")

# SPEC-070: set by transfer_to_human, drained by the turn runner in
# routes/chat.py once the agent's own farewell has been delivered. Writing the
# separator from inside the tool put it in the transcript ABOVE the message it
# explains, and put it on the buyer's chat channel mid-stream — where a push
# into `useChat`'s message list makes the SDK render the whole reply twice.
pending_handoff = _TurnSignal("handoff")


def new_turn():
    """Open a fresh signal box for the turn about to run.

    Called by the request before the agent is, because a box is only isolating
    if this context owns it: an inherited one is the *same dict* two concurrent
    turns would both write into. `set_context` opens one too, so the agent path
    is covered either way — this is the boundary that does not depend on which
    stream implementation runs behind it.
    """
    _turn_signals.set({})


def set_context(user_id=None, item_id=None, language=None):
    """Set the request-scoped user/item/language context for the current execution."""
    current_user_id.set(user_id)
    current_item_id.set(item_id)
    current_user_language.set(language or "en")
    # A fresh box: nothing a previous turn left behind can fire on this one.
    new_turn()


def get_user_id():
    return current_user_id.get()


def get_item_id():
    return current_item_id.get()


def get_user_language():
    return current_user_language.get() or "en"
