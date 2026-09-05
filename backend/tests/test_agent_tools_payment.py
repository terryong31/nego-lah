"""Tests for agent/tools/payment.py (create_checkout_link, cancel_payment_link,
collect_shipping_info, web_search langchain tools).

Mocking notes specific to this module (see conftest.py's module docstring for the
general rules):

- ``create_checkout_link`` does ``from connector import user_supabase`` *inside*
  the function body (a lazy import), so we patch ``connector.user_supabase``
  directly (via the ``patch_supabase("connector", user=...)`` fixture) rather
  than ``agent.tools.payment.user_supabase`` -- no such module-level name exists
  on ``agent.tools.payment``, since the import is re-resolved on every call.
- It also does ``from payment.payment_state import get_pending_payment,
  store_pending_payment`` lazily. To simulate an existing pending payment we
  monkeypatch ``payment.payment_state.get_pending_payment`` directly (it is
  re-imported fresh on every call, so patching the source module takes
  effect). The happy path instead lets the *real*
  ``get_pending_payment``/``store_pending_payment`` run against the safe
  in-memory fake Redis (autoused fixture flushes it after every test), so no
  mocking is needed there -- we verify persistence by reading the fake Redis
  key directly (bypassing the monkeypatched wrapper used in other tests).
- ``collect_shipping_info`` does ``from connector import admin_supabase``
  lazily -> patch ``connector.admin_supabase``.
- ``web_search`` does ``from ddgs import DDGS`` lazily -> patch ``ddgs.DDGS``
  (the real class), since there is no ``agent.tools.payment.DDGS`` module-level
  name to patch.
- All tools read user_id/item_id from ``agent.context`` ContextVars, so every
  test calls ``agent.context.set_context(...)`` first.
"""

import json
from unittest.mock import MagicMock

import pytest

from agent import context
from agent.tools.payment import (
    cancel_payment_link,
    collect_shipping_info,
    create_checkout_link,
    web_search,
)


def _checkout(item_id="item-1", agreed_price=80.0):
    """Call the underlying tool function directly (bypasses the langchain
    StructuredTool schema-validation wrapper, but exercises identical code)."""
    return create_checkout_link.func(item_id, agreed_price)


def _cancel(item_id="item-1"):
    return cancel_payment_link.func(item_id)


def _collect(order_id="order-1", recipient_name="Jane Doe", phone="0123456789", address="123 Main St"):
    return collect_shipping_info.func(order_id, recipient_name, phone, address)


def _search(query="used casio calculator price"):
    return web_search.func(query)


ITEM = {
    "id": "item-1",
    "name": "Cool Widget",
    "status": "available",
    "price": 100,
    "min_price": 60,
}


def _set_item_lookup(fake_supabase, item=None, items=None):
    """Configure fake_supabase.table('items').select('*').eq('id', x).execute()."""
    result = MagicMock()
    result.data = items if items is not None else ([item] if item else [])
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = result
    return result


def _no_existing_payment(monkeypatch):
    monkeypatch.setattr("payment.payment_state.get_pending_payment", lambda uid, iid: None)


# ---------------------------------------------------------------------------
# create_checkout_link
# ---------------------------------------------------------------------------

def test_create_checkout_no_user_id():
    context.set_context(user_id=None, item_id=None)
    result = _checkout()
    assert result == "ERROR: Cannot create checkout - user not identified. Please ensure you're logged in."


def test_create_checkout_existing_pending_payment(monkeypatch):
    context.set_context(user_id="user-1", item_id="item-1")
    existing = {"agreed_price": 75.5, "payment_url": "https://pay.example/link1"}
    monkeypatch.setattr("payment.payment_state.get_pending_payment", lambda uid, iid: existing)

    result = _checkout()

    assert "already exists" in result
    assert "RM75.50" in result
    assert "https://pay.example/link1" in result


@pytest.mark.parametrize("placeholder", ["test-item-id", "item_id", "string", ""])
def test_create_checkout_hallucinated_item_id_falls_back_to_context(
    placeholder, patch_supabase, fake_supabase, monkeypatch
):
    context.set_context(user_id="user-1", item_id="real-item-42")
    _no_existing_payment(monkeypatch)
    patch_supabase("connector", user=fake_supabase)
    _set_item_lookup(fake_supabase, items=[])  # doesn't matter for this test; we inspect which id was queried

    _checkout(item_id=placeholder, agreed_price=80.0)

    eq_mock = fake_supabase.table.return_value.select.return_value.eq
    used_ids = [call.args[1] for call in eq_mock.call_args_list]
    assert used_ids == ["real-item-42"]


def test_create_checkout_item_not_found_no_context_fallback(patch_supabase, fake_supabase, monkeypatch):
    context.set_context(user_id="user-1", item_id=None)
    _no_existing_payment(monkeypatch)
    patch_supabase("connector", user=fake_supabase)
    _set_item_lookup(fake_supabase, items=[])

    result = _checkout(item_id="missing-item", agreed_price=80.0)

    assert result == "Cannot create checkout - item not found. Please try again or ask about the item explicitly."


def test_create_checkout_item_lookup_retries_with_context_item_id(
    patch_supabase, fake_supabase, fake_stripe, monkeypatch
):
    context.set_context(user_id="user-1", item_id="context-item-99")
    _no_existing_payment(monkeypatch)
    patch_supabase("connector", user=fake_supabase)

    empty = MagicMock(data=[])
    found = MagicMock(data=[dict(ITEM, id="context-item-99")])
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.side_effect = [empty, found]

    result = _checkout(item_id="wrong-item-id", agreed_price=80.0)

    eq_mock = fake_supabase.table.return_value.select.return_value.eq
    used_ids = [call.args[1] for call in eq_mock.call_args_list]
    assert used_ids == ["wrong-item-id", "context-item-99"]
    assert "Payment link created" in result


def test_create_checkout_item_not_available(patch_supabase, fake_supabase, monkeypatch):
    context.set_context(user_id="user-1", item_id=None)
    _no_existing_payment(monkeypatch)
    patch_supabase("connector", user=fake_supabase)
    sold_item = dict(ITEM, status="sold")
    _set_item_lookup(fake_supabase, item=sold_item)

    result = _checkout(item_id="item-1", agreed_price=80.0)

    assert "no longer available" in result


def test_create_checkout_price_below_min_rejected(patch_supabase, fake_supabase, monkeypatch):
    context.set_context(user_id="user-1", item_id=None)
    _no_existing_payment(monkeypatch)
    patch_supabase("connector", user=fake_supabase)
    _set_item_lookup(fake_supabase, item=ITEM)  # min_price=60, price=100

    result = _checkout(item_id="item-1", agreed_price=50.0)

    assert "PRICE VALIDATION FAILED" in result
    # Security requirement: never leak the actual min_price to the caller.
    assert "60" not in result


def test_create_checkout_price_non_positive_rejected(patch_supabase, fake_supabase, monkeypatch):
    context.set_context(user_id="user-1", item_id=None)
    _no_existing_payment(monkeypatch)
    patch_supabase("connector", user=fake_supabase)
    # min_price falls back to price via `item.get('min_price') or item.get('price', 0)`,
    # and 0 is falsy, so an item priced at 0 with an explicit min_price of 0 gives
    # min_price == 0 -- letting a price of exactly 0 clear the min_price check and
    # fall through to the dedicated non-positive-price guard.
    zero_item = {"id": "item-2", "name": "Freebie", "status": "available", "price": 0, "min_price": 0}
    _set_item_lookup(fake_supabase, item=zero_item)

    result = _checkout(item_id="item-2", agreed_price=0.0)

    assert result == "ERROR: Price must be a positive number."


def test_create_checkout_price_suspiciously_high_rejected(patch_supabase, fake_supabase, monkeypatch):
    context.set_context(user_id="user-1", item_id=None)
    _no_existing_payment(monkeypatch)
    patch_supabase("connector", user=fake_supabase)
    _set_item_lookup(fake_supabase, item=ITEM)  # asking price=100 -> cap at 1000

    result = _checkout(item_id="item-1", agreed_price=1500.0)

    assert "unreasonably high" in result


def test_create_checkout_success(patch_supabase, fake_supabase, fake_stripe, monkeypatch):
    context.set_context(user_id="user-1", item_id=None)
    _no_existing_payment(monkeypatch)
    patch_supabase("connector", user=fake_supabase)
    _set_item_lookup(fake_supabase, item=ITEM)

    fake_stripe.Product.create.return_value = MagicMock(id="prod_123")
    fake_stripe.Price.create.return_value = MagicMock(id="price_123")
    fake_stripe.PaymentLink.create.return_value = MagicMock(id="plink_123", url="https://buy.stripe.com/test")

    result = _checkout(item_id="item-1", agreed_price=80.0)

    assert "Payment link created for RM80.00" in result
    assert "https://buy.stripe.com/test" in result
    fake_stripe.Product.create.assert_called_once()
    fake_stripe.Price.create.assert_called_once()
    fake_stripe.PaymentLink.create.assert_called_once()
    assert fake_stripe.PaymentLink.create.call_args.kwargs["metadata"]["item_name"] == "Cool Widget"
    # Confirm the unit_amount conversion to cents was performed correctly.
    assert fake_stripe.Price.create.call_args.kwargs["unit_amount"] == 8000

    # store_pending_payment really ran against the safe in-memory fake Redis.
    # (We read the key directly rather than via `get_pending_payment`, since that
    # name is monkeypatched to a stub in this test via `_no_existing_payment`.)
    from cache import redis_client

    raw = redis_client.get("payment:user-1:item-1")
    assert raw is not None
    stored = json.loads(raw)
    assert stored["payment_url"] == "https://buy.stripe.com/test"
    assert stored["agreed_price"] == 80.0


def test_create_checkout_stripe_error_returns_message(patch_supabase, fake_supabase, fake_stripe, monkeypatch):
    context.set_context(user_id="user-1", item_id=None)
    _no_existing_payment(monkeypatch)
    patch_supabase("connector", user=fake_supabase)
    _set_item_lookup(fake_supabase, item=ITEM)

    fake_stripe.Product.create.side_effect = Exception("stripe is down")

    result = _checkout(item_id="item-1", agreed_price=80.0)

    assert result == "Error creating payment link: stripe is down"


# ---------------------------------------------------------------------------
# cancel_payment_link
# ---------------------------------------------------------------------------

def test_cancel_no_user_id():
    context.set_context(user_id=None, item_id=None)
    result = _cancel("item-1")
    assert result == "ERROR: Cannot cancel - user not identified."


def test_cancel_uses_context_item_id_over_param(monkeypatch):
    context.set_context(user_id="user-1", item_id="context-item")
    captured = {}

    def fake_get(uid, iid):
        captured["item_id"] = iid
        return None

    monkeypatch.setattr("payment.payment_state.get_pending_payment", fake_get)

    result = _cancel("param-item")

    assert captured["item_id"] == "context-item"
    assert "No active payment link found" in result


def test_cancel_falls_back_to_param_item_id_without_context(monkeypatch):
    context.set_context(user_id="user-1", item_id=None)
    captured = {}

    def fake_get(uid, iid):
        captured["item_id"] = iid
        return None

    monkeypatch.setattr("payment.payment_state.get_pending_payment", fake_get)

    _cancel("param-item")

    assert captured["item_id"] == "param-item"


def test_cancel_no_existing_payment(monkeypatch):
    context.set_context(user_id="user-1", item_id="item-1")
    monkeypatch.setattr("payment.payment_state.get_pending_payment", lambda uid, iid: None)

    result = _cancel("item-1")

    assert result == "No active payment link found for this item. You can continue negotiating or ask about other items."


def test_cancel_success(monkeypatch):
    context.set_context(user_id="user-1", item_id="item-1")
    existing = {"agreed_price": 99.99, "payment_url": "https://pay.example/x"}
    monkeypatch.setattr("payment.payment_state.get_pending_payment", lambda uid, iid: existing)
    monkeypatch.setattr(
        "payment.payment_state.delete_pending_payment",
        lambda uid, iid, cleanup_stripe=True: True,
    )

    result = _cancel("item-1")

    assert "Payment link cancelled" in result
    assert "RM99.99" in result


def test_cancel_delete_failure(monkeypatch):
    context.set_context(user_id="user-1", item_id="item-1")
    existing = {"agreed_price": 20.0, "payment_url": "https://pay.example/y"}
    monkeypatch.setattr("payment.payment_state.get_pending_payment", lambda uid, iid: existing)
    monkeypatch.setattr(
        "payment.payment_state.delete_pending_payment",
        lambda uid, iid, cleanup_stripe=True: False,
    )

    result = _cancel("item-1")

    assert result == "Error cancelling payment link. Please try again."


# ---------------------------------------------------------------------------
# collect_shipping_info
# ---------------------------------------------------------------------------

def test_collect_shipping_success(patch_supabase, fake_supabase):
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "order-1"}]
    )

    result = _collect(order_id="order-1")

    assert "Shipping information saved" in result
    assert "Jane Doe" in result
    assert "0123456789" in result
    assert "123 Main St" in result
    fake_supabase.table.return_value.update.assert_called_once_with(
        {
            "recipient_name": "Jane Doe",
            "phone": "0123456789",
            "address": "123 Main St",
            "status": "confirmed",
        }
    )
    fake_supabase.table.return_value.update.return_value.eq.assert_called_once_with("id", "order-1")


def test_collect_shipping_order_not_found(patch_supabase, fake_supabase):
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

    result = _collect(order_id="missing-order")

    assert result == "Order not found. Please check the order ID."


def test_collect_shipping_exception(patch_supabase, fake_supabase):
    patch_supabase("connector", admin=fake_supabase)
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.side_effect = Exception(
        "db exploded"
    )

    result = _collect(order_id="order-1")

    assert result == "Error saving shipping info: db exploded"


# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------

def test_web_search_success(monkeypatch):
    mock_instance = MagicMock()
    mock_instance.text.return_value = [
        {"title": "Casio VX-4 listing", "body": "Sold for RM150 used"},
        {"title": "Another listing", "body": "RM120 asking price"},
    ]
    monkeypatch.setattr("ddgs.DDGS", MagicMock(return_value=mock_instance))

    result = _search("used casio vx-4 price")

    assert "Found the following info" in result
    assert "Casio VX-4 listing" in result
    assert "Sold for RM150 used" in result
    mock_instance.text.assert_called_once_with("used casio vx-4 price", max_results=3)


def test_web_search_no_results(monkeypatch):
    mock_instance = MagicMock()
    mock_instance.text.return_value = []
    monkeypatch.setattr("ddgs.DDGS", MagicMock(return_value=mock_instance))

    result = _search("some obscure item")

    assert result == "No results found."


def test_web_search_none_results(monkeypatch):
    mock_instance = MagicMock()
    mock_instance.text.return_value = None
    monkeypatch.setattr("ddgs.DDGS", MagicMock(return_value=mock_instance))

    result = _search("some obscure item")

    assert result == "No results found."


def test_web_search_exception(monkeypatch):
    mock_instance = MagicMock()
    mock_instance.text.side_effect = Exception("network down")
    monkeypatch.setattr("ddgs.DDGS", MagicMock(return_value=mock_instance))

    result = _search("anything")

    assert result == "Error searching web: network down"
