"""Recording postage, and the three notifications that follow (SPEC-057).

The seller records a courier and a tracking number once; that single act has to
reach the buyer by email, in the live chat, and through the notification bell.
The write is the part that must not be lost, so it happens first and the
notifications are individually best-effort behind it — an order that shipped but
whose email bounced is a recoverable annoyance, an email sent for a shipment
that was never recorded is a lie.

Mocking seams (see conftest.py): `routes/admin/orders.py` imports
`admin_supabase` lazily inside each handler, so `patch_supabase("connector",
admin=...)` takes effect at call time; `write_audit` needs
`patch_supabase("admin_session", ...)` as well.
"""

from unittest.mock import MagicMock

import pytest

from conftest import make_supabase_result


@pytest.fixture
def admin_supabase(patch_supabase, fake_supabase):
    patch_supabase("connector", admin=fake_supabase)
    patch_supabase("admin_session", admin=fake_supabase)
    return fake_supabase


@pytest.fixture
def csrf(client):
    from cache import redis_client
    from env import ADMIN_SESSION_TTL

    sid, value = "sid-ship", "csrf-ship"
    redis_client.setex(f"csrf:{sid}", ADMIN_SESSION_TTL, value)
    client.cookies.set("admin_sid", sid)
    return {"X-CSRF-Token": value}


@pytest.fixture
def notifications(monkeypatch):
    """Capture the three fan-out calls without performing any of them."""
    sent = {"emails": [], "chats": []}

    monkeypatch.setattr(
        "services.email_service.send_shipment_notice",
        lambda email, order, delivered=False: sent["emails"].append((email, order, delivered)) or True,
    )
    monkeypatch.setattr(
        "payment.fulfillment.broadcast_to_chat",
        lambda user_id, content, role="ai", source="ai": sent["chats"].append((user_id, content, source)),
    )
    monkeypatch.setattr("payment.buyer.account_email", lambda _uid: "buyer@example.com")
    return sent


ORDER = {
    "id": "order-1",
    "buyer_id": "buyer-1",
    "item_name": "Casio VX-4",
    "status": "confirmed",
}


def _order_lookup(fake_supabase, order=None):
    (
        fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value
    ) = make_supabase_result([order] if order else [])


def _order_update(fake_supabase, order):
    (
        fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value
    ) = make_supabase_result([order])


async def _ship(client, headers, **body):
    payload = {"courier": "J&T Express", "tracking_number": "630123456789", **body}
    return await client.put("/admin/orders/order-1/shipment", json=payload, headers=headers)


# ---------------------------------------------------------------------------
# The write
# ---------------------------------------------------------------------------

async def test_recording_postage_writes_tracking_and_moves_the_order_to_shipped(
    client, admin_user, admin_supabase, csrf, notifications
):
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, {**ORDER, "status": "shipped"})

    res = await _ship(client, csrf)

    assert res.status_code == 200
    written = admin_supabase.table.return_value.update.call_args[0][0]
    assert written["courier"] == "J&T Express"
    assert written["tracking_number"] == "630123456789"
    assert written["status"] == "shipped"
    assert written["shipped_at"]


async def test_the_tracking_url_is_derived_from_the_courier(
    client, admin_user, admin_supabase, csrf, notifications
):
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, ORDER)

    await _ship(client, csrf)

    written = admin_supabase.table.return_value.update.call_args[0][0]
    assert "630123456789" in written["tracking_url"]


async def test_an_explicit_tracking_url_wins_over_the_derived_one(
    client, admin_user, admin_supabase, csrf, notifications
):
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, ORDER)

    await _ship(client, csrf, tracking_url="https://tracking.example.test/xyz")

    written = admin_supabase.table.return_value.update.call_args[0][0]
    assert written["tracking_url"] == "https://tracking.example.test/xyz"


async def test_an_unknown_courier_is_recorded_without_a_url(
    client, admin_user, admin_supabase, csrf, notifications
):
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, ORDER)

    await _ship(client, csrf, courier="Some Local Bike Guy")

    written = admin_supabase.table.return_value.update.call_args[0][0]
    assert written["courier"] == "Some Local Bike Guy"
    assert written["tracking_url"] is None


async def test_the_courier_name_is_normalised_before_it_is_stored(
    client, admin_user, admin_supabase, csrf, notifications
):
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, ORDER)

    await _ship(client, csrf, courier="  jnt  ")

    assert admin_supabase.table.return_value.update.call_args[0][0]["courier"] == "J&T Express"


async def test_it_writes_an_audit_entry(client, admin_user, admin_supabase, csrf, notifications, monkeypatch):
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, ORDER)
    audited = []
    monkeypatch.setattr("routes.admin.orders.write_audit", lambda *a, **k: audited.append(a))

    await _ship(client, csrf)

    assert audited and audited[0][2] == "order.shipment"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("headers", [{}, {"X-CSRF-Token": "forged"}], ids=["absent", "forged"])
async def test_recording_postage_requires_a_csrf_token(
    client, admin_user, admin_supabase, csrf, notifications, headers
):
    """`csrf` is requested so the admin_sid cookie exists — without a session
    cookie `verify_csrf_token` defers to `verify_admin` and this would pass for
    the wrong reason."""
    admin_user()
    _order_lookup(admin_supabase, ORDER)

    res = await _ship(client, headers)

    assert res.status_code == 403
    admin_supabase.table.return_value.update.assert_not_called()
    assert notifications["emails"] == []


@pytest.mark.parametrize("bad", [{"courier": "   "}, {"tracking_number": ""}, {"tracking_number": "  "}])
async def test_a_blank_courier_or_tracking_number_is_refused(
    client, admin_user, admin_supabase, csrf, notifications, bad
):
    admin_user()
    _order_lookup(admin_supabase, ORDER)

    res = await _ship(client, csrf, **bad)

    assert res.status_code == 400
    admin_supabase.table.return_value.update.assert_not_called()
    assert notifications["emails"] == []


async def test_an_unknown_order_is_a_404(client, admin_user, admin_supabase, csrf, notifications):
    admin_user()
    _order_lookup(admin_supabase, None)

    res = await _ship(client, csrf)

    assert res.status_code == 404
    assert notifications["emails"] == []


# ---------------------------------------------------------------------------
# The fan-out
# ---------------------------------------------------------------------------

async def test_the_buyer_is_told_by_email_and_in_the_chat(
    client, admin_user, admin_supabase, csrf, notifications
):
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, {**ORDER, "courier": "J&T Express", "tracking_number": "630123456789"})

    res = await _ship(client, csrf)

    assert res.json()["notified"] == {"email": True, "chat": True}
    assert len(notifications["emails"]) == 1
    assert notifications["emails"][0][0] == "buyer@example.com"

    assert len(notifications["chats"]) == 1
    user_id, content, source = notifications["chats"][0]
    assert user_id == "buyer-1"
    assert "630123456789" in content
    # Posted as the seller's own voice so it renders like any other AI message
    # and rings the buyer's notification bell (broadcast_to_chat skips those for
    # source="human"/"system").
    assert source == "ai"


async def test_notify_false_records_the_shipment_silently(
    client, admin_user, admin_supabase, csrf, notifications
):
    """For fixing a typo in a shipment the buyer has already been told about."""
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, ORDER)

    res = await _ship(client, csrf, notify=False)

    assert res.status_code == 200
    assert notifications["emails"] == []
    assert notifications["chats"] == []
    assert res.json()["notified"] == {"email": False, "chat": False}


async def test_a_failing_email_does_not_lose_the_shipment(
    client, admin_user, admin_supabase, csrf, notifications, monkeypatch
):
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, ORDER)
    monkeypatch.setattr(
        "services.email_service.send_shipment_notice",
        MagicMock(side_effect=Exception("resend is down")),
    )

    res = await _ship(client, csrf)

    assert res.status_code == 200
    assert res.json()["notified"]["email"] is False
    # The chat message is a separate best-effort step and still goes out.
    assert res.json()["notified"]["chat"] is True
    admin_supabase.table.return_value.update.assert_called()


async def test_a_failing_broadcast_does_not_lose_the_shipment(
    client, admin_user, admin_supabase, csrf, notifications, monkeypatch
):
    admin_user()
    _order_lookup(admin_supabase, ORDER)
    _order_update(admin_supabase, ORDER)
    monkeypatch.setattr(
        "payment.fulfillment.broadcast_to_chat",
        MagicMock(side_effect=Exception("realtime is down")),
    )

    res = await _ship(client, csrf)

    assert res.status_code == 200
    assert res.json()["notified"] == {"email": True, "chat": False}


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

async def test_marking_an_order_delivered_stamps_the_time_and_notifies(
    client, admin_user, admin_supabase, csrf, notifications
):
    admin_user()
    _order_lookup(admin_supabase, {**ORDER, "status": "shipped"})
    _order_update(admin_supabase, {**ORDER, "status": "delivered"})

    res = await client.put(
        "/admin/orders/order-1/status", json={"status": "delivered"}, headers=csrf
    )

    assert res.status_code == 200
    assert admin_supabase.table.return_value.update.call_args[0][0]["delivered_at"]
    assert len(notifications["emails"]) == 1
    assert notifications["emails"][0][2] is True, "the notice must be worded as a delivery"


async def test_other_status_changes_do_not_notify_the_buyer(
    client, admin_user, admin_supabase, csrf, notifications
):
    admin_user()
    _order_lookup(admin_supabase, {**ORDER, "status": "delivered"})
    _order_update(admin_supabase, {**ORDER, "status": "shipped"})

    res = await client.put(
        "/admin/orders/order-1/status", json={"status": "shipped"}, headers=csrf
    )

    assert res.status_code == 200
    assert notifications["emails"] == []
    assert notifications["chats"] == []


async def test_re_marking_an_already_delivered_order_does_not_notify_twice(
    client, admin_user, admin_supabase, csrf, notifications
):
    admin_user()
    _order_lookup(admin_supabase, {**ORDER, "status": "delivered"})
    _order_update(admin_supabase, {**ORDER, "status": "delivered"})

    await client.put("/admin/orders/order-1/status", json={"status": "delivered"}, headers=csrf)

    assert notifications["emails"] == []
