"""SPEC-091 — the local turn: decide, execute, speak; the cloud turn is untouched.

`hybrid_llm_session()` already pins one provider for the whole turn (SPEC-020).
This fork hangs off that pin, so a turn can never be routed by one architecture
and spoken by the other.
"""

from unittest.mock import AsyncMock

import pytest

import agent.bot as bot
from agent.decide import TurnDecision
from agent.llm_factory import cloud_provider_info, current_provider, local_provider_info


@pytest.fixture
def pin_local():
    token = current_provider.set(local_provider_info())
    yield
    current_provider.reset(token)


@pytest.fixture
def pin_cloud():
    token = current_provider.set(cloud_provider_info())
    yield
    current_provider.reset(token)


# ---------------------------------------------------------------------------
# S1 — the fork follows the pinned provider
# ---------------------------------------------------------------------------

def test_local_provider_uses_the_two_pass_turn(pin_local):
    assert bot.uses_decide_then_speak(current_provider.get()) is True


def test_cloud_provider_keeps_the_react_agent(pin_cloud):
    assert bot.uses_decide_then_speak(current_provider.get()) is False


def test_unpinned_turn_keeps_the_react_agent():
    """Scripts, evals and standalone calls stay on the path they always used."""
    assert bot.uses_decide_then_speak(None) is False


# ---------------------------------------------------------------------------
# S8 — a "no tool" decision skips execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_tool_decision_executes_nothing(monkeypatch):
    called = []

    async def fake_execute(decision):  # pragma: no cover - must never run
        called.append(decision)
        return "unexpected"

    monkeypatch.setattr(bot, "execute_decision", fake_execute)

    result = await bot.run_decision(TurnDecision(tool=None, args={}))

    assert result is None
    assert called == []


@pytest.mark.asyncio
async def test_a_tool_decision_runs_that_tool(monkeypatch):
    monkeypatch.setattr(
        bot, "execute_decision", AsyncMock(return_value="COUNTER: ... RM1095")
    )

    result = await bot.run_decision(
        TurnDecision(tool="evaluate_offer", args={"item_id": "i", "offered_price": 1050})
    )

    assert result == "COUNTER: ... RM1095"


@pytest.mark.asyncio
async def test_a_failing_tool_does_not_kill_the_turn(monkeypatch):
    """The buyer still gets a reply; the speaker just has no tool result."""
    async def boom(decision):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(bot, "execute_decision", boom)

    assert await bot.run_decision(TurnDecision(tool="evaluate_offer", args={})) is None


@pytest.mark.asyncio
async def test_an_unknown_tool_name_is_refused(monkeypatch):
    """A hallucinated tool name must not reach getattr-style dispatch."""
    assert await bot.run_decision(TurnDecision(tool="rm_rf", args={})) is None


# ---------------------------------------------------------------------------
# S6 — COD still carries the FCFS caveat (SPEC-086)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cod_transfer_still_appends_the_fcfs_caveat(monkeypatch):
    """The tool object is what runs, so SPEC-086's caveat is not re-implemented here."""
    from agent.context import set_context

    set_context(user_id="u1", item_id="i1", language="en")

    result = await bot.execute_decision(
        TurnDecision(
            tool="transfer_to_human",
            args={"reason": "Cash-on-delivery arrangement requested", "summary": "wants to meet up"},
        )
    )

    assert "first come first served" in result.lower()


# ---------------------------------------------------------------------------
# S9 — the cloud path is unchanged by this spec
# ---------------------------------------------------------------------------

def test_cloud_prompt_tools_and_temperature_are_unchanged():
    from agent.config import CLOUD_AGENT_TEMPERATURE

    assert bot.customer_prompt_for(cloud_provider_info()) == bot.CUSTOMER_AGENT_PROMPT
    assert bot.customer_temperature_for(cloud_provider_info()) == CLOUD_AGENT_TEMPERATURE
    assert {t.name for t in bot.customer_tools} >= {
        "evaluate_offer", "create_checkout_link", "web_search", "transfer_to_human"
    }
