from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from cache import check_rate_limit, check_ai_token_limit, track_ai_tokens
from connector import admin_supabase
from auth_middleware import verify_user_token, get_user_id_from_body_or_token
import json
import base64
from logger import logger

router = APIRouter(prefix="", tags=["Chat"])


def _sse(obj: dict) -> str:
    """Serialize a dict as a single Server-Sent Event line."""
    return f"data: {json.dumps(obj)}\n\n"


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

    try:
        from agent.memory import conversation_memory

        return conversation_memory.get_history_page(user_id, limit=limit, offset=offset)
    except Exception as e:
        logger.error(f"Error getting chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        conversation_memory.clear_history(user_id)
        return {"message": "Chat history cleared"}
    except Exception as e:
        logger.error(f"Error clearing chat history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat/settings/{user_id}")
async def get_chat_settings(
    user_id: str,
    token_user_id: str = Depends(verify_user_token)
):
    """Get chat settings (AI enabled status) for a user. Requires valid JWT token."""
    # Validate token matches requested user_id
    get_user_id_from_body_or_token(user_id, token_user_id)

    try:
        result = admin_supabase.table('chat_settings').select('ai_enabled').eq('user_id', user_id).execute()
        if result.data and len(result.data) > 0:
            return {"ai_enabled": result.data[0].get('ai_enabled', True)}
        return {"ai_enabled": True}  # Default to enabled
    except Exception as e:
        logger.error(f"Error getting chat settings: {e}")
        return {"ai_enabled": True}  # Default to enabled on error


@router.post("/chat/stream")
async def chat_stream(request: Request):
    """
    Stream chat response using Server-Sent Events.
    Requires valid JWT token in Authorization header.
    Accepts both JSON body and multipart form data with optional file attachments.
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

    # Rate limit: 10 messages per minute per user
    if not check_rate_limit(f"chat:{user_id}", max_requests=10, window=60):
        raise HTTPException(status_code=429, detail="Too many messages. Please wait a moment.")

    # Stable id correlating all text parts of this single assistant message.
    text_id = "0"

    async def generate():
        from agent.bot import chat_stream
        from agent.memory import conversation_memory

        # Check if AI is enabled for this user
        ai_enabled = True
        try:
            settings = admin_supabase.table('chat_settings').select('ai_enabled').eq('user_id', user_id).execute()
            if settings.data and len(settings.data) > 0:
                ai_enabled = settings.data[0].get('ai_enabled', True)
        except Exception:
            pass  # Default to AI enabled if check fails

        if not ai_enabled:
            # Save user message to memory but don't respond with AI.
            conversation_memory.add_message(user_id, "human", message, source="human")
            # Emit an empty-but-well-formed message so useChat clears its loading state.
            yield _sse({"type": "start"})
            yield _sse({"type": "finish"})
            yield "data: [DONE]\n\n"
            return

        # Check AI token rate limit (1M tokens per 30 minutes)
        is_within_limit, current_usage = check_ai_token_limit(user_id)
        if not is_within_limit:
            # Rate limit exceeded - disable AI and hand over to admin
            rate_limit_message = "Sorry you messaged me too many times, may try again later.\n\nI will hand this conversation to Terry so you can discuss with him directly"

            # Save user message first
            conversation_memory.add_message(user_id, "human", message, source="human")

            # Send the rate limit message as an AI response
            conversation_memory.add_message(user_id, "ai", rate_limit_message, source="ai")

            # Update chat_settings to disable AI and enable admin intervention
            admin_supabase.table('chat_settings').upsert({
                'user_id': user_id,
                'ai_enabled': False,
                'admin_intervening': True,
                'updated_at': 'now()'
            }).execute()

            # Add system message about AI retiring
            system_msg = "--- The AI has retired from the chat and Terry will take over now ---"
            conversation_memory.add_message(user_id, "system", system_msg, source="system")

            # Deliver the rate-limit notice as a normal assistant message.
            yield _sse({"type": "start"})
            yield _sse({"type": "text-start", "id": text_id})
            yield _sse({"type": "text-delta", "id": text_id, "delta": rate_limit_message})
            yield _sse({"type": "text-end", "id": text_id})
            yield _sse({"type": "finish"})
            yield "data: [DONE]\n\n"
            return

        # Stream the agent's response. `text-start` is emitted lazily on the
        # first real token so the client keeps showing its "thinking" shimmer
        # while the model is still generating (no empty bubble during the wait).
        yield _sse({"type": "start"})

        collected = []
        started = False
        try:
            for delta in chat_stream(
                user_id=user_id,
                message=message or "Please analyze these files.",
                item_id=item_id,
                files=file_data if file_data else None,
            ):
                if not delta:
                    continue
                collected.append(delta)
                if not started:
                    yield _sse({"type": "text-start", "id": text_id})
                    started = True
                yield _sse({"type": "text-delta", "id": text_id, "delta": delta})
        except Exception as e:
            logger.error(f"Error during chat stream: {e}")
            yield _sse({"type": "error", "errorText": "Something went wrong. Please try again."})
            if started:
                yield _sse({"type": "text-end", "id": text_id})
            yield _sse({"type": "finish"})
            yield "data: [DONE]\n\n"
            return

        # Track token usage (estimate: ~4 chars per token)
        response_text = "".join(collected)
        input_tokens = len(message) // 4 + 1
        output_tokens = len(response_text) // 4 + 1 if response_text else 0
        track_ai_tokens(user_id, input_tokens, output_tokens)

        if started:
            yield _sse({"type": "text-end", "id": text_id})
        yield _sse({"type": "finish"})
        yield "data: [DONE]\n\n"

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
