import stripe
from connector import admin_supabase
from env import STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET

stripe.api_key = STRIPE_API_KEY


def handle_checkout_completed(event) -> bool:
    """
    Called when a Stripe payment is successful.
    
    1. Gets item_id from payment metadata
    2. Marks item as 'sold' in database
    3. Records the transaction
    """
    session = event['data']['object']
    
    # Get item_id from metadata (we set this when creating checkout)
    item_id = session.get('metadata', {}).get('item_id')
    buyer_email = session.get('customer_details', {}).get('email')
    amount = session.get('amount_total', 0) / 100  # Convert from cents
    
    if item_id:
        # Mark item as sold
        admin_supabase.table('items').update({
            'status': 'sold'
        }).eq('id', item_id).execute()
        
        # Record the transaction
        admin_supabase.table('transactions').insert({
            'item_id': item_id,
            'buyer_email': buyer_email,
            'amount': amount,
            'stripe_payment_id': session.get('payment_intent'),
            'status': 'completed'
        }).execute()
        
        print(f"✅ Item {item_id} marked as sold. Buyer: {buyer_email}")
        return True
    
    return False


def verify_webhook(payload: bytes, sig_header: str):
    """
    Verify that the webhook actually came from Stripe.
    Returns the event if valid, None if invalid.
    """
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        return event
    except ValueError:
        print("❌ Invalid payload")
        return None
    except stripe.error.SignatureVerificationError:
        print("❌ Invalid signature")
        return None
