"""
Tests for payment/payment_state.py

Covers the Redis-backed payment link lifecycle: store/get/has-active/list-for-user,
delete (with/without Stripe cleanup), the background cleanup-expired-payments job,
and the admin/debug get-all-pending-payments helper.

Uses the real in-memory Redis (flushed automatically after each test via the
autouse `_flush_in_memory_redis` fixture in conftest.py) -- no storage mocking
needed. Only Stripe calls are mocked, via the `fake_stripe` fixture.
"""

import time

import payment.payment_state as payment_state
from cache import redis_client

CLEANUP_QUEUE_KEY = "payment:cleanup_queue"


def _store(user_id="user-1", item_id="item-1", **overrides):
    kwargs = {
        "user_id": user_id,
        "item_id": item_id,
        "agreed_price": 100.0,
        "payment_link_id": "plink_123",
        "product_id": "prod_123",
        "price_id": "price_123",
        "payment_url": "https://pay.example/checkout/123",
    }
    kwargs.update(overrides)
    return payment_state.store_pending_payment(**kwargs)


# ---------------------------------------------------------------------------
# store_pending_payment / get_pending_payment
# ---------------------------------------------------------------------------

def test_store_and_get_pending_payment_roundtrip():
    ok = _store()
    assert ok is True

    payment = payment_state.get_pending_payment("user-1", "item-1")
    assert payment is not None
    assert payment["user_id"] == "user-1"
    assert payment["item_id"] == "item-1"
    assert payment["agreed_price"] == 100.0
    assert payment["payment_link_id"] == "plink_123"
    assert payment["product_id"] == "prod_123"
    assert payment["price_id"] == "price_123"
    assert payment["payment_url"] == "https://pay.example/checkout/123"
    assert "created_at" in payment


def test_store_pending_payment_adds_to_cleanup_queue():
    _store(user_id="user-q", item_id="item-q")
    key = "payment:user-q:item-q"

    # Should be findable in the sorted set with a score in the future.
    far_future = time.time() + payment_state.PAYMENT_TTL + 10
    members = redis_client.zrangebyscore(CLEANUP_QUEUE_KEY, 0, far_future)
    assert key in members


def test_store_pending_payment_handles_exception_and_returns_false(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("redis down")

    monkeypatch.setattr(payment_state.redis_client, "setex", _boom)
    ok = _store(user_id="user-err", item_id="item-err")
    assert ok is False

    # Nothing should have been persisted.
    assert payment_state.get_pending_payment("user-err", "item-err") is None


def test_get_pending_payment_not_found_returns_none():
    assert payment_state.get_pending_payment("nobody", "nothing") is None


# ---------------------------------------------------------------------------
# has_active_payment
# ---------------------------------------------------------------------------

def test_has_active_payment_true_and_false():
    assert payment_state.has_active_payment("user-2", "item-2") is False
    _store(user_id="user-2", item_id="item-2")
    assert payment_state.has_active_payment("user-2", "item-2") is True


# ---------------------------------------------------------------------------
# get_active_payments_for_user
# ---------------------------------------------------------------------------

def test_get_active_payments_for_user_returns_only_that_users_urls():
    _store(user_id="user-a", item_id="item-1", payment_url="https://pay.example/a1")
    _store(user_id="user-a", item_id="item-2", payment_url="https://pay.example/a2")
    _store(user_id="user-b", item_id="item-1", payment_url="https://pay.example/b1")

    urls_a = payment_state.get_active_payments_for_user("user-a")
    assert sorted(urls_a) == ["https://pay.example/a1", "https://pay.example/a2"]

    urls_b = payment_state.get_active_payments_for_user("user-b")
    assert urls_b == ["https://pay.example/b1"]


def test_get_active_payments_for_user_no_payments_returns_empty_list():
    assert payment_state.get_active_payments_for_user("ghost-user") == []


def test_get_active_payments_for_user_skips_entries_without_payment_url():
    # Simulate a stored record that has no truthy payment_url (defensive branch).
    _store(user_id="user-c", item_id="item-1", payment_url="")
    assert payment_state.get_active_payments_for_user("user-c") == []


# ---------------------------------------------------------------------------
# delete_pending_payment
# ---------------------------------------------------------------------------

def test_delete_pending_payment_with_cleanup_calls_stripe(fake_stripe):
    _store(user_id="user-d", item_id="item-d")

    result = payment_state.delete_pending_payment("user-d", "item-d", cleanup_stripe=True)

    assert result is True
    fake_stripe.PaymentLink.modify.assert_called_once_with("plink_123", active=False)
    fake_stripe.Product.modify.assert_called_once_with("prod_123", active=False)

    # Redis state cleaned up.
    assert payment_state.get_pending_payment("user-d", "item-d") is None
    assert "payment:user-d:item-d" not in redis_client.zrangebyscore(
        CLEANUP_QUEUE_KEY, 0, time.time() + payment_state.PAYMENT_TTL + 10
    )


def test_delete_pending_payment_without_cleanup_skips_stripe(fake_stripe):
    _store(user_id="user-e", item_id="item-e")

    result = payment_state.delete_pending_payment("user-e", "item-e", cleanup_stripe=False)

    assert result is True
    fake_stripe.PaymentLink.modify.assert_not_called()
    fake_stripe.Product.modify.assert_not_called()
    assert payment_state.get_pending_payment("user-e", "item-e") is None


def test_delete_pending_payment_missing_key_is_noop_true(fake_stripe):
    # No payment was ever stored for this user/item.
    result = payment_state.delete_pending_payment("ghost", "ghost-item", cleanup_stripe=True)
    assert result is True
    fake_stripe.PaymentLink.modify.assert_not_called()
    fake_stripe.Product.modify.assert_not_called()


def test_delete_pending_payment_skips_stripe_calls_for_falsy_ids(fake_stripe):
    _store(user_id="user-f", item_id="item-f", payment_link_id="", product_id="")

    result = payment_state.delete_pending_payment("user-f", "item-f", cleanup_stripe=True)

    assert result is True
    fake_stripe.PaymentLink.modify.assert_not_called()
    fake_stripe.Product.modify.assert_not_called()
    assert payment_state.get_pending_payment("user-f", "item-f") is None


def test_delete_pending_payment_stripe_error_is_caught_not_raised(fake_stripe):
    _store(user_id="user-g", item_id="item-g")
    fake_stripe.PaymentLink.modify.side_effect = RuntimeError("stripe exploded")

    # Should not raise despite the Stripe error.
    result = payment_state.delete_pending_payment("user-g", "item-g", cleanup_stripe=True)

    assert result is True
    # Redis is still cleaned up even though Stripe cleanup failed.
    assert payment_state.get_pending_payment("user-g", "item-g") is None


# ---------------------------------------------------------------------------
# cleanup_expired_payments
# ---------------------------------------------------------------------------

def _make_expired_entry(user_id, item_id, **overrides):
    """Store a payment normally, then move its cleanup-queue score into the past."""
    _store(user_id=user_id, item_id=item_id, **overrides)
    key = f"payment:{user_id}:{item_id}"
    redis_client.zadd(CLEANUP_QUEUE_KEY, {key: time.time() - 1})
    return key


def test_cleanup_expired_payments_no_expired_entries_returns_zero(fake_stripe):
    _store(user_id="user-h", item_id="item-h")  # score is in the future

    cleaned = payment_state.cleanup_expired_payments()

    assert cleaned == 0
    fake_stripe.PaymentLink.modify.assert_not_called()
    fake_stripe.Product.modify.assert_not_called()
    # Still active since it wasn't touched.
    assert payment_state.get_pending_payment("user-h", "item-h") is not None


def test_cleanup_expired_payments_cleans_up_expired_and_calls_stripe(fake_stripe):
    key = _make_expired_entry("user-i", "item-i")

    cleaned = payment_state.cleanup_expired_payments()

    assert cleaned == 1
    fake_stripe.PaymentLink.modify.assert_called_once_with("plink_123", active=False)
    fake_stripe.Product.modify.assert_called_once_with("prod_123", active=False)

    # Removed from both the data store and the cleanup queue.
    assert redis_client.get(key) is None
    assert key not in redis_client.zrangebyscore(CLEANUP_QUEUE_KEY, 0, time.time() + 10)


def test_cleanup_expired_payments_already_deleted_key_not_counted(fake_stripe):
    # Add directly to the cleanup queue with an expired score, but never store
    # the corresponding payment data -- simulates a payment that already
    # completed/was deleted before the cleanup job ran.
    key = "payment:user-j:item-j"
    redis_client.zadd(CLEANUP_QUEUE_KEY, {key: time.time() - 1})

    cleaned = payment_state.cleanup_expired_payments()

    assert cleaned == 0
    fake_stripe.PaymentLink.modify.assert_not_called()
    fake_stripe.Product.modify.assert_not_called()
    # Removed from the queue regardless.
    assert key not in redis_client.zrangebyscore(CLEANUP_QUEUE_KEY, 0, time.time() + 10)


def test_cleanup_expired_payments_stripe_error_caught_and_entry_still_removed(fake_stripe):
    key = _make_expired_entry("user-k", "item-k")
    fake_stripe.PaymentLink.modify.side_effect = RuntimeError("stripe down")

    cleaned = payment_state.cleanup_expired_payments()

    # The exception happens before `cleaned += 1`, so this entry isn't counted...
    assert cleaned == 0
    # ...but it must still be purged from Redis so the job doesn't loop on it forever.
    assert redis_client.get(key) is None
    assert key not in redis_client.zrangebyscore(CLEANUP_QUEUE_KEY, 0, time.time() + 10)


def test_cleanup_expired_payments_processes_multiple_entries(fake_stripe):
    key1 = _make_expired_entry(
        "user-l", "item-1", payment_link_id="plink_l1", product_id="prod_l1"
    )
    key2 = _make_expired_entry(
        "user-l", "item-2", payment_link_id="plink_l2", product_id="prod_l2"
    )
    # One still-active (non-expired) entry that must be left alone.
    _store(user_id="user-l", item_id="item-3")

    cleaned = payment_state.cleanup_expired_payments()

    assert cleaned == 2
    assert redis_client.get(key1) is None
    assert redis_client.get(key2) is None
    assert payment_state.get_pending_payment("user-l", "item-3") is not None
    assert fake_stripe.PaymentLink.modify.call_count == 2
    assert fake_stripe.Product.modify.call_count == 2


# ---------------------------------------------------------------------------
# get_all_pending_payments
# ---------------------------------------------------------------------------

def test_get_all_pending_payments_returns_all_stored_payments():
    _store(user_id="user-m", item_id="item-1")
    _store(user_id="user-n", item_id="item-1")

    all_payments = payment_state.get_all_pending_payments()

    assert len(all_payments) == 2
    user_ids = {p["user_id"] for p in all_payments}
    assert user_ids == {"user-m", "user-n"}


def test_get_all_pending_payments_empty_when_nothing_stored():
    assert payment_state.get_all_pending_payments() == []
