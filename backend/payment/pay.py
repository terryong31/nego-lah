import stripe
from env import STRIPE_API_KEY

stripe.api_key = STRIPE_API_KEY


def create_checkout_session(item_name: str, price_cents: int, item_id: str, user_id: str = None):
    """
    Create a Stripe checkout session for an item.
    
    Args:
        item_name: Name of the item being sold
        price_cents: Price in cents (RM100 = 10000)
        item_id: Your database item ID (for tracking)
        user_id: User ID of the buyer (optional, for webhook tracking)
    
    Returns:
        Checkout URL to redirect customer to
    """
    metadata = {'item_id': item_id}
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
        success_url='https://nego-lah.terryong.me/?payment=success&session_id={CHECKOUT_SESSION_ID}',
        cancel_url='https://nego-lah.terryong.me/?payment=cancelled',
        metadata=metadata,
    )
    
    return session.url