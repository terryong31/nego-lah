from fastapi import APIRouter, HTTPException, Request, Header
from schemas import CheckoutRequest
from connector import admin_supabase
from payment.pay import create_checkout_session

router = APIRouter(prefix="", tags=["Payment"])


@router.post("/checkout")
def checkout(request: CheckoutRequest):
    """Create a Stripe checkout session for an item."""
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
        item_id=item_id
    )
    
    return {"checkout_url": checkout_url}


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
    event = verify_webhook(payload, stripe_signature)
    
    if not event:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    
    # Handle different event types
    if event['type'] == 'checkout.session.completed':
        handle_checkout_completed(event)
    
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


@router.get("/orders/user/{user_email}")
def get_user_orders(user_email: str):
    """
    Get all orders for a specific user by their email.
    Returns transactions with item details.
    """
    # Get transactions for this user
    response = admin_supabase.table('transactions').select('*').eq('buyer_email', user_email).order('created_at', desc=True).execute()
    
    if not response.data:
        return {"orders": []}
    
    # Get item details for each transaction
    orders = []
    for transaction in response.data:
        item_id = transaction.get('item_id')
        item_response = admin_supabase.table('items').select('name, description, image_path, condition').eq('id', item_id).execute()
        
        item_data = item_response.data[0] if item_response.data else {}
        
        orders.append({
            "id": transaction.get('id'),
            "item_id": item_id,
            "item_name": item_data.get('name', 'Unknown Item'),
            "item_image": item_data.get('image_path'),
            "item_condition": item_data.get('condition'),
            "amount": transaction.get('amount'),
            "status": transaction.get('status'),
            "created_at": transaction.get('created_at'),
            "stripe_payment_id": transaction.get('stripe_payment_id')
        })
    
    return {"orders": orders}


@router.get("/admin/orders")
def get_all_orders():
    """
    Get all orders for admin panel.
    Returns all transactions with item and buyer details.
    """
    from payment.payment_history import get_all_transactions, get_sales_summary
    
    transactions = get_all_transactions()
    
    # Enrich with item details
    orders = []
    for transaction in transactions:
        item_id = transaction.get('item_id')
        item_response = admin_supabase.table('items').select('name, image_path, price').eq('id', item_id).execute()
        
        item_data = item_response.data[0] if item_response.data else {}
        
        orders.append({
            "id": transaction.get('id'),
            "item_id": item_id,
            "item_name": item_data.get('name', 'Unknown Item'),
            "item_image": item_data.get('image_path'),
            "original_price": item_data.get('price'),
            "amount_paid": transaction.get('amount'),
            "buyer_email": transaction.get('buyer_email'),
            "status": transaction.get('status'),
            "created_at": transaction.get('created_at'),
            "stripe_payment_id": transaction.get('stripe_payment_id')
        })
    
    return {
        "orders": orders,
        "summary": get_sales_summary()
    }
