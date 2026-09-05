import asyncio

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from admin_session import verify_admin
from auth_middleware import get_user_id_from_body_or_token, verify_user_token
from connector import admin_supabase
from logger import logger
from payment.pay import create_checkout_session
from schemas import CheckoutRequest

router = APIRouter(prefix="/payment", tags=["Payment"])


@router.post("/checkout")
def checkout(
    request: CheckoutRequest,
    token_user_id: str = Depends(verify_user_token),
):
    """Create a Stripe checkout session for an item."""
    try:
        # Require a valid (and non-banned) JWT. The buyer is always the
        # authenticated user — never trust the user_id from the body.
        user_id = get_user_id_from_body_or_token(request.user_id, token_user_id)

        item_id = request.item_id

        # Get item from database (soft-deleted items can't be purchased).
        response = admin_supabase.table('items').select('*').eq('id', item_id).is_('deleted_at', 'null').execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Item not found")

        item = response.data[0]

        # Don't open a checkout for an item that's already gone. Mirrors the
        # guard in the AI agent's create_checkout_link; the atomic claim at the
        # webhook is still the final authority if two buyers race past here.
        if item.get('status') != 'available':
            raise HTTPException(status_code=409, detail="Item is no longer available")

        # Convert price to cents. Round rather than truncate: float(19.99)*100 is
        # 1998.9999999... and int() would floor it to 1998, undercharging by a sen.
        price_cents = round(float(item['price']) * 100)

        # Create Stripe checkout session
        checkout_url = create_checkout_session(
            item_name=item['name'],
            price_cents=price_cents,
            item_id=item_id,
            user_id=user_id
        )

        return {"checkout_url": checkout_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in checkout: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Checkout failed: {str(e)}"
        ) from e


@router.get("/active/{user_id}")
def get_active_payments(user_id: str, token_user_id: str = Depends(verify_user_token)):
    """Get all active payment link URLs for a user."""
    user_id = get_user_id_from_body_or_token(user_id, token_user_id)
    from payment.payment_state import get_active_payments_for_user
    try:
        urls = get_active_payments_for_user(user_id)
        return {"active_urls": urls}
    except Exception as e:
        logger.error(f"Error fetching active payments for user {user_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch active payments: {str(e)}"
        ) from e


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Handle Stripe webhooks.

    When a payment is completed:
    1. Marks the item as 'sold'
    2. Records the transaction
    """
    from payment.webhooks import handle_checkout_completed, verify_webhook

    payload = await request.body()
    logger.info("\n🔔 WEBHOOK RECEIVED")
    logger.info(f"Stripe-Signature header present: {stripe_signature is not None}")
    logger.info(f"Payload size: {len(payload)} bytes")

    # Signature verification and fulfilment are synchronous: Supabase writes, an
    # email send and possibly a Stripe refund. Stripe retries on timeout, so a
    # stalled loop here compounds into duplicate deliveries.
    event = await asyncio.to_thread(verify_webhook, payload, stripe_signature)

    if not event:
        logger.error("❌ Webhook signature verification FAILED")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event['type']
    logger.info(f"✅ Event verified: {event_type}")

    # Handle different event types
    if event_type in ('checkout.session.completed', 'payment_link.completed'):
        logger.info(f"📦 Processing {event_type}")
        result = await asyncio.to_thread(handle_checkout_completed, event)
        logger.info(f"📦 Result: {result}")

        # If fulfilment hit a transient error, return 5xx so Stripe retries.
        # "duplicate" / "race_lost" are terminal successes — ack with 200.
        if result.get("status") == "error" and result.get("retry", True):
            raise HTTPException(status_code=503, detail="Fulfilment failed, retry")
    else:
        logger.info(f"ℹ️ Ignoring event type: {event_type}")

    return {"status": "success"}


@router.get("/transactions")
def get_transactions(admin: dict = Depends(verify_admin)):
    """Get all transactions (sales history). Admin only."""
    from payment.payment_history import get_all_transactions, get_sales_summary

    return {
        "transactions": get_all_transactions(),
        "summary": get_sales_summary()
    }


@router.post("/refund/{item_id}")
def refund_item(item_id: str, reason: str = None, admin: dict = Depends(verify_admin)):
    """Process a refund for an item. Admin only."""
    from payment.refunds import process_refund

    result = process_refund(item_id, reason)

    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=400, detail=result["error"])


@router.get("/orders/user/{user_id}")
def get_user_orders(user_id: str, token_user_id: str = Depends(verify_user_token)):
    """
    Get all orders for a specific user by their ID.
    Returns orders with item details.
    """
    user_id = get_user_id_from_body_or_token(user_id, token_user_id)
    # Get orders for this user
    response = admin_supabase.table('orders').select('*').eq('buyer_id', user_id).order('created_at', desc=True).execute()

    if not response.data:
        # Fallback: Check transactions table by email (if needed, but prefer orders)
        # For now, just return empty to encourage migration to orders table
        return {"orders": []}

    orders = []
    for order in response.data:
        item_id = order.get('item_id')
        item_response = admin_supabase.table('items').select('name, description, image_path, condition').eq('id', item_id).execute()

        item_data = item_response.data[0] if item_response.data else {}

        orders.append({
            "id": order.get('id'),
            "item_id": item_id,
            "item_name": order.get('item_name') or item_data.get('name', 'Unknown Item'),
            "item_image": item_data.get('image_path'),
            "item_condition": item_data.get('condition'),
            "amount": order.get('amount'),
            "status": order.get('status'),
            "created_at": order.get('created_at'),
            "stripe_payment_id": order.get('stripe_payment_id')
        })

    return {"orders": orders}





@router.post("/confirm-payment")
def confirm_payment(
    item_id: str = None,
    user_id: str = None,
    session_id: str = None,
    token_user_id: str = Depends(verify_user_token)
):
    """
    Frontend fallback after the success redirect, in case the Stripe webhook is
    delayed. This NEVER marks an item sold on trust — it requires a Stripe
    Checkout Session id that Stripe itself confirms as 'paid'. The actual
    fulfilment is delegated to the same idempotent, race-safe path the webhook
    uses, so calling this is always safe (duplicate calls are no-ops).
    """
    import stripe

    from env import STRIPE_API_KEY
    from payment.fulfillment import fulfill_purchase
    from payment.stripe_compat import stripe_get

    # Enforce the authenticated user; cannot confirm on behalf of another user.
    user_id = get_user_id_from_body_or_token(user_id, token_user_id)

    stripe.api_key = STRIPE_API_KEY

    logger.info(f"📦 CONFIRM-PAYMENT item={item_id} user={user_id} session={session_id}")

    # Without a verifiable Stripe session we cannot prove payment. Do NOT write
    # anything — just report whether the webhook has already marked it sold so
    # the frontend can show the right state. (Closes the free-item exploit.)
    if not session_id:
        if not item_id:
            raise HTTPException(status_code=400, detail="item_id is required")
        item_response = admin_supabase.table('items').select('status').eq('id', item_id).execute()
        if item_response.data and item_response.data[0].get('status') == 'sold':
            return {"status": "already_sold", "message": "Item already marked as sold"}
        # Webhook hasn't landed yet — tell the client to keep waiting.
        return {"status": "pending", "message": "Awaiting payment confirmation"}

    # Verify the session with Stripe — this is the proof of payment.
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except stripe.error.InvalidRequestError:
        logger.error(f"❌ Could not verify session {session_id}")
        raise HTTPException(status_code=400, detail="Invalid Stripe session") from None

    payment_status = stripe_get(session, 'payment_status')
    if payment_status != 'paid':
        logger.error(f"❌ Session not paid: {payment_status}")
        raise HTTPException(status_code=400, detail="Payment not completed")

    metadata = stripe_get(session, 'metadata') or {}
    # Trust Stripe's metadata for item/user, falling back to the request.
    item_id = stripe_get(metadata, 'item_id') or item_id
    session_user_id = stripe_get(metadata, 'user_id')

    # The authenticated caller must match the buyer recorded on the session.
    if session_user_id and session_user_id != user_id:
        logger.error("❌ Session buyer does not match authenticated user")
        raise HTTPException(status_code=403, detail="Session does not belong to this user")
    user_id = session_user_id or user_id

    if not item_id:
        raise HTTPException(status_code=400, detail="item_id is required")

    payment_intent = stripe_get(session, 'payment_intent')
    amount = (stripe_get(session, 'amount_total') or 0) / 100
    item_name = stripe_get(metadata, 'item_name')
    if (not item_name or item_name.strip().lower() == "item") and item_id:
        try:
            row = admin_supabase.table('items').select('name').eq('id', item_id).execute()
            if row and row.data and row.data[0].get('name'):
                item_name = row.data[0]['name']
        except Exception as e:
            logger.warning(f"⚠️ Confirm route item lookup error: {e}")
    item_name = item_name or 'Item'

    result = fulfill_purchase(
        item_id=item_id,
        user_id=user_id,
        payment_intent=payment_intent,
        amount=amount,
        item_name=item_name,
        buyer_email=stripe_get(stripe_get(session, 'customer_details'), 'email'),
    )

    status_map = {
        "fulfilled": ("success", "Payment confirmed and item marked as sold"),
        "duplicate": ("already_sold", "Item already marked as sold"),
        "race_lost": ("refunded", "Item was sold to someone else; you have been refunded"),
    }
    if result["status"] in status_map:
        code, msg = status_map[result["status"]]
        return {"status": code, "message": msg, "order_id": result.get("order_id")}

    raise HTTPException(status_code=500, detail="Could not confirm payment")
