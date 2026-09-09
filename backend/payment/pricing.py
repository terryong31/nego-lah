"""
Negotiated-price resolution (SPEC-047).

A buyer who has haggled with the agent has a price that is lower than the
listing — cached by `evaluate_offer` in Redis, or locked into a pending Stripe
payment link. Every "what does this buyer actually pay?" surface must agree on
that number:

- `routes/items.py::_apply_discount` — the `discounted_price` shown on the item
  card, the item detail page and the chat header pin.
- `routes/payment.py::checkout` — the amount the **Buy Now** button charges.
  Before SPEC-047 this path ignored the negotiation entirely and charged the
  listed price, so a buyer who agreed RM900 in chat was billed RM1000 the moment
  they tapped Buy Now instead of the agent's pay link.

This module is the single place that logic lives.
"""

from logger import logger


def active_negotiated_price(user_id: str | None, item_id: str | None) -> float | None:
    """The lowest still-live price this buyer has been quoted for this item.

    Considers, and takes the minimum of:
      1. a pending Stripe payment link's locked `agreed_price`
         (`payment_state.get_pending_payment`);
      2. the agent's cached counter / acceptance
         (`negotiated_price:{user_id}:{item_id}` in Redis, 3-day TTL, written by
         `evaluate_offer`).

    Returns `None` when the buyer has neither — the caller then falls back to the
    listed price. Never raises: a Redis/state hiccup must not block a checkout.
    """
    if not user_id or not item_id:
        return None

    prices: list[float] = []

    try:
        from payment.payment_state import get_pending_payment

        pending = get_pending_payment(user_id, item_id)
        if pending and pending.get("agreed_price") is not None:
            prices.append(float(pending["agreed_price"]))
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"active_negotiated_price: pending-payment lookup failed for {user_id}/{item_id}: {e}")

    try:
        from cache import redis_client

        cached = redis_client.get(f"negotiated_price:{user_id}:{item_id}")
        if cached is not None:
            prices.append(float(cached))
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"active_negotiated_price: redis lookup failed for {user_id}/{item_id}: {e}")

    return min(prices) if prices else None
