from langchain.tools import tool
import stripe
import sys
sys.path.append('..')
from connector import admin_supabase
from env import STRIPE_API_KEY

stripe.api_key = STRIPE_API_KEY


@tool
def get_item_info(item_id: str) -> str:
    """Get item details including price range for negotiation. Use this first when discussing an item."""
    response = admin_supabase.table('items').select('*').eq('id', item_id).execute()
    if response.data:
        item = response.data[0]
        min_price = item.get('min_price') or item['price']
        return f"""
Item: {item['name']}
Asking Price: RM{item['price']}
Minimum Price: RM{min_price}
Condition: {item['condition']}
Description: {item['description']}

NEGOTIATION RULES:
- Defend RM{item['price']} first
- Can go as low as RM{min_price} but reluctantly
- Never go below RM{min_price}
"""
    return "Item not found"


@tool  
def evaluate_offer(item_id: str, offered_price: float) -> str:
    """Check if a buyer's offer is acceptable. Use this when buyer makes a price offer."""
    response = admin_supabase.table('items').select('*').eq('id', item_id).execute()
    if not response.data:
        return "Item not found"
    
    item = response.data[0]
    asking = float(item['price'])
    minimum = float(item.get('min_price') or asking)
    
    if offered_price >= asking:
        return f"ACCEPT - RM{offered_price} is full price or above! Create checkout link now."
    elif offered_price >= minimum:
        discount = ((asking - offered_price) / asking) * 100
        if discount <= 5:
            return f"ACCEPT - RM{offered_price} is within 5% discount. Create checkout link."
        elif discount <= 10:
            return f"ACCEPT RELUCTANTLY - RM{offered_price} is a {discount:.0f}% discount. Accept but act like it's a big favor."
        else:
            counter = minimum + (asking - minimum) * 0.6
            return f"COUNTER - Offer RM{counter:.0f} instead. Their RM{offered_price} is acceptable but try to get more first."
    else:
        return f"REJECT - RM{offered_price} is below minimum RM{minimum}. Cannot accept this offer."


@tool
def create_checkout_link(item_id: str, final_price: float, item_name: str) -> str:
    """Create a Stripe Payment Link for the agreed price. Use this when a deal is finalized."""
    try:
        # ========================================
        # CRITICAL: SERVER-SIDE PRICE VALIDATION
        # This check CANNOT be bypassed by prompt injection
        # ========================================
        response = admin_supabase.table('items').select('*').eq('id', item_id).execute()
        if not response.data:
            return "ERROR: Item not found. Cannot create checkout link."
        
        item = response.data[0]
        min_price = float(item.get('min_price') or item.get('price', 0))
        asking_price = float(item.get('price', 0))
        
        print(f"🔒 SECURITY CHECK: final_price={final_price}, min_price={min_price}")
        
        if final_price < min_price:
            # SECURITY: Do NOT reveal min_price to user
            return f"""🚫 PRICE VALIDATION FAILED

The offered price of RM{final_price:.2f} is too low and cannot be accepted.

Please continue negotiating for a fair price."""
        
        if final_price <= 0:
            return "ERROR: Price must be a positive number."
        
        print(f"✅ SECURITY: Price {final_price} >= min {min_price} - APPROVED")
        
        # Convert to cents (Stripe uses smallest currency unit)
        price_cents = int(final_price * 100)
        
        # Create a one-time product
        product = stripe.Product.create(
            name=item_name,
            metadata={"item_id": item_id, "source": "negotiation_bot"}
        )
        
        # Create price for this product
        price = stripe.Price.create(
            product=product.id,
            unit_amount=price_cents,
            currency="myr"
        )
        
        # Create the payment link
        payment_link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            metadata={
                "item_id": item_id, 
                "negotiated_price": str(final_price),
                "source": "negotiation_bot"
            }
        )
        
        return f"""
✅ CHECKOUT LINK CREATED!

Link: {payment_link.url}

Item: {item_name}
Price: RM{final_price}

Send this link to the buyer so they can complete the purchase.
"""
    
    except Exception as e:
        return f"Error creating payment link: {str(e)}"
