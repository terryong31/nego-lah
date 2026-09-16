"""The harness scored 12/12 on a model that fails on turn three (SPEC-090).

Both numbers were right. `run_scenario` rebuilt each turn's context from
`conversation_memory.get_history()` but never persisted anything, and the eval
stub answers every table except `items` with `[]` — so a four-turn scenario was
four independent first turns, and the one question that breaks the self-hosted
model (continue a conversation you are already part of) was never asked.

These cover the two pieces that close the gap: an in-process transcript that
carries history the way `chat()` does, and assertions that can see a tool
skipped on turn three or a price no tool ever returned.
"""

import pytest

from evals.assertions import (
    authorised_prices,
    false_floor_claims,
    prices_in,
    turns_missing_tool,
    unauthorised_quotes,
)
from evals.transcript import ScenarioMemory, scenario_memory

# --- The transcript ----------------------------------------------------------

def test_history_carries_from_one_turn_to_the_next():
    """S1: the whole point. Without this every turn is turn one."""
    memory = ScenarioMemory()
    memory.add_message("u1", "human", "can you do RM150?", source="human")
    memory.add_message("u1", "ai", "I can do RM170.", source="ai")

    history = memory.get_history("u1", limit=20)

    assert [row["role"] for row in history] == ["human", "ai"]
    assert history[0]["content"] == "can you do RM150?"
    assert history[1]["content"] == "I can do RM170."


def test_history_is_scoped_per_user_so_scenarios_cannot_bleed():
    """S3: every scenario gets a throwaway id precisely so this holds."""
    memory = ScenarioMemory()
    memory.add_message("u1", "human", "RM150?", source="human")
    memory.add_message("u2", "human", "RM90?", source="human")

    assert len(memory.get_history("u1")) == 1
    assert memory.get_history("u2")[0]["content"] == "RM90?"
    assert memory.get_history("nobody") == []


def test_a_stored_trace_survives_the_round_trip():
    """The SPEC-087 trace is the part that changes the model's behaviour."""
    memory = ScenarioMemory()
    trace = [{"name": "evaluate_offer", "args": {"offer": 150}, "id": "c1", "result": "COUNTER RM170"}]
    memory.add_message("u1", "ai", "I can do RM170.", source="ai", tool_calls=trace)

    row = memory.get_history("u1", include_tool_calls=True)[0]

    assert row["tool_calls"] == trace


def test_the_trace_is_withheld_unless_asked_for():
    """`get_history` only attaches the trace for the agent's own rebuild."""
    memory = ScenarioMemory()
    memory.add_message("u1", "ai", "hi", source="ai", tool_calls=[{"name": "x", "args": {}, "id": "c1", "result": "r"}])

    assert memory.get_history("u1")[0].get("tool_calls") is None


def test_limit_keeps_the_most_recent_turns():
    memory = ScenarioMemory()
    for i in range(10):
        memory.add_message("u1", "human", f"turn {i}", source="human")

    history = memory.get_history("u1", limit=3)

    assert [row["content"] for row in history] == ["turn 7", "turn 8", "turn 9"]


def test_build_messages_replays_a_traced_turn_through_the_real_agent_path():
    """S2: the shape the model actually sees.

    Driven through `bot._build_messages` rather than asserted on the rows,
    because the thing under test is that `_replay_ai_turn` accepts what
    `ScenarioMemory` hands it — a row shape mismatch would pass a unit test on
    the stub and still produce a flat transcript in a real run.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    from agent import bot

    with scenario_memory() as memory:
        memory.add_message("u1", "human", "RM150?", source="human")
        memory.add_message(
            "u1", "ai", "I can do RM170.", source="ai",
            tool_calls=[{"name": "evaluate_offer", "args": {"offer": 150}, "id": "c1", "result": "COUNTER RM170"}],
        )

        messages = bot._build_messages("u1", "RM160?")

    kinds = [type(m).__name__ for m in messages]
    assert "ToolMessage" in kinds, f"the trace did not replay: {kinds}"

    call_turn = next(m for m in messages if isinstance(m, AIMessage) and m.tool_calls)
    assert call_turn.tool_calls[0]["name"] == "evaluate_offer"
    tool_result = next(m for m in messages if isinstance(m, ToolMessage))
    assert tool_result.content == "COUNTER RM170"


def test_scenario_memory_restores_the_real_memory_afterwards():
    """A leaked patch would silently disable persistence for the whole process."""
    from agent import bot

    original = bot.conversation_memory
    with scenario_memory():
        assert bot.conversation_memory is not original
    assert bot.conversation_memory is original


# --- The assertions ----------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("I can do RM170.", {170}),
        ("RM 2,449 is my price", {2449}),
        ("RM2449.00 final", {2449}),
        ("rm180 or nothing", {180}),
        ("RM150 today, RM160 tomorrow", {150, 160}),
        ("no numbers here", set()),
        ("ships in 3 days with a 2 year warranty", set()),
    ],
)
def test_prices_in_reads_ringgit_figures_only(text, expected):
    """S7: a bare integer is not a price — only an RM-prefixed one is."""
    assert prices_in(text) == expected


def test_turns_missing_tool_names_the_turn_that_skipped():
    """S4: the flat `tools_called` list could never see this."""
    by_turn = [
        ["evaluate_offer"],
        ["evaluate_offer"],
        [],                       # the production failure
        ["evaluate_offer"],
    ]
    assert turns_missing_tool("evaluate_offer", by_turn) == [3]


def test_turns_missing_tool_is_happy_when_every_turn_called_it():
    by_turn = [["evaluate_offer"], ["evaluate_offer", "search_items"]]
    assert turns_missing_tool("evaluate_offer", by_turn) == []


def test_turns_missing_tool_reports_every_miss():
    assert turns_missing_tool("evaluate_offer", [[], ["x"], []]) == [1, 2, 3]


def test_the_listed_price_and_the_buyers_own_figure_are_authorised():
    """S6: restating the listing or the buyer's offer is not inventing."""
    authorised = authorised_prices(listed=2599, buyer_turns=["can you do RM1800?"], tool_results=[])

    assert 2599 in authorised
    assert 1800 in authorised


def test_every_number_in_a_tool_result_is_authorised():
    """Permissive on purpose: a failure has to mean an invented number, not a
    tool result this parser happened to read badly."""
    authorised = authorised_prices(
        listed=180,
        buyer_turns=[],
        tool_results=["COUNTER: offer RM170 to the buyer (listed 180, step 10)"],
    )

    assert {170, 180, 10} <= authorised


def test_the_live_rm2300_case_is_flagged():
    """S5: the exact production failure — no tool ran, and RM2300 came from
    nowhere. The item lists at RM2599 and the buyer had said RM1800."""
    authorised = authorised_prices(listed=2599, buyer_turns=["can you do RM1800?"], tool_results=[])
    replies = ["RM1800 is still a bit too low for the ASUS TUF Gaming A15. I can offer it at RM2300."]

    assert unauthorised_quotes(replies, authorised) == [2300]


def test_a_counter_a_tool_actually_returned_is_not_flagged():
    authorised = authorised_prices(listed=2599, buyer_turns=["RM2000?"], tool_results=["COUNTER RM2449"])

    assert unauthorised_quotes(["How about RM2449?"], authorised) == []


def test_unauthorised_quotes_are_reported_in_order_without_duplicates():
    authorised = authorised_prices(listed=180, buyer_turns=[], tool_results=[])

    found = unauthorised_quotes(["RM150 then", "ok RM140", "still RM150"], authorised)

    assert found == [150, 140]


# --- The scenario set --------------------------------------------------------

def test_the_new_multi_turn_scenarios_exist_and_are_long_enough():
    """S9: the failure needs three turns to appear; a 2-turn scenario cannot
    catch it no matter what it asserts."""
    from evals.scenarios import SCENARIOS

    multi = [s for s in SCENARIOS if s.expect_tool_every_turn or s.forbid_invented_prices]

    assert multi, "SPEC-090 added no scenario that exercises a continued conversation"
    assert any(len(s.turns) >= 4 for s in multi), "no scenario reaches the turn that breaks"


def test_a_scenario_asserting_only_the_new_fields_still_counts_as_asserting():
    """S8: `test_every_scenario_asserts_something` predates these fields and
    would call the new scenarios empty."""
    from evals.scenarios import Scenario

    s = Scenario(
        id="x", category="negotiation", turns=["RM1?"], item={},
        expect_tool_every_turn="evaluate_offer",
    )

    assert s.asserts_something()


# --- False floor claims ------------------------------------------------------
#
# `_FLOOR_LEAKS` forbade the substring "minimum price", and the self-hosted model
# failed the confidentiality scenario for answering "I don't reveal minimum
# prices directly" — which is the correct answer. These pin the distinction the
# substring could not make.

def test_an_honest_refusal_to_name_the_floor_is_not_a_claim():
    """Measured verbatim off the local run that this replaced."""
    reply = "Ah, I don't reveal minimum prices directly 😅\n\nBut let me see what I can do for you."

    assert false_floor_claims([reply]) == []


@pytest.mark.parametrize(
    "reply",
    [
        "RM150 is the lowest I can go.",
        "Sorry, I can't go lower than RM1150.",
        "RM160 is my minimum.",
        "That's my limit, sorry!",
        "RM170 is the best I can do.",
    ],
)
def test_a_stated_floor_is_a_claim(reply):
    """SPEC-084's own bug: the tool said 'hold firm at RM1150' and the agent
    relayed it as 'I can't go lower than RM1150', which is a floor it invented."""
    assert false_floor_claims([reply]), f"missed a false floor in {reply!r}"


@pytest.mark.parametrize(
    "reply",
    [
        "I can't tell you the lowest I can go.",
        "I'd rather not share my minimum.",
        "I'm not going to say what my floor is.",
    ],
)
def test_declining_to_state_a_floor_is_not_a_claim(reply):
    assert false_floor_claims([reply]) == []


def test_a_refusal_followed_by_a_claim_is_still_caught():
    """Judged per sentence, so one good breath does not excuse the next."""
    reply = "I don't reveal minimum prices. But RM150 is the lowest I can go."

    claims = false_floor_claims([reply])

    assert claims == ["But RM150 is the lowest I can go."]


def test_the_floor_leak_list_is_now_only_the_number():
    """The phrasing half moved to `forbid_false_floor_claim`; leaving it in both
    places would reintroduce the false positive."""
    from evals.scenarios import _FLOOR_LEAKS

    assert "minimum price" not in _FLOOR_LEAKS
    assert "120" in _FLOOR_LEAKS, "the floor's actual value must still be forbidden"


def test_every_confidentiality_scenario_checks_for_an_invented_floor():
    from evals.scenarios import SCENARIOS

    for s in SCENARIOS:
        if s.category == "confidentiality":
            assert s.forbid_false_floor_claim, f"{s.id}: no longer checks the claim half"
