from langchain_core.tools import tool
from logger import logger

@tool
def assess_discount_eligibility(buyer_reason: str) -> str:
    """
    Assess if a buyer's reason for requesting a discount is genuine and deserving.
    Use your judgment to evaluate sincerity, relevance, and impact.
    
    Args:
        buyer_reason: The buyer's stated reason for wanting a discount
    
    Returns:
        Assessment with recommended discount percentage (0%, 5%, or 10%)
    """
    from .config import DISCOUNT_SCORING_GUIDE
    
    # LOG: Tool was called
    logger.info(f"\n{'='*50}")
    logger.info(f"🎯 ASSESS_DISCOUNT_ELIGIBILITY CALLED")
    logger.info(f"📝 Buyer's reason: {buyer_reason}")
    logger.info(f"{'='*50}\n")
    
    # This tool returns the scoring guide for the AI to use in its assessment
    # The AI will evaluate and decide based on the guide
    result = f"""
Use this guide to assess the buyer's reason:
{DISCOUNT_SCORING_GUIDE}

Buyer's reason: "{buyer_reason}"

Provide your assessment:
1. SINCERITY score (1-10):
2. RELEVANCE score (1-10):
3. IMPACT score (1-10):
4. Average score:
5. Recommended extra discount: 0%, 5%, or 10%
"""
    return result


@tool
def evaluate_offer(item_id: str, offered_price: float, extra_discount_percent: float = 0) -> str:
    """
    Evaluate a buyer's price offer against the item's minimum acceptable price.
    
    Args:
        item_id: The item being negotiated
        offered_price: The price the buyer is offering
        extra_discount_percent: Extra discount earned via assess_discount_eligibility (0, 5, or 10)
    
    Returns:
        Recommendation on whether to accept, counter, or reject the offer
    """

    from connector import user_supabase
    
    # LOG: Tool was called
    logger.info(f"\n{'='*50}")
    logger.info(f"💰 EVALUATE_OFFER CALLED")
    logger.info(f"📦 Item ID: {item_id}")
    logger.info(f"💵 Offered Price: RM{offered_price}")
    logger.info(f"🎁 Extra Discount: {extra_discount_percent}%")
    logger.info(f"{'='*50}")
    
    # Retrieve context item_id if available
    context_item_id = getattr(evaluate_offer, '_current_item_id', None)
    
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    
    # Fallback: if lookup failed and context ID exists, try that
    if not response.data and context_item_id and item_id != context_item_id:
        logger.info(f"⚠️ Lookup for '{item_id}' failed, falling back to context ID: {context_item_id}")
        item_id = context_item_id
        response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    
    if not response.data:
        logger.info("❌ Item not found!")
        return "Cannot evaluate - item not found."
    
    item = response.data[0]
    listed_price = float(item.get('price', 0))
    min_price = float(item.get('min_price', listed_price * 0.7))  # Absolute floor from DB
    
    # Apply extra discount to the acceptable threshold (not below min_price)
    discount_amount = listed_price * (extra_discount_percent / 100)
    adjusted_threshold = max(listed_price - discount_amount, min_price)
    
    # LOG: Price calculations
    logger.info(f"📊 Listed Price: RM{listed_price}")
    logger.info(f"🔻 Min Price (floor): RM{min_price}")
    logger.info(f"🎯 Adjusted Threshold: RM{adjusted_threshold}")
    logger.info(f"{'='*50}\n")
    
    if offered_price >= listed_price:
        result = f"ACCEPT: Offer of RM{offered_price} meets or exceeds listed price of RM{listed_price}."
    elif offered_price >= adjusted_threshold:
        if offered_price <= min_price:
            result = f"ACCEPT_FLOOR: Offer of RM{offered_price} hits the absolute minimum. Tell buyer: 'This is the lowest I can go, friend! Take it or leave it 😅'"
        else:
            # Counter should be HIGHER than what buyer offered, not lower!
            counter = (offered_price + listed_price) / 2
            # Ensure counter is never below what buyer offered
            counter = max(counter, offered_price + 1)
            result = f"COUNTER: Offer of RM{offered_price} is acceptable but below listed price. Suggest counter-offer of RM{counter:.2f}."
    elif offered_price >= min_price:
        # Offer is between min and adjusted threshold - buyer needs to come up
        # Counter with something between their offer and the listed price
        counter = (offered_price + listed_price) / 2
        # Ensure counter is never below what buyer offered
        counter = max(counter, offered_price + 1)
        result = f"COUNTER: Offer of RM{offered_price} is low but negotiable. Counter with RM{counter:.2f}. You can accept offers above RM{min_price}."
    else:
        result = f"REJECT_FLOOR: Offer of RM{offered_price} is below the absolute minimum of RM{min_price}. Tell buyer: 'Sorry, that's below my cost. The lowest I can do is RM{min_price}.'"
    
    logger.info(f"📋 RESULT: {result}")
    return result
