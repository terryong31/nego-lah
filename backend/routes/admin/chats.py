"""Admin chat intervention: read conversations and take over from the AI."""

from fastapi import APIRouter, Depends

from admin_session import verify_admin, write_audit
from logger import logger
from schemas import AdminMessageRequest

from ._profiles import resolve_avatar_url

router = APIRouter()


@router.get("/chats")
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
        avatar_url = resolve_avatar_url(meta, profile)
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


@router.get("/chats/{user_id}")
def get_user_chat(user_id: str, limit: int = 10, offset: int = 0):
    """Get a specific user's conversation history."""
    from agent.memory import conversation_memory

    history = conversation_memory.get_history(user_id, limit=limit, offset=offset)
    return {"user_id": user_id, "messages": history}


@router.post("/chats/{user_id}/message")
def admin_send_message(user_id: str, request: AdminMessageRequest, admin: dict = Depends(verify_admin)):
    """Send a message to a user as the admin (seller)."""
    from agent.memory import conversation_memory

    # Add the admin's message with source='admin' to differentiate from AI
    conversation_memory.add_message(user_id, "ai", request.message, source="admin")

    # Broadcast to live chat via Supabase Realtime
    try:
        from payment.fulfillment import broadcast_to_chat
        broadcast_to_chat(user_id, request.message, role="ai", source="admin")
    except Exception as e:
        logger.warning(f"⚠️ Broadcast to chat failed: {e}")

    # Fall back to email if the buyer has no live SSE stream. The stream itself
    # was already fed by broadcast_to_chat above (source="admin") -- publishing
    # again here delivered every seller message to the buyer twice.
    try:
        from notifications import notification_broker
        is_live = notification_broker.has_subscribers(user_id)

        if not is_live:
            from connector import admin_supabase
            user_res = admin_supabase.auth.admin.get_user_by_id(user_id)
            buyer_email = None
            if user_res and hasattr(user_res, "user") and user_res.user:
                buyer_email = user_res.user.email
            elif user_res and isinstance(user_res, dict):
                buyer_email = user_res.get("email") or (user_res.get("user") or {}).get("email")

            if buyer_email:
                from services.email_service import send_unread_message_email
                send_unread_message_email(buyer_email, request.message)
    except Exception as e:
        logger.warning(f"⚠️ Notification delivery error: {e}")

    write_audit(admin.get("user_id"), admin.get("email"), "chat.message", user_id, admin.get("ip"))
    return {"message": "Message sent successfully"}
