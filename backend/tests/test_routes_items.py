"""
Tests for routes/items.py — public, unauthenticated item read endpoints.

Mocking seam notes:
- `routes/items.py` does `from items import get_items, get_featured_items` at
  module import time, so those two names are bound directly into the
  `routes.items` module namespace. We monkeypatch them there
  (`routes.items.get_items` / `routes.items.get_featured_items`) rather than
  patching Supabase, since routes/items.py never touches Supabase directly
  for those two routes.
- `get_item_by_id` (the `/{item_id}` route) does a *lazy* `from connector
  import user_supabase` inside the function body, so patching
  `connector.user_supabase` (via `patch_supabase("connector", user=fake)`)
  takes effect at call time.
"""

import asyncio
import contextlib
import json
import time

import routes.items as routes_items

# ---------------------------------------------------------------------------
# GET /items
# ---------------------------------------------------------------------------

async def test_get_all_items_no_keyword_returns_public_shape(client, monkeypatch):
    raw_items = [
        {
            "id": "item-1",
            "name": "Widget",
            "image_path": json.dumps({"0.jpg": "https://example.com/0.jpg"}),
        },
        {
            "id": "item-2",
            "name": "Gadget",
            "image_path": None,
        },
    ]
    monkeypatch.setattr(routes_items, "get_items", lambda keyword=None: raw_items)

    response = await client.get("/items")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["item_id"] == "item-1"
    assert json.loads(body[0]["images"]) == ["https://example.com/0.jpg"]
    assert body[1]["item_id"] == "item-2"
    assert json.loads(body[1]["images"]) == []
    # Original fields preserved alongside the aliases.
    assert body[0]["id"] == "item-1"
    assert body[0]["name"] == "Widget"


async def test_get_all_items_preserves_translations(client, monkeypatch):
    raw_items = [
        {
            "id": "item-1",
            "name": "Widget",
            "image_path": None,
            "translations": {
                "en": {"name": "Widget", "description": "English desc"},
                "ms": {"name": "Widget MS", "description": "Penerangan"},
                "zh": {"name": "小部件", "description": "中文描述"},
            },
        },
    ]
    monkeypatch.setattr(routes_items, "get_items", lambda keyword=None: raw_items)

    response = await client.get("/items")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["translations"]["zh"]["name"] == "小部件"


async def test_get_all_items_empty_list(client, monkeypatch):
    monkeypatch.setattr(routes_items, "get_items", lambda keyword=None: [])

    response = await client.get("/items")

    assert response.status_code == 200
    assert response.json() == []


async def test_get_all_items_none_returns_empty_list(client, monkeypatch):
    # get_items() can theoretically return a falsy value other than [] (e.g.
    # None) -- route guards with `if items else []`.
    monkeypatch.setattr(routes_items, "get_items", lambda keyword=None: None)

    response = await client.get("/items")

    assert response.status_code == 200
    assert response.json() == []


async def test_get_all_items_with_keyword_forwards_it(client, monkeypatch):
    captured = {}

    def fake_get_items(keyword=None):
        captured["keyword"] = keyword
        return [{"id": "item-1", "name": "Widget", "image_path": None}]

    monkeypatch.setattr(routes_items, "get_items", fake_get_items)

    response = await client.get("/items", params={"keyword": "widget"})

    assert response.status_code == 200
    assert captured["keyword"] == "widget"
    assert response.json()[0]["item_id"] == "item-1"


# ---------------------------------------------------------------------------
# GET /items/featured  (must not be shadowed by /{item_id})
# ---------------------------------------------------------------------------

async def test_get_featured_not_shadowed_by_item_id_route(client, monkeypatch):
    # If '/featured' were captured by '/{item_id}' this would hit
    # get_item_by_id (which does a Supabase lookup for id='featured') instead
    # of get_featured_items. Monkeypatch both to prove which one actually runs.
    monkeypatch.setattr(
        routes_items, "get_featured_items", lambda limit=6: [{"id": "feat-1", "name": "Featured", "image_path": None}]
    )

    def fail_get_item_by_id_path(*args, **kwargs):
        raise AssertionError("get_item_by_id path should not be hit for /items/featured")

    response = await client.get("/items/featured")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["item_id"] == "feat-1"


async def test_get_featured_default_limit(client, monkeypatch):
    captured = {}

    def fake_get_featured_items(limit=6):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(routes_items, "get_featured_items", fake_get_featured_items)

    response = await client.get("/items/featured")

    assert response.status_code == 200
    assert response.json() == []
    assert captured["limit"] == 6


async def test_get_featured_custom_limit(client, monkeypatch):
    captured = {}

    def fake_get_featured_items(limit=6):
        captured["limit"] = limit
        return []

    monkeypatch.setattr(routes_items, "get_featured_items", fake_get_featured_items)

    response = await client.get("/items/featured", params={"limit": 3})

    assert response.status_code == 200
    assert captured["limit"] == 3


# ---------------------------------------------------------------------------
# GET /items/{item_id}
# ---------------------------------------------------------------------------

async def test_get_item_by_id_found(client, patch_supabase, fake_supabase):
    from conftest import make_supabase_result as _make_supabase_result

    row = {
        "id": "item-123",
        "name": "Widget",
        "image_path": json.dumps(["https://example.com/a.jpg"]),
    }
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        _make_supabase_result([row])
    )
    patch_supabase("connector", user=fake_supabase)

    response = await client.get("/items/item-123")

    assert response.status_code == 200
    body = response.json()
    assert body["item_id"] == "item-123"
    assert json.loads(body["images"]) == ["https://example.com/a.jpg"]
    fake_supabase.table.assert_any_call("items")


async def test_get_item_by_id_preserves_translations(client, patch_supabase, fake_supabase):
    from conftest import make_supabase_result as _make_supabase_result

    row = {
        "id": "item-tr",
        "name": "Widget",
        "translations": {
            "en": {"name": "Widget", "description": "English"},
            "ms": {"name": "Widget Melayu", "description": "Melayu"},
            "zh": {"name": "中文组件", "description": "中文"},
        },
    }
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        _make_supabase_result([row])
    )
    patch_supabase("connector", user=fake_supabase)

    response = await client.get("/items/item-tr")

    assert response.status_code == 200
    body = response.json()
    assert body["translations"]["ms"]["name"] == "Widget Melayu"


async def test_get_item_by_id_not_found_empty_data(client, patch_supabase, fake_supabase):
    from conftest import make_supabase_result as _make_supabase_result

    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        _make_supabase_result([])
    )
    patch_supabase("connector", user=fake_supabase)

    response = await client.get("/items/does-not-exist")

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


async def test_get_item_by_id_not_found_none_data(client, patch_supabase, fake_supabase):
    from conftest import make_supabase_result as _make_supabase_result

    result = _make_supabase_result(None)
    # make_supabase_result coerces None -> [] by default, force None explicitly
    # to exercise the `if response.data and ...` falsy branch either way.
    result.data = None
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = result
    patch_supabase("connector", user=fake_supabase)

    response = await client.get("/items/whatever-id")

    assert response.status_code == 404


async def test_get_item_by_id_soft_deleted_is_404(client, patch_supabase, fake_supabase):
    """Soft-deleted rows are filtered out by `.is_('deleted_at', 'null')` at the
    query layer, so from the route's point of view a soft-deleted item just
    looks like empty `.data` -> 404."""
    from conftest import make_supabase_result as _make_supabase_result

    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        _make_supabase_result([])
    )
    patch_supabase("connector", user=fake_supabase)

    response = await client.get("/items/soft-deleted-item")

    assert response.status_code == 404
    # Confirm the query actually filtered on deleted_at IS NULL.
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.assert_any_call("deleted_at", "null")


async def test_get_item_by_id_malformed_id_lookup_exception_is_404_not_500(client, patch_supabase, fake_supabase):
    """A malformed id (e.g. 'undefined', invalid UUID) can raise inside the
    Supabase client itself; the route catches this and returns 404 rather
    than letting it bubble up as a 500."""
    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.side_effect = (
        Exception("invalid input syntax for type uuid")
    )
    patch_supabase("connector", user=fake_supabase)

    response = await client.get("/items/undefined")

    assert response.status_code == 404
    assert "undefined" in response.json()["detail"]


async def test_get_item_by_id_uses_eq_id_filter(client, patch_supabase, fake_supabase):
    from conftest import make_supabase_result as _make_supabase_result

    fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = (
        _make_supabase_result([{"id": "abc", "name": "Thing", "image_path": None}])
    )
    patch_supabase("connector", user=fake_supabase)

    response = await client.get("/items/abc")

    assert response.status_code == 200
    fake_supabase.table.return_value.select.return_value.eq.assert_any_call("id", "abc")


# ---------------------------------------------------------------------------
# _to_public helper — direct unit tests for the image_path normalization logic
# ---------------------------------------------------------------------------

def test_to_public_dict_image_path():
    row = {"id": "1", "image_path": json.dumps({"a.jpg": "url-a", "b.jpg": "url-b"})}
    out = routes_items._to_public(row)
    assert out["item_id"] == "1"
    assert sorted(json.loads(out["images"])) == sorted(["url-a", "url-b"])


def test_to_public_list_image_path():
    row = {"id": "2", "image_path": json.dumps(["url-x", "url-y"])}
    out = routes_items._to_public(row)
    assert json.loads(out["images"]) == ["url-x", "url-y"]


def test_to_public_scalar_image_path():
    # A JSON-parseable scalar (e.g. a bare number/string) falls into the
    # "neither dict nor list" branch and wraps the *original raw* image_path
    # string (not the parsed scalar) as a single-element list.
    raw_image_path = json.dumps("just-a-string")  # '"just-a-string"'
    row = {"id": "3", "image_path": raw_image_path}
    out = routes_items._to_public(row)
    assert json.loads(out["images"]) == [raw_image_path]


def test_to_public_non_json_image_path():
    # Not valid JSON at all -> json.loads raises -> except branch wraps the
    # raw value as a single-element list.
    row = {"id": "4", "image_path": "not-json-{{{"}
    out = routes_items._to_public(row)
    assert json.loads(out["images"]) == ["not-json-{{{"]


def test_to_public_missing_image_path():
    row = {"id": "5"}
    out = routes_items._to_public(row)
    assert out["item_id"] == "5"
    assert json.loads(out["images"]) == []


def test_to_public_empty_string_image_path():
    row = {"id": "6", "image_path": ""}
    out = routes_items._to_public(row)
    assert json.loads(out["images"]) == []


# ---------------------------------------------------------------------------
# Event-loop safety
#
# The storefront is the highest-traffic surface in the app. Its Supabase reads
# are synchronous, so running them on the loop inside an `async def` handler
# serialises every concurrent visitor behind one another.
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def _loop_ticks():
    counter = {"ticks": 0}

    async def ticker():
        while True:
            await asyncio.sleep(0.01)
            counter["ticks"] += 1

    beat = asyncio.create_task(ticker())
    try:
        yield counter
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat


ROW = {"id": "item-1", "name": "Widget", "price": 10, "status": "available", "image_path": None}


async def test_listing_items_does_not_block_the_event_loop(client, monkeypatch):
    def slow_get_items(_keyword=None):
        time.sleep(0.2)
        return [ROW]

    monkeypatch.setattr(routes_items, "get_items", slow_get_items)

    async with _loop_ticks() as counter:
        response = await client.get("/items")

    assert response.status_code == 200
    assert response.json()[0]["item_id"] == "item-1"
    assert counter["ticks"] > 5


async def test_featured_items_do_not_block_the_event_loop(client, monkeypatch):
    def slow_featured(_limit=6):
        time.sleep(0.2)
        return [ROW]

    monkeypatch.setattr(routes_items, "get_featured_items", slow_featured)

    async with _loop_ticks() as counter:
        response = await client.get("/items/featured")

    assert response.status_code == 200
    assert counter["ticks"] > 5


async def test_single_item_lookup_does_not_block_the_event_loop(
    client, patch_supabase, fake_supabase
):
    from conftest import make_supabase_result

    def slow_execute():
        time.sleep(0.2)
        return make_supabase_result([ROW])

    (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .is_.return_value.execute
    ) = slow_execute
    patch_supabase("connector", user=fake_supabase)

    async with _loop_ticks() as counter:
        response = await client.get("/items/item-1")

    assert response.status_code == 200
    assert response.json()["item_id"] == "item-1"
    assert counter["ticks"] > 5
