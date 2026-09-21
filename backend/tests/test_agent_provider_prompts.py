"""SPEC-081 — one prompt per engine, chosen by the engine the turn is pinned to.

`CUSTOMER_AGENT_PROMPT` was written for Gemini and sent to both providers. On the
self-hosted Qwen it produced a specific failure: instead of calling
`evaluate_offer`, the model narrated the call ("Let me check the floor price for
you.") and then copied the persona's own example sentences back to the buyer.
With the tool never run there is no counter number, no `pending_discount`, and
therefore no `data-discount` frame — the header price simply never moves.

These tests assert the *properties* that failure needs (a tool mandate, and no
quotable buyer-facing scripts in the local prompt) plus the invariants both
prompts must keep, rather than pinning exact copy — the wording stays free to
change as the local model does.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import domains.negotiation.bot as bot
from domains.negotiation.config import CLOUD_AGENT_TEMPERATURE, COD_POLICY, LOCAL_AGENT_TEMPERATURE
from domains.negotiation.llm_factory import (
    cloud_provider_info,
    current_provider,
    local_provider_info,
)


def _lower(text: str) -> str:
    return " ".join(text.lower().split())


CLOUD = _lower(bot.CUSTOMER_AGENT_PROMPT)
LOCAL = _lower(bot.LOCAL_CUSTOMER_AGENT_PROMPT)


# ---------------------------------------------------------------------------
# S1 — the prompt follows the provider the turn already pinned
# ---------------------------------------------------------------------------


def test_local_provider_gets_the_local_prompt():
    assert bot.customer_prompt_for(local_provider_info()) == bot.LOCAL_CUSTOMER_AGENT_PROMPT


def test_cloud_provider_gets_the_cloud_prompt():
    assert bot.customer_prompt_for(cloud_provider_info()) == bot.CUSTOMER_AGENT_PROMPT


def test_unpinned_turn_falls_back_to_the_cloud_prompt():
    """Scripts, standalone tool calls and tests run outside `hybrid_llm_session()`."""
    assert bot.customer_prompt_for(None) == bot.CUSTOMER_AGENT_PROMPT


def test_the_two_prompts_are_actually_different():
    assert bot.LOCAL_CUSTOMER_AGENT_PROMPT != bot.CUSTOMER_AGENT_PROMPT


# ---------------------------------------------------------------------------
# S2 — what LangGraph receives for the turn
# ---------------------------------------------------------------------------


def test_select_prompt_prepends_one_system_message_and_keeps_history():
    history = [HumanMessage(content="2000?"), AIMessage(content="hmm")]

    result = bot._select_customer_prompt({"messages": history})

    assert isinstance(result[0], SystemMessage)
    assert result[1:] == history
    assert sum(isinstance(m, SystemMessage) for m in result) == 1


def test_select_prompt_uses_the_pinned_provider():
    token = current_provider.set(local_provider_info())
    try:
        local = bot._select_customer_prompt({"messages": []})[0].content
    finally:
        current_provider.reset(token)

    token = current_provider.set(cloud_provider_info())
    try:
        cloud = bot._select_customer_prompt({"messages": []})[0].content
    finally:
        current_provider.reset(token)

    assert local == bot.LOCAL_CUSTOMER_AGENT_PROMPT
    assert cloud == bot.CUSTOMER_AGENT_PROMPT


# ---------------------------------------------------------------------------
# S3 — the local prompt closes the narrate-instead-of-call hole
# ---------------------------------------------------------------------------


def test_local_prompt_mandates_evaluate_offer():
    assert "evaluate_offer" in LOCAL
    # The mandate has to be phrased as an obligation, not a suggestion.
    assert "must" in LOCAL


def test_local_prompt_forbids_narrating_tool_use():
    """The exact phrase Qwen emitted instead of a tool call."""
    assert "let me check" in LOCAL, "the prompt must name the behaviour it bans"
    # ...and it must be banned, not demonstrated: every occurrence is inside a
    # prohibition, so a negation word is never far from it.
    index = LOCAL.index("let me check")
    assert "never" in LOCAL[max(0, index - 200) : index] or "do not" in LOCAL[max(0, index - 200) : index]


def test_local_prompt_states_the_tool_contract_before_the_persona_colour():
    """Tool rules first: buried under 250 lines of persona they lost."""
    assert LOCAL.index("evaluate_offer") < LOCAL.index("emoji")


# ---------------------------------------------------------------------------
# S4 — no buyer-facing sentence the model can copy instead of calling a tool
# ---------------------------------------------------------------------------


def test_local_prompt_quotes_no_literal_counter_offer():
    """`So RM2100? 🛒` in the prompt came back out as a real, floor-free quote."""
    import re

    assert not re.search(r"rm\s*\d", LOCAL), "no concrete ringgit figure belongs in the local prompt"


def test_local_prompt_has_no_reusable_refusal_script():
    assert "can you go a bit higher?" not in LOCAL
    assert "that's too low for me" not in LOCAL


# ---------------------------------------------------------------------------
# S5 — invariants both prompts keep
# ---------------------------------------------------------------------------


def test_both_prompts_protect_the_floor():
    for prompt in (CLOUD, LOCAL):
        assert "min_price" in prompt or "minimum price" in prompt
        assert "never" in prompt


def test_both_prompts_carry_the_cod_policy():
    for prompt in (CLOUD, LOCAL):
        assert "cod" in prompt
        assert "transfer_to_human" in prompt
    assert COD_POLICY in bot.LOCAL_CUSTOMER_AGENT_PROMPT


def test_both_prompts_keep_the_store_assistant_scope():
    for prompt in (CLOUD, LOCAL):
        assert "refuse" in prompt or "decline" in prompt


def test_local_prompt_keeps_the_prompt_injection_defence():
    assert "ignore" in LOCAL
    assert "terry" in LOCAL


# ---------------------------------------------------------------------------
# S6 — the choice is made per turn, not frozen into the compiled graph
# ---------------------------------------------------------------------------


def test_graph_is_compiled_with_a_callable_prompt(monkeypatch):
    captured = {}

    def fake_create_react_agent(model, tools, prompt=None):
        captured["prompt"] = prompt

        class _Graph:
            def with_config(self, _cfg):
                return "compiled"

        return _Graph()

    monkeypatch.setattr(bot, "create_react_agent", fake_create_react_agent)
    monkeypatch.setattr(bot, "_customer_agent", None)

    try:
        assert bot._get_customer_agent() == "compiled"
    finally:
        bot._customer_agent = None

    assert callable(captured["prompt"]), "a frozen string would pin the process to one engine"
    assert captured["prompt"] is bot._select_customer_prompt


# ---------------------------------------------------------------------------
# S7 — the two phrasings that measurably lost the tool call
#
# Both are regressions observed against the live tunnel, not hypotheticals. The
# first shape ("800 also cannot, offer me one") reads as a REJECTED number plus
# a request that the seller go first, and the model answered it in prose every
# time until the prompt named both cases explicitly.
# ---------------------------------------------------------------------------


def test_local_prompt_covers_a_price_the_buyer_is_rejecting():
    assert "also cannot" in LOCAL or "rejecting" in LOCAL


def test_local_prompt_covers_the_buyer_asking_the_seller_to_go_first():
    """ "You offer me one" is still a turn that needs the tool, not a licence to invent."""
    assert "make me an offer" in LOCAL or "offer me one" in LOCAL


def test_local_prompt_bans_floor_vocabulary_outright_not_just_on_two_verbs():
    """It described the LISTED price as "my minimum price", which teaches the buyer
    the word for what it must never disclose."""
    index = LOCAL.index("minimum")
    assert "never" in LOCAL[max(0, index - 300) : index]


# ---------------------------------------------------------------------------
# S8 — temperature is part of the per-provider decision, not a constant
# ---------------------------------------------------------------------------


def test_local_turns_run_cooler_than_cloud_turns():
    assert bot.customer_temperature_for(local_provider_info()) == LOCAL_AGENT_TEMPERATURE
    assert bot.customer_temperature_for(cloud_provider_info()) == CLOUD_AGENT_TEMPERATURE
    assert LOCAL_AGENT_TEMPERATURE < CLOUD_AGENT_TEMPERATURE


def test_unpinned_turn_uses_the_cloud_temperature():
    assert bot.customer_temperature_for(None) == CLOUD_AGENT_TEMPERATURE


def test_select_model_asks_for_the_pinned_providers_temperature(monkeypatch):
    seen = []
    monkeypatch.setattr(
        bot,
        "get_chat_model",
        lambda temperature=0.7: seen.append(temperature) or type("M", (), {"bind_tools": lambda self, t: "bound"})(),
    )

    token = current_provider.set(local_provider_info())
    try:
        assert bot._select_customer_model(None, None) == "bound"
    finally:
        current_provider.reset(token)

    assert seen == [LOCAL_AGENT_TEMPERATURE]
