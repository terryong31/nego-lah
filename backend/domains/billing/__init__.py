"""Billing domain: Stripe checkout, payment links, payment state, fulfillment, refunds."""

from domains._lazy import lazy_getattr

_EXPORTS = {
    # Bus wiring, called from main.py's lifespan (SPEC-097).
    "register_providers": ("domains.billing.providers", "register_providers"),
    "BillingService": ("domains.billing.services", "BillingService"),
    # `main.py`'s lifespan loop sweeps abandoned checkouts, so the sweep is
    # part of billing's public surface rather than something to reach in for.
    "cleanup_expired_payments": ("domains.billing.payment_state", "cleanup_expired_payments"),
    # An order shipping is a billing event; negotiation and the console both
    # render the same facts, so the summary is part of the contract (SPEC-097).
    "shipment_summary": ("domains.billing.shipping_notice", "shipment_summary"),
    "shipment_chat_message": ("domains.billing.shipping_notice", "shipment_chat_message"),
    "billing_router": ("domains.billing.routes", "router"),
    "admin_orders_router": ("domains.billing.admin_routes", "router"),
}

__getattr__ = lazy_getattr(__name__, _EXPORTS)
__all__ = list(_EXPORTS)
