"""SPEC-070 — the handoff separator belongs under the farewell, not over it.

`transfer_to_human` used to persist and broadcast its separator from inside the
tool call, which put it in the transcript *before* the reply the agent was still
writing ("let me pass you to Terry"), and put it on the buyer's chat channel
while `useChat` was still streaming into the message list — the mid-turn push
that duplicated the whole reply on screen.

The tool now records the notice; the turn runner writes it once the reply has
been delivered, the way the rate-limit handoff in `_run_turn` already did.

The turn-level tests run on conftest's `turn_env`, which records everything a
turn touches instead of performing it — exactly the ledger these assertions are
about.
"""

import asyncio
import json
from unittest.mock import MagicMock

from starlette.requests import Request

import domains.negotiation.bot as bot
from domains.negotiation.context import pending_handoff, set_context
from domains.negotiation.routes import chat_stream


def _make_request(user_id, message="hi"):
    body = json.dumps({"user_id": user_id, "message": message}).encode()
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/chat/stream",
        "raw_path": b"/chat/stream",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-type", b"application/json"),
            (b"authorization", b"Bearer sometoken"),
        ],
        "client": ("203.0.113.7", 54321),
        "server": ("testserver", 80),
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


async def _settle(deadline=2.0):
    """Give the turn's own task a chance to finish after the response ends."""
    loop_deadline = asyncio.get_running_loop().time() + deadline
    while asyncio.get_running_loop().time() < loop_deadline:
        await asyncio.sleep(0.01)
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        if not pending:
            return


# ---------------------------------------------------------------------------
# Scenario 5 — the tool records the notice instead of writing it
# ---------------------------------------------------------------------------


async def test_transfer_records_the_notice_rather_than_writing_it(monkeypatch):
    set_context(user_id="user-handoff-1", item_id="item-1")

    fake_memory = MagicMock()
    monkeypatch.setattr(bot, "conversation_memory", fake_memory)
    fake_broadcast = MagicMock()
    monkeypatch.setattr("core.broadcast.broadcast_to_chat", fake_broadcast)
    monkeypatch.setattr("core.connector.admin_supabase", MagicMock())
    monkeypatch.setattr("core.email_service.send_human_transfer_alert", MagicMock())

    await bot.transfer_to_human.ainvoke(
        {
            "reason": "Cash-on-delivery arrangement requested",
            "summary": "Buyer wants to meet up and pay cash.",
        }
    )

    notice = pending_handoff.get()
    assert notice and "transferred" in notice.lower()
    assert not fake_memory.add_message.called, "the separator jumped the reply"
    assert not fake_broadcast.called, "the separator went out mid-turn"


async def test_transfer_still_pauses_the_ai_and_alerts_terry_immediately(monkeypatch):
    """Only the separator is deferred. The decision itself is not: a second
    message arriving in the meantime must not be answered by the agent."""
    set_context(user_id="user-handoff-2", item_id=None)

    monkeypatch.setattr(bot, "conversation_memory", MagicMock())
    monkeypatch.setattr("core.broadcast.broadcast_to_chat", MagicMock())
    fake_supabase = MagicMock()
    monkeypatch.setattr("core.connector.admin_supabase", fake_supabase)
    fake_alert = MagicMock(return_value=True)
    monkeypatch.setattr("core.email_service.send_human_transfer_alert", fake_alert)

    await bot.transfer_to_human.ainvoke({"reason": "Dispute", "summary": ""})

    upserted = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert upserted["ai_enabled"] is False
    assert upserted["admin_intervening"] is True
    assert fake_alert.call_args.kwargs["reason"] == "Dispute"


async def test_a_turn_with_no_handoff_leaves_nothing_pending(monkeypatch):
    """`set_context` clears it, so one buyer's handoff cannot separate the
    next buyer's conversation."""
    set_context(user_id="user-handoff-3", item_id=None)
    assert pending_handoff.get() is None


# ---------------------------------------------------------------------------
# Scenario 6 — the turn runner writes it, after the reply
# ---------------------------------------------------------------------------


async def test_notice_is_persisted_and_broadcast_after_the_reply(monkeypatch, turn_env):
    record = turn_env("handoff-order")

    async def stream(user_id, message, item_id=None, files=None):
        """A COD turn, shaped like the real `agent.bot.chat_stream`: it writes
        the buyer's message, the tool hands over, then the agent says goodbye
        and the reply is persisted on the way out."""
        from domains.negotiation.memory import conversation_memory

        conversation_memory.add_message(user_id, "human", message, item_id, source="human")
        pending_handoff.set("--- transferred to Terry ---")
        yield "Ah, COD isn't something I can set up here"
        conversation_memory.add_message(user_id, "ai", "Ah, COD isn't something I can set up here", item_id)

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", stream)

    response = await chat_stream(_make_request("handoff-order", "boleh cod x?"))
    async for _ in response.body_iterator:
        pass
    await _settle()

    roles = [role for _, role, _ in record["persisted"]]
    assert roles == ["human", "ai", "system"], f"transcript out of order: {roles}"
    assert record["persisted"][-1][2] == "--- transferred to Terry ---"

    sources = [source for *_, source in record["broadcast"]]
    assert sources == ["human", "ai", "system"], f"broadcast out of order: {sources}"
    assert pending_handoff.get() is None, "a drained notice must not fire twice"


async def test_notice_survives_a_turn_that_broke_after_the_handoff(monkeypatch, turn_env):
    """The AI is already switched off by then, so a swallowed separator would
    leave the buyer waiting on an agent that is never going to answer."""
    record = turn_env("handoff-error")

    async def stream(user_id, message, item_id=None, files=None):
        pending_handoff.set("--- transferred to Terry ---")
        yield "Let me pass you to Terry"
        raise RuntimeError("provider fell over")

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", stream)

    response = await chat_stream(_make_request("handoff-error"))
    async for _ in response.body_iterator:
        pass
    await _settle()

    system_messages = [m for m in record["persisted"] if m[1] == "system"]
    assert system_messages == [("handoff-error", "system", "--- transferred to Terry ---")]
    assert [b for b in record["broadcast"] if b[3] == "system"]
