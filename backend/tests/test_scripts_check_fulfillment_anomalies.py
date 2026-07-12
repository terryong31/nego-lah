"""
Tests for scripts/check_fulfillment_anomalies.py.

`check_fulfillment_anomalies.py` does `from connector import admin_supabase`
at module import time, so per conftest.py's guidance we patch
`scripts.check_fulfillment_anomalies.admin_supabase` directly (not
`connector.admin_supabase`, which would have no effect on this module).

The script queries two different tables ("orders" then "items") through the
*same* chained mock object (`admin_supabase.table(...).select(...).eq(...)
.execute()`). A plain MagicMock returns the identical `.table.return_value`
regardless of the table name argument, so a naive single-chain configuration
would make the "items" query return the same `.data` as the "orders" query.
`_make_admin_supabase()` below installs a `side_effect` on `.table(...)` that
branches on the table name so "orders" and "items" queries can be configured
independently (and "items" queries are further keyed by the `id` passed to
`.eq("id", item_id)`, since a single order-check loop can look up several
different items in principle).

`stripe.PaymentIntent.retrieve` / `stripe.Charge.retrieve` are NOT part of
conftest's `fake_stripe` fixture (it only covers checkout/refund/payment
link/product/price/webhook entry points), so this file uses `fake_stripe` as
a baseline (it's the real, already-partially-mocked `stripe` module used by
the script) and additionally monkeypatches `PaymentIntent.retrieve` /
`Charge.retrieve` per test, exactly as conftest's own fixture does for the
other entry points -- this guarantees no test here ever reaches Stripe's
network.

Note: this script uses its own module-level `logging.getLogger(__name__)`
logger (not backend/logger.py's shared logger), and initializes Sentry only
if `SENTRY_DSN` is set in the environment -- conftest pops that var, so
importing this module never calls the real `sentry_sdk.init`.
"""

import importlib
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from conftest import make_supabase_result
from scripts import check_fulfillment_anomalies as cfa

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_admin_supabase(orders_data, items_by_id=None):
    """Build a fake admin_supabase whose `.table("orders")...` and
    `.table("items")...` chains are configured independently.

    `items_by_id`: dict mapping item_id -> item dict (or list of dicts) to
    return for `.table("items").select(...).eq("id", item_id).execute()`.
    Missing ids resolve to an empty result (mimicking "item not found").
    """
    items_by_id = items_by_id or {}
    admin = MagicMock()

    def table_side_effect(table_name):
        table_mock = MagicMock()
        if table_name == "orders":
            table_mock.select.return_value.eq.return_value.execute.return_value = (
                make_supabase_result(orders_data)
            )
        elif table_name == "items":
            def eq_side_effect(_field, item_id):
                eq_mock = MagicMock()
                raw = items_by_id.get(item_id)
                if raw is None:
                    data = []
                elif isinstance(raw, list):
                    data = raw
                else:
                    data = [raw]
                eq_mock.execute.return_value = make_supabase_result(data)
                return eq_mock

            table_mock.select.return_value.eq.side_effect = eq_side_effect
        return table_mock

    admin.table.side_effect = table_side_effect
    return admin


def _iso_with_micros(dt):
    return dt.isoformat()


def _iso_without_micros(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _order(
    order_id="order-1",
    item_id="item-1",
    buyer_id="buyer-1",
    stripe_payment_id="pi_123",
    age=timedelta(hours=48),
    micros=False,
):
    created_at = datetime.now(UTC) - age
    created_at_str = _iso_with_micros(created_at) if micros else _iso_without_micros(created_at)
    return {
        "id": order_id,
        "item_id": item_id,
        "buyer_id": buyer_id,
        "stripe_payment_id": stripe_payment_id,
        "created_at": created_at_str,
        "status": "pending_info",
    }


@pytest.fixture(autouse=True)
def _capture_message(monkeypatch):
    """Replace sentry_sdk.capture_message on the script's imported `sentry_sdk`
    module reference with a MagicMock, so every test can assert on alerts
    without ever touching a real Sentry endpoint (SENTRY_DSN is unset anyway,
    so no client is configured -- this belt-and-suspenders patch also guards
    against the module having been imported elsewhere with a DSN set)."""
    mock = MagicMock()
    monkeypatch.setattr(cfa.sentry_sdk, "capture_message", mock)
    return mock


def _patch_admin(monkeypatch, orders_data, items_by_id=None):
    admin = _make_admin_supabase(orders_data, items_by_id)
    monkeypatch.setattr(cfa, "admin_supabase", admin)
    return admin


def _patch_stripe_pi_charge(fake_stripe, monkeypatch, *, pi_status="succeeded", latest_charge="ch_1", charge_refunded=False, pi_side_effect=None):
    mock_pi = MagicMock(status=pi_status, latest_charge=latest_charge)
    mock_charge = MagicMock(refunded=charge_refunded)
    if pi_side_effect is not None:
        monkeypatch.setattr(fake_stripe.PaymentIntent, "retrieve", MagicMock(side_effect=pi_side_effect))
    else:
        monkeypatch.setattr(fake_stripe.PaymentIntent, "retrieve", MagicMock(return_value=mock_pi))
    monkeypatch.setattr(fake_stripe.Charge, "retrieve", MagicMock(return_value=mock_charge))
    return mock_pi, mock_charge


# ---------------------------------------------------------------------------
# 1. No pending_info orders at all -> early return, no alerts.
# ---------------------------------------------------------------------------

def test_no_orders_data_empty_list_returns_early(monkeypatch, _capture_message):
    _patch_admin(monkeypatch, orders_data=[])
    cfa.check_anomalies()
    _capture_message.assert_not_called()


def test_no_orders_data_none_returns_early(monkeypatch, _capture_message):
    _patch_admin(monkeypatch, orders_data=None)
    cfa.check_anomalies()
    _capture_message.assert_not_called()


# ---------------------------------------------------------------------------
# 2. "No alert" paths: item not found, item not sold, item sold to same
#    buyer, and item sold to a different buyer but still within SLA (<24h).
# ---------------------------------------------------------------------------

def test_item_not_found_skips_order(monkeypatch, _capture_message):
    order = _order(item_id="ghost-item")
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={})
    cfa.check_anomalies()
    _capture_message.assert_not_called()


def test_item_not_sold_no_alert(monkeypatch, _capture_message):
    order = _order(item_id="item-1", buyer_id="buyer-1")
    item = {"status": "available", "buyer_id": None}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    cfa.check_anomalies()
    _capture_message.assert_not_called()


def test_item_sold_to_same_buyer_no_alert(monkeypatch, _capture_message):
    order = _order(item_id="item-1", buyer_id="buyer-1")
    item = {"status": "sold", "buyer_id": "buyer-1"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    cfa.check_anomalies()
    _capture_message.assert_not_called()


def test_item_sold_to_different_buyer_but_within_sla_no_alert(monkeypatch, _capture_message):
    # Item resold to a different buyer, but the order is still fresh (<24h),
    # so no SLA violation should be raised yet.
    order = _order(item_id="item-1", buyer_id="buyer-1", age=timedelta(hours=1))
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    cfa.check_anomalies()
    _capture_message.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Fatal path: stuck refund (>24h, PaymentIntent succeeded, Charge not
#    refunded).
# ---------------------------------------------------------------------------

def test_stuck_refund_triggers_fatal_alert(monkeypatch, fake_stripe, _capture_message):
    order = _order(order_id="order-42", item_id="item-1", buyer_id="buyer-1", stripe_payment_id="pi_999")
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    _patch_stripe_pi_charge(fake_stripe, monkeypatch, pi_status="succeeded", latest_charge="ch_abc", charge_refunded=False)

    cfa.check_anomalies()

    _capture_message.assert_called_once()
    args, kwargs = _capture_message.call_args
    assert "Stuck Refund" in args[0]
    assert "order-42" in args[0]
    assert kwargs["level"] == "fatal"
    assert kwargs["tags"]["alert"] == "stuck_refund_sla"
    assert kwargs["tags"]["order_id"] == "order-42"
    assert kwargs["tags"]["payment_intent"] == "pi_999"


def test_stuck_refund_uses_charge_retrieve_with_latest_charge_id(monkeypatch, fake_stripe, _capture_message):
    order = _order(item_id="item-1", stripe_payment_id="pi_555")
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    _patch_stripe_pi_charge(fake_stripe, monkeypatch, latest_charge="ch_specific", charge_refunded=False)

    cfa.check_anomalies()

    fake_stripe.PaymentIntent.retrieve.assert_called_once_with("pi_555")
    fake_stripe.Charge.retrieve.assert_called_once_with("ch_specific")
    _capture_message.assert_called_once()
    assert _capture_message.call_args.kwargs["level"] == "fatal"


# ---------------------------------------------------------------------------
# 4. General SLA warning path: every way the fatal branch can be bypassed
#    while the order is still stuck >24h with the item sold to someone else.
# ---------------------------------------------------------------------------

def test_general_warning_when_no_payment_intent_id(monkeypatch, fake_stripe, _capture_message):
    order = _order(item_id="item-1", stripe_payment_id=None)
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    monkeypatch.setattr(fake_stripe.PaymentIntent, "retrieve", MagicMock())

    cfa.check_anomalies()

    fake_stripe.PaymentIntent.retrieve.assert_not_called()
    _capture_message.assert_called_once()
    kwargs = _capture_message.call_args.kwargs
    assert kwargs["level"] == "warning"
    assert kwargs["tags"]["alert"] == "stuck_order_sla"


def test_general_warning_when_payment_intent_id_not_pi_prefixed(monkeypatch, fake_stripe, _capture_message):
    order = _order(item_id="item-1", stripe_payment_id="ch_not_a_payment_intent")
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    monkeypatch.setattr(fake_stripe.PaymentIntent, "retrieve", MagicMock())

    cfa.check_anomalies()

    fake_stripe.PaymentIntent.retrieve.assert_not_called()
    _capture_message.assert_called_once()
    assert _capture_message.call_args.kwargs["level"] == "warning"


def test_general_warning_when_payment_intent_not_succeeded(monkeypatch, fake_stripe, _capture_message):
    order = _order(item_id="item-1", stripe_payment_id="pi_pending")
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    _patch_stripe_pi_charge(fake_stripe, monkeypatch, pi_status="requires_payment_method")

    cfa.check_anomalies()

    fake_stripe.Charge.retrieve.assert_not_called()
    _capture_message.assert_called_once()
    kwargs = _capture_message.call_args.kwargs
    assert kwargs["level"] == "warning"
    assert kwargs["tags"]["alert"] == "stuck_order_sla"


def test_general_warning_when_no_latest_charge(monkeypatch, fake_stripe, _capture_message):
    order = _order(item_id="item-1", stripe_payment_id="pi_no_charge")
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    _patch_stripe_pi_charge(fake_stripe, monkeypatch, pi_status="succeeded", latest_charge=None)

    cfa.check_anomalies()

    fake_stripe.Charge.retrieve.assert_not_called()
    _capture_message.assert_called_once()
    assert _capture_message.call_args.kwargs["level"] == "warning"


def test_general_warning_when_charge_already_refunded(monkeypatch, fake_stripe, _capture_message):
    order = _order(item_id="item-1", stripe_payment_id="pi_refunded")
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    _patch_stripe_pi_charge(fake_stripe, monkeypatch, pi_status="succeeded", latest_charge="ch_ref", charge_refunded=True)

    cfa.check_anomalies()

    _capture_message.assert_called_once()
    kwargs = _capture_message.call_args.kwargs
    assert kwargs["level"] == "warning"
    assert kwargs["tags"]["alert"] == "stuck_order_sla"


def test_general_warning_when_stripe_raises(monkeypatch, fake_stripe, _capture_message):
    order = _order(item_id="item-1", stripe_payment_id="pi_boom")
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    _patch_stripe_pi_charge(fake_stripe, monkeypatch, pi_side_effect=RuntimeError("stripe unavailable"))

    cfa.check_anomalies()

    _capture_message.assert_called_once()
    kwargs = _capture_message.call_args.kwargs
    assert kwargs["level"] == "warning"
    assert kwargs["tags"]["alert"] == "stuck_order_sla"


# ---------------------------------------------------------------------------
# 5. created_at parsing branches.
# ---------------------------------------------------------------------------

def test_created_at_with_microseconds_parses_and_still_alerts(monkeypatch, fake_stripe, _capture_message):
    order = _order(item_id="item-1", stripe_payment_id="pi_micro", age=timedelta(hours=30), micros=True)
    assert "." in order["created_at"]
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    _patch_stripe_pi_charge(fake_stripe, monkeypatch, charge_refunded=False)

    cfa.check_anomalies()

    _capture_message.assert_called_once()
    assert _capture_message.call_args.kwargs["level"] == "fatal"


def test_created_at_without_microseconds_parses_and_still_alerts(monkeypatch, fake_stripe, _capture_message):
    order = _order(item_id="item-1", stripe_payment_id="pi_nomicro", age=timedelta(hours=30), micros=False)
    assert "." not in order["created_at"]
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    _patch_stripe_pi_charge(fake_stripe, monkeypatch, charge_refunded=False)

    cfa.check_anomalies()

    _capture_message.assert_called_once()
    assert _capture_message.call_args.kwargs["level"] == "fatal"


def test_created_at_unparseable_falls_back_to_now_and_suppresses_alert(monkeypatch, fake_stripe, _capture_message):
    # created_at is garbage -> the except-Exception fallback sets
    # created_at = now, so age is ~0 and the >24h gate never opens even
    # though the item was sold to someone else. This documents current
    # behavior (a malformed created_at silently hides an otherwise-real
    # anomaly rather than raising or defaulting to "stale").
    order = _order(item_id="item-1", stripe_payment_id="pi_whatever")
    order["created_at"] = "not-a-real-timestamp"
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})
    monkeypatch.setattr(fake_stripe.PaymentIntent, "retrieve", MagicMock())

    cfa.check_anomalies()

    fake_stripe.PaymentIntent.retrieve.assert_not_called()
    _capture_message.assert_not_called()


def test_created_at_none_falls_back_to_now_and_suppresses_alert(monkeypatch, fake_stripe, _capture_message):
    # order.get("created_at") can legitimately be None; "." in None raises
    # TypeError, which is also caught by the broad except-Exception fallback.
    order = _order(item_id="item-1", stripe_payment_id="pi_whatever")
    order["created_at"] = None
    item = {"status": "sold", "buyer_id": "someone-else"}
    _patch_admin(monkeypatch, orders_data=[order], items_by_id={"item-1": item})

    cfa.check_anomalies()

    _capture_message.assert_not_called()


# ---------------------------------------------------------------------------
# 6. Module-level Sentry initialization gating (mirrors main.py's test
#    pattern: SENTRY_DSN is read once at import time, so we monkeypatch the
#    env var and importlib.reload() the module to observe both branches).
#    sentry_sdk.init itself is mocked so this never touches the network.
# ---------------------------------------------------------------------------

def test_sentry_not_initialized_without_dsn():
    # conftest pins SENTRY_DSN to "" (falsy, not simply absent - see conftest's
    # module docstring for why), so the module-level import at the top of this
    # file already ran with sentry_sdk.init never called.
    import os
    assert not os.environ.get("SENTRY_DSN")


def test_sentry_initialized_when_dsn_set(monkeypatch):
    import sentry_sdk

    mock_init = MagicMock()
    monkeypatch.setattr(sentry_sdk, "init", mock_init)
    monkeypatch.setenv("SENTRY_DSN", "https://fakekey@fake.ingest.sentry.io/123")
    monkeypatch.setenv("ENV", "staging")
    try:
        importlib.reload(cfa)
        mock_init.assert_called_once_with(
            dsn="https://fakekey@fake.ingest.sentry.io/123", environment="staging"
        )
    finally:
        monkeypatch.undo()
        importlib.reload(cfa)


# ---------------------------------------------------------------------------
# 7. Multiple orders processed in one pass, mixing outcomes.
# ---------------------------------------------------------------------------

def test_multiple_orders_mixed_outcomes(monkeypatch, fake_stripe, _capture_message):
    fatal_order = _order(order_id="order-fatal", item_id="item-fatal", buyer_id="buyer-a", stripe_payment_id="pi_fatal")
    warning_order = _order(order_id="order-warn", item_id="item-warn", buyer_id="buyer-b", stripe_payment_id=None)
    clean_order = _order(order_id="order-clean", item_id="item-clean", buyer_id="buyer-c", stripe_payment_id="pi_clean")

    items_by_id = {
        "item-fatal": {"status": "sold", "buyer_id": "someone-else"},
        "item-warn": {"status": "sold", "buyer_id": "someone-else"},
        "item-clean": {"status": "sold", "buyer_id": "buyer-c"},  # same buyer -> not anomalous
    }
    _patch_admin(monkeypatch, orders_data=[fatal_order, warning_order, clean_order], items_by_id=items_by_id)
    _patch_stripe_pi_charge(fake_stripe, monkeypatch, pi_status="succeeded", latest_charge="ch_fatal", charge_refunded=False)

    cfa.check_anomalies()

    assert _capture_message.call_count == 2
    levels = {call.kwargs["level"] for call in _capture_message.call_args_list}
    assert levels == {"fatal", "warning"}
    order_ids_alerted = {call.kwargs["tags"]["order_id"] for call in _capture_message.call_args_list}
    assert order_ids_alerted == {"order-fatal", "order-warn"}
    # stripe.PaymentIntent.retrieve should only ever be called for the order
    # that actually has a "pi_"-prefixed payment id (fatal_order); the
    # warning_order (no payment id) and clean_order (not anomalous, so the
    # SLA branch is never entered) must not trigger a Stripe call.
    fake_stripe.PaymentIntent.retrieve.assert_called_once_with("pi_fatal")
