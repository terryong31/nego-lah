"""
Tests for the domain services (SPEC-002, SPEC-092).

These assert what the service *does to the query* — the column allowlist it
selects, the filters it applies, the conditional it claims on — not merely that
a MagicMock hands its own fixture back. A test that configures
`fake.table().select().eq().execute().data = [...]` and then asserts the row
came out proves only that the mock works.
"""

from unittest.mock import MagicMock, patch

import pytest

from domains.billing import BillingService
from domains.catalog import CatalogService
from domains.catalog.items import CONFIDENTIAL_ITEM_COLUMNS, PUBLIC_ITEM_SELECT


def _recording_client(data):
    """A Supabase double whose builder chain records the calls made against it."""
    calls: list[tuple[str, tuple]] = []

    class _Chain:
        def __getattr__(self, name):
            def _call(*args, **kwargs):
                calls.append((name, args))
                return self

            return _call

        def execute(self):
            calls.append(("execute", ()))
            return MagicMock(data=data)

    client = MagicMock()
    client.table.side_effect = lambda name: (calls.append(("table", (name,))), _Chain())[1]
    return client, calls


# ---------------------------------------------------------------------------
# CatalogService — SPEC-036 column boundary
# ---------------------------------------------------------------------------


def test_get_public_item_by_id_selects_only_public_columns_and_hides_soft_deleted():
    client, calls = _recording_client([{"id": "item-123", "name": "Vintage Chair"}])
    item = CatalogService.get_public_item_by_id("item-123", supabase_client=client)

    assert item["name"] == "Vintage Chair"
    assert ("table", ("items",)) in calls
    # The allowlist is what is sent to PostgREST — not merely absent from the fixture.
    selected = next(args[0] for name, args in calls if name == "select")
    assert selected == PUBLIC_ITEM_SELECT
    for column in CONFIDENTIAL_ITEM_COLUMNS:
        assert column not in selected, f"public read must not select '{column}'"
    assert ("is_", ("deleted_at", "null")) in calls, "soft-deleted items must be excluded"


def test_get_item_with_floor_price_is_the_only_reader_of_the_floor():
    client, calls = _recording_client([{"id": "item-123", "price": 120.0, "min_price": 90.0}])
    item = CatalogService.get_item_with_floor_price("item-123", supabase_client=client)

    assert item["min_price"] == 90.0
    assert next(args[0] for name, args in calls if name == "select") == "*"


def test_get_item_name_returns_none_rather_than_raising_when_lookup_fails():
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.execute.side_effect = RuntimeError("db down")
    assert CatalogService.get_item_name("item-123", supabase_client=client) is None


# ---------------------------------------------------------------------------
# CatalogService.claim_item_as_sold — the atomic transition (ADR-0001)
# ---------------------------------------------------------------------------


def test_claim_item_as_sold_is_conditional_on_the_item_still_being_available():
    client, calls = _recording_client([{"id": "item-123", "status": "sold", "buyer_id": "buyer-456"}])
    won, row = CatalogService.claim_item_as_sold("item-123", "buyer-456", supabase_client=client)

    assert won is True
    assert row["buyer_id"] == "buyer-456"
    assert ("update", ({"status": "sold", "buyer_id": "buyer-456"},)) in calls
    # Without this filter the UPDATE is not a claim — it would steal a sold item.
    assert ("eq", ("status", "available")) in calls


def test_claim_item_as_sold_reports_the_current_holder_when_the_claim_is_lost():
    client = MagicMock()
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": "item-123", "status": "sold", "buyer_id": "other-buyer"}
    ]
    won, row = CatalogService.claim_item_as_sold("item-123", "buyer-456", supabase_client=client)

    assert won is False
    assert row["buyer_id"] == "other-buyer"


def test_claim_item_as_sold_propagates_db_errors_instead_of_reporting_a_lost_claim():
    """
    A swallowed error here reads as "another buyer won", and payment.fulfillment
    answers a lost claim by REFUNDING the payment. A transient PostgREST failure
    must reach the webhook so Stripe redelivers instead.
    """
    client = MagicMock()
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.side_effect = RuntimeError(
        "supabase 503"
    )
    with pytest.raises(RuntimeError):
        CatalogService.claim_item_as_sold("item-123", "buyer-456", supabase_client=client)


def test_claim_item_as_sold_does_not_touch_the_cache():
    """
    Cache invalidation belongs to `_finalize_won_sale`, which guards it. A Redis
    round-trip inside this method could fail after the claim had committed.
    """
    import domains.catalog.services as services

    assert not hasattr(services, "invalidate_item_cache")


# ---------------------------------------------------------------------------
# CatalogService — public search surface
# ---------------------------------------------------------------------------


def test_search_items_filters_soft_deleted_and_honours_the_limit():
    client, calls = _recording_client([{"id": "item-1", "name": "Match"}])
    results = CatalogService.search_items("Match", limit=3, supabase_client=client)

    assert [r["name"] for r in results] == ["Match"]
    assert ("ilike", ("name", "%Match%")) in calls
    assert ("is_", ("deleted_at", "null")) in calls
    assert ("limit", (3,)) in calls


def test_list_available_items_returns_only_available_stock():
    client, calls = _recording_client([{"id": "item-1", "name": "In stock"}])
    CatalogService.list_available_items(limit=7, supabase_client=client)

    assert ("eq", ("status", "available")) in calls
    assert ("is_", ("deleted_at", "null")) in calls
    assert ("limit", (7,)) in calls


def test_public_reads_degrade_to_empty_rather_than_raising_into_an_agent_turn():
    client = MagicMock()
    client.table.side_effect = RuntimeError("db down")
    assert CatalogService.get_public_item_by_id("x", supabase_client=client) is None
    assert CatalogService.search_items("x", supabase_client=client) == []
    assert CatalogService.list_available_items(supabase_client=client) == []


# ---------------------------------------------------------------------------
# BillingService — the one operation another domain performs
# ---------------------------------------------------------------------------


def test_billing_service_get_active_negotiated_price_delegates_to_pricing():
    # The service imports lazily inside the method, so patch the origin module.
    with patch("domains.billing.pricing.active_negotiated_price", return_value=85.0) as priced:
        assert BillingService.get_active_negotiated_price("user-1", "item-1") == 85.0
    priced.assert_called_once_with("user-1", "item-1")


def test_list_all_users_pages_past_gotrues_default_of_fifty():
    """Audit SCL-2: an unpaged `list_users()` returns 50 accounts and stops."""
    from domains.identity import IdentityService

    size = IdentityService.USERS_PAGE_SIZE
    pages = {1: [f"u{i}" for i in range(size)], 2: [f"v{i}" for i in range(size)], 3: ["w0"]}
    client = MagicMock()
    client.auth.admin.list_users.side_effect = lambda page, per_page: pages.get(page, [])

    users = IdentityService.list_all_users(client)

    assert len(users) == 2 * size + 1
    assert [c.kwargs["page"] for c in client.auth.admin.list_users.call_args_list] == [1, 2, 3]
