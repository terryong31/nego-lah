"""Admin order lifecycle: listing, status transitions, postage, edits, deletion,
and the Stripe cleanup job that expires abandoned payment links."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from admin_session import verify_admin, write_audit
from logger import logger
from schemas import OrderStatusUpdate, OrderUpdate, ShipmentUpdate

router = APIRouter()

VALID_ORDER_STATUSES = [
    'pending_info', 'confirmed', 'shipped', 'delivered', 'cancelled', 'refunded'
]


def _notify_buyer_of_shipment(order: dict, delivered: bool = False) -> dict:
    """Tell the buyer their parcel moved — by email, and in the chat (SPEC-057).

    Called AFTER the order row is written, and every step is individually
    best-effort. The ordering is the point: an order that shipped but whose
    email bounced is a recoverable annoyance, whereas an email announcing a
    shipment that was never recorded is a lie the seller cannot retract.
    """
    from payment.buyer import account_email
    from services.shipping_notice import shipment_chat_message

    result = {"email": False, "chat": False}
    buyer_id = order.get("buyer_id")

    try:
        from services.email_service import send_shipment_notice
        result["email"] = bool(send_shipment_notice(account_email(buyer_id), order, delivered=delivered))
    except Exception as e:
        logger.error(f"Shipment email failed for order {order.get('id')}: {e}")

    try:
        from payment.fulfillment import broadcast_to_chat

        # source="ai" so it lands in the buyer's chat as the seller's own voice
        # AND rings the notification bell — broadcast_to_chat deliberately skips
        # the SSE hop for "human"/"system" messages.
        broadcast_to_chat(
            buyer_id,
            shipment_chat_message(order, delivered=delivered),
            role="assistant",
            source="ai",
        )
        result["chat"] = True
    except Exception as e:
        logger.error(f"Shipment chat broadcast failed for order {order.get('id')}: {e}")

    return result


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
    """Update order status. Reaching 'delivered' also tells the buyer (SPEC-057)."""
    from connector import admin_supabase

    if request.status not in VALID_ORDER_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {VALID_ORDER_STATUSES}")

    existing = admin_supabase.table('orders').select('*').eq('id', order_id).execute()
    current = existing.data[0] if existing.data else None

    update_data = {'status': request.status}

    # Only a *transition* into delivered is an event worth an email. Re-saving a
    # row that is already delivered — which the console does whenever the seller
    # re-picks the same value — must not send a second one.
    newly_delivered = request.status == 'delivered' and (current or {}).get('status') != 'delivered'
    if newly_delivered:
        update_data['delivered_at'] = datetime.now(UTC).isoformat()

    result = admin_supabase.table('orders').update(update_data).eq('id', order_id).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found")

    write_audit(admin.get("user_id"), admin.get("email"), f"order.status:{request.status}", order_id, admin.get("ip"))

    if newly_delivered:
        _notify_buyer_of_shipment({**(current or {}), **result.data[0]}, delivered=True)

    return {"message": f"Order status updated to {request.status}"}


@router.put("/orders/{order_id}/shipment")
def record_shipment(order_id: str, request: ShipmentUpdate, admin: dict = Depends(verify_admin)):
    """Record postage for a paid order and tell the buyer about it.

    SPEC-057. Before this the lifecycle simply stopped: `status` could be set to
    'shipped' but there was nowhere to put what it shipped WITH, so the seller
    pasted tracking numbers into the chat by hand and the agent could only
    repeat the word "shipped" when asked.

    One call does all four things — record, stamp, email, post to the chat —
    because a seller who has to remember the other three will eventually not.
    """
    from connector import admin_supabase
    from domains.catalog.shipping import normalise_courier, resolve_tracking_url

    courier = normalise_courier(request.courier)
    tracking_number = (request.tracking_number or "").strip()
    if not courier or not tracking_number:
        raise HTTPException(status_code=400, detail="Courier and tracking number are both required")

    existing = admin_supabase.table('orders').select('*').eq('id', order_id).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Order not found")

    update_data = {
        'courier': courier,
        'tracking_number': tracking_number,
        # An explicit URL wins: the seller may be using a carrier the registry
        # doesn't know, or a consignment link that isn't the generic search page.
        'tracking_url': (request.tracking_url or "").strip() or resolve_tracking_url(courier, tracking_number),
        'shipped_at': datetime.now(UTC).isoformat(),
        'status': 'shipped',
    }

    result = admin_supabase.table('orders').update(update_data).eq('id', order_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found")

    order = {**existing.data[0], **update_data, **(result.data[0] or {})}
    write_audit(admin.get("user_id"), admin.get("email"), "order.shipment", order_id, admin.get("ip"))

    notified = (
        _notify_buyer_of_shipment(order)
        if request.notify
        else {"email": False, "chat": False}
    )

    return {"message": "Shipment recorded", "order": order, "notified": notified}


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
        if request.status not in VALID_ORDER_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {VALID_ORDER_STATUSES}")
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


@router.post("/orders/refund/{item_id}")
def refund_item(item_id: str, reason: str = None, admin: dict = Depends(verify_admin)):
    """Refund a paid item, releasing it back to the catalogue.

    SPEC-056 #1. This used to be `POST /payment/refund/{item_id}` on the public
    payment router with `Depends(verify_admin)` and nothing more. Admin auth is
    a cookie the browser attaches by itself, which is exactly the shape CSRF
    exploits — every other mutating admin action is gated by `verify_csrf_token`
    via the `protected` router in `routes/admin/__init__.py`, and the one that
    moves money was the exception. Living here, it inherits that gate.
    """
    from payment.refunds import process_refund

    result = process_refund(item_id, reason)

    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    write_audit(admin.get("user_id"), admin.get("email"), "order.refund", item_id, admin.get("ip"))
    return result


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
