"""Every turn that spends tokens must charge for them. (SPEC-044 B)

`routes/chat.py` charged `track_ai_tokens` on exactly one code path — the one
where the stream ran to completion. The timeout branch and the exception branch
both `return` before reaching it, and a client that hangs up mid-stream never
reaches it at all.

So the 1M-tokens-per-30-minutes ceiling could not be hit by anyone who didn't
want to hit it. Send a message, let the model start generating, abort. The
tokens were spent upstream and billed by the provider; the counter stayed at
zero. Repeat. The budget was only ever enforced against well-behaved clients,
which are not the ones a budget exists to stop.

These tests assert the property per exit path rather than per branch, because
the branch that leaks is always the one nobody remembered to instrument.

The abandonment test drives the endpoint's generator directly instead of going
through the ASGI client: closing an `httpx` response is not the same event as
the server-side generator being closed, and it is precisely the server-side
close that has to do the accounting.
"""

import asyncio
import json

import pytest
from starlette.requests import Request

from conftest import make_supabase_result
from routes.chat import chat_stream


def set_chat_settings_select(fake_supabase, data):
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .execute.return_value
    ) = make_supabase_result(data)


def fake_verify_user_token(user_id):
    async def _fake(request):
        return user_id
    return _fake


def _make_request(user_id, message="hi"):
    """A minimal ASGI POST carrying a JSON body, good enough for the handler's
    `await request.json()` and its header reads."""
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


@pytest.fixture
def budget(monkeypatch):
    """Records every charge against the AI token budget."""
    calls = []
    monkeypatch.setattr(
        "routes.chat.track_ai_tokens",
        lambda uid, inp, out: calls.append((uid, inp, out)),
    )
    return calls


@pytest.fixture
def chat_env(monkeypatch, patch_supabase, fake_supabase):
    """Wires up the collaborators every streaming test needs, so each test body
    only has to supply the turn it wants to exercise."""
    def _setup(user_id):
        monkeypatch.setattr(
            "routes.chat.verify_user_token", fake_verify_user_token(user_id)
        )
        set_chat_settings_select(fake_supabase, [])
        patch_supabase("routes.chat", admin=fake_supabase)
        monkeypatch.setattr(
            "agent.memory.conversation_memory.add_message",
            lambda *a, **k: None,
        )
        # Imported lazily inside `generate()` (`from payment.fulfillment import
        # broadcast_to_chat`), so the patch has to land on the source module.
        monkeypatch.setattr(
            "payment.fulfillment.broadcast_to_chat", lambda *a, **k: None
        )
        return fake_supabase

    return _setup


# ---------------------------------------------------------------------------
# every exit path settles the budget
# ---------------------------------------------------------------------------

async def test_completed_turn_is_charged_once(client, monkeypatch, chat_env, budget):
    user_id = "budget-ok"
    chat_env(user_id)

    async def stream(user_id, message, item_id=None, files=None):
        yield "Hello "
        yield "world!"

    monkeypatch.setattr("agent.bot.chat_stream", stream)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "Hi there"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    assert len(budget) == 1, f"expected exactly one charge, got {budget}"
    charged_user, input_tokens, output_tokens = budget[0]
    assert charged_user == user_id
    assert input_tokens > 0
    assert output_tokens > 0


async def test_timed_out_turn_is_still_charged(client, monkeypatch, chat_env, budget):
    """The model generated tokens right up to the deadline. They cost the same
    as tokens that arrived in time."""
    user_id = "budget-timeout"
    chat_env(user_id)
    monkeypatch.setattr("routes.chat.CHAT_TURN_DEADLINE_SECONDS", 0.15)

    async def hanging(user_id, message, item_id=None, files=None):
        yield "partial answer"
        await asyncio.sleep(30)
        yield "never arrives"

    monkeypatch.setattr("agent.bot.chat_stream", hanging)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "Hi there"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    assert len(budget) == 1, f"a timed-out turn must be charged: {budget}"
    assert budget[0][2] > 0, "the partial output was generated and must be charged"


async def test_errored_turn_is_still_charged(client, monkeypatch, chat_env, budget):
    """A turn that blows up after streaming half an answer has already spent
    everything it streamed."""
    user_id = "budget-error"
    chat_env(user_id)

    async def exploding(user_id, message, item_id=None, files=None):
        yield "half an answer"
        raise RuntimeError("upstream fell over")

    monkeypatch.setattr("agent.bot.chat_stream", exploding)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "Hi there"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    assert len(budget) == 1, f"an errored turn must be charged: {budget}"


async def test_abandoned_turn_is_charged_when_it_finishes(monkeypatch, chat_env, budget):
    """The actual abuse case: start a turn, read a token, hang up.

    SPEC-060 changed WHEN this settles, not whether it does. The turn used to be
    killed by the hang-up, so the charge had to happen in the generator's
    cleanup and could only ever cover the fragment already streamed. The turn
    now outlives the response, so it charges on its own way out — for
    everything it generated, including the tokens produced after the buyer
    stopped reading. Aborting on the first token buys nothing.
    """
    user_id = "budget-abandoned"
    chat_env(user_id)

    finished = asyncio.Event()

    async def slow(user_id, message, item_id=None, files=None):
        yield "first chunk"
        await asyncio.sleep(0.05)
        yield "the rest of a real answer, generated whether or not anyone reads it"
        finished.set()

    monkeypatch.setattr("agent.bot.chat_stream", slow)

    response = await chat_stream(_make_request(user_id))
    body = response.body_iterator

    # Pull frames until the first real token has been streamed, then walk away
    # exactly as a closed browser tab does.
    async for frame in body:
        if "first chunk" in frame:
            break

    assert not budget, "nothing should be charged while the turn is still open"

    await body.aclose()
    await asyncio.wait_for(finished.wait(), timeout=2)
    # The charge lands in the producer's tail, one scheduler pass after the
    # agent's last yield.
    for _ in range(50):
        if budget:
            break
        await asyncio.sleep(0.01)

    assert len(budget) == 1, f"an abandoned turn must be charged: {budget}"
    assert budget[0][0] == user_id
    assert budget[0][2] > 10, (
        f"the charge must cover what the model generated unwatched: {budget}"
    )


async def test_abandoned_turn_is_not_charged_twice_when_it_also_completed(
    monkeypatch, chat_env, budget
):
    """Closing a generator that already ran to completion must not re-charge:
    the success path and the cleanup path both settle the budget, and only one
    of them may take effect."""
    user_id = "budget-once"
    chat_env(user_id)

    async def stream(user_id, message, item_id=None, files=None):
        yield "done"

    monkeypatch.setattr("agent.bot.chat_stream", stream)

    response = await chat_stream(_make_request(user_id))
    body = response.body_iterator

    async for _ in body:
        pass
    await body.aclose()

    assert len(budget) == 1, f"charged more than once: {budget}"


# ---------------------------------------------------------------------------
# turns where no model ran are still free
# ---------------------------------------------------------------------------

async def test_turn_is_not_charged_when_ai_is_disabled(
    client, monkeypatch, chat_env, budget, fake_supabase
):
    user_id = "budget-ai-off"
    chat_env(user_id)
    set_chat_settings_select(fake_supabase, [{"ai_enabled": False}])

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "Hi there"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    assert budget == [], "no model ran, so there is nothing to charge"


async def test_turn_is_not_charged_when_already_over_the_budget(
    client, monkeypatch, chat_env, budget
):
    """The over-limit reply is a canned string, not a generated one."""
    user_id = "budget-exceeded"
    chat_env(user_id)
    monkeypatch.setattr(
        "routes.chat.check_ai_token_limit", lambda uid: (False, 1_500_000)
    )

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "Hi there"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    assert budget == [], "the hand-over message costs no model tokens"
