"""Tests for agent/tools/items.py (get_item_info, search_items, list_all_items
langchain tools).

Unlike most of the codebase, `agent.tools.items` does NOT bind
`user_supabase` at module import time -- each tool function does
`from connector import user_supabase` *inside its own body*, freshly, on
every call. That means patching `agent.tools.items.user_supabase` would have
no effect (the name doesn't even exist in that module's namespace), while
patching `connector.user_supabase` directly *does* take effect, since the
lazy import re-resolves the current value of that name at call time. We use
`patch_supabase("connector", user=fake_supabase)` for exactly that reason.

We call `.func(...)` directly on the langchain `@tool`-wrapped
`StructuredTool` objects to invoke the underlying python function (skipping
the pydantic argument-schema wrapper), plus one `.invoke(...)` sanity check
per tool to confirm the public langchain entrypoint also works end-to-end.

`get_item_info` filters out soft-deleted items with `.is_('deleted_at',
'null')`, matching `search_items` and `list_all_items`, so the agent won't
answer questions about a removed item queried directly by ID.
"""

from agent.tools.items import get_item_info, list_all_items, search_items
from conftest import make_supabase_result


# ---------------------------------------------------------------------------
# Chain helpers -- each tool builds a different Supabase query chain, so the
# terminal `.execute` mock lives at a different attribute path for each.
# ---------------------------------------------------------------------------
def _get_item_info_chain(fake_supabase):
    """.table('items').select('*').eq('id', item_id).is_('deleted_at', 'null').execute()"""
    return fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value


def _search_items_chain(fake_supabase):
    """.table('items').select(...).is_('deleted_at', 'null').ilike('name', q).limit(5).execute()"""
    return (
        fake_supabase.table.return_value.select.return_value.is_.return_value
        .ilike.return_value.limit.return_value
    )


def _list_all_items_chain(fake_supabase):
    """.table('items').select(...).eq('status', 'available').is_('deleted_at', 'null').limit(10).execute()"""
    return (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .is_.return_value.limit.return_value
    )


# ---------------------------------------------------------------------------
# get_item_info
# ---------------------------------------------------------------------------
def test_get_item_info_is_langchain_tool_with_expected_name():
    assert get_item_info.name == "get_item_info"


def test_get_item_info_found_full_fields(fake_supabase, patch_supabase):
    item = {
        "id": "item-1",
        "name": "Vintage Lamp",
        "description": "A cozy vintage lamp",
        "price": 150,
        "condition": "used - good",
        "status": "available",
    }
    _get_item_info_chain(fake_supabase).execute.return_value = make_supabase_result([item])
    patch_supabase("connector", user=fake_supabase)

    result = get_item_info.func("item-1")

    assert "item_id: item-1" in result
    assert "Item: Vintage Lamp" in result
    assert "Description: A cozy vintage lamp" in result
    assert "Price: RM150" in result
    assert "Condition: used - good" in result
    assert "Status: available" in result


def test_get_item_info_missing_fields_use_defaults(fake_supabase, patch_supabase):
    item = {"id": "item-2"}
    _get_item_info_chain(fake_supabase).execute.return_value = make_supabase_result([item])
    patch_supabase("connector", user=fake_supabase)

    result = get_item_info.func("item-2")

    assert "item_id: item-2" in result
    assert "Item: Unknown" in result
    assert "Description: No description" in result
    assert "Price: RMN/A" in result
    assert "Condition: Unknown" in result
    assert "Status: available" in result


def test_get_item_info_not_found_empty_data(fake_supabase, patch_supabase):
    _get_item_info_chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("connector", user=fake_supabase)

    result = get_item_info.func("missing-item")

    assert result == "Item not found."


def test_get_item_info_not_found_none_data(fake_supabase, patch_supabase):
    _get_item_info_chain(fake_supabase).execute.return_value = make_supabase_result(None)
    patch_supabase("connector", user=fake_supabase)

    result = get_item_info.func("missing-item")

    assert result == "Item not found."


def test_get_item_info_filters_soft_deleted_items(fake_supabase, patch_supabase):
    """get_item_info applies `.is_('deleted_at', 'null')`, matching
    search_items/list_all_items, so a soft-deleted item is excluded. A real DB
    would return no row for a deleted id; here we assert the filter is present
    in the query chain."""
    _get_item_info_chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("connector", user=fake_supabase)

    result = get_item_info.func("item-3")

    assert result == "Item not found."
    # The soft-delete filter is applied on the .eq(...) result.
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.assert_called_with(
        "deleted_at", "null"
    )


def test_get_item_info_queries_expected_table_and_filters(fake_supabase, patch_supabase):
    _get_item_info_chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("connector", user=fake_supabase)

    get_item_info.func("item-42")

    fake_supabase.table.assert_called_with("items")
    fake_supabase.table.return_value.select.assert_called_with("*")
    fake_supabase.table.return_value.select.return_value.eq.assert_called_with("id", "item-42")
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.assert_called_with(
        "deleted_at", "null"
    )


def test_get_item_info_invoke_via_langchain_interface(fake_supabase, patch_supabase):
    item = {"id": "item-1", "name": "Chair", "price": 20}
    _get_item_info_chain(fake_supabase).execute.return_value = make_supabase_result([item])
    patch_supabase("connector", user=fake_supabase)

    result = get_item_info.invoke({"item_id": "item-1"})

    assert "Item: Chair" in result


# ---------------------------------------------------------------------------
# search_items
# ---------------------------------------------------------------------------
def test_search_items_is_langchain_tool_with_expected_name():
    assert search_items.name == "search_items"


def test_search_items_found_formats_list(fake_supabase, patch_supabase):
    items = [
        {"id": "i-1", "name": "Red Chair", "price": 50, "condition": "used", "status": "available"},
        {"id": "i-2", "name": "Red Chair XL", "price": 80, "condition": "new", "status": "sold"},
    ]
    _search_items_chain(fake_supabase).execute.return_value = make_supabase_result(items)
    patch_supabase("connector", user=fake_supabase)

    result = search_items.func("chair")

    lines = result.split("\n")
    assert len(lines) == 2
    assert lines[0] == "• ID: i-1 | Name: Red Chair | Price: RM50 | Status: available"
    assert lines[1] == "• ID: i-2 | Name: Red Chair XL | Price: RM80 | Status: sold"


def test_search_items_missing_status_defaults_to_available(fake_supabase, patch_supabase):
    items = [{"id": "i-3", "name": "Mystery Box", "price": 10, "condition": "new", "status": None}]
    _search_items_chain(fake_supabase).execute.return_value = make_supabase_result(items)
    patch_supabase("connector", user=fake_supabase)

    result = search_items.func("mystery")

    assert result == "• ID: i-3 | Name: Mystery Box | Price: RM10 | Status: available"


def test_search_items_no_matching_items_empty_data(fake_supabase, patch_supabase):
    _search_items_chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("connector", user=fake_supabase)

    result = search_items.func("nonexistent")

    assert result == "No matching items found."


def test_search_items_no_matching_items_none_data(fake_supabase, patch_supabase):
    _search_items_chain(fake_supabase).execute.return_value = make_supabase_result(None)
    patch_supabase("connector", user=fake_supabase)

    result = search_items.func("nonexistent")

    assert result == "No matching items found."


def test_search_items_query_uses_ilike_wildcard_and_deleted_filter(fake_supabase, patch_supabase):
    _search_items_chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("connector", user=fake_supabase)

    search_items.func("lamp")

    fake_supabase.table.assert_called_with("items")
    fake_supabase.table.return_value.select.assert_called_with(
        "id, name, price, condition, status"
    )
    fake_supabase.table.return_value.select.return_value.is_.assert_called_with(
        "deleted_at", "null"
    )
    fake_supabase.table.return_value.select.return_value.is_.return_value.ilike.assert_called_with(
        "name", "%lamp%"
    )
    (
        fake_supabase.table.return_value.select.return_value.is_.return_value
        .ilike.return_value.limit.assert_called_with(5)
    )


def test_search_items_invoke_via_langchain_interface(fake_supabase, patch_supabase):
    items = [{"id": "i-9", "name": "Sofa", "price": 200, "condition": "used", "status": "available"}]
    _search_items_chain(fake_supabase).execute.return_value = make_supabase_result(items)
    patch_supabase("connector", user=fake_supabase)

    result = search_items.invoke({"search_term": "sofa"})

    assert "Sofa" in result


# ---------------------------------------------------------------------------
# list_all_items
# ---------------------------------------------------------------------------
def test_list_all_items_is_langchain_tool_with_expected_name():
    assert list_all_items.name == "list_all_items"


def test_list_all_items_found_formats_list(fake_supabase, patch_supabase):
    items = [
        {"id": "a-1", "name": "Table", "price": 300},
        {"id": "a-2", "name": "Lamp", "price": 45},
    ]
    _list_all_items_chain(fake_supabase).execute.return_value = make_supabase_result(items)
    patch_supabase("connector", user=fake_supabase)

    result = list_all_items.func()

    lines = result.split("\n")
    assert lines[0] == "• ID: a-1 | Name: Table | Price: RM300"
    assert lines[1] == "• ID: a-2 | Name: Lamp | Price: RM45"


def test_list_all_items_no_items_found_empty_data(fake_supabase, patch_supabase):
    _list_all_items_chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("connector", user=fake_supabase)

    result = list_all_items.func()

    assert result == "No available items found."


def test_list_all_items_no_items_found_none_data(fake_supabase, patch_supabase):
    _list_all_items_chain(fake_supabase).execute.return_value = make_supabase_result(None)
    patch_supabase("connector", user=fake_supabase)

    result = list_all_items.func()

    assert result == "No available items found."


def test_list_all_items_query_filters_status_and_deleted_and_limit(fake_supabase, patch_supabase):
    _list_all_items_chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("connector", user=fake_supabase)

    list_all_items.func()

    fake_supabase.table.assert_called_with("items")
    fake_supabase.table.return_value.select.assert_called_with(
        "id, name, price, condition, status"
    )
    fake_supabase.table.return_value.select.return_value.eq.assert_called_with(
        "status", "available"
    )
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.assert_called_with(
        "deleted_at", "null"
    )
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .is_.return_value.limit.assert_called_with(10)
    )


def test_list_all_items_invoke_via_langchain_interface(fake_supabase, patch_supabase):
    items = [{"id": "a-5", "name": "Bookshelf", "price": 120}]
    _list_all_items_chain(fake_supabase).execute.return_value = make_supabase_result(items)
    patch_supabase("connector", user=fake_supabase)

    result = list_all_items.invoke({})

    assert "Bookshelf" in result
