from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from admin_auth import verify_admin
import secrets
from typing import Optional, Annotated
from cache import redis_client

router = APIRouter(prefix="/admin", tags=["Admin"])

# Admin session TTL: 2 hours
ADMIN_SESSION_TTL = 7200  # seconds

class AdminLoginRequest(BaseModel):
    username: str
    password: str

class BanRequest(BaseModel):
    is_banned: bool

class AIToggleRequest(BaseModel):
    ai_enabled: bool

class AdminMessageRequest(BaseModel):
    message: str

class UserProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None

@router.post("/login")
def admin_login(request: AdminLoginRequest):
    """Admin login endpoint with 2-hour session TTL."""
    if verify_admin(request.username, request.password):
        # Generate session token and store in Redis with TTL
        token = secrets.token_urlsafe(32)
        redis_client.setex(f"admin_session:{token}", ADMIN_SESSION_TTL, request.username)
        return {"token": token, "message": "Login successful", "expires_in": ADMIN_SESSION_TTL}
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@router.post("/logout")
def admin_logout(token: str):
    """Admin logout endpoint - invalidates token in Redis."""
    redis_client.delete(f"admin_session:{token}")
    return {"message": "Logged out"}

@router.get("/verify")
def verify_token(token: str):
    """Verify if admin token is valid (checks Redis)."""
    username = redis_client.get(f"admin_session:{token}")
    if username:
        # Refresh TTL on each verification (sliding expiration)
        redis_client.expire(f"admin_session:{token}", ADMIN_SESSION_TTL)
        return {"valid": True, "username": username}
    return {"valid": False}


# =====================
# User Management
# =====================

@router.get("/users")
def get_all_users():
    """Get all users with their profiles and chat settings."""
    from connector import admin_supabase
    from fastapi import HTTPException
    
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
            
            users.append({
                "id": user_id,
                "email": user.email,
                "display_name": profile.get('display_name', user.email.split('@')[0] if user.email else 'User'),
                "avatar_url": profile.get('avatar_url'),
                "is_banned": profile.get('is_banned', False),
                "ai_enabled": setting.get('ai_enabled', True),
                "admin_intervening": setting.get('admin_intervening', False),
                "created_at": user.created_at
            })
        
        return users
    except Exception as e:
        print(f"Error in get_all_users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}/profile")
def update_user_profile(user_id: str, request: UserProfileUpdateRequest):
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
    
    return {"message": "User profile updated successfully"}


@router.post("/users/{user_id}/avatar")
async def upload_user_avatar(
    user_id: str,
    avatar: Annotated[UploadFile, File()]
):
    """Upload a user avatar."""
    from connector import admin_supabase
    from fastapi import UploadFile, File
    import base64
    import uuid
    
    contents = await avatar.read()
    
    # Try to use storage first
    try:
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{user_id}_{unique_id}_{avatar.filename}"
        file_path = f"avatars/{filename}"
        
        # Upload to 'user-avatars' bucket (create if needed in Supabase)
        # Using 'item-images' as a shared bucket if users don't have one, 
        # or better, assuming 'avatars' or similar exists. 
        # For safety/simplicity in this environment, let's try 'item-images' 
        # since we know it exists, but organized under 'avatars/' folder.
        
        bucket_name = 'item-images' 
        
        admin_supabase.storage.from_(bucket_name).upload(
            file_path, 
            contents,
            {"content-type": avatar.content_type}
        )
        public_url = admin_supabase.storage.from_(bucket_name).get_public_url(file_path)
        
        # Update profile with URL
        admin_supabase.table('user_profiles').upsert({
            'id': user_id,
            'avatar_url': public_url,
            'updated_at': 'now()'
        }).execute()
        
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
        
        return {"message": "Avatar uploaded (base64)", "avatar_url": data_url}


@router.put("/users/{user_id}/ban")
def ban_user(user_id: str, request: BanRequest):
    """Ban or unban a user."""
    from connector import admin_supabase
    
    # Upsert user profile with ban status
    admin_supabase.table('user_profiles').upsert({
        'id': user_id,
        'is_banned': request.is_banned,
        'updated_at': 'now()'
    }).execute()
    
    return {"message": f"User {'banned' if request.is_banned else 'unbanned'} successfully"}


@router.put("/users/{user_id}/ai")
def toggle_user_ai(user_id: str, request: AIToggleRequest):
    """Enable or disable AI for a specific user."""
    from connector import admin_supabase
    from agent.memory import conversation_memory
    
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
        from env import SUPABASE_URL, SUPABASE_KEY
        
        # Use Supabase REST API to broadcast via realtime channel
        # Format: POST /realtime/v1/api/broadcast with messages array
        broadcast_url = f"{SUPABASE_URL}/realtime/v1/api/broadcast"
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        # Supabase broadcast API expects messages array with channel, event, payload
        payload = {
            "messages": [{
                "topic": f"realtime:chat:{user_id}",
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
        print(f"Broadcast response: {resp.status_code} - {resp.text}")
    except Exception as e:
        print(f"Failed to broadcast system message: {e}")
    
    return {"message": f"AI {'enabled' if request.ai_enabled else 'disabled'} for user"}



# =====================
# Chat Intervention
# =====================

@router.get("/chats")
def get_all_chats():
    """Get list of all active conversations."""
    from agent.memory import conversation_memory
    
    # Get all user histories
    all_histories = conversation_memory.get_all_histories()
    
    chats = []
    for user_id, history in all_histories.items():
        if history:
            last_message = history[-1] if history else None
            chats.append({
                "user_id": user_id,
                "message_count": len(history),
                "last_message": last_message.get('content', '')[:100] if last_message else '',
                "last_role": last_message.get('role', '') if last_message else ''
            })
    
    return chats


@router.get("/chats/{user_id}")
def get_user_chat(user_id: str, limit: int = 10, offset: int = 0):
    """Get a specific user's conversation history."""
    from agent.memory import conversation_memory
    
    history = conversation_memory.get_history(user_id, limit=limit, offset=offset)
    return {"user_id": user_id, "messages": history}


@router.post("/chats/{user_id}/message")
def admin_send_message(user_id: str, request: AdminMessageRequest):
    """Send a message to a user as the admin (seller)."""
    from agent.memory import conversation_memory
    
    # Add the admin's message with source='admin' to differentiate from AI
    conversation_memory.add_message(user_id, "ai", request.message, source="admin")
    
    return {"message": "Message sent successfully"}


# =====================
# Stripe Cleanup
# =====================

@router.post("/cleanup-stripe")
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

@router.get("/orders")
def get_all_orders():
    """Get all orders for admin view with summary stats."""
    from connector import admin_supabase
    
    result = admin_supabase.table('orders').select('*').order('created_at', desc=True).execute()
    orders_data = result.data or []
    
    # Enrich with buyer info
    try:
        users_response = admin_supabase.auth.admin.list_users()
        users_map = {u.id: u.email for u in users_response}
        
        # Get profiles for display names
        profiles = admin_supabase.table('user_profiles').select('id, display_name').execute()
        profiles_map = {p['id']: p['display_name'] for p in (profiles.data or [])}
        
        for order in orders_data:
            buyer_id = order.get('buyer_id')
            if buyer_id:
                order['buyer_email'] = users_map.get(buyer_id, 'Unknown Email')
                order['buyer_name'] = profiles_map.get(buyer_id, 'Unknown User')
    except Exception as e:
        print(f"Error enriching orders with user data: {e}")
    
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


@router.get("/orders/{order_id}")
def get_order(order_id: str):
    """Get a specific order by ID."""
    from connector import admin_supabase
    
    result = admin_supabase.table('orders').select('*').eq('id', order_id).execute()
    if result.data:
        return result.data[0]
    raise HTTPException(status_code=404, detail="Order not found")


class OrderStatusUpdate(BaseModel):
    status: str  # pending_info, confirmed, shipped, delivered


@router.put("/orders/{order_id}/status")
def update_order_status(order_id: str, request: OrderStatusUpdate):
    """Update order status."""
    from connector import admin_supabase
    
    valid_statuses = ['pending_info', 'confirmed', 'shipped', 'delivered', 'cancelled', 'refunded']
    if request.status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    
    result = admin_supabase.table('orders').update({
        'status': request.status
    }).eq('id', order_id).execute()
    
    if result.data:
        return {"message": f"Order status updated to {request.status}"}
    raise HTTPException(status_code=404, detail="Order not found")


class OrderUpdate(BaseModel):
    item_name: Optional[str] = None
    amount: Optional[float] = None
    status: Optional[str] = None
    shipping_address: Optional[str] = None
    shipping_phone: Optional[str] = None
    shipping_name: Optional[str] = None
    notes: Optional[str] = None


@router.put("/orders/{order_id}")
def update_order(order_id: str, request: OrderUpdate):
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
    if request.shipping_address is not None:
        update_data['shipping_address'] = request.shipping_address
    if request.shipping_phone is not None:
        update_data['shipping_phone'] = request.shipping_phone
    if request.shipping_name is not None:
        update_data['shipping_name'] = request.shipping_name
    if request.notes is not None:
        update_data['notes'] = request.notes
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    result = admin_supabase.table('orders').update(update_data).eq('id', order_id).execute()
    
    if result.data:
        return {"message": "Order updated successfully", "order": result.data[0]}
    raise HTTPException(status_code=404, detail="Order not found")


@router.delete("/orders/{order_id}")
def delete_order(order_id: str):
    """Delete an order."""
    from connector import admin_supabase
    
    # Check if order exists first
    check = admin_supabase.table('orders').select('id').eq('id', order_id).execute()
    if not check.data:
        raise HTTPException(status_code=404, detail="Order not found")
    
    admin_supabase.table('orders').delete().eq('id', order_id).execute()
    return {"message": "Order deleted successfully"}


# =====================
# AI Image Analysis
# =====================

@router.post("/analyze-image")
async def analyze_item_image(
    image: Annotated[UploadFile, File()]
):
    """
    Analyze an uploaded image to generate item details (Name, Description, Condition).
    Uses custom Image Analyzer service (Gemini Vision - NO APIFY).
    """
    import base64
    from agent.tools.image_analyzer import image_analyzer
    from agent.tools.market_price import market_service
    
    try:
        # Read image
        contents = await image.read()
        base64_image = base64.b64encode(contents).decode('utf-8')
        image_type = image.content_type or "image/jpeg"
        
        # --- Custom Image Analyzer (Gemini Vision) ---
        print("Analyzing image with custom Image Analyzer...")
        data = await image_analyzer.analyze(base64_image, image_type)
        print(f"Image analysis result: {data}")
        
        # --- Market Valuation ---
        try:
            print(f"Fetching market data for: {data.get('name')}")
            market_data = market_service.get_market_valuation(
                query=data.get('name', ''), 
                condition=data.get('condition', 'good'),
                category=data.get('category')
            )
            data['market_data'] = market_data
        except Exception as market_error:
            print(f"Market valuation failed: {market_error}")
            data['market_data'] = None
        
        return data

    except Exception as e:
        print(f"Error analyzing image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze image: {str(e)}")


# =====================
# Market Valuation Endpoint
# =====================

class MarketValuationRequest(BaseModel):
    query: str
    condition: str = "good"
    category: Optional[str] = None


@router.post("/market-valuation")
def get_market_valuation(request: MarketValuationRequest):
    """
    Get market valuation for an item directly.
    Uses custom Market Valuator (NO APIFY - implement your own scraper!).
    """
    from agent.tools.market_price import market_service
    
    try:
        print(f"Fetching market data for: {request.query} ({request.condition})")
        market_data = market_service.get_market_valuation(
            query=request.query, 
            condition=request.condition,
            category=request.category
        )
        return market_data
    except Exception as e:
        print(f"Market valuation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
