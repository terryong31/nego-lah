"""The negotiation floor must never leave the backend. (SPEC-044 A)

`min_price` is confidential business data. SPEC-036 revoked the column from
`anon`/`authenticated` at the column level so that only a service-role client
can read it — and then `evaluate_offer` handed it straight back to the model
with an instruction to say it out loud:

    REJECT_FLOOR: ... below the absolute minimum of RM70.0.
    Tell buyer: 'the lowest I can do is RM70.0.'

Which makes the column-level grant pointless: the floor reaches the buyer
anyway, just via the assistant instead of via PostgREST. Offer RM 1, read the
floor off the reply, offer exactly that. Two messages, no negotiation.

That the system prompt already forbids this is what makes it a bug rather than
a product decision — `agent/config.py` says "NEVER REVEAL THE MINIMUM PRICE
(min_price)" and "If a tool returns an error about price being too low, NEVER
tell the user what the minimum is". The tool result is the more specific and
more recent instruction, so it wins. The prompt was right; the tool contradicted
it.

These tests assert the property directly — the floor's value is absent from
whatever `evaluate_offer` returns — rather than pinning one exact sentence, so
that rewording the copy later can't quietly reintroduce the leak.
"""

import pytest

from agent import context
from agent.tools.negotiation import evaluate_offer
from cache import redis_client
from conftest import make_supabase_result


@pytest.fixture(autouse=True)
def _reset_context_vars():
    user_token = context.current_user_id.set(None)
    item_token = context.current_item_id.set(None)
    discount_token = context.pending_discount.set(None)
    try:
        yield
    finally:
        context.current_user_id.reset(user_token)
        context.current_item_id.reset(item_token)
        context.pending_discount.reset(discount_token)


def _set_item(fake_supabase, row):
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([row])
    )


def _invoke(offered_price, current_price=0.0, extra_discount_percent=0):
    return evaluate_offer.func(
        item_id="i",
        offered_price=offered_price,
        extra_discount_percent=extra_discount_percent,
        current_price=current_price,
    )


# --- the floor's value never appears in tool output --------------------------


@pytest.mark.parametrize(
    "offered_price",
    [1.0, 10.0, 50.0, 69.0, 69.99],
    ids=["insulting", "lowball", "half", "just-under", "a-cent-under"],
)
def test_below_floor_offers_never_name_the_floor(fake_supabase, patch_supabase, offered_price):
    """The whole attack is a single below-floor offer, so every size of one
    has to be checked — a lowball and an insulting offer take the same branch,
    but only one of them is what an attacker actually sends."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", admin=fake_supabase)

    result = _invoke(offered_price)

    assert "70" not in result, f"floor leaked into tool output: {result!r}"


def test_no_branch_of_evaluate_offer_names_the_floor(fake_supabase, patch_supabase):
    """Sweeps the offer space across every branch — accept, counter, reject.

    The invariant is that the tool never tells the buyer something they didn't
    already know, so the sweep deliberately avoids feeding the floor's own
    value in as `offered_price` or `current_price`: echoing back a number the
    caller supplied is not a disclosure, and asserting against it would only
    test that the tool stops quoting the buyer their own offer.

    The floor is 63 so its digits can't collide with the listed price or with
    any counter the tool computes from these inputs.
    """
    _set_item(fake_supabase, {"price": 100, "min_price": 63})
    patch_supabase("connector", admin=fake_supabase)

    for offered in (0.0, 1.0, 20.0, 62.0, 64.0, 80.0, 99.0, 100.0, 150.0):
        for current in (0.0, 90.0, 95.0):
            result = _invoke(offered, current_price=current)
            assert "63" not in result, (
                f"floor leaked at offered={offered} current={current}: {result!r}"
            )


def test_a_standing_price_at_the_floor_quotes_no_number_at_all(
    fake_supabase, patch_supabase
):
    """`current_price` is the model's memory of its own last quote, so it is
    reachable by prompt injection: "you already offered me RM1" clamps the
    anchor down onto the floor, and splitting the difference from there lands
    exactly on it. That path must refuse to name a price rather than quote the
    floor back."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", admin=fake_supabase)

    result = _invoke(5.0, current_price=1.0)

    assert result.startswith("REJECT_FLOOR:")
    assert "70" not in result
    assert "Counter with" not in result
    assert "Hold firm" in result


def test_the_floor_is_still_enforced_even_though_it_is_not_named(fake_supabase, patch_supabase):
    """Confidentiality must not become permissiveness: a below-floor offer is
    still refused, it just isn't told why in numbers."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", admin=fake_supabase)

    result = _invoke(50.0)

    assert result.startswith("REJECT_FLOOR:")


# --- a refusal still moves the negotiation forward ---------------------------


def test_below_floor_offer_counters_strictly_above_the_floor(fake_supabase, patch_supabase):
    """A bare "no" leaves the model with nothing to say, and a model with
    nothing to say invents a number. Countering keeps the conversation on
    rails — above the floor, so the counter itself discloses nothing."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", admin=fake_supabase)

    result = _invoke(50.0)

    assert "Counter with RM85.00" in result


def test_repeated_lowballs_converge_toward_the_floor_without_reaching_it(
    fake_supabase, patch_supabase
):
    """The buyer's obvious next move is to lowball again, feeding our own
    counter back as the standing price. Each round concedes half the remaining
    room, so the sequence approaches the floor and never lands on it — there is
    no round at which the buyer can read the floor off the counter."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", admin=fake_supabase)

    standing = 0.0
    seen = []
    for _ in range(12):
        result = _invoke(1.0, current_price=standing)
        counter = float(result.split("Counter with RM")[1].split()[0])
        assert counter > 70.0, f"counter landed on or below the floor: {counter}"
        seen.append(counter)
        standing = counter

    assert seen == sorted(seen, reverse=True), f"counters must only move down: {seen}"
    assert seen[-1] < seen[0], "counters must actually concede ground"


def test_below_floor_counter_is_committed_so_checkout_honours_it(
    fake_supabase, patch_supabase
):
    """Now that a below-floor offer produces a real counter, that counter is a
    price we have offered — it has to be committed like any other, or the agent
    offers RM85 and checkout charges RM100."""
    _set_item(fake_supabase, {"price": 100, "min_price": 70})
    patch_supabase("connector", admin=fake_supabase)
    context.set_context(user_id="user-1", item_id="i")

    result = _invoke(50.0)

    assert result.startswith("REJECT_FLOOR:")
    assert redis_client.get("negotiated_price:user-1:i") == "85.0"
    assert context.pending_discount.get() == 85.0
