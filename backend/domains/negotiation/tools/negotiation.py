import math

from langchain_core.tools import tool

from core import cache, connector
from core.logger import logger
from domains.billing import BillingService
from domains.catalog import CatalogService
from domains.negotiation import context
from domains.negotiation.config import COUNTER_CONCESSION_RATIO, COUNTER_STEP_RM, DISCOUNT_SCORING_GUIDE

# Hard upper bound on buyer-earned extra discounts (SPEC-116 / SEC-18).
# The scoring guide only awards 0%, 5%, or 10%; clamping in code prevents
# prompt injection from supplying 100% and forcing acceptance at the floor.
MAX_EXTRA_DISCOUNT_PERCENT = 10.0


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
    logger.info(f"assess_discount_eligibility reason={buyer_reason!r}")

    return f"""
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


@tool
def evaluate_offer(
    item_id: str, offered_price: float, extra_discount_percent: float = 0, current_price: float = 0
) -> str:
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
    # SPEC-116 / SEC-18: reject non-finite offers and clamp extra_discount_percent
    # before any arithmetic so prompt injection cannot force acceptance at floor
    # or trigger NaN/Inf edge cases.
    if not math.isfinite(offered_price):
        logger.warning(f"evaluate_offer rejected non-finite offered_price={offered_price!r}")
        return "ERROR: Invalid offer price."

    if not math.isfinite(extra_discount_percent) or extra_discount_percent < 0:
        extra_discount_percent = 0.0
    elif extra_discount_percent > MAX_EXTRA_DISCOUNT_PERCENT:
        extra_discount_percent = MAX_EXTRA_DISCOUNT_PERCENT

    context_item_id = context.get_item_id()

    # Service role is required because `min_price` is revoked from anon/authenticated (SPEC-036).
    item = CatalogService.get_item_with_floor_price(item_id, supabase_client=connector.admin_supabase)

    if not item and context_item_id and item_id != context_item_id:
        logger.info(f"evaluate_offer lookup failed for item_id={item_id!r}, falling back to context={context_item_id}")
        item_id = context_item_id
        item = CatalogService.get_item_with_floor_price(item_id, supabase_client=connector.admin_supabase)

    if not item:
        logger.info(f"evaluate_offer item not found item_id={item_id!r}")
        return "Cannot evaluate - item not found."

    listed_price = float(item.get("price", 0))
    min_price = CatalogService.floor_price(item)  # Absolute floor; listed price when unset (SPEC-105)

    discount_amount = listed_price * (extra_discount_percent / 100)
    adjusted_threshold = max(listed_price - discount_amount, min_price)

    # Resolve standing price from server state (SPEC-084) so counters stay monotonic
    # across turns and ignore LLM-supplied current_price overrides (SPEC-116 / SEC-18).
    user_id = context.get_user_id()

    standing_price = None
    try:
        standing_price = BillingService.get_active_negotiated_price(user_id, item_id)
    except Exception as e:  # noqa: BLE001 — a cache hiccup must not break a negotiation
        logger.warning(f"evaluate_offer standing price lookup failed, anchoring to listed: {e}")

    candidates = [listed_price]
    if standing_price is not None:
        candidates.append(float(standing_price))

    # Clamp into [min_price, listed_price]
    anchor = min(max(min(candidates), min_price), listed_price)

    logger.info(
        f"evaluate_offer item_id={item_id} offered=RM{offered_price} extra_discount={extra_discount_percent}% "
        f"listed=RM{listed_price} floor=RM{min_price} standing={standing_price} anchor=RM{anchor}"
    )

    def make_counter() -> float | None:
        # SPEC-047: concede a rounded fraction of the gap on natural RM increments.
        gap = anchor - offered_price
        concession = _round_to_step(gap * COUNTER_CONCESSION_RATIO, COUNTER_STEP_RM)
        if concession <= 0:
            return None
        candidate = float(round(anchor - concession))
        return candidate if offered_price < candidate < anchor else None

    counter: float | None = None

    if offered_price >= listed_price:
        result = f"ACCEPT: Offer of RM{offered_price} meets or exceeds listed price of RM{listed_price}."
    elif offered_price >= anchor or offered_price >= adjusted_threshold:
        if offered_price <= min_price:
            result = f"ACCEPT_FLOOR: Offer of RM{offered_price} hits the absolute minimum. Tell buyer: 'This is the lowest I can go, friend! Take it or leave it 😅'"
        else:
            result = f"ACCEPT: Offer of RM{offered_price} matches or beats your current price of RM{anchor:.2f}. Take the deal."
    elif offered_price >= min_price:
        counter = make_counter()
        if counter is None:
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
        # Below the floor — hold without disclosing min_price (SPEC-044, SPEC-047, SPEC-084).
        # If anchor == min_price, quote no number at all to avoid leaking the floor.
        counter = None
        if anchor > min_price:
            hold_instruction = (
                f"Your standing price is still RM{anchor:.0f}. Restate that number and invite them "
                f"to come up. Concede nothing this round."
            )
        else:
            hold_instruction = (
                "Restate the price you last quoted, invite them to come up, and concede nothing this round."
            )
        result = (
            f"REJECT_FLOOR: Offer of RM{offered_price} is too low to accept. "
            f"{hold_instruction} "
            f"Do NOT say this is your lowest, that you cannot go lower, or name any minimum "
            f"or floor — none of that is true and none of it is yours to say."
        )

    if user_id and item_id:
        try:
            active_price = None
            if "ACCEPT" in result and offered_price < listed_price:
                active_price = offered_price
            elif counter is not None:
                active_price = counter
            if active_price is not None:
                cache.redis_client.setex(f"negotiated_price:{user_id}:{item_id}", 3 * 86400, str(active_price))
                # SPEC-041: signal SSE stream to emit a data-discount frame.
                context.pending_discount.set(active_price)
        except Exception as e:
            logger.warning(f"evaluate_offer failed to cache negotiated price: {e}")

    logger.info(f"evaluate_offer result={result.split(':', 1)[0]} item_id={item_id}")
    return result
