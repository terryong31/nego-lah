"""Tests for routes/chat.py — chat history, chat settings, and the SSE
/chat/stream endpoint.

Mocking notes specific to this file (see conftest.py's module docstring for
the full rationale):
- `admin_supabase` is imported at module level (`from connector import
  admin_supabase`) in routes/chat.py, so it's patched via
  `patch_supabase("routes.chat", admin=...)`.
- `/chat/stream` calls `await verify_user_token(request)` directly in the
  handler body, NOT via `Depends(...)` -- `app.dependency_overrides` has no
  effect there. We monkeypatch `routes.chat.verify_user_token` directly.
- `check_rate_limit`, `check_ai_token_limit`, and `track_ai_tokens` are all
  imported by name into routes.chat (`from cache import ...`), so they're
  patched as `routes.chat.<name>`.
- `agent.memory.conversation_memory` is a module-level singleton imported
  lazily (inside function bodies) in routes/chat.py. Its methods internally
  reach for the REAL `connector.admin_supabase` (a separate binding from
  routes.chat's), which would attempt a real network call if invoked
  un-mocked. Every test that exercises a code path calling
  `conversation_memory.add_message` / `get_history_page` / `clear_history`
  monkeypatches that method directly on the singleton instance
  (`agent.memory.conversation_memory`) rather than trying to route it
  through `fake_supabase`.
- `agent.bot.chat_stream` is imported lazily inside `/chat/stream`'s
  `generate()` closure (`from agent.bot import chat_stream`), so
  monkeypatching the `chat_stream` attribute on the already-imported
  `agent.bot` module takes effect on the next call (the lazy import
  re-resolves the name at call time).
"""

import json

from conftest import make_supabase_result

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def parse_sse(text: str):
    """Split a raw SSE response body into a list of parsed frames.

    Each frame is either a dict (for `data: {...}` JSON lines) or the literal
    string "[DONE]" for the terminal sentinel line.
    """
    frames = []
    for chunk in text.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        assert chunk.startswith("data: ")
        payload = chunk[len("data: "):]
        if payload == "[DONE]":
            frames.append("[DONE]")
        else:
            frames.append(json.loads(payload))
    return frames


def set_chat_settings_select(fake_supabase, data):
    """Wire up admin_supabase.table('chat_settings').select(...).eq(...).execute()"""
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .execute.return_value
    ) = make_supabase_result(data)


async def fake_verify_user_token_factory(user_id):
    async def _fake(request):
        return user_id
    return _fake


# ---------------------------------------------------------------------------
# GET /chat/history/{user_id}
# ---------------------------------------------------------------------------

async def test_get_chat_history_success(client, auth_user, monkeypatch):
    auth_user("user-1")
    page = {"messages": [{"role": "human", "content": "hi", "source": "human"}],
            "has_more": False, "next_offset": 1}
    calls = {}

    def fake_get_history_page(user_id, limit=20, offset=0):
        calls["args"] = (user_id, limit, offset)
        return page

    monkeypatch.setattr("agent.memory.conversation_memory.get_history_page", fake_get_history_page)

    resp = await client.get("/chat/history/user-1")

    assert resp.status_code == 200
    assert resp.json() == page
    assert calls["args"] == ("user-1", 20, 0)


async def test_get_chat_history_custom_pagination(client, auth_user, monkeypatch):
    auth_user("user-1")
    calls = {}

    def fake_get_history_page(user_id, limit=20, offset=0):
        calls["args"] = (user_id, limit, offset)
        return {"messages": [], "has_more": True, "next_offset": offset + limit}

    monkeypatch.setattr("agent.memory.conversation_memory.get_history_page", fake_get_history_page)

    resp = await client.get("/chat/history/user-1?limit=5&offset=10")

    assert resp.status_code == 200
    assert calls["args"] == ("user-1", 5, 10)
    assert resp.json()["next_offset"] == 15


async def test_get_chat_history_id_mismatch(client, auth_user, monkeypatch):
    auth_user("user-1")
    monkeypatch.setattr("agent.memory.conversation_memory.get_history_page", lambda *a, **k: {})

    resp = await client.get("/chat/history/someone-else")

    assert resp.status_code == 403
    assert "User ID mismatch" in resp.json()["detail"]


async def test_get_chat_history_exception_returns_500(client, auth_user, monkeypatch):
    auth_user("user-1")

    def boom(*a, **k):
        raise RuntimeError("db exploded")

    monkeypatch.setattr("agent.memory.conversation_memory.get_history_page", boom)

    resp = await client.get("/chat/history/user-1")

    assert resp.status_code == 500
    assert "db exploded" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# DELETE /chat/history/{user_id}
# ---------------------------------------------------------------------------

async def test_clear_chat_history_success(client, auth_user, monkeypatch):
    auth_user("user-1")
    calls = []
    monkeypatch.setattr(
        "agent.memory.conversation_memory.clear_history",
        lambda user_id: calls.append(user_id),
    )

    resp = await client.delete("/chat/history/user-1")

    assert resp.status_code == 200
    assert resp.json() == {"message": "Chat history cleared"}
    assert calls == ["user-1"]


async def test_clear_chat_history_id_mismatch(client, auth_user, monkeypatch):
    auth_user("user-1")
    monkeypatch.setattr("agent.memory.conversation_memory.clear_history", lambda user_id: None)

    resp = await client.delete("/chat/history/someone-else")

    assert resp.status_code == 403


async def test_clear_chat_history_exception_returns_500(client, auth_user, monkeypatch):
    auth_user("user-1")

    def boom(user_id):
        raise RuntimeError("cannot delete")

    monkeypatch.setattr("agent.memory.conversation_memory.clear_history", boom)

    resp = await client.delete("/chat/history/user-1")

    assert resp.status_code == 500
    assert "cannot delete" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /chat/settings/{user_id}
# ---------------------------------------------------------------------------

async def test_get_chat_settings_defaults_true_when_no_row(client, auth_user, patch_supabase, fake_supabase):
    auth_user("user-1")
    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    resp = await client.get("/chat/settings/user-1")

    assert resp.status_code == 200
    assert resp.json() == {"ai_enabled": True}


async def test_get_chat_settings_returns_stored_false(client, auth_user, patch_supabase, fake_supabase):
    auth_user("user-1")
    set_chat_settings_select(fake_supabase, [{"ai_enabled": False}])
    patch_supabase("routes.chat", admin=fake_supabase)

    resp = await client.get("/chat/settings/user-1")

    assert resp.status_code == 200
    assert resp.json() == {"ai_enabled": False}


async def test_get_chat_settings_row_missing_key_defaults_true(client, auth_user, patch_supabase, fake_supabase):
    auth_user("user-1")
    set_chat_settings_select(fake_supabase, [{}])
    patch_supabase("routes.chat", admin=fake_supabase)

    resp = await client.get("/chat/settings/user-1")

    assert resp.status_code == 200
    assert resp.json() == {"ai_enabled": True}


async def test_get_chat_settings_exception_defaults_true(client, auth_user, patch_supabase, fake_supabase):
    auth_user("user-1")
    fake_supabase.table.side_effect = RuntimeError("supabase down")
    patch_supabase("routes.chat", admin=fake_supabase)

    resp = await client.get("/chat/settings/user-1")

    assert resp.status_code == 200
    assert resp.json() == {"ai_enabled": True}


async def test_get_chat_settings_id_mismatch(client, auth_user, patch_supabase, fake_supabase):
    auth_user("user-1")
    patch_supabase("routes.chat", admin=fake_supabase)

    resp = await client.get("/chat/settings/someone-else")

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /chat/stream
# ---------------------------------------------------------------------------

async def test_chat_stream_happy_path(client, monkeypatch, patch_supabase, fake_supabase):
    user_id = "user-happy"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    # ai_enabled check inside generate(): no row -> defaults to enabled.
    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    recorded_calls = []

    async def fake_chat_stream(user_id, message, item_id=None, files=None):
        recorded_calls.append({"user_id": user_id, "message": message, "item_id": item_id, "files": files})
        yield {"status": "thinking"}
        yield "Hello "
        yield "world!"

    monkeypatch.setattr("agent.bot.chat_stream", fake_chat_stream)

    track_calls = []
    monkeypatch.setattr(
        "routes.chat.track_ai_tokens",
        lambda uid, inp, out: track_calls.append((uid, inp, out)),
    )

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "Hi there", "item_id": "item-1"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-vercel-ai-ui-message-stream"] == "v1"

    frames = parse_sse(resp.text)
    assert frames[0] == {"type": "start"}
    assert {"type": "text-start", "id": "0"} in frames
    assert {"type": "text-delta", "id": "0", "delta": "[[STATUS:thinking]]"} in frames
    assert {"type": "text-delta", "id": "0", "delta": "Hello "} in frames
    assert {"type": "text-delta", "id": "0", "delta": "world!"} in frames
    assert {"type": "text-end", "id": "0"} in frames
    assert frames[-2] == {"type": "finish"}
    assert frames[-1] == "[DONE]"

    assert recorded_calls == [
        {"user_id": user_id, "message": "Hi there", "item_id": "item-1", "files": None}
    ]
    assert len(track_calls) == 1
    assert track_calls[0][0] == user_id


async def test_chat_stream_multipart_with_file_and_empty_message(client, monkeypatch, patch_supabase, fake_supabase):
    user_id = "user-multipart"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    recorded_calls = []

    async def fake_chat_stream(user_id, message, item_id=None, files=None):
        recorded_calls.append({"user_id": user_id, "message": message, "item_id": item_id, "files": files})
        yield "ok"

    monkeypatch.setattr("agent.bot.chat_stream", fake_chat_stream)
    monkeypatch.setattr("routes.chat.track_ai_tokens", lambda *a, **k: None)

    resp = await client.post(
        "/chat/stream",
        data={"user_id": user_id, "message": "", "item_id": "item-42"},
        files=[("files", ("test.png", b"binary-content", "image/png"))],
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    frames = parse_sse(resp.text)
    assert frames[0] == {"type": "start"}
    assert frames[-1] == "[DONE]"

    assert len(recorded_calls) == 1
    call = recorded_calls[0]
    assert call["user_id"] == user_id
    # Empty message + files present falls back to the canned analyze message.
    assert call["message"] == "Please analyze these files."
    assert call["item_id"] == "item-42"
    assert call["files"] == [
        {"name": "test.png", "type": "image/png", "data": "YmluYXJ5LWNvbnRlbnQ="}
    ]


async def test_chat_stream_missing_message_and_files_returns_400(client, monkeypatch):
    user_id = "user-empty"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": ""},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 400
    assert "message or files are required" in resp.json()["detail"]


async def test_chat_stream_user_id_mismatch_returns_403(client, monkeypatch):
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory("token-user"))

    resp = await client.post(
        "/chat/stream",
        json={"user_id": "someone-else", "message": "hi"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 403


async def test_chat_stream_invalid_token_propagates_401(client, monkeypatch):
    from fastapi import HTTPException

    async def fake_verify(request):
        raise HTTPException(status_code=401, detail="Invalid token")

    monkeypatch.setattr("routes.chat.verify_user_token", fake_verify)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": "user-1", "message": "hi"},
    )

    assert resp.status_code == 401


async def test_chat_stream_rate_limit_exceeded(client, monkeypatch):
    user_id = "user-ratelimited"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))
    monkeypatch.setattr("routes.chat.check_rate_limit", lambda *a, **k: False)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "hi"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 429
    assert "Too many messages" in resp.json()["detail"]


async def test_chat_stream_ai_disabled_short_circuits(client, monkeypatch, patch_supabase, fake_supabase):
    user_id = "user-ai-disabled"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    set_chat_settings_select(fake_supabase, [{"ai_enabled": False}])
    patch_supabase("routes.chat", admin=fake_supabase)

    add_message_calls = []
    monkeypatch.setattr(
        "agent.memory.conversation_memory.add_message",
        lambda *a, **k: add_message_calls.append((a, k)),
    )

    # chat_stream should never be reached on this path -- if it were called,
    # this would blow up (not an async generator), failing the test loudly.
    monkeypatch.setattr("agent.bot.chat_stream", object())

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "hello"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    frames = parse_sse(resp.text)
    assert frames == [{"type": "start"}, {"type": "finish"}, "[DONE]"]

    assert len(add_message_calls) == 1
    args, kwargs = add_message_calls[0]
    assert args[0] == user_id
    assert args[1] == "human"
    assert args[2] == "hello"
    assert kwargs.get("source") == "human"


async def test_chat_stream_ai_token_limit_exceeded(client, monkeypatch, patch_supabase, fake_supabase):
    user_id = "user-token-limited"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    # ai_enabled check passes (defaults True), but the upsert() call later in
    # this path shares the same fake_supabase.table(...) chain.
    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    monkeypatch.setattr("routes.chat.check_ai_token_limit", lambda user_id: (False, 1_500_000))

    add_message_calls = []
    monkeypatch.setattr(
        "agent.memory.conversation_memory.add_message",
        lambda *a, **k: add_message_calls.append((a, k)),
    )

    monkeypatch.setattr("agent.bot.chat_stream", object())  # must not be reached

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "spam spam spam"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    frames = parse_sse(resp.text)
    assert frames[0] == {"type": "start"}
    assert frames[1] == {"type": "text-start", "id": "0"}
    rate_limit_message = (
        "Sorry you messaged me too many times, may try again later.\n\n"
        "I will hand this conversation to Terry so you can discuss with him directly"
    )
    assert frames[2] == {"type": "text-delta", "id": "0", "delta": rate_limit_message}
    assert frames[3] == {"type": "text-end", "id": "0"}
    assert frames[4] == {"type": "finish"}
    assert frames[5] == "[DONE]"

    # human message, ai rate-limit message, system retirement message
    assert len(add_message_calls) == 3
    roles = [args[1] for args, _ in add_message_calls]
    assert roles == ["human", "ai", "system"]

    # chat_settings.upsert(...) should have flipped ai_enabled off and flagged admin intervention.
    fake_supabase.table.return_value.upsert.assert_called_once()
    upsert_payload = fake_supabase.table.return_value.upsert.call_args[0][0]
    assert upsert_payload["user_id"] == user_id
    assert upsert_payload["ai_enabled"] is False
    assert upsert_payload["admin_intervening"] is True


async def test_chat_stream_exception_before_any_content(client, monkeypatch, patch_supabase, fake_supabase):
    user_id = "user-error-early"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    async def failing_chat_stream(user_id, message, item_id=None, files=None):
        raise RuntimeError("agent blew up")
        yield "unreachable"  # noqa: pragma - keeps this an async generator

    monkeypatch.setattr("agent.bot.chat_stream", failing_chat_stream)
    monkeypatch.setattr("routes.chat.track_ai_tokens", lambda *a, **k: None)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "hi"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    frames = parse_sse(resp.text)
    # started == False when the exception hits -> no text-end frame emitted.
    assert frames == [
        {"type": "start"},
        {"type": "error", "errorText": "Something went wrong. Please try again."},
        {"type": "finish"},
        "[DONE]",
    ]


async def test_chat_stream_exception_after_partial_content(client, monkeypatch, patch_supabase, fake_supabase):
    user_id = "user-error-late"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    async def failing_chat_stream(user_id, message, item_id=None, files=None):
        yield "partial text"
        raise RuntimeError("stream interrupted")

    monkeypatch.setattr("agent.bot.chat_stream", failing_chat_stream)
    monkeypatch.setattr("routes.chat.track_ai_tokens", lambda *a, **k: None)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "hi"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    frames = parse_sse(resp.text)
    # started == True (a text-delta already went out) -> text-end IS emitted
    # after the error frame.
    assert frames == [
        {"type": "start"},
        {"type": "text-start", "id": "0"},
        {"type": "text-delta", "id": "0", "delta": "partial text"},
        {"type": "error", "errorText": "Something went wrong. Please try again."},
        {"type": "text-end", "id": "0"},
        {"type": "finish"},
        "[DONE]",
    ]


async def test_chat_stream_settings_check_exception_defaults_ai_enabled(client, monkeypatch, patch_supabase, fake_supabase):
    """If the ai_enabled lookup inside generate() itself raises, the stream
    should still proceed as if AI were enabled (broad except -> pass)."""
    user_id = "user-settings-error"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    fake_supabase.table.side_effect = RuntimeError("settings lookup exploded")
    patch_supabase("routes.chat", admin=fake_supabase)

    async def fake_chat_stream(user_id, message, item_id=None, files=None):
        yield "still works"

    monkeypatch.setattr("agent.bot.chat_stream", fake_chat_stream)
    monkeypatch.setattr("routes.chat.track_ai_tokens", lambda *a, **k: None)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "hi"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    frames = parse_sse(resp.text)
    assert {"type": "text-delta", "id": "0", "delta": "still works"} in frames
    assert frames[-1] == "[DONE]"


async def test_chat_stream_skips_falsy_and_statusless_deltas(client, monkeypatch, patch_supabase, fake_supabase):
    """Covers: falsy deltas are skipped outright; a status-carrying dict with
    an empty/missing status is treated like a no-op continue; and a second
    status delta (once `started` is already True) skips re-emitting
    text-start."""
    user_id = "user-mixed-deltas"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    async def fake_chat_stream(user_id, message, item_id=None, files=None):
        yield ""  # falsy -> skipped entirely (never even reaches the dict check)
        yield {"status": "thinking"}  # first status -> emits text-start + delta
        yield {"status": ""}  # truthy dict, but falsy status -> falls through to bare `continue`
        yield {"status": "still-thinking"}  # second status -> started already True
        yield "final answer"

    monkeypatch.setattr("agent.bot.chat_stream", fake_chat_stream)
    monkeypatch.setattr("routes.chat.track_ai_tokens", lambda *a, **k: None)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "hi"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    frames = parse_sse(resp.text)
    # Exactly one text-start, despite two status deltas.
    assert frames.count({"type": "text-start", "id": "0"}) == 1
    assert {"type": "text-delta", "id": "0", "delta": "[[STATUS:thinking]]"} in frames
    assert {"type": "text-delta", "id": "0", "delta": "[[STATUS:still-thinking]]"} in frames
    assert {"type": "text-delta", "id": "0", "delta": "final answer"} in frames


async def test_chat_stream_empty_response_skips_text_end(client, monkeypatch, patch_supabase, fake_supabase):
    """If the agent yields nothing at all, `started` stays False and the
    normal completion path must skip the text-end frame."""
    user_id = "user-empty-response"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    async def fake_chat_stream(user_id, message, item_id=None, files=None):
        return
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr("agent.bot.chat_stream", fake_chat_stream)
    monkeypatch.setattr("routes.chat.track_ai_tokens", lambda *a, **k: None)

    resp = await client.post(
        "/chat/stream",
        json={"user_id": user_id, "message": "hi"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    frames = parse_sse(resp.text)
    assert frames == [{"type": "start"}, {"type": "finish"}, "[DONE]"]


async def test_chat_stream_multipart_ignores_non_file_field_under_files_key(client, monkeypatch, patch_supabase, fake_supabase):
    """A plain (non-upload) form value under the "files" key has no `.read`,
    so it's skipped by the `hasattr(file, 'read')` guard; only the real
    upload alongside it is collected."""
    user_id = "user-mixed-files-field"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    recorded = []

    async def fake_chat_stream(user_id, message, item_id=None, files=None):
        recorded.append(files)
        yield "ok"

    monkeypatch.setattr("agent.bot.chat_stream", fake_chat_stream)
    monkeypatch.setattr("routes.chat.track_ai_tokens", lambda *a, **k: None)

    # httpx encodes `data` fields before `files` fields; both share the
    # "files" form key, so the plain string arrives as one part (no
    # filename) and the upload arrives as a second, separate part.
    resp = await client.post(
        "/chat/stream",
        data={"user_id": user_id, "message": "hi", "files": "not-a-file"},
        files=[("files", ("real.png", b"bytes", "image/png"))],
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    assert len(recorded) == 1
    assert recorded[0] == [{"name": "real.png", "type": "image/png", "data": "Ynl0ZXM="}]


async def test_chat_stream_body_user_id_blank_falls_back_to_token_user(client, monkeypatch, patch_supabase, fake_supabase):
    """When the JSON body omits user_id, the token's user_id is used instead."""
    user_id = "user-from-token"
    monkeypatch.setattr("routes.chat.verify_user_token", await fake_verify_user_token_factory(user_id))

    set_chat_settings_select(fake_supabase, [])
    patch_supabase("routes.chat", admin=fake_supabase)

    recorded = []

    async def fake_chat_stream(user_id, message, item_id=None, files=None):
        recorded.append(user_id)
        yield "hi back"

    monkeypatch.setattr("agent.bot.chat_stream", fake_chat_stream)
    monkeypatch.setattr("routes.chat.track_ai_tokens", lambda *a, **k: None)

    resp = await client.post(
        "/chat/stream",
        json={"message": "hello, no user_id given"},
        headers={"Authorization": "Bearer sometoken"},
    )

    assert resp.status_code == 200
    assert recorded == [user_id]
