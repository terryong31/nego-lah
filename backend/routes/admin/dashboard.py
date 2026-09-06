"""Admin dashboard summary counters."""

from fastapi import APIRouter

from logger import logger

router = APIRouter()


@router.get("/summary")
def admin_summary():
    """Aggregate counts for the admin dashboard overview."""
    from connector import admin_supabase

    try:
        users = admin_supabase.auth.admin.list_users()
        user_count = len(users)
    except Exception as e:
        logger.error(f"summary: list_users failed: {e}")
        user_count = 0

    items = (admin_supabase.table('items').select('status').is_('deleted_at', 'null').execute().data) or []
    orders = (admin_supabase.table('orders').select('status, amount').execute().data) or []
    convos = (admin_supabase.table('conversations').select('id').execute().data) or []

    by_status: dict = {}
    for o in orders:
        s = o.get('status') or 'unknown'
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "users": user_count,
        "conversations": len(convos),
        "items_total": len(items),
        "items_available": sum(1 for i in items if i.get('status') != 'sold'),
        "items_sold": sum(1 for i in items if i.get('status') == 'sold'),
        "orders_total": len(orders),
        "orders_pending": by_status.get('pending_info', 0),
        "orders_confirmed": by_status.get('confirmed', 0),
        "orders_shipped": by_status.get('shipped', 0),
        "orders_delivered": by_status.get('delivered', 0),
        "sales_total": sum((o.get('amount') or 0) for o in orders),
    }
