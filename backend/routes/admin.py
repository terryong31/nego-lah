from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from admin_auth import verify_admin
import secrets
from typing import Optional, List

router = APIRouter(prefix="/admin", tags=["Admin"])

# Simple token storage (in production, use Redis or JWT)
admin_tokens = {}

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
    """Admin login endpoint."""
    if verify_admin(request.username, request.password):
        # Generate session token
        token = secrets.token_urlsafe(32)
        admin_tokens[token] = request.username
        return {"token": token, "message": "Login successful"}
    else:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@router.post("/logout")
def admin_logout(token: str):
    """Admin logout endpoint."""
    if token in admin_tokens:
        del admin_tokens[token]
    return {"message": "Logged out"}

@router.get("/verify")
def verify_token(token: str):
    """Verify if admin token is valid."""
    if token in admin_tokens:
        return {"valid": True, "username": admin_tokens[token]}
    return {"valid": False}


# =====================
# User Management
# =====================

@router.get("/users")
def get_all_users():
    """Get all users with their profiles and chat settings."""
    from connector import admin_supabase
    
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
