"""Admin order lifecycle: listing, status transitions, edits, deletion, and the
Stripe cleanup job that expires abandoned payment links."""

from fastapi import APIRouter, Depends, HTTPException

from admin_session import verify_admin, write_audit
from logger import logger
from schemas import OrderStatusUpdate, OrderUpdate

router = APIRouter()


@router.post("/cleanup-stripe")
def cleanup_expired_stripe_links():
    """
    Cleanup expired Stripe payment links.
    Call this periodically (e.g., via cron job) to clean up abandoned payments.
    """
    try:
        from payment.payment_state import cleanup_expired_payments
        cleaned = cleanup_expired_payments()
        return {"message": f"Cleaned up {cleaned} expired payment links"}
    except Exception as e:
        logger.error(f"Stripe cleanup job failed: {e}")
        return {"error": str(e)}


# =====================
# Orders Management
# =====================

@router.get("/orders")
def get_all_orders():
    """Get all orders for admin view with summary stats."""
    from connector import admin_supabase

    result = admin_supabase.table('orders').select('*').order('created_at', desc=True).execute()
    orders_data = result.data or []

    # Enrich with buyer info
    try:
        users_response = admin_supabase.auth.admin.list_users()
        users_map = {u.id: u.email for u in users_response}

        # Build map of names from auth metadata first
        names_map = {}
        for u in users_response:
            meta = u.user_metadata or {}
            # Try to get name from various metadata fields
            name = meta.get('full_name') or meta.get('name') or meta.get('display_name')
            if name:
                names_map[u.id] = name

        # Get profiles for display names (override if exists and not null)
        profiles = admin_supabase.table('user_profiles').select('id, display_name').execute()
        for p in (profiles.data or []):
            if p.get('display_name'):
                names_map[p['id']] = p['display_name']

        for order in orders_data:
            buyer_id = order.get('buyer_id')
            if buyer_id:
                order['buyer_email'] = users_map.get(buyer_id, 'Unknown Email')
                # Use name from map, or fallback to email part, or 'Unknown User'
                email_name = users_map.get(buyer_id, '').split('@')[0] if users_map.get(buyer_id) else 'Unknown User'
                order['buyer_name'] = names_map.get(buyer_id, email_name)
    except Exception as e:
        logger.error(f"Error enriching orders with user data: {e}")

    # Calculate stats
    total_orders = len(orders_data)
    total_sales = sum((order.get('amount') or 0) for order in orders_data)

    return {
        "orders": orders_data,
        "stats": {
            "total_orders": total_orders,
            "total_sales": total_sales
        }
    }


@router.get("/orders/{order_id}")
def get_order(order_id: str):
    """Get a specific order by ID."""
    from connector import admin_supabase

    result = admin_supabase.table('orders').select('*').eq('id', order_id).execute()
    if result.data:
        return result.data[0]
    raise HTTPException(status_code=404, detail="Order not found")


@router.put("/orders/{order_id}/status")
def update_order_status(order_id: str, request: OrderStatusUpdate, admin: dict = Depends(verify_admin)):
    """Update order status."""
    from connector import admin_supabase

    valid_statuses = ['pending_info', 'confirmed', 'shipped', 'delivered', 'cancelled', 'refunded']
    if request.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    result = admin_supabase.table('orders').update({
        'status': request.status
    }).eq('id', order_id).execute()

    if result.data:
        write_audit(admin.get("user_id"), admin.get("email"), f"order.status:{request.status}", order_id, admin.get("ip"))
        return {"message": f"Order status updated to {request.status}"}
    raise HTTPException(status_code=404, detail="Order not found")


@router.put("/orders/{order_id}")
def update_order(order_id: str, request: OrderUpdate, admin: dict = Depends(verify_admin)):
    """Update order details."""
    from connector import admin_supabase

    # Build update dict with only provided fields
    update_data = {}
    if request.item_name is not None:
        update_data['item_name'] = request.item_name
    if request.amount is not None:
        update_data['amount'] = request.amount
    if request.status is not None:
        valid_statuses = ['pending_info', 'confirmed', 'shipped', 'delivered', 'cancelled', 'refunded']
        if request.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
        update_data['status'] = request.status

    # Handle address - support both frontend 'address' and backend 'shipping_address'
    addr = request.address or request.shipping_address
    if addr is not None:
        update_data['address'] = addr

    # Handle phone - support both frontend 'phone' and backend 'shipping_phone'
    ph = request.phone or request.shipping_phone
    if ph is not None:
        update_data['phone'] = ph

    # Handle recipient name - support both frontend 'recipient_name' and backend 'shipping_name'
    name = request.recipient_name or request.shipping_name
    if name is not None:
        update_data['recipient_name'] = name

    if request.notes is not None:
        update_data['notes'] = request.notes

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = admin_supabase.table('orders').update(update_data).eq('id', order_id).execute()

    if result.data:
        write_audit(admin.get("user_id"), admin.get("email"), "order.update", order_id, admin.get("ip"))
        return {"message": "Order updated successfully", "order": result.data[0]}
    raise HTTPException(status_code=404, detail="Order not found")


@router.delete("/orders/{order_id}")
def delete_order(order_id: str, admin: dict = Depends(verify_admin)):
    """Delete an order."""
    from connector import admin_supabase

    # Check if order exists first
    check = admin_supabase.table('orders').select('id').eq('id', order_id).execute()
    if not check.data:
        raise HTTPException(status_code=404, detail="Order not found")

    admin_supabase.table('orders').delete().eq('id', order_id).execute()
    write_audit(admin.get("user_id"), admin.get("email"), "order.delete", order_id, admin.get("ip"))
    return {"message": "Order deleted successfully"}
