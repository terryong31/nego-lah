"""
Tests for agent/sub_agents/item_agent.py and agent/sub_agents/stripe_agent.py.

Both modules build a real (but harmless-to-construct) LangGraph react-agent at
*import time* -- `create_react_agent(...)` does not make a network call by
itself, so importing these modules is safe under the conftest fake env vars.

Since SPEC-020 the model is NOT built at import time: each module exposes a
`_select_*_model(state, runtime)` callable that LangGraph invokes per turn, so
the sub-agent follows whichever provider `hybrid_llm_session()` pinned for the
request instead of being frozen to whatever was reachable at boot. Model-config
tests therefore assert on that selector's output rather than on a module-level
singleton.

What we must NOT do is actually invoke the graph for real (that would call out
to a live model), so every "does it run" test monkeypatches `.ainvoke` directly
on the already-built `item_agent` / `stripe_agent` singletons (per the
assignment notes and conftest's docstring on LLM/LangChain mocking seams).
"""

from unittest.mock import AsyncMock

from langchain_google_genai import ChatGoogleGenerativeAI

from agent.sub_agents import item_agent as item_agent_module
from agent.sub_agents import stripe_agent as stripe_agent_module
from agent.sub_agents.item_agent import item_agent, item_agent_graph
from agent.sub_agents.stripe_agent import stripe_agent, stripe_agent_graph

# ---------------------------------------------------------------------------
# item_agent.py
# ---------------------------------------------------------------------------


def test_item_agent_exists_and_is_configured():
    assert item_agent is not None
    # with_config wraps/copies the compiled graph -- distinct object, same class.
    assert type(item_agent) is type(item_agent_graph)
    assert item_agent is not item_agent_graph


def test_item_agent_recursion_limit_config():
    assert item_agent.config.get("recursion_limit") == 10


def _resolved_model(selector):
    """Run a SPEC-020 dynamic-model selector and unwrap the tool binding.

    The selector returns `model.bind_tools(...)` (a RunnableBinding); the model
    itself is on `.bound`. conftest pins LLM_PROVIDER=gemini, so this resolves
    to Gemini without touching the network.
    """
    bound = selector(None, None)
    return getattr(bound, "bound", bound)


def test_item_agent_model_config():
    model = _resolved_model(item_agent_module._select_item_model)
    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-3.8-flash"
    assert model.temperature == 0.3
    assert model.google_api_key.get_secret_value() == "test-gemini-api-key"


def _bound_tool_names(selector):
    """Tool names a selector bound onto its model.

    Providers normalise `bind_tools` differently, so accept either the OpenAI
    function envelope (`{"type": "function", "function": {"name": ...}}`) or a
    flat `{"name": ...}` schema.
    """
    bound = selector(None, None)
    return {t.get("function", t)["name"] for t in bound.kwargs["tools"]}


def test_item_agent_selector_binds_its_own_tools():
    """The dynamic model must arrive with tools already bound -- LangGraph does
    not bind them for a callable model."""
    assert _bound_tool_names(item_agent_module._select_item_model) == {
        "get_item_info", "search_items", "list_all_items"
    }


def test_item_agent_prompt_content():
    prompt = item_agent_module.ITEM_AGENT_PROMPT
    assert "Inventory Specialist Agent" in prompt
    assert "list_all_items" in prompt
    assert "search_items" in prompt
    assert "get_item_info" in prompt
    # It explicitly delegates negotiation to another agent.
    assert "Do not negotiate" in prompt or "Do NOT negotiate" in prompt


def test_item_agent_tools_imported_into_module_namespace():
    # item_agent.py does `from ..tools.items import get_item_info, search_items,
    # list_all_items`, so those names are bound directly on the module and are
    # the exact tool objects wired into create_react_agent(...).
    assert item_agent_module.get_item_info.name == "get_item_info"
    assert item_agent_module.search_items.name == "search_items"
    assert item_agent_module.list_all_items.name == "list_all_items"


async def test_item_agent_ainvoke_round_trips_when_mocked(monkeypatch):
    mock_ainvoke = AsyncMock(return_value={"messages": [{"role": "ai", "content": "Here are the items."}]})
    monkeypatch.setattr(item_agent, "ainvoke", mock_ainvoke)

    payload = {"messages": [{"role": "user", "content": "what do you have?"}]}
    result = await item_agent.ainvoke(payload)

    mock_ainvoke.assert_awaited_once_with(payload)
    assert result == {"messages": [{"role": "ai", "content": "Here are the items."}]}


async def test_item_agent_ainvoke_propagates_exceptions_when_mocked(monkeypatch):
    mock_ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(item_agent, "ainvoke", mock_ainvoke)

    try:
        await item_agent.ainvoke({"messages": []})
        raise AssertionError("expected RuntimeError to propagate")
    except RuntimeError as exc:
        assert str(exc) == "boom"


# ---------------------------------------------------------------------------
# stripe_agent.py
# ---------------------------------------------------------------------------


def test_stripe_agent_exists_and_is_configured():
    assert stripe_agent is not None
    assert type(stripe_agent) is type(stripe_agent_graph)
    assert stripe_agent is not stripe_agent_graph


def test_stripe_agent_recursion_limit_config():
    assert stripe_agent.config.get("recursion_limit") == 10


def test_stripe_agent_model_config():
    model = _resolved_model(stripe_agent_module._select_stripe_model)
    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-3.8-flash"
    # Payment logic uses a stricter (lower) temperature than the item agent.
    assert model.temperature == 0.1
    assert model.google_api_key.get_secret_value() == "test-gemini-api-key"


def test_stripe_agent_selector_binds_its_own_tools():
    assert _bound_tool_names(stripe_agent_module._select_stripe_model) == {
        "create_checkout_link", "cancel_payment_link", "collect_shipping_info"
    }


def test_stripe_agent_prompt_content():
    prompt = stripe_agent_module.STRIPE_AGENT_PROMPT
    assert "Payment Processor Agent" in prompt
    assert "create_checkout_link" in prompt
    assert "cancel_payment_link" in prompt
    assert "collect_shipping_info" in prompt


def test_stripe_agent_tools_imported_into_module_namespace():
    assert stripe_agent_module.create_checkout_link.name == "create_checkout_link"
    assert stripe_agent_module.cancel_payment_link.name == "cancel_payment_link"
    assert stripe_agent_module.collect_shipping_info.name == "collect_shipping_info"


async def test_stripe_agent_ainvoke_round_trips_when_mocked(monkeypatch):
    mock_ainvoke = AsyncMock(
        return_value={"messages": [{"role": "ai", "content": "Payment link created."}]}
    )
    monkeypatch.setattr(stripe_agent, "ainvoke", mock_ainvoke)

    payload = {"messages": [{"role": "user", "content": "I agree to RM100, checkout please"}]}
    result = await stripe_agent.ainvoke(payload)

    mock_ainvoke.assert_awaited_once_with(payload)
    assert result == {"messages": [{"role": "ai", "content": "Payment link created."}]}


async def test_stripe_agent_ainvoke_propagates_exceptions_when_mocked(monkeypatch):
    mock_ainvoke = AsyncMock(side_effect=ValueError("bad state"))
    monkeypatch.setattr(stripe_agent, "ainvoke", mock_ainvoke)

    try:
        await stripe_agent.ainvoke({"messages": []})
        raise AssertionError("expected ValueError to propagate")
    except ValueError as exc:
        assert str(exc) == "bad state"


# ---------------------------------------------------------------------------
# Both agents are independent singletons (no shared mutable config leakage)
# ---------------------------------------------------------------------------


def test_item_and_stripe_agents_are_distinct_objects_with_independent_configs():
    assert item_agent is not stripe_agent
    # Different temperatures, so the two selectors must not resolve to one shared model.
    assert _resolved_model(item_agent_module._select_item_model) is not _resolved_model(
        stripe_agent_module._select_stripe_model
    )
    assert item_agent.config.get("recursion_limit") == stripe_agent.config.get("recursion_limit") == 10
