import stripe

from core import stripe_client
from core.env import STRIPE_WEBHOOK_SECRET
from core.logger import logger
from domains.billing.fulfillment import fulfill_purchase
from domains.billing.stripe_compat import stripe_get


def resolve_session_metadata(session) -> dict:
    """Resolve authoritative Stripe metadata for a Checkout Session.

    Stripe propagates PaymentLink metadata onto newly created Checkout Sessions;
    this also checks the underlying PaymentLink as a defensive fallback if a
    session's own metadata lacks `item_id` (SPEC-116 / SEC-16).
    """
    metadata = stripe_get(session, "metadata") or {}
    payment_link_id = stripe_get(session, "payment_link")
    if payment_link_id and not stripe_get(metadata, "item_id"):
        try:
            plink = stripe_client.get_stripe_client().v1.payment_links.retrieve(payment_link_id)
            metadata = stripe_get(plink, "metadata") or {}
        except Exception as e:
            logger.warning(f"Error fetching PaymentLink metadata: {e}")
    return metadata


def handle_checkout_completed(event) -> dict:
    """
    Called when a Stripe payment is successful.

    Extracts buyer/item from the session (or the underlying PaymentLink) and
    hands off to the idempotent, race-safe fulfiller. The actual money charged
    (amount_total) is the source of truth for the order amount.

    Returns the fulfill_purchase result dict so the route can decide whether to
    ask Stripe to retry.
    """
    session = stripe_get(stripe_get(event, "data"), "object")
    metadata = resolve_session_metadata(session)

    item_id = stripe_get(metadata, "item_id")
    user_id = stripe_get(metadata, "user_id")
    item_name = stripe_get(metadata, "item_name")
    if (not item_name or item_name.strip().lower() == "item") and item_id:
        from domains.catalog import CatalogService

        item_name = CatalogService.get_item_name(item_id) or item_name
    item_name = item_name or "Item"

    buyer_email = stripe_get(stripe_get(session, "customer_details"), "email")
    payment_intent = stripe_get(session, "payment_intent")

    # Trust the amount Stripe actually charged.
    amount = (stripe_get(session, "amount_total") or 0) / 100

    logger.info(f"PAYMENT COMPLETED — item={item_id} buyer={user_id} amount=RM{amount} pi={payment_intent}")

    if not item_id or not user_id:
        logger.error("Missing item_id or user_id in metadata — cannot fulfil")
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
    logger.info(f"Fulfillment result: {result.get('status')}")
    return result


def verify_webhook(payload: bytes, sig_header: str):
    """
    Verify that the webhook actually came from Stripe.
    Returns the event if valid, None if invalid.
    """
    try:
        event = stripe_client.get_stripe_client().construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        return event
    except ValueError:
        logger.error("Invalid webhook payload")
        return None
    except stripe.SignatureVerificationError:
        logger.error("Invalid webhook signature")
        return None
