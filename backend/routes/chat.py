from fastapi import APIRouter, HTTPException, Form, File, UploadFile, Request
from fastapi.responses import StreamingResponse
from schemas import ChatRequest
from cache import check_rate_limit
from connector import admin_supabase
from typing import Optional, List
import json
import asyncio
import base64

router = APIRouter(prefix="", tags=["Chat"])


def get_conversation_history(user_id: str, item_id: Optional[str] = None) -> list:
    """Load conversation history from Supabase."""
    try:
        query = admin_supabase.table('conversations').select('messages').eq('user_id', user_id)
        if item_id:
            query = query.eq('item_id', item_id)
        result = query.single().execute()
        
        if result.data:
            return result.data.get('messages', [])
        return []
    except Exception:
        return []


def save_conversation_history(user_id: str, messages: list, item_id: Optional[str] = None):
    """Save conversation history to Supabase."""
    try:
        # Check if conversation exists
        query = admin_supabase.table('conversations').select('id').eq('user_id', user_id)
        if item_id:
            query = query.eq('item_id', item_id)
        existing = query.execute()
        
        if existing.data and len(existing.data) > 0:
            # Update existing
            update_query = admin_supabase.table('conversations').update({
                'messages': messages,
                'updated_at': 'now()'
            }).eq('user_id', user_id)
            if item_id:
                update_query = update_query.eq('item_id', item_id)
            update_query.execute()
        else:
            # Insert new
            admin_supabase.table('conversations').insert({
                'user_id': user_id,
                'item_id': item_id,
                'messages': messages
            }).execute()
    except Exception as e:
        print(f"Error saving conversation: {e}")


@router.get("/chat/history/{user_id}")
def get_chat_history(user_id: str, limit: int = 10, offset: int = 0):
    """
    Get chat history for a user from SQLite.
    This includes system messages (join/leave notifications).
    """
    from agent.memory import conversation_memory
    
    history = conversation_memory.get_history(user_id, limit=limit, offset=offset)
    return {"messages": history}


@router.post("/chat")
def chat_with_agent(request: ChatRequest):
    """
    Chat with the negotiation agent.
    
    The agent will:
    1. Answer questions about items
    2. Negotiate prices
    3. Create checkout links when a deal is made
    """
    # Rate limit: 10 messages per minute per user
    if not check_rate_limit(f"chat:{request.user_id}", max_requests=10, window=60):
        raise HTTPException(status_code=429, detail="Too many messages. Please wait a moment.")
    
    from agent.bot import chat
    
    response = chat(
        user_id=request.user_id,
        message=request.message,
        item_id=request.item_id
    )
    
    return {"response": response}


@router.post("/chat/stream")
async def chat_stream(request: Request):
    """
    Stream chat response using Server-Sent Events.
    Accepts both JSON body and multipart form data with optional file attachments.
    """
    content_type = request.headers.get("content-type", "")
    
    # Parse request based on content type
    file_data = []  # List of {"name": str, "type": str, "data": base64_str}
    
    if "multipart/form-data" in content_type:
        # Handle FormData with potential file attachments
        form = await request.form()
        user_id = form.get("user_id", "")
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
        user_id = body.get("user_id", "")
        message = body.get("message", "")
        item_id = body.get("item_id")
    
    # Validate required fields - allow empty message if files are present
    if not user_id or (not message and not file_data):
        raise HTTPException(status_code=400, detail="user_id and message (or files) are required")
    
    # Rate limit: 10 messages per minute per user
    if not check_rate_limit(f"chat:{user_id}", max_requests=10, window=60):
        raise HTTPException(status_code=429, detail="Too many messages. Please wait a moment.")
    
    async def generate():
        from agent.bot import chat
        from connector import admin_supabase
        from agent.memory import conversation_memory
        
        # Check if AI is enabled for this user
        ai_enabled = True
        try:
            settings = admin_supabase.table('chat_settings').select('ai_enabled').eq('user_id', user_id).execute()
            if settings.data and len(settings.data) > 0:
                ai_enabled = settings.data[0].get('ai_enabled', True)
        except:
            pass  # Default to AI enabled if check fails
        
        if not ai_enabled:
            # Save user message to memory but don't respond with AI
            conversation_memory.add_message(user_id, "human", message, source="human")
            waiting_msg = "Please wait, Terry is reviewing your message..."
            for char in waiting_msg:
                yield f"data: {json.dumps({'char': char})}\n\n"
                await asyncio.sleep(0.01)
            yield f"data: {json.dumps({'done': True})}\n\n"
            return
        
        # Get the full response first
        response = chat(
            user_id=user_id,
            message=message or "Please analyze these files.",
            item_id=item_id,
            files=file_data if file_data else None
        )
        
        # Handle if response is a list
        if isinstance(response, list):
            response = json.dumps(response)
        
        # Send full response at once - frontend handles typing animation
        yield f"data: {json.dumps({'content': response, 'done': True})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )




