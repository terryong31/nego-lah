"""Tests for payment/pay.py: create_checkout_session()."""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock

from core.env import FRONTEND_URL
from domains.billing.pay import create_checkout_session


def test_create_checkout_session_without_user_id_returns_url(fake_stripe):
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/pay/cs_test_without_user"
    fake_stripe.v1.checkout.sessions.create.return_value = fake_session

    result = create_checkout_session(
        item_name="Vintage Lamp",
        price_cents=12345,
        item_id="item-1",
    )

    assert result == "https://checkout.stripe.com/pay/cs_test_without_user"
    fake_stripe.v1.checkout.sessions.create.assert_called_once()

    params = fake_stripe.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert params["metadata"] == {"item_id": "item-1", "item_name": "Vintage Lamp"}
    assert "user_id" not in params["metadata"]
    assert "customer_email" not in params
    assert "payment_method_types" not in params


def test_create_checkout_session_with_user_id_includes_metadata(fake_stripe):
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/pay/cs_test_with_user"
    fake_stripe.v1.checkout.sessions.create.return_value = fake_session

    result = create_checkout_session(
        item_name="Antique Chair",
        price_cents=5000,
        item_id="item-2",
        user_id="user-42",
    )

    assert result == "https://checkout.stripe.com/pay/cs_test_with_user"

    params = fake_stripe.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert params["metadata"] == {"item_id": "item-2", "user_id": "user-42", "item_name": "Antique Chair"}


def test_create_checkout_session_passes_customer_email_to_stripe(fake_stripe):
    """SPEC-047/048: the buyer's account email pre-fills the Stripe checkout so
    the receipt has a deliverable address that matches the account."""
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/pay/cs_test_email"
    fake_stripe.v1.checkout.sessions.create.return_value = fake_session

    create_checkout_session(
        item_name="Camera",
        price_cents=30000,
        item_id="item-9",
        user_id="user-9",
        customer_email="buyer@example.com",
    )

    params = fake_stripe.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert params["customer_email"] == "buyer@example.com"
    assert params["metadata"]["item_name"] == "Camera"


def test_create_checkout_session_uses_myr_currency_and_price(fake_stripe):
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/pay/cs_test_currency"
    fake_stripe.v1.checkout.sessions.create.return_value = fake_session

    create_checkout_session(
        item_name="Wooden Desk",
        price_cents=99999,
        item_id="item-3",
    )

    params = fake_stripe.v1.checkout.sessions.create.call_args.kwargs["params"]
    line_item = params["line_items"][0]
    assert line_item["price_data"]["currency"] == "myr"
    assert line_item["price_data"]["unit_amount"] == 99999
    assert line_item["price_data"]["product_data"]["name"] == "Wooden Desk"
    assert line_item["quantity"] == 1


def test_create_checkout_session_sets_payment_mode_and_urls(fake_stripe):
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/pay/cs_test_urls"
    fake_stripe.v1.checkout.sessions.create.return_value = fake_session

    create_checkout_session(
        item_name="Bicycle",
        price_cents=25000,
        item_id="item-4",
    )

    params = fake_stripe.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert "payment_method_types" not in params
    assert params["mode"] == "payment"
    assert params["success_url"] == (
        f"{FRONTEND_URL}/checkout/success?payment=success&item_id=item-4&session_id={{CHECKOUT_SESSION_ID}}"
    )
    assert params["cancel_url"] == f"{FRONTEND_URL}/checkout/cancel"


def test_create_checkout_session_user_id_none_omits_metadata_key(fake_stripe):
    """Explicitly passing user_id=None should behave like not passing it at all."""
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/pay/cs_test_none_user"
    fake_stripe.v1.checkout.sessions.create.return_value = fake_session

    create_checkout_session(
        item_name="Sofa",
        price_cents=15000,
        item_id="item-5",
        user_id=None,
    )

    params = fake_stripe.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert params["metadata"] == {"item_id": "item-5", "item_name": "Sofa"}


def test_create_checkout_session_empty_string_user_id_omits_metadata_key(fake_stripe):
    """An empty string is falsy, so it is treated the same as no user_id (documents
    current behavior of the truthy `if user_id:` check in pay.py)."""
    fake_session = MagicMock()
    fake_session.url = "https://checkout.stripe.com/pay/cs_test_empty_user"
    fake_stripe.v1.checkout.sessions.create.return_value = fake_session

    create_checkout_session(
        item_name="Mirror",
        price_cents=8000,
        item_id="item-6",
        user_id="",
        customer_email="",
    )

    params = fake_stripe.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert params["metadata"] == {"item_id": "item-6", "item_name": "Mirror"}
    assert "customer_email" not in params
