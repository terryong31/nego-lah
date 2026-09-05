"""Tests for payment/stripe_compat.py::stripe_get.

The regression this guards: stripe-python 15 made `StripeObject` stop being a
dict subclass, so `.get()` on any Stripe resource raises AttributeError. Every
field read in the webhook and confirm-payment paths goes through `stripe_get`,
so these assert both shapes (real Stripe resources and plain dicts).
"""

import stripe

from payment.stripe_compat import stripe_get


def _session(payload):
    return stripe.checkout.Session.construct_from(
        {"id": "cs_1", "object": "checkout.session", **payload}, "sk_test_fixture"
    )


def test_reads_a_field_off_a_real_stripe_object():
    session = _session({"payment_status": "paid", "amount_total": 10000})

    assert stripe_get(session, "payment_status") == "paid"
    assert stripe_get(session, "amount_total") == 10000


def test_stripe_objects_still_reject_the_dict_api_this_helper_replaces():
    """Guards the premise: if a future SDK restores `.get()`, this test tells us."""
    session = _session({"payment_status": "paid"})

    try:
        session.get("payment_status")
    except AttributeError:
        pass
    else:
        raise AssertionError("StripeObject unexpectedly supports .get() again")


def test_missing_field_on_a_stripe_object_returns_the_default():
    session = _session({"payment_status": "paid"})

    assert stripe_get(session, "payment_link") is None
    assert stripe_get(session, "payment_link", "fallback") == "fallback"


def test_nested_stripe_objects_are_readable_by_chaining():
    session = _session({"customer_details": {"email": "buyer@example.com"}})

    assert stripe_get(stripe_get(session, "customer_details"), "email") == "buyer@example.com"


def test_none_short_circuits_to_the_default():
    """Chaining over an absent nested resource must not raise."""
    session = _session({})

    assert stripe_get(stripe_get(session, "customer_details"), "email") is None
    assert stripe_get(None, "anything", "fallback") == "fallback"


def test_plain_dicts_keep_working():
    """Webhook payloads and cached metadata reach these paths as dicts."""
    assert stripe_get({"item_id": "item-1"}, "item_id") == "item-1"
    assert stripe_get({}, "item_id") is None
    assert stripe_get({}, "item_id", "fallback") == "fallback"


def test_an_explicit_null_field_reads_as_none_not_the_default():
    """Matches dict.get semantics: a present-but-null field is None."""
    assert stripe_get({"metadata": None}, "metadata", {}) is None
    assert stripe_get(_session({"payment_intent": None}), "payment_intent", "fallback") is None


def test_unsubscriptable_objects_fall_back_to_the_default_rather_than_raising():
    assert stripe_get(object(), "item_id", "fallback") == "fallback"
    assert stripe_get(42, "item_id") is None
