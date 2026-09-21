"""Admin user management: listing, profile edits, avatars, bans, deletion.

The AI toggle used to live here too and is now in `console/admin_ai.py`:
identity sits below negotiation and may not call it (SPEC-097). What is left
reaches negotiation only through `core.bus` — a question it asks without naming
who answers, and an announcement it makes without knowing who listens.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from core import bus
from core.env import STORAGE_BUCKET
from core.images import MAX_AVATAR_EDGE, process_upload
from core.logger import logger
from core.schemas import BanRequest, UserProfileUpdateRequest
from core.uploads import MAX_AVATAR_IMAGE_BYTES
from domains.identity.admin_session import verify_admin, write_audit
from domains.identity.services import IdentityService

from .profiles import resolve_avatar_url

router = APIRouter()


@router.get("/users")
def get_all_users():
    """Get all users with their profiles and chat settings."""
    from fastapi import HTTPException

    from core.connector import admin_supabase

    try:
        # Get all users from auth
        users_response = admin_supabase.auth.admin.list_users()

        # Get profiles and chat settings
        profiles = admin_supabase.table("user_profiles").select("*").execute()
        settings_map = bus.ask("negotiation.ai_settings_map", {})

        profiles_map = {p["id"]: p for p in (profiles.data or [])}

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
                meta.get("display_name")
                or profile.get("display_name")
                or (user.email.split("@")[0] if user.email else "User")
            )
            avatar_url = resolve_avatar_url(meta, profile)

            users.append(
                {
                    "id": user_id,
                    "email": user.email,
                    "display_name": display_name,
                    "avatar_url": avatar_url,
                    "is_banned": profile.get("is_banned", False),
                    "ai_enabled": setting.get("ai_enabled", True),
                    "admin_intervening": setting.get("admin_intervening", False),
                    "created_at": user.created_at,
                }
            )

        return users
    except Exception as e:
        logger.error(f"Error in get_all_users: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/users/{user_id}/profile")
def update_user_profile(user_id: str, request: UserProfileUpdateRequest, admin: dict = Depends(verify_admin)):
    """Update a user's profile (display name, avatar)."""
    from core.connector import admin_supabase

    updates = {"id": user_id, "updated_at": "now()"}

    if request.display_name is not None:
        updates["display_name"] = request.display_name

    if request.avatar_url is not None:
        updates["avatar_url"] = request.avatar_url

    admin_supabase.table("user_profiles").upsert(updates).execute()
    write_audit(admin.get("user_id"), admin.get("email"), "user.profile_update", user_id, admin.get("ip"))
    return {"message": "User profile updated successfully"}


@router.post("/users/{user_id}/avatar")
async def upload_user_avatar(
    user_id: str,
    avatar: Annotated[UploadFile, File()],
    admin: dict = Depends(verify_admin),
):
    """Upload a user avatar."""
    import base64
    import uuid

    from core.connector import admin_supabase

    contents = await avatar.read()

    # Outside the try below, deliberately: that block falls back to inlining the
    # bytes as a `data:` URL, so validating inside it would turn a rejected file
    # into a stored `data:text/html` profile picture instead of a 400.
    contents, content_type, ext = await asyncio.to_thread(
        process_upload,
        contents,
        max_edge=MAX_AVATAR_EDGE,
        max_bytes=MAX_AVATAR_IMAGE_BYTES,
    )

    # Supabase's client is synchronous and this handler must stay `async def`
    # (it awaits the upload), so the storage round trip goes through a thread —
    # on the event loop it would stall every buyer this worker is serving.
    # Try to use storage first
    try:
        unique_id = str(uuid.uuid4())[:8]
        # Every part of the key is chosen here — `user_id` is a path parameter
        # and the rest is generated. The uploaded filename used to be
        # interpolated in raw, which put client-controlled slashes in the path.
        file_path = f"avatars/{user_id}_{unique_id}.{ext}"

        def _store() -> str:
            admin_supabase.storage.from_(STORAGE_BUCKET).upload(file_path, contents, {"content-type": content_type})
            url = admin_supabase.storage.from_(STORAGE_BUCKET).get_public_url(file_path)
            admin_supabase.table("user_profiles").upsert(
                {"id": user_id, "avatar_url": url, "updated_at": "now()"}
            ).execute()
            return url

        public_url = await asyncio.to_thread(_store)

        write_audit(admin.get("user_id"), admin.get("email"), "user.avatar_upload", user_id, admin.get("ip"))
        return {"message": "Avatar uploaded successfully", "avatar_url": public_url}

    except Exception as e:
        # Fallback to base64 data URL if storage fails. It works, but it inlines
        # the whole image into every profile response — worth knowing about.
        logger.warning(f"Avatar storage upload failed for {user_id}, falling back to base64: {e}")
        base64_image = base64.b64encode(contents).decode("utf-8")
        data_url = f"data:{content_type};base64,{base64_image}"

        await asyncio.to_thread(
            lambda: (
                admin_supabase.table("user_profiles")
                .upsert({"id": user_id, "avatar_url": data_url, "updated_at": "now()"})
                .execute()
            )
        )

        write_audit(admin.get("user_id"), admin.get("email"), "user.avatar_upload", user_id, admin.get("ip"))
        return {"message": "Avatar uploaded (base64)", "avatar_url": data_url}


@router.put("/users/{user_id}/ban")
def ban_user(user_id: str, request: BanRequest, admin: dict = Depends(verify_admin)):
    """Ban or unban a user."""
    from core.connector import admin_supabase
    from domains.identity.admin_session import _is_admin_user

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
    admin_supabase.table("user_profiles").upsert(
        {"id": user_id, "is_banned": request.is_banned, "updated_at": "now()"}
    ).execute()

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
    from core.cache import invalidate_ban_status

    invalidate_ban_status(user_id)

    write_audit(
        admin.get("user_id"),
        admin.get("email"),
        "user.ban" if request.is_banned else "user.unban",
        user_id,
        admin.get("ip"),
    )
    return {"message": f"User {'banned' if request.is_banned else 'unbanned'} successfully"}


@router.delete("/users/{user_id}")
def admin_delete_user(user_id: str, admin: dict = Depends(verify_admin)):
    """Permanently delete a user: app-side data + the Supabase auth user.
    Orders are intentionally retained as business records."""
    from core.connector import admin_supabase

    # Each domain erases its own rows. Identity does not know who else stores
    # data about a user, and must not: subscribers clean up after this event.
    # Orders are intentionally retained as business records.
    bus.emit("user.deleted", user_id=user_id)
    IdentityService.purge_user_profile(user_id)

    try:
        admin_supabase.auth.admin.delete_user(user_id)
    except Exception as e:
        logger.error(f"Error deleting auth user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete user") from e

    write_audit(admin.get("user_id"), admin.get("email"), "user.delete", user_id, admin.get("ip"))
    return {"message": "User deleted successfully"}
