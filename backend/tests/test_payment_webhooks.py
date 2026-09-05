"""
Tests for payment/webhooks.py:

- verify_webhook(): success, ValueError (bad payload), and
  stripe.error.SignatureVerificationError (bad signature) branches.
- handle_checkout_completed(): metadata present on the session, metadata
  missing but recoverable via stripe.PaymentLink.retrieve() fallback, and
  metadata missing entirely (from both session and PaymentLink) -> the
  "missing_metadata" error result.

`payment.webhooks` imports `fulfill_purchase` directly into its own module
namespace (`from payment.fulfillment import fulfill_purchase`), so per
conftest.py's guidance we monkeypatch "payment.webhooks.fulfill_purchase"
rather than patching payment.fulfillment (which would have no effect here).
"""

import stripe

from payment import webhooks

# ---------------------------------------------------------------------------
# verify_webhook
# ---------------------------------------------------------------------------

def test_verify_webhook_success_returns_event(fake_stripe):
    fake_event = {"id": "evt_123", "type": "checkout.session.completed"}
    fake_stripe.Webhook.construct_event.return_value = fake_event

    result = webhooks.verify_webhook(b"payload-bytes", "sig-header-value")

    assert result == fake_event
    fake_stripe.Webhook.construct_event.assert_called_once_with(
        b"payload-bytes", "sig-header-value", webhooks.STRIPE_WEBHOOK_SECRET
    )


def test_verify_webhook_bad_payload_returns_none(fake_stripe):
    fake_stripe.Webhook.construct_event.side_effect = ValueError("bad payload")

    result = webhooks.verify_webhook(b"not-json", "sig-header-value")

    assert result is None


def test_verify_webhook_bad_signature_returns_none(fake_stripe):
    fake_stripe.Webhook.construct_event.side_effect = stripe.error.SignatureVerificationError(
        "signature mismatch", "sig-header-value"
    )

    result = webhooks.verify_webhook(b"payload-bytes", "bad-sig")

    assert result is None


# ---------------------------------------------------------------------------
# handle_checkout_completed
# ---------------------------------------------------------------------------

def _session_event(session_overrides=None):
    """A real Stripe Event, not a dict.

    Stripe hands `handle_checkout_completed` a `StripeObject`, which since
    stripe-python 15 is no longer a dict subclass: `.get()` on it raises
    AttributeError. Building the fixture as a plain dict hid that breakage
    from this suite while every live webhook delivery failed."""
    session = {
        "object": "checkout.session",
        "metadata": {},
        "customer_details": {"email": "buyer@example.com"},
        "payment_intent": "pi_123",
        "amount_total": 5000,
    }
    if session_overrides:
        session.update(session_overrides)
    return stripe.Event.construct_from(
        {
            "id": "evt_123",
            "object": "event",
            "type": "checkout.session.completed",
            "data": {"object": session},
        },
        "sk_test_fixture",
    )


def _payment_link(metadata):
    """A real `stripe.PaymentLink`, as `PaymentLink.retrieve()` returns."""
    return stripe.PaymentLink.construct_from(
        {"id": "plink_abc", "object": "payment_link", "metadata": metadata},
        "sk_test_fixture",
    )


def test_handle_checkout_completed_metadata_on_session(monkeypatch):
    """Metadata is present directly on the session -> no PaymentLink lookup needed."""
    called_kwargs = {}

    def fake_fulfill_purchase(**kwargs):
        called_kwargs.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(webhooks, "fulfill_purchase", fake_fulfill_purchase)

    event = _session_event({
        "metadata": {"item_id": "item-1", "user_id": "user-1", "item_name": "Widget"},
    })

    result = webhooks.handle_checkout_completed(event)

    assert result == {"status": "success"}
    assert called_kwargs == {
        "item_id": "item-1",
        "user_id": "user-1",
        "payment_intent": "pi_123",
        "amount": 50.0,
        "item_name": "Widget",
        "buyer_email": "buyer@example.com",
    }


def test_handle_checkout_completed_metadata_via_payment_link_fallback(monkeypatch, fake_stripe):
    """Metadata missing on session but session references a payment_link -> fetched from PaymentLink."""
    fake_stripe.PaymentLink.retrieve.return_value = _payment_link(
        {"item_id": "item-2", "user_id": "user-2", "item_name": "Gadget"}
    )

    called_kwargs = {}

    def fake_fulfill_purchase(**kwargs):
        called_kwargs.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(webhooks, "fulfill_purchase", fake_fulfill_purchase)

    event = _session_event({
        "metadata": {},
        "payment_link": "plink_abc",
    })

    result = webhooks.handle_checkout_completed(event)

    stripe.PaymentLink.retrieve.assert_called_once_with("plink_abc")
    assert result == {"status": "success"}
    assert called_kwargs == {
        "item_id": "item-2",
        "user_id": "user-2",
        "payment_intent": "pi_123",
        "amount": 50.0,
        "item_name": "Gadget",
        "buyer_email": "buyer@example.com",
    }


def test_handle_checkout_completed_missing_metadata_returns_error(monkeypatch, fake_stripe):
    """No metadata on session, no payment_link at all -> fulfillment is never attempted."""
    called = False

    def fake_fulfill_purchase(**kwargs):
        nonlocal called
        called = True
        return {"status": "success"}

    monkeypatch.setattr(webhooks, "fulfill_purchase", fake_fulfill_purchase)

    event = _session_event({"metadata": {}})
    # no "payment_link" key at all in the session

    result = webhooks.handle_checkout_completed(event)

    assert result == {"status": "error", "error": "missing_metadata", "retry": False}
    assert called is False
    stripe.PaymentLink.retrieve.assert_not_called()


def test_handle_checkout_completed_payment_link_lookup_raises_falls_through_to_missing_metadata(
    monkeypatch, fake_stripe
):
    """If the PaymentLink retrieve() call itself raises, the exception is swallowed
    (logged as a warning) and we fall through to the missing_metadata error path."""
    fake_stripe.PaymentLink.retrieve.side_effect = Exception("stripe api down")

    called = False

    def fake_fulfill_purchase(**kwargs):
        nonlocal called
        called = True
        return {"status": "success"}

    monkeypatch.setattr(webhooks, "fulfill_purchase", fake_fulfill_purchase)

    event = _session_event({
        "metadata": {},
        "payment_link": "plink_broken",
    })

    result = webhooks.handle_checkout_completed(event)

    assert result == {"status": "error", "error": "missing_metadata", "retry": False}
    assert called is False


def test_handle_checkout_completed_payment_link_metadata_none_falls_through(monkeypatch, fake_stripe):
    """PaymentLink.retrieve() succeeds but its .metadata is falsy (None) ->
    `metadata = plink.metadata or {}` covers the `or {}` branch, still missing item_id/user_id."""
    fake_stripe.PaymentLink.retrieve.return_value = _payment_link(None)

    monkeypatch.setattr(webhooks, "fulfill_purchase", lambda **kwargs: {"status": "success"})

    event = _session_event({
        "metadata": {},
        "payment_link": "plink_empty",
    })

    result = webhooks.handle_checkout_completed(event)

    assert result == {"status": "error", "error": "missing_metadata", "retry": False}


def test_handle_checkout_completed_missing_user_id_only(monkeypatch, fake_stripe):
    """item_id present but user_id missing -> still treated as missing_metadata."""
    monkeypatch.setattr(webhooks, "fulfill_purchase", lambda **kwargs: {"status": "success"})

    event = _session_event({
        "metadata": {"item_id": "item-3"},
    })

    result = webhooks.handle_checkout_completed(event)

    assert result == {"status": "error", "error": "missing_metadata", "retry": False}
    stripe.PaymentLink.retrieve.assert_not_called()


def test_handle_checkout_completed_defaults_item_name_and_buyer_email(monkeypatch):
    """item_name defaults to 'Item' when absent; buyer_email is None when customer_details missing."""
    called_kwargs = {}

    def fake_fulfill_purchase(**kwargs):
        called_kwargs.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(webhooks, "fulfill_purchase", fake_fulfill_purchase)

    event = _session_event({
        "metadata": {"item_id": "item-4", "user_id": "user-4"},
        "customer_details": None,
    })

    result = webhooks.handle_checkout_completed(event)

    assert result == {"status": "success"}
    assert called_kwargs["item_name"] == "Item"
    assert called_kwargs["buyer_email"] is None


def test_handle_checkout_completed_amount_total_missing_defaults_to_zero(monkeypatch):
    """amount_total absent -> amount computed as 0 / 100 == 0.0, no ZeroDivisionError etc."""
    called_kwargs = {}

    def fake_fulfill_purchase(**kwargs):
        called_kwargs.update(kwargs)
        return {"status": "success"}

    monkeypatch.setattr(webhooks, "fulfill_purchase", fake_fulfill_purchase)

    event = _session_event({
        "metadata": {"item_id": "item-5", "user_id": "user-5"},
        "amount_total": None,
    })

    result = webhooks.handle_checkout_completed(event)

    assert result == {"status": "success"}
    assert called_kwargs["amount"] == 0.0


def test_handle_checkout_completed_returns_fulfill_purchase_result_verbatim(monkeypatch):
    """The route relies on whatever fulfill_purchase returns (e.g. a 'retry' flag) -
    handle_checkout_completed must pass it through unchanged."""
    fulfillment_result = {"status": "error", "error": "item_unavailable", "retry": True}
    monkeypatch.setattr(webhooks, "fulfill_purchase", lambda **kwargs: fulfillment_result)

    event = _session_event({
        "metadata": {"item_id": "item-6", "user_id": "user-6"},
    })

    result = webhooks.handle_checkout_completed(event)

    assert result is fulfillment_result
