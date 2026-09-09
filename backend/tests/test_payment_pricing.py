"""Tests for payment/pricing.py::active_negotiated_price (SPEC-047).

`active_negotiated_price` lazily imports `payment.payment_state.get_pending_payment`
and `cache.redis_client` inside the function body, so both re-resolve at call
time. The in-memory Redis fake (see conftest `_flush_in_memory_redis`) is the
seam here — seed `payment:{u}:{i}` (pending link) and `negotiated_price:{u}:{i}`
(agent's cached quote) directly.
"""

import json

from cache import redis_client
from payment.pricing import active_negotiated_price


def _seed_pending(user_id, item_id, agreed_price):
    redis_client.setex(
        f"payment:{user_id}:{item_id}",
        3600,
        json.dumps({"user_id": user_id, "item_id": item_id, "agreed_price": agreed_price}),
    )


def test_returns_none_when_nothing_is_negotiated():
    assert active_negotiated_price("u1", "i1") is None


def test_returns_none_for_missing_ids():
    assert active_negotiated_price(None, "i1") is None
    assert active_negotiated_price("u1", None) is None


def test_reads_the_agents_cached_counter_from_redis():
    redis_client.setex("negotiated_price:u1:i1", 3600, "820.0")

    assert active_negotiated_price("u1", "i1") == 820.0


def test_reads_a_pending_payment_links_locked_price():
    _seed_pending("u1", "i1", 750.0)

    assert active_negotiated_price("u1", "i1") == 750.0


def test_lowest_live_quote_wins_when_both_exist():
    """A locked pending link at RM800 and a fresher cached counter at RM850 —
    the buyer pays the lowest price they have actually been quoted."""
    _seed_pending("u1", "i1", 800.0)
    redis_client.setex("negotiated_price:u1:i1", 3600, "850.0")

    assert active_negotiated_price("u1", "i1") == 800.0


def test_is_scoped_per_user_and_item():
    redis_client.setex("negotiated_price:u1:i1", 3600, "500.0")

    assert active_negotiated_price("u2", "i1") is None
    assert active_negotiated_price("u1", "i2") is None
