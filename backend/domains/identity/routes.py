"""
User account management.

Authentication itself (login / register / logout / password reset) is handled
client-side by the Supabase JS SDK using the anon key - it does not belong on
the backend. What lives here are the privileged account operations that REQUIRE
the service role key and therefore cannot be done safely from the browser:

  - delete account
  - change password
  - change email

Every endpoint requires a valid session and enforces that the caller can only act
on their own account (token user id must match the path user id).
"""

import asyncio
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile

from core import bus
from core.cache import cache_ban_status, check_rate_limit, invalidate_token
from core.connector import admin_supabase, new_user_client
from core.csrf import verify_user_csrf_token
from core.env import API_BASE_URL, STORAGE_BUCKET
from core.images import MAX_AVATAR_EDGE, process_upload
from core.logger import logger
from core.schemas import (
    AccountDeleteSchema,
    EmailUpdateSchema,
    LanguageUpdateSchema,
    PasswordUpdateSchema,
)
from core.uploads import MAX_AVATAR_IMAGE_BYTES
from domains.identity.auth_middleware import get_user_id_from_body_or_token, verify_user_token
from domains.identity.services import IdentityService
from domains.identity.user_session import clear_session_cookies

SUPPORTED_LANGUAGES = {"en", "ms", "zh"}

# SPEC-056 #7. Password guessing is an attack on ONE ACCOUNT mounted from
# wherever the attacker likes, so throttling it per IP is the wrong axis — a
# botnet sails through, and a conference behind one NAT address gets punished
# for nobody's mistake. Count the failures against the account instead.
REAUTH_MAX_ATTEMPTS = int(os.getenv("REAUTH_MAX_ATTEMPTS", "10"))
REAUTH_WINDOW_SECONDS = int(os.getenv("REAUTH_WINDOW_SECONDS", "900"))

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


def _reauthenticate(user_id: str, current_password: str):
    """Prove the person holding this access token also knows the password.

    A bearer token is a *session*; it can be lifted by XSS or off an unlocked
    device. That is fine for reading a profile and not fine for the two
    operations that end an account's life — changing the address it is
    recovered through, and deleting it (SPEC-056 #3/#7). Both now demand the
    password as well, the way `change_password` always has.

    Returns the signed-in client so the caller can act as the user; see
    `new_user_client` for why it must not be the shared singleton.
    """
    if not check_rate_limit(f"reauth:{user_id}", max_requests=REAUTH_MAX_ATTEMPTS, window=REAUTH_WINDOW_SECONDS):
        raise HTTPException(
            status_code=429,
            detail="Too many password attempts. Please wait a few minutes and try again.",
        )

    email = _get_user_email(user_id)
    session = new_user_client()
    try:
        session.auth.sign_in_with_password({"email": email, "password": current_password})
    except Exception:
        raise HTTPException(status_code=401, detail="Current password is incorrect") from None
    return session


@router.put("/{user_id}/password", dependencies=[Depends(verify_user_csrf_token)])
def change_password(
    user_id: str, payload: PasswordUpdateSchema, request: Request, token_user_id: str = Depends(verify_user_token)
):
    """Change the authenticated user's password (verifies the current password first)."""
    get_user_id_from_body_or_token(user_id, token_user_id)

    _reauthenticate(user_id, payload.current_password)

    try:
        admin_supabase.auth.admin.update_user_by_id(user_id, {"password": payload.new_password})
    except Exception as e:
        logger.error(f"Error changing password for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to change password") from e

    return {"message": "Password changed successfully"}


@router.put("/{user_id}/email", dependencies=[Depends(verify_user_csrf_token)])
def change_email(
    user_id: str, payload: EmailUpdateSchema, request: Request, token_user_id: str = Depends(verify_user_token)
):
    """Request a change of the authenticated user's email address.

    SPEC-056 #3. This used to hand `{"email": ..., "email_confirm": True}` to the
    admin API with no password check: the new address was marked verified on the
    spot, and neither the old nor the new inbox heard about it. A stolen access
    token was therefore a permanent account takeover — the attacker owns the
    address that password resets go to, and the real owner has no notification
    and no way back.

    Now it costs the password, and the update runs on the user's OWN session, so
    Supabase treats it as a change request and mails the confirmation link. The
    address does not move until someone clicks it.
    """
    get_user_id_from_body_or_token(user_id, token_user_id)

    session = _reauthenticate(user_id, payload.current_password)

    try:
        # The confirmation link has to come back to the API, which redeems it and
        # opens the session before handing the browser to the app (SPEC-093).
        session.auth.update_user(
            {"email": payload.new_email},
            {"email_redirect_to": f"{API_BASE_URL}/auth/callback"},
        )
    except Exception as e:
        logger.error(f"Error changing email for {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to change email") from e

    return {
        "message": "Confirmation email sent",
        "email": payload.new_email,
        "confirmation_required": True,
    }


@router.put("/{user_id}/language", dependencies=[Depends(verify_user_csrf_token)])
def update_language(
    user_id: str, payload: LanguageUpdateSchema, request: Request, token_user_id: str = Depends(verify_user_token)
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
            detail=f"Unsupported language '{payload.language}'. Supported languages: {', '.join(sorted(SUPPORTED_LANGUAGES))}",
        )

    existing = admin_supabase.auth.admin.get_user_by_id(user_id)
    if not existing or not existing.user:
        raise HTTPException(status_code=404, detail="User not found")

    metadata = dict(existing.user.user_metadata or {})
    metadata["preferred_language"] = lang

    try:
        admin_supabase.auth.admin.update_user_by_id(user_id, {"user_metadata": metadata})
        try:
            from core.cache import redis_client

            if redis_client:
                redis_client.set(f"user:{user_id}:lang", lang, ex=86400)
        except Exception as cache_err:
            logger.debug(f"Redis language cache write failed for {user_id}: {cache_err}")
    except Exception as e:
        logger.error(f"Error updating language for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to update language") from e

    return {"message": "Language updated", "preferred_language": lang}


def get_user_preferred_language(user_id: str | None) -> str:
    """Retrieve user's preferred language from Redis cache or Supabase auth metadata.

    Returns 'en', 'ms', or 'zh' (defaulting to 'en' on miss or error).
    """
    if not user_id:
        return "en"

    cache_key = f"user:{user_id}:lang"
    try:
        from core.cache import redis_client

        if redis_client:
            cached = redis_client.get(cache_key)
            if cached:
                cached_str = cached.decode("utf-8") if isinstance(cached, bytes) else str(cached)
                if cached_str in SUPPORTED_LANGUAGES:
                    return cached_str
    except Exception as e:
        logger.debug(f"Redis language cache read failed for {user_id}: {e}")

    try:
        user_res = admin_supabase.auth.admin.get_user_by_id(user_id)
        if user_res and getattr(user_res, "user", None):
            meta_lang = (user_res.user.user_metadata or {}).get("preferred_language")
            if meta_lang and str(meta_lang).lower().strip() in SUPPORTED_LANGUAGES:
                normalized = str(meta_lang).lower().strip()
                try:
                    from core.cache import redis_client

                    if redis_client:
                        redis_client.set(cache_key, normalized, ex=86400)
                except Exception as cache_err:
                    logger.debug(f"Redis language cache set failed for {user_id}: {cache_err}")
                return normalized
    except Exception as e:
        logger.debug(f"Supabase auth language lookup failed for {user_id}: {e}")

    return "en"


@router.put("/{user_id}/profile", dependencies=[Depends(verify_user_csrf_token)])
async def update_profile(
    user_id: str,
    request: Request,
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
        # SPEC-054 additionally decodes and re-encodes: the long edge is capped
        # at avatar size, the file is compressed, a phone's HEIC is converted to
        # something browsers render, and the EXIF (GPS included) is dropped.
        # CPU-bound, so it goes through a thread like the upload below.
        contents, content_type, ext = await asyncio.to_thread(
            process_upload,
            contents,
            max_edge=MAX_AVATAR_EDGE,
            max_bytes=MAX_AVATAR_IMAGE_BYTES,
        )
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


# Long enough to outlive any access token the deleted user still holds (1 h,
# plus refresh skew); by then every other device's refresh has failed and its
# session is revoked.
_DELETED_ACCOUNT_BLOCK_SECONDS = 2 * 3600


def _purge_avatars(user_id: str) -> None:
    """Best-effort: uploaded avatars sit in a public bucket and are usually a face."""
    try:
        bucket = admin_supabase.storage.from_(STORAGE_BUCKET)
        prefix = f"avatars/{user_id}"
        names = [f"{prefix}/{obj['name']}" for obj in (bucket.list(prefix) or []) if obj.get("name")]
        if names:
            bucket.remove(names)
    except Exception as e:
        logger.warning(f"Avatar cleanup failed for deleted user {user_id}: {e}")


@router.delete("/{user_id}", dependencies=[Depends(verify_user_csrf_token)])
def delete_account(
    user_id: str,
    payload: AccountDeleteSchema,
    request: Request,
    response: Response,
    token_user_id: str = Depends(verify_user_token),
):
    """
    Permanently delete the authenticated user's account.

    Removes app-side data (profile, chat settings, conversations) and the
    Supabase auth user. Orders/transactions are intentionally retained as
    business records.

    SPEC-056 #7: costs the password too. This is irreversible and takes the
    transcript with it, so a lifted access token must not be enough on its own.
    """
    get_user_id_from_body_or_token(user_id, token_user_id)

    _reauthenticate(user_id, payload.current_password)

    # Best-effort cleanup, each domain erasing its own rows (don't abort the
    # delete if a table is empty). Identity announces the deletion rather than
    # naming who else holds this user's data (SPEC-097).
    bus.emit("user.deleted", user_id=user_id)
    IdentityService.purge_user_profile(user_id)

    # Delete the auth user (requires service role)
    try:
        admin_supabase.auth.admin.delete_user(user_id)
    except Exception as e:
        logger.error(f"Error deleting auth user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete account") from e

    # Audit PRV-3: end the session that made this request, and block the user
    # id everywhere else — a session on another device kept resolving until its
    # next token refresh failed, and could still write rows for a user that no
    # longer exists.
    clear_session_cookies(request, response)
    cache_ban_status(user_id, True, ttl=_DELETED_ACCOUNT_BLOCK_SECONDS)
    _purge_avatars(user_id)

    # Invalidate the cached token so the deleted session can't be reused
    auth_header = request.headers.get("Authorization", "")
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        invalidate_token(parts[1])

    return {"message": "Account deleted successfully"}
