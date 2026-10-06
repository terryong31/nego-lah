"""
Identity domain service (ADR-0002, SPEC-002).

What other domains may ask identity for. The auth dependencies themselves
(`verify_admin`, `verify_user_token`, …) are exported straight from the package
— they are FastAPI dependencies, not service calls.

There is deliberately no ban-check method here: `auth_middleware` owns that rule
with the Redis ban-status cache in front of it, and a second uncached copy would
be a fail-open auth primitive with two sources of truth.
"""

from __future__ import annotations

from typing import Any

from core.connector import admin_supabase
from core.logger import logger


class IdentityService:
    """Exported domain service for the Identity bounded context."""

    @staticmethod
    def resolve_avatar_url(*args, **kwargs) -> str | None:
        """
        Pick the avatar that represents a user. Auth metadata wins over the legacy
        `user_profiles` row — identity's rule, used by the negotiation console too.
        """
        from domains.identity.profiles import resolve_avatar_url

        return resolve_avatar_url(*args, **kwargs)

    @staticmethod
    def get_display_names(supabase_client: Any = None) -> dict[str, str]:
        """{user_id: display_name} for every profile that has one set."""
        client = supabase_client or admin_supabase
        try:
            rows = client.table("user_profiles").select("id, display_name").execute().data or []
        except Exception as e:
            logger.warning(f"Could not load display names: {e}")
            return {}
        return {r["id"]: r["display_name"] for r in rows if r.get("id") and r.get("display_name")}

    @staticmethod
    def get_display_profiles(supabase_client: Any = None) -> dict[str, dict]:
        """{user_id: {display_name, avatar_url}} for rendering a person."""
        client = supabase_client or admin_supabase
        try:
            rows = client.table("user_profiles").select("id, display_name, avatar_url").execute().data or []
        except Exception as e:
            logger.warning(f"Could not load display profiles: {e}")
            return {}
        return {r["id"]: r for r in rows if r.get("id")}

    @staticmethod
    def purge_user_profile(user_id: str, supabase_client: Any = None) -> None:
        """Erase a user's profile row — account deletion."""
        client = supabase_client or admin_supabase
        try:
            client.table("user_profiles").delete().eq("id", user_id).execute()
        except Exception as e:
            logger.warning(f"Could not clean up user_profiles for {user_id}: {e}")

    # GoTrue's admin endpoint returns 50 users per page unless told otherwise,
    # so an unpaged `list_users()` silently stopped at 50 accounts (audit SCL-2).
    USERS_PAGE_SIZE = 1000

    @staticmethod
    def list_all_users(supabase_client: Any = None) -> list:
        """Every auth user, across as many pages as it takes."""
        client = supabase_client or admin_supabase
        users: list = []
        page = 1
        while True:
            batch = list(client.auth.admin.list_users(page=page, per_page=IdentityService.USERS_PAGE_SIZE) or [])
            users.extend(batch)
            if len(batch) < IdentityService.USERS_PAGE_SIZE:
                return users
            page += 1

    @staticmethod
    def count_users() -> int:
        """Registered accounts, for the admin summary."""
        try:
            return len(IdentityService.list_all_users())
        except Exception as e:
            logger.error(f"summary: list_users failed: {e}")
            return 0


__all__ = ["IdentityService"]
