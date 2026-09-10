"""Tests for `ConversationMemory`'s client wiring and failure behaviour.

The storage contract itself — appends never read, reads come back paged and in
order, concurrent writers can't clobber each other — lives in
`test_conversation_append_only.py`, which exercises it against a fake that
actually behaves like the table. This file covers the parts that are about the
object rather than the data: how it gets its Supabase client, and what it does
when that client fails.

Mocking note: `_supabase` is patched directly, bypassing the
`connector.admin_supabase` import path entirely. Each test gets a fresh
MagicMock and the attribute is restored afterwards so other modules touching
the same singleton aren't affected.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from agent.memory import ConversationMemory, conversation_memory
from conftest import make_supabase_result


@pytest.fixture
def mem_supabase(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(conversation_memory, "_supabase", fake)
    return fake


def _select_chain_execute(fake):
    """Terminal `.execute()` for `select().eq().order().range()`."""
    return (
        fake.table.return_value.select.return_value
        .eq.return_value.order.return_value.range.return_value.execute
    )


def _insert_execute(fake):
    return fake.table.return_value.insert.return_value.execute


def _delete_eq_execute(fake):
    return fake.table.return_value.delete.return_value.eq.return_value.execute


# ---------------------------------------------------------------------------
# Lazy `supabase` property
# ---------------------------------------------------------------------------

def test_supabase_property_lazy_loads_from_connector(monkeypatch):
    """When _supabase is None, the property should import connector.admin_supabase
    and cache it on self._supabase."""
    fresh = ConversationMemory()
    fake_admin = MagicMock(name="admin_supabase")
    monkeypatch.setattr("connector.admin_supabase", fake_admin, raising=False)

    assert fresh._supabase is None
    result = fresh.supabase
    assert result is fake_admin
    assert fresh._supabase is fake_admin

    # Second access returns the cached value without re-importing.
    monkeypatch.setattr("connector.admin_supabase", MagicMock(name="other"), raising=False)
    assert fresh.supabase is fake_admin


# ---------------------------------------------------------------------------
# Writes target the append-only table
# ---------------------------------------------------------------------------

def test_add_message_writes_to_the_messages_table(mem_supabase):
    _insert_execute(mem_supabase).return_value = make_supabase_result([])

    conversation_memory.add_message("user-1", "human", "hello", item_id="item-2", source="human")

    mem_supabase.table.assert_called_with("messages")
    payload = mem_supabase.table.return_value.insert.call_args[0][0]
    assert payload["user_id"] == "user-1"
    assert payload["role"] == "human"
    assert payload["content"] == "hello"
    assert payload["item_id"] == "item-2"
    assert payload["source"] == "human"
    assert payload["created_at"]


def test_add_message_writes_an_aware_utc_timestamp(mem_supabase):
    """SPEC-066. `created_at` is a `timestamptz`, and Postgres reads a naive
    literal as the *session's* zone — UTC on Supabase. A naive `datetime.now()`
    on a UTC+8 host therefore stored every message eight hours in the future,
    where no read watermark stamped at `now(UTC)` could ever get past it."""
    _insert_execute(mem_supabase).return_value = make_supabase_result([])

    conversation_memory.add_message("user-1", "ai", "sure")

    written = datetime.fromisoformat(
        mem_supabase.table.return_value.insert.call_args[0][0]["created_at"]
    )
    assert written.tzinfo is not None, "a naive literal means whatever the host's zone is"
    assert abs((written - datetime.now(UTC)).total_seconds()) < 5


def test_add_message_defaults_item_id_and_source(mem_supabase):
    _insert_execute(mem_supabase).return_value = make_supabase_result([])

    conversation_memory.add_message("user-1", "ai", "sure")

    payload = mem_supabase.table.return_value.insert.call_args[0][0]
    assert payload["item_id"] is None
    assert payload["source"] == "ai"


def test_add_message_swallows_exception_and_logs(mem_supabase, monkeypatch):
    """A failed save must not take the whole turn down with it — the buyer
    still gets their answer, and the loss is visible in the log."""
    mem_supabase.table.side_effect = RuntimeError("supabase is down")
    logged = {}
    monkeypatch.setattr(
        "agent.memory.logger.info",
        lambda msg: logged.setdefault("msg", msg),
    )

    conversation_memory.add_message("user-5", "human", "hello")

    assert "Error saving message" in logged["msg"]


# ---------------------------------------------------------------------------
# Reads fail soft
# ---------------------------------------------------------------------------

def test_get_history_returns_empty_list_when_nothing_stored(mem_supabase):
    _select_chain_execute(mem_supabase).return_value = make_supabase_result([])

    assert conversation_memory.get_history("user-1") == []


def test_get_history_handles_a_null_data_payload(mem_supabase):
    """PostgREST can answer with `data=None`; that's empty, not a crash."""
    _select_chain_execute(mem_supabase).return_value = make_supabase_result(None)

    assert conversation_memory.get_history("user-1") == []


def test_get_history_defaults_source_when_missing(mem_supabase):
    _select_chain_execute(mem_supabase).return_value = make_supabase_result(
        [{"role": "ai", "content": "hi"}]
    )

    assert conversation_memory.get_history("user-1") == [
        {"role": "ai", "content": "hi", "source": "ai"}
    ]


def test_get_history_swallows_exception_and_returns_empty_list(mem_supabase, monkeypatch):
    mem_supabase.table.side_effect = RuntimeError("boom")
    logged = {}
    monkeypatch.setattr(
        "agent.memory.logger.info",
        lambda msg: logged.setdefault("msg", msg),
    )

    result = conversation_memory.get_history("user-1")

    assert result == []
    assert "Error getting history" in logged["msg"]


def test_get_history_page_returns_default_shape_when_nothing_stored(mem_supabase):
    _select_chain_execute(mem_supabase).return_value = make_supabase_result([])

    assert conversation_memory.get_history_page("user-1") == {
        "messages": [], "has_more": False, "next_offset": 0
    }


def test_get_history_page_swallows_exception_and_keeps_the_offset(mem_supabase, monkeypatch):
    """The offset is echoed back unchanged so a retry resumes where the reader
    was, rather than silently jumping to the top of the conversation."""
    mem_supabase.table.side_effect = RuntimeError("boom")
    logged = {}
    monkeypatch.setattr(
        "agent.memory.logger.info",
        lambda msg: logged.setdefault("msg", msg),
    )

    result = conversation_memory.get_history_page("user-1", limit=20, offset=7)

    assert result == {"messages": [], "has_more": False, "next_offset": 7}
    assert "Error getting history page" in logged["msg"]


def test_get_all_histories_returns_empty_dict_when_no_rows(mem_supabase):
    (
        mem_supabase.table.return_value.select.return_value
        .order.return_value.execute
    ).return_value = make_supabase_result([])

    assert conversation_memory.get_all_histories() == {}


def test_get_all_histories_swallows_exception_and_returns_empty_dict(mem_supabase, monkeypatch):
    mem_supabase.table.side_effect = RuntimeError("boom")
    logged = {}
    monkeypatch.setattr(
        "agent.memory.logger.info",
        lambda msg: logged.setdefault("msg", msg),
    )

    result = conversation_memory.get_all_histories()

    assert result == {}
    assert "Error getting all histories" in logged["msg"]


# ---------------------------------------------------------------------------
# clear_history
# ---------------------------------------------------------------------------

def test_clear_history_deletes_by_user_id(mem_supabase):
    _delete_eq_execute(mem_supabase).return_value = make_supabase_result([])

    conversation_memory.clear_history("user-9")

    mem_supabase.table.assert_called_with("messages")
    mem_supabase.table.return_value.delete.return_value.eq.assert_called_with(
        "user_id", "user-9"
    )


def test_clear_history_swallows_exception_and_logs(mem_supabase, monkeypatch):
    mem_supabase.table.side_effect = RuntimeError("boom")
    logged = {}
    monkeypatch.setattr(
        "agent.memory.logger.info",
        lambda msg: logged.setdefault("msg", msg),
    )

    conversation_memory.clear_history("user-9")

    assert "Error clearing history" in logged["msg"]


def test_broadcast_message_is_a_noop():
    """Realtime delivery is handled elsewhere; this exists so callers that
    expect the hook don't have to care."""
    assert conversation_memory.broadcast_message("u", "ai", "hi", "ai") is None


# ---------------------------------------------------------------------------
# `read_watermark` — a mark that covers the transcript, not the clock
# ---------------------------------------------------------------------------

def _watermark(monkeypatch, newest):
    monkeypatch.setattr(conversation_memory, "newest_at", lambda *_a, **_k: newest)
    return datetime.fromisoformat(conversation_memory.read_watermark("user-1", "ai"))


def test_read_watermark_is_now_when_nothing_is_newer(monkeypatch):
    """The ordinary case, and the one anchoring must not disturb: stamping must
    never drag a watermark backwards to an old message."""
    old = (datetime.now(UTC) - timedelta(days=2)).isoformat()

    assert abs((_watermark(monkeypatch, old) - datetime.now(UTC)).total_seconds()) < 5


def test_read_watermark_covers_a_row_this_clock_has_not_reached(monkeypatch):
    """SPEC-066. The row was dated by whoever wrote it, and two clocks that both
    believe they are on UTC can still disagree. A mark that stops a second short
    of the newest message is a chip that comes back after being read."""
    just_ahead = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()

    assert _watermark(monkeypatch, just_ahead) == datetime.fromisoformat(just_ahead)


def test_read_watermark_falls_back_to_now_without_a_readable_row(monkeypatch):
    """`newest_at` fails soft, and so must this: a chip is not worth a 503."""
    assert abs((_watermark(monkeypatch, None) - datetime.now(UTC)).total_seconds()) < 5


# ---------------------------------------------------------------------------
# The future horizon — a mis-stamped row is history, not news (SPEC-066)
# ---------------------------------------------------------------------------

def _newest_at_chain(fake):
    return (
        fake.table.return_value.select.return_value
        .eq.return_value.eq.return_value.lte.return_value
        .order.return_value.limit.return_value.execute
    )


def _count_chain(fake):
    return (
        fake.table.return_value.select.return_value
        .eq.return_value.eq.return_value.lte.return_value
        .gt.return_value.limit.return_value.execute
    )


def _horizon_arg(lte_mock):
    column, value = lte_mock.call_args[0]
    assert column == "created_at"
    return datetime.fromisoformat(value)


def test_newest_at_will_not_believe_a_row_from_the_future(mem_supabase):
    """Rows written before the fix are dated by the API host's local clock in a
    UTC column — eight hours out on a UTC+8 box. Taking one for "the newest
    thing said" would drag the unread cutoff past every message that follows."""
    _newest_at_chain(mem_supabase).return_value = make_supabase_result(
        [{"created_at": "2026-09-10T10:00:00+00:00"}]
    )

    assert conversation_memory.newest_at("user-1", "human") == "2026-09-10T10:00:00+00:00"

    lte = mem_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.lte
    horizon = _horizon_arg(lte)
    assert datetime.now(UTC) < horizon <= datetime.now(UTC) + timedelta(minutes=2)


def test_count_since_will_not_count_a_row_from_the_future(mem_supabase):
    """The other half: those rows are the buyer's own read history, and counting
    them is a chip that cannot be cleared until the wall clock catches up."""
    _count_chain(mem_supabase).return_value = make_supabase_result([{"id": 1}], count=1)

    assert conversation_memory.count_since("user-1", "ai", "2026-09-10T09:00:00+00:00", 99) == 1

    lte = mem_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.lte
    assert _horizon_arg(lte) > datetime.now(UTC)
