"""SPEC-089 — money cannot leave below a price the server actually offered.

`create_checkout_link` enforced `agreed_price >= min_price`. That answers "is
this above the absolute minimum?" — not "is this a price we agreed to?". The two
come apart the moment the model invents a discount. Observed, with the SPEC-087
trace showing no tool ran on the turn:

    [human] can you do RM1800?
    [ai]    tool_calls=None
            "RM1800 is still a bit too low … I can offer it at RM2300."

The listing is RM2599 with a RM2000 floor, so RM1800 is BELOW the floor and the
authorised answer was no counter at all. RM2300 cleared `min_price` and would
have been charged.
"""

from unittest.mock import MagicMock

import pytest

from domains.negotiation import context
from domains.negotiation.tools.payment import create_checkout_link

# The real listing from the observed conversation.
LAPTOP = {"id": "item-1", "name": "ASUS TUF Gaming A15", "price": 2599.0, "min_price": 2000.0, "status": "available"}


@pytest.fixture(autouse=True)
def _ctx():
    context.set_context(user_id="buyer-1", item_id="item-1")
    yield
    context.set_context(user_id=None, item_id=None)


@pytest.fixture
def checkout(monkeypatch, fake_supabase, patch_supabase, fake_stripe):
    patch_supabase("core.connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[LAPTOP])
    monkeypatch.setattr("domains.billing.payment_state.get_pending_payment", lambda uid, iid: None)
    monkeypatch.setattr("domains.billing.payment_state.store_pending_payment", lambda **kw: None)
    fake_stripe.Product.create.return_value = MagicMock(id="prod_1")
    fake_stripe.Price.create.return_value = MagicMock(id="price_1")
    fake_stripe.PaymentLink.create.return_value = MagicMock(id="pl_1", url="https://buy.stripe.com/x")

    def _run(agreed_price, standing=None):
        monkeypatch.setattr("domains.billing.pricing.active_negotiated_price", lambda uid, iid: standing)
        return create_checkout_link.func(item_id="item-1", agreed_price=agreed_price)

    return _run


# ---------------------------------------------------------------------------
# S1 — the observed case
# ---------------------------------------------------------------------------


def test_an_invented_discount_is_refused_even_though_it_clears_the_floor(checkout):
    result = checkout(2300.0, standing=None)

    assert "NOT AUTHORISED" in result
    assert "buy.stripe.com" not in result


# ---------------------------------------------------------------------------
# S2-S4 — the authorised path still works
# ---------------------------------------------------------------------------


def test_a_committed_counter_is_checkout_able_at_exactly_that_price(checkout):
    result = checkout(2449.0, standing=2449.0)

    assert "Payment link created" in result


def test_undercutting_a_committed_counter_is_refused(checkout):
    result = checkout(2100.0, standing=2449.0)

    assert "NOT AUTHORISED" in result


def test_paying_more_than_the_standing_price_is_fine(checkout):
    assert "Payment link created" in checkout(2599.0, standing=2449.0)


def test_full_price_with_no_negotiation_is_fine(checkout):
    """Nothing negotiated means the standing price is the listing."""
    assert "Payment link created" in checkout(2599.0, standing=None)


# ---------------------------------------------------------------------------
# S5/S6 — the floor check is untouched, and nothing is disclosed
# ---------------------------------------------------------------------------


def test_a_below_floor_price_still_fails_the_original_check(checkout):
    """The floor check runs first, so its wording and its silence are unchanged."""
    result = checkout(1500.0, standing=None)

    assert "PRICE VALIDATION FAILED" in result
    assert "2000" not in result


def test_the_refusal_names_neither_the_floor_nor_the_standing_price(checkout):
    result = checkout(2300.0, standing=2449.0)

    assert "2000" not in result
    assert "2449" not in result
    assert "2599" not in result


def test_the_refusal_tells_the_agent_what_to_do_instead(checkout):
    assert "evaluate_offer" in checkout(2300.0, standing=None)


# ---------------------------------------------------------------------------
# S7 — a resolver failure falls back to the listing rather than opening up
# ---------------------------------------------------------------------------


def test_a_resolver_failure_holds_to_the_listed_price(checkout, monkeypatch):
    def boom(_uid, _iid):
        raise RuntimeError("redis down")

    monkeypatch.setattr("domains.billing.pricing.active_negotiated_price", boom)
    result = create_checkout_link.func(item_id="item-1", agreed_price=2300.0)

    assert "NOT AUTHORISED" in result
