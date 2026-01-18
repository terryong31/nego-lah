import stripe
from connector import admin_supabase
from env import STRIPE_API_KEY
from typing import Dict

stripe.api_key = STRIPE_API_KEY


def process_refund(item_id: str, reason: str = None) -> Dict:
    """
    Process a full refund for an item.
    
    Steps:
    1. Find the transaction in database
    2. Refund via Stripe API
    3. Mark item as 'available' again
    4. Update transaction status to 'refunded'
    
    Args:
        item_id: The item to refund
        reason: Optional reason (requested_by_customer, duplicate, fraudulent)
    
    Returns:
        Dict with success status and refund_id or error message
    """
    # Get the transaction
    response = admin_supabase.table('transactions').select('*').eq('item_id', item_id).execute()
    
    if not response.data:
        return {"success": False, "error": "Transaction not found for this item"}
    
    transaction = response.data[0]
    
    # Check if already refunded
    if transaction.get('status') == 'refunded':
        return {"success": False, "error": "This item has already been refunded"}
    
    payment_id = transaction.get('stripe_payment_id')
    
    if not payment_id:
        return {"success": False, "error": "No Stripe payment ID found"}
    
    try:
        # Process refund in Stripe
        refund = stripe.Refund.create(
            payment_intent=payment_id,
            reason=reason or "requested_by_customer"
        )
        
        # Mark item as available again
        admin_supabase.table('items').update({
            'status': 'available'
        }).eq('id', item_id).execute()
        
        # Update transaction status
        admin_supabase.table('transactions').update({
            'status': 'refunded'
        }).eq('item_id', item_id).execute()
        
        print(f"✅ Refund processed for item {item_id}. Refund ID: {refund.id}")
        
        return {
            "success": True, 
            "refund_id": refund.id,
            "amount_refunded": transaction.get('amount')
        }
    
    except stripe.error.StripeError as e:
        print(f"❌ Stripe error: {str(e)}")
        return {"success": False, "error": str(e)}
