"""
Tests for agent/bot.py — the customer-facing orchestrator (supervisor) agent.

bot.py owns its OWN `conversation_memory` singleton (a separate instance from
agent.memory.conversation_memory), and lazily builds `_customer_agent` via
`_get_customer_agent()`. Since SPEC-020 there is no `_model` singleton: the
compiled graph is cached but its model is resolved per turn by
`_select_customer_model`, so the process is never pinned to one provider. Per
the file-specific notes, tests here:
  - monkeypatch `agent.bot._get_customer_agent` to return a fake object with an
    async `.ainvoke(...)` and an async-generator `.astream(...)` shaped like the
    real LangGraph "messages" stream_mode output (AIMessageChunk instances,
    optionally carrying `tool_call_chunks`).
  - monkeypatch `agent.bot.conversation_memory` directly (NOT agent.memory's
    singleton) since bot.py imports its own instance.
  - monkeypatch `agent.bot.item_agent` / `agent.bot.stripe_agent` (the names
    bound into bot.py's namespace via `from .sub_agents.X import X`) for the
    `call_item_agent` / `call_stripe_agent` wrapper tools.

No real Gemini/Supabase/network call is ever made.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

import agent.bot as bot
from agent.context import current_item_id, current_user_id, get_item_id, get_user_id, set_context

# ---------------------------------------------------------------------------
# Shared fakes / fixtures
# ---------------------------------------------------------------------------

class FakeAgent:
    """Stand-in for a compiled LangGraph agent (customer / item / stripe)."""

    def __init__(self, ainvoke_result=None, stream_chunks=None):
        self.ainvoke_result = ainvoke_result
        self.stream_chunks = stream_chunks or []
        self.ainvoke_calls = []
        self.astream_calls = []

    async def ainvoke(self, payload):
        self.ainvoke_calls.append(payload)
        return self.ainvoke_result

    async def astream(self, payload, stream_mode="messages"):
        self.astream_calls.append((payload, stream_mode))
        for item in self.stream_chunks:
            yield item


@pytest.fixture
def fake_memory(monkeypatch):
    """Replace bot's own `conversation_memory` singleton with a MagicMock so no
    Supabase call ever happens, and so tests can assert on add_message/get_history."""
    fake = MagicMock()
    fake.get_history.return_value = []
    monkeypatch.setattr(bot, "conversation_memory", fake)
    return fake


@pytest.fixture(autouse=True)
def _reset_context_vars():
    """Isolate ContextVar state per test (mirrors tests/test_agent_context.py)."""
    user_token = current_user_id.set(None)
    item_token = current_item_id.set(None)
    try:
        yield
    finally:
        current_user_id.reset(user_token)
        current_item_id.reset(item_token)


def _msg(role, content, source="ai"):
    return {"role": role, "content": content, "source": source}


# ---------------------------------------------------------------------------
# _extract_text_from_content
# ---------------------------------------------------------------------------

def test_extract_text_from_content_plain_string():
    assert bot._extract_text_from_content("hello world") == "hello world"


def test_extract_text_from_content_list_of_strings():
    assert bot._extract_text_from_content(["foo", "bar"]) == "foobar"


def test_extract_text_from_content_list_of_text_dicts():
    content = [{"type": "text", "text": "foo"}, {"type": "text", "text": "bar"}]
    assert bot._extract_text_from_content(content) == "foobar"


def test_extract_text_from_content_mixed_list_skips_unrecognized_parts():
    content = [
        {"type": "text", "text": "A"},
        {"type": "image_url", "image_url": {"url": "http://x"}},
        "B",
        42,  # neither str nor dict-with-text -> silently skipped
    ]
    assert bot._extract_text_from_content(content) == "AB"


def test_extract_text_from_content_empty_list_returns_empty_string():
    assert bot._extract_text_from_content([]) == ""


def test_extract_text_from_content_none_returns_empty_string():
    assert bot._extract_text_from_content(None) == ""


def test_extract_text_from_content_other_type_stringified():
    assert bot._extract_text_from_content(42) == "42"


# ---------------------------------------------------------------------------
# get_item_details_for_context
# ---------------------------------------------------------------------------

def test_get_item_details_for_context_returns_first_row(monkeypatch):
    import connector
    from conftest import make_supabase_result

    fake_client = MagicMock()
    fake_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"name": "iPhone", "price": 500}])
    )
    monkeypatch.setattr(connector, "user_supabase", fake_client, raising=False)

    result = bot.get_item_details_for_context("item-1")

    assert result == {"name": "iPhone", "price": 500}
    fake_client.table.assert_called_once_with("items")
    fake_client.table.return_value.select.assert_called_once_with(
        "name, description, price, condition, image_path"
    )
    fake_client.table.return_value.select.return_value.eq.assert_called_once_with("id", "item-1")


def test_get_item_details_for_context_returns_none_when_no_rows(monkeypatch):
    import connector
    from conftest import make_supabase_result

    fake_client = MagicMock()
    fake_client.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([])
    )
    monkeypatch.setattr(connector, "user_supabase", fake_client, raising=False)

    assert bot.get_item_details_for_context("missing-item") is None


def test_get_item_details_for_context_swallows_exception_and_returns_none(monkeypatch):
    import connector

    fake_client = MagicMock()
    fake_client.table.side_effect = RuntimeError("db is down")
    monkeypatch.setattr(connector, "user_supabase", fake_client, raising=False)

    assert bot.get_item_details_for_context("item-1") is None


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------

def test_build_messages_no_history_no_item_no_files_single_content(fake_memory):
    messages = bot._build_messages("user-1", "hello there")

    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)
    assert messages[0].content == "hello there"


def test_build_messages_reconstructs_history_then_appends_new_turn(fake_memory):
    fake_memory.get_history.return_value = [
        _msg("human", "hi", "human"),
        _msg("ai", "hello!"),
    ]

    messages = bot._build_messages("user-1", "how much?")

    assert len(messages) == 3
    assert isinstance(messages[0], HumanMessage) and messages[0].content == "hi"
    assert isinstance(messages[1], AIMessage) and messages[1].content == "hello!"
    assert isinstance(messages[2], HumanMessage) and messages[2].content == "how much?"
    fake_memory.get_history.assert_called_once_with("user-1", limit=50)


def test_build_messages_without_item_id_does_not_look_up_item(fake_memory, monkeypatch):
    lookup = MagicMock()
    monkeypatch.setattr(bot, "get_item_details_for_context", lookup)

    bot._build_messages("user-1", "hello")

    lookup.assert_not_called()


def test_build_messages_with_item_id_found_injects_context_and_images(fake_memory, monkeypatch):
    import json

    images = {"0": "http://img/1.png", "1": "http://img/2.png", "2": "http://img/3.png"}
    monkeypatch.setattr(
        bot,
        "get_item_details_for_context",
        lambda item_id: {
            "name": "iPhone 12",
            "price": 500,
            "image_path": json.dumps(images),
        },
    )

    messages = bot._build_messages("user-1", "still available?", item_id="item-42")

    assert len(messages) == 1
    new_msg = messages[0]
    assert isinstance(new_msg, HumanMessage)
    assert isinstance(new_msg.content, list)
    # First part is the text/context block.
    text_part = new_msg.content[0]
    assert text_part["type"] == "text"
    assert "Context Item ID: item-42" in text_part["text"]
    assert 'Item Name: "iPhone 12"' in text_part["text"]
    assert "Listed Price: RM500" in text_part["text"]
    assert "Buyer: still available?" in text_part["text"]
    # Only the first 2 images are attached, in map order.
    image_parts = [p for p in new_msg.content if p["type"] == "image_url"]
    assert len(image_parts) == 2
    assert image_parts[0]["image_url"]["url"] == "http://img/1.png"
    assert image_parts[1]["image_url"]["url"] == "http://img/2.png"


def test_build_messages_with_item_id_not_found_uses_plain_buyer_prefix(fake_memory, monkeypatch):
    monkeypatch.setattr(bot, "get_item_details_for_context", lambda item_id: None)

    messages = bot._build_messages("user-1", "hello?", item_id="missing-item")

    assert len(messages) == 1
    assert messages[0].content == "Buyer: hello?"


def test_build_messages_bad_image_path_json_is_caught_and_logged(fake_memory, monkeypatch):
    monkeypatch.setattr(
        bot,
        "get_item_details_for_context",
        lambda item_id: {"name": "Chair", "price": 20, "image_path": "not-valid-json"},
    )
    logged = {}
    monkeypatch.setattr(bot.logger, "info", lambda msg: logged.setdefault("msg", msg))

    messages = bot._build_messages("user-1", "hi", item_id="item-1")

    # Falls back to text-only content since item_images stayed empty.
    assert messages[0].content == (
        'SYSTEM: Context Item ID: item-1\nItem Name: "Chair"\nListed Price: RM20\n\nBuyer: hi'
    )
    assert "Failed to parse item images" in logged["msg"]


def test_build_messages_missing_image_path_key_defaults_gracefully(fake_memory, monkeypatch):
    monkeypatch.setattr(
        bot,
        "get_item_details_for_context",
        lambda item_id: {"name": "Chair", "price": 20},
    )

    messages = bot._build_messages("user-1", "hi", item_id="item-1")

    assert isinstance(messages[0].content, str)
    assert "Chair" in messages[0].content


def test_build_messages_with_image_file_attaches_data_uri(fake_memory):
    files = [{"name": "photo.png", "type": "image/png", "data": "QUJD"}]

    messages = bot._build_messages("user-1", "here's a pic", files=files)

    content = messages[0].content
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "here's a pic"}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,QUJD"},
    }


def test_build_messages_with_non_image_file_appends_attachment_note(fake_memory):
    files = [{"name": "invoice.pdf", "type": "application/pdf", "data": "irrelevant"}]

    messages = bot._build_messages("user-1", "see attached", files=files)

    content = messages[0].content
    assert content[0] == {"type": "text", "text": "see attached"}
    assert content[1] == {"type": "text", "text": "\n[Attached: invoice.pdf]"}


def test_build_messages_with_empty_files_list_is_treated_as_no_files(fake_memory):
    messages = bot._build_messages("user-1", "hi", files=[])

    assert messages[0].content == "hi"


# ---------------------------------------------------------------------------
# chat()
# ---------------------------------------------------------------------------

async def test_chat_returns_extracted_text_and_persists_messages(fake_memory, monkeypatch):
    fake_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="Sure, RM50 works!")]})
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    result = await bot.chat("user-1", "can you do RM50?")

    assert result == "Sure, RM50 works!"
    fake_memory.add_message.assert_any_call(
        "user-1", "human", "can you do RM50?", None, source="human"
    )
    fake_memory.add_message.assert_any_call("user-1", "ai", "Sure, RM50 works!", None)
    assert fake_agent.ainvoke_calls[0]["messages"][-1].content == "can you do RM50?"


async def test_chat_extracts_text_from_list_of_content_blocks(fake_memory, monkeypatch):
    fake_agent = FakeAgent(
        ainvoke_result={
            "messages": [
                SimpleNamespace(content=[{"type": "text", "text": "Part1"}, {"type": "text", "text": "Part2"}])
            ]
        }
    )
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    result = await bot.chat("user-1", "hi")

    assert result == "Part1Part2"
    fake_memory.add_message.assert_any_call("user-1", "ai", "Part1Part2", None)


async def test_chat_passes_item_id_through_to_memory_and_context(fake_memory, monkeypatch):
    monkeypatch.setattr(bot, "get_item_details_for_context", lambda item_id: None)
    fake_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="ok")]})
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    await bot.chat("user-1", "hello", item_id="item-99")

    fake_memory.add_message.assert_any_call("user-1", "human", "hello", "item-99", source="human")
    fake_memory.add_message.assert_any_call("user-1", "ai", "ok", "item-99")


async def test_chat_sets_request_scoped_context_for_agent_run(fake_memory, monkeypatch):
    observed = {}
    monkeypatch.setattr(bot, "get_item_details_for_context", lambda item_id: None)

    class ContextCheckingAgent(FakeAgent):
        async def ainvoke(self, payload):
            observed["user_id"] = get_user_id()
            observed["item_id"] = get_item_id()
            return await super().ainvoke(payload)

    fake_agent = ContextCheckingAgent(ainvoke_result={"messages": [SimpleNamespace(content="ok")]})
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    await bot.chat("user-42", "hi", item_id="item-7")

    assert observed == {"user_id": "user-42", "item_id": "item-7"}


# ---------------------------------------------------------------------------
# chat_stream()
# ---------------------------------------------------------------------------

async def _collect_stream(agen):
    """Collect a chat_stream(), dropping the SPEC-020 provider attribution event.

    `chat_stream` always opens with `{"provider": {...}}` naming the engine
    serving the turn (self-hosted M5 vs Gemini overflow). The tests below are
    about text/status forwarding, so that leading event is stripped here rather
    than restated in every assertion. Its own contract — that it is emitted, and
    emitted FIRST — is covered in test_hybrid_llm_load_balancer.py.
    """
    out = []
    async for item in agen:
        if isinstance(item, dict) and "provider" in item:
            continue
        out.append(item)
    return out


@pytest.mark.parametrize(
    "tool_name,expected_status",
    [
        ("call_item_agent", "Understanding the item..."),
        ("call_stripe_agent", "Generating payment link..."),
        ("check_user_orders", "Checking your orders..."),
        ("evaluate_offer", "Evaluating your offer..."),
        ("web_search", "Searching the market..."),
        ("assess_discount_eligibility", "Checking discounts..."),
        ("some_unmapped_tool", "Cooking..."),
    ],
)
async def test_chat_stream_yields_status_for_each_tool_call_chunk(
    fake_memory, monkeypatch, tool_name, expected_status
):
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": tool_name, "args": "", "id": "call-1", "index": 0}],
    )
    fake_agent = FakeAgent(stream_chunks=[(chunk, {})])
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    results = await _collect_stream(bot.chat_stream("user-1", "hi"))

    assert results == [{"status": expected_status}]


async def test_chat_stream_yields_plain_text_deltas_and_persists_final_text(fake_memory, monkeypatch):
    chunks = [
        (AIMessageChunk(content="Hello "), {}),
        (AIMessageChunk(content="world!"), {}),
    ]
    fake_agent = FakeAgent(stream_chunks=chunks)
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    results = await _collect_stream(bot.chat_stream("user-1", "hi"))

    assert results == ["Hello ", "world!"]
    fake_memory.add_message.assert_any_call("user-1", "ai", "Hello world!", None)


async def test_chat_stream_skips_non_ai_message_chunks(fake_memory, monkeypatch):
    chunks = [
        (SimpleNamespace(content="should be ignored"), {}),
        (AIMessageChunk(content="kept"), {}),
    ]
    fake_agent = FakeAgent(stream_chunks=chunks)
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    results = await _collect_stream(bot.chat_stream("user-1", "hi"))

    assert results == ["kept"]


async def test_chat_stream_skips_empty_content_chunks(fake_memory, monkeypatch):
    chunks = [
        (AIMessageChunk(content=""), {}),
        (AIMessageChunk(content="text"), {}),
    ]
    fake_agent = FakeAgent(stream_chunks=chunks)
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    results = await _collect_stream(bot.chat_stream("user-1", "hi"))

    assert results == ["text"]


async def test_chat_stream_tool_call_chunk_without_name_yields_no_status(fake_memory, monkeypatch):
    # Argument-continuation chunks in a real stream carry no "name" -- only the
    # first chunk of a given tool call does. These must not produce a status.
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": None, "args": '{"partial":', "id": "call-1", "index": 0}],
    )
    fake_agent = FakeAgent(stream_chunks=[(chunk, {})])
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    results = await _collect_stream(bot.chat_stream("user-1", "hi"))

    assert results == []


async def test_chat_stream_multiple_tool_call_chunks_in_one_chunk_yield_multiple_statuses(
    fake_memory, monkeypatch
):
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": "call_item_agent", "args": "", "id": "call-1", "index": 0},
            {"name": "call_stripe_agent", "args": "", "id": "call-2", "index": 1},
        ],
    )
    fake_agent = FakeAgent(stream_chunks=[(chunk, {})])
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    results = await _collect_stream(bot.chat_stream("user-1", "hi"))

    assert results == [
        {"status": "Understanding the item..."},
        {"status": "Generating payment link..."},
    ]


async def test_chat_stream_calls_astream_with_messages_and_messages_mode(fake_memory, monkeypatch):
    fake_agent = FakeAgent(stream_chunks=[])
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    await _collect_stream(bot.chat_stream("user-1", "hello"))

    assert len(fake_agent.astream_calls) == 1
    payload, stream_mode = fake_agent.astream_calls[0]
    assert stream_mode == "messages"
    assert payload["messages"][-1].content == "hello"


async def test_chat_stream_persists_empty_string_when_nothing_collected(fake_memory, monkeypatch):
    fake_agent = FakeAgent(stream_chunks=[])
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    results = await _collect_stream(bot.chat_stream("user-1", "hi"))

    assert results == []
    fake_memory.add_message.assert_any_call("user-1", "ai", "", None)


async def test_chat_stream_sets_request_scoped_context(fake_memory, monkeypatch):
    observed = {}
    monkeypatch.setattr(bot, "get_item_details_for_context", lambda item_id: None)

    class ContextCheckingAgent(FakeAgent):
        async def astream(self, payload, stream_mode="messages"):
            observed["user_id"] = get_user_id()
            observed["item_id"] = get_item_id()
            async for item in super().astream(payload, stream_mode):
                yield item

    fake_agent = ContextCheckingAgent(stream_chunks=[])
    monkeypatch.setattr(bot, "_get_customer_agent", lambda: fake_agent)

    await _collect_stream(bot.chat_stream("user-9", "hi", item_id="item-3"))

    assert observed == {"user_id": "user-9", "item_id": "item-3"}


# ---------------------------------------------------------------------------
# call_item_agent (sub-agent wrapper tool)
# ---------------------------------------------------------------------------

async def test_call_item_agent_delegates_to_item_agent_and_returns_last_message(monkeypatch):
    fake_item_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="We have 2 iPhones")]})
    monkeypatch.setattr(bot, "item_agent", fake_item_agent)

    result = await bot.call_item_agent.ainvoke({"query": "do you have iphones?"})

    assert result == "We have 2 iPhones"
    sent_messages = fake_item_agent.ainvoke_calls[0]["messages"]
    assert len(sent_messages) == 1
    assert isinstance(sent_messages[0], HumanMessage)
    assert sent_messages[0].content == "do you have iphones?"


# ---------------------------------------------------------------------------
# call_stripe_agent (sub-agent wrapper tool + item_id fallback resolution)
# ---------------------------------------------------------------------------

async def test_call_stripe_agent_uses_context_item_id_without_resolution(monkeypatch):
    set_context(user_id="user-1", item_id="item-real-uuid-123")
    fake_stripe_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="Link created")]})
    fake_item_agent = FakeAgent()  # should NOT be called
    monkeypatch.setattr(bot, "stripe_agent", fake_stripe_agent)
    monkeypatch.setattr(bot, "item_agent", fake_item_agent)

    result = await bot.call_stripe_agent.ainvoke({"request": "create link for item-real-uuid-123 at RM50"})

    assert result == "Link created"
    assert fake_item_agent.ainvoke_calls == []
    sent_messages = fake_stripe_agent.ainvoke_calls[0]["messages"]
    assert sent_messages[0].content == "create link for item-real-uuid-123 at RM50"


class _ItemIdObservingStripeAgent(FakeAgent):
    """Captures get_item_id() as seen from *inside* stripe_agent.ainvoke().

    NOTE (discovered while testing, not a bug we're fixing per instructions):
    `call_stripe_agent` does `current_item_id.set(resolved_id)` and then calls
    `stripe_agent.ainvoke(...)` in the same coroutine, so that nested call DOES
    observe the resolved id (asserted here). However, LangChain's
    `BaseTool.ainvoke()` runs the tool's coroutine in a way that isolates its
    contextvar mutations from the caller -- so `get_item_id()` read from
    *outside* `call_stripe_agent.ainvoke(...)` after it returns is back to
    whatever it was before the call (see the isolation test below). The
    resolved id is effectively only visible to tools invoked synchronously
    inside this same tool call, not to the wider request context.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.item_id_seen_inside = "NOT_CALLED"

    async def ainvoke(self, payload):
        self.item_id_seen_inside = get_item_id()
        return await super().ainvoke(payload)


@pytest.mark.parametrize("missing_item_id", [None, "test-item-id", "None"])
async def test_call_stripe_agent_resolves_missing_item_id_from_history(
    fake_memory, monkeypatch, missing_item_id
):
    set_context(user_id="user-1", item_id=missing_item_id)
    fake_memory.get_history.return_value = [
        {"role": "human", "content": "I want the iPhone 12"},
        {"role": "ai", "content": "Sure, it's RM500"},
    ]
    resolved_uuid = "resolved-uuid-1234567890"
    fake_item_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content=resolved_uuid)]})
    fake_stripe_agent = _ItemIdObservingStripeAgent(
        ainvoke_result={"messages": [SimpleNamespace(content="Link created")]}
    )
    monkeypatch.setattr(bot, "item_agent", fake_item_agent)
    monkeypatch.setattr(bot, "stripe_agent", fake_stripe_agent)

    result = await bot.call_stripe_agent.ainvoke({"request": "create the link"})

    assert result == "Link created"
    # Resolution query included the conversation history text.
    resolution_query = fake_item_agent.ainvoke_calls[0]["messages"][0].content
    assert "I want the iPhone 12" in resolution_query
    assert "Sure, it's RM500" in resolution_query
    # The resolved id is visible to stripe_agent.ainvoke() (called within the
    # same tool invocation)...
    assert fake_stripe_agent.item_id_seen_inside == resolved_uuid
    # ...but does NOT propagate back out to this (caller's) context -- see
    # _ItemIdObservingStripeAgent docstring.
    assert get_item_id() == missing_item_id


async def test_call_stripe_agent_strips_markdown_code_fences_from_resolved_id(fake_memory, monkeypatch):
    set_context(user_id="user-1", item_id=None)
    fake_memory.get_history.return_value = [{"role": "human", "content": "the chair"}]
    fake_item_agent = FakeAgent(
        ainvoke_result={"messages": [SimpleNamespace(content="```resolved-uuid-abcdefghij```")]}
    )
    fake_stripe_agent = _ItemIdObservingStripeAgent(ainvoke_result={"messages": [SimpleNamespace(content="ok")]})
    monkeypatch.setattr(bot, "item_agent", fake_item_agent)
    monkeypatch.setattr(bot, "stripe_agent", fake_stripe_agent)

    await bot.call_stripe_agent.ainvoke({"request": "create the link"})

    assert fake_stripe_agent.item_id_seen_inside == "resolved-uuid-abcdefghij"


async def test_call_stripe_agent_resolution_from_list_content_blocks(fake_memory, monkeypatch):
    set_context(user_id="user-1", item_id=None)
    fake_memory.get_history.return_value = [{"role": "human", "content": "the chair"}]
    resolution_content = [{"type": "text", "text": "resolved-list-"}, "uuid-9876543210"]
    fake_item_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content=resolution_content)]})
    fake_stripe_agent = _ItemIdObservingStripeAgent(ainvoke_result={"messages": [SimpleNamespace(content="ok")]})
    monkeypatch.setattr(bot, "item_agent", fake_item_agent)
    monkeypatch.setattr(bot, "stripe_agent", fake_stripe_agent)

    await bot.call_stripe_agent.ainvoke({"request": "create the link"})

    assert fake_stripe_agent.item_id_seen_inside == "resolved-list-uuid-9876543210"


async def test_call_stripe_agent_context_update_does_not_leak_to_caller(fake_memory, monkeypatch):
    """Documents the contextvar-isolation behavior described above in isolation:
    even though `call_stripe_agent` resolves and `.set()`s the item id, the
    caller's own `get_item_id()` is unaffected once `.ainvoke()` returns."""
    set_context(user_id="user-1", item_id=None)
    fake_memory.get_history.return_value = [{"role": "human", "content": "the chair"}]
    fake_item_agent = FakeAgent(
        ainvoke_result={"messages": [SimpleNamespace(content="resolved-uuid-1234567890")]}
    )
    fake_stripe_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="ok")]})
    monkeypatch.setattr(bot, "item_agent", fake_item_agent)
    monkeypatch.setattr(bot, "stripe_agent", fake_stripe_agent)

    await bot.call_stripe_agent.ainvoke({"request": "create the link"})

    assert get_item_id() is None


async def test_call_stripe_agent_resolution_not_found_leaves_item_id_unset(fake_memory, monkeypatch):
    set_context(user_id="user-1", item_id=None)
    fake_memory.get_history.return_value = [{"role": "human", "content": "something vague"}]
    fake_item_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="NOT_FOUND")]})
    fake_stripe_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="ok")]})
    monkeypatch.setattr(bot, "item_agent", fake_item_agent)
    monkeypatch.setattr(bot, "stripe_agent", fake_stripe_agent)

    await bot.call_stripe_agent.ainvoke({"request": "create the link"})

    assert get_item_id() is None


async def test_call_stripe_agent_resolution_too_short_is_rejected(fake_memory, monkeypatch):
    set_context(user_id="user-1", item_id=None)
    fake_memory.get_history.return_value = [{"role": "human", "content": "something vague"}]
    # len("12345") == 5, not > 10 -> sanity check fails, treated as unresolved.
    fake_item_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="12345")]})
    fake_stripe_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="ok")]})
    monkeypatch.setattr(bot, "item_agent", fake_item_agent)
    monkeypatch.setattr(bot, "stripe_agent", fake_stripe_agent)

    await bot.call_stripe_agent.ainvoke({"request": "create the link"})

    assert get_item_id() is None


async def test_call_stripe_agent_skips_resolution_when_no_user_id_in_context(monkeypatch):
    set_context(user_id=None, item_id=None)
    fake_item_agent = FakeAgent()  # must not be called: no ctx_user_id means no history lookup
    fake_stripe_agent = FakeAgent(ainvoke_result={"messages": [SimpleNamespace(content="ok")]})
    monkeypatch.setattr(bot, "item_agent", fake_item_agent)
    monkeypatch.setattr(bot, "stripe_agent", fake_stripe_agent)

    result = await bot.call_stripe_agent.ainvoke({"request": "create the link"})

    assert result == "ok"
    assert fake_item_agent.ainvoke_calls == []
    assert get_item_id() is None


async def test_transfer_to_human_success(fake_memory, monkeypatch):
    set_context(user_id="user_transfer_1", item_id="item-1")

    # Mock admin_supabase chat_settings upsert
    fake_supabase = MagicMock()
    monkeypatch.setattr("connector.admin_supabase", fake_supabase)

    # Mock broadcast_to_chat
    fake_broadcast = MagicMock()
    monkeypatch.setattr("payment.fulfillment.broadcast_to_chat", fake_broadcast)

    # Mock send_human_transfer_alert
    fake_email_alert = MagicMock(return_value=True)
    monkeypatch.setattr("services.email_service.send_human_transfer_alert", fake_email_alert)

    result = await bot.transfer_to_human.ainvoke({
        "reason": "Customer requested human seller",
        "summary": "Need help with pickup schedule"
    })

    assert "transferred" in result.lower()
    assert fake_supabase.table.called
    assert fake_broadcast.called
    assert fake_email_alert.called
    assert fake_email_alert.call_args.kwargs["user_id"] == "user_transfer_1"
    assert fake_email_alert.call_args.kwargs["reason"] == "Customer requested human seller"
    assert fake_memory.add_message.called


async def test_transfer_to_human_missing_user_context():
    set_context(user_id=None, item_id=None)
    result = await bot.transfer_to_human.ainvoke({"reason": "Test"})
    assert "user context missing" in result.lower()
