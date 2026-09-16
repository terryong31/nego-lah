"""SPEC-084 — a concession, once made, stays made.

`evaluate_offer` anchored its counter to `current_price`, an argument the MODEL
was asked to fill with "the lowest price you have already offered". Across a
full SPEC-083 eval run it arrived as 0 on 13 calls out of 13, so the anchor fell
back to the listed price every turn and the agent re-quoted the list price after
having come down:

    Buyer: RM120?        -> Seller: "Best I can do is RM165."
    Buyer: actually 110? -> Seller: "RM180 is already a fair price."

The server already knows the standing price — `evaluate_offer` writes every
committed counter to `negotiated_price:{user}:{item}`, and
`payment.pricing.active_negotiated_price` is what the item card and checkout
already read it back with. These tests hold the rule that the tool now reads it
back too, and that a model argument can only ever lower the anchor, never raise it.
"""

from unittest.mock import patch

import pytest

from agent import context
from agent.tools.negotiation import evaluate_offer
from conftest import make_supabase_result

ITEM = {"id": "i", "name": "Casio", "price": 180.0, "min_price": 120.0}


@pytest.fixture(autouse=True)
def _reset_context_vars():
    user_token = context.current_user_id.set(None)
    item_token = context.current_item_id.set(None)
    context.pending_discount.set(None)
    try:
        yield
    finally:
        context.current_user_id.reset(user_token)
        context.current_item_id.reset(item_token)
        context.pending_discount.set(None)


@pytest.fixture
def item(fake_supabase, patch_supabase):
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([ITEM])
    )
    context.set_context(user_id="buyer-1", item_id="i")
    return fake_supabase


def _offer(price, current_price=0.0):
    return evaluate_offer.func(item_id="i", offered_price=price, current_price=current_price)


def _standing(value):
    """Stub the server's record of what this buyer was last quoted."""
    return patch("payment.pricing.active_negotiated_price", lambda _u, _i: value)


# ---------------------------------------------------------------------------
# S1 — the production bug, in one test
# ---------------------------------------------------------------------------

def test_a_below_floor_lowball_holds_the_conceded_price_not_the_list_price(item):
    """The eval transcript, in one test. `current_price=0` is what the model
    actually sends; RM110 is under the RM120 floor, so this is REJECT_FLOOR —
    the branch that used to hand the model no number at all, leaving it to
    improvise RM180 after having already conceded RM165."""
    with _standing(165.0):
        result = _offer(110.0, current_price=0.0)

    assert result.startswith("REJECT_FLOOR:")
    assert "180" not in result, "re-quoted the listed price after conceding"
    assert "165" in result, "must name the price to hold, not leave it to the model"
    assert "120" not in result, "the floor itself is still never named"


def test_the_agent_is_never_told_to_go_back_up(item):
    with _standing(165.0):
        result = _offer(150.0, current_price=0.0)

    assert "COUNTER" in result or "HOLD" in result
    quoted = [float(n) for n in __import__("re").findall(r"RM(\d+(?:\.\d+)?)", result)]
    assert quoted and max(quoted) <= 165.0


# ---------------------------------------------------------------------------
# S2/S3 — the model argument can only lower the anchor
# ---------------------------------------------------------------------------

def test_a_model_argument_above_the_standing_price_cannot_raise_the_anchor(item):
    """A hallucinated or optimistic `current_price` must not undo a concession."""
    with _standing(150.0):
        result = _offer(120.0, current_price=175.0)

    assert "175" not in result
    assert "150" in result


def test_a_model_argument_below_the_standing_price_still_wins(item):
    """The agent may have quoted lower in the same turn than the cache records."""
    with _standing(165.0):
        result = _offer(120.0, current_price=140.0)

    assert "140" in result
    assert "165" not in result


# ---------------------------------------------------------------------------
# S4/S5/S6 — fall back safely
# ---------------------------------------------------------------------------

def test_no_standing_price_behaves_exactly_as_before(item):
    with _standing(None):
        result = _offer(150.0, current_price=0.0)

    assert "180" in result, "with nothing conceded yet the anchor is the listed price"


def test_a_standing_price_below_the_floor_is_clamped_up_to_the_floor(item):
    """Nothing may drag the anchor under `min_price`, whatever the cache holds."""
    with _standing(50.0):
        result = _offer(45.0, current_price=0.0)

    assert "50" not in result
    assert "REJECT_FLOOR" in result or "HOLD" in result or "ACCEPT_FLOOR" in result


def test_a_lookup_failure_degrades_to_the_listed_price_anchor(item):
    """A Redis hiccup must not break a negotiation — `active_negotiated_price`
    is documented never to raise, but the caller does not rely on that."""
    def boom(_u, _i):
        raise RuntimeError("redis down")

    with patch("payment.pricing.active_negotiated_price", boom):
        result = _offer(150.0, current_price=0.0)

    assert "COUNTER" in result or "HOLD" in result


# ---------------------------------------------------------------------------
# S7 — meeting the standing price closes the deal
# ---------------------------------------------------------------------------

def test_an_offer_matching_the_standing_price_is_accepted(item):
    with _standing(165.0):
        result = _offer(165.0, current_price=0.0)

    assert "ACCEPT" in result


def test_the_floor_is_never_named_on_any_of_these_paths(item):
    for offered, standing in ((110.0, 165.0), (45.0, 50.0), (150.0, None)):
        with _standing(standing):
            result = _offer(offered)
        assert "120" not in result, f"floor leaked for offer {offered}"
        assert "min_price" not in result.lower()
