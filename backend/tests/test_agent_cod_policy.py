"""SPEC-055 — the agent's position on cash on delivery.

The platform has no COD flow: checkout is Stripe-only, and stock is claimed by
payment rather than by agreement. With nothing in the persona the model
improvised — sometimes agreeing to a meet-up nothing in the system can honour,
sometimes refusing flatly and leaving the buyer with no way forward.

These assert the *properties* the policy has to hold (refuse in-app, hand to
Terry, state the first-come-first-served caveat) rather than one exact sentence,
so the wording stays free to change.
"""

from unittest.mock import MagicMock

import pytest

import agent.bot as bot
from agent.config import COD_POLICY, SELLER_PERSONA
from agent.context import set_context


def _lower(text: str) -> str:
    return " ".join(text.lower().split())


PERSONA = _lower(SELLER_PERSONA)
POLICY = _lower(COD_POLICY)


# ---------------------------------------------------------------------------
# Scenario 1 — the policy is in the prompt the model actually receives
# ---------------------------------------------------------------------------

def test_persona_refuses_cash_on_delivery():
    assert "cash-on-delivery" in PERSONA or "cash on delivery" in PERSONA
    assert "cod" in PERSONA


def test_persona_hands_cod_to_terry():
    """Refusing is only half an answer — the buyer has to be given the route."""
    assert "transfer_to_human" in POLICY
    assert "terry" in POLICY


def test_persona_states_first_come_first_served():
    assert "first come" in POLICY or "first-come" in POLICY
    # An unpaid arrangement holds nothing, and says so.
    assert "paid" in POLICY
    assert "cancel" in POLICY


def test_persona_forbids_promising_cod_terms():
    """A time and a place are Terry's to give, not the agent's."""
    assert "never" in POLICY


# ---------------------------------------------------------------------------
# Scenario 2 — the wording is one editable knob, not a prompt rewrite
# ---------------------------------------------------------------------------

def test_cod_policy_is_an_editable_knob():
    assert isinstance(COD_POLICY, str)
    assert COD_POLICY.strip()
    assert COD_POLICY in SELLER_PERSONA


# ---------------------------------------------------------------------------
# Scenario 3 — the supervisor can find the tool for this case
# ---------------------------------------------------------------------------

def test_transfer_tool_documents_the_cod_case():
    doc = _lower(bot.transfer_to_human.description or "")
    assert "cash on delivery" in doc or "cash-on-delivery" in doc or "cod" in doc


# ---------------------------------------------------------------------------
# Scenario 4 — the handoff itself works when the reason is COD
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cod_transfer_disables_ai_and_alerts_terry(monkeypatch):
    set_context(user_id="user-cod-1", item_id="item-1")

    fake_memory = MagicMock()
    monkeypatch.setattr(bot, "conversation_memory", fake_memory)
    fake_supabase = MagicMock()
    monkeypatch.setattr("connector.admin_supabase", fake_supabase)
    monkeypatch.setattr("payment.fulfillment.broadcast_to_chat", MagicMock())
    fake_alert = MagicMock(return_value=True)
    monkeypatch.setattr("services.email_service.send_human_transfer_alert", fake_alert)

    result = await bot.transfer_to_human.ainvoke({
        "reason": "Cash-on-delivery arrangement requested",
        "summary": "Buyer wants to meet in KL to pay cash.",
    })

    assert "transferred" in result.lower()
    upserted = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert upserted["ai_enabled"] is False
    assert upserted["admin_intervening"] is True
    assert fake_alert.call_args.kwargs["reason"] == "Cash-on-delivery arrangement requested"


# ---------------------------------------------------------------------------
# Scenario 5 — the new text leaks nothing the rest of the persona protects
# ---------------------------------------------------------------------------

def test_cod_policy_leaks_no_pricing_floor():
    assert "min_price" not in POLICY
    assert "minimum price" not in POLICY
    assert "discount" not in POLICY
