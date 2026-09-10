import asyncio
import base64
import contextlib
import json
import os
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent.context import pending_discount
from auth_middleware import get_user_id_from_body_or_token, verify_user_token
from cache import (
    check_ai_token_limit,
    check_rate_limit,
    get_rate_limit_remaining,
    get_rate_limit_retry_after,
    track_ai_tokens,
)
from connector import admin_supabase
from limiter import NOTIFICATION_STREAM_LIMIT, limiter
from logger import logger

router = APIRouter(prefix="", tags=["Chat"])

# Per-user message cooldown. `CHAT_RATE_LIMIT_WARN_AT_REMAINING` is how many
# messages are left when the buyer first gets a heads-up, so hitting the wall
# is never a surprise (SPEC-043 workstream E).
CHAT_RATE_LIMIT_MAX = 10
CHAT_RATE_LIMIT_WINDOW = 60
CHAT_RATE_LIMIT_WARN_AT_REMAINING = 2

# Longest single message accepted. Generous for a person haggling — several
# paragraphs — and far below what makes a prompt expensive to run.
CHAT_MESSAGE_MAX_CHARS = int(os.getenv("CHAT_MESSAGE_MAX_CHARS", "4000"))

# Wall-clock ceiling on one whole turn, tool calls included. The providers have
# their own per-request timeouts, but a turn is a *sequence* of requests, so
# only a deadline out here can promise the buyer an answer or an ending. Set
# above a legitimately slow tool-using turn — this is a backstop, not a target.
CHAT_TURN_DEADLINE_SECONDS = float(os.getenv("CHAT_TURN_DEADLINE_SECONDS", "180"))


# Highest unread count the badge will report. It is a chip on an avatar, not a
# ledger — past this the exact number tells the buyer nothing they don't
# already know, and asking for it costs a full count on a neglected thread.
UNREAD_COUNT_CAP = 99


def _sse(obj: dict) -> str:
    """Serialize a dict as a single Server-Sent Event line."""
    return f"data: {json.dumps(obj)}\n\n"


def _buyer_read_watermark(user_id: str) -> str | None:
    """When this buyer last read their conversation, or None if never.

    SPEC-061, the mirror of the seller's `admin_last_read_at`. Read failures
    return None rather than raising: the caller's fallback rule (count from the
    buyer's own last message) is a worse answer than the watermark but a much
    better one than a 500 over a notification chip.
    """
    try:
        result = (
            admin_supabase.table('chat_settings')
            .select('user_last_read_at')
            .eq('user_id', user_id)
            .execute()
        )
        rows = result.data or []
        return rows[0].get('user_last_read_at') if rows else None
    except Exception as e:
        logger.debug(f"Could not read the unread watermark for {user_id}: {e}")
        return None


def _stamp_buyer_read(user_id: str) -> str:
    """Mark this buyer's conversation read. Raises on failure.

    The mark covers every agent/seller message already in the transcript, which
    is not the same as `now` (SPEC-066): rows written before that fix carry the
    API host's local time in a UTC column, hours ahead of any clock reading it
    back, and a `now` stamp leaves them counted as unread for the whole offset.
    """
    from agent.memory import conversation_memory

    read_at = conversation_memory.read_watermark(user_id, 'ai')
    admin_supabase.table('chat_settings').upsert({
        'user_id': user_id,
        'user_last_read_at': read_at,
        'updated_at': 'now()',
    }).execute()
    return read_at


@router.get("/chat/history/{user_id}")
async def get_chat_history(
    user_id: str,
    limit: int = 20,
    offset: int = 0,
    token_user_id: str = Depends(verify_user_token)
):
    """
    Get a page of chat history for a user from Supabase.
    `offset` counts back from the newest message; `limit` is the page size.
    Returns { messages, has_more, next_offset } for lazy "load older" paging.
    Requires valid JWT token matching the user_id.
    """
    # Validate token matches requested user_id
    get_user_id_from_body_or_token(user_id, token_user_id)

    # SPEC-052: opening the chat IS reading it, so any digest still waiting to
    # be emailed is dropped. Best-effort — a Redis blip must not fail the read.
    with contextlib.suppress(Exception):
        from services.unread_digest import mark_conversation_seen
        await asyncio.to_thread(mark_conversation_seen, user_id)

    # SPEC-061: and the same act moves the unread watermark. This is the
    # backstop for a hard load, which paints the transcript before the header's
    # composable ever gets to stamp it.
    with contextlib.suppress(Exception):
        await asyncio.to_thread(_stamp_buyer_read, user_id)

    try:
        from agent.memory import conversation_memory

        return await asyncio.to_thread(
            conversation_memory.get_history_page, user_id, limit=limit, offset=offset
        )
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/chat/history/{user_id}")
async def clear_chat_history(
    user_id: str,
    token_user_id: str = Depends(verify_user_token)
):
    """Clear chat history for a user. Requires valid JWT token."""
    # Validate token matches requested user_id
    get_user_id_from_body_or_token(user_id, token_user_id)

    try:
        from agent.memory import conversation_memory
        await asyncio.to_thread(conversation_memory.clear_history, user_id)
        return {"message": "Chat history cleared"}
    except Exception as e:
        logger.error(f"Error clearing chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/chat/settings/{user_id}")
async def get_chat_settings(
    user_id: str,
    token_user_id: str = Depends(verify_user_token)
):
    """Get chat settings (AI enabled status) for a user. Requires valid JWT token."""
    # Validate token matches requested user_id
    get_user_id_from_body_or_token(user_id, token_user_id)

    try:
        result = await asyncio.to_thread(
            lambda: admin_supabase.table('chat_settings')
            .select('ai_enabled').eq('user_id', user_id).execute()
        )
        if result.data and len(result.data) > 0:
            return {"ai_enabled": result.data[0].get('ai_enabled', True)}
        return {"ai_enabled": True}  # Default to enabled
    except Exception as e:
        logger.error(f"Error getting chat settings: {e}")
        return {"ai_enabled": True}  # Default to enabled on error


# --- Detached turns --------------------------------------------------------
#
# SPEC-060. A turn belongs to the buyer's conversation, not to the HTTP
# response that happened to ask for it. It used to run *inside* the
# `StreamingResponse` generator, so closing the tab cancelled it at whichever
# `await` it was sitting on — usually mid-token — and the agent never reached
# the `add_message` that persists its reply. The buyer's own message was
# already saved, so the transcript read as a question the seller ignored.
#
# Producers are held in a module-level set because asyncio keeps only a weak
# reference to a running task: without a strong one the garbage collector can
# stop a turn mid-sentence, which is the exact failure this indirection exists
# to prevent.
_running_turns: set[asyncio.Task] = set()

# Pushed by the producer when there is nothing more to send.
_TURN_END = object()


class _TurnRelay:
    """The only thing an in-flight turn and its HTTP response share.

    The response reads frames off this queue and does nothing else, so the
    cancellation a closed tab delivers has no application logic to interrupt.
    `detach()` is what the response's `finally` calls; after it, emitted frames
    are dropped rather than queued behind a reader that is never coming back.
    """

    def __init__(self) -> None:
        self._frames: asyncio.Queue = asyncio.Queue()
        self._attached = True

    @property
    def attached(self) -> bool:
        """False once the client has hung up. The turn plays on regardless —
        this only says whether anyone is still watching it happen."""
        return self._attached

    def emit(self, frame: dict) -> None:
        if self._attached:
            self._frames.put_nowait(frame)

    def end(self) -> None:
        self._frames.put_nowait(_TURN_END)

    def detach(self) -> None:
        self._attached = False

    async def frames(self):
        while True:
            frame = await self._frames.get()
            if frame is _TURN_END:
                return
            yield frame


async def _deliver(user_id: str, text: str) -> None:
    """Put a finished reply in front of the buyer, wherever they are.

    Live streams get it through the broker; a buyer with no stream at all gets
    it batched into the same digest email a seller's message would take
    (SPEC-052), instead of it waiting silently in a transcript nobody has open.
    """
    if not text:
        return

    from payment.fulfillment import broadcast_to_chat
    await asyncio.to_thread(broadcast_to_chat, user_id, text, role="ai", source="ai")

    try:
        from notifications import notification_broker
        if notification_broker.has_subscribers(user_id):
            return
        from services.unread_digest import queue_unread_message
        await asyncio.to_thread(queue_unread_message, user_id, text)
    except Exception as e:
        logger.debug(f"Unread digest queue skipped for {user_id}: {e}")


async def _run_turn(
    *,
    user_id: str,
    message: str,
    item_id: str | None,
    file_data: list,
    remaining: int,
    relay: _TurnRelay,
) -> None:
    """Drive one agent turn to completion, whatever the buyer's browser does.

    Everything with a side effect lives here rather than in the response
    generator: the incoming broadcast, the AI-enabled check, the token budget,
    the agent stream, and the delivery of what it produced. A closed tab
    therefore costs the buyer a live view of the answer and nothing else.
    """
    from agent.bot import chat_stream
    from agent.memory import conversation_memory

    # Stable id correlating all text parts of this single assistant message.
    text_id = "0"

    try:
        from payment.fulfillment import broadcast_to_chat

        # Broadcast incoming human message to Realtime channel for live admin
        # console synchronization.
        await asyncio.to_thread(broadcast_to_chat, user_id, message, role="user", source="human")

        # Check if AI is enabled for this user
        ai_enabled = True
        try:
            settings = await asyncio.to_thread(
                lambda: admin_supabase.table('chat_settings')
                .select('ai_enabled').eq('user_id', user_id).execute()
            )
            if settings.data and len(settings.data) > 0:
                ai_enabled = settings.data[0].get('ai_enabled', True)
        except Exception as e:
            logger.debug(f"Could not check ai_enabled for {user_id}, defaulting to enabled: {e}")

        if not ai_enabled:
            # Save user message to memory but don't respond with AI.
            await asyncio.to_thread(
                conversation_memory.add_message, user_id, "human", message, source="human"
            )
            # Emit an empty-but-well-formed message so useChat clears its loading state.
            relay.emit({"type": "start"})
            relay.emit({"type": "finish"})
            return

        # Check AI token rate limit (1M tokens per 30 minutes)
        is_within_limit, current_usage = await asyncio.to_thread(
            check_ai_token_limit, user_id
        )
        if not is_within_limit:
            # Rate limit exceeded - disable AI and hand over to admin
            rate_limit_message = "Sorry you messaged me too many times, may try again later.\n\nI will hand this conversation to Terry so you can discuss with him directly"

            # Save user message first
            await asyncio.to_thread(
                conversation_memory.add_message, user_id, "human", message, source="human"
            )

            # Send the rate limit message as an AI response
            await asyncio.to_thread(
                conversation_memory.add_message, user_id, "ai", rate_limit_message, source="ai"
            )

            # Update chat_settings to disable AI and enable admin intervention
            await asyncio.to_thread(
                lambda: admin_supabase.table('chat_settings').upsert({
                    'user_id': user_id,
                    'ai_enabled': False,
                    'admin_intervening': True,
                    'updated_at': 'now()'
                }).execute()
            )

            # Add system message about AI retiring
            system_msg = "--- The AI has retired from the chat and Terry will take over now ---"
            await asyncio.to_thread(
                conversation_memory.add_message, user_id, "system", system_msg, source="system"
            )

            await _deliver(user_id, rate_limit_message)
            await asyncio.to_thread(
                broadcast_to_chat, user_id, system_msg, role="system", source="system"
            )

            # Deliver the rate-limit notice as a normal assistant message.
            relay.emit({"type": "start"})
            relay.emit({"type": "text-start", "id": text_id})
            relay.emit({"type": "text-delta", "id": text_id, "delta": rate_limit_message})
            relay.emit({"type": "text-end", "id": text_id})
            relay.emit({"type": "finish"})
            return

        # Stream the agent's response. `text-start` is emitted lazily on the
        # first real token so the client keeps showing its "thinking" shimmer
        # while the model is still generating (no empty bubble during the wait).
        relay.emit({"type": "start"})

        # Early warning: the buyer is close to the per-minute cooldown. Sent as
        # a data part rather than words in the transcript — it's a UI state, not
        # something the assistant said.
        if remaining <= CHAT_RATE_LIMIT_WARN_AT_REMAINING:
            relay.emit({
                "type": "data-cooldown-warning",
                "id": "cooldown-warning",
                "data": {"remaining": remaining},
            })

        collected = []
        started = False
        timed_out = False
        charged = False

        def charge_for_turn() -> None:
            """Settle this turn against the AI token budget, at most once.

            Every way out of the turn has to come through here. Charging only
            where the turn ran to completion meant a turn that timed out or
            threw cost real money upstream and incremented nothing — so the
            1M/30min ceiling was only ever enforced against clients that waited
            for their answer.
            """
            nonlocal charged
            if charged:
                return
            charged = True
            partial = "".join(collected)
            # ~4 chars per token, same estimate the completed path has always used.
            track_ai_tokens(
                user_id,
                len(message) // 4 + 1,
                len(partial) // 4 + 1 if partial else 0,
            )

        # chat_stream is a native async generator (LangGraph .astream), so the
        # LLM's network I/O yields control and never blocks the event loop —
        # concurrent chats and the admin console stay responsive.
        turn = chat_stream(
            user_id=user_id,
            message=message or "Please analyze these files.",
            item_id=item_id,
            files=file_data if file_data else None,
        )
        # One budget for the whole turn, not per chunk: a turn that dribbles a
        # token every few seconds forever is just as stuck as one that never
        # yields at all, and only a wall-clock deadline catches both.
        deadline = time.monotonic() + CHAT_TURN_DEADLINE_SECONDS
        try:
            while True:
                time_left = deadline - time.monotonic()
                if time_left <= 0:
                    timed_out = True
                    break
                try:
                    delta = await asyncio.wait_for(turn.__anext__(), timeout=time_left)
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    timed_out = True
                    break

                if not delta:
                    continue

                # SPEC-041: drain any discount committed by evaluate_offer before
                # forwarding the chunk. The ContextVar is set by the tool and reset
                # to None here so it fires at most once per turn.
                discount = pending_discount.get()
                if discount is not None:
                    pending_discount.set(None)
                    relay.emit({"type": "data-discount", "id": "discount", "data": {"discounted_price": discount}})

                if isinstance(delta, dict):
                    # SPEC-020: which engine served this turn (self-hosted Apple
                    # M5 vs Gemini overflow). Emitted as an AI SDK data part —
                    # this stream speaks the UI message protocol, where a bare
                    # `event: metadata` frame would be dropped by the client.
                    provider = delta.get("provider")
                    if provider:
                        relay.emit({"type": "data-provider", "id": "provider", "data": provider})
                        continue

                    status = delta.get("status", "")
                    if status:
                        if not started:
                            relay.emit({"type": "text-start", "id": text_id})
                            started = True
                        relay.emit({"type": "text-delta", "id": text_id, "delta": f"[[STATUS:{status}]]"})
                    continue
                collected.append(delta)
                if not started:
                    relay.emit({"type": "text-start", "id": text_id})
                    started = True
                relay.emit({"type": "text-delta", "id": text_id, "delta": delta})
        except Exception as e:
            logger.error(f"Error during chat stream: {e}")
            # Whatever was streamed before it broke was still generated upstream.
            await asyncio.to_thread(charge_for_turn)
            relay.emit({"type": "error", "errorText": "Something went wrong. Please try again."})
            if started:
                relay.emit({"type": "text-end", "id": text_id})
            relay.emit({"type": "finish"})
            return
        finally:
            # Closing the generator runs its `finally`, which is what releases
            # the local-LLM lease and the overflow permit. On the happy path it
            # has already run to completion and this is a no-op; on the timeout
            # and error paths it is what stops the model mid-flight.
            await turn.aclose()

        if timed_out:
            logger.warning(
                f"Chat turn for {user_id} exceeded {CHAT_TURN_DEADLINE_SECONDS}s — ending the stream."
            )
            # Running out of time doesn't refund what the model already produced.
            await asyncio.to_thread(charge_for_turn)
            partial = "".join(collected)
            # `aclose()` above stopped the agent before its own `add_message`,
            # so a partial answer only survives if this writes it. Gated on the
            # client being gone: someone still watching gets the retry the
            # timeout frame offers, and a persisted partial would then sit in
            # the transcript in front of the answer that replaces it.
            if partial and not relay.attached:
                await asyncio.to_thread(
                    conversation_memory.add_message, user_id, "ai", partial, item_id
                )
                await _deliver(user_id, partial)
            # A distinct part, not the generic error frame: the UI offers a
            # retry for this, and nothing actually broke — the turn just ran
            # out of time. Anything already streamed stays on screen.
            relay.emit({
                "type": "data-turn-timeout",
                "id": "turn-timeout",
                "data": {"partial": bool(collected)},
            })
            if started:
                relay.emit({"type": "text-end", "id": text_id})
            relay.emit({"type": "finish"})
            return

        await asyncio.to_thread(charge_for_turn)

        # The agent persisted the reply itself on its way out; this is what
        # tells the buyer it happened.
        await _deliver(user_id, "".join(collected))

        if started:
            relay.emit({"type": "text-end", "id": text_id})
        relay.emit({"type": "finish"})
    except asyncio.CancelledError:
        # Server shutdown, not a client hang-up — that cancels the relay loop,
        # never this task. Nothing to salvage.
        raise
    except Exception as e:
        logger.error(f"Chat turn for {user_id} failed: {e}")
        relay.emit({"type": "error", "errorText": "Something went wrong. Please try again."})
        relay.emit({"type": "finish"})
    finally:
        # Unconditional: a response waiting on frames that never end would hang
        # the buyer's browser on a spinner for as long as it kept the socket.
        relay.end()


@router.post("/chat/stream")
async def chat_stream(request: Request):
    """
    Stream chat response using Server-Sent Events.
    Requires valid JWT token in Authorization header.
    Accepts both JSON body and multipart form data with optional file attachments.

    Deliberately NOT Turnstile-gated: a siteverify token is single-use and
    expires in ~300s, so it can only guard one-shot submissions (the auth entry
    points in SPEC-003), not an endpoint the client calls on every message.
    Abuse protection here is JWT auth + the per-user rate limit below + the AI
    token budget.
    """
    # Validate JWT token FIRST
    token_user_id = await verify_user_token(request)

    content_type = request.headers.get("content-type", "")

    # Parse request based on content type
    file_data = []  # List of {"name": str, "type": str, "data": base64_str}

    if "multipart/form-data" in content_type:
        # Handle FormData with potential file attachments
        form = await request.form()
        body_user_id = form.get("user_id", "")
        message = form.get("message", "")
        item_id = form.get("item_id")

        # Read and encode uploaded files
        files = form.getlist("files")
        for file in files:
            if hasattr(file, 'read'):
                content = await file.read()
                file_data.append({
                    "name": file.filename or "file",
                    "type": file.content_type or "application/octet-stream",
                    "data": base64.b64encode(content).decode('utf-8')
                })
    else:
        # Handle JSON body
        body = await request.json()
        body_user_id = body.get("user_id", "")
        message = body.get("message", "")
        item_id = body.get("item_id")

    # Validate token matches body user_id
    user_id = get_user_id_from_body_or_token(body_user_id, token_user_id)

    # Validate required fields - allow empty message if files are present
    if not message and not file_data:
        raise HTTPException(status_code=400, detail="message or files are required")

    # A single message could previously be anything under the 10 MB body cap,
    # and every turn replays it to a paid model along with the last 50 messages
    # of history. That made one account with one script an unbounded bill.
    # The ceiling is far above any real negotiation message.
    if len(message) > CHAT_MESSAGE_MAX_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Message is too long (limit {CHAT_MESSAGE_MAX_CHARS} characters).",
        )

    # Rate limit: 10 messages per minute per user. The Redis client is
    # synchronous and this is an `async def` handler, so it goes through a
    # thread — a slow Redis here would otherwise stall every other request on
    # this worker (SPEC-023's rule: synchronous I/O always goes through a thread).
    rate_key = f"chat:{user_id}"
    within_limit = await asyncio.to_thread(
        check_rate_limit, rate_key, CHAT_RATE_LIMIT_MAX, CHAT_RATE_LIMIT_WINDOW
    )
    if not within_limit:
        # 429 + Retry-After is the standard answer, and it's what the client
        # derives its countdown from. The seconds also ride in the body so the
        # SPA doesn't depend on reading a header through the AI SDK transport.
        retry_after = await asyncio.to_thread(get_rate_limit_retry_after, rate_key)
        raise HTTPException(
            status_code=429,
            detail={
                "code": "chat_cooldown",
                "retryAfterSeconds": retry_after,
                "message": "Too many messages. Please wait a moment.",
            },
            headers={"Retry-After": str(retry_after)},
        )

    # How close this turn is to the wall, for the client's early warning.
    remaining = await asyncio.to_thread(
        get_rate_limit_remaining, rate_key, CHAT_RATE_LIMIT_MAX
    )

    # SPEC-052: a buyer typing is a buyer who is present. Anything the seller
    # queued for them is by definition seen, so it must not arrive as an email
    # five minutes into a live conversation.
    with contextlib.suppress(Exception):
        from services.unread_digest import mark_conversation_seen
        await asyncio.to_thread(mark_conversation_seen, user_id)

    # The turn is started here and owned by nobody but itself (SPEC-060): the
    # response below is one optional viewer of it.
    relay = _TurnRelay()
    producer = asyncio.create_task(_run_turn(
        user_id=user_id,
        message=message,
        item_id=item_id,
        file_data=file_data,
        remaining=remaining,
        relay=relay,
    ))
    _running_turns.add(producer)
    producer.add_done_callback(_running_turns.discard)

    async def generate():
        # Relay only. Every side effect lives in the producer, so the
        # cancellation a closed tab delivers here interrupts nothing.
        try:
            async for frame in relay.frames():
                yield _sse(frame)
            yield "data: [DONE]\n\n"
        finally:
            relay.detach()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Tells the AI SDK client this is a v1 UI message stream.
            "x-vercel-ai-ui-message-stream": "v1",
        }
    )


@router.get("/chat/unread")
async def get_unread(user_id: str = Depends(verify_user_token)):
    """How many seller/agent messages this buyer hasn't read (SPEC-061).

    The count is the header chip's only source of truth across a reload. Both
    the user and the scope come from the JWT — there is no `user_id` in the
    path and therefore nothing to scope optionally
    (`docs/SECURITY_ANTI_PATTERNS.md`).

    Cutoff is the later of the watermark and the buyer's own newest message:
    typing is proof of presence, and it is what a conversation with no
    watermark yet counts from, so shipping this does not mark an existing
    user's whole history unread.

    `role='ai'` is both the agent and the seller — the console writes seller
    replies as `role='ai', source='admin'`. `system` separators are not
    messages anyone is waiting on.
    """
    from agent.memory import conversation_memory

    read_at, last_human_at = await asyncio.gather(
        asyncio.to_thread(_buyer_read_watermark, user_id),
        asyncio.to_thread(conversation_memory.newest_at, user_id, "human"),
    )
    cutoff = max(filter(None, (read_at, last_human_at)), default=None)

    count = await asyncio.to_thread(
        conversation_memory.count_since, user_id, "ai", cutoff, UNREAD_COUNT_CAP
    )
    return {"count": count, "has_unread": count > 0}


@router.post("/chat/read")
async def mark_read(user_id: str = Depends(verify_user_token)):
    """Mark this buyer's conversation read, at now (SPEC-061)."""
    try:
        read_at = await asyncio.to_thread(_stamp_buyer_read, user_id)
    except Exception as e:
        # Surfaced rather than swallowed: a chip that clears on screen and
        # comes back on the next load is worse than one that never cleared.
        logger.warning(f"⚠️ Failed to stamp the read watermark for {user_id}: {e}")
        raise HTTPException(status_code=503, detail="Could not update read state") from e

    # SPEC-052: reading is reading, whichever door they came through.
    with contextlib.suppress(Exception):
        from services.unread_digest import mark_conversation_seen
        await asyncio.to_thread(mark_conversation_seen, user_id)

    return {"read_at": read_at}


@router.post("/chat/notifications/ticket")
@limiter.limit(NOTIFICATION_STREAM_LIMIT)
async def notifications_ticket(request: Request, user_id: str = Depends(verify_user_token)):
    """Mint a short-lived, single-use ticket for opening the notification stream.

    SPEC-056 #6. `EventSource` cannot set headers, which is why the stream used
    to accept `?token=<supabase access token>`. That put an hour-long credential
    for the whole API into every access log, proxy log, APM breadcrumb and
    browser history entry that touches the URL. This endpoint is a normal
    header-authenticated POST; what goes in the URL afterwards is a 30-second
    ticket good for exactly one stream and nothing else.
    """
    from cache import SSE_TICKET_TTL, mint_sse_ticket

    return {"ticket": mint_sse_ticket(user_id), "expires_in": SSE_TICKET_TTL}


@router.get("/chat/notifications/stream")
@limiter.limit(NOTIFICATION_STREAM_LIMIT)
async def notifications_stream(request: Request):
    """
    Real-time Server-Sent Events (SSE) notification stream.
    Emits instant notifications when the seller sends a message.

    Authorised by a `?ticket=` minted at POST /chat/notifications/ticket. Access
    tokens are deliberately NOT accepted here any more (SPEC-056 #6) — a URL is
    a public place, and the ticket is designed to be worthless in one.
    """
    from cache import redeem_sse_ticket

    user_id = await asyncio.to_thread(redeem_sse_ticket, request.query_params.get("ticket", ""))
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing or expired stream ticket")

    from notifications import notification_broker

    async def event_generator():
        # Subscribe INSIDE the generator so it is always paired with the
        # `finally` below. Subscribing in the route body leaks a queue (and its
        # Redis channel) whenever the response body is never iterated — a client
        # that vanishes between the handshake and the first chunk.
        queue = await notification_broker.subscribe(user_id)
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: message\ndata: {json.dumps(event)}\n\n"
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            await notification_broker.unsubscribe(user_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

