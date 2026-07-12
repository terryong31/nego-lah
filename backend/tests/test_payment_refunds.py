"""
Tests for payment/refunds.py::process_refund.

process_refund is a plain synchronous function that:
  1. Looks up the transaction row for `item_id` via admin_supabase.
  2. Bails out early (no Stripe call) if: no transaction found, transaction
     already refunded, or transaction has no stripe_payment_id.
  3. Otherwise calls stripe.Refund.create(...), then updates items/orders/
     transactions tables and invalidates the item cache.
  4. On stripe.error.StripeError returns a failure dict; a non-Stripe error
     from the Stripe call itself is left to propagate. The three post-refund DB
     writes are best-effort: any failure there is caught and surfaced as a
     `db_sync_warning` on an otherwise-successful result, so a retry can't
     double-refund.

payment/refunds.py does `from connector import admin_supabase` at module
import time, so we must patch `payment.refunds.admin_supabase` (via the
`patch_supabase` fixture) rather than `connector.admin_supabase`.

`cache.invalidate_item_cache` is imported *inside* the function body
(`from cache import invalidate_item_cache`), which is a lazy import that
re-resolves at call time -- so monkeypatching `cache.invalidate_item_cache`
directly takes effect.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from unittest.mock import call

import pytest

# `make_supabase_result` is defined in the top-level conftest.py. It isn't a
# fixture itself (the `fake_supabase` / `patch_supabase` fixtures are), so we
# import the conftest module directly to reuse the same result-builder logic
# inside plain helper functions below.
import conftest as _conftest  # noqa: E402
from payment.refunds import process_refund


def _txn_result(data):
    return _conftest.make_supabase_result(data)


# ---------------------------------------------------------------------------
# Early-exit / validation paths (no Stripe call should happen)
# ---------------------------------------------------------------------------

def test_no_transaction_found_returns_error_without_calling_stripe(patch_supabase, fake_supabase, fake_stripe):
    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result([])

    result = process_refund("item-1")

    assert result == {"success": False, "error": "Transaction not found for this item"}
    fake_stripe.Refund.create.assert_not_called()


def test_transaction_already_refunded_returns_error_without_calling_stripe(patch_supabase, fake_supabase, fake_stripe):
    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result(
        [{"status": "refunded", "stripe_payment_id": "pi_123"}]
    )

    result = process_refund("item-1")

    assert result == {"success": False, "error": "This item has already been refunded"}
    fake_stripe.Refund.create.assert_not_called()


def test_missing_stripe_payment_id_returns_error_without_calling_stripe(patch_supabase, fake_supabase, fake_stripe):
    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result(
        [{"status": "completed"}]  # no stripe_payment_id key at all
    )

    result = process_refund("item-1")

    assert result == {"success": False, "error": "No Stripe payment ID found"}
    fake_stripe.Refund.create.assert_not_called()


def test_missing_stripe_payment_id_when_value_is_falsy(patch_supabase, fake_supabase, fake_stripe):
    """stripe_payment_id present but empty/None should also be treated as missing."""
    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result(
        [{"status": "completed", "stripe_payment_id": None}]
    )

    result = process_refund("item-1")

    assert result == {"success": False, "error": "No Stripe payment ID found"}
    fake_stripe.Refund.create.assert_not_called()


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

def test_success_path_updates_tables_and_invalidates_cache(patch_supabase, fake_supabase, fake_stripe, monkeypatch):
    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result(
        [{"status": "completed", "stripe_payment_id": "pi_123", "amount": 4999}]
    )

    fake_refund = type("FakeRefund", (), {"id": "re_abc123"})()
    fake_stripe.Refund.create.return_value = fake_refund

    invalidate_calls = []
    monkeypatch.setattr(
        "cache.invalidate_item_cache",
        lambda item_id=None: invalidate_calls.append(item_id),
    )

    result = process_refund("item-42", reason="duplicate")

    assert result == {"success": True, "refund_id": "re_abc123", "amount_refunded": 4999}

    # Stripe was called with the payment intent and reason.
    fake_stripe.Refund.create.assert_called_once_with(payment_intent="pi_123", reason="duplicate")

    # Cache was invalidated for this item.
    assert invalidate_calls == ["item-42"]

    # `.table()` was called in order: transactions (lookup), items (update),
    # orders (update), transactions (update).
    assert fake_supabase.table.call_args_list == [
        call("transactions"),
        call("items"),
        call("orders"),
        call("transactions"),
    ]

    # items.update sets status=available and clears buyer_id.
    update_calls = fake_supabase.table.return_value.update.call_args_list
    assert update_calls[0] == call({"status": "available", "buyer_id": None})
    # orders.update sets status=refunded.
    assert update_calls[1] == call({"status": "refunded"})
    # transactions.update sets status=refunded.
    assert update_calls[2] == call({"status": "refunded"})

    # Corresponding .eq() filters used for each update.
    eq_calls = fake_supabase.table.return_value.update.return_value.eq.call_args_list
    assert eq_calls[0] == call("id", "item-42")
    assert eq_calls[1] == call("stripe_payment_id", "pi_123")
    assert eq_calls[2] == call("item_id", "item-42")

    # Each update chain called .execute().
    assert fake_supabase.table.return_value.update.return_value.eq.return_value.execute.call_count == 3


def test_success_path_defaults_reason_to_requested_by_customer(patch_supabase, fake_supabase, fake_stripe, monkeypatch):
    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result(
        [{"status": "completed", "stripe_payment_id": "pi_999", "amount": 100}]
    )
    fake_stripe.Refund.create.return_value = type("FakeRefund", (), {"id": "re_default"})()
    monkeypatch.setattr("cache.invalidate_item_cache", lambda item_id=None: None)

    result = process_refund("item-7")  # no reason passed

    assert result["success"] is True
    fake_stripe.Refund.create.assert_called_once_with(payment_intent="pi_999", reason="requested_by_customer")


def test_success_path_survives_cache_invalidation_failure(patch_supabase, fake_supabase, fake_stripe, monkeypatch):
    """If invalidate_item_cache blows up, the refund should still be reported as successful
    (the function wraps the cache invalidation call in its own try/except)."""
    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result(
        [{"status": "completed", "stripe_payment_id": "pi_555", "amount": 250}]
    )
    fake_stripe.Refund.create.return_value = type("FakeRefund", (), {"id": "re_555"})()

    def _boom(item_id=None):
        raise RuntimeError("cache backend down")

    monkeypatch.setattr("cache.invalidate_item_cache", _boom)

    result = process_refund("item-99")

    assert result == {"success": True, "refund_id": "re_555", "amount_refunded": 250}


def test_db_write_failure_after_stripe_refund_returns_success_with_warning(
    patch_supabase, fake_supabase, fake_stripe, monkeypatch
):
    """If a DB update raises AFTER Stripe already refunded the money, the
    function must NOT propagate (a retry would double-refund). It returns
    success with a `db_sync_warning` for manual reconciliation instead."""
    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result(
        [{"status": "completed", "stripe_payment_id": "pi_777", "amount": 1500}]
    )
    # Every post-refund UPDATE .execute() blows up.
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.side_effect = RuntimeError(
        "supabase unreachable"
    )
    fake_stripe.Refund.create.return_value = type("FakeRefund", (), {"id": "re_777"})()
    monkeypatch.setattr("cache.invalidate_item_cache", lambda item_id=None: None)

    result = process_refund("item-777")

    assert result["success"] is True
    assert result["refund_id"] == "re_777"
    assert result["amount_refunded"] == 1500
    assert "db_sync_warning" in result
    # Stripe refund happened exactly once -- no retry, no double refund.
    fake_stripe.Refund.create.assert_called_once()


# ---------------------------------------------------------------------------
# Stripe error handling
# ---------------------------------------------------------------------------

def test_stripe_error_is_caught_and_returns_failure_dict(patch_supabase, fake_supabase, fake_stripe):
    import stripe

    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result(
        [{"status": "completed", "stripe_payment_id": "pi_bad", "amount": 10}]
    )
    fake_stripe.Refund.create.side_effect = stripe.error.StripeError("card issuer declined the refund")

    result = process_refund("item-err")

    assert result == {"success": False, "error": "card issuer declined the refund"}

    # No downstream table updates should have happened since the Stripe call
    # raised before any update calls were made -- only the initial lookup
    # call to 'transactions' should have occurred.
    assert fake_supabase.table.call_args_list == [call("transactions")]


def test_non_stripe_exception_propagates_uncaught(patch_supabase, fake_supabase, fake_stripe):
    patch_supabase("payment.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = _txn_result(
        [{"status": "completed", "stripe_payment_id": "pi_weird", "amount": 10}]
    )
    fake_stripe.Refund.create.side_effect = ValueError("totally unexpected")

    with pytest.raises(ValueError, match="totally unexpected"):
        process_refund("item-weird")
