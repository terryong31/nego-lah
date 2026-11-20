"""TDD regression tests for SPEC-116 (2026-11-20 White-Box Security Audit, SEC-16..SEC-25)."""

import io
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import stripe as real_stripe
from fastapi import HTTPException
from PIL import Image, ImageFilter

import domains.billing.fulfillment as fulfillment
import domains.identity.admin_auth as admin_auth
import domains.identity.admin_session as admin_session
import domains.identity.admin_users as admin_users
import domains.identity.auth_routes as auth_routes
import domains.identity.user_session as user_session
import domains.webhooks.routes as webhooks_module
from conftest import make_supabase_result
from core.cache import redis_client
from core.csrf import ADMIN_SCOPE, USER_SCOPE, generate_csrf_token
from core.env import ADMIN_COOKIE_NAME, USER_COOKIE_NAME
from core.images import normalize_image
from core.limiter import resolve_route_limit
from core.security import verify_turnstile
from domains.identity.user_session import _SESS_KEY, create_session, read_session, resolve_session
from domains.negotiation import context
from domains.negotiation.tools.negotiation import evaluate_offer


def _make_stripe_session(
    payment_status="paid",
    metadata=None,
    payment_intent="pi_123",
    amount_total=10000,
    customer_details=None,
    payment_link=None,
):
    payload = {
        "id": "cs_1",
        "object": "checkout.session",
        "payment_status": payment_status,
        "metadata": metadata if metadata is not None else {},
        "payment_intent": payment_intent,
        "amount_total": amount_total,
        "customer_details": customer_details,
    }
    if payment_link is not None:
        payload["payment_link"] = payment_link
    return real_stripe.checkout.Session.construct_from(payload, "sk_test_fixture")


def _make_supabase_session(user_id="user-1", access="access-1", refresh="refresh-1"):
    return SimpleNamespace(
        access_token=access,
        refresh_token=refresh,
        expires_at=int(time.time()) + 3600,
        user=SimpleNamespace(id=user_id, email="buyer@example.com", user_metadata={}),
    )


# ---------------------------------------------------------------------------
# SEC-16: POST /payment/confirm-payment payment-to-item swap & fail-closed
# ---------------------------------------------------------------------------


async def test_sec16_confirm_payment_rejects_missing_stripe_metadata_even_with_query_item_id(
    client, auth_user, fake_stripe, monkeypatch
):
    """Client-supplied item_id must NEVER stand in for missing Stripe metadata."""
    auth_user("buyer-1")
    session = _make_stripe_session(payment_status="paid", metadata={"user_id": "buyer-1"})
    fake_stripe.v1.checkout.sessions.retrieve.return_value = session
    fulfill_mock = MagicMock()
    monkeypatch.setattr(fulfillment, "fulfill_purchase", fulfill_mock)

    res = await client.post(
        "/payment/confirm-payment",
        params={"session_id": "cs_1", "item_id": "expensive-item-uuid"},
    )

    assert res.status_code == 400
    fulfill_mock.assert_not_called()


async def test_sec16_confirm_payment_rejects_missing_user_id_in_stripe_metadata(
    client, auth_user, fake_stripe, monkeypatch
):
    auth_user("buyer-1")
    session = _make_stripe_session(payment_status="paid", metadata={"item_id": "item-1"})
    fake_stripe.v1.checkout.sessions.retrieve.return_value = session
    fulfill_mock = MagicMock()
    monkeypatch.setattr(fulfillment, "fulfill_purchase", fulfill_mock)

    res = await client.post("/payment/confirm-payment", params={"session_id": "cs_1"})

    assert res.status_code == 400
    fulfill_mock.assert_not_called()


async def test_sec16_confirm_payment_resolves_payment_link_metadata_and_ignores_spoofed_query_item(
    client, auth_user, fake_stripe, fake_supabase, patch_supabase, monkeypatch
):
    """If a session lacks item_id metadata, resolve_session_metadata fetches PaymentLink metadata."""
    auth_user("buyer-1")
    session = _make_stripe_session(
        payment_status="paid",
        metadata={},
        payment_link="plink_123",
        amount_total=500,
    )
    fake_stripe.v1.checkout.sessions.retrieve.return_value = session
    fake_stripe.v1.payment_links.retrieve.return_value = real_stripe.PaymentLink.construct_from(
        {
            "id": "plink_123",
            "object": "payment_link",
            "metadata": {"item_id": "cheap-item", "user_id": "buyer-1", "item_name": "Cheap Sticker"},
        },
        "sk_test_fixture",
    )
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"id": "cheap-item", "name": "Cheap Sticker", "price": 5.0, "min_price": 5.0}]
    )
    patch_supabase("core.connector", admin=fake_supabase)

    captured = {}

    def fake_fulfill(**kwargs):
        captured.update(kwargs)
        return {"status": "fulfilled", "order_id": "ord-1"}

    monkeypatch.setattr(fulfillment, "fulfill_purchase", fake_fulfill)

    res = await client.post(
        "/payment/confirm-payment",
        params={"session_id": "cs_1", "item_id": "expensive-macbook"},
    )

    assert res.status_code == 200
    assert captured["item_id"] == "cheap-item"
    assert captured["user_id"] == "buyer-1"


async def test_sec16_confirm_payment_rejects_underpaid_amount_below_item_floor(
    client, auth_user, fake_stripe, fake_supabase, patch_supabase, monkeypatch
):
    auth_user("buyer-1")
    session = _make_stripe_session(
        payment_status="paid",
        metadata={"item_id": "item-1", "user_id": "buyer-1"},
        amount_total=500,  # RM5.00
    )
    fake_stripe.v1.checkout.sessions.retrieve.return_value = session
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"id": "item-1", "name": "MacBook", "price": 5000.0, "min_price": 4000.0}]
    )
    patch_supabase("core.connector", admin=fake_supabase)
    fulfill_mock = MagicMock()
    monkeypatch.setattr(fulfillment, "fulfill_purchase", fulfill_mock)

    res = await client.post("/payment/confirm-payment", params={"session_id": "cs_1"})

    assert res.status_code == 400
    fulfill_mock.assert_not_called()


# ---------------------------------------------------------------------------
# SEC-17: POST /auth/password/reset requires recovery session & is single-use
# ---------------------------------------------------------------------------


async def test_sec17_password_reset_rejects_ordinary_login_session(client, auth_user, monkeypatch):
    """A normal logged-in session must NOT bypass current_password via /auth/password/reset."""
    auth_user("user-1")
    fake_auth = MagicMock()
    monkeypatch.setattr(auth_routes, "new_user_client", lambda: fake_auth)

    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 3600)
    csrf = generate_csrf_token(sid, USER_SCOPE)

    res = await client.post(
        "/auth/password/reset",
        json={"new_password": "attacker-password-123"},
        cookies={USER_COOKIE_NAME: sid},
        headers={"X-CSRF-Token": csrf},
    )

    assert res.status_code == 403
    fake_auth.auth.update_user.assert_not_called()


async def test_sec17_recovery_callback_mints_single_use_recovery_session(client, auth_user, monkeypatch):
    auth_user("user-3")
    fake_auth = MagicMock()
    fake_auth.auth.verify_otp.return_value = SimpleNamespace(session=_make_supabase_session("user-3"))
    monkeypatch.setattr(auth_routes, "new_user_client", lambda: fake_auth)

    cb = await client.get("/auth/callback?token_hash=abc&type=recovery", follow_redirects=False)
    assert cb.status_code == 302
    raw_sid = next(c for c in cb.headers.get_list("set-cookie") if c.startswith(f"{USER_COOKIE_NAME}="))
    sid = raw_sid.split(";")[0].split("=", 1)[1]
    assert read_session(sid).get("is_recovery") is True

    csrf = generate_csrf_token(sid, USER_SCOPE)
    first = await client.post(
        "/auth/password/reset",
        json={"new_password": "new-strong-password"},
        cookies={USER_COOKIE_NAME: sid},
        headers={"X-CSRF-Token": csrf},
    )
    assert first.status_code == 200
    assert read_session(sid).get("is_recovery") is False

    second = await client.post(
        "/auth/password/reset",
        json={"new_password": "another-password"},
        cookies={USER_COOKIE_NAME: sid},
        headers={"X-CSRF-Token": csrf},
    )
    assert second.status_code == 403


async def test_sec17_signup_callback_session_is_not_a_recovery_session(client, monkeypatch):
    fake_auth = MagicMock()
    fake_auth.auth.verify_otp.return_value = SimpleNamespace(session=_make_supabase_session("user-3"))
    monkeypatch.setattr(auth_routes, "new_user_client", lambda: fake_auth)

    cb = await client.get("/auth/callback?token_hash=abc&type=signup", follow_redirects=False)
    raw_sid = next(c for c in cb.headers.get_list("set-cookie") if c.startswith(f"{USER_COOKIE_NAME}="))
    sid = raw_sid.split(";")[0].split("=", 1)[1]
    assert not read_session(sid).get("is_recovery")


# ---------------------------------------------------------------------------
# SEC-18: evaluate_offer server-side clamping & authoritative anchor
# ---------------------------------------------------------------------------


def test_sec18_evaluate_offer_clamps_extra_discount_percent_to_10(fake_supabase, patch_supabase):
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"id": "i", "price": 1000.0, "min_price": 500.0}]
    )
    patch_supabase("core.connector", admin=fake_supabase)
    context.set_context(user_id="buyer-1", item_id="i")

    # Even if prompt injection passes 100% discount, threshold clamps to 10% off (RM900),
    # so RM600 is countered, NOT accepted at floor.
    result = evaluate_offer.func(item_id="i", offered_price=600.0, extra_discount_percent=100.0)
    assert result.startswith("COUNTER:")
    assert redis_client.get("negotiated_price:buyer-1:i") != "600.0"


def test_sec18_evaluate_offer_ignores_llm_current_price_override(fake_supabase, patch_supabase):
    """LLM-supplied current_price=1 must not collapse anchor to min_price or leak floor."""
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"id": "i", "price": 1000.0, "min_price": 600.0}]
    )
    patch_supabase("core.connector", admin=fake_supabase)
    context.set_context(user_id="buyer-1", item_id="i")

    result = evaluate_offer.func(item_id="i", offered_price=600.0, current_price=1.0)
    assert result.startswith("COUNTER:")
    assert "RM900" in result


def test_sec18_evaluate_offer_rejects_non_finite_offer(fake_supabase, patch_supabase):
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"id": "i", "price": 1000.0, "min_price": 600.0}]
    )
    patch_supabase("core.connector", admin=fake_supabase)
    context.set_context(user_id="buyer-1", item_id="i")

    result = evaluate_offer.func(item_id="i", offered_price=float("nan"))
    assert "ERROR" in result or "invalid" in result.lower()


# ---------------------------------------------------------------------------
# SEC-19: URL scheme validation on tracking_url & avatar_url
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "data:text/html,<script>1</script>", "ftp://example.com"])
async def test_sec19_shipment_rejects_unsafe_tracking_url_scheme(
    client, admin_user, fake_supabase, patch_supabase, bad_url
):
    admin_user()
    patch_supabase("core.connector", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"id": "order-1", "buyer_id": "buyer-1", "status": "confirmed"}]
    )

    res = await client.put(
        "/admin/orders/order-1/shipment",
        json={"courier": "J&T Express", "tracking_number": "123", "tracking_url": bad_url},
    )
    assert res.status_code == 400


@pytest.mark.parametrize("bad_url", ["javascript:alert(1)", "data:text/html,hi", "vbscript:msgbox(1)"])
async def test_sec19_admin_profile_update_rejects_unsafe_avatar_url_scheme(
    client, admin_user, fake_supabase, patch_supabase, bad_url
):
    admin_user()
    patch_supabase("core.connector", admin=fake_supabase)

    res = await client.put(
        "/admin/users/target-user/profile",
        json={"avatar_url": bad_url},
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# SEC-20: EXIF/GPS metadata always stripped even when re-encoded image is larger
# ---------------------------------------------------------------------------


def test_sec20_normalize_image_strips_exif_even_when_reencoding_is_larger():
    """A heavily compressed JPEG with EXIF/GPS expands at quality=82; raw bytes must NOT pass through."""
    channels = [Image.effect_noise((300, 300), 64).filter(ImageFilter.GaussianBlur(2)) for _ in range(3)]
    img = Image.merge("RGB", channels)
    exif = img.getexif()
    exif[271] = "SecretGPSCamera"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=20, exif=exif)
    raw = buf.getvalue()
    assert b"SecretGPSCamera" in raw

    out, content_type, ext = normalize_image(raw)
    assert content_type == "image/jpeg"
    assert ext == "jpg"
    assert b"SecretGPSCamera" not in out


# ---------------------------------------------------------------------------
# SEC-21: Session revocation on admin delete/ban & refresh lock race
# ---------------------------------------------------------------------------


def test_sec21_refresh_lock_loser_returns_none_when_session_revoked_mid_wait(monkeypatch):
    """If the session is destroyed while another thread waits on the refresh lock, fail closed."""
    sid = create_session("user-1", "access-1", "refresh-1", int(time.time()) + 10)
    entered = threading.Event()

    def slow_refresh(_token):
        entered.wait(timeout=2)
        user_session.destroy_session(sid)
        raise Exception("revoked")

    client = MagicMock()
    client.auth.refresh_session.side_effect = slow_refresh
    monkeypatch.setattr(user_session, "new_user_client", lambda: client)

    results = []

    def loser():
        time.sleep(0.05)
        entered.set()
        results.append(resolve_session(sid))

    t1 = threading.Thread(target=lambda: resolve_session(sid))
    t2 = threading.Thread(target=loser)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert results == [None]


async def test_sec21_admin_ban_and_delete_revoke_active_redis_sessions(
    client, admin_user, fake_supabase, patch_supabase, monkeypatch
):
    admin_user(user_id="admin-1")
    patch_supabase("core.connector", admin=fake_supabase)
    monkeypatch.setattr(admin_session, "_is_admin_user", MagicMock(return_value=False))
    monkeypatch.setattr(admin_users, "write_audit", MagicMock())
    fake_supabase.auth.admin.get_user_by_id.return_value = SimpleNamespace(
        user=SimpleNamespace(id="victim", app_metadata={})
    )

    sid_ban = create_session("victim", "a", "r", int(time.time()) + 3600)
    res_ban = await client.put("/admin/users/victim/ban", json={"is_banned": True})
    assert res_ban.status_code == 200
    assert redis_client.get(f"{_SESS_KEY}{sid_ban}") is None

    sid_del = create_session("victim-del", "a", "r", int(time.time()) + 3600)
    res_del = await client.delete("/admin/users/victim-del")
    assert res_del.status_code == 200
    assert redis_client.get(f"{_SESS_KEY}{sid_del}") is None


# ---------------------------------------------------------------------------
# SEC-22: POST /admin/auth/logout enforces CSRF token
# ---------------------------------------------------------------------------


async def test_sec22_admin_logout_requires_csrf_token_when_cookie_present(client, admin_user, monkeypatch):
    admin_user(user_id="admin-1")
    monkeypatch.setattr(admin_auth, "clear_session", MagicMock())
    monkeypatch.setattr(admin_auth, "write_audit", MagicMock())

    sid = "admin-logout-sid"
    csrf = generate_csrf_token(sid, ADMIN_SCOPE)
    client.cookies.set(ADMIN_COOKIE_NAME, sid)

    # Missing CSRF header -> 403
    missing = await client.post("/admin/auth/logout")
    assert missing.status_code == 403

    # Valid CSRF header -> 200
    valid = await client.post("/admin/auth/logout", headers={"X-CSRF-Token": csrf})
    assert valid.status_code == 200


# ---------------------------------------------------------------------------
# SEC-23: Rate limits, pagination bounds & webhook validation
# ---------------------------------------------------------------------------


def test_sec23_auth_routes_have_dedicated_ip_rate_limit_buckets():
    assert resolve_route_limit("/auth/login")[0] == "auth"
    assert resolve_route_limit("/auth/register")[0] == "auth"
    assert resolve_route_limit("/admin/auth/login")[0] == "admin_auth"


async def test_sec23_register_and_forgot_password_are_rate_limited(client, monkeypatch):
    fake_auth = MagicMock()
    fake_auth.auth.sign_up.return_value = SimpleNamespace(session=None)
    fake_auth.auth.reset_password_email.return_value = None
    monkeypatch.setattr(auth_routes, "new_user_client", lambda: fake_auth)

    for _ in range(auth_routes._REGISTER_MAX):
        res = await client.post("/auth/register", json={"email": "spam@example.com", "password": "password123"})
        assert res.status_code == 200
    res_over = await client.post("/auth/register", json={"email": "spam@example.com", "password": "password123"})
    assert res_over.status_code == 429

    for _ in range(auth_routes._FORGOT_MAX):
        res = await client.post("/auth/password/forgot", json={"email": "reset@example.com"})
        assert res.status_code == 200
    res_forgot_over = await client.post("/auth/password/forgot", json={"email": "reset@example.com"})
    assert res_forgot_over.status_code == 429


async def test_sec23_pagination_limits_are_bounded(client, auth_user):
    auth_user("user-1")
    assert (await client.get("/items/featured?limit=0")).status_code == 422
    assert (await client.get("/items/featured?limit=500")).status_code == 422
    assert (await client.get("/chat/history/user-1?limit=0")).status_code == 422
    assert (await client.get("/chat/history/user-1?limit=500")).status_code == 422
    assert (await client.get("/chat/history/user-1?offset=-1")).status_code == 422


async def test_sec23_resend_webhook_rejects_malformed_email_id(client, monkeypatch):
    class FakeWebhook:
        def __init__(self, _secret):
            pass

        def verify(self, _payload, _headers):
            return None

    monkeypatch.setattr(webhooks_module, "Webhook", FakeWebhook)
    body = json.dumps(
        {
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Hi",
                "email_id": "../../admin/secrets",
                "to": ["support@example.com"],
            },
        }
    ).encode()
    res = await client.post("/webhooks/resend", content=body)
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# SEC-24: Turnstile hostname fail-closed & same-buyer double payment refund
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sec24_turnstile_fails_closed_when_hostname_missing_and_allowlist_set(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "real-prod-secret")
    monkeypatch.setenv("TURNSTILE_HOSTNAMES", "negolah.my")

    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {"success": True}  # no hostname field

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        with pytest.raises(HTTPException) as exc:
            await verify_turnstile(x_turnstile_token="valid-token")
        assert exc.value.status_code == 403


def test_sec24_same_buyer_second_distinct_payment_intent_is_auto_refunded(fake_stripe, patch_supabase, fake_supabase):
    patch_supabase("domains.billing.fulfillment", admin=fake_supabase)

    orders_mock = MagicMock()
    items_mock = MagicMock()
    fake_supabase.table.side_effect = lambda name: {"orders": orders_mock, "items": items_mock}[name]

    # New order inserted for pi_second (distinct PaymentIntent).
    orders_mock.insert.return_value.execute.return_value = make_supabase_result([{"id": "order-2"}])
    # Atomic item claim fails because item is already sold to buyer-1.
    items_mock.update.return_value.eq.return_value.eq.return_value.execute.return_value = make_supabase_result([])
    items_mock.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"status": "sold", "buyer_id": "buyer-1"}]
    )
    # Existing winning order for this item/buyer carries a DIFFERENT PaymentIntent (pi_first).
    (
        orders_mock.select.return_value.eq.return_value.eq.return_value.neq.return_value.neq.return_value.limit.return_value.execute.return_value
    ) = make_supabase_result([{"id": "order-1", "stripe_payment_id": "pi_first"}])

    res = fulfillment.fulfill_purchase(
        item_id="item-1",
        user_id="buyer-1",
        payment_intent="pi_second",
        amount=100.0,
    )

    assert res["status"] == "race_lost"
    assert res["refunded"] is True
    fake_stripe.v1.refunds.create.assert_called_once_with(
        params={"payment_intent": "pi_second", "reason": "duplicate"},
        options={"idempotency_key": "auto_refund_pi_second"},
    )


async def test_sec23_resend_webhook_rejects_oversized_raw_email_download(client, monkeypatch):
    class FakeWebhook:
        def __init__(self, _secret):
            pass

        def verify(self, _payload, _headers):
            return None

    monkeypatch.setattr(webhooks_module, "Webhook", FakeWebhook)
    monkeypatch.setattr(webhooks_module, "MAX_INBOUND_RAW_BYTES", 32)

    fetch_resp = MagicMock()
    fetch_resp.raise_for_status.return_value = None
    fetch_resp.json.return_value = {
        "html": "<p>hi</p>",
        "text": "hi",
        "attachments": [{"content_disposition": "attachment", "filename": "huge.bin"}],
        "raw": {"download_url": "https://api.resend.com/raw/email_big"},
    }
    raw_resp = MagicMock()
    raw_resp.raise_for_status.return_value = None
    raw_resp.headers = {"content-length": "64"}
    raw_resp.content = b"x" * 64

    responses = [fetch_resp, raw_resp]
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=lambda *_a, **_kw: responses.pop(0))
    fake_client.post = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=fake_client)
    cm.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(webhooks_module.httpx, "AsyncClient", MagicMock(return_value=cm))

    body = json.dumps(
        {
            "type": "email.received",
            "data": {
                "from": "sender@example.com",
                "subject": "Huge",
                "email_id": "email_big",
                "to": ["support@example.com"],
            },
        }
    ).encode()
    res = await client.post("/webhooks/resend", content=body)
    assert res.status_code == 413
    fake_client.post.assert_not_awaited()


# ---------------------------------------------------------------------------
# SEC-25: Generic error messages without internal exception text
# ---------------------------------------------------------------------------


async def test_sec25_admin_analyze_image_and_cleanup_do_not_leak_exception_text(client, admin_user, monkeypatch):
    import console.admin_listings as admin_listings
    import domains.billing.payment_state as payment_state

    admin_user()

    def boom_cleanup():
        raise RuntimeError("secret-stripe-key-leak")

    monkeypatch.setattr(payment_state, "cleanup_expired_payments", boom_cleanup)
    cleanup_res = await client.post("/admin/cleanup-stripe")
    assert cleanup_res.status_code == 200
    assert cleanup_res.json() == {"error": "Stripe cleanup failed"}
    assert "secret-stripe-key-leak" not in cleanup_res.text

    async def boom_encode(_images):
        raise RuntimeError("internal-vision-traceback")

    monkeypatch.setattr(admin_listings, "_encode_images", boom_encode)
    analyze_res = await client.post(
        "/admin/analyze-image",
        files=[("images", ("a.jpg", b"abc", "image/jpeg"))],
    )
    assert analyze_res.status_code == 500
    assert analyze_res.json() == {"detail": "Failed to analyze image"}
    assert "internal-vision-traceback" not in analyze_res.text
