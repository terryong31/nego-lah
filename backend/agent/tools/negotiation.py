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
    from ..config import DISCOUNT_SCORING_GUIDE

    # LOG: Tool was called
    logger.info(f"\n{'='*50}")
    logger.info("🎯 ASSESS_DISCOUNT_ELIGIBILITY CALLED")
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
def evaluate_offer(item_id: str, offered_price: float, extra_discount_percent: float = 0, current_price: float = 0) -> str:
    """
    Evaluate a buyer's price offer against the item's minimum acceptable price.

    Args:
        item_id: The item being negotiated
        offered_price: The price the buyer is offering
        extra_discount_percent: Extra discount earned via assess_discount_eligibility (0, 5, or 10)
        current_price: The LOWEST price you (the seller) have already offered or agreed to
            earlier in THIS conversation. Pass 0 (or omit) if you have not yet made any
            counter-offer below the listed price. A negotiation can only move DOWN: the
            counter will never be higher than this value once you've committed to it.

    Returns:
        Recommendation on whether to accept, counter, or reject the offer
    """

    from connector import user_supabase

    # LOG: Tool was called
    logger.info(f"\n{'='*50}")
    logger.info("💰 EVALUATE_OFFER CALLED")
    logger.info(f"📦 Item ID: {item_id}")
    logger.info(f"💵 Offered Price: RM{offered_price}")
    logger.info(f"🎁 Extra Discount: {extra_discount_percent}%")
    logger.info(f"🪙 Current Standing Price: RM{current_price}")
    logger.info(f"{'='*50}")

    # Retrieve context item_id if available
    from agent.context import get_item_id
    context_item_id = get_item_id()

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

    # The seller's current standing price — the lowest we've already offered/agreed
    # to this conversation. Counters anchor to THIS, not the listed price, so the
    # negotiation only ever moves down. Sanitize into [min_price, listed_price];
    # if no prior offer was made (0 / unset), the anchor is the listed price.
    anchor = listed_price
    if current_price and current_price > 0:
        anchor = min(max(current_price, min_price), listed_price)

    # LOG: Price calculations
    logger.info(f"📊 Listed Price: RM{listed_price}")
    logger.info(f"🔻 Min Price (floor): RM{min_price}")
    logger.info(f"🎯 Adjusted Threshold: RM{adjusted_threshold}")
    logger.info(f"⚓ Anchor (standing price): RM{anchor}")
    logger.info(f"{'='*50}\n")

    def make_counter() -> float:
        # Meet the buyer partway between their offer and our standing price, but
        # NEVER above the anchor (no going back up) and always a little above
        # what they offered so there's room to settle.
        counter = (offered_price + anchor) / 2
        counter = max(counter, offered_price + 1)
        counter = min(counter, anchor)
        return counter

    if offered_price >= listed_price:
        result = f"ACCEPT: Offer of RM{offered_price} meets or exceeds listed price of RM{listed_price}."
    elif offered_price >= anchor or offered_price >= adjusted_threshold:
        # Buyer met (or beat) the price we already agreed to / our discounted threshold — close it.
        if offered_price <= min_price:
            result = f"ACCEPT_FLOOR: Offer of RM{offered_price} hits the absolute minimum. Tell buyer: 'This is the lowest I can go, friend! Take it or leave it 😅'"
        else:
            result = f"ACCEPT: Offer of RM{offered_price} matches or beats your current price of RM{anchor:.2f}. Take the deal."
    elif offered_price >= min_price:
        counter = make_counter()
        if counter <= offered_price:
            # No meaningful room left above their offer — accept it.
            result = f"ACCEPT: Offer of RM{offered_price} is as good as it gets above the floor. Take the deal."
        else:
            result = f"COUNTER: Offer of RM{offered_price} is below your current price of RM{anchor:.2f}. Counter with RM{counter:.2f} (must be ≤ RM{anchor:.2f} — never go back up)."
    else:
        result = f"REJECT_FLOOR: Offer of RM{offered_price} is below the absolute minimum of RM{min_price}. Tell buyer: 'Sorry, that's below my cost. The lowest I can do is RM{min_price}.'"

    logger.info(f"📋 RESULT: {result}")
    return result
