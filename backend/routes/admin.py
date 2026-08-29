import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

from admin_session import (
    clear_session,
    client_ip,
    enforce_login_rate_limit,
    password_then_send_otp,
    verify_admin,
    verify_otp_and_open_session,
    write_audit,
)
from csrf import generate_csrf_token, set_csrf_cookie, verify_csrf_token
from env import ADMIN_PREFIX, STORAGE_BUCKET
from logger import logger
from schemas import (
    Admin2FARequest,
    AdminLoginRequest,
    AdminMessageRequest,
    AIToggleRequest,
    BanRequest,
    MarketValuationRequest,
    OrderStatusUpdate,
    OrderUpdate,
    UpdateItemSchema,
    UserProfileUpdateRequest,
)

# Public auth router (NOT gated by verify_admin — that's what these establish).
# There is no IP allowlist; access is gated by 2FA + rate limiting + audit.
router = APIRouter(prefix=ADMIN_PREFIX, tags=["System"])

# Every data route below requires a valid admin session + CSRF verification.
protected = APIRouter(dependencies=[Depends(verify_admin), Depends(verify_csrf_token)])


# =====================
# Auth: password (factor 1) -> email OTP (factor 2) -> opaque session cookie
# =====================

@router.post("/auth/login")
def admin_login(request: AdminLoginRequest, req: Request):
    """Factor 1. Verify password + admin role, then email a 6-digit OTP.

    Returns an opaque pre-auth handle to use with /auth/verify-2fa. The response
    is intentionally identical whether or not the email is a real admin.
    """
    email = request.email.strip().lower()
    enforce_login_rate_limit(email, client_ip(req))
    handle = password_then_send_otp(email, request.password)
    return {"handle": handle, "message": "A verification code has been emailed to you."}


@router.post("/auth/verify-2fa")
def admin_verify_2fa(request: Admin2FARequest, req: Request, response: Response):
    """Factor 2. Verify the email OTP and open the admin session cookie."""
    result = verify_otp_and_open_session(request.handle, request.code.strip(), response, req)
    return {"valid": True, "email": result["email"]}


@router.post("/auth/logout")
def admin_logout(req: Request, response: Response, admin: dict = Depends(verify_admin)):
    """Invalidate the current admin session."""
    write_audit(admin.get("user_id"), admin.get("email"), "logout", None, admin.get("ip"))
    clear_session(req, response)
    return {"message": "Logged out"}


@router.get("/auth/session")
def admin_session(admin: dict = Depends(verify_admin)):
    """Lightweight check used by the frontend route middleware."""
    return {"valid": True, "email": admin.get("email")}


@router.get("/auth/csrf")
def admin_csrf_token(req: Request, response: Response, admin: dict = Depends(verify_admin)):
    """Return a fresh CSRF token. Called on page refresh when the cookie may be stale."""
    from env import ADMIN_COOKIE_NAME
    sid = req.cookies.get(ADMIN_COOKIE_NAME, "")
    token = generate_csrf_token(sid)
    set_csrf_cookie(response, token)
    return {"csrf_token": token}


# =====================
# User Management
# =====================

@protected.get("/users")
def get_all_users():
    """Get all users with their profiles and chat settings."""
    from fastapi import HTTPException

    from connector import admin_supabase

    try:
        # Get all users from auth
        users_response = admin_supabase.auth.admin.list_users()

        # Get profiles and chat settings
        profiles = admin_supabase.table('user_profiles').select('*').execute()
        settings = admin_supabase.table('chat_settings').select('*').execute()

        profiles_map = {p['id']: p for p in (profiles.data or [])}
        settings_map = {s['user_id']: s for s in (settings.data or [])}

        users = []
        for user in users_response:
            user_id = user.id
            profile = profiles_map.get(user_id, {})
            setting = settings_map.get(user_id, {})
            meta = user.user_metadata or {}

            # Source of truth for display name / avatar is auth user_metadata
            # (set by the self-service profile page); fall back to the legacy
            # user_profiles row, then the email local-part.
            display_name = (
                meta.get('display_name')
                or profile.get('display_name')
                or (user.email.split('@')[0] if user.email else 'User')
            )
            avatar_url = meta.get('avatar_url') or profile.get('avatar_url')

            users.append({
                "id": user_id,
                "email": user.email,
                "display_name": display_name,
                "avatar_url": avatar_url,
                "is_banned": profile.get('is_banned', False),
                "ai_enabled": setting.get('ai_enabled', True),
                "admin_intervening": setting.get('admin_intervening', False),
                "created_at": user.created_at
            })

        return users
    except Exception as e:
        logger.error(f"Error in get_all_users: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@protected.put("/users/{user_id}/profile")
def update_user_profile(user_id: str, request: UserProfileUpdateRequest, admin: dict = Depends(verify_admin)):
    """Update a user's profile (display name, avatar)."""
    from connector import admin_supabase

    updates = {
        'id': user_id,
        'updated_at': 'now()'
    }

    if request.display_name is not None:
        updates['display_name'] = request.display_name

    if request.avatar_url is not None:
        updates['avatar_url'] = request.avatar_url

    admin_supabase.table('user_profiles').upsert(updates).execute()
    write_audit(admin.get("user_id"), admin.get("email"), "user.profile_update", user_id, admin.get("ip"))
    return {"message": "User profile updated successfully"}


@protected.post("/users/{user_id}/avatar")
async def upload_user_avatar(
    user_id: str,
    avatar: Annotated[UploadFile, File()],
    admin: dict = Depends(verify_admin),
):
    """Upload a user avatar."""
    import base64
    import uuid

    from connector import admin_supabase

    contents = await avatar.read()

    # Try to use storage first
    try:
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{user_id}_{unique_id}_{avatar.filename}"
        # Store avatars under an 'avatars/' folder in the shared storage bucket
        file_path = f"avatars/{filename}"

        admin_supabase.storage.from_(STORAGE_BUCKET).upload(
            file_path,
            contents,
            {"content-type": avatar.content_type}
        )
        public_url = admin_supabase.storage.from_(STORAGE_BUCKET).get_public_url(file_path)

        # Update profile with URL
        admin_supabase.table('user_profiles').upsert({
            'id': user_id,
            'avatar_url': public_url,
            'updated_at': 'now()'
        }).execute()

        write_audit(admin.get("user_id"), admin.get("email"), "user.avatar_upload", user_id, admin.get("ip"))
        return {"message": "Avatar uploaded successfully", "avatar_url": public_url}

    except Exception:
        # Fallback to base64 data URL if storage fails
        base64_image = base64.b64encode(contents).decode('utf-8')
        data_url = f"data:{avatar.content_type};base64,{base64_image}"

        admin_supabase.table('user_profiles').upsert({
            'id': user_id,
            'avatar_url': data_url,
            'updated_at': 'now()'
        }).execute()

        write_audit(admin.get("user_id"), admin.get("email"), "user.avatar_upload", user_id, admin.get("ip"))
        return {"message": "Avatar uploaded (base64)", "avatar_url": data_url}


@protected.put("/users/{user_id}/ban")
def ban_user(user_id: str, request: BanRequest, admin: dict = Depends(verify_admin)):
    """Ban or unban a user."""
    from admin_session import _is_admin_user
    from connector import admin_supabase

    # Guard against locking out admins. Banning applies at the Supabase auth
    # level, which would block the admin dashboard login too, so an admin must
    # never be able to ban themselves or another admin.
    if request.is_banned:
        if user_id == admin.get("user_id"):
            raise HTTPException(status_code=400, detail="You cannot ban your own account")
        try:
            target = admin_supabase.auth.admin.get_user_by_id(user_id)
            if target and target.user and _is_admin_user(target.user):
                raise HTTPException(status_code=403, detail="Cannot ban an admin account")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Could not verify admin status for {user_id}: {e}")

    # Upsert user profile with ban status
    admin_supabase.table('user_profiles').upsert({
        'id': user_id,
        'is_banned': request.is_banned,
        'updated_at': 'now()'
    }).execute()

    # Ban at the Supabase auth level too. This blocks new logins and revokes the
    # user's refresh tokens, so they can't mint a fresh session. (Our own
    # verify_user_token check still covers the window where an already-issued
    # access token is valid.) "none" lifts the ban on unban.
    try:
        admin_supabase.auth.admin.update_user_by_id(
            user_id,
            {"ban_duration": "876000h" if request.is_banned else "none"},  # ~100 years
        )
    except Exception as e:
        logger.error(f"Failed to set Supabase auth ban for {user_id}: {e}")

    # Drop the cached ban status so the change takes effect on the next request.
    from cache import invalidate_ban_status
    invalidate_ban_status(user_id)

    write_audit(admin.get("user_id"), admin.get("email"),
                "user.ban" if request.is_banned else "user.unban", user_id, admin.get("ip"))
    return {"message": f"User {'banned' if request.is_banned else 'unbanned'} successfully"}


@protected.put("/users/{user_id}/ai")
def toggle_user_ai(user_id: str, request: AIToggleRequest, admin: dict = Depends(verify_admin)):
    """Enable or disable AI for a specific user."""
    from agent.memory import conversation_memory
    from connector import admin_supabase

    # Upsert chat settings
    admin_supabase.table('chat_settings').upsert({
        'user_id': user_id,
        'ai_enabled': request.ai_enabled,
        'admin_intervening': not request.ai_enabled,  # If AI disabled, admin is intervening
        'updated_at': 'now()'
    }).execute()

    # Add system message to notify user
    if request.ai_enabled:
        system_msg = "--- Terry has retired from the chat and the AI will take over now ---"
    else:
        system_msg = "--- Terry has joined the chat, the AI will retire for now ---"

    conversation_memory.add_message(user_id, "system", system_msg, source="system")

    # Broadcast the system message in real-time via Supabase channel
    try:
        import requests

        from env import ADMIN_SUPABASE_KEY, SUPABASE_URL

        # Use Supabase REST API to broadcast via realtime channel
        # Format: POST /realtime/v1/api/broadcast with messages array
        broadcast_url = f"{SUPABASE_URL}/realtime/v1/api/broadcast"
        headers = {
            "apikey": ADMIN_SUPABASE_KEY,
            "Authorization": f"Bearer {ADMIN_SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        # Supabase broadcast API expects messages array with channel, event, payload
        payload = {
            "messages": [{
                "topic": f"chat:{user_id}",
                "event": "broadcast",
                "payload": {
                    "event": "new_message",
                    "payload": {
                        "role": "system",
                        "content": system_msg,
                        "source": "system"
                    }
                }
            }]
        }
        resp = requests.post(broadcast_url, json=payload, headers=headers, timeout=2)
        logger.info(f"Broadcast response: {resp.status_code} - {resp.text}")
    except Exception as e:
        logger.error(f"Failed to broadcast system message: {e}")

    write_audit(admin.get("user_id"), admin.get("email"),
                "user.ai_enable" if request.ai_enabled else "user.ai_disable", user_id, admin.get("ip"))
    return {"message": f"AI {'enabled' if request.ai_enabled else 'disabled'} for user"}


@protected.delete("/users/{user_id}")
def admin_delete_user(user_id: str, admin: dict = Depends(verify_admin)):
    """Permanently delete a user: app-side data + the Supabase auth user.
    Orders are intentionally retained as business records."""
    from connector import admin_supabase

    # Best-effort cleanup of app data (don't abort if a table is empty)
    for table, column in [
        ("chat_settings", "user_id"),
        ("conversations", "user_id"),
        ("user_profiles", "id"),
    ]:
        try:
            admin_supabase.table(table).delete().eq(column, user_id).execute()
        except Exception as e:
            logger.warning(f"Could not clean up {table} for {user_id}: {e}")

    try:
        admin_supabase.auth.admin.delete_user(user_id)
    except Exception as e:
        logger.error(f"Error deleting auth user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete user") from e

    write_audit(admin.get("user_id"), admin.get("email"), "user.delete", user_id, admin.get("ip"))
    return {"message": "User deleted successfully"}



# =====================
# Chat Intervention
# =====================

@protected.get("/chats")
def get_all_chats():
    """Get list of all active conversations, enriched with the user's display
    name / avatar and an `unread` flag (true when the customer sent the last
    message and is still waiting for a seller reply)."""
    from agent.memory import conversation_memory
    from connector import admin_supabase

    # Build a user lookup (id -> display name / avatar) the same way /users does:
    # auth user_metadata is the source of truth, then the legacy user_profiles
    # row, then the email local-part.
    profiles_map = {}
    users_map = {}
    try:
        profiles = admin_supabase.table('user_profiles').select('id, display_name, avatar_url').execute()
        profiles_map = {p['id']: p for p in (profiles.data or [])}
        for u in admin_supabase.auth.admin.list_users():
            users_map[u.id] = u
    except Exception as e:
        logger.warning(f"Could not enrich chats with user info: {e}")

    def _user_info(user_id: str):
        user = users_map.get(user_id)
        profile = profiles_map.get(user_id, {})
        meta = (user.user_metadata or {}) if user else {}
        email = user.email if user else None
        display_name = (
            meta.get('display_name')
            or profile.get('display_name')
            or (email.split('@')[0] if email else 'Unknown user')
        )
        avatar_url = meta.get('avatar_url') or profile.get('avatar_url')
        return display_name, avatar_url

    # Get all user histories
    all_histories = conversation_memory.get_all_histories()

    chats = []
    for user_id, history in all_histories.items():
        if history:
            last_message = history[-1] if history else None
            last_role = last_message.get('role', '') if last_message else ''
            display_name, avatar_url = _user_info(user_id)
            chats.append({
                "user_id": user_id,
                "display_name": display_name,
                "avatar_url": avatar_url,
                "message_count": len(history),
                "last_message": last_message.get('content', '')[:100] if last_message else '',
                "last_role": last_role,
                "unread": last_role == 'human',
            })

    return chats


@protected.get("/chats/{user_id}")
def get_user_chat(user_id: str, limit: int = 10, offset: int = 0):
    """Get a specific user's conversation history."""
    from agent.memory import conversation_memory

    history = conversation_memory.get_history(user_id, limit=limit, offset=offset)
    return {"user_id": user_id, "messages": history}


@protected.post("/chats/{user_id}/message")
def admin_send_message(user_id: str, request: AdminMessageRequest, admin: dict = Depends(verify_admin)):
    """Send a message to a user as the admin (seller)."""
    from agent.memory import conversation_memory

    # Add the admin's message with source='admin' to differentiate from AI
    conversation_memory.add_message(user_id, "ai", request.message, source="admin")

    write_audit(admin.get("user_id"), admin.get("email"), "chat.message", user_id, admin.get("ip"))
    return {"message": "Message sent successfully"}


# =====================
# Stripe Cleanup
# =====================

@protected.post("/cleanup-stripe")
def cleanup_expired_stripe_links():
    """
    Cleanup expired Stripe payment links.
    Call this periodically (e.g., via cron job) to clean up abandoned payments.
    """
    try:
        from payment.payment_state import cleanup_expired_payments
        cleaned = cleanup_expired_payments()
        return {"message": f"Cleaned up {cleaned} expired payment links"}
    except Exception as e:
        return {"error": str(e)}


# =====================
# Orders Management
# =====================

@protected.get("/orders")
def get_all_orders():
    """Get all orders for admin view with summary stats."""
    from connector import admin_supabase

    result = admin_supabase.table('orders').select('*').order('created_at', desc=True).execute()
    orders_data = result.data or []

    # Enrich with buyer info
    try:
        users_response = admin_supabase.auth.admin.list_users()
        users_map = {u.id: u.email for u in users_response}

        # Build map of names from auth metadata first
        names_map = {}
        for u in users_response:
            meta = u.user_metadata or {}
            # Try to get name from various metadata fields
            name = meta.get('full_name') or meta.get('name') or meta.get('display_name')
            if name:
                names_map[u.id] = name

        # Get profiles for display names (override if exists and not null)
        profiles = admin_supabase.table('user_profiles').select('id, display_name').execute()
        for p in (profiles.data or []):
            if p.get('display_name'):
                names_map[p['id']] = p['display_name']

        for order in orders_data:
            buyer_id = order.get('buyer_id')
            if buyer_id:
                order['buyer_email'] = users_map.get(buyer_id, 'Unknown Email')
                # Use name from map, or fallback to email part, or 'Unknown User'
                email_name = users_map.get(buyer_id, '').split('@')[0] if users_map.get(buyer_id) else 'Unknown User'
                order['buyer_name'] = names_map.get(buyer_id, email_name)
    except Exception as e:
        logger.error(f"Error enriching orders with user data: {e}")

    # Calculate stats
    total_orders = len(orders_data)
    total_sales = sum((order.get('amount') or 0) for order in orders_data)

    return {
        "orders": orders_data,
        "stats": {
            "total_orders": total_orders,
            "total_sales": total_sales
        }
    }


@protected.get("/orders/{order_id}")
def get_order(order_id: str):
    """Get a specific order by ID."""
    from connector import admin_supabase

    result = admin_supabase.table('orders').select('*').eq('id', order_id).execute()
    if result.data:
        return result.data[0]
    raise HTTPException(status_code=404, detail="Order not found")


@protected.put("/orders/{order_id}/status")
def update_order_status(order_id: str, request: OrderStatusUpdate, admin: dict = Depends(verify_admin)):
    """Update order status."""
    from connector import admin_supabase

    valid_statuses = ['pending_info', 'confirmed', 'shipped', 'delivered', 'cancelled', 'refunded']
    if request.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

    result = admin_supabase.table('orders').update({
        'status': request.status
    }).eq('id', order_id).execute()

    if result.data:
        write_audit(admin.get("user_id"), admin.get("email"), f"order.status:{request.status}", order_id, admin.get("ip"))
        return {"message": f"Order status updated to {request.status}"}
    raise HTTPException(status_code=404, detail="Order not found")


@protected.put("/orders/{order_id}")
def update_order(order_id: str, request: OrderUpdate, admin: dict = Depends(verify_admin)):
    """Update order details."""
    from connector import admin_supabase

    # Build update dict with only provided fields
    update_data = {}
    if request.item_name is not None:
        update_data['item_name'] = request.item_name
    if request.amount is not None:
        update_data['amount'] = request.amount
    if request.status is not None:
        valid_statuses = ['pending_info', 'confirmed', 'shipped', 'delivered', 'cancelled', 'refunded']
        if request.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
        update_data['status'] = request.status

    # Handle address - support both frontend 'address' and backend 'shipping_address'
    addr = request.address or request.shipping_address
    if addr is not None:
        update_data['address'] = addr

    # Handle phone - support both frontend 'phone' and backend 'shipping_phone'
    ph = request.phone or request.shipping_phone
    if ph is not None:
        update_data['phone'] = ph

    # Handle recipient name - support both frontend 'recipient_name' and backend 'shipping_name'
    name = request.recipient_name or request.shipping_name
    if name is not None:
        update_data['recipient_name'] = name

    if request.notes is not None:
        update_data['notes'] = request.notes

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = admin_supabase.table('orders').update(update_data).eq('id', order_id).execute()

    if result.data:
        write_audit(admin.get("user_id"), admin.get("email"), "order.update", order_id, admin.get("ip"))
        return {"message": "Order updated successfully", "order": result.data[0]}
    raise HTTPException(status_code=404, detail="Order not found")


@protected.delete("/orders/{order_id}")
def delete_order(order_id: str, admin: dict = Depends(verify_admin)):
    """Delete an order."""
    from connector import admin_supabase

    # Check if order exists first
    check = admin_supabase.table('orders').select('id').eq('id', order_id).execute()
    if not check.data:
        raise HTTPException(status_code=404, detail="Order not found")

    admin_supabase.table('orders').delete().eq('id', order_id).execute()
    write_audit(admin.get("user_id"), admin.get("email"), "order.delete", order_id, admin.get("ip"))
    return {"message": "Order deleted successfully"}


# =====================
# AI Image Analysis
# =====================

async def _encode_images(images: list[UploadFile]) -> list[dict]:
    """Read and base64-encode uploads concurrently, preserving their order."""
    import asyncio
    import base64

    async def encode(img: UploadFile) -> dict:
        contents = await img.read()
        # Encoding a multi-MB photo is CPU work; keep it off the event loop so
        # several images encode at once instead of one after another.
        encoded = await asyncio.to_thread(base64.b64encode, contents)
        return {
            "base64_image": encoded.decode('utf-8'),
            "mime_type": img.content_type or "image/jpeg"
        }

    return list(await asyncio.gather(*(encode(img) for img in images)))


@protected.post("/analyze-image/stream")
async def analyze_item_image_stream(
    images: list[UploadFile] = File(...)
):
    """Streaming twin of /analyze-image.

    Emits Server-Sent Events as each pipeline stage genuinely completes, so the
    client can show a real progress percentage (and fill in fields early)
    instead of animating a fake bar. See agent.tools.listing_pipeline for why
    the stages overlap.
    """
    import asyncio

    from agent.tools.listing_pipeline import analyze_listing

    # Read the uploads before streaming starts — the request body is not
    # available once we've handed back a streaming response.
    images_data = await _encode_images(images)

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_progress(event: dict):
            await queue.put(event)

        async def run():
            try:
                data = await analyze_listing(images_data, on_progress)
                await queue.put({"stage": "done", "progress": 100, "message": "Done", "result": data})
            except Exception as e:
                logger.error(f"Error analyzing image: {e}")
                await queue.put({"stage": "error", "progress": 100, "message": f"Failed to analyze image: {e}"})
            finally:
                await queue.put(None)

        worker = asyncio.create_task(run())
        try:
            yield f"data: {json.dumps({'stage': 'uploaded', 'progress': 10, 'message': 'Photos received'})}\n\n"
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            # The client hung up (or we're done) — don't leave the pipeline running.
            worker.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Tells nginx/Caddy-style proxies not to buffer, which would
            # defeat the whole point of streaming progress.
            "X-Accel-Buffering": "no",
        },
    )


@protected.post("/analyze-image")
async def analyze_item_image(
    images: list[UploadFile] = File(...)
):
    """
    Analyze uploaded images to generate item details (Name, Description, Condition).
    Uses custom Image Analyzer service (Gemini Vision).

    Non-streaming fallback for clients that can't read the SSE variant above.
    """
    from agent.tools.image_analyzer import image_analyzer
    from agent.tools.market_price import market_service

    try:
        images_data = await _encode_images(images)

        # --- Custom Image Analyzer (Gemini Vision) ---
        logger.info(f"Analyzing {len(images_data)} image(s) with custom Image Analyzer...")
        data = await image_analyzer.analyze(images_data)
        logger.info(f"Image analysis result: {data}")

        # --- Market Valuation ---
        try:
            logger.info(f"Fetching market data for: {data.get('name')}")
            market_data = market_service.get_market_valuation(
                query=data.get('name', ''),
                condition=data.get('condition', 'good'),
                category=data.get('category')
            )
            data['market_data'] = market_data
        except Exception as market_error:
            logger.error(f"Market valuation failed: {market_error}")
            data['market_data'] = None

        return data

    except Exception as e:
        logger.error(f"Error analyzing image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze image: {str(e)}") from e


# =====================
# Market Valuation Endpoint
# =====================

@protected.post("/market-valuation")
def get_market_valuation(request: MarketValuationRequest):
    """
    Get market valuation for an item directly.
    Uses custom Market Valuator (NO APIFY - implement your own scraper!).
    """
    from agent.tools.market_price import market_service

    try:
        logger.info(f"Fetching market data for: {request.query} ({request.condition})")
        market_data = market_service.get_market_valuation(
            query=request.query,
            condition=request.condition,
            category=request.category
        )
        return market_data
    except Exception as e:
        logger.error(f"Market valuation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# =====================
# Dashboard summary
# =====================

@protected.get("/summary")
def admin_summary():
    """Aggregate counts for the admin dashboard overview."""
    from connector import admin_supabase

    try:
        users = admin_supabase.auth.admin.list_users()
        user_count = len(users)
    except Exception as e:
        logger.error(f"summary: list_users failed: {e}")
        user_count = 0

    items = (admin_supabase.table('items').select('status').is_('deleted_at', 'null').execute().data) or []
    orders = (admin_supabase.table('orders').select('status, amount').execute().data) or []
    convos = (admin_supabase.table('conversations').select('id').execute().data) or []

    by_status: dict = {}
    for o in orders:
        s = o.get('status') or 'unknown'
        by_status[s] = by_status.get(s, 0) + 1

    return {
        "users": user_count,
        "conversations": len(convos),
        "items_total": len(items),
        "items_available": sum(1 for i in items if i.get('status') != 'sold'),
        "items_sold": sum(1 for i in items if i.get('status') == 'sold'),
        "orders_total": len(orders),
        "orders_pending": by_status.get('pending_info', 0),
        "orders_confirmed": by_status.get('confirmed', 0),
        "orders_shipped": by_status.get('shipped', 0),
        "orders_delivered": by_status.get('delivered', 0),
        "sales_total": sum((o.get('amount') or 0) for o in orders),
    }


# =====================
# Items Management (admin-only; the public /items router is read-only)
# =====================

@protected.get("/items")
def admin_list_items():
    """List every live item (including sold), newest first. Soft-deleted items are hidden."""
    from connector import admin_supabase
    res = admin_supabase.table('items').select('*').is_('deleted_at', 'null').order('created_at', desc=True).execute()
    return res.data or []


@protected.post("/items", status_code=201)
async def admin_create_item(
    name: Annotated[str, Form()],
    description: Annotated[str, Form()],
    condition: Annotated[str, Form()],
    price: Annotated[float, Form()],
    images: Annotated[list[UploadFile], File()],
    min_price: Annotated[float | None, Form()] = None,
    admin: dict = Depends(verify_admin),
):
    """Create a new listing with one or more images."""
    from items import upload_item
    ok = await upload_item(name, description, condition, images, price, min_price)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to create item")
    write_audit(admin.get("user_id"), admin.get("email"), "item.create", name, admin.get("ip"))
    return {"message": "Item created successfully"}


@protected.put("/items/{item_id}")
def admin_update_item(item_id: str, body: UpdateItemSchema, admin: dict = Depends(verify_admin)):
    """Update a listing's fields."""
    from items import update_item
    ok = update_item(
        item_id=item_id,
        name=body.name,
        description=body.description,
        condition=body.condition,
        price=body.price,
        min_price=body.min_price,
        images=body.images,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found or update failed")
    write_audit(admin.get("user_id"), admin.get("email"), "item.update", item_id, admin.get("ip"))
    return {"message": "Item updated successfully"}


@protected.delete("/items/{item_id}")
def admin_delete_item(item_id: str, admin: dict = Depends(verify_admin)):
    """Delete a listing (and its related orders/conversations)."""
    from items import delete_item
    ok = delete_item(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found or delete failed")
    write_audit(admin.get("user_id"), admin.get("email"), "item.delete", item_id, admin.get("ip"))
    return {"message": "Item deleted successfully"}


# Mount the verify_admin-gated routes under the same prefix as the auth routes.
router.include_router(protected)
