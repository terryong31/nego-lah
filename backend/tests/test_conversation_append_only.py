"""SPEC-043 Workstream B — conversation history is append-only.

The old `ConversationMemory` kept one jsonb array per user and rewrote all of
it on every message. Two consequences, one obvious and one not:

  * Saying "ok" cost as much as the entire transcript that came before it, and
    that cost grew for the whole life of a negotiation.
  * It was a read-then-write with no atomicity. Two writers landing together —
    the AI's reply and an admin typing from the console — each built their new
    array from the same earlier read, so whichever wrote second silently
    dropped the other's message. No error, no log, just a missing line.

The second one is a correctness bug, so it gets a test that would have caught
it (`test_concurrent_writes_do_not_lose_a_message`). The public interface is
unchanged on purpose: ~15 call sites across the agent, routes and fulfilment
keep working untouched.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory import ConversationMemory  # noqa: E402


class FakeMessagesTable:
    """A stand-in for the `messages` table that behaves like an append-only
    log: inserts accumulate, and selects are ordered pages over them.

    Deliberately not a MagicMock — the whole point of this workstream is *how*
    writes reach the database, and a chainable mock would happily record a
    read-modify-write as readily as an append.
    """

    def __init__(self):
        self.rows: list[dict] = []
        self.insert_calls = 0
        self.select_calls = 0
        self._next_id = 1

    # -- query builder -----------------------------------------------------
    def select(self, _columns="*", **_kwargs):
        self.select_calls += 1
        return _Query(self, list(self.rows))

    def insert(self, payload):
        self.insert_calls += 1
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            stored = dict(row)
            stored.setdefault("id", self._next_id)
            self._next_id += 1
            self.rows.append(stored)
        return _Terminal([dict(r) for r in rows])

    def delete(self):
        return _Delete(self)

    def update(self, _payload):  # pragma: no cover - must never be reached
        raise AssertionError(
            "history is append-only: an UPDATE means the old rewrite crept back"
        )


class _Query:
    def __init__(self, table, rows):
        self.table = table
        self.rows = rows
        self._desc = False

    def eq(self, column, value):
        self.rows = [r for r in self.rows if r.get(column) == value]
        return self

    def order(self, column, desc=False, **_kwargs):
        self._desc = desc
        self.rows = sorted(self.rows, key=lambda r: r.get(column, 0), reverse=desc)
        return self

    def range(self, start, end):
        self.rows = self.rows[start:end + 1]
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def execute(self):
        return _Result([dict(r) for r in self.rows])


class _Delete:
    def __init__(self, table):
        self.table = table
        self._filters = []

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def execute(self):
        kept = [
            r for r in self.table.rows
            if not all(r.get(c) == v for c, v in self._filters)
        ]
        removed = len(self.table.rows) - len(kept)
        self.table.rows[:] = kept
        return _Result([{"removed": removed}])


class _Result:
    def __init__(self, data):
        self.data = data


class _Terminal:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return _Result(self.data)


@pytest.fixture
def messages_table():
    return FakeMessagesTable()


@pytest.fixture
def memory(messages_table):
    client = MagicMock()

    def _table(name):
        if name != "messages":
            raise AssertionError(f"unexpected table {name!r}")
        return messages_table

    client.table.side_effect = _table

    mem = ConversationMemory()
    mem._supabase = client
    return mem


# ---------------------------------------------------------------------------
# B1 — a write is an append, not a rewrite
# ---------------------------------------------------------------------------

def test_add_message_inserts_once_and_reads_nothing(memory, messages_table):
    memory.add_message("user-1", "human", "is 800 ok?", item_id=None, source="human")

    assert messages_table.insert_calls == 1
    assert messages_table.select_calls == 0, (
        "a write that reads first is the read-modify-write this spec removes"
    )


def test_write_cost_does_not_grow_with_history_length(memory, messages_table):
    """The old design read and rewrote the whole transcript every time, so the
    200th message was far more expensive than the first. Appends are flat."""
    for i in range(200):
        memory.add_message("user-1", "human", f"message {i}", source="human")

    calls_for_200 = messages_table.insert_calls
    reads = messages_table.select_calls

    assert calls_for_200 == 200
    assert reads == 0
    assert len(messages_table.rows) == 200


def test_stored_row_carries_the_full_shape(memory, messages_table):
    memory.add_message("user-1", "ai", "how about 850?", item_id="item-9", source="ai")

    row = messages_table.rows[0]
    assert row["user_id"] == "user-1"
    assert row["role"] == "ai"
    assert row["content"] == "how about 850?"
    assert row["source"] == "ai"
    assert row["item_id"] == "item-9"


def test_list_content_is_serialised_like_before(memory, messages_table):
    """Multimodal turns arrive as a list of parts; the column is text."""
    memory.add_message("user-1", "human", [{"type": "text", "text": "hi"}])

    assert isinstance(messages_table.rows[0]["content"], str)
    assert "hi" in messages_table.rows[0]["content"]


# ---------------------------------------------------------------------------
# B2 — the lost-update bug is gone
# ---------------------------------------------------------------------------

def test_concurrent_writes_do_not_lose_a_message(memory, messages_table):
    """The bug this workstream exists to kill.

    Under the old design both writers read the same array, appended their own
    message to their own copy, and wrote it back — so the second write erased
    the first message. Two appends cannot do that to each other.
    """
    memory.add_message("user-1", "ai", "AI reply", source="ai")
    memory.add_message("user-1", "admin", "Terry stepping in", source="admin")

    contents = [r["content"] for r in messages_table.rows]
    assert contents == ["AI reply", "Terry stepping in"]

    history = memory.get_history("user-1")
    assert [m["content"] for m in history] == ["AI reply", "Terry stepping in"]


# ---------------------------------------------------------------------------
# Reads: same contracts as before, now served by an indexed page
# ---------------------------------------------------------------------------

def test_get_history_returns_chronological_order(memory):
    for text in ["first", "second", "third"]:
        memory.add_message("user-1", "human", text, source="human")

    history = memory.get_history("user-1")

    assert [m["content"] for m in history] == ["first", "second", "third"]
    assert history[0]["role"] == "human"
    assert history[0]["source"] == "human"


def test_get_history_limit_keeps_the_most_recent(memory):
    for i in range(10):
        memory.add_message("user-1", "human", f"m{i}", source="human")

    history = memory.get_history("user-1", limit=3)

    assert [m["content"] for m in history] == ["m7", "m8", "m9"]


def test_get_history_only_returns_that_users_messages(memory):
    memory.add_message("user-1", "human", "mine", source="human")
    memory.add_message("user-2", "human", "theirs", source="human")

    assert [m["content"] for m in memory.get_history("user-1")] == ["mine"]


def test_get_history_page_walks_backwards_through_the_transcript(memory):
    for i in range(5):
        memory.add_message("user-1", "human", f"m{i}", source="human")

    newest = memory.get_history_page("user-1", limit=2, offset=0)
    assert [m["content"] for m in newest["messages"]] == ["m3", "m4"]
    assert newest["has_more"] is True
    assert newest["next_offset"] == 2

    older = memory.get_history_page("user-1", limit=2, offset=newest["next_offset"])
    assert [m["content"] for m in older["messages"]] == ["m1", "m2"]
    assert older["has_more"] is True

    oldest = memory.get_history_page("user-1", limit=2, offset=older["next_offset"])
    assert [m["content"] for m in oldest["messages"]] == ["m0"]
    assert oldest["has_more"] is False


def test_get_history_page_on_an_empty_conversation(memory):
    page = memory.get_history_page("nobody", limit=20, offset=0)

    assert page == {"messages": [], "has_more": False, "next_offset": 0}


def test_clear_history_removes_only_that_user(memory, messages_table):
    memory.add_message("user-1", "human", "mine", source="human")
    memory.add_message("user-2", "human", "theirs", source="human")

    memory.clear_history("user-1")

    assert [r["content"] for r in messages_table.rows] == ["theirs"]


def test_get_all_histories_groups_by_user(memory):
    memory.add_message("user-1", "human", "a", source="human")
    memory.add_message("user-2", "human", "b", source="human")
    memory.add_message("user-1", "ai", "c", source="ai")

    histories = memory.get_all_histories()

    assert [m["content"] for m in histories["user-1"]] == ["a", "c"]
    assert [m["content"] for m in histories["user-2"]] == ["b"]


def test_reads_degrade_to_empty_rather_than_raising(monkeypatch):
    """A chat page that 500s because history is unavailable is worse than one
    that opens empty — the buyer can still send a message."""
    mem = ConversationMemory()
    broken = MagicMock()
    broken.table.side_effect = RuntimeError("supabase down")
    mem._supabase = broken

    assert mem.get_history("user-1") == []
    assert mem.get_history_page("user-1") == {
        "messages": [], "has_more": False, "next_offset": 0
    }
    assert mem.get_all_histories() == {}
