"""
Facts billing answers for domains below it (SPEC-097).

Catalog shows a buyer the price they negotiated, which lives in billing. Catalog
sits below billing and may not name it, so it asks `core.bus` for the number and
billing is whoever happens to answer.
"""

from core import bus


def _active_negotiated_price(user_id: str, item_id: str, **_: object) -> float | None:
    from domains.billing.services import BillingService

    return BillingService.get_active_negotiated_price(user_id, item_id)


def register_providers() -> None:
    """Wire this domain onto the bus.

    Idempotent for the same reason as negotiation's: `_active_negotiated_price`
    is a module-level singleton, so re-running re-registers the same object.
    """
    bus.register_provider("billing.active_negotiated_price", _active_negotiated_price)
