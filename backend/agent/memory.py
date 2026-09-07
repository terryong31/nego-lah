"""
Conversation Memory - Supabase-backed, append-only.

Table structure (messages), one row per message:
- id: bigint identity (also the chronological order — see below)
- user_id: uuid
- item_id: uuid | null (the listing being discussed, if any)
- role: text ('human', 'ai', 'system', 'admin')
- content: text
- source: text ('ai' | 'admin' | 'system' | 'human')
- created_at: timestamptz

SPEC-043 replaced the previous shape — one `conversations` row per user
holding the whole transcript as a jsonb array — because appending to it meant
reading the entire array, appending in Python and writing all of it back.
That made the cost of every message grow with the conversation, and being a
read-then-write it could silently lose a message when two writers (the AI's
reply and an admin typing from the console) landed together.

Ordering is by `id`, not `created_at`: it's the insertion sequence, so it's
stable and unique, while two messages written in the same millisecond share a
timestamp and would page inconsistently.
"""

import json
from datetime import datetime

from logger import logger

# Sent to the agent as context, and the default page for the admin console.
DEFAULT_HISTORY_LIMIT = 50


class ConversationMemory:
    """Supabase-based conversation memory for storing chat history."""

    def __init__(self):
        self._supabase = None

    @property
    def supabase(self):
        """Lazy load Supabase client."""
        if self._supabase is None:
            from connector import admin_supabase
            self._supabase = admin_supabase
        return self._supabase

    @staticmethod
    def _to_public(row: dict) -> dict:
        """The shape every caller has always received."""
        return {
            "role": row.get("role"),
            "content": row.get("content"),
            "source": row.get("source", "ai"),
        }

    def add_message(
        self,
        user_id: str,
        role: str,
        message: str,
        item_id: str = None,
        source: str = 'ai'
    ):
        """Append a message to a user's history.

        Args:
            user_id: User identifier
            role: 'human', 'ai', 'system', 'admin'
            message: The message content
            item_id: Optional item context
            source: 'ai' | 'admin' | 'system' | 'human'
        """
        # Multimodal turns arrive as a list of content parts; the column is text.
        if isinstance(message, list):
            message = json.dumps(message)

        try:
            self.supabase.table('messages').insert({
                'user_id': user_id,
                'item_id': item_id,
                'role': role,
                'content': message,
                'source': source,
                'created_at': datetime.now().isoformat(),
            }).execute()
        except Exception as e:
            logger.info(f"[ConversationMemory] Error saving message: {e}")

    def _page(self, user_id: str, limit: int, offset: int) -> list[dict]:
        """One page of a user's messages, newest-anchored, returned oldest-first.

        Reads descending so `offset` counts back from the newest message (which
        is how both callers page), then reverses so the caller gets the natural
        reading order.
        """
        query = (
            self.supabase.table('messages')
            .select('role, content, source')
            .eq('user_id', user_id)
            .order('id', desc=True)
        )
        if limit:
            query = query.range(offset, offset + limit - 1)
        elif offset:
            # No limit but a non-zero offset: everything older than `offset`.
            query = query.range(offset, offset + 10_000)

        rows = query.execute().data or []
        return [self._to_public(r) for r in reversed(rows)]

    def get_history(self, user_id: str, limit: int = DEFAULT_HISTORY_LIMIT, offset: int = 0) -> list[dict]:
        """Get conversation history for a user, oldest-first."""
        try:
            return self._page(user_id, limit, offset)
        except Exception as e:
            logger.info(f"[ConversationMemory] Error getting history: {e}")
            return []

    def get_history_page(self, user_id: str, limit: int = 20, offset: int = 0) -> dict:
        """Get a page of conversation history, newest-anchored.

        `offset` counts messages back from the most recent one; `limit` is the
        page size. Returns messages in chronological order plus paging metadata
        so the client can lazily load older messages.

        Returns: {"messages": [...], "has_more": bool, "next_offset": int}
        """
        try:
            # One extra row is the cheapest way to answer "is there more?" —
            # cheaper than a COUNT over the whole conversation.
            rows = self._page(user_id, limit + 1, offset)
            has_more = len(rows) > limit
            page = rows[1:] if has_more else rows

            return {
                "messages": page,
                "has_more": has_more,
                "next_offset": offset + len(page),
            }
        except Exception as e:
            logger.info(f"[ConversationMemory] Error getting history page: {e}")
            return {"messages": [], "has_more": False, "next_offset": offset}

    def get_all_histories(self) -> dict[str, list[dict]]:
        """Get all conversation histories grouped by user_id (admin console)."""
        try:
            result = (
                self.supabase.table('messages')
                .select('user_id, role, content, source')
                .order('id', desc=False)
                .execute()
            )

            all_histories: dict[str, list[dict]] = {}
            for row in result.data or []:
                user_id = row.get('user_id')
                all_histories.setdefault(user_id, []).append(self._to_public(row))

            # Last 50 per user, matching what the console has always shown.
            return {
                user_id: messages[-DEFAULT_HISTORY_LIMIT:]
                for user_id, messages in all_histories.items()
            }
        except Exception as e:
            logger.info(f"[ConversationMemory] Error getting all histories: {e}")
            return {}

    def clear_history(self, user_id: str):
        """Clear conversation history for a user."""
        try:
            self.supabase.table('messages').delete().eq('user_id', user_id).execute()
        except Exception as e:
            logger.info(f"[ConversationMemory] Error clearing history: {e}")

    def broadcast_message(self, user_id: str, role: str, message: str, source: str):
        """Broadcast is handled by Supabase Realtime automatically."""
        pass  # Frontend subscribes to DB changes via Supabase Realtime


# Singleton instance
conversation_memory = ConversationMemory()
