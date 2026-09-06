"""
Tests for the admin router -- Stripe cleanup, Orders CRUD, AI image analysis,
market valuation, dashboard summary, and Items CRUD (admin-only endpoints).

NOTE: auth/users/chats admin endpoints are covered by a different test file --
this file intentionally only exercises: /admin/cleanup-stripe, /admin/orders*,
/admin/analyze-image, /admin/market-valuation, /admin/summary, /admin/items*.

Mocking seam notes (see conftest.py docstring for the general rules):
- Every route in this file lives under the `protected` router
  (`Depends(verify_admin)`), so every test uses the `admin_user` fixture to
  bypass that dependency.
- the routes/admin/* modules do a *lazy* `from connector import admin_supabase` inside
  each function body for its own Supabase calls, so `patch_supabase("connector",
  admin=...)` takes effect at call time.
- `write_audit` (called on every successful mutation) lives in admin_session.py,
  which does an *eager* `from connector import admin_supabase` at module import
  time -- patching `connector.admin_supabase` alone does NOT affect it. We must
  also `patch_supabase("admin_session", admin=...)` (see test_admin_session.py's
  own tests for write_audit, which establish this same pattern) or a real
  network call would be attempted against the fake Supabase URL. The local
  `admin_supabase` fixture below patches both in one place.
- `/admin/cleanup-stripe` does a lazy `from payment.payment_state import
  cleanup_expired_payments` -- monkeypatch the function on the `payment.payment_state`
  module so the lazy import re-resolves to our fake at call time.
- `/admin/analyze-image` and `/admin/market-valuation` use the already-constructed
  singleton objects `agent.tools.image_analyzer.image_analyzer` and
  `agent.tools.market_price.market_service` -- we monkeypatch the `.analyze` /
  `.get_market_valuation` *methods* directly on those objects (same object
  identity regardless of the lazy import inside the route).
- `/admin/items` (create/update/delete) just delegate to `items.upload_item`
  (async) / `items.update_item` (sync) / `items.delete_item` (sync), imported
  lazily inside the route body -- monkeypatch those names directly on the
  `items` module.
"""

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import agent.tools.image_analyzer as image_analyzer_module
import agent.tools.listing_pipeline as listing_pipeline_module
import agent.tools.market_price as market_price_module
import items as items_module
import payment.payment_state as payment_state_module
from conftest import make_supabase_result

# ---------------------------------------------------------------------------
# Local composite fixture: patches BOTH connector.admin_supabase (used by
# the routes/admin/* modules' own lazy imports) and admin_session.admin_supabase (used
# by write_audit) with the same fake, since a successful mutation touches both.
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_supabase(patch_supabase, fake_supabase):
    patch_supabase("connector", admin=fake_supabase)
    patch_supabase("admin_session", admin=fake_supabase)
    return fake_supabase


# ---------------------------------------------------------------------------
# POST /admin/cleanup-stripe
# ---------------------------------------------------------------------------

async def test_cleanup_stripe_success(client, admin_user, monkeypatch):
    admin_user()
    monkeypatch.setattr(payment_state_module, "cleanup_expired_payments", lambda: 3)

    response = await client.post("/admin/cleanup-stripe")

    assert response.status_code == 200
    assert response.json() == {"message": "Cleaned up 3 expired payment links"}


async def test_cleanup_stripe_exception_returns_error_dict(client, admin_user, monkeypatch):
    admin_user()

    def _boom():
        raise RuntimeError("stripe unreachable")

    monkeypatch.setattr(payment_state_module, "cleanup_expired_payments", _boom)

    response = await client.post("/admin/cleanup-stripe")

    # The route catches the exception itself and returns a 200 with an "error"
    # key rather than raising an HTTPException -- documenting current behavior.
    assert response.status_code == 200
    assert response.json() == {"error": "stripe unreachable"}


# ---------------------------------------------------------------------------
# GET /admin/orders
# ---------------------------------------------------------------------------

async def test_get_all_orders_success_with_buyer_enrichment(client, admin_user, admin_supabase):
    admin_user()
    orders_data = [
        {"id": "o1", "buyer_id": "u1", "amount": 100},   # metadata name, no profile override
        {"id": "o2", "buyer_id": "u2", "amount": 50},    # profile override wins
        {"id": "o3", "buyer_id": "ghost", "amount": 25}, # buyer_id not found in auth users
        {"id": "o4", "buyer_id": None, "amount": 10},    # no buyer at all
    ]
    admin_supabase.table.return_value.select.return_value.order.return_value.execute.return_value = (
        make_supabase_result(orders_data)
    )
    users_response = [
        SimpleNamespace(id="u1", email="alice@example.com", user_metadata={"display_name": "Alice"}),
        SimpleNamespace(id="u2", email="bob@example.com", user_metadata={}),
    ]
    admin_supabase.auth.admin.list_users.return_value = users_response
    admin_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result(
        [{"id": "u2", "display_name": "Bobby P."}]
    )

    response = await client.get("/admin/orders")

    assert response.status_code == 200
    body = response.json()
    by_id = {o["id"]: o for o in body["orders"]}
    assert by_id["o1"]["buyer_email"] == "alice@example.com"
    assert by_id["o1"]["buyer_name"] == "Alice"
    assert by_id["o2"]["buyer_email"] == "bob@example.com"
    assert by_id["o2"]["buyer_name"] == "Bobby P."  # profile display_name overrides metadata
    assert by_id["o3"]["buyer_email"] == "Unknown Email"
    assert by_id["o3"]["buyer_name"] == "Unknown User"
    assert "buyer_email" not in by_id["o4"]
    assert body["stats"]["total_orders"] == 4
    assert body["stats"]["total_sales"] == 185


async def test_get_all_orders_enrichment_exception_still_returns_orders(client, admin_user, admin_supabase):
    admin_user()
    orders_data = [{"id": "o1", "buyer_id": "u1", "amount": 100}]
    admin_supabase.table.return_value.select.return_value.order.return_value.execute.return_value = (
        make_supabase_result(orders_data)
    )
    admin_supabase.auth.admin.list_users.side_effect = Exception("auth service down")

    response = await client.get("/admin/orders")

    assert response.status_code == 200
    body = response.json()
    # Enrichment failed entirely, so no buyer_email/buyer_name were added, but
    # the raw order and the stats are still returned.
    assert body["orders"] == orders_data
    assert body["stats"] == {"total_orders": 1, "total_sales": 100}


async def test_get_all_orders_empty(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.select.return_value.order.return_value.execute.return_value = (
        make_supabase_result([])
    )
    admin_supabase.auth.admin.list_users.return_value = []
    admin_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result([])

    response = await client.get("/admin/orders")

    assert response.status_code == 200
    assert response.json() == {"orders": [], "stats": {"total_orders": 0, "total_sales": 0}}


async def test_get_all_orders_profile_without_display_name_is_ignored(client, admin_user, admin_supabase):
    admin_user()
    orders_data = [{"id": "o1", "buyer_id": "u1", "amount": 100}]
    admin_supabase.table.return_value.select.return_value.order.return_value.execute.return_value = (
        make_supabase_result(orders_data)
    )
    admin_supabase.auth.admin.list_users.return_value = [
        SimpleNamespace(id="u1", email="alice@example.com", user_metadata={"display_name": "Alice"}),
    ]
    # Profile row exists for u1 but has no display_name -- the override loop's
    # `if p.get('display_name')` guard must skip it, leaving the metadata name.
    admin_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result(
        [{"id": "u1", "display_name": None}]
    )

    response = await client.get("/admin/orders")

    assert response.status_code == 200
    body = response.json()
    assert body["orders"][0]["buyer_name"] == "Alice"


async def test_get_all_orders_missing_amount_treated_as_zero(client, admin_user, admin_supabase):
    admin_user()
    orders_data = [{"id": "o1", "buyer_id": None}]  # no "amount" key at all
    admin_supabase.table.return_value.select.return_value.order.return_value.execute.return_value = (
        make_supabase_result(orders_data)
    )
    admin_supabase.auth.admin.list_users.return_value = []
    admin_supabase.table.return_value.select.return_value.execute.return_value = make_supabase_result([])

    response = await client.get("/admin/orders")

    assert response.status_code == 200
    assert response.json()["stats"]["total_sales"] == 0


# ---------------------------------------------------------------------------
# GET /admin/orders/{order_id}
# ---------------------------------------------------------------------------

async def test_get_order_found(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"id": "order-1", "amount": 50}])
    )

    response = await client.get("/admin/orders/order-1")

    assert response.status_code == 200
    assert response.json() == {"id": "order-1", "amount": 50}


async def test_get_order_not_found(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([])
    )

    response = await client.get("/admin/orders/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


# ---------------------------------------------------------------------------
# PUT /admin/orders/{order_id}/status
# ---------------------------------------------------------------------------

async def test_update_order_status_invalid_status_400(client, admin_user, admin_supabase):
    admin_user()

    response = await client.put("/admin/orders/order-1/status", json={"status": "not-a-real-status"})

    assert response.status_code == 400
    assert "Invalid status" in response.json()["detail"]


async def test_update_order_status_success(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"id": "order-1", "status": "confirmed"}])
    )

    response = await client.put("/admin/orders/order-1/status", json={"status": "confirmed"})

    assert response.status_code == 200
    assert response.json() == {"message": "Order status updated to confirmed"}
    admin_supabase.table.return_value.update.assert_called_with({"status": "confirmed"})
    # write_audit fired -- confirm the audit insert actually happened.
    admin_supabase.table.assert_any_call("admin_audit_log")


async def test_update_order_status_not_found_404(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([])
    )

    response = await client.put("/admin/orders/missing/status", json={"status": "confirmed"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


# ---------------------------------------------------------------------------
# PUT /admin/orders/{order_id}
# ---------------------------------------------------------------------------

async def test_update_order_no_fields_400(client, admin_user, admin_supabase):
    admin_user()

    response = await client.put("/admin/orders/order-1", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "No fields to update"


async def test_update_order_invalid_status_400(client, admin_user, admin_supabase):
    admin_user()

    response = await client.put("/admin/orders/order-1", json={"status": "bogus"})

    assert response.status_code == 400
    assert "Invalid status" in response.json()["detail"]


async def test_update_order_success_with_frontend_field_aliases(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"id": "order-1", "address": "123 Street"}])
    )

    payload = {
        "item_name": "Widget",
        "amount": 199.5,
        "address": "123 Street",
        "phone": "555-1234",
        "recipient_name": "Jane Doe",
        "notes": "Leave at door",
    }
    response = await client.put("/admin/orders/order-1", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["message"] == "Order updated successfully"
    assert body["order"] == {"id": "order-1", "address": "123 Street"}
    called_update_data = admin_supabase.table.return_value.update.call_args[0][0]
    assert called_update_data == {
        "item_name": "Widget",
        "amount": 199.5,
        "address": "123 Street",
        "phone": "555-1234",
        "recipient_name": "Jane Doe",
        "notes": "Leave at door",
    }


async def test_update_order_success_with_backend_field_names(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"id": "order-1"}])
    )

    # Only the backend-style field names are provided (no frontend aliases) --
    # `addr = request.address or request.shipping_address` etc. should fall
    # through to these.
    payload = {
        "shipping_address": "456 Avenue",
        "shipping_phone": "555-9999",
        "shipping_name": "John Smith",
    }
    response = await client.put("/admin/orders/order-1", json=payload)

    assert response.status_code == 200
    called_update_data = admin_supabase.table.return_value.update.call_args[0][0]
    assert called_update_data == {
        "address": "456 Avenue",
        "phone": "555-9999",
        "recipient_name": "John Smith",
    }


async def test_update_order_success_with_valid_status_field(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"id": "order-1", "status": "shipped"}])
    )

    response = await client.put("/admin/orders/order-1", json={"status": "shipped"})

    assert response.status_code == 200
    admin_supabase.table.return_value.update.assert_called_with({"status": "shipped"})


async def test_update_order_not_found_404(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([])
    )

    response = await client.put("/admin/orders/missing", json={"item_name": "Widget"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"


# ---------------------------------------------------------------------------
# DELETE /admin/orders/{order_id}
# ---------------------------------------------------------------------------

async def test_delete_order_not_found_404(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([])
    )

    response = await client.delete("/admin/orders/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Order not found"
    admin_supabase.table.return_value.delete.assert_not_called()


async def test_delete_order_success(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"id": "order-1"}])
    )

    response = await client.delete("/admin/orders/order-1")

    assert response.status_code == 200
    assert response.json() == {"message": "Order deleted successfully"}
    admin_supabase.table.return_value.delete.return_value.eq.assert_called_with("id", "order-1")
    admin_supabase.table.assert_any_call("admin_audit_log")


# ---------------------------------------------------------------------------
# POST /admin/analyze-image
# ---------------------------------------------------------------------------

async def test_analyze_image_success_with_market_data(client, admin_user, monkeypatch):
    admin_user()
    analyze_mock = AsyncMock(
        return_value={"name": "Vintage Lamp", "description": "A lamp", "condition": "good", "category": "home"}
    )
    monkeypatch.setattr(image_analyzer_module.image_analyzer, "analyze", analyze_mock)
    market_mock = MagicMock(return_value={"estimated_price": 120, "currency": "MYR"})
    monkeypatch.setattr(market_price_module.market_service, "get_market_valuation", market_mock)

    files = [("images", ("lamp.jpg", b"fake-image-bytes", "image/jpeg"))]
    response = await client.post("/admin/analyze-image", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Vintage Lamp"
    assert body["market_data"] == {"estimated_price": 120, "currency": "MYR"}
    analyze_mock.assert_awaited_once()
    images_arg = analyze_mock.await_args[0][0]
    assert len(images_arg) == 1
    assert images_arg[0]["mime_type"] == "image/jpeg"
    market_mock.assert_called_once_with(query="Vintage Lamp", condition="good", category="home")


async def test_analyze_image_multiple_images(client, admin_user, monkeypatch):
    admin_user()
    analyze_mock = AsyncMock(return_value={"name": "Item", "condition": "fair"})
    monkeypatch.setattr(image_analyzer_module.image_analyzer, "analyze", analyze_mock)
    monkeypatch.setattr(
        market_price_module.market_service, "get_market_valuation", MagicMock(return_value={"estimated_price": 10})
    )

    files = [
        ("images", ("a.jpg", b"aaa", "image/jpeg")),
        ("images", ("b.png", b"bbb", "image/png")),
    ]
    response = await client.post("/admin/analyze-image", files=files)

    assert response.status_code == 200
    images_arg = analyze_mock.await_args[0][0]
    assert len(images_arg) == 2
    assert images_arg[1]["mime_type"] == "image/png"


async def test_analyze_image_market_valuation_failure_sets_none(client, admin_user, monkeypatch):
    admin_user()
    analyze_mock = AsyncMock(return_value={"name": "Chair", "condition": "good"})
    monkeypatch.setattr(image_analyzer_module.image_analyzer, "analyze", analyze_mock)

    def _boom(**kwargs):
        raise RuntimeError("market service unavailable")

    monkeypatch.setattr(market_price_module.market_service, "get_market_valuation", _boom)

    files = [("images", ("chair.jpg", b"fake", "image/jpeg"))]
    response = await client.post("/admin/analyze-image", files=files)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Chair"
    assert body["market_data"] is None


async def test_analyze_image_analyzer_exception_returns_500(client, admin_user, monkeypatch):
    admin_user()
    analyze_mock = AsyncMock(side_effect=RuntimeError("gemini exploded"))
    monkeypatch.setattr(image_analyzer_module.image_analyzer, "analyze", analyze_mock)

    files = [("images", ("broken.jpg", b"fake", "image/jpeg"))]
    response = await client.post("/admin/analyze-image", files=files)

    assert response.status_code == 500
    assert "Failed to analyze image" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /admin/analyze-image/stream
#
# The route delegates to agent.tools.listing_pipeline.analyze_listing (imported
# lazily inside the handler), so patching the name on that module is what the
# route resolves at call time. The pipeline's own stage/concurrency behaviour is
# covered by test_agent_tools_listing_pipeline.py -- here we only assert the SSE
# framing around it.
# ---------------------------------------------------------------------------


def _sse_events(body: str) -> list[dict]:
    """Parse an SSE response body into the list of JSON payloads it carried."""
    import json as _json

    return [
        _json.loads(line[len("data:"):].strip())
        for frame in body.split("\n\n")
        for line in frame.split("\n")
        if line.startswith("data:")
    ]


async def test_analyze_image_stream_emits_progress_then_the_final_result(client, admin_user, monkeypatch):
    admin_user()

    async def fake_pipeline(images_data, on_progress=None):
        await on_progress({"stage": "identifying", "progress": 20, "message": "Looking…"})
        await on_progress({
            "stage": "identified", "progress": 50, "message": "Identified: Lamp",
            "patch": {"name": "Lamp"},
        })
        return {"name": "Lamp", "description": "A lamp", "market_data": {"suggested_listing": 90}}

    monkeypatch.setattr(listing_pipeline_module, "analyze_listing", fake_pipeline)

    files = [("images", ("lamp.jpg", b"fake-image-bytes", "image/jpeg"))]
    response = await client.post("/admin/analyze-image/stream", files=files)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"

    events = _sse_events(response.text)
    assert [e["stage"] for e in events] == ["uploaded", "identifying", "identified", "done"]
    assert events[0]["progress"] == 10
    assert events[2]["patch"] == {"name": "Lamp"}
    assert events[-1]["progress"] == 100
    assert events[-1]["result"]["name"] == "Lamp"


async def test_analyze_image_stream_passes_every_encoded_image_through(client, admin_user, monkeypatch):
    admin_user()
    seen = {}

    async def fake_pipeline(images_data, on_progress=None):
        seen["images"] = images_data
        return {"name": "Item"}

    monkeypatch.setattr(listing_pipeline_module, "analyze_listing", fake_pipeline)

    files = [
        ("images", ("a.jpg", b"aaa", "image/jpeg")),
        ("images", ("b.png", b"bbb", "image/png")),
    ]
    response = await client.post("/admin/analyze-image/stream", files=files)

    assert response.status_code == 200
    # Order is preserved, and each image arrives base64-encoded with its type.
    assert [i["mime_type"] for i in seen["images"]] == ["image/jpeg", "image/png"]
    assert seen["images"][0]["base64_image"] == base64.b64encode(b"aaa").decode()


async def test_encode_images_defaults_a_missing_content_type_to_jpeg():
    # Exercised directly: an HTTP client always fills in *some* content type
    # (httpx defaults to application/octet-stream), so this branch is only
    # reachable from an UploadFile that carries none.
    import io

    from fastapi import UploadFile

    from routes.admin.listings import _encode_images

    upload = UploadFile(filename="mystery", file=io.BytesIO(b"data"))
    assert upload.content_type is None

    encoded = await _encode_images([upload])

    assert encoded == [{"base64_image": base64.b64encode(b"data").decode(), "mime_type": "image/jpeg"}]


async def test_analyze_image_stream_reports_a_pipeline_failure_as_an_error_event(client, admin_user, monkeypatch):
    admin_user()

    async def boom(images_data, on_progress=None):
        raise RuntimeError("gemini exploded")

    monkeypatch.setattr(listing_pipeline_module, "analyze_listing", boom)

    files = [("images", ("broken.jpg", b"fake", "image/jpeg"))]
    response = await client.post("/admin/analyze-image/stream", files=files)

    # The stream has already started, so the failure is delivered in-band
    # rather than as an HTTP error status.
    assert response.status_code == 200
    events = _sse_events(response.text)
    assert events[-1]["stage"] == "error"
    assert "gemini exploded" in events[-1]["message"]


# ---------------------------------------------------------------------------
# POST /admin/market-valuation
# ---------------------------------------------------------------------------

async def test_market_valuation_success(client, admin_user, monkeypatch):
    admin_user()
    market_mock = MagicMock(return_value={"estimated_price": 300, "currency": "MYR"})
    monkeypatch.setattr(market_price_module.market_service, "get_market_valuation", market_mock)

    response = await client.post(
        "/admin/market-valuation", json={"query": "iPhone 12", "condition": "like new", "category": "electronics"}
    )

    assert response.status_code == 200
    assert response.json() == {"estimated_price": 300, "currency": "MYR"}
    market_mock.assert_called_once_with(query="iPhone 12", condition="like new", category="electronics")


async def test_market_valuation_default_condition(client, admin_user, monkeypatch):
    admin_user()
    market_mock = MagicMock(return_value={"estimated_price": 50})
    monkeypatch.setattr(market_price_module.market_service, "get_market_valuation", market_mock)

    response = await client.post("/admin/market-valuation", json={"query": "Old Book"})

    assert response.status_code == 200
    market_mock.assert_called_once_with(query="Old Book", condition="good", category=None)


async def test_market_valuation_exception_returns_500(client, admin_user, monkeypatch):
    admin_user()

    def _boom(**kwargs):
        raise RuntimeError("scraper down")

    monkeypatch.setattr(market_price_module.market_service, "get_market_valuation", _boom)

    response = await client.post("/admin/market-valuation", json={"query": "Broken Thing"})

    assert response.status_code == 500
    assert response.json()["detail"] == "scraper down"


async def test_market_valuation_missing_query_422(client, admin_user):
    admin_user()

    response = await client.post("/admin/market-valuation", json={})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /admin/summary
# ---------------------------------------------------------------------------

async def test_admin_summary_success(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.auth.admin.list_users.return_value = [SimpleNamespace(id="u1"), SimpleNamespace(id="u2")]
    admin_supabase.table.return_value.select.return_value.is_.return_value.execute.return_value = (
        make_supabase_result([{"status": "available"}, {"status": "sold"}, {"status": "available"}])
    )
    admin_supabase.table.return_value.select.return_value.execute.side_effect = [
        make_supabase_result(
            [
                {"status": "confirmed", "amount": 100},
                {"status": "pending_info", "amount": 50},
                {"status": "shipped", "amount": 25},
                {"status": "delivered", "amount": 10},
            ]
        ),
        make_supabase_result([{"id": "c1"}, {"id": "c2"}, {"id": "c3"}]),
    ]

    response = await client.get("/admin/summary")

    assert response.status_code == 200
    assert response.json() == {
        "users": 2,
        "conversations": 3,
        "items_total": 3,
        "items_available": 2,
        "items_sold": 1,
        "orders_total": 4,
        "orders_pending": 1,
        "orders_confirmed": 1,
        "orders_shipped": 1,
        "orders_delivered": 1,
        "sales_total": 185,
    }


async def test_admin_summary_list_users_exception_falls_back_to_zero(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.auth.admin.list_users.side_effect = Exception("auth down")
    admin_supabase.table.return_value.select.return_value.is_.return_value.execute.return_value = (
        make_supabase_result([])
    )
    admin_supabase.table.return_value.select.return_value.execute.side_effect = [
        make_supabase_result([]),
        make_supabase_result([]),
    ]

    response = await client.get("/admin/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["users"] == 0
    assert body["items_total"] == 0
    assert body["orders_total"] == 0


# ---------------------------------------------------------------------------
# GET /admin/items
# ---------------------------------------------------------------------------

async def test_admin_list_items_success(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.select.return_value.is_.return_value.order.return_value.execute.return_value = (
        make_supabase_result([{"id": "item-1", "name": "Widget"}])
    )

    response = await client.get("/admin/items")

    assert response.status_code == 200
    assert response.json() == [{"id": "item-1", "name": "Widget"}]


async def test_admin_list_items_empty(client, admin_user, admin_supabase):
    admin_user()
    admin_supabase.table.return_value.select.return_value.is_.return_value.order.return_value.execute.return_value = (
        make_supabase_result(None)
    )

    response = await client.get("/admin/items")

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# POST /admin/items  (create)
# ---------------------------------------------------------------------------

async def test_admin_create_item_success(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    upload_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(items_module, "upload_item", upload_mock)

    data = {"name": "Widget", "description": "A nice widget", "condition": "good", "price": "19.99"}
    files = [("images", ("widget.jpg", b"fake-bytes", "image/jpeg"))]
    response = await client.post("/admin/items", data=data, files=files)

    assert response.status_code == 201
    assert response.json() == {"message": "Item created successfully"}
    upload_mock.assert_awaited_once()
    args = upload_mock.await_args[0]
    assert args[0] == "Widget"
    assert args[1] == "A nice widget"
    assert args[2] == "good"
    assert args[4] == 19.99
    assert args[5] is None  # min_price not provided
    admin_supabase.table.assert_any_call("admin_audit_log")


async def test_admin_create_item_with_min_price(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    upload_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(items_module, "upload_item", upload_mock)

    data = {
        "name": "Widget",
        "description": "A nice widget",
        "condition": "good",
        "price": "19.99",
        "min_price": "9.99",
    }
    files = [("images", ("widget.jpg", b"fake-bytes", "image/jpeg"))]
    response = await client.post("/admin/items", data=data, files=files)

    assert response.status_code == 201
    args = upload_mock.await_args[0]
    assert args[5] == 9.99


async def test_admin_create_item_with_translations(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    upload_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(items_module, "upload_item", upload_mock)

    translations_dict = {"en": {"name": "En"}, "ms": {"name": "Ms"}, "zh": {"name": "Zh"}}
    data = {
        "name": "Widget",
        "description": "A nice widget",
        "condition": "good",
        "price": "19.99",
        "translations": json.dumps(translations_dict),
    }
    files = [("images", ("widget.jpg", b"fake-bytes", "image/jpeg"))]
    response = await client.post("/admin/items", data=data, files=files)

    assert response.status_code == 201
    kwargs = upload_mock.await_args.kwargs
    assert kwargs.get("translations") == translations_dict


async def test_admin_create_item_upload_failure_500(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    upload_mock = AsyncMock(return_value=False)
    monkeypatch.setattr(items_module, "upload_item", upload_mock)

    data = {"name": "Widget", "description": "A nice widget", "condition": "good", "price": "19.99"}
    files = [("images", ("widget.jpg", b"fake-bytes", "image/jpeg"))]
    response = await client.post("/admin/items", data=data, files=files)

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to create item"


# ---------------------------------------------------------------------------
# PUT /admin/items/{item_id}  (update)
# ---------------------------------------------------------------------------

async def test_admin_update_item_success(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    update_mock = MagicMock(return_value=True)
    monkeypatch.setattr(items_module, "update_item", update_mock)

    response = await client.put("/admin/items/item-1", data={"name": "New Name", "price": "25.5"})

    assert response.status_code == 200
    assert response.json() == {"message": "Item updated successfully"}
    update_mock.assert_called_once_with(
        item_id="item-1",
        name="New Name",
        description=None,
        condition=None,
        price=25.5,
        min_price=None,
        images=None,
        translations=None,
    )
    admin_supabase.table.assert_any_call("admin_audit_log")


async def test_admin_update_item_with_translations(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    update_mock = MagicMock(return_value=True)
    monkeypatch.setattr(items_module, "update_item", update_mock)

    translations = {"en": {"name": "En"}, "ms": {"name": "Ms"}, "zh": {"name": "Zh"}}
    response = await client.put(
        "/admin/items/item-1",
        data={"name": "New Name", "translations": json.dumps(translations)},
    )

    assert response.status_code == 200
    update_mock.assert_called_once_with(
        item_id="item-1",
        name="New Name",
        description=None,
        condition=None,
        price=None,
        min_price=None,
        images=None,
        translations=translations,
    )


async def test_admin_update_item_ignores_unparseable_translations(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    update_mock = MagicMock(return_value=True)
    monkeypatch.setattr(items_module, "update_item", update_mock)

    response = await client.put(
        "/admin/items/item-1",
        data={"name": "New Name", "translations": "{not json"},
    )

    assert response.status_code == 200
    assert update_mock.call_args.kwargs["translations"] is None


async def test_admin_update_item_syncs_images_when_an_order_is_given(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    update_mock = MagicMock(return_value=True)
    sync_mock = AsyncMock(return_value='{"0.jpg": "https://cdn.example.com/a.jpg"}')
    monkeypatch.setattr(items_module, "update_item", update_mock)
    monkeypatch.setattr(items_module, "sync_item_images", sync_mock)

    order = ["new:0", "https://cdn.example.com/a.jpg"]
    response = await client.put(
        "/admin/items/item-1",
        data={"name": "New Name", "images_order": json.dumps(order)},
        files=[("new_images", ("fresh.png", b"fake-bytes", "image/png"))],
    )

    assert response.status_code == 200
    sync_mock.assert_awaited_once()
    assert sync_mock.await_args.args[0] == "item-1"
    assert sync_mock.await_args.args[1] == order
    assert len(sync_mock.await_args.args[2]) == 1
    assert update_mock.call_args.kwargs["images"] == '{"0.jpg": "https://cdn.example.com/a.jpg"}'


async def test_admin_update_item_accepts_an_empty_new_images_list(client, admin_user, admin_supabase, monkeypatch):
    """Reordering/removing photos sends an order but uploads nothing."""
    admin_user()
    update_mock = MagicMock(return_value=True)
    sync_mock = AsyncMock(return_value="{}")
    monkeypatch.setattr(items_module, "update_item", update_mock)
    monkeypatch.setattr(items_module, "sync_item_images", sync_mock)

    response = await client.put(
        "/admin/items/item-1",
        data={"name": "New Name", "images_order": json.dumps([])},
    )

    assert response.status_code == 200
    assert sync_mock.await_args.args[2] == []
    assert update_mock.call_args.kwargs["images"] == "{}"


async def test_admin_update_item_rejects_an_unparseable_images_order(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    update_mock = MagicMock(return_value=True)
    sync_mock = AsyncMock(return_value="{}")
    monkeypatch.setattr(items_module, "update_item", update_mock)
    monkeypatch.setattr(items_module, "sync_item_images", sync_mock)

    response = await client.put(
        "/admin/items/item-1",
        data={"name": "New Name", "images_order": "{not json"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid images_order"
    sync_mock.assert_not_awaited()
    update_mock.assert_not_called()


async def test_admin_update_item_image_sync_failure_500(client, admin_user, admin_supabase, monkeypatch):
    """A failed photo sync must not half-apply the edit."""
    admin_user()
    update_mock = MagicMock(return_value=True)
    sync_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(items_module, "update_item", update_mock)
    monkeypatch.setattr(items_module, "sync_item_images", sync_mock)

    response = await client.put(
        "/admin/items/item-1",
        data={"name": "New Name", "images_order": json.dumps(["new:0"])},
        files=[("new_images", ("fresh.png", b"fake-bytes", "image/png"))],
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to update item images"
    update_mock.assert_not_called()


async def test_admin_update_item_not_found_404(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    monkeypatch.setattr(items_module, "update_item", MagicMock(return_value=False))

    response = await client.put("/admin/items/missing", data={"name": "New Name"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found or update failed"


# ---------------------------------------------------------------------------
# DELETE /admin/items/{item_id}
# ---------------------------------------------------------------------------

async def test_admin_delete_item_success(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    monkeypatch.setattr(items_module, "delete_item", MagicMock(return_value=True))

    response = await client.delete("/admin/items/item-1")

    assert response.status_code == 200
    assert response.json() == {"message": "Item deleted successfully"}
    admin_supabase.table.assert_any_call("admin_audit_log")


async def test_admin_delete_item_not_found_404(client, admin_user, admin_supabase, monkeypatch):
    admin_user()
    monkeypatch.setattr(items_module, "delete_item", MagicMock(return_value=False))

    response = await client.delete("/admin/items/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found or delete failed"


# ---------------------------------------------------------------------------
# Auth gate sanity check (bonus): the whole `protected` router requires a
# valid admin session cookie -- confirms /admin/orders isn't accidentally
# reachable without the verify_admin dependency doing its job.
# ---------------------------------------------------------------------------

async def test_admin_orders_requires_admin_session_401(client):
    response = await client.get("/admin/orders")

    assert response.status_code == 401
