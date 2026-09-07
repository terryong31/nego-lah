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

    # Service role, not the anon key: `min_price` is revoked from anon /
    # authenticated at the column level (SPEC-036), so the floor is only
    # readable by a client that bypasses RLS.
    from connector import admin_supabase

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

    response = admin_supabase.table('items').select('*').eq('id', item_id).execute()

    # Fallback: if lookup failed and context ID exists, try that
    if not response.data and context_item_id and item_id != context_item_id:
        logger.info(f"⚠️ Lookup for '{item_id}' failed, falling back to context ID: {context_item_id}")
        item_id = context_item_id
        response = admin_supabase.table('items').select('*').eq('id', item_id).execute()

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

    # The price we end up offering, if any. Set by whichever branch produces a
    # counter, and committed below so checkout charges what the agent quoted.
    counter: float | None = None

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
        # Below the floor. Refuse it — but never name the floor (SPEC-044 A).
        #
        # `min_price` is confidential: SPEC-036 revoked the column from anon /
        # authenticated precisely so a buyer can't read it, and the system
        # prompt says "NEVER REVEAL THE MINIMUM PRICE". Spelling it out here
        # overrode both, because a tool result is the most specific and most
        # recent instruction the model has, so it's the one it follows.
        #
        # Concede half the room between our standing price and the floor
        # instead. That gives the model something concrete to say, moves the
        # negotiation, and approaches the floor asymptotically — so no round
        # ever lands on it and no counter discloses it.
        halfway = (anchor + min_price) / 2
        if halfway <= min_price:
            # The standing price is already at the floor, so every number we
            # could quote IS the floor. Hold at whatever we last offered
            # without restating it — the model has its own last quote in the
            # transcript, and the tool refuses to hand the value over.
            #
            # This is also what stops a buyer manufacturing the disclosure:
            # `current_price` comes from the model, so "you already offered me
            # RM1" clamps the anchor down to the floor. That reaches here and
            # gets no number, instead of quoting the floor back.
            counter = None
            result = (
                f"REJECT_FLOOR: Offer of RM{offered_price} is too low to accept. "
                f"Hold firm at the price you last quoted and do not go lower. "
                f"Do NOT state a minimum, a floor, or how low you can go."
            )
        else:
            counter = halfway
            result = (
                f"REJECT_FLOOR: Offer of RM{offered_price} is too low to accept. "
                f"Do NOT state a minimum or say how low you can go. "
                f"Counter with RM{counter:.2f} and tell the buyer that's the best you can do."
            )

    from agent.context import get_user_id

    user_id = get_user_id()
    if user_id and item_id:
        try:
            from cache import redis_client
            active_price = None
            if "ACCEPT" in result and offered_price < listed_price:
                active_price = offered_price
            elif counter is not None:
                # Keyed off the variable rather than sniffing the result string:
                # REJECT_FLOOR now quotes a counter too, and matching on the
                # word "COUNTER" would have missed it — leaving the agent
                # offering a price checkout knew nothing about.
                active_price = counter
            if active_price is not None:
                redis_client.setex(f"negotiated_price:{user_id}:{item_id}", 3 * 86400, str(active_price))
                # SPEC-041: signal the SSE stream loop to emit a data-discount frame.
                # ContextVar is isolated per async task so this never bleeds into other users.
                from agent.context import pending_discount
                pending_discount.set(active_price)
        except Exception as e:
            logger.warning(f"⚠️ Could not cache negotiated price: {e}")

    logger.info(f"📋 RESULT: {result}")
    return result
