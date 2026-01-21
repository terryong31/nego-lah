import stripe
from env import STRIPE_API_KEY

stripe.api_key = STRIPE_API_KEY


def create_checkout_session(item_name: str, price_cents: int, item_id: str):
    """
    Create a Stripe checkout session for an item.
    
    Args:
        item_name: Name of the item being sold
        price_cents: Price in cents (RM100 = 10000)
        item_id: Your database item ID (for tracking)
    
    Returns:
        Checkout URL to redirect customer to
    """
    session = stripe.checkout.Session.create(
        payment_method_types=['card', 'fpx', 'grabpay'],
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
        success_url='https://nego-lah.terryong.me/?payment=success',
        cancel_url='https://nego-lah.terryong.me/?payment=cancelled',
        metadata={'item_id': item_id},
    )
    
    return session.url