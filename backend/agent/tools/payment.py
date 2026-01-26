from langchain_core.tools import tool

@tool
def create_checkout_link(item_id: str, agreed_price: float) -> str:
    """
    Create a Stripe checkout link for the agreed sale.
    Only use this when both parties have agreed on a final price.
    
    IMPORTANT: Once a payment link is created, the price is LOCKED.
    Tell the buyer they cannot negotiate further - they must pay or cancel.
    
    Args:
        item_id: The item to purchase
        agreed_price: The final agreed price
    
    Returns:
        Checkout URL or error message
    """
    import stripe
    from env import STRIPE_API_KEY
    from connector import user_supabase
    from payment.payment_state import (
        get_pending_payment, 
        store_pending_payment,
        has_active_payment
    )
    
    print(f"\n{'='*50}")
    print(f"💳 CREATE_CHECKOUT_LINK CALLED")
    print(f"📦 Item ID: {item_id}")
    print(f"💰 Agreed Price: RM{agreed_price}")
    print(f"{'='*50}")
    
    stripe.api_key = STRIPE_API_KEY
    
    # Get current user_id from conversation context
    # This will be passed in via the agent's state
    user_id = getattr(create_checkout_link, '_current_user_id', None)
    context_item_id = getattr(create_checkout_link, '_current_item_id', None)
    print(f"👤 User ID: {user_id}")
    print(f"📦 Context Item ID: {context_item_id}")
    
    if not user_id:
        return "ERROR: Cannot create checkout - user not identified. Please ensure you're logged in."

    # FALLBACK: If item_id is missing, placeholder, or not found, try using context_item_id
    # Common hallucinations: 'test-item-id', 'item_id', 'CHECKOUT_LINK'
    if (not item_id or item_id in ['test-item-id', 'item_id', 'string']) and context_item_id:
        print(f"⚠️ Invalid/Missing item_id '{item_id}', using context_item_id: {context_item_id}")
        item_id = context_item_id
    
    # Check for existing payment link
    existing = get_pending_payment(user_id, item_id)
    if existing:
        print(f"⚠️ Existing payment link found!")
        return f"A payment link already exists for this item at RM{existing['agreed_price']:.2f}. The price is locked - please complete the payment or say 'cancel' to start over. Link: {existing['payment_url']}"
    
    # Get item details
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    print(f"📊 Item lookup result: {len(response.data) if response.data else 0} items")
    
    # Double check: if lookup failed and we haven't tried context_item_id yet, try it now
    if (not response.data) and context_item_id and (item_id != context_item_id):
        print(f"⚠️ Lookup failed for '{item_id}', trying context_item_id: {context_item_id}")
        item_id = context_item_id
        response = user_supabase.table('items').select('*').eq('id', item_id).execute()
        print(f"📊 Retry lookup result: {len(response.data) if response.data else 0} items")
    
    if not response.data:
        print(f"❌ Item not found!")
        return "Cannot create checkout - item not found. Please try again or ask about the item explicitly."
    
    item = response.data[0]
    item_name = item.get('name', 'Item')
    print(f"✅ Item found: {item_name}")
    
    try:
        # Create Stripe Product (so we can archive it later)
        print(f"🔄 Creating Stripe Product...")
        product = stripe.Product.create(
            name=item_name,
            metadata={
                "item_id": item_id,
                "user_id": user_id,
                "source": "nego_lah_ai"
            }
        )
        print(f"✅ Product created: {product.id}")
        
        # Create Stripe Price
        print(f"🔄 Creating Stripe Price...")
        price = stripe.Price.create(
            product=product.id,
            unit_amount=int(agreed_price * 100),  # Convert to cents
            currency="myr"
        )
        print(f"✅ Price created: {price.id}")
        
        # Create Payment Link with user_id in metadata (for webhook to identify buyer)
        print(f"🔄 Creating Stripe PaymentLink...")
        payment_link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            metadata={
                "item_id": item_id,
                "user_id": user_id,
            },
            after_completion={
                "type": "redirect",
                "redirect": {
                    "url": "https://nego-lah.com/payment-success?session_id={CHECKOUT_SESSION_ID}"
                }
            }
        )
        print(f"✅ Payment Link created: {payment_link.url}")
        
        # Store in Redis for cleanup logic
        store_pending_payment(
            user_id=user_id,
            item_id=item_id,
            agreed_price=agreed_price,
            payment_link_id=payment_link.id,
            product_id=product.id,
            price_id=price.id,
            payment_url=payment_link.url
        )
        
        return f"Payment link created for RM{agreed_price:.2f}: {payment_link.url} (Note: This link is valid for 3 days)"
        
    except Exception as e:
        print(f"❌ Error creating payment link: {str(e)}")
        return f"Error creating payment link: {str(e)}"


@tool
def cancel_payment_link(item_id: str) -> str:
    """
    Cancel an existing payment link when buyer says they don't want it anymore.
    Use this when the buyer explicitly cancels or says they're not interested.
    
    This will:
    1. Deactivate the payment link in Stripe
    2. Archive the product in Stripe
    3. Remove from pending payments
    
    Args:
        item_id: The item whose payment link should be cancelled
    
    Returns:
        Confirmation message
    """

    from payment.payment_state import get_pending_payment, delete_pending_payment
    
    print(f"\n{'='*50}")
    print(f"🚫 CANCEL_PAYMENT_LINK CALLED")
    print(f"📦 Item ID: {item_id}")
    print(f"{'='*50}")
    
    # Get current user_id from conversation context
    user_id = getattr(cancel_payment_link, '_current_user_id', None)
    print(f"👤 User ID: {user_id}")
    
    if not user_id:
        return "ERROR: Cannot cancel - user not identified."
    
    # Check if payment link exists
    existing = get_pending_payment(user_id, item_id)
    if not existing:
        return "No active payment link found for this item. You can continue negotiating or ask about other items."
    
    # Delete from Redis and cleanup Stripe
    success = delete_pending_payment(user_id, item_id, cleanup_stripe=True)
    
    if success:
        print(f"✅ Payment link cancelled successfully")
        return f"Payment link cancelled. The payment link for RM{existing['agreed_price']:.2f} has been deactivated. You're free to negotiate a new price or look at other items."
    else:
        return "Error cancelling payment link. Please try again."


@tool
def collect_shipping_info(order_id: str, recipient_name: str, phone: str, address: str) -> str:
    """
    Collect and save shipping information for an order after payment.
    Use this after the buyer has paid and provides their shipping details.
    
    Args:
        order_id: The order ID from the payment
        recipient_name: Full name of the recipient
        phone: Phone number for delivery
        address: Full shipping address
    
    Returns:
        Confirmation message
    """

    from connector import admin_supabase
    
    print(f"\n{'='*50}")
    print(f"📦 COLLECT_SHIPPING_INFO CALLED")
    print(f"🆔 Order ID: {order_id}")
    print(f"👤 Name: {recipient_name}")
    print(f"📞 Phone: {phone}")
    print(f"📍 Address: {address}")
    print(f"{'='*50}")
    
    try:
        # Update order with shipping info
        result = admin_supabase.table('orders').update({
            'recipient_name': recipient_name,
            'phone': phone,
            'address': address,
            'status': 'confirmed'
        }).eq('id', order_id).execute()
        
        if result.data:
            print(f"✅ Shipping info saved successfully")
            return f"Shipping information saved! Your order will be shipped to:\n\n**{recipient_name}**\n📞 {phone}\n📍 {address}\n\nYou'll receive updates when your item ships. Thank you for your purchase!"
        else:
            return "Order not found. Please check the order ID."
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return f"Error saving shipping info: {str(e)}"

@tool
def web_search(query: str) -> str:
    """
    Search the web for information using DuckDuckGo.
    Use this to find item prices, specs, or verify information.
    
    Args:
        query: Search query
    
    Returns:
        Summary of search results
    """
    # Note: duckduckgo_search must be installed
    from duckduckgo_search import DDGS
    
    print(f"\n{'='*50}")
    print(f"🌍 WEB_SEARCH CALLED")
    print(f"❓ Query: {query}")
    print(f"{'='*50}")
    
    try:
        results = DDGS().text(query, max_results=3)
        if results:
            summary = "\n".join([f"- {r['title']}: {r['body']}" for r in results])
            return f"Found the following info:\n{summary}"
        return "No results found."
    except Exception as e:
        print(f"❌ Search error: {e}")
        return f"Error searching web: {str(e)}"
