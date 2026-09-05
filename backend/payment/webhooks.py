import stripe

from env import STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET
from logger import logger
from payment.fulfillment import fulfill_purchase
from payment.stripe_compat import stripe_get

stripe.api_key = STRIPE_API_KEY


def handle_checkout_completed(event) -> dict:
    """
    Called when a Stripe payment is successful.

    Extracts buyer/item from the session (or the underlying PaymentLink) and
    hands off to the idempotent, race-safe fulfiller. The actual money charged
    (amount_total) is the source of truth for the order amount.

    Returns the fulfill_purchase result dict so the route can decide whether to
    ask Stripe to retry.
    """
    session = stripe_get(stripe_get(event, 'data'), 'object')

    metadata = stripe_get(session, 'metadata') or {}

    # PaymentLinks don't propagate metadata onto the Session — fetch from the link.
    payment_link_id = stripe_get(session, 'payment_link')
    if payment_link_id and not stripe_get(metadata, 'item_id'):
        try:
            plink = stripe.PaymentLink.retrieve(payment_link_id)
            metadata = stripe_get(plink, 'metadata') or {}
        except Exception as e:
            logger.warning(f"⚠️ Error fetching PaymentLink metadata: {e}")

    item_id = stripe_get(metadata, 'item_id')
    user_id = stripe_get(metadata, 'user_id')
    item_name = stripe_get(metadata, 'item_name')
    if (not item_name or item_name.strip().lower() == "item") and item_id:
        try:
            from connector import admin_supabase
            row = admin_supabase.table('items').select('name').eq('id', item_id).execute()
            if row and row.data and row.data[0].get('name'):
                item_name = row.data[0]['name']
        except Exception as e:
            logger.warning(f"⚠️ Webhook item lookup error: {e}")
    item_name = item_name or 'Item'

    buyer_email = stripe_get(stripe_get(session, 'customer_details'), 'email')
    payment_intent = stripe_get(session, 'payment_intent')

    # Trust the amount Stripe actually charged.
    amount = (stripe_get(session, 'amount_total') or 0) / 100

    logger.info(
        f"💰 PAYMENT COMPLETED — item={item_id} buyer={user_id} "
        f"amount=RM{amount} pi={payment_intent}"
    )

    if not item_id or not user_id:
        logger.error("❌ Missing item_id or user_id in metadata — cannot fulfil")
        # Nothing we can do server-side; don't ask Stripe to retry forever.
        return {"status": "error", "error": "missing_metadata", "retry": False}

    result = fulfill_purchase(
        item_id=item_id,
        user_id=user_id,
        payment_intent=payment_intent,
        amount=amount,
        item_name=item_name,
        buyer_email=buyer_email,
    )
    logger.info(f"📦 Fulfillment result: {result.get('status')}")
    return result


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
        logger.error("❌ Invalid webhook payload")
        return None
    except stripe.error.SignatureVerificationError:
        logger.error("❌ Invalid webhook signature")
        return None
