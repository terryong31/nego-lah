"""
SPEC-037 — payment_state must not block Redis, and must not log to stdout.

`KEYS <pattern>` walks the entire keyspace and, because Redis is
single-threaded, blocks every other client for the duration. It is fine on a
laptop with twelve keys and a production incident with a million. `SCAN` does
the same job in cursored batches.

Separately, this module reported Stripe cleanup failures with `print()`, which
goes to stdout and never reaches the JSON logger — so the one class of error an
operator actually needs to see (a payment link left live in Stripe) was
invisible to the log pipeline and to Sentry.
"""

import logging

import payment.payment_state as payment_state
from cache import redis_client


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


class _NoKeysRedis:
    """Delegates everything to the real in-memory double except `keys`, which
    detonates — so any surviving KEYS call fails the test loudly."""

    def __init__(self, inner):
        self._inner = inner

    def keys(self, *a, **kw):
        raise AssertionError("KEYS is banned in payment_state; use scan_iter")

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_get_active_payments_for_user_does_not_call_keys(monkeypatch):
    _store(user_id="user-1", item_id="item-1")
    _store(user_id="user-1", item_id="item-2")
    _store(user_id="user-2", item_id="item-3")
    monkeypatch.setattr(payment_state, "redis_client", _NoKeysRedis(redis_client))

    urls = payment_state.get_active_payments_for_user("user-1")

    assert len(urls) == 2


def test_get_all_pending_payments_does_not_call_keys(monkeypatch):
    _store(user_id="user-1", item_id="item-1")
    _store(user_id="user-2", item_id="item-2")
    monkeypatch.setattr(payment_state, "redis_client", _NoKeysRedis(redis_client))

    payments = payment_state.get_all_pending_payments()

    assert len(payments) == 2
    assert {p["user_id"] for p in payments} == {"user-1", "user-2"}


def test_store_failure_is_logged_not_printed(monkeypatch, caplog, capsys):
    class BrokenRedis:
        def setex(self, *a, **kw):
            raise ConnectionError("redis down")

    monkeypatch.setattr(payment_state, "redis_client", BrokenRedis())

    with caplog.at_level(logging.ERROR):
        assert _store() is False

    assert any("redis down" in r.getMessage() for r in caplog.records)
    assert capsys.readouterr().out == ""


def test_stripe_cleanup_failure_is_logged_not_printed(fake_stripe, caplog, capsys):
    _store()
    fake_stripe.PaymentLink.modify.side_effect = RuntimeError("stripe exploded")

    with caplog.at_level(logging.ERROR):
        assert payment_state.delete_pending_payment("user-1", "item-1") is True

    assert any("stripe exploded" in r.getMessage() for r in caplog.records)
    assert capsys.readouterr().out == ""


def test_expired_cleanup_reports_through_the_logger(fake_stripe, caplog, capsys):
    import time as _time

    _store()
    redis_client.zadd(
        "payment:cleanup_queue", {"payment:user-1:item-1": _time.time() - 10}
    )

    with caplog.at_level(logging.INFO):
        assert payment_state.cleanup_expired_payments() == 1

    assert any("Cleaned up" in r.getMessage() for r in caplog.records)
    assert capsys.readouterr().out == ""


def test_no_print_calls_remain_in_the_module():
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(payment_state))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert not calls, f"{len(calls)} print() call(s) still in payment_state"
