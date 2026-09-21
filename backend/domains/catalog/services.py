"""
Catalog domain service (ADR-0002, SPEC-002).

The catalog's contract with the rest of the monolith. Every read or write of the
`items` table by another domain goes through here — `tests/test_domain_boundaries.py`
fails the build if one doesn't.
"""

from __future__ import annotations

from typing import Any

from core.connector import admin_supabase, user_supabase
from core.logger import logger
from domains.catalog.items import (
    CONFIDENTIAL_ITEM_COLUMNS,
    PUBLIC_ITEM_COLUMNS,
    PUBLIC_ITEM_SELECT,
)


class CatalogService:
    """Exported domain service for the Catalog bounded context."""

    # --- public reads ------------------------------------------------------

    @staticmethod
    def get_public_item_by_id(item_id: str, supabase_client: Any = None) -> dict | None:
        """Fetch one item using the public column allowlist (SPEC-036). Soft-deleted excluded."""
        client = supabase_client or user_supabase
        try:
            res = client.table("items").select(PUBLIC_ITEM_SELECT).eq("id", item_id).is_("deleted_at", "null").execute()
            return res.data[0] if res and res.data else None
        except Exception:
            return None

    @staticmethod
    def get_item_card(item_id: str, supabase_client: Any = None) -> dict | None:
        """The fields the agent needs to talk about an item (SPEC-020 knowledge card)."""
        client = supabase_client or user_supabase
        try:
            res = (
                client.table("items")
                .select("name, description, price, condition, image_path")
                .eq("id", item_id)
                .execute()
            )
            return res.data[0] if res and res.data else None
        except Exception:
            return None

    @staticmethod
    def get_item_name(item_id: str, supabase_client: Any = None) -> str | None:
        """Lightweight lookup for an item's display name."""
        client = supabase_client or admin_supabase
        try:
            res = client.table("items").select("name").eq("id", item_id).execute()
            if res and res.data and res.data[0].get("name"):
                return res.data[0]["name"]
        except Exception as e:
            logger.debug(f"Failed to lookup item name for {item_id}: {e}")
        return None

    @staticmethod
    def get_item_status(item_id: str, supabase_client: Any = None) -> str | None:
        """Current lifecycle status ('available' / 'sold'), or None if unknown."""
        client = supabase_client or admin_supabase
        try:
            res = client.table("items").select("status").eq("id", item_id).execute()
            return res.data[0].get("status") if res and res.data else None
        except Exception:
            return None

    @staticmethod
    def get_checkout_snapshot(item_id: str, supabase_client: Any = None) -> dict | None:
        """The name/description/images/condition a checkout session shows the buyer."""
        client = supabase_client or admin_supabase
        try:
            res = client.table("items").select("name, description, image_path, condition").eq("id", item_id).execute()
            return res.data[0] if res and res.data else None
        except Exception:
            return None

    # --- confidential reads (service-role only) ----------------------------

    @staticmethod
    def get_item_with_floor_price(item_id: str, supabase_client: Any = None) -> dict | None:
        """
        Fetch an item INCLUDING `min_price`, the negotiation floor (SPEC-036,
        ADR-0009). Service-role only, and the result must never be splatted into
        a client response or an agent prompt.
        """
        client = supabase_client or admin_supabase
        try:
            res = client.table("items").select("*").eq("id", item_id).execute()
            return res.data[0] if res and res.data else None
        except Exception:
            return None

    @staticmethod
    def get_live_item_with_floor_price(item_id: str, supabase_client: Any = None) -> dict | None:
        """As `get_item_with_floor_price`, but soft-deleted items are invisible."""
        client = supabase_client or admin_supabase
        try:
            res = client.table("items").select("*").eq("id", item_id).is_("deleted_at", "null").execute()
            return res.data[0] if res and res.data else None
        except Exception:
            return None

    # --- state changes -----------------------------------------------------

    @staticmethod
    def claim_item_as_sold(
        item_id: str,
        user_id: str,
        supabase_client: Any = None,
    ) -> tuple[bool, dict | None]:
        """
        Atomically transition an item from 'available' to 'sold' for buyer user_id
        (ADR-0001). Returns (True, item_row) if the claim was won, or
        (False, current_row) if it was lost — current_row is None if the item is gone.

        This method deliberately does NOT catch database errors, and callers must
        not add a blanket `except` around it. `False` means "another buyer holds
        this item", and `domains.billing.fulfillment` answers a lost claim by
        REFUNDING the payment. Swallowing a transient PostgREST failure here would
        auto-refund a good payment on an item that is still available; letting it
        propagate makes the Stripe webhook return 5xx so the payment is redelivered.

        Cache invalidation stays with the caller (`_finalize_won_sale` already
        wraps it in its own try/except): a Redis round-trip inside this method
        could fail *after* the claim had committed and veto a completed sale.
        """
        client = supabase_client or admin_supabase
        claim = (
            client.table("items")
            .update({"status": "sold", "buyer_id": user_id})
            .eq("id", item_id)
            .eq("status", "available")
            .execute()
        )
        if claim.data:
            return True, claim.data[0]

        cur = client.table("items").select("status, buyer_id").eq("id", item_id).execute()
        return False, (cur.data[0] if cur.data else None)

    @staticmethod
    def release_item_to_available(item_id: str, supabase_client: Any = None) -> bool:
        """Put a refunded item back on the shelf (billing's refund path)."""
        client = supabase_client or admin_supabase
        try:
            client.table("items").update({"status": "available", "buyer_id": None}).eq("id", item_id).execute()
            return True
        except Exception as e:
            logger.warning(f"Could not release item {item_id} back to available: {e}")
            return False

    # --- search ------------------------------------------------------------

    @staticmethod
    def search_items(search_term: str, limit: int = 5, supabase_client: Any = None) -> list[dict]:
        """Search live items by name."""
        client = supabase_client or user_supabase
        try:
            res = (
                client.table("items")
                .select("id, name, price, condition, status")
                .is_("deleted_at", "null")
                .ilike("name", f"%{search_term}%")
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception:
            return []

    @staticmethod
    def list_available_items(limit: int = 10, supabase_client: Any = None) -> list[dict]:
        """List available live items up to `limit`."""
        client = supabase_client or user_supabase
        try:
            res = (
                client.table("items")
                .select("id, name, price, condition, status")
                .eq("status", "available")
                .is_("deleted_at", "null")
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception:
            return []

    # --- aggregates (admin dashboard) --------------------------------------

    @staticmethod
    def count_by_status(supabase_client: Any = None) -> dict[str, int]:
        """{status: count} over live items, for the cross-domain admin summary."""
        client = supabase_client or admin_supabase
        try:
            rows = client.table("items").select("status").is_("deleted_at", "null").execute().data or []
        except Exception:
            return {}
        counts: dict[str, int] = {}
        for row in rows:
            key = row.get("status") or "unknown"
            counts[key] = counts.get(key, 0) + 1
        return counts


__all__ = [
    "CatalogService",
    "PUBLIC_ITEM_COLUMNS",
    "PUBLIC_ITEM_SELECT",
    "CONFIDENTIAL_ITEM_COLUMNS",
]
