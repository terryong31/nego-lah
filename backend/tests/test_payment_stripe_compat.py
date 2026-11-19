"""Tests for payment/stripe_compat.py::stripe_get.

The regression this guards: stripe-python 15 made `StripeObject` stop being a
dict subclass, so `.get()` on any Stripe resource raises AttributeError. Every
field read in the webhook and confirm-payment paths goes through `stripe_get`,
so these assert both shapes (real Stripe resources and plain dicts).
"""

import stripe

from domains.billing.stripe_compat import stripe_get


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


# ---------------------------------------------------------------------------
# SPEC-114: modern StripeClient (.v1 namespace) + SDK TypedDict contracts
# ---------------------------------------------------------------------------


def _stripe_production_files():
    """Every backend module that should follow modern StripeClient v1 usage."""
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    skip = {".venv", "htmlcov", "__pycache__", "migrations", "tests", "evals"}
    files = []
    for path in sorted(backend.rglob("*.py")):
        parts = path.relative_to(backend).parts
        if any(p in skip for p in parts) or path.name == "conftest.py":
            continue
        if parts[0] == "scripts" and path.name != "check_fulfillment_anomalies.py":
            continue
        files.append(path)
    return files


def test_get_stripe_client_returns_cached_stripe_client(monkeypatch):
    from core import stripe_client

    monkeypatch.setattr(stripe_client, "_client", None)
    monkeypatch.setattr("core.env.STRIPE_API_KEY", "sk_test_spec114")

    first = stripe_client.get_stripe_client()
    second = stripe_client.get_stripe_client()

    assert isinstance(first, stripe.StripeClient)
    assert first is second


def test_get_stripe_client_survives_missing_api_key(monkeypatch):
    from core import stripe_client

    monkeypatch.setattr(stripe_client, "_client", None)
    monkeypatch.setattr("core.env.STRIPE_API_KEY", None)

    client = stripe_client.get_stripe_client()
    assert isinstance(client, stripe.StripeClient)


def test_no_deprecated_stripe_syntax_in_backend():
    """SPEC-114: prohibit global stripe.api_key, stripe.error.*, legacy static
    resource classes, and top-level StripeClient.<service> without .v1."""
    import ast

    legacy_resources = {
        "Product",
        "Price",
        "PaymentLink",
        "Refund",
        "Webhook",
        "PaymentIntent",
        "Charge",
        "Customer",
        "Subscription",
    }
    v1_services = {
        "checkout",
        "refunds",
        "products",
        "prices",
        "payment_links",
        "payment_intents",
        "charges",
    }

    violations: list[str] = []
    for path in _stripe_production_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        client_vars: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                if (isinstance(func, ast.Name) and func.id in {"get_stripe_client", "StripeClient"}) or (
                    isinstance(func, ast.Attribute) and func.attr == "StripeClient"
                ):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            client_vars.add(target.id)

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "stripe.error":
                violations.append(f"{path.name}:{node.lineno} from stripe.error import ...")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "stripe":
                if node.attr == "api_key":
                    violations.append(f"{path.name}:{node.lineno} stripe.api_key")
                elif node.attr == "error":
                    violations.append(f"{path.name}:{node.lineno} stripe.error.*")
                elif node.attr in legacy_resources:
                    violations.append(f"{path.name}:{node.lineno} stripe.{node.attr}")
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "Session"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "checkout"
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "stripe"
            ):
                violations.append(f"{path.name}:{node.lineno} stripe.checkout.Session")
            if isinstance(node, ast.Attribute) and node.attr in v1_services:
                base = node.value
                is_direct_factory = (
                    isinstance(base, ast.Call)
                    and isinstance(base.func, ast.Name)
                    and base.func.id == "get_stripe_client"
                )
                is_client_var = isinstance(base, ast.Name) and base.id in client_vars
                if is_direct_factory or is_client_var:
                    violations.append(f"{path.name}:{node.lineno} missing .v1 before .{node.attr}")

    assert not violations, f"Deprecated Stripe SDK usage found: {violations}"


def test_stripe_params_and_options_match_installed_sdk_schema(fake_stripe, monkeypatch, patch_supabase, fake_supabase):
    """Contract guard: every params/options key sent by backend Stripe calls
    must exist in the installed stripe SDK's TypedDicts (with RequestOptions
    kept in `options`, never mixed into `params`)."""
    from unittest.mock import MagicMock

    from stripe._request_options import RequestOptions
    from stripe.params import (
        PaymentLinkCreateParams,
        PaymentLinkUpdateParams,
        PriceCreateParams,
        ProductCreateParams,
        ProductUpdateParams,
        RefundCreateParams,
    )
    from stripe.params.checkout import SessionCreateParams

    from domains.billing import fulfillment, payment_state, refunds
    from domains.billing.pay import create_checkout_session
    from domains.negotiation import context
    from domains.negotiation.tools.payment import create_checkout_link

    request_option_keys = set(RequestOptions.__annotations__.keys())

    def _allowed_params(typed_dict_cls) -> set[str]:
        return set(typed_dict_cls.__annotations__.keys()) - request_option_keys

    # 1. Checkout session (Buy Now)
    fake_stripe.v1.checkout.sessions.create.return_value = MagicMock(url="https://checkout.stripe.com/c/pay/cs_test")
    create_checkout_session(
        item_name="Camera",
        price_cents=15000,
        item_id="item-1",
        user_id="user-1",
        customer_email="buyer@example.com",
    )
    session_params = fake_stripe.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert set(session_params.keys()) <= _allowed_params(SessionCreateParams)
    assert "payment_method_types" not in session_params

    # 2. Agent create_checkout_link (Product -> Price -> PaymentLink)
    patch_supabase("core.connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[{"id": "item-1", "name": "Camera", "price": 150.0, "min_price": 100.0, "status": "available"}]
    )
    monkeypatch.setattr("domains.billing.pricing.active_negotiated_price", lambda uid, iid: 120.0)
    fake_stripe.v1.products.create.return_value = MagicMock(id="prod_1")
    fake_stripe.v1.prices.create.return_value = MagicMock(id="price_1")
    fake_stripe.v1.payment_links.create.return_value = MagicMock(id="pl_1", url="https://buy.stripe.com/test")

    context.set_context(user_id="user-1", item_id="item-1")
    try:
        create_checkout_link.func(item_id="item-1", agreed_price=120.0)
    finally:
        context.set_context(user_id=None, item_id=None)

    assert set(fake_stripe.v1.products.create.call_args.kwargs["params"].keys()) <= _allowed_params(ProductCreateParams)
    assert set(fake_stripe.v1.prices.create.call_args.kwargs["params"].keys()) <= _allowed_params(PriceCreateParams)
    assert set(fake_stripe.v1.payment_links.create.call_args.kwargs["params"].keys()) <= _allowed_params(
        PaymentLinkCreateParams
    )

    # 3. PaymentLink / Product updates during cleanup (uses the pending payment just stored in Redis)
    payment_state.delete_pending_payment("user-1", "item-1", cleanup_stripe=True)
    assert set(fake_stripe.v1.payment_links.update.call_args.kwargs["params"].keys()) <= _allowed_params(
        PaymentLinkUpdateParams
    )
    assert set(fake_stripe.v1.products.update.call_args.kwargs["params"].keys()) <= _allowed_params(ProductUpdateParams)

    # 4. Auto-refund and admin refund
    fulfillment._refund("pi_123", reason="duplicate")
    refund_call = fake_stripe.v1.refunds.create.call_args
    assert set(refund_call.kwargs["params"].keys()) <= _allowed_params(RefundCreateParams)
    assert set(refund_call.kwargs["options"].keys()) <= request_option_keys

    patch_supabase("domains.billing.refunds", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = (
        MagicMock(data=[{"status": "completed", "stripe_payment_id": "pi_456", "amount": 120}])
    )
    monkeypatch.setattr("core.cache.invalidate_item_cache", lambda item_id=None: None)
    fake_stripe.v1.refunds.create.return_value = MagicMock(id="re_1")
    refunds.process_refund("item-1", reason="requested_by_customer")
    admin_refund_call = fake_stripe.v1.refunds.create.call_args
    assert set(admin_refund_call.kwargs["params"].keys()) <= _allowed_params(RefundCreateParams)
    assert set(admin_refund_call.kwargs["options"].keys()) <= request_option_keys
