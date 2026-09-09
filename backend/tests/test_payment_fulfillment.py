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

`broadcast_to_chat` uses the module-level `requests` import, so we monkeypatch
`payment.fulfillment.requests` directly to assert calls without ever hitting
the network.
"""

from unittest.mock import MagicMock

import pytest
import stripe

from payment import fulfillment

# ---------------------------------------------------------------------------
# shared fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _no_network_broadcast(monkeypatch):
    """Guarantee broadcast_to_chat never makes a real HTTP call in this file."""
    fake_requests = MagicMock()
    monkeypatch.setattr(fulfillment, "requests", fake_requests)
    return fake_requests


@pytest.fixture(autouse=True)
def _quiet_side_effects(monkeypatch):
    """
    By default, neutralize the lazy-imported side effects so tests that don't
    care about them (e.g. race_lost / error branches before finalization)
    don't accidentally hit real code. Individual tests override as needed.
    """
    monkeypatch.setattr("cache.invalidate_item_cache", MagicMock(), raising=False)
    monkeypatch.setattr("payment.payment_state.delete_pending_payment", MagicMock(), raising=False)
    monkeypatch.setattr("services.email_service.send_purchase_receipt", MagicMock(), raising=False)
    monkeypatch.setattr("services.email_service.send_seller_sale_alert", MagicMock(), raising=False)
    fake_memory = MagicMock()
    monkeypatch.setattr("agent.memory.conversation_memory", fake_memory, raising=False)
    return fake_memory


def _order_insert_result(admin, row=None):
    """Configure admin.table('orders').insert(...).execute() to return `row`."""
    from conftest import make_supabase_result
    admin.table.return_value.insert.return_value.execute.return_value = make_supabase_result(
        [row] if row else []
    )


def _items_claim_result(admin, claimed_rows):
    """Configure the atomic claim UPDATE chain's .execute() return value."""
    from conftest import make_supabase_result
    (admin.table.return_value.update.return_value.eq.return_value.eq.return_value
     .execute.return_value) = make_supabase_result(claimed_rows)


def _items_select_result(admin, rows):
    from conftest import make_supabase_result
    (admin.table.return_value.select.return_value.eq.return_value
     .execute.return_value) = make_supabase_result(rows)


# ---------------------------------------------------------------------------
# _is_unique_violation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "duplicate key value violates unique constraint",
    "ERROR: 23505: duplicate key",
    "Key (stripe_payment_id)=(pi_123) already exists.",
    "violates unique constraint \"orders_stripe_payment_id_key\"",
    "DUPLICATE KEY VALUE",  # case-insensitive
])
def test_is_unique_violation_true_cases(message):
    assert fulfillment._is_unique_violation(Exception(message)) is True


@pytest.mark.parametrize("message", [
    "connection refused",
    "permission denied for table orders",
    "timeout",
    "",
])
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

def test_broadcast_to_chat_posts_twice_for_chat_and_notifications(_no_network_broadcast):
    seen_topics = []
    seen_payloads = []

    def _capture(*args, **kwargs):
        seen_topics.append(kwargs["json"]["messages"][0]["topic"])
        seen_payloads.append(kwargs["json"]["messages"][0].copy())
        return MagicMock()

    _no_network_broadcast.post.side_effect = _capture

    fulfillment.broadcast_to_chat("user-1", "hello", role="ai", source="ai")

    assert _no_network_broadcast.post.call_count == 2
    assert seen_topics == ["chat:user-1", "notifications:user-1"]
    assert seen_payloads[0]["event"] == "new_message"
    assert seen_payloads[0]["payload"] == {"role": "ai", "source": "ai", "content": "hello"}


@pytest.mark.asyncio
async def test_broadcast_notifies_the_buyer_for_messages_from_the_ai_or_the_seller(_no_network_broadcast):
    """The SSE stream is the buyer's "someone messaged you" channel."""
    from notifications import notification_broker

    for source in ("ai", "admin"):
        q = await notification_broker.subscribe("user-1")
        try:
            fulfillment.broadcast_to_chat("user-1", "hello", role="ai", source=source)
            event = q.get_nowait()
            assert event == {
                "type": "new_message",
                "message": "hello",
                "source": source,
                "role": "ai",
            }
        finally:
            await notification_broker.unsubscribe("user-1", q)


@pytest.mark.asyncio
async def test_broadcast_never_notifies_the_buyer_of_their_own_message(_no_network_broadcast):
    """The human broadcast exists to sync the admin console, not to ping the
    buyer about text they just typed themselves."""
    import asyncio

    from notifications import notification_broker

    q = await notification_broker.subscribe("user-1")
    try:
        fulfillment.broadcast_to_chat("user-1", "hi there", role="user", source="human")

        # Realtime still carries it (that is what the console listens to)...
        assert _no_network_broadcast.post.call_count == 2
        # ...but nothing lands on the buyer's notification stream.
        with pytest.raises(asyncio.QueueEmpty):
            q.get_nowait()
    finally:
        await notification_broker.unsubscribe("user-1", q)


@pytest.mark.asyncio
async def test_broadcast_does_not_notify_for_system_separators(_no_network_broadcast):
    """"--- Terry has joined the chat ---" is a thread separator, not a message."""
    import asyncio

    from notifications import notification_broker

    q = await notification_broker.subscribe("user-1")
    try:
        fulfillment.broadcast_to_chat(
            "user-1", "--- Terry has joined the chat ---", role="system", source="system"
        )
        with pytest.raises(asyncio.QueueEmpty):
            q.get_nowait()
    finally:
        await notification_broker.unsubscribe("user-1", q)


def test_broadcast_to_chat_swallows_exceptions(_no_network_broadcast):
    _no_network_broadcast.post.side_effect = RuntimeError("network down")

    # Must not raise -- broadcast failures are logged and swallowed.
    fulfillment.broadcast_to_chat("user-1", "hello")


# ---------------------------------------------------------------------------
# _send_thank_you
# ---------------------------------------------------------------------------

def test_send_thank_you_adds_to_memory_and_broadcasts(_quiet_side_effects, _no_network_broadcast):
    fulfillment._send_thank_you("user-1", "Vintage Lamp", 49.9)

    _quiet_side_effects.add_message.assert_called_once()
    args, kwargs = _quiet_side_effects.add_message.call_args
    assert args[0] == "user-1"
    assert args[1] == "ai"
    assert "Vintage Lamp" in args[2]
    assert "RM49.90" in args[2]
    assert "**" not in args[2]
    assert "🎉 Payment Confirmed!" in args[2]
    assert _no_network_broadcast.post.call_count == 2


def test_send_thank_you_swallows_memory_errors(monkeypatch, _no_network_broadcast):
    broken_memory = MagicMock()
    broken_memory.add_message.side_effect = RuntimeError("db down")
    monkeypatch.setattr("agent.memory.conversation_memory", broken_memory, raising=False)

    # Must not raise, and must still broadcast to chat.
    fulfillment._send_thank_you("user-1", "Widget", 10.0)

    assert _no_network_broadcast.post.call_count == 2


# ---------------------------------------------------------------------------
# _get_or_create_order
# ---------------------------------------------------------------------------

def test_get_or_create_order_success(patch_supabase, fake_supabase):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})

    order_id, status, buyer = fulfillment._get_or_create_order(
        "pi_1", "item-1", "user-1", 10.0, "Widget"
    )

    assert order_id == "order-1"
    assert status == "pending_info"
    assert buyer == "user-1"


def test_get_or_create_order_unique_violation_returns_existing(patch_supabase, fake_supabase):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )
    from conftest import make_supabase_result
    (fake_supabase.table.return_value.select.return_value.eq.return_value
     .limit.return_value.execute.return_value) = make_supabase_result(
        [{"id": "order-existing", "status": "pending_info", "buyer_id": "user-1"}]
    )

    order_id, status, buyer = fulfillment._get_or_create_order(
        "pi_1", "item-1", "user-1", 10.0, "Widget"
    )

    assert order_id == "order-existing"
    assert status == "pending_info"
    assert buyer == "user-1"


def test_get_or_create_order_unique_violation_but_lookup_empty_returns_none(patch_supabase, fake_supabase):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )
    from conftest import make_supabase_result
    (fake_supabase.table.return_value.select.return_value.eq.return_value
     .limit.return_value.execute.return_value) = make_supabase_result([])

    order_id, status, buyer = fulfillment._get_or_create_order(
        "pi_1", "item-1", "user-1", 10.0, "Widget"
    )

    assert (order_id, status, buyer) == (None, None, None)


def test_get_or_create_order_hard_error_returns_none(patch_supabase, fake_supabase):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "connection refused"
    )

    order_id, status, buyer = fulfillment._get_or_create_order(
        "pi_1", "item-1", "user-1", 10.0, "Widget"
    )

    assert (order_id, status, buyer) == (None, None, None)


def test_get_or_create_order_non_unique_error_returns_none(patch_supabase, fake_supabase):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError("db down")

    order_id, status, buyer = fulfillment._get_or_create_order(
        "pi_1", "item-1", "user-1", 10.0, "Widget"
    )

    assert (order_id, status, buyer) == (None, None, None)


# ---------------------------------------------------------------------------
# _finalize_won_sale
# ---------------------------------------------------------------------------

def test_finalize_won_sale_happy_path(monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, _no_network_broadcast):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    fake_invalidate = MagicMock()
    fake_delete_pending = MagicMock()
    fake_receipt = MagicMock()
    fake_seller_alert = MagicMock()
    monkeypatch.setattr("cache.invalidate_item_cache", fake_invalidate, raising=False)
    monkeypatch.setattr("payment.payment_state.delete_pending_payment", fake_delete_pending, raising=False)
    monkeypatch.setattr("services.email_service.send_purchase_receipt", fake_receipt, raising=False)
    monkeypatch.setattr("services.email_service.send_seller_sale_alert", fake_seller_alert, raising=False)

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
    assert _no_network_broadcast.post.call_count == 2


def test_finalize_won_sale_alerts_sentry_when_the_receipt_send_fails(monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, _no_network_broadcast):
    """SPEC-048 #38-1: Resend rejecting every send is a silent failure today —
    make it a Sentry alert. Fulfilment itself still succeeds."""
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    monkeypatch.setattr("services.email_service.send_purchase_receipt", MagicMock(return_value=False), raising=False)
    monkeypatch.setattr("services.email_service.send_seller_sale_alert", MagicMock(), raising=False)
    captured = []
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", lambda msg, **kw: captured.append((msg, kw)))

    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com", order_id="ord-1")

    assert len(captured) == 1
    _msg, kw = captured[0]
    assert kw["level"] == "error"
    assert kw["tags"]["alert"] == "receipt_undelivered"
    assert kw["tags"]["order_id"] == "ord-1"


def test_finalize_won_sale_alerts_sentry_when_no_recipient_address_resolves(monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, _no_network_broadcast):
    """SPEC-048 #38-2: no Stripe email and the account lookup returns nothing —
    the receipt can't be addressed; that must page, not vanish into the log."""
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    monkeypatch.setattr("payment.buyer.account_email", lambda _uid: None)
    receipt = MagicMock()
    monkeypatch.setattr("services.email_service.send_purchase_receipt", receipt, raising=False)
    monkeypatch.setattr("services.email_service.send_seller_sale_alert", MagicMock(), raising=False)
    captured = []
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", lambda msg, **kw: captured.append((msg, kw)))
    # Force the non-sandbox branch (env.STRIPE_API_KEY is re-imported inside the
    # function) so the RESEND_FORWARD_TO catch-all redirect doesn't kick in.
    monkeypatch.setattr("env.STRIPE_API_KEY", "sk_live_xxx")

    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", None, order_id="ord-2")

    receipt.assert_not_called()
    assert any(kw["tags"]["alert"] == "receipt_no_address" for _m, kw in captured)


def test_finalize_won_sale_sends_to_the_account_email_when_stripe_passed_none(monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, _no_network_broadcast):
    """SPEC-048 #38-4: Stripe captured no email, but the buyer's account email
    is a perfectly good address — use it."""
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    monkeypatch.setattr("payment.buyer.account_email", lambda _uid: "account@example.com")
    receipt = MagicMock(return_value=True)
    monkeypatch.setattr("services.email_service.send_purchase_receipt", receipt, raising=False)
    monkeypatch.setattr("services.email_service.send_seller_sale_alert", MagicMock(), raising=False)
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", MagicMock())

    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", None, order_id="ord-3")

    assert receipt.call_args[0][0] == "account@example.com"
    fulfillment.sentry_sdk.capture_message.assert_not_called()


def test_finalize_won_sale_swallows_cache_invalidate_error(monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    broken_invalidate = MagicMock(side_effect=RuntimeError("cache down"))
    monkeypatch.setattr("cache.invalidate_item_cache", broken_invalidate, raising=False)

    # Must not raise.
    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com")


def test_finalize_won_sale_swallows_delete_pending_payment_error(monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    broken_delete = MagicMock(side_effect=RuntimeError("redis down"))
    monkeypatch.setattr("payment.payment_state.delete_pending_payment", broken_delete, raising=False)

    # Must not raise.
    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com")


def test_finalize_won_sale_swallows_transaction_insert_error(monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = RuntimeError("db down")

    # Must not raise -- transaction record failure is best-effort.
    fulfillment._finalize_won_sale("item-1", "user-1", "pi_1", 25.0, "Widget", "buyer@example.com")


def test_finalize_won_sale_transaction_unique_violation_is_silent(monkeypatch, patch_supabase, fake_supabase, _quiet_side_effects, caplog):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
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
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception("connection refused")

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0
    )

    assert result == {"status": "error", "error": "order_upsert_failed"}


def test_fulfill_purchase_already_refunded_order_is_noop(patch_supabase, fake_supabase):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )
    from conftest import make_supabase_result
    (fake_supabase.table.return_value.select.return_value.eq.return_value
     .limit.return_value.execute.return_value) = make_supabase_result(
        [{"id": "order-1", "status": "refunded", "buyer_id": "user-1"}]
    )

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0
    )

    assert result == {"status": "race_lost", "refunded": True, "order_id": "order-1"}


def test_fulfill_purchase_buyer_mismatch_reports_to_sentry(monkeypatch, patch_supabase, fake_supabase):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.side_effect = Exception(
        "duplicate key value violates unique constraint"
    )
    from conftest import make_supabase_result
    (fake_supabase.table.return_value.select.return_value.eq.return_value
     .limit.return_value.execute.return_value) = make_supabase_result(
        [{"id": "order-1", "status": "pending_info", "buyer_id": "someone-else"}]
    )
    fake_capture = MagicMock()
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", fake_capture)

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0
    )

    assert result == {"status": "error", "error": "buyer_mismatch"}
    fake_capture.assert_called_once()
    _, kwargs = fake_capture.call_args
    assert kwargs["tags"]["alert"] == "buyer_mismatch"
    assert kwargs["tags"]["payment_intent"] == "pi_1"


def test_fulfill_purchase_fulfilled_happy_path(patch_supabase, fake_supabase, _quiet_side_effects, _no_network_broadcast):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [{"id": "item-1", "status": "sold", "buyer_id": "user-1"}])

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0,
        item_name="Widget", buyer_email="buyer@example.com",
    )

    assert result == {"status": "fulfilled", "order_id": "order-1"}
    # One-time side effects ran: thank-you message added + broadcast twice.
    _quiet_side_effects.add_message.assert_called_once()
    assert _no_network_broadcast.post.call_count == 2


def test_fulfill_purchase_duplicate_when_already_sold_to_same_buyer(patch_supabase, fake_supabase, _no_network_broadcast):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    # Claim UPDATE affects 0 rows (item no longer 'available').
    _items_claim_result(fake_supabase, [])
    _items_select_result(fake_supabase, [{"status": "sold", "buyer_id": "user-1"}])

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0
    )

    assert result == {"status": "duplicate", "order_id": "order-1"}
    # No refund broadcast should have happened for the duplicate/no-op path.
    _no_network_broadcast.post.assert_not_called()


def test_fulfill_purchase_race_lost_refunds_loser(fake_stripe, patch_supabase, fake_supabase, _no_network_broadcast):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [])  # lost the atomic claim
    _items_select_result(fake_supabase, [{"status": "sold", "buyer_id": "other-user"}])

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0
    )

    assert result == {"status": "race_lost", "refunded": True, "order_id": "order-1"}
    fake_stripe.Refund.create.assert_called_once_with(
        payment_intent="pi_1",
        reason="duplicate",
        idempotency_key="auto_refund_pi_1",
    )
    # Losing order gets marked refunded.
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.assert_any_call()
    # The loser is notified via broadcast.
    assert _no_network_broadcast.post.call_count == 2


def test_fulfill_purchase_race_lost_item_gone_entirely(fake_stripe, patch_supabase, fake_supabase, _no_network_broadcast):
    """Claim failed and the subsequent lookup finds no item row at all (e.g. deleted)."""
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [])
    _items_select_result(fake_supabase, [])  # no row found

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0
    )

    assert result == {"status": "race_lost", "refunded": True, "order_id": "order-1"}
    fake_stripe.Refund.create.assert_called_once()


def test_fulfill_purchase_refund_failed_reports_sentry_and_returns_error(monkeypatch, fake_stripe, patch_supabase, fake_supabase, _no_network_broadcast):
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [])
    _items_select_result(fake_supabase, [{"status": "sold", "buyer_id": "other-user"}])
    fake_stripe.Refund.create.side_effect = RuntimeError("stripe outage")
    fake_capture = MagicMock()
    monkeypatch.setattr(fulfillment.sentry_sdk, "capture_message", fake_capture)

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0
    )

    assert result == {"status": "error", "error": "refund_failed", "order_id": "order-1"}
    fake_capture.assert_called_once()
    _, kwargs = fake_capture.call_args
    assert kwargs["tags"]["alert"] == "refund_failed"
    assert kwargs["tags"]["order_id"] == "order-1"
    # No "you've been refunded" broadcast should be sent when the refund failed.
    _no_network_broadcast.post.assert_not_called()
    # Order must NOT be marked refunded when the refund didn't actually happen.
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.assert_not_called()


def test_fulfill_purchase_race_lost_mark_refunded_update_error_is_swallowed(fake_stripe, patch_supabase, fake_supabase, _no_network_broadcast):
    """Refund succeeds but marking the order 'refunded' afterwards throws -- must not raise/blow up the response."""
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [])
    _items_select_result(fake_supabase, [{"status": "sold", "buyer_id": "other-user"}])
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.side_effect = RuntimeError("db down")

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0
    )

    assert result == {"status": "race_lost", "refunded": True, "order_id": "order-1"}


def test_fulfill_purchase_without_payment_intent_mints_nopi_placeholder(patch_supabase, fake_supabase, _quiet_side_effects, _no_network_broadcast):
    """No payment_intent given -> degraded-idempotency 'nopi_' key is minted and used
    as the orders.stripe_payment_id (documents current behavior)."""
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [{"id": "item-1", "status": "sold", "buyer_id": "user-1"}])

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="", amount=10.0
    )

    assert result == {"status": "fulfilled", "order_id": "order-1"}
    insert_call = fake_supabase.table.return_value.insert.call_args
    assert insert_call.args[0]["stripe_payment_id"] == "nopi_user-1_item-1"


def test_fulfill_purchase_resolves_item_name_from_db_when_default_item(
    patch_supabase, fake_supabase, _quiet_side_effects, _no_network_broadcast
):
    """When item_name is missing or 'Item', fulfillment queries items table to get real name."""
    patch_supabase("payment.fulfillment", admin=fake_supabase)
    _order_insert_result(fake_supabase, {"id": "order-1"})
    _items_claim_result(fake_supabase, [{"id": "item-1", "status": "sold", "buyer_id": "user-1", "name": "Real Camera"}])
    _items_select_result(fake_supabase, [{"name": "Real Camera"}])

    result = fulfillment.fulfill_purchase(
        item_id="item-1", user_id="user-1", payment_intent="pi_1", amount=10.0,
        item_name="Item", buyer_email="buyer@example.com",
    )

    assert result == {"status": "fulfilled", "order_id": "order-1"}
    # Verify thank you message used the real item name instead of "Item"
    thank_you_call = _quiet_side_effects.add_message.call_args[0][2]
    assert "Real Camera" in thank_you_call
    assert "purchasing Real Camera" in thank_you_call
