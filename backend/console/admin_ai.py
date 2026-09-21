"""
The admin AI toggle — identity and negotiation in one screen (SPEC-097).

Turning the agent off for a buyer writes negotiation's `chat_settings`, posts a
system line into that conversation, and writes identity's audit log. Two
domains, and `identity` sits BELOW `negotiation`, so it cannot be the one to
call it. Composition code can, which is why these two routes live here rather
than beside the rest of `/users` in the identity domain.
"""

from fastapi import APIRouter, Depends

from core.logger import logger
from core.schemas import AIToggleRequest
from domains.identity import verify_admin, write_audit
from domains.negotiation import NegotiationService

router = APIRouter()


@router.get("/users/{user_id}/ai")
def get_user_ai_status(user_id: str, admin: dict = Depends(verify_admin)):
    """Get the current AI status for a user."""
    ai_enabled = True
    try:
        ai_enabled = NegotiationService.is_ai_enabled(user_id)
    except Exception as e:
        logger.debug(f"Could not check ai_enabled for {user_id}: {e}")
    return {"user_id": user_id, "ai_enabled": ai_enabled}


@router.put("/users/{user_id}/ai")
def toggle_user_ai(user_id: str, request: AIToggleRequest, admin: dict = Depends(verify_admin)):
    """Enable or disable AI for a specific user."""
    NegotiationService.set_ai_enabled(user_id, request.ai_enabled)

    # Add system message to notify user
    if request.ai_enabled:
        system_msg = "--- Terry has retired from the chat and the AI will take over now ---"
    else:
        system_msg = "--- Terry has joined the chat, the AI will retire for now ---"

    NegotiationService.add_system_message(user_id, system_msg)

    # Live on both sides: the buyer's open tab and the admin console read the
    # same authenticated stream (SPEC-094). This used to POST straight at the
    # Supabase Realtime broadcast API on a public topic.
    try:
        from core.broadcast import broadcast_to_chat

        broadcast_to_chat(user_id, system_msg, role="system", source="system")
    except Exception as e:
        logger.error(f"Failed to broadcast system message: {e}")

    write_audit(
        admin.get("user_id"),
        admin.get("email"),
        "user.ai_enable" if request.ai_enabled else "user.ai_disable",
        user_id,
        admin.get("ip"),
    )
    return {"message": f"AI {'enabled' if request.ai_enabled else 'disabled'} for user"}
