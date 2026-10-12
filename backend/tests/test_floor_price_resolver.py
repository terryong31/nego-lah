"""SPEC-105 — one floor-price resolver, fail-closed when the seller sets none.

`min_price` is nullable and the admin form leaves it out when blank. Before this
spec, `evaluate_offer` did `float(item.get("min_price", listed * 0.7))`: the row
always carries the key, so a NULL floor reached `float(None)` and every price
turn on that item raised. Checkout meanwhile read an unset floor as the listed
price, so the two disagreed even where neither crashed.
"""

from unittest.mock import MagicMock

import pytest

from conftest import make_supabase_result
from domains.catalog import CatalogService
from domains.negotiation import context
from domains.negotiation.tools.negotiation import evaluate_offer
from domains.negotiation.tools.payment import create_checkout_link

# --- the resolver -------------------------------------------------------------


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"price": 100, "min_price": 80}, 80.0),
        ({"price": 100, "min_price": None}, 100.0),
        ({"price": 100}, 100.0),
        ({"price": 100, "min_price": 0}, 100.0),
        ({"price": 100, "min_price": 150}, 100.0),
    ],
    ids=["set", "null", "missing", "zero", "above-listing"],
)
def test_floor_price_fails_closed_to_the_listing(row, expected):
    assert CatalogService.floor_price(row) == expected


# --- the call sites -----------------------------------------------------------


@pytest.fixture(autouse=True)
def _ctx():
    context.set_context(user_id="buyer-1", item_id="item-1")
    context.pending_discount.set(None)
    yield
    context.set_context(user_id=None, item_id=None)
    context.pending_discount.set(None)


NO_FLOOR = {"id": "item-1", "name": "Desk lamp", "price": 100.0, "min_price": None, "status": "available"}


def test_an_unset_floor_no_longer_crashes_the_offer_tool(fake_supabase, patch_supabase, monkeypatch):
    patch_supabase("core.connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [NO_FLOOR]
    )
    monkeypatch.setattr("domains.billing.pricing.active_negotiated_price", lambda uid, iid: None)

    result = evaluate_offer.func(item_id="item-1", offered_price=75.0)

    # No floor set = no discount authorised: the agent holds at the listing.
    assert result.startswith("REJECT_FLOOR")
    assert context.pending_discount.get() is None


def test_checkout_reads_an_unset_floor_the_same_way(fake_supabase, patch_supabase, monkeypatch, fake_stripe):
    patch_supabase("core.connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[NO_FLOOR]
    )
    monkeypatch.setattr("domains.billing.payment_state.get_pending_payment", lambda uid, iid: None)
    monkeypatch.setattr("domains.billing.pricing.active_negotiated_price", lambda uid, iid: None)

    result = create_checkout_link.func(item_id="item-1", agreed_price=75.0)

    assert "PRICE VALIDATION FAILED" in result
    fake_stripe.PaymentLink.create.assert_not_called()
