"""
In-process bus for cross-domain work that must not become a cross-domain import
(SPEC-097, ADR-0030).

The domains are layered `identity < catalog < billing < negotiation`. A domain
may call strictly below itself; anything pointing the other way is a cycle, and
before this module existed there were 24 of them. Two shapes of upward call are
legitimate, and each gets one primitive here:

**Events — `emit` / `on`.** Something happened and a higher domain may care.
Billing settles a payment; whether that produces a chat message is not billing's
concern. Fan-out, no return value, and **a failing subscriber never reaches the
emitter** — `purchase.fulfilled` is emitted from inside the Stripe webhook after
the money has moved, so a chat outage must not fail that webhook and have Stripe
redeliver a payment already fulfilled.

**Queries — `ask` / `provides`.** A lower domain needs one fact a higher one
owns. Catalog shows a buyer their negotiated price without knowing billing
exists. Exactly one provider, and its errors **do** propagate: the caller is
waiting on the answer, and a swallowed failure hands back a wrong number rather
than no number. With no provider registered, `ask` returns the caller's default,
so an unwired domain degrades instead of 500ing.

Registration is explicit, in `main.py`'s lifespan. Domain `__init__` is lazy by
design, so a subscriber module nobody imports is a subscriber nobody registered —
`tests/test_core_bus.py::TestWiring` is what stops that being discovered in
production.

This is deliberately not a task queue. The backend runs on a 2 GB Lightsail box
(AGENTS.md §3): handlers run synchronously, in the caller's thread, and anything
slow belongs in a lifespan loop instead.
"""

from collections import defaultdict
from collections.abc import Callable
from typing import Any

from core.logger import logger

_subscribers: dict[str, list[Callable[..., Any]]] = defaultdict(list)
_providers: dict[str, Callable[..., Any]] = {}


# --- events ----------------------------------------------------------------


def subscribe(event: str, handler: Callable[..., Any]) -> None:
    """Register `handler` for `event`. Registering the same one twice is a no-op."""
    if handler not in _subscribers[event]:
        _subscribers[event].append(handler)


def on(event: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator form of `subscribe`, returning the handler unchanged."""

    def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
        subscribe(event, handler)
        return handler

    return decorator


def emit(event: str, **payload: Any) -> int:
    """
    Announce `event` to every subscriber. Returns how many ran.

    Each handler is isolated: one raising is logged and the next still runs. The
    emitter is told nothing, because by the time an event is emitted the thing it
    describes has already happened and cannot be undone by a listener's opinion.
    """
    handlers = list(_subscribers.get(event, ()))
    for handler in handlers:
        try:
            handler(**payload)
        except Exception as e:
            logger.warning(f"bus: subscriber {getattr(handler, '__name__', handler)!r} failed on '{event}': {e}")
    return len(handlers)


def subscribers(event: str) -> list[Callable[..., Any]]:
    """The handlers registered for `event` (wiring assertions, not dispatch)."""
    return list(_subscribers.get(event, ()))


# --- queries ---------------------------------------------------------------


def register_provider(query: str, handler: Callable[..., Any]) -> None:
    """Register the single provider for `query`."""
    existing = _providers.get(query)
    if existing is not None and existing is not handler:
        raise ValueError(
            f"'{query}' already has a provider ({getattr(existing, '__name__', existing)!r}). "
            "A query resolves to exactly one answer; two providers would make which one silent."
        )
    _providers[query] = handler


def provides(query: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator form of `register_provider`, returning the handler unchanged."""

    def decorator(handler: Callable[..., Any]) -> Callable[..., Any]:
        register_provider(query, handler)
        return handler

    return decorator


def ask(query: str, default: Any = None, **payload: Any) -> Any:
    """
    Ask the registered provider for `query`, or return `default` if there is none.

    Provider exceptions propagate — see the module docstring.
    """
    provider = _providers.get(query)
    if provider is None:
        return default
    return provider(**payload)


def provider(query: str) -> Callable[..., Any] | None:
    """The provider registered for `query`, if any (wiring assertions)."""
    return _providers.get(query)


# --- test support ----------------------------------------------------------


def snapshot() -> tuple[dict[str, list[Callable[..., Any]]], dict[str, Callable[..., Any]]]:
    """Copy the current wiring so a test can restore it afterwards."""
    return ({k: list(v) for k, v in _subscribers.items()}, dict(_providers))


def restore(state: tuple[dict[str, list[Callable[..., Any]]], dict[str, Callable[..., Any]]]) -> None:
    """Put back a `snapshot`."""
    subs, provs = state
    reset()
    for event, handlers in subs.items():
        _subscribers[event] = list(handlers)
    _providers.update(provs)


def reset() -> None:
    """Drop all wiring. Tests only — the app registers once, at startup."""
    _subscribers.clear()
    _providers.clear()
