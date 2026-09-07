"""SPEC-043 Workstream D — backpressure and the rest of the blocking-call gap.

Two distinct defects, both on the hot path of every request:

1. **No applied rate limits.** `slowapi` is constructed in `limiter.py` and
   registered on the app in `main.py`, but `@limiter.limit(...)` decorated
   zero routes — so the whole thing was inert. Nothing shed load before
   saturation, which turns an overload into rising latency instead of a clean
   429.
2. **Synchronous Redis on the event loop.** SPEC-023 moved the *Supabase* half
   of `verify_user_token`'s lookup off-loop but left the Redis `GET` beside it
   synchronous, and never touched `check_rate_limit` / `check_ai_token_limit` /
   `track_ai_tokens` in `routes/chat.py`. Redis is fast enough that this hid on
   a loopback socket; it stops hiding the moment the box is under CPU pressure.

The loop-tick idiom below is the one SPEC-023 introduced in
`test_auth_middleware.py`: run a ticker coroutine alongside the call under
test and assert it kept advancing. Zero ticks means the loop was blocked.
"""

import asyncio
import contextlib
import json
import os
import sys
import time
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from slowapi.errors import RateLimitExceeded

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@contextlib.asynccontextmanager
async def loop_ticks():
    """Count event-loop turns while the block runs. Zero means it was blocked."""
    counter = {"ticks": 0}

    async def ticker():
        while True:
            await asyncio.sleep(0.01)
            counter["ticks"] += 1

    beat = asyncio.create_task(ticker())
    try:
        yield counter
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat


def slow(return_value, delay=0.2):
    """A synchronous stand-in that sleeps — i.e. blocks whatever thread runs it."""
    def _call(*_args, **_kwargs):
        time.sleep(delay)
        return return_value
    return _call


# ---------------------------------------------------------------------------
# D — the Redis calls SPEC-023 didn't cover stay off the event loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_token_cache_lookup_does_not_block_the_event_loop(monkeypatch):
    """`get_cached_user_by_token` runs on every authenticated request.

    SPEC-023's comment in this very function explains why the Supabase call
    below it is threaded — the Redis GET above it was left synchronous.
    """
    import auth_middleware

    monkeypatch.setattr(auth_middleware, "get_cached_user_by_token", slow("cached-user"))
    monkeypatch.setattr(auth_middleware, "_is_user_banned", lambda _uid: False)

    from types import SimpleNamespace
    request = SimpleNamespace(headers={"Authorization": "Bearer warm-token"}, query_params={})

    async with loop_ticks() as counter:
        user_id = await auth_middleware.verify_user_token(request)

    assert user_id == "cached-user"
    assert counter["ticks"] > 5


@pytest.mark.asyncio
async def test_chat_rate_limit_check_does_not_block_the_event_loop(
    client, monkeypatch, patch_supabase, fake_supabase
):
    """The per-user message limiter is consulted before every single turn."""
    import routes.chat as chat_routes

    async def _fake_verify(_request):
        return "u1"

    monkeypatch.setattr(chat_routes, "verify_user_token", _fake_verify)
    # False => cooldown path, which short-circuits before the agent runs.
    monkeypatch.setattr(chat_routes, "check_rate_limit", slow(False))
    patch_supabase("routes.chat", admin=fake_supabase)

    async with loop_ticks() as counter:
        resp = await client.post(
            "/chat/stream",
            json={"user_id": "u1", "message": "hi"},
            headers={"Authorization": "Bearer t"},
        )
        # StreamingResponse bodies are lazy — read it so the generator runs.
        _ = resp.text

    assert counter["ticks"] > 5


@pytest.mark.asyncio
async def test_ai_token_budget_check_does_not_block_the_event_loop(
    client, monkeypatch, patch_supabase, fake_supabase
):
    import routes.chat as chat_routes

    async def _fake_verify(_request):
        return "u2"

    monkeypatch.setattr(chat_routes, "verify_user_token", _fake_verify)
    monkeypatch.setattr(chat_routes, "check_rate_limit", lambda *a, **k: True)
    monkeypatch.setattr(chat_routes, "check_ai_token_limit", slow((False, 999)))
    patch_supabase("routes.chat", admin=fake_supabase)

    import agent.memory as memory_module
    monkeypatch.setattr(memory_module.conversation_memory, "add_message", lambda *a, **k: None)

    import payment.fulfillment as fulfillment
    monkeypatch.setattr(fulfillment, "broadcast_to_chat", lambda *a, **k: None)

    async with loop_ticks() as counter:
        resp = await client.post(
            "/chat/stream",
            json={"user_id": "u2", "message": "hi"},
            headers={"Authorization": "Bearer t"},
        )
        _ = resp.text

    assert counter["ticks"] > 5


@pytest.mark.asyncio
async def test_token_usage_tracking_does_not_block_the_event_loop(
    client, monkeypatch, patch_supabase, fake_supabase
):
    """`track_ai_tokens` runs after every completed turn."""
    import routes.chat as chat_routes

    async def _fake_verify(_request):
        return "u3"

    monkeypatch.setattr(chat_routes, "verify_user_token", _fake_verify)
    monkeypatch.setattr(chat_routes, "check_rate_limit", lambda *a, **k: True)
    monkeypatch.setattr(chat_routes, "check_ai_token_limit", lambda *a, **k: (True, 0))
    monkeypatch.setattr(chat_routes, "track_ai_tokens", slow(None))
    patch_supabase("routes.chat", admin=fake_supabase)

    import agent.bot as bot_module

    async def _fake_stream(**_kwargs):
        yield "hello"

    monkeypatch.setattr(bot_module, "chat_stream", _fake_stream)

    import payment.fulfillment as fulfillment
    monkeypatch.setattr(fulfillment, "broadcast_to_chat", lambda *a, **k: None)

    async with loop_ticks() as counter:
        resp = await client.post(
            "/chat/stream",
            json={"user_id": "u3", "message": "hi"},
            headers={"Authorization": "Bearer t"},
        )
        _ = resp.text

    assert counter["ticks"] > 5


# ---------------------------------------------------------------------------
# D — the Redis connection pool is bounded
# ---------------------------------------------------------------------------

def test_redis_client_is_created_with_an_explicit_max_connections(monkeypatch):
    """An unbounded pool lets a burst open connections without limit."""
    import cache

    captured = {}

    def _fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        client = MagicMock()
        client.ping.return_value = True
        return client

    monkeypatch.setattr(cache.redis, "from_url", _fake_from_url)
    monkeypatch.setattr(cache, "REDIS_URL", "redis://localhost:6379")

    cache._create_redis_client()

    assert captured["kwargs"].get("max_connections") is not None
    assert captured["kwargs"]["max_connections"] > 0


# ---------------------------------------------------------------------------
# D — rate limits are actually applied to routes
# ---------------------------------------------------------------------------

def _limited_endpoint_names():
    """slowapi records every decorated endpoint in `_route_limits`, keyed by
    the endpoint's qualified name."""
    from limiter import limiter
    return set(limiter._route_limits.keys())


@pytest.mark.parametrize(
    "endpoint_name",
    [
        "notifications_stream",
        "get_all_items",
        "get_featured",
        "get_item_by_id",
        "checkout",
    ],
)
def test_hot_endpoints_have_a_rate_limit_applied(endpoint_name):
    """Registering the limiter without decorating anything is inert config."""
    applied = _limited_endpoint_names()
    assert any(endpoint_name in name for name in applied), (
        f"{endpoint_name} has no @limiter.limit — applied limits: {sorted(applied)}"
    )


@pytest.mark.asyncio
async def test_the_shared_limiter_actually_rejects_over_its_limit():
    """Proves enforcement end-to-end against the app's own limiter instance,
    without firing a production-sized number of requests at a real route."""
    from slowapi import _rate_limit_exceeded_handler

    from limiter import limiter

    probe = FastAPI()
    probe.state.limiter = limiter
    probe.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @probe.get("/probe")
    @limiter.limit("2/minute")
    async def _probe(request: Request):  # noqa: ARG001 — slowapi requires the param
        return {"ok": True}

    was_enabled = limiter.enabled
    limiter.enabled = True
    try:
        async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://test") as ac:
            first = await ac.get("/probe")
            second = await ac.get("/probe")
            third = await ac.get("/probe")
    finally:
        limiter.enabled = was_enabled
        limiter.reset()

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


@pytest.mark.asyncio
async def test_a_rate_limited_route_still_answers_normally_under_the_limit(
    client, monkeypatch
):
    """Applying limits must not change the happy path."""
    import routes.items as routes_items

    monkeypatch.setattr(
        routes_items, "get_items",
        lambda keyword=None: [{"id": "item-1", "name": "Widget", "image_path": None}],
    )

    resp = await client.get("/items")
    assert resp.status_code == 200
    body = json.loads(resp.text)
    assert isinstance(body, list)
    assert body[0]["item_id"] == "item-1"
