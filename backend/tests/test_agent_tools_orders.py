"""Tests for agent/tools/orders.py (check_user_orders langchain tool).

`agent.tools.orders` does `from connector import admin_supabase` at import
time, so we must patch `agent.tools.orders.admin_supabase` (via the
`patch_supabase` fixture) rather than `connector.admin_supabase`.

`check_user_orders` reads the current user id from the request-scoped
`agent.context` ContextVar (via `get_user_id()`), so each test that wants a
particular user id must call `agent.context.set_context(user_id=...)` first.

Note: `check_user_orders` is a langchain `@tool`-decorated `StructuredTool`.
We call `.func(...)` directly to invoke the underlying python function --
this exercises identical code to `.invoke(...)` but skips the pydantic
argument-schema wrapper, which is irrelevant to what we're testing here.
"""

from agent import context
from agent.tools.orders import check_user_orders
from conftest import make_supabase_result


def _invoke(query=""):
    return check_user_orders.func(query)


def _chain(fake_supabase):
    """Return the terminal mock in the orders query chain
    (`.table('orders').select('*').eq('buyer_id', uid).order('created_at', desc=True)`)."""
    return (
        fake_supabase.table.return_value.select.return_value.eq.return_value.order.return_value
    )


def test_is_langchain_tool_with_expected_name():
    assert check_user_orders.name == "check_user_orders"


def test_no_user_id_returns_system_error():
    context.set_context(user_id=None)

    result = _invoke()

    assert result == "System Error: I cannot identify your user account at the moment."


def test_no_orders_found_returns_friendly_message(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    _chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert result == "Records show you haven't purchased any items from our store yet."


def test_queries_orders_table_scoped_to_current_user(fake_supabase, patch_supabase):
    context.set_context(user_id="user-42")
    _chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    _invoke()

    fake_supabase.table.assert_called_with("orders")
    fake_supabase.table.return_value.select.assert_called_with("*")
    fake_supabase.table.return_value.select.return_value.eq.assert_called_with(
        "buyer_id", "user-42"
    )
    fake_supabase.table.return_value.select.return_value.eq.return_value.order.assert_called_with(
        "created_at", desc=True
    )


def test_pending_info_order_includes_shipping_hint(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    order = {
        "id": "ord-1",
        "status": "pending_info",
        "item_name": "Vintage Lamp",
        "amount": 150,
        "created_at": "2026-01-15T10:30:00",
    }
    _chain(fake_supabase).execute.return_value = make_supabase_result([order])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert "Found the following orders for you:" in result
    assert "[Date: 2026-01-15] Vintage Lamp (RM 150) | Status: PENDING_INFO | Order ID: ord-1" in result
    assert "ACTION REQUIRED" in result
    assert "shipping details" in result
    assert "Name, Address, and Phone Number" in result
    # This line was a plain string literal missing its `f` prefix, so the model
    # was handed the characters "{order['id']}" and would repeat them to the
    # buyer as if they were an order number. Fixed with SPEC-057.
    assert "(Use Order ID: ord-1 for updates)" in result
    assert "{order[" not in result


def test_confirmed_order_shows_processing_note(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    order = {
        "id": "ord-2",
        "status": "confirmed",
        "item_name": "Desk Chair",
        "amount": 300,
        "created_at": "2026-02-01T00:00:00",
    }
    _chain(fake_supabase).execute.return_value = make_supabase_result([order])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert "Status: CONFIRMED" in result
    assert "Info received. We are processing it." in result
    assert "ACTION REQUIRED" not in result
    assert "Shipped." not in result


def test_shipped_order_shows_shipped_note(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    order = {
        "id": "ord-3",
        "status": "shipped",
        "item_name": "Bookshelf",
        "amount": 220,
        "created_at": "2026-03-05T00:00:00",
    }
    _chain(fake_supabase).execute.return_value = make_supabase_result([order])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert "Status: SHIPPED" in result
    assert "Shipped." in result
    assert "ACTION REQUIRED" not in result
    assert "processing it" not in result


def test_other_status_has_no_extra_note(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    order = {
        "id": "ord-4",
        "status": "cancelled",
        "item_name": "Old Sofa",
        "amount": 0,
        "created_at": "2026-04-10T00:00:00",
    }
    _chain(fake_supabase).execute.return_value = make_supabase_result([order])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    line = [ln for ln in result.split("\n") if "Old Sofa" in ln][0]
    assert line == "- [Date: 2026-04-10] Old Sofa (RM 0) | Status: CANCELLED | Order ID: ord-4"
    assert "ACTION REQUIRED" not in result
    assert "processing it" not in result
    assert "Shipped." not in result


def test_missing_optional_fields_fall_back_to_defaults(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    # `status` and `item_name` default via .get(...); `created_at` defaults to
    # "" via .get('created_at', '') and is then sliced with [:10].
    order = {"id": "ord-5"}
    _chain(fake_supabase).execute.return_value = make_supabase_result([order])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert "[Date: ] Unknown Item (RM 0) | Status: UNKNOWN | Order ID: ord-5" in result


def test_multiple_orders_are_all_listed(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    orders = [
        {
            "id": "ord-a",
            "status": "shipped",
            "item_name": "Item A",
            "amount": 10,
            "created_at": "2026-01-01T00:00:00",
        },
        {
            "id": "ord-b",
            "status": "pending_info",
            "item_name": "Item B",
            "amount": 20,
            "created_at": "2026-01-02T00:00:00",
        },
    ]
    _chain(fake_supabase).execute.return_value = make_supabase_result(orders)
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert "Item A" in result
    assert "Item B" in result
    assert "Order ID: ord-a" in result
    assert "Order ID: ord-b" in result
    # 3, not 2: Item B is pending_info, whose hint appends a second, literal
    # "Order ID: {order['id']}" (see the f-string bug documented in
    # test_pending_info_order_includes_shipping_hint above).
    assert result.count("Order ID:") == 3


def test_supabase_exception_returns_error_string(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    _chain(fake_supabase).execute.side_effect = RuntimeError("connection lost")
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert result == "Error accessing order database: connection lost"


def test_missing_id_key_is_caught_by_broad_except(fake_supabase, patch_supabase):
    """Order dicts missing the required 'id' key raise a KeyError inside the
    try block (order['id'] is accessed with subscript, not .get()) -- this is
    swallowed by the function's broad `except Exception` fallback rather than
    propagating, which documents current (somewhat surprising) behavior."""
    context.set_context(user_id="user-1")
    order = {
        "status": "confirmed",
        "item_name": "No ID Item",
        "amount": 5,
        "created_at": "2026-05-05T00:00:00",
    }
    _chain(fake_supabase).execute.return_value = make_supabase_result([order])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert result.startswith("Error accessing order database:")
    assert "'id'" in result


def test_invoke_via_langchain_structured_tool_interface(fake_supabase, patch_supabase):
    """Sanity check that the public langchain `.invoke(...)` entrypoint (as the
    agent framework actually calls it) also works end-to-end, not just the
    raw `.func` shortcut used elsewhere in this file."""
    context.set_context(user_id="user-1")
    _chain(fake_supabase).execute.return_value = make_supabase_result([])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = check_user_orders.invoke({"query": "where is my stuff"})

    assert result == "Records show you haven't purchased any items from our store yet."


# ---------------------------------------------------------------------------
# Shipment tracking (SPEC-057)
#
# Deliberately folded into check_user_orders rather than given its own tool.
# "Where's my stuff?" is the same question this tool already answers, and every
# extra tool costs its schema in every prompt of every turn (SPEC-058).
# ---------------------------------------------------------------------------

SHIPPED_WITH_TRACKING = {
    "id": "ord-ship",
    "status": "shipped",
    "item_name": "Casio VX-4",
    "amount": 180,
    "created_at": "2026-09-10T00:00:00",
    "courier": "J&T Express",
    "tracking_number": "630123456789",
    "tracking_url": "https://www.jtexpress.my/tracking?billcode=630123456789",
}


def test_a_shipped_order_reports_its_courier_and_tracking_number(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    _chain(fake_supabase).execute.return_value = make_supabase_result([SHIPPED_WITH_TRACKING])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert "J&T Express" in result
    assert "630123456789" in result
    assert "https://www.jtexpress.my/tracking?billcode=630123456789" in result


def test_a_shipped_order_without_tracking_still_reads_sensibly(fake_supabase, patch_supabase):
    """Orders shipped before SPEC-057, or by a seller who only set the status."""
    context.set_context(user_id="user-1")
    order = {k: v for k, v in SHIPPED_WITH_TRACKING.items()
             if k not in ("courier", "tracking_number", "tracking_url")}
    _chain(fake_supabase).execute.return_value = make_supabase_result([order])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert "Shipped." in result
    assert "Tracking" not in result
    assert "None" not in result


def test_a_delivered_order_is_reported_as_delivered(fake_supabase, patch_supabase):
    context.set_context(user_id="user-1")
    _chain(fake_supabase).execute.return_value = make_supabase_result(
        [{**SHIPPED_WITH_TRACKING, "status": "delivered"}]
    )
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    assert "Status: DELIVERED" in result
    assert "delivered" in result.lower()
    assert "630123456789" in result


def test_tracking_details_are_only_shown_for_the_orders_that_have_them(fake_supabase, patch_supabase):
    """Two orders, one tracked: the untracked one must not borrow its number."""
    context.set_context(user_id="user-1")
    plain = {
        "id": "ord-plain",
        "status": "confirmed",
        "item_name": "Desk Chair",
        "amount": 300,
        "created_at": "2026-09-01T00:00:00",
    }
    _chain(fake_supabase).execute.return_value = make_supabase_result([SHIPPED_WITH_TRACKING, plain])
    patch_supabase("agent.tools.orders", admin=fake_supabase)

    result = _invoke()

    chair_block = result.split("Desk Chair")[1]
    assert "630123456789" not in chair_block
