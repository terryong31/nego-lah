import json
from unittest.mock import MagicMock

import pytest

from agent.memory import ConversationMemory, conversation_memory
from conftest import make_supabase_result


# ---------------------------------------------------------------------------
# Fixture: patch the lazily-loaded `_supabase` attribute directly, bypassing
# the `connector.admin_supabase` import path entirely (per file-specific
# notes). Each test gets a fresh MagicMock and the attribute is restored to
# None afterwards so other test modules that touch the same singleton aren't
# affected.
# ---------------------------------------------------------------------------
@pytest.fixture
def mem_supabase(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(conversation_memory, "_supabase", fake)
    return fake


def _select_eq_execute(fake):
    """Shortcut to the terminal .execute() mock for select().eq() chains."""
    return fake.table.return_value.select.return_value.eq.return_value.execute


def _update_eq_execute(fake):
    return fake.table.return_value.update.return_value.eq.return_value.execute


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
# add_message
# ---------------------------------------------------------------------------

def test_add_message_creates_new_conversation_when_none_exists(mem_supabase):
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([])

    conversation_memory.add_message("user-1", "human", "hello there", item_id="item-1", source="human")

    mem_supabase.table.assert_any_call("conversations")
    insert_call = mem_supabase.table.return_value.insert
    insert_call.assert_called_once()
    payload = insert_call.call_args[0][0]
    assert payload["user_id"] == "user-1"
    assert payload["item_id"] == "item-1"
    assert len(payload["messages"]) == 1
    new_msg = payload["messages"][0]
    assert new_msg["role"] == "human"
    assert new_msg["content"] == "hello there"
    assert new_msg["source"] == "human"
    assert new_msg["item_id"] == "item-1"
    assert "timestamp" in new_msg
    _insert_execute(mem_supabase).assert_called_once()


def test_add_message_appends_to_existing_conversation(mem_supabase):
    existing = {"id": "conv-1", "messages": [{"role": "human", "content": "hi", "source": "human"}]}
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([existing])

    conversation_memory.add_message("user-1", "ai", "how can I help?", source="ai")

    update_call = mem_supabase.table.return_value.update
    update_call.assert_called_once()
    payload = update_call.call_args[0][0]
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["content"] == "hi"
    assert payload["messages"][1]["content"] == "how can I help?"
    assert payload["updated_at"] == "now()"
    # .eq() should target the conversation's own id
    mem_supabase.table.return_value.update.return_value.eq.assert_called_once_with("id", "conv-1")
    _update_eq_execute(mem_supabase).assert_called_once()


def test_add_message_handles_existing_conversation_with_null_messages(mem_supabase):
    # messages column can be NULL in the DB -> `.get('messages', []) or []` guards it.
    existing = {"id": "conv-2", "messages": None}
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([existing])

    conversation_memory.add_message("user-2", "human", "first message")

    payload = mem_supabase.table.return_value.update.call_args[0][0]
    assert len(payload["messages"]) == 1


def test_add_message_converts_list_message_to_json_string(mem_supabase):
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([])

    list_message = [{"type": "text", "text": "part one"}, {"type": "text", "text": "part two"}]
    conversation_memory.add_message("user-3", "ai", list_message)

    payload = mem_supabase.table.return_value.insert.call_args[0][0]
    saved_content = payload["messages"][0]["content"]
    assert isinstance(saved_content, str)
    assert json.loads(saved_content) == list_message


def test_add_message_defaults_item_id_and_source(mem_supabase):
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([])

    conversation_memory.add_message("user-4", "system", "note")

    payload = mem_supabase.table.return_value.insert.call_args[0][0]
    new_msg = payload["messages"][0]
    assert new_msg["item_id"] is None
    assert new_msg["source"] == "ai"  # default source


def test_add_message_swallows_exception_and_logs(mem_supabase, monkeypatch):
    mem_supabase.table.side_effect = RuntimeError("supabase is down")
    logged = {}
    monkeypatch.setattr(
        "agent.memory.logger.info",
        lambda msg: logged.setdefault("msg", msg),
    )

    # Should not raise.
    conversation_memory.add_message("user-5", "human", "hello")

    assert "Error saving message" in logged["msg"]


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------

def test_get_history_returns_empty_list_when_no_conversation(mem_supabase):
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([])

    result = conversation_memory.get_history("user-1")

    assert result == []


def test_get_history_returns_mapped_messages_in_order(mem_supabase):
    stored = [
        {"role": "human", "content": "hi", "source": "human", "item_id": None, "timestamp": "t1"},
        {"role": "ai", "content": "hello!", "source": "ai", "item_id": None, "timestamp": "t2"},
    ]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result(
        [{"messages": stored}]
    )

    result = conversation_memory.get_history("user-1")

    assert result == [
        {"role": "human", "content": "hi", "source": "human"},
        {"role": "ai", "content": "hello!", "source": "ai"},
    ]


def test_get_history_defaults_source_when_missing(mem_supabase):
    stored = [{"role": "human", "content": "hi"}]  # no "source" key
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    result = conversation_memory.get_history("user-1")

    assert result == [{"role": "human", "content": "hi", "source": "ai"}]


def test_get_history_applies_limit_truncation(mem_supabase):
    stored = [{"role": "human", "content": str(i), "source": "human"} for i in range(5)]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    result = conversation_memory.get_history("user-1", limit=2)

    assert [m["content"] for m in result] == ["3", "4"]


def test_get_history_falsy_limit_skips_truncation(mem_supabase):
    # `if limit:` is falsy for 0 (and None), so no truncation is applied at all.
    stored = [{"role": "human", "content": str(i), "source": "human"} for i in range(5)]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    result = conversation_memory.get_history("user-1", limit=0)

    assert [m["content"] for m in result] == ["0", "1", "2", "3", "4"]


def test_get_history_applies_offset_from_end(mem_supabase):
    stored = [{"role": "human", "content": str(i), "source": "human"} for i in range(5)]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    # offset=2 drops the last 2 messages, then limit=50 (default) keeps the rest.
    result = conversation_memory.get_history("user-1", offset=2)

    assert [m["content"] for m in result] == ["0", "1", "2"]


def test_get_history_offset_larger_than_length_returns_empty(mem_supabase):
    stored = [{"role": "human", "content": "only-one", "source": "human"}]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    result = conversation_memory.get_history("user-1", offset=10)

    assert result == []


def test_get_history_handles_null_messages_column(mem_supabase):
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": None}])

    result = conversation_memory.get_history("user-1")

    assert result == []


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


# ---------------------------------------------------------------------------
# get_history_page
# ---------------------------------------------------------------------------

def test_get_history_page_returns_default_shape_when_no_conversation(mem_supabase):
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([])

    result = conversation_memory.get_history_page("user-1", limit=20, offset=5)

    assert result == {"messages": [], "has_more": False, "next_offset": 5}


def test_get_history_page_first_page_has_more_when_older_messages_remain(mem_supabase):
    stored = [{"role": "human", "content": str(i), "source": "human"} for i in range(10)]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    result = conversation_memory.get_history_page("user-1", limit=5, offset=0)

    assert [m["content"] for m in result["messages"]] == ["5", "6", "7", "8", "9"]
    assert result["has_more"] is True
    assert result["next_offset"] == 5


def test_get_history_page_last_page_has_no_more(mem_supabase):
    stored = [{"role": "human", "content": str(i), "source": "human"} for i in range(10)]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    result = conversation_memory.get_history_page("user-1", limit=5, offset=8)

    assert [m["content"] for m in result["messages"]] == ["0", "1"]
    assert result["has_more"] is False
    assert result["next_offset"] == 10


def test_get_history_page_limit_larger_than_total(mem_supabase):
    stored = [{"role": "human", "content": str(i), "source": "human"} for i in range(3)]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    result = conversation_memory.get_history_page("user-1", limit=20, offset=0)

    assert [m["content"] for m in result["messages"]] == ["0", "1", "2"]
    assert result["has_more"] is False
    assert result["next_offset"] == 3


def test_get_history_page_offset_beyond_total_returns_empty_page(mem_supabase):
    stored = [{"role": "human", "content": str(i), "source": "human"} for i in range(3)]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    result = conversation_memory.get_history_page("user-1", limit=5, offset=10)

    assert result["messages"] == []
    assert result["has_more"] is False
    assert result["next_offset"] == 10


def test_get_history_page_defaults_source_when_missing(mem_supabase):
    stored = [{"role": "human", "content": "hi"}]
    _select_eq_execute(mem_supabase).return_value = make_supabase_result([{"messages": stored}])

    result = conversation_memory.get_history_page("user-1", limit=5, offset=0)

    assert result["messages"] == [{"role": "human", "content": "hi", "source": "ai"}]


def test_get_history_page_swallows_exception_and_returns_default(mem_supabase, monkeypatch):
    mem_supabase.table.side_effect = RuntimeError("boom")
    logged = {}
    monkeypatch.setattr(
        "agent.memory.logger.info",
        lambda msg: logged.setdefault("msg", msg),
    )

    result = conversation_memory.get_history_page("user-1", limit=20, offset=7)

    assert result == {"messages": [], "has_more": False, "next_offset": 7}
    assert "Error getting history page" in logged["msg"]


# ---------------------------------------------------------------------------
# get_all_histories
# ---------------------------------------------------------------------------

def test_get_all_histories_groups_by_user_id(mem_supabase):
    rows = [
        {
            "user_id": "user-1",
            "messages": [{"role": "human", "content": "a", "source": "human"}],
        },
        {
            "user_id": "user-2",
            "messages": [{"role": "ai", "content": "b", "source": "ai"}],
        },
    ]
    mem_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result(rows)

    result = conversation_memory.get_all_histories()

    assert set(result.keys()) == {"user-1", "user-2"}
    assert result["user-1"] == [{"role": "human", "content": "a", "source": "human"}]
    assert result["user-2"] == [{"role": "ai", "content": "b", "source": "ai"}]


def test_get_all_histories_limits_to_last_50_messages(mem_supabase):
    stored = [{"role": "human", "content": str(i), "source": "human"} for i in range(60)]
    rows = [{"user_id": "user-1", "messages": stored}]
    mem_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result(rows)

    result = conversation_memory.get_all_histories()

    assert len(result["user-1"]) == 50
    assert result["user-1"][0]["content"] == "10"
    assert result["user-1"][-1]["content"] == "59"


def test_get_all_histories_returns_empty_dict_when_no_rows(mem_supabase):
    mem_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result([])

    result = conversation_memory.get_all_histories()

    assert result == {}


def test_get_all_histories_handles_null_messages(mem_supabase):
    rows = [{"user_id": "user-1", "messages": None}]
    mem_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result(rows)

    result = conversation_memory.get_all_histories()

    assert result == {"user-1": []}


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
    conversation_memory.clear_history("user-1")

    mem_supabase.table.assert_any_call("conversations")
    mem_supabase.table.return_value.delete.return_value.eq.assert_called_once_with("user_id", "user-1")
    _delete_eq_execute(mem_supabase).assert_called_once()


def test_clear_history_swallows_exception_and_logs(mem_supabase, monkeypatch):
    mem_supabase.table.side_effect = RuntimeError("boom")
    logged = {}
    monkeypatch.setattr(
        "agent.memory.logger.info",
        lambda msg: logged.setdefault("msg", msg),
    )

    # Should not raise.
    conversation_memory.clear_history("user-1")

    assert "Error clearing history" in logged["msg"]


# ---------------------------------------------------------------------------
# broadcast_message
# ---------------------------------------------------------------------------

def test_broadcast_message_is_a_noop():
    # Realtime broadcast is handled entirely by Supabase's own subscription
    # mechanism; this method intentionally does nothing and must never raise,
    # even with no Supabase mock configured at all.
    result = conversation_memory.broadcast_message("user-1", "human", "hi", "human")
    assert result is None
