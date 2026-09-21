"""SPEC-060 — the agent turn belongs to the conversation, not to the response.

Send a message, close the tab, come back: no reply, ever.

The turn ran inside the `StreamingResponse` generator, so a hang-up cancelled
it. `agent.bot.chat_stream` never reached its trailing `add_message`, the route
never reached `broadcast_to_chat`, and the buyer's own message — written before
the first yield — was left in the transcript looking like a question the seller
ignored.

These tests drive the endpoint's generator directly rather than going through
the ASGI client: closing an `httpx` response is not the same event as the
server-side generator being closed, and it is precisely the server-side close
that used to kill the turn.
"""

import asyncio
import json

from starlette.requests import Request

from conftest import make_supabase_result
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


def fake_verify_user_token(user_id):
    async def _fake(request):
        return user_id

    return _fake


async def _hang_up_after_first_token(response):
    """Read frames until the first real token lands, then walk away."""
    body = response.body_iterator
    async for frame in body:
        if "text-delta" in frame:
            break
    await body.aclose()


async def _settle(deadline=2.0):
    """Give the detached turn a chance to finish."""
    loop_deadline = asyncio.get_running_loop().time() + deadline
    while asyncio.get_running_loop().time() < loop_deadline:
        await asyncio.sleep(0.01)
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()]
        if not pending:
            return
    return


# ---------------------------------------------------------------------------
# the turn finishes even though nobody is listening
# ---------------------------------------------------------------------------


async def test_abandoned_turn_still_persists_the_full_reply(monkeypatch, turn_env):
    record = turn_env("detached-persist")

    # Mirrors the real `agent.bot.chat_stream`, whose trailing `add_message` is
    # the only thing that ever writes an AI reply to the transcript. Cancelling
    # the generator is what used to skip it.
    async def stream(user_id, message, item_id=None, files=None):
        collected = []
        for delta in ("RM240 ", "can lah"):
            collected.append(delta)
            yield delta
            await asyncio.sleep(0.05)
        from domains.negotiation.memory import conversation_memory

        conversation_memory.add_message(user_id, "ai", "".join(collected), item_id)

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", stream)

    response = await chat_stream(_make_request("detached-persist"))
    await _hang_up_after_first_token(response)
    await _settle()

    ai_messages = [m for m in record["persisted"] if m[1] == "ai"]
    assert ai_messages, "the reply was never persisted after the buyer hung up"
    assert ai_messages[0][2] == "RM240 can lah", f"only a fragment survived the hang-up: {ai_messages}"


async def test_abandoned_turn_still_broadcasts_the_reply(monkeypatch, turn_env):
    record = turn_env("detached-broadcast")

    async def stream(user_id, message, item_id=None, files=None):
        yield "Still "
        await asyncio.sleep(0.05)
        yield "here!"

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", stream)

    response = await chat_stream(_make_request("detached-broadcast"))
    await _hang_up_after_first_token(response)
    await _settle()

    ai_broadcasts = [b for b in record["broadcast"] if b[3] == "ai"]
    assert ai_broadcasts == [("detached-broadcast", "Still here!", "ai", "ai")]


async def test_reply_to_an_absent_buyer_is_queued_for_the_digest(monkeypatch, turn_env):
    """Nothing is listening on their SSE stream, so the reply takes the same
    batched-email path a seller message takes (SPEC-052)."""
    record = turn_env("detached-digest", subscribed=False)

    async def stream(user_id, message, item_id=None, files=None):
        yield "Deal at RM240"

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", stream)

    response = await chat_stream(_make_request("detached-digest"))
    async for _ in response.body_iterator:
        pass
    await _settle()

    assert record["queued"] == [("detached-digest", "Deal at RM240")]


async def test_reply_to_a_present_buyer_is_not_queued(monkeypatch, turn_env):
    """They are on the stream; they already have it."""
    record = turn_env("detached-live", subscribed=True)

    async def stream(user_id, message, item_id=None, files=None):
        yield "Deal at RM240"

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", stream)

    response = await chat_stream(_make_request("detached-live"))
    async for _ in response.body_iterator:
        pass
    await _settle()

    assert record["queued"] == []


async def test_abandoned_turn_is_charged_once_for_everything_it_generated(monkeypatch, turn_env):
    """SPEC-044 B still holds: the budget is settled exactly once, and now it
    covers the tokens produced after the buyer stopped reading."""
    record = turn_env("detached-budget")

    async def stream(user_id, message, item_id=None, files=None):
        yield "a"
        await asyncio.sleep(0.05)
        yield "b" * 400

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", stream)

    response = await chat_stream(_make_request("detached-budget"))
    await _hang_up_after_first_token(response)
    await _settle()

    assert len(record["charged"]) == 1, f"charged {len(record['charged'])} times"
    assert record["charged"][0][2] > 50, f"the charge only covered the fragment the buyer saw: {record['charged'][0]}"


async def test_detached_turn_still_respects_the_deadline(monkeypatch, turn_env):
    """An abandoned turn must end, charge and persist — not run forever."""
    record = turn_env("detached-deadline")
    monkeypatch.setattr("domains.negotiation.routes.CHAT_TURN_DEADLINE_SECONDS", 0.2)

    async def hanging(user_id, message, item_id=None, files=None):
        yield "thinking"
        await asyncio.sleep(30)
        yield "never arrives"

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", hanging)

    response = await chat_stream(_make_request("detached-deadline"))
    await _hang_up_after_first_token(response)
    await _settle(deadline=3.0)

    assert len(record["charged"]) == 1
    assert [b for b in record["broadcast"] if b[3] == "ai"], "a timed-out turn still generated text and must deliver it"


async def test_hanging_up_does_not_cancel_the_agent_generator(monkeypatch, turn_env):
    """The generator's own `finally` is what releases the LLM lease. It must run
    because the turn ENDED, not because the socket closed."""
    turn_env("detached-lease")
    outcome = {}

    async def stream(user_id, message, item_id=None, files=None):
        try:
            yield "one"
            await asyncio.sleep(0.05)
            yield "two"
            outcome["completed"] = True
        except asyncio.CancelledError:
            outcome["cancelled"] = True
            raise
        except GeneratorExit:
            outcome["closed"] = True
            raise

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", stream)

    response = await chat_stream(_make_request("detached-lease"))
    await _hang_up_after_first_token(response)
    await _settle()

    assert outcome.get("completed"), f"the turn was killed by the hang-up: {outcome}"


# ---------------------------------------------------------------------------
# ...and the buyer who walked away actually gets told
# ---------------------------------------------------------------------------


async def test_the_reply_reaches_a_live_stream_on_another_page(monkeypatch, patch_supabase, fake_supabase):
    """The whole point of finishing the turn: the buyer sent a message, went
    back to the storefront, and the answer has to reach the chip on the header
    without them reloading the site.

    Deliberately does NOT stub `broadcast_to_chat` — the mocked-out version is
    what the tests above assert against, and it cannot tell us whether the
    broker ever hears about the reply.
    """
    from core.notifications import notification_broker

    user_id = "delivered-live"
    monkeypatch.setattr("domains.negotiation.routes.verify_user_token", fake_verify_user_token(user_id))
    (fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value) = make_supabase_result(
        []
    )
    patch_supabase("domains.negotiation.routes", admin=fake_supabase)
    monkeypatch.setattr("domains.negotiation.memory.conversation_memory.add_message", lambda *a, **k: None)
    monkeypatch.setattr("domains.negotiation.routes.track_ai_tokens", lambda *a, **k: None)

    async def stream(user_id, message, item_id=None, files=None):
        yield "RM240 "
        await asyncio.sleep(0.05)
        yield "can lah"

    monkeypatch.setattr("domains.negotiation.bot.chat_stream", stream)

    # The header's notification stream, open on whatever page they walked to.
    queue = await notification_broker.subscribe(user_id)
    try:
        response = await chat_stream(_make_request(user_id))
        await _hang_up_after_first_token(response)
        await _settle()

        assert not queue.empty(), "the reply never reached the buyer's live stream"

        # Since SPEC-094 the one stream carries both halves of the exchange —
        # the buyer's own text too, so the admin console stays in sync — so pick
        # out the reply rather than assuming it arrived first.
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        reply = next(e for e in events if e.get("source") == "ai")
        assert reply["type"] == "new_message"
        assert reply["message"] == "RM240 can lah"
        assert reply["notify"] is True

        own = next(e for e in events if e.get("source") == "human")
        assert own["notify"] is False, "the buyer must not be toasted for their own message"
    finally:
        await notification_broker.unsubscribe(user_id, queue)
