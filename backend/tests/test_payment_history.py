"""Tests for payment/payment_history.py.

These are plain (non-route) functions that call admin_supabase directly with
no error handling, so exceptions from Supabase would simply propagate. We
patch `payment.payment_history.admin_supabase` (module-level binding) via the
`patch_supabase` fixture and configure `.execute()` return values with
`make_supabase_result`.
"""

# make_supabase_result lives in conftest.py at the tests/ package root level,
# but conftest fixtures are auto-discovered by pytest -- we still need the
# helper function itself, which is defined in backend/conftest.py.
from conftest import make_supabase_result
from payment.payment_history import (
    get_all_transactions,
    get_sales_summary,
    get_transaction_by_item,
    get_transactions_by_status,
)


def test_get_all_transactions_returns_data(fake_supabase, patch_supabase):
    rows = [
        {"id": "t1", "item_id": "i1", "amount": 100, "status": "completed"},
        {"id": "t2", "item_id": "i2", "amount": 50, "status": "refunded"},
    ]
    fake_supabase.table.return_value.select.return_value.order.return_value.execute.return_value = (
        make_supabase_result(rows)
    )
    patch_supabase("payment.payment_history", admin=fake_supabase)

    result = get_all_transactions()

    assert result == rows
    fake_supabase.table.assert_called_with("transactions")
    fake_supabase.table.return_value.select.assert_called_with("*")
    fake_supabase.table.return_value.select.return_value.order.assert_called_with(
        "created_at", desc=True
    )


def test_get_all_transactions_empty(fake_supabase, patch_supabase):
    fake_supabase.table.return_value.select.return_value.order.return_value.execute.return_value = (
        make_supabase_result([])
    )
    patch_supabase("payment.payment_history", admin=fake_supabase)

    result = get_all_transactions()

    assert result == []


def test_get_transaction_by_item_found(fake_supabase, patch_supabase):
    row = {"id": "t1", "item_id": "i1", "amount": 100, "status": "completed"}
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([row])
    )
    patch_supabase("payment.payment_history", admin=fake_supabase)

    result = get_transaction_by_item("i1")

    assert result == row
    fake_supabase.table.return_value.select.return_value.eq.assert_called_with("item_id", "i1")


def test_get_transaction_by_item_not_found(fake_supabase, patch_supabase):
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([])
    )
    patch_supabase("payment.payment_history", admin=fake_supabase)

    result = get_transaction_by_item("missing-item")

    assert result is None


def test_get_transactions_by_status(fake_supabase, patch_supabase):
    rows = [{"id": "t3", "item_id": "i3", "amount": 75, "status": "pending"}]
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result(rows)
    )
    patch_supabase("payment.payment_history", admin=fake_supabase)

    result = get_transactions_by_status("pending")

    assert result == rows
    fake_supabase.table.return_value.select.return_value.eq.assert_called_with("status", "pending")


def test_get_transactions_by_status_empty(fake_supabase, patch_supabase):
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([])
    )
    patch_supabase("payment.payment_history", admin=fake_supabase)

    result = get_transactions_by_status("refunded")

    assert result == []


def test_get_sales_summary_math_with_refunds(fake_supabase, patch_supabase):
    completed_rows = [
        {"id": "t1", "amount": 100},
        {"id": "t2", "amount": 50},
        {"id": "t3", "amount": 25},
    ]
    refunded_rows = [
        {"id": "t4", "amount": 30},
    ]

    def eq_side_effect(field, value):
        chained = fake_supabase.table.return_value.select.return_value.eq.return_value
        if field == "status" and value == "completed":
            chained.execute.return_value = make_supabase_result(completed_rows)
        elif field == "status" and value == "refunded":
            chained.execute.return_value = make_supabase_result(refunded_rows)
        return chained

    fake_supabase.table.return_value.select.return_value.eq.side_effect = eq_side_effect
    patch_supabase("payment.payment_history", admin=fake_supabase)

    summary = get_sales_summary()

    assert summary["total_sales"] == 175.0
    assert summary["total_transactions"] == 3
    assert summary["average_sale"] == round(175 / 3, 2)
    assert summary["refunded_amount"] == 30.0
    assert summary["refund_count"] == 1


def test_get_sales_summary_no_completed_transactions(fake_supabase, patch_supabase):
    # No completed and no refunded transactions -> average_sale falls back to 0
    # (avoids division by zero) and all totals are zero.
    def eq_side_effect(field, value):
        chained = fake_supabase.table.return_value.select.return_value.eq.return_value
        chained.execute.return_value = make_supabase_result([])
        return chained

    fake_supabase.table.return_value.select.return_value.eq.side_effect = eq_side_effect
    patch_supabase("payment.payment_history", admin=fake_supabase)

    summary = get_sales_summary()

    assert summary == {
        "total_sales": 0,
        "total_transactions": 0,
        "average_sale": 0,
        "refunded_amount": 0,
        "refund_count": 0,
    }


def test_get_sales_summary_handles_string_amounts(fake_supabase, patch_supabase):
    # Supabase numeric columns can come back as strings depending on driver
    # config; get_sales_summary explicitly casts with float(), so this should
    # still sum correctly.
    completed_rows = [{"id": "t1", "amount": "100.50"}, {"id": "t2", "amount": "49.50"}]
    refunded_rows = [{"id": "t3", "amount": "10.00"}]

    def eq_side_effect(field, value):
        chained = fake_supabase.table.return_value.select.return_value.eq.return_value
        if value == "completed":
            chained.execute.return_value = make_supabase_result(completed_rows)
        elif value == "refunded":
            chained.execute.return_value = make_supabase_result(refunded_rows)
        return chained

    fake_supabase.table.return_value.select.return_value.eq.side_effect = eq_side_effect
    patch_supabase("payment.payment_history", admin=fake_supabase)

    summary = get_sales_summary()

    assert summary["total_sales"] == 150.0
    assert summary["total_transactions"] == 2
    assert summary["average_sale"] == 75.0
    assert summary["refunded_amount"] == 10.0
    assert summary["refund_count"] == 1


def test_get_sales_summary_missing_amount_defaults_to_zero(fake_supabase, patch_supabase):
    # get_sales_summary uses t.get('amount', 0), so a transaction row missing
    # the 'amount' key entirely should be treated as 0 rather than raising.
    completed_rows = [{"id": "t1"}, {"id": "t2", "amount": 20}]

    def eq_side_effect(field, value):
        chained = fake_supabase.table.return_value.select.return_value.eq.return_value
        if value == "completed":
            chained.execute.return_value = make_supabase_result(completed_rows)
        else:
            chained.execute.return_value = make_supabase_result([])
        return chained

    fake_supabase.table.return_value.select.return_value.eq.side_effect = eq_side_effect
    patch_supabase("payment.payment_history", admin=fake_supabase)

    summary = get_sales_summary()

    assert summary["total_sales"] == 20.0
    assert summary["total_transactions"] == 2
    assert summary["average_sale"] == 10.0


def test_get_sales_summary_null_data_defaults_to_empty_list(fake_supabase, patch_supabase):
    # Supabase can return `.data = None` in some edge cases; get_sales_summary
    # guards against that with `completed.data or []`. make_supabase_result()
    # itself normalizes None -> [], so build the MagicMock directly here to
    # exercise payment_history's own fallback rather than the fixture's.
    from unittest.mock import MagicMock

    def eq_side_effect(field, value):
        chained = fake_supabase.table.return_value.select.return_value.eq.return_value
        null_result = MagicMock()
        null_result.data = None
        chained.execute.return_value = null_result
        return chained

    fake_supabase.table.return_value.select.return_value.eq.side_effect = eq_side_effect
    patch_supabase("payment.payment_history", admin=fake_supabase)

    summary = get_sales_summary()

    assert summary["total_sales"] == 0
    assert summary["total_transactions"] == 0
    assert summary["average_sale"] == 0
    assert summary["refunded_amount"] == 0
    assert summary["refund_count"] == 0
