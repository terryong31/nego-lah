
import stripe

from connector import admin_supabase
from env import STRIPE_API_KEY
from logger import logger

stripe.api_key = STRIPE_API_KEY


def process_refund(item_id: str, reason: str = None) -> dict:
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

    # Process refund in Stripe. If this raises a StripeError the money never
    # moved, so returning a failure is safe. A non-Stripe error (e.g. network)
    # is deliberately left to propagate for the same reason — nothing to undo.
    try:
        refund = stripe.Refund.create(
            payment_intent=payment_id,
            reason=reason or "requested_by_customer"
        )
    except stripe.error.StripeError as e:
        logger.error(f"❌ Stripe refund failed for item {item_id}: {e}")
        return {"success": False, "error": str(e)}

    # The money has now been refunded on Stripe. The DB writes below MUST be
    # best-effort: if one raises and propagates, the caller would treat the whole
    # refund as failed and could retry, double-refunding the customer. True
    # multi-row atomicity would need a Postgres RPC; short of that, we isolate
    # each write and surface a reconciliation warning instead of failing.
    db_errors = []

    # Mark item available again and clear the buyer so it can be re-sold.
    try:
        admin_supabase.table('items').update({
            'status': 'available',
            'buyer_id': None
        }).eq('id', item_id).execute()
    except Exception as e:
        db_errors.append(f"items({item_id}): {e}")

    # Invalidate cache so the relisted item shows up immediately.
    try:
        from cache import invalidate_item_cache
        invalidate_item_cache(item_id)
    except Exception as e:
        logger.warning(f"⚠️ Could not invalidate cache for item {item_id}: {e}")

    # Update the order tied to this exact payment so buyer order history is
    # accurate (the legacy transactions row is updated for completeness too).
    try:
        admin_supabase.table('orders').update({
            'status': 'refunded'
        }).eq('stripe_payment_id', payment_id).execute()
    except Exception as e:
        db_errors.append(f"orders(pi={payment_id}): {e}")

    try:
        admin_supabase.table('transactions').update({
            'status': 'refunded'
        }).eq('item_id', item_id).execute()
    except Exception as e:
        db_errors.append(f"transactions({item_id}): {e}")

    result = {
        "success": True,
        "refund_id": refund.id,
        "amount_refunded": transaction.get('amount')
    }

    if db_errors:
        logger.error(
            f"Refund {refund.id} succeeded on Stripe but DB sync was incomplete "
            f"({'; '.join(db_errors)}). Manual reconciliation required."
        )
        result["db_sync_warning"] = (
            "Refund processed on Stripe but the database update was incomplete; "
            "manual reconciliation needed."
        )
    else:
        logger.info(f"✅ Refund processed for item {item_id}. Refund ID: {refund.id}")

    return result
