import stripe

from env import FRONTEND_URL, STRIPE_API_KEY

stripe.api_key = STRIPE_API_KEY


def create_checkout_session(
    item_name: str,
    price_cents: int,
    item_id: str,
    user_id: str = None,
    customer_email: str = None,
):
    """
    Create a Stripe checkout session for an item.

    Args:
        item_name: Name of the item being sold
        price_cents: Price in cents (RM100 = 10000). Already resolved by the
            caller — the negotiated price when the buyer has one, else the
            listed price (SPEC-047).
        item_id: Your database item ID (for tracking)
        user_id: User ID of the buyer (optional, for webhook tracking)
        customer_email: The buyer's Nego-Lah account email. Pre-fills the Stripe
            checkout so the receipt (SPEC-048) always has a deliverable address
            that matches the account, not just whatever they type on Stripe.

    Returns:
        Checkout URL to redirect customer to
    """
    metadata = {'item_id': item_id, 'item_name': item_name}
    if user_id:
        metadata['user_id'] = user_id

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'myr',
                'product_data': {
                    'name': item_name,
                },
                'unit_amount': price_cents,
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url=f'{FRONTEND_URL}/checkout/success?payment=success&item_id={item_id}&session_id={{CHECKOUT_SESSION_ID}}',
        cancel_url=f'{FRONTEND_URL}/checkout/cancel',
        metadata=metadata,
        customer_email=customer_email or None,
    )

    return session.url
