"""
What negotiation does when something happens elsewhere (SPEC-097).

Billing settles a payment. Identity deletes an account. Neither knows this
domain exists, and neither should: they sit below it in the layering, and an
import pointing up here is a cycle. They announce; this module listens.

Registration is explicit — `register_subscribers()` is called from `main.py`'s
lifespan — because `domains/negotiation/__init__.py` resolves lazily, so a
subscriber module nobody imports is a subscriber nobody registered. That failure
is silent at runtime and loud in `tests/test_core_bus.py::TestWiring`.
"""

from core import bus
from core.logger import logger


def _on_purchase_fulfilled(user_id: str, message: str, **_: object) -> None:
    """A settled payment becomes the seller's thank-you in the buyer's chat."""
    from domains.negotiation.services import NegotiationService

    NegotiationService.add_agent_message(user_id, message)


def _on_shipment_recorded(user_id: str, message: str, item_id: str | None = None, **_: object) -> None:
    """A recorded shipment becomes a chat line in the seller's own voice.

    Persisted here BEFORE the caller broadcasts (SPEC-078): the live push
    reaches nobody unless the buyer's tab is open at that instant, so without
    the row the notice is not delayed, it is gone.
    """
    from domains.negotiation.services import NegotiationService

    NegotiationService.add_agent_message(user_id, message, item_id=item_id, source="ai")


def _on_user_deleted(user_id: str, **_: object) -> None:
    """Erase this domain's rows for a deleted account."""
    from domains.negotiation.services import NegotiationService

    NegotiationService.purge_user_data(user_id)


def _ai_settings_map(**_: object) -> dict:
    """Which buyers have the agent switched off — the console's user table."""
    from domains.negotiation.services import NegotiationService

    try:
        return NegotiationService.get_ai_settings_map()
    except Exception as e:
        logger.debug(f"ai_settings_map unavailable: {e}")
        return {}


def register_subscribers() -> None:
    """Wire this domain onto the bus.

    Idempotent because every handler is a module-level singleton: re-running
    registers the same objects, which the bus ignores. A closure defined in here
    would be a new object on every call — and on a module reload, a duplicate.
    """
    bus.subscribe("purchase.fulfilled", _on_purchase_fulfilled)
    bus.subscribe("shipment.recorded", _on_shipment_recorded)
    bus.subscribe("user.deleted", _on_user_deleted)
    bus.register_provider("negotiation.ai_settings_map", _ai_settings_map)
    logger.debug("negotiation: bus subscribers registered")
