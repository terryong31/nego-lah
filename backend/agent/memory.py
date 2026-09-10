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
from datetime import UTC, datetime, timedelta

from logger import logger

# Sent to the agent as context, and the default page for the admin console.
DEFAULT_HISTORY_LIMIT = 50

# How far ahead of this process's clock a row may be dated and still be taken
# for a real message. Two clocks that both think they are on UTC can disagree by
# a second or two; nothing legitimate is a minute ahead.
#
# Past that horizon a row has not "just arrived", it is mis-stamped — every
# message written before SPEC-066 carries the API host's local time in a UTC
# column, so on a UTC+8 host it is filed eight hours in the future. Those rows
# are history the buyer has already read, and counting them as unread is a chip
# that cannot be cleared until the wall clock catches up. Unread state therefore
# reads nothing beyond the horizon: not news, not a notification.
MESSAGE_FUTURE_GRACE = timedelta(minutes=1)


def _horizon() -> str:
    """The newest `created_at` unread state will believe."""
    return (datetime.now(UTC) + MESSAGE_FUTURE_GRACE).isoformat()


def _as_utc(ts: str | None) -> datetime | None:
    """Parse a stored timestamp, or None if it isn't one.

    A value with no offset is read as UTC — that is how Postgres read it on the
    way in, so it is the only interpretation that round-trips.
    """
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
                # Aware, always (SPEC-066). The column is `timestamptz`, and
                # Postgres reads a naive literal as the *session's* zone — UTC
                # on Supabase — so a bare `datetime.now()` on a UTC+8 host
                # filed every message eight hours into the future, where no
                # read watermark could get past it.
                'created_at': datetime.now(UTC).isoformat(),
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

    def newest_at(self, user_id: str, role: str) -> str | None:
        """When this user's newest `role` message was written, or None.

        SPEC-061 needs two of these: the buyer's own last message (proof they
        were present) and, through `count_since`, everything the seller side
        has said after it.

        Rows dated past the horizon are skipped (SPEC-066) — a message from the
        future is a mis-stamped one, and taking it for the newest thing said
        would push the cutoff hours ahead of every message that follows it.
        """
        try:
            result = (
                self.supabase.table('messages')
                .select('created_at')
                .eq('user_id', user_id)
                .eq('role', role)
                .lte('created_at', _horizon())
                .order('created_at', desc=True)
                .limit(1)
                .execute()
            )
            rows = result.data or []
            return rows[0].get('created_at') if rows else None
        except Exception as e:
            logger.info(f"[ConversationMemory] Error reading newest {role} message: {e}")
            return None

    def read_watermark(self, user_id: str, role: str) -> str:
        """An instant that marks every `role` message written so far as read.

        Normally just now — but `now` is this process's opinion, and the row it
        has to cover was dated by whoever wrote it. Two clocks a second apart
        are enough to leave the newest message sitting just past a watermark
        that was supposed to include it, and a chip that comes back after being
        read is precisely the bug this is here to prevent. So the mark covers
        the newest message it claims to have read, which is a fact about the
        transcript rather than about either clock.

        The reach is bounded by `newest_at`'s horizon: a mis-stamped row hours
        ahead is not something this will follow, because it is not something
        unread state believes in at all.

        `role` is whatever that side of the conversation actually counts as
        unread: 'ai' for the buyer's badge, 'human' for the console's dot.
        """
        now = datetime.now(UTC)
        newest = _as_utc(self.newest_at(user_id, role))
        return (newest if newest and newest > now else now).isoformat()

    def count_since(self, user_id: str, role: str, after: str | None, cap: int) -> int:
        """How many `role` messages this user has after `after`, at most `cap`.

        `after=None` means "all of them" — a conversation with no watermark and
        no message from the buyer. `select('id', count='exact')` asks Postgres
        for the count and brings back at most `cap` ids, so a long-neglected
        thread costs a count, not a transcript.

        Bounded at both ends: rows past the horizon are not news (SPEC-066).
        """
        try:
            query = (
                self.supabase.table('messages')
                .select('id', count='exact')
                .eq('user_id', user_id)
                .eq('role', role)
                .lte('created_at', _horizon())
            )
            if after:
                query = query.gt('created_at', after)
            result = query.limit(cap).execute()
            return min(int(result.count or 0), cap)
        except Exception as e:
            logger.info(f"[ConversationMemory] Error counting {role} messages: {e}")
            return 0

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
