"""SPEC-086 — the COD handoff has to carry the first-come-first-served caveat.

SPEC-055 requires both halves of the COD answer: Terry will arrange it, AND
items are first come first served so only a paid order holds one. The second
half lived in `COD_POLICY`, inside the persona, and the self-hosted Qwen dropped
it — it called `transfer_to_human` and then paraphrased the tool's return string
and nothing else:

    "Terry will be with you shortly to sort out the COD details. Just wait here!"

Same lesson as SPEC-084: what must be said goes in the tool result, which is the
most specific and most recent instruction the model has, not in a policy two
hundred lines up a prompt.
"""

from unittest.mock import MagicMock

import pytest

import domains.negotiation.bot as bot
from domains.negotiation.context import set_context


@pytest.fixture
def transfer(monkeypatch):
    """Run `transfer_to_human` with every side effect stubbed out."""
    monkeypatch.setattr(bot, "conversation_memory", MagicMock())
    monkeypatch.setattr("core.connector.admin_supabase", MagicMock())
    monkeypatch.setattr("core.email_service.send_human_transfer_alert", MagicMock(return_value=True))
    set_context(user_id="buyer-cod", item_id="item-1")

    async def _call(reason, summary=""):
        return await bot.transfer_to_human.ainvoke({"reason": reason, "summary": summary})

    return _call


# ---------------------------------------------------------------------------
# S1-S3 — when the caveat is attached
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cod_reason_carries_the_caveat(transfer):
    result = await transfer("Cash-on-delivery arrangement requested")

    lowered = result.lower()
    assert "first come" in lowered
    assert "paid" in lowered


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "Buyer wants COD",
        "buyer asked to meet up at KL Sentral",
        "nak jumpa dan bayar cash",
        "self-collect requested",
        "wants to pay cash on arrival",
    ],
    ids=["cod", "meetup", "malay", "self-collect", "cash"],
)
async def test_every_phrasing_of_a_meetup_carries_the_caveat(transfer, reason):
    assert "first come" in (await transfer(reason)).lower()


@pytest.mark.asyncio
async def test_the_summary_is_enough_when_the_reason_is_generic(transfer):
    result = await transfer("Unresolved inquiry", summary="Buyer wants to COD at KL Sentral.")

    assert "first come" in result.lower()


# ---------------------------------------------------------------------------
# S4 — and when it is not
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_ordinary_handoff_does_not_carry_it(transfer):
    """The caveat is about meet-ups. On a dispute it is noise."""
    result = await transfer("Customer requested human seller", summary="Wants to talk to a person.")

    assert "first come" not in result.lower()
    assert "transferred" in result.lower()


# ---------------------------------------------------------------------------
# S5/S6 — additive, and discloses nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_handoff_itself_still_happens(transfer, monkeypatch):
    fake_supabase = MagicMock()
    monkeypatch.setattr("core.connector.admin_supabase", fake_supabase)
    fake_alert = MagicMock(return_value=True)
    monkeypatch.setattr("core.email_service.send_human_transfer_alert", fake_alert)

    result = await transfer("Cash-on-delivery arrangement requested")

    upserted = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert upserted["ai_enabled"] is False
    assert upserted["admin_intervening"] is True
    assert fake_alert.called
    assert "transferred" in result.lower()


@pytest.mark.asyncio
async def test_the_caveat_names_no_price_or_floor(transfer):
    result = (await transfer("Cash-on-delivery arrangement requested")).lower()

    assert "min_price" not in result
    assert "minimum" not in result
    assert "discount" not in result
    assert "rm" not in result.replace("terry", "")


@pytest.mark.asyncio
async def test_the_caveat_still_demands_the_handoff_half(transfer):
    """Appended on its own, the caveat became the only thing a terse model
    relayed — the buyer was told the FCFS rule and never told Terry was coming.
    Both halves are enumerated so neither can be the one that survives alone."""
    result = (await transfer("Cash-on-delivery arrangement requested")).lower()

    assert "terry" in result
    assert "first come" in result
    assert "both" in result, "the instruction has to ask for both, not just list them"
