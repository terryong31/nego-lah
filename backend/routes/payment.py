from fastapi import APIRouter, HTTPException, Request, Header, status
from schemas import CheckoutRequest
from connector import admin_supabase
from payment.pay import create_checkout_session

router = APIRouter(prefix="", tags=["Payment"])


@router.post("/checkout")
def checkout(request: CheckoutRequest):
    """Create a Stripe checkout session for an item."""
    try:
        item_id = request.item_id
        
        # Get item from database
        response = admin_supabase.table('items').select('*').eq('id', item_id).execute()
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Item not found")
        
        item = response.data[0]
        
        # Convert price to cents
        price_cents = int(float(item['price']) * 100)
        
        # Create Stripe checkout session
        checkout_url = create_checkout_session(
            item_name=item['name'],
            price_cents=price_cents,
            item_id=item_id,
            user_id=request.user_id
        )
        
        return {"checkout_url": checkout_url}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.info(f"Error in checkout: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Checkout failed: {str(e)}"
        )


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    """
    Handle Stripe webhooks.
    
    When a payment is completed:
    1. Marks the item as 'sold'
    2. Records the transaction
    """
    from payment.webhooks import verify_webhook, handle_checkout_completed
    
    payload = await request.body()
    logger.info(f"\n🔔 WEBHOOK RECEIVED")
    logger.info(f"Stripe-Signature header present: {stripe_signature is not None}")
    logger.info(f"Payload size: {len(payload)} bytes")
    
    event = verify_webhook(payload, stripe_signature)
    
    if not event:
        logger.info("❌ Webhook signature verification FAILED")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    
    event_type = event['type']
    logger.info(f"✅ Event verified: {event_type}")
    
    # Handle different event types
    if event_type == 'checkout.session.completed':
        logger.info("📦 Processing checkout.session.completed")
        result = handle_checkout_completed(event)
        logger.info(f"📦 Result: {result}")
    elif event_type == 'payment_link.completed':
        logger.info("📦 Processing payment_link.completed - treating as checkout")
        result = handle_checkout_completed(event)
        logger.info(f"📦 Result: {result}")
    else:
        logger.info(f"ℹ️ Ignoring event type: {event_type}")
    
    return {"status": "success"}


@router.get("/transactions")
def get_transactions():
    """Get all transactions (sales history)."""
    from payment.payment_history import get_all_transactions, get_sales_summary
    
    return {
        "transactions": get_all_transactions(),
        "summary": get_sales_summary()
    }


@router.post("/refund/{item_id}")
def refund_item(item_id: str, reason: str = None):
    """Process a refund for an item."""
    from payment.refunds import process_refund
    
    result = process_refund(item_id, reason)
    
    if result["success"]:
        return result
    else:
        raise HTTPException(status_code=400, detail=result["error"])


@router.get("/orders/user/{user_id}")
def get_user_orders(user_id: str):
    """
    Get all orders for a specific user by their ID.
    Returns orders with item details.
    """
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
def confirm_payment(item_id: str, user_id: str = None, session_id: str = None):
    """
    Manually confirm a payment and mark item as sold.
    This is a fallback when the Stripe webhook fails.
    
    Called from the frontend after successful payment redirect.
    """
    import stripe
    from env import STRIPE_API_KEY
    
    stripe.api_key = STRIPE_API_KEY
    
    logger.info(f"\n{'='*50}")
    logger.info(f"📦 MANUAL PAYMENT CONFIRMATION")
    logger.info(f"Item ID: {item_id}")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Session ID: {session_id}")
    logger.info(f"{'='*50}")
    
    try:
        # If we have a session_id, verify payment with Stripe
        if session_id:
            try:
                session = stripe.checkout.Session.retrieve(session_id)
                if session.payment_status != 'paid':
                    logger.info(f"❌ Payment not completed: {session.payment_status}")
                    raise HTTPException(status_code=400, detail="Payment not completed")
                
                # Get user_id from session metadata if not provided
                if not user_id:
                    user_id = session.metadata.get('user_id')
                
                # Get item_id from session metadata if not provided
                if not item_id:
                    item_id = session.metadata.get('item_id')
                    
                logger.info(f"✅ Stripe session verified - payment_status: {session.payment_status}")
            except stripe.error.InvalidRequestError:
                logger.info(f"⚠️ Could not verify session {session_id}, proceeding anyway")
        
        if not item_id:
            raise HTTPException(status_code=400, detail="item_id is required")
        
        # Check if item exists
        item_response = admin_supabase.table('items').select('*').eq('id', item_id).execute()
        if not item_response.data:
            raise HTTPException(status_code=404, detail="Item not found")
        
        item = item_response.data[0]
        
        # Check if already sold
        if item.get('status') == 'sold':
            logger.info(f"ℹ️ Item already marked as sold")
            # Invalidate cache just in case it's stale (this fixes the "sold but shows available" bug)
            try:
                from cache import invalidate_item_cache
                invalidate_item_cache(item_id)
                logger.info(f"✅ Cache forced invalidation for already-sold item {item_id}")
            except Exception as e:
                logger.info(f"⚠️ Could not invalidate cache: {e}")
                
            return {"status": "already_sold", "message": "Item was already marked as sold"}
        
        # Mark item as sold
        admin_supabase.table('items').update({
            'status': 'sold',
            'buyer_id': user_id
        }).eq('id', item_id).execute()
        logger.info(f"✅ Item marked as sold")
        
        # Invalidate cache so the status change shows up immediately
        from cache import invalidate_item_cache
        invalidate_item_cache(item_id)
        logger.info(f"✅ Cache invalidated for item {item_id}")
        
        # Get the actual amount paid - priority order:
        # 1. agreed_price from Redis (set during AI negotiation)
        # 2. amount_total from Stripe session (if available)
        # 3. Fallback to original item price
        amount_paid = None
        
        # Check Redis for negotiated price first
        if user_id:
            try:
                from payment.payment_state import get_pending_payment
                pending = get_pending_payment(user_id, item_id)
                if pending and pending.get('agreed_price'):
                    amount_paid = float(pending['agreed_price'])
                    logger.info(f"✅ Using negotiated price from Redis: RM{amount_paid}")
            except Exception as e:
                logger.info(f"⚠️ Could not check pending payment: {e}")
        
        # Try Stripe session amount if no Redis price
        if amount_paid is None and session_id:
            try:
                # Try to get the actual amount from the session we already retrieved
                amount_paid = session.amount_total / 100  # Convert from cents
                logger.info(f"✅ Using Stripe session amount: RM{amount_paid}")
            except:
                logger.info(f"⚠️ Could not get amount from session")
        
        # Final fallback to item price
        if amount_paid is None:
            amount_paid = item.get('price', 0)
            logger.info(f"⚠️ Using original item price as fallback: RM{amount_paid}")
        
        # Create order record
        order_data = {
            'item_id': item_id,
            'item_name': item.get('name', 'Unknown'),
            'buyer_id': user_id,
            'amount': amount_paid,
            'status': 'pending_info'
        }
        
        if session_id:
            order_data['stripe_payment_id'] = session_id
            
        order_result = admin_supabase.table('orders').insert(order_data).execute()
        order_id = order_result.data[0]['id'] if order_result.data else None
        logger.info(f"✅ Order created: {order_id}")
        
        # Also record in transactions table
        try:
            admin_supabase.table('transactions').insert({
                'item_id': item_id,
                'amount': item.get('price', 0),
                'status': 'completed',
                'stripe_payment_id': session_id
            }).execute()
            logger.info(f"✅ Transaction recorded")
        except Exception as e:
            logger.info(f"⚠️ Could not record transaction: {e}")
        
        return {
            "status": "success",
            "message": "Payment confirmed and item marked as sold",
            "order_id": order_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.info(f"❌ Error confirming payment: {e}")
        raise HTTPException(status_code=500, detail=str(e))
