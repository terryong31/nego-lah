"""
User account management.

Authentication itself (login / register / logout / password reset) is handled
client-side by the Supabase JS SDK using the anon key - it does not belong on
the backend. What lives here are the privileged account operations that REQUIRE
the service role key and therefore cannot be done safely from the browser:

  - delete account
  - change password
  - change email

Every endpoint requires a valid JWT and enforces that the caller can only act
on their own account (token user id must match the path user id).
"""

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth_middleware import get_user_id_from_body_or_token, verify_user_token
from cache import invalidate_token
from connector import admin_supabase, user_supabase
from core.uploads import validate_image_upload
from env import STORAGE_BUCKET
from logger import logger
from schemas import EmailUpdateSchema, LanguageUpdateSchema, PasswordUpdateSchema

SUPPORTED_LANGUAGES = {"en", "ms", "zh"}

router = APIRouter(prefix="/user", tags=["User"])


@router.get("/{user_id}/account")
def account_status(user_id: str, token_user_id: str = Depends(verify_user_token)):
    """
    Lightweight probe used by the login flow. `verify_user_token` already raises
    403 for a banned account, so reaching the body means the user is allowed in.
    """
    get_user_id_from_body_or_token(user_id, token_user_id)
    return {"banned": False}


def _get_user_email(user_id: str) -> str:
    """Look up a user's email via the admin API."""
    result = admin_supabase.auth.admin.get_user_by_id(user_id)
    if not result or not result.user:
        raise HTTPException(status_code=404, detail="User not found")
    return result.user.email


@router.put("/{user_id}/password")
def change_password(
    user_id: str,
    payload: PasswordUpdateSchema,
    token_user_id: str = Depends(verify_user_token)
):
    """Change the authenticated user's password (verifies the current password first)."""
    get_user_id_from_body_or_token(user_id, token_user_id)

    email = _get_user_email(user_id)

    # Verify the current password by attempting a sign-in with the anon client
    try:
        user_supabase.auth.sign_in_with_password({
            "email": email,
            "password": payload.current_password
        })
    except Exception:
        raise HTTPException(status_code=401, detail="Current password is incorrect") from None

    try:
        admin_supabase.auth.admin.update_user_by_id(
            user_id, {"password": payload.new_password}
        )
    except Exception as e:
        logger.error(f"Error changing password for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to change password") from e

    return {"message": "Password changed successfully"}


@router.put("/{user_id}/email")
def change_email(
    user_id: str,
    payload: EmailUpdateSchema,
    token_user_id: str = Depends(verify_user_token)
):
    """Change the authenticated user's email address."""
    get_user_id_from_body_or_token(user_id, token_user_id)

    try:
        admin_supabase.auth.admin.update_user_by_id(
            user_id, {"email": payload.new_email, "email_confirm": True}
        )
    except Exception as e:
        logger.error(f"Error changing email for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to change email") from e

    return {"message": "Email changed successfully", "email": payload.new_email}


@router.put("/{user_id}/language")
def update_language(
    user_id: str,
    payload: LanguageUpdateSchema,
    token_user_id: str = Depends(verify_user_token)
):
    """
    Update the authenticated user's preferred language in Supabase auth user_metadata.
    Supported languages: 'en' (English), 'ms' (Bahasa Melayu), 'zh' (Simplified Chinese).
    """
    get_user_id_from_body_or_token(user_id, token_user_id)
    lang = payload.language.lower().strip()
    if lang not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{payload.language}'. Supported languages: {', '.join(sorted(SUPPORTED_LANGUAGES))}"
        )

    existing = admin_supabase.auth.admin.get_user_by_id(user_id)
    if not existing or not existing.user:
        raise HTTPException(status_code=404, detail="User not found")

    metadata = dict(existing.user.user_metadata or {})
    metadata["preferred_language"] = lang

    try:
        admin_supabase.auth.admin.update_user_by_id(
            user_id, {"user_metadata": metadata}
        )
    except Exception as e:
        logger.error(f"Error updating language for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update language") from e

    return {"message": "Language updated", "preferred_language": lang}


@router.put("/{user_id}/profile")
async def update_profile(
    user_id: str,
    token_user_id: str = Depends(verify_user_token),
    display_name: Annotated[str | None, Form()] = None,
    avatar: Annotated[UploadFile | None, File()] = None,
):
    """
    Update the authenticated user's display name and/or profile picture.

    The avatar is uploaded to storage server-side using the service role key -
    clients are never allowed to write to the bucket directly (read-only).
    Both values are stored in the Supabase auth user_metadata, the avatar under
    `custom_avatar_url` so an OAuth sign-in can't overwrite it.
    """
    get_user_id_from_body_or_token(user_id, token_user_id)

    # Supabase's client is synchronous. This handler has to stay `async def`
    # (it awaits the upload), so every call below goes through a thread —
    # otherwise a 2MB avatar upload freezes the worker for every other user.
    existing = await asyncio.to_thread(admin_supabase.auth.admin.get_user_by_id, user_id)
    if not existing or not existing.user:
        raise HTTPException(status_code=404, detail="User not found")
    metadata = dict(existing.user.user_metadata or {})

    if avatar is not None:
        contents = await avatar.read()
        # Both the type and the extension come from the bytes, never from the
        # request (SPEC-044 C). The bucket is public: a forwarded `text/html`
        # got HTML served as HTML from our own storage origin, and an
        # unsanitised filename put slashes into the storage key.
        content_type, ext = validate_image_upload(contents)
        file_path = f"avatars/{user_id}/{uuid.uuid4().hex}.{ext}"
        try:
            def _upload() -> str:
                admin_supabase.storage.from_(STORAGE_BUCKET).upload(
                    file_path,
                    contents,
                    {
                        "content-type": content_type,
                        "upsert": "true",
                    },
                )
                return admin_supabase.storage.from_(STORAGE_BUCKET).get_public_url(file_path)

            # Deliberately NOT `avatar_url`: Supabase re-syncs user_metadata from
            # the identity provider's claims on every OAuth sign-in, and Google's
            # claims carry `avatar_url` / `picture`. Writing there means the next
            # Google login silently replaces the user's upload with their Google
            # photo. `custom_avatar_url` is ours alone, so it survives.
            metadata["custom_avatar_url"] = await asyncio.to_thread(_upload)
        except Exception as e:
            logger.error(f"Avatar upload failed for {user_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to upload avatar") from e

    if display_name is not None:
        metadata["display_name"] = display_name

    try:
        await asyncio.to_thread(
            admin_supabase.auth.admin.update_user_by_id,
            user_id,
            {"user_metadata": metadata},
        )
    except Exception as e:
        logger.error(f"Profile update failed for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile") from e

    return {
        "message": "Profile updated successfully",
        "display_name": metadata.get("display_name"),
        # The *effective* avatar, resolved the same way the clients resolve it.
        "avatar_url": metadata.get("custom_avatar_url") or metadata.get("avatar_url"),
    }


@router.delete("/{user_id}")
def delete_account(
    user_id: str,
    request: Request,
    token_user_id: str = Depends(verify_user_token)
):
    """
    Permanently delete the authenticated user's account.

    Removes app-side data (profile, chat settings, conversations) and the
    Supabase auth user. Orders/transactions are intentionally retained as
    business records.
    """
    get_user_id_from_body_or_token(user_id, token_user_id)

    # Best-effort cleanup of app data (don't abort the delete if a table is empty)
    for table, column in [
        ("chat_settings", "user_id"),
        ("conversations", "user_id"),
        # SPEC-043 moved history here. Both tables are listed: `conversations`
        # still holds everything written before the cutover, and leaving it
        # behind would keep a deleted user's transcript on disk.
        ("messages", "user_id"),
        ("user_profiles", "id"),
    ]:
        try:
            admin_supabase.table(table).delete().eq(column, user_id).execute()
        except Exception as e:
            logger.warning(f"Could not clean up {table} for {user_id}: {e}")

    # Delete the auth user (requires service role)
    try:
        admin_supabase.auth.admin.delete_user(user_id)
    except Exception as e:
        logger.error(f"Error deleting auth user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete account") from e

    # Invalidate the cached token so the deleted session can't be reused
    auth_header = request.headers.get("Authorization", "")
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        invalidate_token(parts[1])

    return {"message": "Account deleted successfully"}
