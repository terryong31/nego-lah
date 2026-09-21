"""
Billing domain service (ADR-0002, SPEC-002).

Billing's contract with the rest of the monolith: what other domains may ask
about money and orders. Billing's OWN routes and webhooks call
`domains.billing.*` directly — that crosses no boundary.
"""

from __future__ import annotations

from typing import Any

from core.connector import admin_supabase


class BillingService:
    """Exported domain service for the Billing bounded context."""

    # --- pricing -----------------------------------------------------------

    @staticmethod
    def get_active_negotiated_price(user_id: str, item_id: str) -> float | None:
        """Resolve the buyer's active accepted offer for an item, or None."""
        from domains.billing.pricing import active_negotiated_price

        return active_negotiated_price(user_id, item_id)

    # --- payment sessions --------------------------------------------------

    @staticmethod
    def get_pending_payment(user_id: str, item_id: str) -> dict | None:
        """The buyer's open checkout session for an item, if any."""
        from domains.billing.payment_state import get_pending_payment

        return get_pending_payment(user_id, item_id)

    @staticmethod
    def store_pending_payment(
        user_id: str,
        item_id: str,
        agreed_price: float,
        payment_link_id: str,
        product_id: str,
        price_id: str,
        payment_url: str,
    ) -> bool:
        """Record a checkout session the agent just opened, with its TTL."""
        from domains.billing.payment_state import store_pending_payment

        return store_pending_payment(
            user_id=user_id,
            item_id=item_id,
            agreed_price=agreed_price,
            payment_link_id=payment_link_id,
            product_id=product_id,
            price_id=price_id,
            payment_url=payment_url,
        )

    @staticmethod
    def delete_pending_payment(user_id: str, item_id: str, cleanup_stripe: bool = True) -> bool:
        """Drop a checkout session and optionally deactivate the Stripe link."""
        from domains.billing.payment_state import delete_pending_payment

        return delete_pending_payment(user_id, item_id, cleanup_stripe=cleanup_stripe)

    @staticmethod
    def get_active_payments_for_user(user_id: str) -> list[dict]:
        """Every open checkout session for a buyer (used to allowlist payment URLs)."""
        from domains.billing.payment_state import get_active_payments_for_user

        return get_active_payments_for_user(user_id)

    # --- orders ------------------------------------------------------------

    @staticmethod
    def list_orders_for_buyer(user_id: str, supabase_client: Any = None) -> list[dict]:
        """A buyer's orders, newest first. Scoped to the buyer — never unscoped."""
        if not user_id:
            return []
        client = supabase_client or admin_supabase
        res = client.table("orders").select("*").eq("buyer_id", user_id).order("created_at", desc=True).execute()
        return res.data or []

    @staticmethod
    def get_order_shipping_for_buyer(order_id: str, user_id: str, supabase_client: Any = None) -> dict | None:
        """
        The shipping fields already recorded on a buyer's order.

        Both `order_id` AND `user_id` are required filters (SPEC-056 #2): an
        unidentified caller must not be able to read anybody's order.
        """
        if not order_id or not user_id:
            return None
        client = supabase_client or admin_supabase
        res = (
            client.table("orders")
            .select("recipient_name, phone, address")
            .eq("id", order_id)
            .eq("buyer_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    @staticmethod
    def update_order_shipping_for_buyer(
        order_id: str, user_id: str, update_data: dict, supabase_client: Any = None
    ) -> bool:
        """Write shipping fields on a buyer's own order. Fails closed without a user_id."""
        if not order_id or not user_id:
            return False
        client = supabase_client or admin_supabase
        res = client.table("orders").update(update_data).eq("id", order_id).eq("buyer_id", user_id).execute()
        return bool(res.data)

    # --- aggregates (admin dashboard) --------------------------------------

    @staticmethod
    def order_summary(supabase_client: Any = None) -> tuple[dict[str, int], list[dict]]:
        """({status: count}, raw rows) over all orders, for the admin summary."""
        client = supabase_client or admin_supabase
        try:
            rows = client.table("orders").select("status, amount").execute().data or []
        except Exception:
            return {}, []
        counts: dict[str, int] = {}
        for row in rows:
            key = row.get("status") or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts, rows


__all__ = ["BillingService"]
