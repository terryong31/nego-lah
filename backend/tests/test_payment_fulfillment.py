"""
Tests for payment/fulfillment.py — the idempotent + race-safe order
fulfillment core.

`payment.fulfillment` does `from connector import admin_supabase` at module
import time, so per conftest.py's guidance we patch
`payment.fulfillment.admin_supabase` (via the `patch_supabase` fixture)
rather than `connector.admin_supabase`.

`_send_thank_you` and `_finalize_won_sale` do LAZY imports inside the
function body:
  - `from agent.memory import conversation_memory`  (NOT agent.bot's copy)
  - `from payment.payment_state import delete_pending_payment`
  - `from cache import invalidate_item_cache`
Because these imports re-resolve at call time, patching the *origin*
module's attribute (`agent.memory.conversation_memory`,
`payment.payment_state.delete_pending_payment`, `cache.invalidate_item_cache`)
is what actually takes effect — patching `payment.fulfillment.<name>` would
do nothing since fulfillment.py never binds those names at module level.

`broadcast_to_chat` now lives in `core.broadcast` (it is realtime fan-out, not
a billing concern). It uses that module's `requests` import, so we monkeypatch
`core.broadcast.requests` directly to assert calls without ever hitting the
network.
"""

from unittest.mock import MagicMock

import pytest
import stripe

from core.broadcast import broadcast_to_chat
from domains.billing import fulfillment

# ---------------------------------------------------------------------------
# shared fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def _broadcasts(monkeypatch):
    """Capture what `broadcast_to_chat` hands the notification broker.

    Replaces the old `requests` guard: since SPEC-094 a broadcast is a local
    publish, not an HTTP POST to Supabase Realtime, so there is no network call
    left to fence off.
    """
    import core.notifications

    published: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        core.notifications.notification_broker,
        "publish",
        lambda user_id, payload: published.append((user_id, payload)),
    )
    return published


@pytest.fixture(autouse=True)
def _quiet_side_effects(monkeypatch):
    """
    By default, neutralize the lazy-imported side effects so tests that don't
    care about them (e.g. race_lost / error branches before finalization)
    don't accidentally hit real code. Individual tests override as needed.
    """
    monkeypatch.setattr("core.cache.invalidate_item_cache", MagicMock(), raising=False)
    monkeypatch.setattr("domains.billing.payment_state.delete_pending_payment", MagicMock(), raising=False)
    monkeypatch.setattr("core.email_service.send_purchase_receipt", MagicMock(), raising=False)
    monkeypatch.setattr("core.email_service.send_seller_sale_alert", MagicMock(), raising=False)
    fake_memory = MagicMock()
    monkeypatch.setattr("domains.negotiation.memory.conversation_memory", fake_memory, raising=False)
    return fake_memory


def _order_insert_result(admin, row=None):
    """Configure admin.table('orders').insert(...).execute() to return `row`."""
    from conftest import make_supabase_result

    admin.table.return_value.insert.return_value.execute.return_value = make_supabase_result([row] if row else [])


def _items_claim_result(admin, claimed_rows):
    """Configure the atomic claim UPDATE chain's .execute() return value."""
    from conftest import make_supabase_result

    (
        admin.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value
    ) = make_supabase_result(claimed_rows)


def _items_select_result(admin, rows):
    from conftest import make_supabase_result

    (admin.table.return_value.select.return_value.eq.return_value.execute.return_value) = make_supabase_result(rows)


# ---------------------------------------------------------------------------
# _is_unique_violation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "duplicate key value violates unique constraint",
        "ERROR: 23505: duplicate key",
        "Key (stripe_payment_id)=(pi_123) already exists.",
        'violates unique constraint "orders_stripe_payment_id_key"',
        "DUPLICATE KEY VALUE",  # case-insensitive
    ],
)
def test_is_unique_violation_true_cases(message):
    assert fulfillment._is_unique_violation(Exception(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        "connection refused",
        "permission denied for table orders",
        "timeout",
        "",
    ],
)
def test_is_unique_violation_false_cases(message):
    assert fulfillment._is_unique_violation(Exception(message)) is False


# ---------------------------------------------------------------------------
# _refund
# ---------------------------------------------------------------------------


def test_refund_returns_false_for_empty_payment_intent():
    assert fulfillment._refund("") is False


def test_refund_returns_false_for_nopi_placeholder():
    # "nopi_" prefixed ids are the degraded-idempotency placeholder minted
    # when fulfill_purchase is called without a real PaymentIntent — never
    # attempt to refund a fake id at Stripe.
    assert fulfillment._refund("nopi_user1_item1") is False


def test_refund_success(fake_stripe):
    result = fulfillment._refund("pi_123", reason="duplicate")

    assert result is True
    fake_stripe.Refund.create.assert_called_once_with(
        payment_intent="pi_123",
        reason="duplicate",
        idempotency_key="auto_refund_pi_123",
    )


def test_refund_treats_invalid_request_error_as_success(fake_stripe):
    # e.g. "charge already refunded" -- Stripe rejects a second refund attempt
    # with InvalidRequestError; fulfillment.py treats that as already-done.
    fake_stripe.Refund.create.side_effect = stripe.error.InvalidRequestError(
        "Charge already refunded", param="payment_intent"
    )

    result = fulfillment._refund("pi_already_refunded")

    assert result is True


def test_refund_generic_exception_returns_false(fake_stripe):
    fake_stripe.Refund.create.side_effect = RuntimeError("network blip")

    result = fulfillment._refund("pi_999")

    assert result is False


# ---------------------------------------------------------------------------
# broadcast_to_chat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_message_reaches_the_one_stream():
    """SPEC-094: there is no second transport any more. The Supabase Realtime
    topic this also posted to was public — the anon key in the bundle plus a
    user id was enough to read someone's negotiation."""
    from core.notifications import notification_broker

    q = await notification_broker.subscribe("user-1")
    try:
        broadcast_to_chat("user-1", "hello", role="ai", source="ai")
        assert q.get_nowait() == {
            "type": "new_message",
            "message": "hello",
            "role": "ai",
            "source": "ai",
            "notify": True,
        }
    finally:
        await notification_broker.unsubscribe("user-1", q)


@pytest.mark.asyncio
async def test_broadcast_notifies_the_buyer_for_messages_from_the_ai_or_the_seller():
    """`notify` is the buyer's "someone messaged you" flag."""
    from core.notifications import notification_broker

    for source in ("ai", "admin"):
        q = await notification_broker.subscribe("user-1")
        try:
            broadcast_to_chat("user-1", "hello", role="ai", source=source)
            assert q.get_nowait()["notify"] is True
        finally:
            await notification_broker.unsubscribe("user-1", q)


@pytest.mark.asyncio
async def test_the_buyers_own_message_is_delivered_but_not_notified():
    """It still has to reach the stream — that is how the admin console stays in
    sync — but nothing should toast the buyer about text they just typed."""
    from core.notifications import notification_broker

    q = await notification_broker.subscribe("user-1")
    try:
        broadcast_to_chat("user-1", "hi there", role="user", source="human")
        event = q.get_nowait()
        assert event["message"] == "hi there"
        assert event["notify"] is False
    finally:
        await notification_broker.unsubscribe("user-1", q)


@pytest.mark.asyncio
async def test_system_separators_are_delivered_but_not_notified():
    """ "--- Terry has joined the chat ---" is a thread separator, not a message."""
    from core.notifications import notification_broker

    q = await notification_broker.subscribe("user-1")
    try:
        broadcast_to_chat("user-1", "--- Terry has joined the chat ---", role="system", source="system")
        assert q.get_nowait()["notify"] is False
    finally:
        await notification_broker.unsubscribe("user-1", q)


@pytest.mark.asyncio
async def test_typing_is_fire_and_forget():
    """Nothing is persisted, and a ping with no listener is simply dropped."""
    from core.broadcast import broadcast_typing
    from core.notifications import notification_broker

    broadcast_typing("user-nobody-listening", "seller")  # must not raise

    q = await notification_broker.subscribe("user-1")
    try:
        broadcast_typing("user-1", "seller")
        assert q.get_nowait() == {"type": "typing", "role": "seller"}
    finally:
        await notification_broker.unsubscribe("user-1", q)


def test_broadcast_to_chat_swallows_exceptions(monkeypatch):
    """A dropped realtime event is cosmetic; the message is already persisted."""
    import core.broadcast

    monkeypatch.setattr(core.broadcast, "_publish", MagicMock(side_effect=RuntimeError("boom")))

    with pytest.raises(RuntimeError):
        core.broadcast._publish("user-1", {})

    # ...and the real _publish swallows what the broker throws.
    monkeypatch.undo()
    import core.notifications

    monkeypatch.setattr(
        core.notifications.notification_broker, "publish", MagicMock(side_effect=RuntimeError("network down"))
    )
    broadcast_to_chat("user-1", "hello")


# ---------------------------------------------------------------------------
# _send_thank_you
# ---------------------------------------------------------------------------


def test_send_thank_you_adds_to_memory_and_broadcasts(_quiet_side_effects, _broadcasts):
    fulfillment._send_thank_you("user-1", "Vintage Lamp", 49.9)

    _quiet_side_effects.add_message.assert_called_once()
    args, kwargs = _quiet_side_effects.add_message.call_args
    assert args[0] == "user-1"
    assert args[1] == "ai"
    assert "Vintage Lamp" in args[2]
    assert "RM49.90" in args[2]
    assert "**" not in args[2]
    assert "🎉 Payment Confirmed!" in args[2]
    assert len(_broadcasts) == 1


def test_send_thank_you_swallows_memory_errors(monkeypatch, _broadcasts):
    broken_memory = MagicMock()
    broken_memory.add_message.side_effect = RuntimeError("db down")
    monkeypatch.setattr("domains.negotiation.memory.conversation_memory", broken_memory, raising=False)

    # Must not raise, and must still reach the buyer's open tab.
    fulfillment._send_thank_you("user-1", "Widget", 10.0)

    assert len(_broadcasts) == 1


# ---------------------------------------------------------------------------
# _get_or_create_order
# ---------------------------------------------------------------------------


def test_get_or_create_order_success(patch_supabase, fake_supabase):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})

    order_id, status, buyer = fulfillment._get_or_create_order("pi_1", "item-1", "user-1", 10.0, "Widget")

    assert order_id == "order-1"
    assert status == "pending_info"
    assert buyer == "user-1"


def test_get_or_create_order_unique_violation_returns_existing(patch_supabase, fake_supabase):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )
    from conftest import make_supabase_result

    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value
    ) = make_supabase_result([{"id": "order-existing", "status": "pending_info", "buyer_id": "user-1"}])

    order_id, status, buyer = fulfillment._get_or_create_order("pi_1", "item-1", "user-1", 10.0, "Widget")

    assert order_id == "order-existing"
    assert status == "pending_info"
    assert buyer == "user-1"


def test_get_or_create_order_unique_violation_but_lookup_empty_returns_none(patch_supabase, fake_supabase):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )
    from conftest import make_supabase_result

    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value
    ) = make_supabase_result([])

    order_id, status, buyer = fulfillment._get_or_create_order("pi_1", "item-1", "user-1", 10.0, "Widget")

    assert (order_id, status, buyer) == (None, None, None)


def test_get_or_create_order_hard_error_returns_none(patch_supabase, fake_supabase):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception("connection refused")

    order_id, status, buyer = fulfillment._get_or_create_order("pi_1", "item-1", "user-1", 10.0, "Widget")

    assert (order_id, status, buyer) == (None, None, None)


def test_get_or_create_order_non_unique_error_returns_none(patch_supabase, fake_supabase):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError("db down")

    order_id, status, buyer = fulfillment._get_or_create_order("pi_1", "item-1", "user-1", 10.0, "Widget")

    assert (order_id, status, buyer) == (None, None, None)


# ---------------------------------------------------------------------------
# _finalize_won_sale
# ---------------------------------------------------------------------------


def test_finalize_won_sale_happy_path(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, _broadcasts
):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_invalidate = MagicMock()
    fake_delete_pending = MagicMock()
    fake_receipt = MagicMock()
    fake_seller_alert = MagicMock()
    monkeypatch.setattr("core.cache.invalidate_item_cache", fake_invalidate, raising=False)
    monkeypatch.setattr("domains.billing.payment_state.delete_pending_payment", fake_delete_pending, raising=False)
    monkeypatch.setattr("core.email_service.send_purchase_receipt", fake_receipt, raising=False)
    monkeypatch.setattr("core.email_service.send_seller_sale_alert", fake_seller_alert, raising=False)

    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com", order_id="ord-1")

    fake_invalidate.assert_called_once_with("item-1")
    fake_delete_pending.assert_called_once_with("user-1", "item-1", cleanup_stripe=True)
    fake_receipt.assert_called_once()
    fake_seller_alert.assert_called_once()
    receipt_args = fake_receipt.call_args[0]
    assert receipt_args[0] == "buyer@example.com"
    assert receipt_args[1]["item_name"] == "Widget"
    assert receipt_args[1]["amount"] == 25.0

    fake_supabase.table.assert_any_call("transactions")
    _quiet_side_effects.add_message.assert_called_once()
    assert len(_broadcasts) == 1


def test_finalize_won_sale_alerts_sentry_when_the_receipt_send_fails(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, _broadcasts
):
    """SPEC-048 #38-1: Resend rejecting every send is a silent failure today —
    make it a Sentry alert. Fulfilment itself still succeeds."""
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    monkeypatch.setattr("core.email_service.send_purchase_receipt", MagicMock(return_value=False), raising=False)
    monkeypatch.setattr("core.email_service.send_seller_sale_alert", MagicMock(), raising=False)
    captured = []
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", lambda msg, **kw: captured.append((msg, kw)))

    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com", order_id="ord-1")

    assert len(captured) == 1
    _msg, kw = captured[0]
    assert kw["level"] == "error"
    assert kw["tags"]["alert"] == "receipt_undelivered"
    assert kw["tags"]["order_id"] == "ord-1"


def test_finalize_won_sale_alerts_sentry_when_no_recipient_address_resolves(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, _broadcasts
):
    """SPEC-048 #38-2: no Stripe email and the account lookup returns nothing —
    the receipt can't be addressed; that must page, not vanish into the log."""
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    monkeypatch.setattr("domains.billing.buyer.account_email", lambda _uid: None)
    receipt = MagicMock()
    monkeypatch.setattr("core.email_service.send_purchase_receipt", receipt, raising=False)
    monkeypatch.setattr("core.email_service.send_seller_sale_alert", MagicMock(), raising=False)
    captured = []
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", lambda msg, **kw: captured.append((msg, kw)))

    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", None, order_id="ord-2")

    receipt.assert_not_called()
    assert any(kw["tags"]["alert"] == "receipt_no_address" for _m, kw in captured)


def test_finalize_won_sale_never_redirects_sandbox_receipts(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, _broadcasts
):
    """SPEC-074 Phase 2: with dev Resend retired there is no sandbox catch-all —
    the receipt is addressed to the buyer we resolved, even on a Stripe test key."""
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    monkeypatch.setattr("domains.billing.buyer.account_email", lambda _uid: "buyer@example.com")
    monkeypatch.setattr("core.env.STRIPE_API_KEY", "sk_test_dummy")
    receipt = MagicMock(return_value=True)
    monkeypatch.setattr("core.email_service.send_purchase_receipt", receipt, raising=False)
    monkeypatch.setattr("core.email_service.send_seller_sale_alert", MagicMock(), raising=False)

    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", None, order_id="ord-9")

    assert receipt.call_args[0][0] == "buyer@example.com"


def test_finalize_won_sale_sends_to_the_account_email_when_stripe_passed_none(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, _broadcasts
):
    """SPEC-048 #38-4: Stripe captured no email, but the buyer's account email
    is a perfectly good address — use it."""
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    monkeypatch.setattr("domains.billing.buyer.account_email", lambda _uid: "account@example.com")
    receipt = MagicMock(return_value=True)
    monkeypatch.setattr("core.email_service.send_purchase_receipt", receipt, raising=False)
    monkeypatch.setattr("core.email_service.send_seller_sale_alert", MagicMock(), raising=False)
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", MagicMock())

    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", None, order_id="ord-3")

    assert receipt.call_args[0][0] == "account@example.com"
    fulfillment.sentry_sdk.capture_message.assert_not_called()


def test_finalize_won_sale_swallows_cache_invalidate_error(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects
):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    broken_invalidate = MagicMock(side_effect=RuntimeError("cache down"))
    monkeypatch.setattr("core.cache.invalidate_item_cache", broken_invalidate, raising=False)

    # Must not raise.
    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com")


def test_finalize_won_sale_swallows_delete_pending_payment_error(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects
):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    broken_delete = MagicMock(side_effect=RuntimeError("redis down"))
    monkeypatch.setattr("domains.billing.payment_state.delete_pending_payment", broken_delete, raising=False)

    # Must not raise.
    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com")


def test_finalize_won_sale_swallows_transaction_insert_error(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects
):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError("db down")

    # Must not raise -- transaction record failure is best-effort.
    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com")


def test_finalize_won_sale_transaction_unique_violation_is_silent(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, caplog
):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )

    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com")

    # Thank-you flow still runs regardless of the transaction-insert outcome.
    _quiet_side_effects.add_message.assert_called_once()


# ---------------------------------------------------------------------------
# fulfill_purchase -- top-level status branches
# ---------------------------------------------------------------------------


def test_fulfill_purchase_missing_item_id_returns_error():
    result = fulfillment.fulfill_purchase(item_id="", user_id="user-1", payment_intent="pi_1", amount=10.0)
    assert result == {"status": "error", "error": "missing_item_or_user"}


def test_fulfill_purchase_missing_user_id_returns_error():
    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="", payment_intent="pi_1", amount=10.0)
    assert result == {"status": "error", "error": "missing_item_or_user"}


def test_fulfill_purchase_order_upsert_failed_returns_error(patch_supabase, fake_supabase):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception("connection refused")

    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0)

    assert result == {"status": "error", "error": "order_upsert_failed"}


def test_fulfill_purchase_already_refunded_order_is_noop(patch_supabase, fake_supabase):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )
    from conftest import make_supabase_result

    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value
    ) = make_supabase_result([{"id": "order-1", "status": "refunded", "buyer_id": "user-1"}])

    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0)

    assert result == {"status": "race_lost", "refunded": True, "order_id": "order-1"}


def test_fulfill_purchase_buyer_mismatch_reports_to_sentry(monkeypatch, patch_supabase, fake_supabase):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )
    from conftest import make_supabase_result

    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value
    ) = make_supabase_result([{"id": "order-1", "status": "pending_info", "buyer_id": "someone-else"}])
    fake_capture = MagicMock()
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", fake_capture)

    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0)

    assert result == {"status": "error", "error": "buyer_mismatch"}
    fake_capture.assert_called_once()
    _, kwargs = fake_capture.call_args
    assert kwargs["tags"]["alert"] == "buyer_mismatch"
    assert kwargs["tags"]["payment_intent"] == "pi_1"


def test_fulfill_purchase_fulfilled_happy_path(
    patch_supabase, fake_supabase, _quiet_side_effects, _broadcasts
):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [{"id": "item-1", "status": "sold", "buyer_id": "user-1"}])

    result = fulfillment.fulfill_purchase(
        item_id="item-1",
        user_id="user-1",
        payment_intent="pi_1",
        amount=10.0,
        item_name="Widget",
        buyer_email="buyer@example.com",
    )

    assert result == {"status": "fulfilled", "order_id": "order-1"}
    # One-time side effects ran: thank-you message added + broadcast twice.
    _quiet_side_effects.add_message.assert_called_once()
    assert len(_broadcasts) == 1


def test_fulfill_purchase_duplicate_when_already_sold_to_same_buyer(
    patch_supabase, fake_supabase, _broadcasts
):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    # Claim UPDATE affects 0 rows (item no longer 'available').
    _items_claim_result(fake_supabase, [])
    _items_select_result(fake_supabase, [{"status": "sold", "buyer_id": "user-1"}])

    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0)

    assert result == {"status": "duplicate", "order_id": "order-1"}
    # No refund broadcast should have happened for the duplicate/no-op path.
    assert _broadcasts == []


def test_fulfill_purchase_race_lost_refunds_loser(fake_stripe, patch_supabase, fake_supabase, _broadcasts):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [])  # lost the atomic claim
    _items_select_result(fake_supabase, [{"status": "sold", "buyer_id": "other-user"}])

    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0)

    assert result == {"status": "race_lost", "refunded": True, "order_id": "order-1"}
    fake_stripe.Refund.create.assert_called_once_with(
        payment_intent="pi_1",
        reason="duplicate",
        idempotency_key="auto_refund_pi_1",
    )
    # Losing order gets marked refunded.
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.assert_any_call()
    # The loser is notified via broadcast.
    assert len(_broadcasts) == 1


def test_fulfill_purchase_race_lost_item_gone_entirely(
    fake_stripe, patch_supabase, fake_supabase, _broadcasts
):
    """Claim failed and the subsequent lookup finds no item row at all (e.g. deleted)."""
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [])
    _items_select_result(fake_supabase, [])  # no row found

    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0)

    assert result == {"status": "race_lost", "refunded": True, "order_id": "order-1"}
    fake_stripe.Refund.create.assert_called_once()


def test_fulfill_purchase_refund_failed_reports_sentry_and_returns_error(
    monkeypatch, fake_stripe, patch_supabase, fake_supabase, _broadcasts
):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [])
    _items_select_result(fake_supabase, [{"status": "sold", "buyer_id": "other-user"}])
    fake_stripe.Refund.create.side_effect = RuntimeError("stripe outage")
    fake_capture = MagicMock()
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", fake_capture)

    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0)

    assert result == {"status": "error", "error": "refund_failed", "order_id": "order-1"}
    fake_capture.assert_called_once()
    _, kwargs = fake_capture.call_args
    assert kwargs["tags"]["alert"] == "refund_failed"
    assert kwargs["tags"]["order_id"] == "order-1"
    # No "you've been refunded" broadcast should be sent when the refund failed.
    assert _broadcasts == []
    # Order must NOT be marked refunded when the refund didn't actually happen.
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.assert_not_called()


def test_fulfill_purchase_race_lost_mark_refunded_update_error_is_swallowed(
    fake_stripe, patch_supabase, fake_supabase, _broadcasts
):
    """Refund succeeds but marking the order 'refunded' afterwards throws -- must not raise/blow up the response."""
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [])
    _items_select_result(fake_supabase, [{"status": "sold", "buyer_id": "other-user"}])
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.side_effect = RuntimeError("db down")

    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0)

    assert result == {"status": "race_lost", "refunded": True, "order_id": "order-1"}


def test_fulfill_purchase_without_payment_intent_mints_nopi_placeholder(
    patch_supabase, fake_supabase, _quiet_side_effects, _broadcasts
):
    """No payment_intent given -> degraded-idempotency 'nopi_' key is minted and used
    as the orders.stripe_payment_id (documents current behavior)."""
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [{"id": "item-1", "status": "sold", "buyer_id": "user-1"}])

    result = fulfillment.fulfill_purchase(item_id="item-1", user_id="user-1", payment_intent="", amount=10.0)

    assert result == {"status": "fulfilled", "order_id": "order-1"}
    insert_call = fake_supabase.table.return_value.insert.call_args
    assert insert_call.args[0]["stripe_payment_id"] == "nopi_user-1_item-1"


def test_fulfill_purchase_resolves_item_name_from_db_when_default_item(
    patch_supabase, fake_supabase, _quiet_side_effects, _broadcasts
):
    """When item_name is missing or 'Item', fulfillment queries items table to get real name."""
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(
        fake_supabase, [{"id": "item-1", "status": "sold", "buyer_id": "user-1", "name": "Real Camera"}]
    )
    _items_select_result(fake_supabase, [{"name": "Real Camera"}])

    result = fulfillment.fulfill_purchase(
        item_id="item-1",
        user_id="user-1",
        payment_intent="pi_1",
        amount=10.0,
        item_name="Item",
        buyer_email="buyer@example.com",
    )

    assert result == {"status": "fulfilled", "order_id": "order-1"}
    # Verify thank you message used the real item name instead of "Item"
    thank_you_call = _quiet_side_effects.add_message.call_args[0][2]
    assert "Real Camera" in thank_you_call
    assert "purchasing Real Camera" in thank_you_call


# ---------------------------------------------------------------------------
# A claim that ERRORED is not a claim that was LOST (SPEC-092 review)
# ---------------------------------------------------------------------------


def test_transient_db_error_during_the_claim_does_not_refund_the_buyer(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects
):
    """
    `fulfill_purchase` answers a lost claim by refunding. If the claim's UPDATE
    raises — a Supabase/PostgREST blip — that is NOT another buyer winning the
    race, and refunding on it takes real money off a payment for an item that is
    still available. The error must propagate so the webhook returns 5xx and
    Stripe redelivers (routes/payment.py maps "error" -> 503).
    """
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1", "status": "pending_info", "buyer_id": "buyer-1"})
    fake_supabase.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = (
        RuntimeError("supabase 503")
    )

    refund = MagicMock(return_value=True)
    monkeypatch.setattr(fulfillment, "_refund", refund)

    with pytest.raises(RuntimeError):
        fulfillment.fulfill_purchase(
            item_id="item-1",
            user_id="buyer-1",
            payment_intent="pi_transient",
            amount=450.0,
            item_name="Chair",
            buyer_email="buyer@example.com",
        )

    refund.assert_not_called()


def test_cache_failure_after_a_won_claim_does_not_refund_the_rightful_buyer(
    monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects
):
    """
    Once the claim UPDATE commits, the item belongs to this buyer. A Redis blip
    while invalidating the item cache must not be able to veto that — the sale
    still counts, and `_finalize_won_sale` already swallows the cache error.
    """
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1", "status": "pending_info", "buyer_id": "buyer-1"})
    _items_claim_result(fake_supabase, [{"id": "item-1", "status": "sold", "buyer_id": "buyer-1"}])
    monkeypatch.setattr("core.cache.invalidate_item_cache", MagicMock(side_effect=RuntimeError("redis down")))

    refund = MagicMock(return_value=True)
    monkeypatch.setattr(fulfillment, "_refund", refund)

    result = fulfillment.fulfill_purchase(
        item_id="item-1",
        user_id="buyer-1",
        payment_intent="pi_redis_blip",
        amount=450.0,
        item_name="Chair",
        buyer_email="buyer@example.com",
    )

    assert result["status"] == "fulfilled"
    refund.assert_not_called()
