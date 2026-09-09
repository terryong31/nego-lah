"""
Tests for routes/payment.py.

Mocking seam notes (see conftest.py docstring for the general rules):
- `routes/payment.py` does `from connector import admin_supabase` and
  `from payment.pay import create_checkout_session` at MODULE import time, so
  both names are bound directly into the `routes.payment` namespace. We patch
  them there (`patch_supabase("routes.payment", admin=...)` /
  `monkeypatch.setattr(routes_payment, "create_checkout_session", ...)`)
  rather than on `connector` / `payment.pay`.
- Every other payment sub-module (`payment.payment_state`, `payment.webhooks`,
  `payment.payment_history`, `payment.refunds`, `payment.fulfillment`) is
  imported LAZILY inside the route function body (`from payment.xxx import
  yyy`), so the import re-resolves at call time -- patching the function
  directly on the sub-module (e.g. `payment.payment_state.get_active_payments_for_user`)
  takes effect even though the route file itself never has a persistent
  top-level binding to it.
- `/payment/confirm-payment` does `import stripe` lazily too, but `fake_stripe`
  patches methods directly on the `stripe.checkout.Session` class object, so
  it doesn't matter whether the import happened before or after that patch.
"""

from unittest.mock import MagicMock

import stripe as real_stripe

import payment.fulfillment as fulfillment
import payment.payment_history as payment_history
import payment.payment_state as payment_state
import payment.refunds as refunds
import payment.webhooks as webhooks
import routes.payment as routes_payment
from conftest import make_supabase_result


def _make_stripe_session(
    payment_status="paid",
    metadata=None,
    payment_intent="pi_123",
    amount_total=10000,
    customer_details=None,
):
    """Build a REAL `stripe.checkout.Session`, not a mock.

    This matters: since stripe-python 15 a `StripeObject` is no longer a dict
    subclass, so `.get()` raises AttributeError. A MagicMock (or a plain dict)
    happily answers `.get()` and would let that break through to production
    unnoticed -- which is exactly how every paid checkout started 500ing.
    `construct_from` gives us the same object the SDK hands the route."""
    return real_stripe.checkout.Session.construct_from(
        {
            "id": "cs_1",
            "object": "checkout.session",
            "payment_status": payment_status,
            "metadata": metadata if metadata is not None else {},
            "payment_intent": payment_intent,
            "amount_total": amount_total,
            "customer_details": customer_details,
        },
        "sk_test_fixture",
    )


# ---------------------------------------------------------------------------
# POST /payment/checkout
# ---------------------------------------------------------------------------

async def test_checkout_success(client, auth_user, patch_supabase, fake_supabase, monkeypatch):
    auth_user("buyer-1")
    item_row = {"id": "item-1", "name": "Widget", "price": "100.00", "status": "available"}
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        make_supabase_result([item_row])
    )
    patch_supabase("routes.payment", admin=fake_supabase)

    captured = {}

    def fake_create_checkout_session(item_name, price_cents, item_id, user_id=None, customer_email=None):
        captured.update(
            item_name=item_name, price_cents=price_cents, item_id=item_id,
            user_id=user_id, customer_email=customer_email,
        )
        return "https://checkout.stripe.com/xyz"

    monkeypatch.setattr(routes_payment, "create_checkout_session", fake_create_checkout_session)
    monkeypatch.setattr(routes_payment, "_buyer_account_email", lambda _uid: "buyer1@example.com")

    response = await client.post("/payment/checkout", json={"item_id": "item-1"})

    assert response.status_code == 200
    assert response.json() == {"checkout_url": "https://checkout.stripe.com/xyz"}
    assert captured == {
        "item_name": "Widget",
        "price_cents": 10000,
        "item_id": "item-1",
        "user_id": "buyer-1",
        "customer_email": "buyer1@example.com",
    }
    fake_supabase.table.assert_any_call("items")


async def test_checkout_item_not_found_404(client, auth_user, patch_supabase, fake_supabase):
    auth_user("buyer-1")
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        make_supabase_result([])
    )
    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.post("/payment/checkout", json={"item_id": "does-not-exist"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found"


async def test_checkout_item_not_available_409(client, auth_user, patch_supabase, fake_supabase):
    auth_user("buyer-1")
    item_row = {"id": "item-1", "name": "Widget", "price": "100.00", "status": "sold"}
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        make_supabase_result([item_row])
    )
    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.post("/payment/checkout", json={"item_id": "item-1"})

    assert response.status_code == 409
    assert response.json()["detail"] == "Item is no longer available"


async def test_checkout_user_id_mismatch_is_403(client, auth_user, patch_supabase, fake_supabase):
    auth_user("buyer-1")
    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.post(
        "/payment/checkout", json={"item_id": "item-1", "user_id": "someone-else"}
    )

    assert response.status_code == 403


async def test_checkout_generic_exception_returns_500(
    client, auth_user, patch_supabase, fake_supabase
):
    auth_user("buyer-1")
    item_row = {"id": "item-1", "name": "Widget", "price": "not-a-number", "status": "available"}
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        make_supabase_result([item_row])
    )
    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.post("/payment/checkout", json={"item_id": "item-1"})

    assert response.status_code == 500
    assert "Checkout failed" in response.json()["detail"]


async def test_checkout_price_cents_rounds_to_nearest_cent(
    client, auth_user, patch_supabase, fake_supabase, monkeypatch
):
    """Regression test for the cent-rounding fix: `round(float(item['price']) * 100)`
    rather than `int(...)`. `19.99 * 100` is `1998.9999999999998` in IEEE-754
    float; int() would floor it to 1998 (RM19.98, undercharging by a sen),
    while round() correctly yields 1999 cents (RM19.99)."""
    auth_user("buyer-1")
    item_row = {"id": "item-1", "name": "Widget", "price": "19.99", "status": "available"}
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        make_supabase_result([item_row])
    )
    patch_supabase("routes.payment", admin=fake_supabase)

    captured = {}

    def fake_create_checkout_session(item_name, price_cents, item_id, user_id=None, customer_email=None):
        captured["price_cents"] = price_cents
        return "https://checkout.stripe.com/xyz"

    monkeypatch.setattr(routes_payment, "create_checkout_session", fake_create_checkout_session)

    response = await client.post("/payment/checkout", json={"item_id": "item-1"})

    assert response.status_code == 200
    # round() charges the correct 1999 cents (RM19.99), not int()'s 1998.
    assert captured["price_cents"] == 1999


# --- SPEC-047: Buy Now honours the negotiated price -------------------------

async def _run_checkout(client, monkeypatch, fake_supabase, patch_supabase, item_row):
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        make_supabase_result([item_row])
    )
    patch_supabase("routes.payment", admin=fake_supabase)
    captured = {}

    def fake_create_checkout_session(item_name, price_cents, item_id, user_id=None, customer_email=None):
        captured["price_cents"] = price_cents
        return "https://checkout.stripe.com/xyz"

    monkeypatch.setattr(routes_payment, "create_checkout_session", fake_create_checkout_session)
    monkeypatch.setattr(routes_payment, "_buyer_account_email", lambda _uid: None)
    resp = await client.post("/payment/checkout", json={"item_id": item_row["id"]})
    return resp, captured


async def test_checkout_charges_the_negotiated_price_when_the_buyer_has_one(
    client, auth_user, patch_supabase, fake_supabase, monkeypatch
):
    auth_user("buyer-1")
    from cache import redis_client
    redis_client.setex("negotiated_price:buyer-1:item-1", 3600, "900.0")

    item_row = {"id": "item-1", "name": "Widget", "price": "1000.00", "min_price": "650.00", "status": "available"}
    resp, captured = await _run_checkout(client, monkeypatch, fake_supabase, patch_supabase, item_row)

    assert resp.status_code == 200
    assert captured["price_cents"] == 90000  # RM900, not the RM1000 listing


async def test_checkout_uses_the_listed_price_when_no_negotiation_exists(
    client, auth_user, patch_supabase, fake_supabase, monkeypatch
):
    auth_user("buyer-1")
    item_row = {"id": "item-1", "name": "Widget", "price": "1000.00", "min_price": "650.00", "status": "available"}
    resp, captured = await _run_checkout(client, monkeypatch, fake_supabase, patch_supabase, item_row)

    assert resp.status_code == 200
    assert captured["price_cents"] == 100000


async def test_checkout_clamps_a_below_floor_negotiated_price_up_to_the_floor(
    client, auth_user, patch_supabase, fake_supabase, monkeypatch
):
    """`evaluate_offer` never commits below the floor, but checkout is the money
    path — it clamps defensively rather than trusting that on faith."""
    auth_user("buyer-1")
    from cache import redis_client
    redis_client.setex("negotiated_price:buyer-1:item-1", 3600, "500.0")

    item_row = {"id": "item-1", "name": "Widget", "price": "1000.00", "min_price": "650.00", "status": "available"}
    resp, captured = await _run_checkout(client, monkeypatch, fake_supabase, patch_supabase, item_row)

    assert resp.status_code == 200
    assert captured["price_cents"] == 65000  # clamped to RM650, not RM500


async def test_checkout_passes_the_buyer_account_email_to_stripe(
    client, auth_user, patch_supabase, fake_supabase, monkeypatch
):
    auth_user("buyer-1")
    item_row = {"id": "item-1", "name": "Widget", "price": "100.00", "status": "available"}
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        make_supabase_result([item_row])
    )
    patch_supabase("routes.payment", admin=fake_supabase)
    captured = {}

    def fake_create_checkout_session(item_name, price_cents, item_id, user_id=None, customer_email=None):
        captured["customer_email"] = customer_email
        return "https://checkout.stripe.com/xyz"

    monkeypatch.setattr(routes_payment, "create_checkout_session", fake_create_checkout_session)
    monkeypatch.setattr(routes_payment, "_buyer_account_email", lambda uid: f"{uid}@example.com")

    resp = await client.post("/payment/checkout", json={"item_id": "item-1"})

    assert resp.status_code == 200
    assert captured["customer_email"] == "buyer-1@example.com"


async def test_checkout_requires_auth(client):
    response = await client.post("/payment/checkout", json={"item_id": "item-1"})
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /payment/active/{user_id}
# ---------------------------------------------------------------------------

async def test_get_active_payments_success(client, auth_user, monkeypatch):
    auth_user("buyer-1")
    monkeypatch.setattr(
        payment_state, "get_active_payments_for_user", lambda user_id: ["https://pay.example/1"]
    )

    response = await client.get("/payment/active/buyer-1")

    assert response.status_code == 200
    assert response.json() == {"active_urls": ["https://pay.example/1"]}


async def test_get_active_payments_mismatch_is_403(client, auth_user):
    auth_user("buyer-1")

    response = await client.get("/payment/active/someone-else")

    assert response.status_code == 403


async def test_get_active_payments_exception_returns_500(client, auth_user, monkeypatch):
    auth_user("buyer-1")

    def boom(user_id):
        raise RuntimeError("redis down")

    monkeypatch.setattr(payment_state, "get_active_payments_for_user", boom)

    response = await client.get("/payment/active/buyer-1")

    assert response.status_code == 500
    assert "Failed to fetch active payments" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /payment/webhook/stripe
# ---------------------------------------------------------------------------

async def test_webhook_bad_signature_returns_400(client, monkeypatch):
    monkeypatch.setattr(webhooks, "verify_webhook", lambda payload, sig: None)

    response = await client.post(
        "/payment/webhook/stripe",
        content=b'{"type": "checkout.session.completed"}',
        headers={"stripe-signature": "bad-sig"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid webhook signature"


async def test_webhook_retry_error_returns_503(client, monkeypatch):
    event = {"type": "checkout.session.completed", "data": {"object": {}}}
    monkeypatch.setattr(webhooks, "verify_webhook", lambda payload, sig: event)
    monkeypatch.setattr(
        webhooks,
        "handle_checkout_completed",
        lambda evt: {"status": "error", "retry": True},
    )

    response = await client.post(
        "/payment/webhook/stripe",
        content=b"{}",
        headers={"stripe-signature": "good-sig"},
    )

    assert response.status_code == 503


async def test_webhook_fulfilment_does_not_block_the_event_loop(client, monkeypatch):
    """Fulfilment writes to Supabase, sends an email and can issue a Stripe
    refund — all synchronous. Stripe retries on timeout, so a stalled loop here
    turns one slow webhook into duplicate deliveries."""
    import asyncio
    import contextlib
    import time

    event = {"type": "checkout.session.completed", "data": {"object": {}}}
    monkeypatch.setattr(webhooks, "verify_webhook", lambda payload, sig: event)

    def slow_fulfil(_evt):
        time.sleep(0.2)
        return {"status": "fulfilled", "order_id": "order-1"}

    monkeypatch.setattr(webhooks, "handle_checkout_completed", slow_fulfil)

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(ticker())
    try:
        response = await client.post(
            "/payment/webhook/stripe",
            content=b"{}",
            headers={"stripe-signature": "good-sig"},
        )
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat

    assert response.status_code == 200
    assert ticks > 5


async def test_webhook_success_returns_200(client, monkeypatch):
    event = {"type": "checkout.session.completed", "data": {"object": {}}}
    monkeypatch.setattr(webhooks, "verify_webhook", lambda payload, sig: event)
    monkeypatch.setattr(
        webhooks,
        "handle_checkout_completed",
        lambda evt: {"status": "fulfilled", "order_id": "order-1"},
    )

    response = await client.post(
        "/payment/webhook/stripe",
        content=b"{}",
        headers={"stripe-signature": "good-sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}


async def test_webhook_error_without_retry_still_returns_200(client, monkeypatch):
    # "duplicate" / "race_lost" / non-retryable errors are terminal successes
    # from Stripe's point of view -- ack with 200 so Stripe stops retrying.
    event = {"type": "payment_link.completed", "data": {"object": {}}}
    monkeypatch.setattr(webhooks, "verify_webhook", lambda payload, sig: event)
    monkeypatch.setattr(
        webhooks,
        "handle_checkout_completed",
        lambda evt: {"status": "error", "retry": False, "error": "missing_metadata"},
    )

    response = await client.post(
        "/payment/webhook/stripe",
        content=b"{}",
        headers={"stripe-signature": "good-sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}


async def test_webhook_ignored_event_type_does_not_call_handler(client, monkeypatch):
    event = {"type": "customer.created", "data": {"object": {}}}
    monkeypatch.setattr(webhooks, "verify_webhook", lambda payload, sig: event)

    called = {"count": 0}

    def fail_if_called(evt):
        called["count"] += 1
        return {"status": "fulfilled"}

    monkeypatch.setattr(webhooks, "handle_checkout_completed", fail_if_called)

    response = await client.post(
        "/payment/webhook/stripe",
        content=b"{}",
        headers={"stripe-signature": "good-sig"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert called["count"] == 0


# ---------------------------------------------------------------------------
# GET /payment/transactions (admin)
# ---------------------------------------------------------------------------

async def test_get_transactions_success(client, admin_user, monkeypatch):
    admin_user()
    monkeypatch.setattr(
        payment_history, "get_all_transactions", lambda: [{"id": "t1", "amount": 50}]
    )
    monkeypatch.setattr(
        payment_history,
        "get_sales_summary",
        lambda: {"total_sales": 50, "total_transactions": 1},
    )

    response = await client.get("/payment/transactions")

    assert response.status_code == 200
    body = response.json()
    assert body["transactions"] == [{"id": "t1", "amount": 50}]
    assert body["summary"] == {"total_sales": 50, "total_transactions": 1}


async def test_get_transactions_requires_admin(client):
    response = await client.get("/payment/transactions")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /payment/refund/{item_id} (admin)
# ---------------------------------------------------------------------------

async def test_refund_item_success(client, admin_user, monkeypatch):
    admin_user()
    captured = {}

    def fake_process_refund(item_id, reason):
        captured["item_id"] = item_id
        captured["reason"] = reason
        return {"success": True, "refund_id": "re_1", "amount_refunded": 100}

    monkeypatch.setattr(refunds, "process_refund", fake_process_refund)

    response = await client.post(
        "/payment/refund/item-1", params={"reason": "requested_by_customer"}
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "refund_id": "re_1", "amount_refunded": 100}
    assert captured == {"item_id": "item-1", "reason": "requested_by_customer"}


async def test_refund_item_no_reason_defaults_to_none(client, admin_user, monkeypatch):
    admin_user()
    captured = {}

    def fake_process_refund(item_id, reason):
        captured["reason"] = reason
        return {"success": True, "refund_id": "re_2", "amount_refunded": 20}

    monkeypatch.setattr(refunds, "process_refund", fake_process_refund)

    response = await client.post("/payment/refund/item-1")

    assert response.status_code == 200
    assert captured["reason"] is None


async def test_refund_item_failure_returns_400(client, admin_user, monkeypatch):
    admin_user()
    monkeypatch.setattr(
        refunds,
        "process_refund",
        lambda item_id, reason: {"success": False, "error": "Transaction not found for this item"},
    )

    response = await client.post("/payment/refund/item-1")

    assert response.status_code == 400
    assert response.json()["detail"] == "Transaction not found for this item"


async def test_refund_item_requires_admin(client):
    response = await client.post("/payment/refund/item-1")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /payment/orders/user/{user_id}
# ---------------------------------------------------------------------------

async def test_get_user_orders_success_with_item_join(
    client, auth_user, patch_supabase, fake_supabase
):
    auth_user("buyer-1")

    orders_mock = MagicMock()
    items_mock = MagicMock()
    fake_supabase.table.side_effect = lambda name: {
        "orders": orders_mock,
        "items": items_mock,
    }[name]

    order_row = {
        "id": "order-1",
        "item_id": "item-1",
        "item_name": None,
        "amount": 100,
        "status": "sold",
        "created_at": "2026-01-01T00:00:00Z",
        "stripe_payment_id": "pi_1",
    }
    orders_mock.select.return_value.eq.return_value.order.return_value.execute.return_value = (
        make_supabase_result([order_row])
    )
    item_row = {
        "name": "Widget",
        "description": "A nice widget",
        "image_path": "img.jpg",
        "condition": "new",
    }
    items_mock.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [item_row]
    )

    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.get("/payment/orders/user/buyer-1")

    assert response.status_code == 200
    body = response.json()
    assert body["orders"] == [
        {
            "id": "order-1",
            "item_id": "item-1",
            "item_name": "Widget",
            "item_image": "img.jpg",
            "item_condition": "new",
            "amount": 100,
            "status": "sold",
            "created_at": "2026-01-01T00:00:00Z",
            "stripe_payment_id": "pi_1",
        }
    ]
    orders_mock.select.return_value.eq.assert_any_call("buyer_id", "buyer-1")
    items_mock.select.return_value.eq.assert_any_call("id", "item-1")


async def test_get_user_orders_item_lookup_missing_falls_back(
    client, auth_user, patch_supabase, fake_supabase
):
    auth_user("buyer-1")

    orders_mock = MagicMock()
    items_mock = MagicMock()
    fake_supabase.table.side_effect = lambda name: {
        "orders": orders_mock,
        "items": items_mock,
    }[name]

    order_row = {
        "id": "order-2",
        "item_id": "item-missing",
        "item_name": "Saved Name",
        "amount": 50,
        "status": "sold",
        "created_at": "2026-01-02T00:00:00Z",
        "stripe_payment_id": "pi_2",
    }
    orders_mock.select.return_value.eq.return_value.order.return_value.execute.return_value = (
        make_supabase_result([order_row])
    )
    items_mock.select.return_value.eq.return_value.execute.return_value = make_supabase_result([])

    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.get("/payment/orders/user/buyer-1")

    assert response.status_code == 200
    body = response.json()["orders"][0]
    # Falls back to the order's own item_name, and image/condition are None.
    assert body["item_name"] == "Saved Name"
    assert body["item_image"] is None
    assert body["item_condition"] is None


async def test_get_user_orders_empty_returns_empty_list(
    client, auth_user, patch_supabase, fake_supabase
):
    auth_user("buyer-1")
    fake_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = (
        make_supabase_result([])
    )
    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.get("/payment/orders/user/buyer-1")

    assert response.status_code == 200
    assert response.json() == {"orders": []}


async def test_get_user_orders_mismatch_is_403(client, auth_user, patch_supabase, fake_supabase):
    auth_user("buyer-1")
    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.get("/payment/orders/user/someone-else")

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# POST /payment/confirm-payment
# ---------------------------------------------------------------------------

async def test_confirm_payment_no_session_no_item_id_400(client, auth_user):
    auth_user("buyer-1")

    response = await client.post("/payment/confirm-payment")

    assert response.status_code == 400
    assert response.json()["detail"] == "item_id is required"


async def test_confirm_payment_no_session_item_already_sold(
    client, auth_user, patch_supabase, fake_supabase
):
    auth_user("buyer-1")
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"status": "sold"}])
    )
    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.post("/payment/confirm-payment", params={"item_id": "item-1"})

    assert response.status_code == 200
    assert response.json() == {"status": "already_sold", "message": "Item already marked as sold"}


async def test_confirm_payment_no_session_item_pending(
    client, auth_user, patch_supabase, fake_supabase
):
    auth_user("buyer-1")
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"status": "available"}])
    )
    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.post("/payment/confirm-payment", params={"item_id": "item-1"})

    assert response.status_code == 200
    assert response.json() == {"status": "pending", "message": "Awaiting payment confirmation"}


async def test_confirm_payment_no_session_item_lookup_empty_is_pending(
    client, auth_user, patch_supabase, fake_supabase
):
    auth_user("buyer-1")
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([])
    )
    patch_supabase("routes.payment", admin=fake_supabase)

    response = await client.post("/payment/confirm-payment", params={"item_id": "item-1"})

    assert response.status_code == 200
    assert response.json()["status"] == "pending"


async def test_confirm_payment_invalid_stripe_session_400(client, auth_user, fake_stripe):
    auth_user("buyer-1")
    fake_stripe.checkout.Session.retrieve.side_effect = real_stripe.error.InvalidRequestError(
        "No such checkout session", None
    )

    response = await client.post(
        "/payment/confirm-payment", params={"session_id": "cs_bad"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Stripe session"


async def test_confirm_payment_not_paid_400(client, auth_user, fake_stripe):
    auth_user("buyer-1")
    session = _make_stripe_session(payment_status="unpaid")
    fake_stripe.checkout.Session.retrieve.return_value = session

    response = await client.post(
        "/payment/confirm-payment", params={"session_id": "cs_1"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Payment not completed"


async def test_confirm_payment_buyer_mismatch_403(client, auth_user, fake_stripe):
    auth_user("buyer-1")
    session = _make_stripe_session(
        payment_status="paid", metadata={"item_id": "item-1", "user_id": "someone-else"}
    )
    fake_stripe.checkout.Session.retrieve.return_value = session

    response = await client.post(
        "/payment/confirm-payment", params={"session_id": "cs_1"}
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Session does not belong to this user"


async def test_confirm_payment_missing_item_id_after_metadata_400(client, auth_user, fake_stripe):
    auth_user("buyer-1")
    session = _make_stripe_session(payment_status="paid", metadata={})
    fake_stripe.checkout.Session.retrieve.return_value = session

    response = await client.post(
        "/payment/confirm-payment", params={"session_id": "cs_1"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "item_id is required"


async def test_confirm_payment_fulfilled_returns_success(
    client, auth_user, fake_stripe, monkeypatch
):
    auth_user("buyer-1")
    session = _make_stripe_session(
        payment_status="paid",
        metadata={"item_id": "item-1", "user_id": "buyer-1", "item_name": "Widget"},
        payment_intent="pi_1",
        amount_total=10000,
        customer_details={"email": "buyer@example.com"},
    )
    fake_stripe.checkout.Session.retrieve.return_value = session

    captured = {}

    def fake_fulfill_purchase(**kwargs):
        captured.update(kwargs)
        return {"status": "fulfilled", "order_id": "order-1"}

    monkeypatch.setattr(fulfillment, "fulfill_purchase", fake_fulfill_purchase)

    response = await client.post(
        "/payment/confirm-payment", params={"session_id": "cs_1"}
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Payment confirmed and item marked as sold",
        "order_id": "order-1",
    }
    assert captured["item_id"] == "item-1"
    assert captured["user_id"] == "buyer-1"
    assert captured["payment_intent"] == "pi_1"
    assert captured["amount"] == 100.0
    assert captured["item_name"] == "Widget"
    assert captured["buyer_email"] == "buyer@example.com"


async def test_confirm_payment_duplicate_returns_already_sold(
    client, auth_user, fake_stripe, monkeypatch
):
    auth_user("buyer-1")
    session = _make_stripe_session(
        payment_status="paid", metadata={"item_id": "item-1", "user_id": "buyer-1"}
    )
    fake_stripe.checkout.Session.retrieve.return_value = session
    monkeypatch.setattr(
        fulfillment,
        "fulfill_purchase",
        lambda **kwargs: {"status": "duplicate", "order_id": "order-1"},
    )

    response = await client.post(
        "/payment/confirm-payment", params={"session_id": "cs_1"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "already_sold"


async def test_confirm_payment_race_lost_returns_refunded(
    client, auth_user, fake_stripe, monkeypatch
):
    auth_user("buyer-1")
    session = _make_stripe_session(
        payment_status="paid", metadata={"item_id": "item-1", "user_id": "buyer-1"}
    )
    fake_stripe.checkout.Session.retrieve.return_value = session
    monkeypatch.setattr(
        fulfillment,
        "fulfill_purchase",
        lambda **kwargs: {"status": "race_lost", "order_id": "order-1"},
    )

    response = await client.post(
        "/payment/confirm-payment", params={"session_id": "cs_1"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "refunded"


async def test_confirm_payment_unknown_fulfillment_status_500(
    client, auth_user, fake_stripe, monkeypatch
):
    auth_user("buyer-1")
    session = _make_stripe_session(
        payment_status="paid", metadata={"item_id": "item-1", "user_id": "buyer-1"}
    )
    fake_stripe.checkout.Session.retrieve.return_value = session
    monkeypatch.setattr(
        fulfillment,
        "fulfill_purchase",
        lambda **kwargs: {"status": "error", "error": "order_upsert_failed"},
    )

    response = await client.post(
        "/payment/confirm-payment", params={"session_id": "cs_1"}
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Could not confirm payment"


async def test_confirm_payment_item_id_falls_back_to_query_param(
    client, auth_user, fake_stripe, monkeypatch
):
    """metadata has no item_id, but the query param supplies it -- covers the
    `metadata.get('item_id') or item_id` fallback branch."""
    auth_user("buyer-1")
    session = _make_stripe_session(
        payment_status="paid", metadata={"user_id": "buyer-1"}
    )
    fake_stripe.checkout.Session.retrieve.return_value = session

    captured = {}

    def fake_fulfill_purchase(**kwargs):
        captured.update(kwargs)
        return {"status": "fulfilled", "order_id": "order-9"}

    monkeypatch.setattr(fulfillment, "fulfill_purchase", fake_fulfill_purchase)

    response = await client.post(
        "/payment/confirm-payment",
        params={"session_id": "cs_1", "item_id": "item-from-query"},
    )

    assert response.status_code == 200
    assert captured["item_id"] == "item-from-query"
