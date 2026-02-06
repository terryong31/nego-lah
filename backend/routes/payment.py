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
        print(f"Error in checkout: {str(e)}")
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
    print(f"\n🔔 WEBHOOK RECEIVED")
    print(f"Stripe-Signature header present: {stripe_signature is not None}")
    print(f"Payload size: {len(payload)} bytes")
    
    event = verify_webhook(payload, stripe_signature)
    
    if not event:
        print("❌ Webhook signature verification FAILED")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    
    event_type = event['type']
    print(f"✅ Event verified: {event_type}")
    
    # Handle different event types
    if event_type == 'checkout.session.completed':
        print("📦 Processing checkout.session.completed")
        result = handle_checkout_completed(event)
        print(f"📦 Result: {result}")
    elif event_type == 'payment_link.completed':
        print("📦 Processing payment_link.completed - treating as checkout")
        result = handle_checkout_completed(event)
        print(f"📦 Result: {result}")
    else:
        print(f"ℹ️ Ignoring event type: {event_type}")
    
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
    
    print(f"\n{'='*50}")
    print(f"📦 MANUAL PAYMENT CONFIRMATION")
    print(f"Item ID: {item_id}")
    print(f"User ID: {user_id}")
    print(f"Session ID: {session_id}")
    print(f"{'='*50}")
    
    try:
        # If we have a session_id, verify payment with Stripe
        if session_id:
            try:
                session = stripe.checkout.Session.retrieve(session_id)
                if session.payment_status != 'paid':
                    print(f"❌ Payment not completed: {session.payment_status}")
                    raise HTTPException(status_code=400, detail="Payment not completed")
                
                # Get user_id from session metadata if not provided
                if not user_id:
                    user_id = session.metadata.get('user_id')
                
                # Get item_id from session metadata if not provided
                if not item_id:
                    item_id = session.metadata.get('item_id')
                    
                print(f"✅ Stripe session verified - payment_status: {session.payment_status}")
            except stripe.error.InvalidRequestError:
                print(f"⚠️ Could not verify session {session_id}, proceeding anyway")
        
        if not item_id:
            raise HTTPException(status_code=400, detail="item_id is required")
        
        # Check if item exists
        item_response = admin_supabase.table('items').select('*').eq('id', item_id).execute()
        if not item_response.data:
            raise HTTPException(status_code=404, detail="Item not found")
        
        item = item_response.data[0]
        
        # Check if already sold
        if item.get('status') == 'sold':
            print(f"ℹ️ Item already marked as sold")
            # Invalidate cache just in case it's stale (this fixes the "sold but shows available" bug)
            try:
                from cache import invalidate_item_cache
                invalidate_item_cache(item_id)
                print(f"✅ Cache forced invalidation for already-sold item {item_id}")
            except Exception as e:
                print(f"⚠️ Could not invalidate cache: {e}")
                
            return {"status": "already_sold", "message": "Item was already marked as sold"}
        
        # Mark item as sold
        admin_supabase.table('items').update({
            'status': 'sold',
            'buyer_id': user_id
        }).eq('id', item_id).execute()
        print(f"✅ Item marked as sold")
        
        # Invalidate cache so the status change shows up immediately
        from cache import invalidate_item_cache
        invalidate_item_cache(item_id)
        print(f"✅ Cache invalidated for item {item_id}")
        
        # Create order record
        order_data = {
            'item_id': item_id,
            'item_name': item.get('name', 'Unknown'),
            'buyer_id': user_id,
            'amount': item.get('price', 0),
            'status': 'pending_info'
        }
        
        if session_id:
            order_data['stripe_payment_id'] = session_id
            
        order_result = admin_supabase.table('orders').insert(order_data).execute()
        order_id = order_result.data[0]['id'] if order_result.data else None
        print(f"✅ Order created: {order_id}")
        
        # Also record in transactions table
        try:
            admin_supabase.table('transactions').insert({
                'item_id': item_id,
                'amount': item.get('price', 0),
                'status': 'completed',
                'stripe_payment_id': session_id
            }).execute()
            print(f"✅ Transaction recorded")
        except Exception as e:
            print(f"⚠️ Could not record transaction: {e}")
        
        return {
            "status": "success",
            "message": "Payment confirmed and item marked as sold",
            "order_id": order_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error confirming payment: {e}")
        raise HTTPException(status_code=500, detail=str(e))
