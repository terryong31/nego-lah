"""SPEC-083 — the scenarios' item has to actually reach the agent.

`scenario.item` was inert data: its id is not a UUID, so every lookup raised and
`evaluate_offer` returned "item not found". These hold the stub that fixes it,
including the property that matters — with the stub in place the tool reaches a
real verdict instead of the not-found string.
"""

import domains.negotiation.bot as bot
from domains.negotiation import context
from domains.negotiation.tools.negotiation import evaluate_offer
from evals.fixtures import item_row, scenario_item
from evals.scenarios import CASIO


def test_item_row_carries_the_floor_and_the_listed_price():
    row = item_row(CASIO)
    assert row["price"] == CASIO["price"]
    assert row["min_price"] == CASIO["min_price"]
    assert row["min_price"] < row["price"], "a floor above the listed price cannot be negotiated to"


def test_the_prompt_context_sees_the_scenario_item():
    with scenario_item(CASIO):
        assert bot.get_item_details_for_context(CASIO["id"])["name"] == CASIO["name"]


def test_evaluate_offer_reaches_a_verdict_instead_of_item_not_found():
    """The bug in one assertion: without the stub this returns
    "Cannot evaluate - item not found." for every scenario."""
    context.pending_discount.set(None)
    with scenario_item(CASIO):
        result = evaluate_offer.func(item_id=CASIO["id"], offered_price=170.0)

    assert "not found" not in result.lower()
    assert any(verb in result for verb in ("ACCEPT", "COUNTER", "HOLD", "REJECT_FLOOR"))


def test_an_offer_below_the_floor_is_not_accepted():
    context.pending_discount.set(None)
    with scenario_item(CASIO):
        result = evaluate_offer.func(item_id=CASIO["id"], offered_price=CASIO["min_price"] - 50)

    assert "REJECT_FLOOR" in result or "HOLD" in result


def test_the_stub_is_removed_on_exit():
    with scenario_item(CASIO):
        pass
    assert bot.get_item_details_for_context.__module__ == "domains.negotiation.bot"


def test_unused_query_builders_chain_instead_of_raising():
    """`ConversationMemory.get_history` calls `.order()`. Spelling out only the
    methods `evaluate_offer` uses made the stub raise on every turn, which the
    memory layer then logged as an error twelve times a run."""
    from evals.fixtures import _Client

    client = _Client([{"id": "x"}])
    query = client.table("items").select("*").eq("id", "x").order("id").limit(5)

    assert query.execute().data == [{"id": "x"}]


def test_non_item_tables_return_nothing():
    """An orders or checkout scenario must not be handed a pocket computer."""
    from evals.fixtures import _Client

    assert _Client([{"id": "x"}]).table("orders").select("*").execute().data == []


def test_every_client_the_agent_tools_reach_for_is_stubbed():
    """One scenario errored with `invalid input syntax for type uuid` because
    The agent's item reads go through `CatalogService` and its order reads
    through `BillingService`; both bind their clients at module level, so
    neither is covered by patching `core.connector.admin_supabase` alone."""
    import core.connector as connector
    import domains.billing.services as billing_services

    with scenario_item(CASIO):
        assert connector.admin_supabase.table("items").select("*").execute().data
        assert connector.user_supabase.table("items").select("*").execute().data
        assert billing_services.admin_supabase.table("orders").select("*").execute().data == []
