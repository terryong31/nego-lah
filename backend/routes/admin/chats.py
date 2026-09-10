"""Admin chat intervention: read conversations and take over from the AI."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from admin_session import verify_admin, write_audit
from logger import logger
from schemas import AdminArchiveRequest, AdminMessageRequest, AdminReadStateRequest

from ._profiles import resolve_avatar_url

router = APIRouter()


def _parse_ts(value):
    """Parse a Postgres timestamptz string, or None if it isn't one.

    Postgres hands back `...Z` and `...+00:00` interchangeably depending on the
    driver, and a hand-written row can carry neither. Anything unparseable
    returns None so the caller falls back to the pre-SPEC-053 rule rather than
    guessing — a wrong guess here silently hides a customer's message.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    # A naive timestamp compared against an aware one raises; assume UTC, which
    # is what every writer here stores.
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_unread(admin_last_read_at, last_human_at, last_role: str) -> bool:
    """SPEC-053 — true when a customer message is newer than the watermark.

    With no usable watermark (never marked, or a value we can't read) this is
    the original rule: the customer spoke last and is still waiting.
    """
    from agent.memory import MESSAGE_FUTURE_GRACE

    read_at = _parse_ts(admin_last_read_at)
    if read_at is None:
        return last_role == 'human'

    human_at = _parse_ts(last_human_at)
    if human_at is None or human_at > datetime.now(UTC) + MESSAGE_FUTURE_GRACE:
        # Marked read, and nothing datable from the customer since. Trust the
        # mark — that is the whole point of having one.
        #
        # "Nothing datable" includes a row from the future (SPEC-066): every
        # message written before that fix carries the API host's local time in
        # a UTC column, so on a UTC+8 host it is dated eight hours out and beats
        # any watermark the seller can write. It is not a message they have yet
        # to read — it is one they read this morning.
        return False
    return human_at > read_at


def _stamp_read(user_id: str, read_at: str | None):
    """Write (or clear) a conversation's read watermark. Raises on failure."""
    from connector import admin_supabase

    admin_supabase.table('chat_settings').upsert({
        'user_id': user_id,
        'admin_last_read_at': read_at,
        'updated_at': 'now()',
    }).execute()


def _stamp_archived(user_id: str, archived_at: str | None):
    """Move a conversation out of the console list, or back in. Raises on failure."""
    from connector import admin_supabase

    admin_supabase.table('chat_settings').upsert({
        'user_id': user_id,
        'archived_at': archived_at,
        'updated_at': 'now()',
    }).execute()


@router.get("/chats")
def get_all_chats(include_archived: bool = False):
    """Get list of all active conversations, enriched with the user's display
    name / avatar and an `unread` flag.

    `unread` is the seller's read watermark (SPEC-053): true when the newest
    CUSTOMER message is newer than `chat_settings.admin_last_read_at`. A
    conversation that has never been marked falls back to the original rule —
    the customer sent the last message and is still waiting for a reply.

    Archived conversations (SPEC-063) are omitted unless `include_archived`.
    Every row also carries the identity fields the console's customer panel
    shows — this handler already holds every auth user and profile, so asking
    for them again from a second endpoint would be a round trip for data that
    is already in hand.
    """
    from agent.memory import conversation_memory
    from connector import admin_supabase

    # Build a user lookup (id -> display name / avatar) the same way /users does:
    # auth user_metadata is the source of truth, then the legacy user_profiles
    # row, then the email local-part.
    profiles_map = {}
    users_map = {}
    settings_map = {}
    last_activity_map = {}
    last_human_map = {}
    try:
        profiles = admin_supabase.table('user_profiles').select('id, display_name, avatar_url').execute()
        profiles_map = {p['id']: p for p in (profiles.data or [])}
        for u in admin_supabase.auth.admin.list_users():
            users_map[u.id] = u
        # HITL status + read watermark per conversation — same bulk read /users
        # uses (SPEC-046 #39, SPEC-053).
        settings = admin_supabase.table('chat_settings').select(
            'user_id, ai_enabled, admin_intervening, admin_last_read_at, archived_at'
        ).execute()
        settings_map = {s.get('user_id'): s for s in (settings.data or []) if s.get('user_id')}
        # Newest message per conversation, and separately the newest CUSTOMER
        # message: the first drives the "recent activity" sort (SPEC-046 #42),
        # the second decides `unread`. One descending read answers both, so the
        # first row seen per user (per role) is that conversation's latest.
        ts_rows = admin_supabase.table('messages').select('user_id, role, created_at').order(
            'created_at', desc=True
        ).execute()
        for row in (ts_rows.data or []):
            uid = row.get('user_id')
            if not uid:
                continue
            if uid not in last_activity_map:
                last_activity_map[uid] = row.get('created_at')
            if row.get('role') == 'human' and uid not in last_human_map:
                last_human_map[uid] = row.get('created_at')
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
        return {
            "display_name": display_name,
            "avatar_url": resolve_avatar_url(meta, profile),
            "email": email,
            "created_at": getattr(user, 'created_at', None) if user else None,
            "is_banned": bool(profile.get('is_banned', False)),
        }

    # Get all user histories
    all_histories = conversation_memory.get_all_histories()

    chats = []
    for user_id, history in all_histories.items():
        if history:
            setting = settings_map.get(user_id, {})
            archived_at = setting.get('archived_at')
            if archived_at and not include_archived:
                continue

            last_message = history[-1] if history else None
            last_role = last_message.get('role', '') if last_message else ''
            info = _user_info(user_id)
            read_at = setting.get('admin_last_read_at')
            chats.append({
                "user_id": user_id,
                "display_name": info["display_name"],
                "avatar_url": info["avatar_url"],
                "email": info["email"],
                "created_at": info["created_at"],
                "is_banned": info["is_banned"],
                "message_count": len(history),
                "last_message": last_message.get('content', '')[:100] if last_message else '',
                "last_role": last_role,
                "unread": _is_unread(read_at, last_human_map.get(user_id), last_role),
                "admin_last_read_at": read_at,
                "archived": bool(archived_at),
                "archived_at": archived_at,
                "ai_enabled": setting.get('ai_enabled', True),
                "admin_intervening": setting.get('admin_intervening', False),
                "last_activity": last_activity_map.get(user_id),
            })

    return chats


@router.get("/chats/{user_id}")
def get_user_chat(user_id: str, limit: int = 10, offset: int = 0):
    """Get a specific user's conversation history."""
    from agent.memory import conversation_memory

    history = conversation_memory.get_history(user_id, limit=limit, offset=offset)
    return {"user_id": user_id, "messages": history}


@router.post("/chats/{user_id}/read")
def set_chat_read_state(
    user_id: str,
    request: AdminReadStateRequest = AdminReadStateRequest(),
    admin: dict = Depends(verify_admin),
):
    """Mark a conversation read (or back to unread) — SPEC-053.

    `read: true` stamps the watermark over every customer message already in
    the thread, which clears the dot until they say something new. `read:
    false` clears it, putting the thread back in the Unread filter so it can be
    triaged later.

    The mark covers the transcript rather than reading the clock (SPEC-066):
    rows written before that fix carry the API host's local time in a UTC
    column, and a `now` stamp never gets past them.
    """
    from agent.memory import conversation_memory

    read_at = conversation_memory.read_watermark(user_id, 'human') if request.read else None

    try:
        _stamp_read(user_id, read_at)
    except Exception as e:
        # Surfaced rather than swallowed: a click that silently does nothing is
        # exactly the bug this spec exists to fix.
        logger.warning(f"⚠️ Failed to write read state for {user_id}: {e}")
        raise HTTPException(status_code=503, detail="Could not update read state") from e

    write_audit(admin.get("user_id"), admin.get("email"), "chat.read", user_id, admin.get("ip"))
    return {"user_id": user_id, "unread": not request.read, "admin_last_read_at": read_at}


@router.post("/chats/{user_id}/archive")
def set_chat_archived(
    user_id: str,
    request: AdminArchiveRequest = AdminArchiveRequest(),
    admin: dict = Depends(verify_admin),
):
    """Archive a conversation out of the console list, or restore it — SPEC-063.

    Reversible by construction: this writes one timestamp and never touches
    `messages`. Mounted on the `protected` router, so the admin session and the
    CSRF header are already required by the time this runs.
    """
    archived_at = datetime.now(UTC).isoformat() if request.archived else None

    try:
        _stamp_archived(user_id, archived_at)
    except Exception as e:
        # Same rule as the read watermark: a click that silently does nothing is
        # the bug, not the error message.
        logger.warning(f"⚠️ Failed to write archive state for {user_id}: {e}")
        raise HTTPException(status_code=503, detail="Could not update archive state") from e

    action = "chat.archive" if request.archived else "chat.unarchive"
    write_audit(admin.get("user_id"), admin.get("email"), action, user_id, admin.get("ip"))
    return {"user_id": user_id, "archived": request.archived, "archived_at": archived_at}


@router.post("/chats/{user_id}/message")
def admin_send_message(user_id: str, request: AdminMessageRequest, admin: dict = Depends(verify_admin)):
    """Send a message to a user as the admin (seller)."""
    from agent.memory import conversation_memory

    # Add the admin's message with source='admin' to differentiate from AI
    conversation_memory.add_message(user_id, "ai", request.message, source="admin")

    # Replying is proof of having read it, so the watermark moves with the
    # reply — otherwise the dot would clear only until the next list refresh.
    try:
        _stamp_read(user_id, conversation_memory.read_watermark(user_id, "human"))
    except Exception as e:
        logger.warning(f"⚠️ Failed to stamp read state on reply for {user_id}: {e}")

    # Broadcast to live chat via Supabase Realtime
    try:
        from payment.fulfillment import broadcast_to_chat
        broadcast_to_chat(user_id, request.message, role="ai", source="admin")
    except Exception as e:
        logger.warning(f"⚠️ Broadcast to chat failed: {e}")

    # Queue for the digest if the buyer has no live SSE stream. The stream
    # itself was already fed by broadcast_to_chat above (source="admin") --
    # publishing again here delivered every seller message to the buyer twice.
    #
    # SPEC-052: this used to email immediately, one email per bubble. It now
    # queues, and the sweeper sends ONE email covering everything still unread
    # five minutes later — or none at all, if the buyer comes back and reads.
    try:
        from notifications import notification_broker

        if not notification_broker.has_subscribers(user_id):
            from services.unread_digest import queue_unread_message
            queue_unread_message(user_id, request.message)
    except Exception as e:
        logger.warning(f"⚠️ Notification delivery error: {e}")

    write_audit(admin.get("user_id"), admin.get("email"), "chat.message", user_id, admin.get("ip"))
    return {"message": "Message sent successfully"}
