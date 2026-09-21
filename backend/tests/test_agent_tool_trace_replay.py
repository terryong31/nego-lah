"""SPEC-087 — the transcript has to show the tool call, not just its conclusion.

`messages` stored role + content only, so a turn that ran `evaluate_offer` was
replayed as plain assistant prose. The transcript then demonstrated "buyer names
a price -> answer in prose", with no evidence a tool was ever involved, and the
self-hosted model followed the demonstration over the system prompt: after two
such turns it stopped calling the tool and reused its own last reply with the
number swapped.

Measured against the live model, same prompt, same offer, 3 samples each:

    empty history ................................ 3/3 called the tool
    two prior prose answers (what we replayed) ... 0/3
    the same turns WITH their tool calls ......... 3/3

A stronger prompt rule did not move it and neither did a synthetic exemplar, so
these tests hold the structural fix rather than a wording.
"""

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import domains.negotiation.bot as bot
from domains.negotiation.config import AGENT_TOOL_RESULT_MAX_CHARS, AGENT_TOOL_TRACE_TURNS


def _trace(name="evaluate_offer", call_id="call_1", result="COUNTER: counter with RM1110."):
    return [{"name": name, "args": {"item_id": "i", "offered_price": 1000}, "id": call_id, "result": result}]


@pytest.fixture
def memory(monkeypatch):
    fake = MagicMock()
    fake.get_history.return_value = []
    monkeypatch.setattr(bot, "conversation_memory", fake)
    return fake


# ---------------------------------------------------------------------------
# S1/S2 — a stored trace replays as the exchange that actually happened
# ---------------------------------------------------------------------------


def test_a_traced_turn_replays_call_result_then_answer(memory):
    memory.get_history.return_value = [
        {"role": "human", "content": "1000?"},
        {"role": "ai", "content": "How about RM1110?", "tool_calls": _trace()},
    ]

    messages = bot._build_messages("u1", "900?")

    assert isinstance(messages[0], HumanMessage)
    assert isinstance(messages[1], AIMessage) and messages[1].tool_calls
    assert messages[1].tool_calls[0]["name"] == "evaluate_offer"
    assert isinstance(messages[2], ToolMessage)
    assert "RM1110" in messages[2].content
    assert isinstance(messages[3], AIMessage) and messages[3].content == "How about RM1110?"


def test_every_replayed_call_has_a_matching_tool_message(memory):
    """A dangling tool call is a hard error on both providers."""
    memory.get_history.return_value = [
        {"role": "human", "content": "1000?"},
        {
            "role": "ai",
            "content": "ok",
            "tool_calls": _trace() + _trace(name="get_item_info", call_id="call_2", result="Item: X"),
        },
    ]

    messages = bot._build_messages("u1", "hi")

    called = {c["id"] for m in messages if isinstance(m, AIMessage) for c in (m.tool_calls or [])}
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    assert called == answered == {"call_1", "call_2"}


def test_a_trace_stored_as_a_json_string_still_replays(memory):
    """Some drivers hand jsonb back as text."""
    memory.get_history.return_value = [
        {"role": "ai", "content": "ok", "tool_calls": json.dumps(_trace())},
    ]

    messages = bot._build_messages("u1", "hi")

    assert any(isinstance(m, ToolMessage) for m in messages)


# ---------------------------------------------------------------------------
# S3 — everything written before this spec replays exactly as before
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "row",
    [
        {"role": "ai", "content": "hello!"},
        {"role": "ai", "content": "hello!", "tool_calls": None},
        {"role": "ai", "content": "hello!", "tool_calls": []},
    ],
    ids=["no-column", "null", "empty"],
)
def test_an_untraced_turn_replays_as_plain_prose(memory, row):
    memory.get_history.return_value = [row]

    messages = bot._build_messages("u1", "hi")

    assert not any(isinstance(m, ToolMessage) for m in messages)
    assert messages[0].content == "hello!"
    assert not messages[0].tool_calls


# ---------------------------------------------------------------------------
# S4 — only the recent turns pay for a trace
# ---------------------------------------------------------------------------


def test_only_the_most_recent_turns_carry_their_trace(memory):
    memory.get_history.return_value = [
        {"role": "ai", "content": f"turn {i}", "tool_calls": _trace(call_id=f"call_{i}")}
        for i in range(AGENT_TOOL_TRACE_TURNS + 4)
    ]

    messages = bot._build_messages("u1", "hi")

    replayed = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    assert len(replayed) == AGENT_TOOL_TRACE_TURNS
    # The newest ones, not the oldest.
    assert f"call_{AGENT_TOOL_TRACE_TURNS + 3}" in replayed
    assert "call_0" not in replayed


def test_the_agent_asks_for_traces_but_the_ui_page_does_not(memory):
    bot._build_messages("u1", "hi")

    assert memory.get_history.call_args.kwargs["include_tool_calls"] is True


# ---------------------------------------------------------------------------
# S5/S8 — extraction from a completed graph result
# ---------------------------------------------------------------------------


def test_extract_pairs_each_call_with_its_result():
    result = [
        AIMessage(content="", tool_calls=[{"name": "evaluate_offer", "args": {"offered_price": 1000}, "id": "c1"}]),
        ToolMessage(content="COUNTER: RM1110", tool_call_id="c1"),
        AIMessage(content="How about RM1110?"),
    ]

    trace = bot.extract_tool_trace(result)

    assert trace == [
        {"name": "evaluate_offer", "args": {"offered_price": 1000}, "id": "c1", "result": "COUNTER: RM1110"}
    ]


def test_a_call_whose_result_never_arrived_is_dropped():
    result = [AIMessage(content="", tool_calls=[{"name": "x", "args": {}, "id": "c1"}])]

    assert bot.extract_tool_trace(result) == []


def test_a_long_tool_result_is_truncated():
    result = [
        AIMessage(content="", tool_calls=[{"name": "web_search", "args": {}, "id": "c1"}]),
        ToolMessage(content="x" * 5000, tool_call_id="c1"),
    ]

    stored = bot.extract_tool_trace(result)[0]["result"]

    assert len(stored) <= AGENT_TOOL_RESULT_MAX_CHARS + 1


def test_extract_is_safe_on_an_empty_turn():
    assert bot.extract_tool_trace([]) == []
    assert bot.extract_tool_trace(None) == []


# ---------------------------------------------------------------------------
# S7 — the message survives a database that has not been migrated yet
# ---------------------------------------------------------------------------


def test_a_rejected_trace_still_saves_the_message():
    """If `messages.tool_calls` does not exist yet, the insert fails. A trace is
    a nice-to-have; the transcript is the record of what was agreed, so the turn
    is re-saved without it rather than lost."""
    from domains.negotiation.memory import ConversationMemory

    memory = ConversationMemory()
    calls = []

    def insert(payload):
        calls.append(payload)
        if "tool_calls" in payload:
            raise RuntimeError("column messages.tool_calls does not exist")
        return MagicMock(execute=MagicMock(return_value=None))

    fake = MagicMock()
    fake.table.return_value.insert.side_effect = insert
    memory._supabase = fake

    memory.add_message("u1", "ai", "How about RM1110?", "i", "ai", _trace())

    assert len(calls) == 2, "the retry never happened"
    assert "tool_calls" in calls[0]
    assert "tool_calls" not in calls[1]
    assert calls[1]["content"] == "How about RM1110?"


def test_the_trace_column_is_only_selected_when_asked_for():
    """The chat client and the admin console read the same page and have no use
    for it."""
    from domains.negotiation.memory import ConversationMemory

    memory = ConversationMemory()
    fake = MagicMock()
    memory._supabase = fake

    memory.get_history("u1", limit=5)
    assert "tool_calls" not in fake.table.return_value.select.call_args[0][0]

    memory.get_history("u1", limit=5, include_tool_calls=True)
    assert "tool_calls" in fake.table.return_value.select.call_args[0][0]


def test_the_selected_trace_actually_reaches_the_caller():
    """SPEC-090 found this: the column was selected and then thrown away.

    `_page` asked for `tool_calls`, and `_to_public` — which every row goes
    through on the way out — built its dict from three fixed keys. So
    `_build_messages` read `row.get("tool_calls")` as None on every turn, the
    `traced` set above it selected rows that then replayed as plain prose, and
    SPEC-087 was inert in production from the day it shipped. Every test around
    it passed because they all stub `get_history` and hand the trace back
    themselves.
    """
    from domains.negotiation.memory import ConversationMemory

    memory = ConversationMemory()
    fake = MagicMock()
    stored = {"role": "ai", "content": "How about RM1110?", "source": "ai", "tool_calls": _trace()}
    fake.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
        stored
    ]
    memory._supabase = fake

    row = memory.get_history("u1", limit=5, include_tool_calls=True)[0]

    assert row.get("tool_calls") == _trace(), "the trace was selected and then dropped on the way out"


def test_the_trace_is_withheld_from_callers_that_did_not_ask():
    """The other half: the chat client must keep reading exactly what it did."""
    from domains.negotiation.memory import ConversationMemory

    memory = ConversationMemory()
    fake = MagicMock()
    stored = {"role": "ai", "content": "How about RM1110?", "source": "ai", "tool_calls": _trace()}
    fake.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.return_value.data = [
        stored
    ]
    memory._supabase = fake

    row = memory.get_history("u1", limit=5)[0]

    assert "tool_calls" not in row
    assert row["content"] == "How about RM1110?"
