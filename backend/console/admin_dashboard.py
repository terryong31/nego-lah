"""Admin dashboard summary — application composition, not a domain.

The overview counts items, orders, conversations and users in one payload, so it
is the one screen that legitimately spans every bounded context. Rather than
reach into four domains' tables, it asks each domain for its own numbers; the
aggregation is the only logic that lives here.

It sits beside `admin_api.py` for the same reason that module does: a file that
needs every domain is not itself a domain.
"""

from fastapi import APIRouter

from domains.billing import BillingService
from domains.catalog import CatalogService
from domains.identity import IdentityService
from domains.negotiation import NegotiationService

router = APIRouter()


@router.get("/summary")
def admin_summary():
    """Aggregate counts for the admin dashboard overview."""
    items_by_status = CatalogService.count_by_status()
    orders_by_status, orders = BillingService.order_summary()

    items_total = sum(items_by_status.values())
    items_sold = items_by_status.get("sold", 0)

    return {
        "users": IdentityService.count_users(),
        "conversations": NegotiationService.count_conversations(),
        "items_total": items_total,
        "items_available": items_total - items_sold,
        "items_sold": items_sold,
        "orders_total": len(orders),
        "orders_pending": orders_by_status.get("pending_info", 0),
        "orders_confirmed": orders_by_status.get("confirmed", 0),
        "orders_shipped": orders_by_status.get("shipped", 0),
        "orders_delivered": orders_by_status.get("delivered", 0),
        "sales_total": sum((o.get("amount") or 0) for o in orders),
    }
