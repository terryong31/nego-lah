import math

from langchain_core.tools import tool

from logger import logger


def _round_to_step(value: float, step: float) -> float:
    """Round `value` to the nearest multiple of `step`, halves rounding up.

    Keeps every price the agent *quotes* on a natural marketplace increment
    (RM5 by default) so a counter reads as "RM90", never "RM89.50" (SPEC-047).
    """
    if step <= 0:
        return value
    return math.floor(value / step + 0.5) * step


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
    logger.info(f"🪙 Current Standing Price (from model): RM{current_price}")
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

    # The seller's current standing price — the lowest we've already offered or
    # agreed to. Counters anchor to THIS, not the listed price, so the
    # negotiation only ever moves down.
    #
    # SPEC-084: the standing price is resolved from the SERVER, not from the
    # `current_price` argument alone. Asking the model to carry conversational
    # state in a tool argument did not work — across a full eval run it arrived
    # as 0 on 13 calls out of 13, so the anchor silently fell back to the listed
    # price every turn and the agent re-quoted the list price after conceding.
    # `active_negotiated_price` is the same resolver the item card and checkout
    # already use, so all three surfaces now agree on what this buyer was quoted.
    #
    # The argument is still honoured, but only ever DOWNWARD: the agent may have
    # quoted lower within this turn than the cache has recorded, while a
    # hallucinated high value must not be able to undo a real concession.
    from agent.context import get_user_id

    user_id = get_user_id()

    standing_price = None
    try:
        from payment.pricing import active_negotiated_price

        standing_price = active_negotiated_price(user_id, item_id)
    except Exception as e:  # noqa: BLE001 — a cache hiccup must not break a negotiation
        logger.warning(f"⚠️ Could not resolve standing price, anchoring to listed: {e}")

    candidates = [listed_price]
    if current_price and current_price > 0:
        candidates.append(float(current_price))
    if standing_price is not None:
        candidates.append(float(standing_price))

    # Clamp into [min_price, listed_price]: nothing may drag the anchor under
    # the floor, and nothing may lift it above the listing.
    anchor = min(max(min(candidates), min_price), listed_price)

    # LOG: Price calculations
    logger.info(f"📊 Listed Price: RM{listed_price}")
    logger.info(f"🔻 Min Price (floor): RM{min_price}")
    logger.info(f"🎯 Adjusted Threshold: RM{adjusted_threshold}")
    logger.info(f"🗄️ Standing Price (from server): {standing_price}")
    logger.info(f"⚓ Anchor (standing price): RM{anchor}")
    logger.info(f"{'='*50}\n")

    def make_counter() -> float | None:
        # SPEC-047: concede a rounded fraction of the gap the buyer is still
        # short of our standing price, so the quote lands on a natural
        # increment (…, 85, 90, 95) like a real haggle — not the arithmetic
        # midpoint that produced RM94.32. Returns None when the rounded
        # concession is zero (buyer already within one step) — the caller then
        # holds instead of countering. Never below what they offered, never
        # back up to our own standing price, always a whole ringgit.
        from agent.config import COUNTER_CONCESSION_RATIO, COUNTER_STEP_RM

        gap = anchor - offered_price
        concession = _round_to_step(gap * COUNTER_CONCESSION_RATIO, COUNTER_STEP_RM)
        if concession <= 0:
            return None
        candidate = float(round(anchor - concession))
        return candidate if offered_price < candidate < anchor else None

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
        if counter is None:
            # The rounded concession is zero — the buyer is within one step of
            # our price. Hold this round rather than shaving off loose change.
            result = (
                f"HOLD: Offer of RM{offered_price} is close to your price of RM{anchor:.0f}. "
                f"Restate RM{anchor:.0f} and don't go lower this round."
            )
        else:
            result = (
                f"COUNTER: Offer of RM{offered_price} is below your price of RM{anchor:.0f}. "
                f"Counter with RM{counter:.0f} (must stay ≤ RM{anchor:.0f} — never go back up)."
            )
    else:
        # Below the floor — hold (SPEC-047). A below-floor lowball earns no
        # concession: the buyer has to come up first. Only a genuine-need case
        # moves us, and that routes through the threshold branch above (a
        # positive extra_discount_percent), not here.
        #
        # Quote NO number and never name the floor (SPEC-044 A): min_price is
        # confidential (SPEC-036 revoked the column from anon / authenticated),
        # and a tool result is the most specific, most recent instruction the
        # model has — so if it spelled the floor out here, the model would
        # repeat it. The model has its own last quote in the transcript; the
        # tool tells it to restate that and hold.
        counter = None
        # SPEC-084: tell the model WHICH price to hold. "Hold firm at the price
        # you last quoted" assumed the model could remember its own last quote
        # from the transcript; it cannot. Given no number it improvised, and
        # what it improvised was the LISTED price — so a below-floor lowball
        # after a concession withdrew the concession.
        #
        # Naming the anchor here discloses nothing: it is a price this buyer was
        # already quoted out loud. The exception is an anchor sitting exactly on
        # `min_price`, where the number IS the floor — that path still quotes
        # nothing at all (SPEC-044 A, and see
        # `test_a_standing_price_at_the_floor_quotes_no_number_at_all`).
        # Phrasing matters here. "Hold firm at RM1150 and do not go lower" was
        # relayed to the buyer as "I can't go lower than RM1150" — a floor claim
        # about the LISTED price, which is both the wording the persona bans and
        # a lie that ends the negotiation while RM150 of room remains. The
        # instruction is addressed to the agent's own conduct instead: restate,
        # concede nothing, invite them up.
        if anchor > min_price:
            hold_instruction = (
                f"Your standing price is still RM{anchor:.0f}. Restate that number and invite them "
                f"to come up. Concede nothing this round."
            )
        else:
            hold_instruction = (
                "Restate the price you last quoted, invite them to come up, and concede nothing "
                "this round."
            )
        result = (
            f"REJECT_FLOOR: Offer of RM{offered_price} is too low to accept. "
            f"{hold_instruction} "
            f"Do NOT say this is your lowest, that you cannot go lower, or name any minimum "
            f"or floor — none of that is true and none of it is yours to say."
        )

    if user_id and item_id:
        try:
            from cache import redis_client
            active_price = None
            if "ACCEPT" in result and offered_price < listed_price:
                active_price = offered_price
            elif counter is not None:
                # Keyed off the variable, not the result text: only the COUNTER
                # branch sets `counter`, and a HOLD / REJECT_FLOOR result
                # deliberately leaves it None so nothing is committed for a
                # round where the agent didn't actually move the price.
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
