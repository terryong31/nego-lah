"""
SPEC-036 — confidential item columns must never reach the storefront.

`min_price` is the negotiation floor: publishing it hands every buyer the
seller's reserve and makes the agent's haggling theatre. `buyer_id` names who
bought an item, and `deleted_at` is bookkeeping. None belong in a public
response, a Redis cache entry, or an anon-key PostgREST select.

Seam notes (see conftest): `routes/items.py` binds `get_items` /
`get_featured_items` at import time, so we patch them on `routes.items`;
`get_item_by_id` does a lazy `from connector import user_supabase`, so
`patch_supabase("connector", user=...)` takes effect at call time.
"""

import json
from unittest.mock import MagicMock

import items as items_module
import routes.items as routes_items
from conftest import make_supabase_result
from items import CONFIDENTIAL_ITEM_COLUMNS, PUBLIC_ITEM_SELECT

# A row exactly as Postgres hands it back: everything, secrets included.
RAW_ROW = {
    "id": "item-1",
    "name": "Widget",
    "description": "A widget",
    "condition": "good",
    "price": 100.0,
    "min_price": 60.0,
    "buyer_id": "user-9",
    "deleted_at": None,
    "image_path": json.dumps({"0.jpg": "https://example.com/0.jpg"}),
    "status": "available",
    "created_at": "2026-01-01T00:00:00Z",
    "translations": {"en": {"name": "Widget"}},
}


def _assert_clean(payload: dict):
    for column in CONFIDENTIAL_ITEM_COLUMNS:
        assert column not in payload, f"{column} leaked into the public payload"


# ---------------------------------------------------------------------------
# _to_public is an allowlist, not a copy
# ---------------------------------------------------------------------------

def test_to_public_drops_confidential_columns():
    out = routes_items._to_public(RAW_ROW)
    _assert_clean(out)


def test_to_public_drops_unknown_columns():
    """The allowlist is closed: a column added to the table later must not
    start shipping publicly just because nobody remembered to denylist it."""
    out = routes_items._to_public({**RAW_ROW, "secret_cost": 12.5})
    assert "secret_cost" not in out


def test_to_public_preserves_the_storefront_shape():
    out = routes_items._to_public(RAW_ROW)
    assert out["item_id"] == "item-1"
    assert out["id"] == "item-1"
    assert out["name"] == "Widget"
    assert out["price"] == 100.0
    assert out["condition"] == "good"
    assert out["status"] == "available"
    assert out["created_at"] == "2026-01-01T00:00:00Z"
    assert out["translations"] == {"en": {"name": "Widget"}}
    assert json.loads(out["images"]) == ["https://example.com/0.jpg"]


# ---------------------------------------------------------------------------
# The three public endpoints
# ---------------------------------------------------------------------------

async def test_get_all_items_does_not_leak_min_price(client, monkeypatch):
    monkeypatch.setattr(routes_items, "get_items", lambda keyword=None: [RAW_ROW])

    body = (await client.get("/items")).json()

    assert len(body) == 1
    _assert_clean(body[0])


async def test_get_featured_does_not_leak_min_price(client, monkeypatch):
    monkeypatch.setattr(routes_items, "get_featured_items", lambda limit=6: [RAW_ROW])

    body = (await client.get("/items/featured")).json()

    assert len(body) == 1
    _assert_clean(body[0])


async def test_get_item_by_id_does_not_leak_min_price(
    client, fake_supabase, patch_supabase
):
    (fake_supabase.table.return_value.select.return_value
     .eq.return_value.is_.return_value.execute.return_value) = make_supabase_result([RAW_ROW])
    patch_supabase("connector", user=fake_supabase)

    response = await client.get("/items/item-1")

    assert response.status_code == 200
    _assert_clean(response.json())


# ---------------------------------------------------------------------------
# The anon client must never ask for the confidential columns in the first
# place — belt (API projection) and braces (query projection).
# ---------------------------------------------------------------------------

def test_public_select_excludes_confidential_columns():
    requested = {c.strip() for c in PUBLIC_ITEM_SELECT.split(",")}
    assert requested.isdisjoint(CONFIDENTIAL_ITEM_COLUMNS)
    assert "*" not in requested
    # The storefront still needs everything it renders.
    assert {"id", "name", "price", "image_path", "status", "created_at"} <= requested


def test_get_items_requests_only_public_columns(monkeypatch, fake_supabase):
    (fake_supabase.table.return_value.select.return_value.is_.return_value
     .order.return_value.order.return_value.execute.return_value) = make_supabase_result([])
    monkeypatch.setattr(items_module, "user_supabase", fake_supabase)
    monkeypatch.setattr(items_module, "get_cached_items_with_hash", lambda: (None, None))

    items_module.get_items()

    fake_supabase.table.return_value.select.assert_called_with(PUBLIC_ITEM_SELECT)


def test_get_featured_items_requests_only_public_columns(
    monkeypatch, fake_supabase
):
    (fake_supabase.table.return_value.select.return_value.eq.return_value
     .is_.return_value.order.return_value.limit.return_value
     .execute.return_value) = make_supabase_result([])
    monkeypatch.setattr(items_module, "user_supabase", fake_supabase)

    items_module.get_featured_items()

    fake_supabase.table.return_value.select.assert_called_with(PUBLIC_ITEM_SELECT)


async def test_cached_storefront_payload_holds_no_secrets(monkeypatch, fake_supabase):
    """The Redis cache is written from whatever the query returned, so a `*`
    select would park min_price in Redis even if the API filtered it later."""
    from cache import get_cached_items_with_hash, invalidate_item_cache

    invalidate_item_cache()
    (fake_supabase.table.return_value.select.return_value.is_.return_value
     .order.return_value.order.return_value.execute.return_value) = make_supabase_result(
        [{k: v for k, v in RAW_ROW.items() if k not in CONFIDENTIAL_ITEM_COLUMNS}]
    )
    monkeypatch.setattr(items_module, "user_supabase", fake_supabase)

    items_module.get_items()
    cached, _ = get_cached_items_with_hash()

    assert cached
    for row in cached:
        _assert_clean(row)


# ---------------------------------------------------------------------------
# The floor still has to be readable server-side. Column privileges apply to
# the anon key, so the negotiation guards must hold the service-role client —
# otherwise revoking `min_price` silently disarms them.
# ---------------------------------------------------------------------------

FLOOR_ROW = {"id": "item-1", "name": "Widget", "price": 100.0,
             "min_price": 60.0, "status": "available"}


def _bind_item(fake, row):
    fake.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([row])
    )


def test_evaluate_offer_reads_the_floor_with_the_service_role(
    fake_supabase, patch_supabase, monkeypatch
):
    from agent.tools.negotiation import evaluate_offer

    _bind_item(fake_supabase, FLOOR_ROW)
    anon = MagicMock()
    patch_supabase("connector", admin=fake_supabase, user=anon)

    result = evaluate_offer.func(item_id="item-1", offered_price=10.0)

    assert "REJECT_FLOOR" in result
    anon.table.assert_not_called()


def test_create_checkout_reads_the_floor_with_the_service_role(
    fake_supabase, patch_supabase, monkeypatch
):
    from agent import context
    from agent.tools.payment import create_checkout_link

    _bind_item(fake_supabase, FLOOR_ROW)
    anon = MagicMock()
    patch_supabase("connector", admin=fake_supabase, user=anon)
    context.set_context(user_id="user-1", item_id="item-1")
    monkeypatch.setattr(
        "payment.payment_state.get_pending_payment", lambda *a, **k: None
    )

    result = create_checkout_link.func(item_id="item-1", agreed_price=10.0)

    assert "PRICE VALIDATION FAILED" in result
    # The floor must never be echoed back to the buyer.
    assert "60" not in result
    anon.table.assert_not_called()


# ---------------------------------------------------------------------------
# The API allowlist and the SQL grant are two halves of one boundary. Nothing
# in the build fails if they drift apart, so assert they agree.
# ---------------------------------------------------------------------------

def test_column_grant_matches_the_python_allowlist():
    import pathlib
    import re

    from items import PUBLIC_ITEM_COLUMNS

    migration = (
        pathlib.Path(__file__).resolve().parents[2]
        / "supabase" / "migrations" / "20260702000000_items_column_privileges.sql"
    ).read_text()

    granted_block = re.search(
        r"grant select \((.*?)\) on public\.items to anon, authenticated;",
        migration,
        re.DOTALL,
    )
    assert granted_block, "column-scoped grant not found in the migration"
    granted = {
        line.strip().rstrip(",")
        for line in granted_block.group(1).splitlines()
        if line.strip() and not line.strip().startswith("--")
    }

    # `deleted_at` is granted but never published: column privileges cover WHERE
    # clauses, and every storefront query filters on it.
    assert granted == set(PUBLIC_ITEM_COLUMNS) | {"deleted_at"}
    assert granted.isdisjoint({"min_price", "buyer_id"})


def test_row_policy_hides_soft_deleted_listings():
    import pathlib

    migration = (
        pathlib.Path(__file__).resolve().parents[2]
        / "supabase" / "migrations" / "20260702000000_items_column_privileges.sql"
    ).read_text()

    assert "revoke select on public.items from anon, authenticated;" in migration
    assert "using (deleted_at is null)" in migration
