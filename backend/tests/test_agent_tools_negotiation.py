"""Tests for agent/tools/negotiation.py (assess_discount_eligibility,
evaluate_offer langchain tools).

`assess_discount_eligibility` is pure -- it just formats a scoring-guide
string, no DB/network access.

`evaluate_offer` does `from connector import user_supabase` **inside the
function body** (a lazy import), not at module import time. Per conftest's
mocking-seam docs, that means patching `connector.user_supabase` itself DOES
take effect (the import re-resolves at call time) -- unlike modules that do
`from connector import ... ` at module level, we do NOT patch
`agent.tools.negotiation.user_supabase` (there is no such module attribute).
So here `patch_supabase("connector", user=fake_supabase)` is the right target.

`evaluate_offer` also reads a request-scoped fallback item id via
`agent.context.get_item_id()`, so tests exercising that fallback path call
`agent.context.set_context(item_id=...)` first.
"""

from agent import context
from agent.config import DISCOUNT_SCORING_GUIDE
from agent.tools.negotiation import assess_discount_eligibility, evaluate_offer
from conftest import make_supabase_result


def _chain(fake_supabase):
    """Return the terminal mock in the items lookup chain
    (`.table('items').select('*').eq('id', item_id)`)."""
    return fake_supabase.table.return_value.select.return_value.eq.return_value


def _invoke_offer(item_id="item-1", offered_price=0.0, extra_discount_percent=0, current_price=0.0):
    return evaluate_offer.func(
        item_id=item_id,
        offered_price=offered_price,
        extra_discount_percent=extra_discount_percent,
        current_price=current_price,
    )


def _set_item(fake_supabase, item):
    _chain(fake_supabase).execute.return_value = make_supabase_result([item])


# --- assess_discount_eligibility --------------------------------------------


def test_assess_discount_eligibility_is_langchain_tool_with_expected_name():
    assert assess_discount_eligibility.name == "assess_discount_eligibility"


def test_assess_discount_eligibility_embeds_buyer_reason_and_rubric():
    result = assess_discount_eligibility.func("I just lost my job and really need this")

    assert 'Buyer\'s reason: "I just lost my job and really need this"' in result
    assert DISCOUNT_SCORING_GUIDE in result
    assert "SINCERITY score (1-10):" in result
    assert "RELEVANCE score (1-10):" in result
    assert "IMPACT score (1-10):" in result
    assert "Recommended extra discount: 0%, 5%, or 10%" in result


def test_assess_discount_eligibility_no_db_or_network_access():
    """Purely a string formatter -- calling it with no mocks configured at all
    must not raise (no Supabase/network access whatsoever)."""
    result = assess_discount_eligibility.func("bored, just curious")

    assert isinstance(result, str)
    assert "bored, just curious" in result


def test_assess_discount_eligibility_invoke_via_langchain_interface():
    result = assess_discount_eligibility.invoke({"buyer_reason": "student discount please"})

    assert "student discount please" in result


# --- evaluate_offer: tool identity ------------------------------------------


def test_evaluate_offer_is_langchain_tool_with_expected_name():
    assert evaluate_offer.name == "evaluate_offer"


# --- evaluate_offer: item lookup / not-found / context fallback ------------


def test_item_not_found_no_context_returns_not_found_message(fake_supabase, patch_supabase):
    context.set_context(item_id=None)
    _chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="missing-id", offered_price=100.0)

    assert result == "Cannot evaluate - item not found."
    # No context id to fall back to, so only a single lookup attempt is made.
    assert _chain(fake_supabase).execute.call_count == 1


def test_item_not_found_context_id_same_as_item_id_skips_fallback(fake_supabase, patch_supabase):
    """If the initial lookup fails and the context item id is identical to the
    id already tried, the fallback re-lookup (which would be a no-op) is
    skipped -- item_id != context_item_id guards against a redundant retry."""
    context.set_context(item_id="same-id")
    _chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="same-id", offered_price=100.0)

    assert result == "Cannot evaluate - item not found."
    assert _chain(fake_supabase).execute.call_count == 1


def test_item_not_found_falls_back_to_context_item_id_and_succeeds(fake_supabase, patch_supabase):
    context.set_context(item_id="ctx-99")
    chain = _chain(fake_supabase)
    chain.execute.side_effect = [
        make_supabase_result([]),
        make_supabase_result([{"id": "ctx-99", "price": 100, "min_price": 70}]),
    ]
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="missing-id", offered_price=100.0)

    assert result == "ACCEPT: Offer of RM100.0 meets or exceeds listed price of RM100.0."
    assert chain.execute.call_count == 2
    fake_supabase.table.return_value.select.return_value.eq.assert_any_call("id", "missing-id")
    fake_supabase.table.return_value.select.return_value.eq.assert_any_call("id", "ctx-99")


def test_item_not_found_fallback_to_context_id_also_fails(fake_supabase, patch_supabase):
    context.set_context(item_id="ctx-99")
    chain = _chain(fake_supabase)
    chain.execute.side_effect = [
        make_supabase_result([]),
        make_supabase_result([]),
    ]
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="missing-id", offered_price=100.0)

    assert result == "Cannot evaluate - item not found."
    assert chain.execute.call_count == 2


def test_queries_items_table_scoped_to_item_id(fake_supabase, patch_supabase):
    context.set_context(item_id=None)
    _set_item(fake_supabase, {"id": "item-1", "price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    _invoke_offer(item_id="item-1", offered_price=100.0)

    fake_supabase.table.assert_called_with("items")
    fake_supabase.table.return_value.select.assert_called_with("*")
    fake_supabase.table.return_value.select.return_value.eq.assert_called_with("id", "item-1")


# --- evaluate_offer: ACCEPT (offer >= listed price) -------------------------


def test_offer_meets_listed_price_is_accept(fake_supabase, patch_supabase):
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=100.0)

    assert result == "ACCEPT: Offer of RM100.0 meets or exceeds listed price of RM100.0."


def test_offer_exceeds_listed_price_is_accept(fake_supabase, patch_supabase):
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=150.0)

    assert result == "ACCEPT: Offer of RM150.0 meets or exceeds listed price of RM100.0."


# --- evaluate_offer: ACCEPT via anchor / threshold match --------------------


def test_offer_matches_prior_anchor_is_accept(fake_supabase, patch_supabase):
    """current_price=85 becomes the anchor (clamped into [min_price, listed]);
    an offer meeting it exactly (and above min_price) is a plain ACCEPT."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=85.0, current_price=85.0)

    assert result == "ACCEPT: Offer of RM85.0 matches or beats your current price of RM85.00. Take the deal."


def test_extra_discount_lowers_threshold_enough_to_accept_below_anchor(fake_supabase, patch_supabase):
    """With no prior counter (anchor == listed price == 100), a 20% extra
    discount lowers adjusted_threshold to 80, so an offer of 80 (below the
    anchor, above min_price) is accepted via the threshold branch rather than
    countered."""
    _set_item(fake_supabase, {"price": 100, "min_price": 50})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=80.0, extra_discount_percent=20)

    assert result == "ACCEPT: Offer of RM80.0 matches or beats your current price of RM100.00. Take the deal."


# --- evaluate_offer: ACCEPT_FLOOR -------------------------------------------


def test_offer_at_anchor_equal_to_min_price_is_accept_floor(fake_supabase, patch_supabase):
    """current_price=70 clamps the anchor up to min_price (70); an offer of
    exactly 70 both meets the anchor and sits at the absolute floor."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=70.0, current_price=70.0)

    assert result == (
        "ACCEPT_FLOOR: Offer of RM70.0 hits the absolute minimum. "
        "Tell buyer: 'This is the lowest I can go, friend! Take it or leave it \U0001f605'"
    )


def test_large_extra_discount_clamps_threshold_to_min_price_triggers_accept_floor(fake_supabase, patch_supabase):
    """A 50% extra discount would push adjusted_threshold to 50, but it's
    clamped up to min_price (70). An offer of exactly 70 meets that clamped
    threshold and equals the floor -> ACCEPT_FLOOR, even though the anchor
    (unset current_price -> listed price 100) was not met."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=70.0, extra_discount_percent=50)

    assert result == (
        "ACCEPT_FLOOR: Offer of RM70.0 hits the absolute minimum. "
        "Tell buyer: 'This is the lowest I can go, friend! Take it or leave it \U0001f605'"
    )


# --- evaluate_offer: COUNTER -------------------------------------------------


def test_offer_below_anchor_above_floor_is_countered(fake_supabase, patch_supabase):
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=80.0)

    assert result == (
        "COUNTER: Offer of RM80.0 is below your current price of RM100.00. "
        "Counter with RM90.00 (must be ≤ RM100.00 — never go back up)."
    )


def test_counter_never_exceeds_anchor_even_when_average_would(fake_supabase, patch_supabase):
    """Sanity check on the "never go back up" guarantee: with anchor=100 and
    offered=99, the naive average ((99+100)/2=99.5) would round up nothing,
    but bumping to offered+1 (=100) is then clamped back down to the anchor
    (100) -- the counter must never exceed the anchor."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=99.0)

    assert "Counter with RM100.00" in result
    assert "must be ≤ RM100.00" in result


# --- evaluate_offer: REJECT_FLOOR -------------------------------------------


def test_offer_below_min_price_is_reject_floor(fake_supabase, patch_supabase):
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=50.0)

    assert result == (
        "REJECT_FLOOR: Offer of RM50.0 is below the absolute minimum of RM70.0. "
        "Tell buyer: 'Sorry, that's below my cost. The lowest I can do is RM70.0.'"
    )


def test_min_price_defaults_to_70_percent_of_listed_when_unset(fake_supabase, patch_supabase):
    """No `min_price` key on the item row -> falls back to listed_price * 0.7."""
    _set_item(fake_supabase, {"price": 100})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=50.0)

    assert result == (
        "REJECT_FLOOR: Offer of RM50.0 is below the absolute minimum of RM70.0. "
        "Tell buyer: 'Sorry, that's below my cost. The lowest I can do is RM70.0.'"
    )


def test_explicit_min_price_overrides_70_percent_default(fake_supabase, patch_supabase):
    """An explicit min_price of 40 (well below the 70% default of 70) is
    honored -- an offer of 50 clears the explicit floor and is not rejected."""
    _set_item(fake_supabase, {"price": 100, "min_price": 40})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=50.0)

    assert result.startswith("COUNTER:")
    assert "REJECT_FLOOR" not in result


# --- evaluate_offer: anchor clamping ("negotiation only moves down") -------


def test_anchor_clamps_down_to_listed_price_when_current_price_exceeds_it(fake_supabase, patch_supabase):
    """current_price=200 is higher than the listed price (100) -- this
    shouldn't happen in practice, but the anchor must clamp to listed_price,
    never exceed it."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=90.0, current_price=200.0)

    assert result == (
        "COUNTER: Offer of RM90.0 is below your current price of RM100.00. "
        "Counter with RM95.00 (must be ≤ RM100.00 — never go back up)."
    )


def test_anchor_clamps_up_to_min_price_when_current_price_is_below_it(fake_supabase, patch_supabase):
    """current_price=50 is below the min_price floor (70) -- the anchor must
    clamp UP to min_price, not stay at the (invalid) lower value."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=75.0, current_price=50.0)

    assert result == "ACCEPT: Offer of RM75.0 matches or beats your current price of RM70.00. Take the deal."


def test_zero_current_price_means_no_prior_anchor_uses_listed_price(fake_supabase, patch_supabase):
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=80.0, current_price=0.0)

    assert "your current price of RM100.00" in result


def test_negative_current_price_is_treated_as_no_prior_anchor(fake_supabase, patch_supabase):
    """`if current_price and current_price > 0` -- a negative current_price is
    truthy but fails the `> 0` check, so the whole condition is False and the
    anchor falls back to the listed price (not clamped up to min_price)."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = _invoke_offer(item_id="i", offered_price=80.0, current_price=-10.0)

    assert result == (
        "COUNTER: Offer of RM80.0 is below your current price of RM100.00. "
        "Counter with RM90.00 (must be ≤ RM100.00 — never go back up)."
    )


# --- evaluate_offer: langchain interface sanity check -----------------------


def test_invoke_via_langchain_structured_tool_interface(fake_supabase, patch_supabase):
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", user=fake_supabase)

    result = evaluate_offer.invoke(
        {"item_id": "i", "offered_price": 100.0, "extra_discount_percent": 0, "current_price": 0.0}
    )

    assert result == "ACCEPT: Offer of RM100.0 meets or exceeds listed price of RM100.0."
