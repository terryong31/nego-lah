"""
Negotiation domain service (ADR-0002, SPEC-002).

What other domains may ask the negotiation context for: a user's AI settings,
their conversation data, and the listing-authoring aids the catalogue console
uses. `agent.bot` itself is reached through the package's lazy `chat` /
`chat_stream` exports.

Every import of the agent stack is deferred into the method body on purpose:
importing `bot` pulls LangChain/LangGraph (+430 ms, +70 MB RSS per worker), and
this module is reachable from the admin console, which never runs a turn.
"""

from __future__ import annotations

from typing import Any

from core.connector import admin_supabase
from core.logger import logger
from core.pagination import fetch_all


def _delete_by_user(query: Any, table: str, user_id: str) -> None:
    """Delete a user's rows from one already-selected table, best effort."""
    try:
        query.delete().eq("user_id", user_id).execute()
    except Exception as e:
        logger.warning(f"Could not clean up {table} for {user_id}: {e}")


class NegotiationService:
    """Exported domain service for the Negotiation bounded context."""

    # --- per-user AI settings (`chat_settings` is negotiation's table) ------

    @staticmethod
    def get_ai_settings_map(supabase_client: Any = None) -> dict[str, dict]:
        """{user_id: settings_row} for every user, for the admin user list."""
        client = supabase_client or admin_supabase
        try:
            rows = client.table("chat_settings").select("*").execute().data or []
        except Exception as e:
            logger.warning(f"Could not load chat settings: {e}")
            return {}
        return {row["user_id"]: row for row in rows if row.get("user_id")}

    @staticmethod
    def is_ai_enabled(user_id: str, supabase_client: Any = None) -> bool:
        """Whether the agent answers for this user. Defaults to True."""
        client = supabase_client or admin_supabase
        try:
            res = client.table("chat_settings").select("ai_enabled").eq("user_id", user_id).execute()
            if res.data:
                return bool(res.data[0].get("ai_enabled", True))
        except Exception as e:
            logger.warning(f"Could not read ai_enabled for {user_id}: {e}")
        return True

    @staticmethod
    def set_ai_enabled(user_id: str, enabled: bool, supabase_client: Any = None) -> None:
        """Enable/disable the agent for a user; disabling marks an admin as intervening."""
        client = supabase_client or admin_supabase
        client.table("chat_settings").upsert(
            {
                "user_id": user_id,
                "ai_enabled": enabled,
                "admin_intervening": not enabled,
                "updated_at": "now()",
            }
        ).execute()

    # --- conversation data -------------------------------------------------

    @staticmethod
    def clear_user_conversation(user_id: str) -> None:
        """Drop a user's in-memory conversation (admin intervention, AI toggle)."""
        from domains.negotiation.memory import conversation_memory

        conversation_memory.clear(user_id)

    @staticmethod
    def add_agent_message(user_id: str, content: str, source: str = "ai", **kwargs) -> None:
        """Append a message to a user's conversation in the assistant's voice."""
        from domains.negotiation.memory import conversation_memory

        conversation_memory.add_message(user_id, "ai", content, source=source, **kwargs)

    @staticmethod
    def add_system_message(user_id: str, content: str) -> None:
        """Append a system notice (admin joined/left the chat) to a conversation."""
        from domains.negotiation.memory import conversation_memory

        conversation_memory.add_message(user_id, "system", content, source="system")

    @staticmethod
    def purge_user_data(user_id: str, supabase_client: Any = None) -> None:
        """Erase a user's negotiation footprint — account deletion (identity domain).

        The two tables are spelled out rather than looped over: the boundary
        scanner decides table ownership by reading the name at rest, and a name
        that only exists at runtime is invisible to it (SPEC-095). Each delete is
        independent — one failing must not strand the other, because a partial
        purge that reports success is worse than a loud one.
        """
        client = supabase_client or admin_supabase
        _delete_by_user(client.table("chat_settings"), "chat_settings", user_id)
        _delete_by_user(client.table("messages"), "messages", user_id)

    # --- aggregates (admin dashboard) --------------------------------------

    @staticmethod
    def count_conversations(supabase_client: Any = None) -> int:
        """
        Distinct people who have said something. SPEC-043 made history one row
        per message, so a conversation is a distinct `user_id`, which is what the
        old one-row-per-user table happened to count.
        """
        client = supabase_client or admin_supabase
        try:
            # The inbox function is already one row per conversation; reading
            # `messages` here was capped at its first 1,000 rows (audit SCL-2).
            rows = fetch_all(lambda: client.rpc("admin_chat_inbox", {}).order("user_id"))
        except Exception:
            return 0
        return len({row.get("user_id") for row in rows if row.get("user_id")})


__all__ = ["NegotiationService"]
