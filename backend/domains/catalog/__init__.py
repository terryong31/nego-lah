"""Catalog domain: items, search, inventory, and shipping couriers."""

from domains._lazy import lazy_getattr

_EXPORTS = {
    "CatalogService": ("domains.catalog.services", "CatalogService"),
    "PUBLIC_ITEM_COLUMNS": ("domains.catalog.items", "PUBLIC_ITEM_COLUMNS"),
    "PUBLIC_ITEM_SELECT": ("domains.catalog.items", "PUBLIC_ITEM_SELECT"),
    "CONFIDENTIAL_ITEM_COLUMNS": ("domains.catalog.items", "CONFIDENTIAL_ITEM_COLUMNS"),
    # Courier naming and tracking URLs (SPEC-057). Billing's order console
    # records a shipment, so these are part of catalog's public contract.
    "normalise_courier": ("domains.catalog.shipping", "normalise_courier"),
    "resolve_tracking_url": ("domains.catalog.shipping", "resolve_tracking_url"),
    "catalog_router": ("domains.catalog.routes", "router"),
    "admin_items_router": ("domains.catalog.admin_routes", "router"),
}

__getattr__ = lazy_getattr(__name__, _EXPORTS)
__all__ = list(_EXPORTS)
