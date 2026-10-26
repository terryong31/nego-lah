"""
Tests for items.py:
- compute_items_hash: determinism / sensitivity to inputs.
- get_items_fingerprint: cheap COUNT + MAX(updated_at) query.
- should_validate_cache: Redis-backed 30s debounce gate.
- get_items: cache hit / stale-cache / cache-miss / keyword-search paths.
- get_featured_items: success path + broad-except-returns-[] fallback.
- upload_item: async image upload + item insert, and its except-returns-False path.
- sync_item_images: rebuilding an item's ordered image map on edit.
- delete_item / update_item: soft delete / partial update, and their
  except-returns-False fallback paths.
"""

import io
import json
import re
import time
from datetime import UTC, datetime

from PIL import Image, ImageFilter

from conftest import PNG_BYTES, make_supabase_result
from core.cache import cache_items_with_hash, redis_client
from core.images import MAX_ITEM_EDGE
from domains.catalog.items import (
    compute_items_hash,
    delete_item,
    get_featured_items,
    get_items,
    get_items_fingerprint,
    should_validate_cache,
    sync_item_images,
    update_item,
    upload_item,
)


def _encode_photo(size) -> bytes:
    """A photographic JPEG of a given size — blurred noise, not a flat fill, so
    the compression assertions describe what a real photo does."""
    channels = [Image.effect_noise(size, 64).filter(ImageFilter.GaussianBlur(2)) for _ in range(3)]
    buf = io.BytesIO()
    Image.merge("RGB", channels).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


class FakeUploadFile:
    """Minimal stand-in for fastapi.UploadFile -- upload_item only touches
    `.filename`, `.content_type`, and `await .read()`.

    Since SPEC-054 the bytes are DECODED on the way in, so `content` has to be a
    real image; `filename` and `content_type` are still accepted (and still
    passed by these tests) precisely so we can assert they no longer decide
    anything about what gets stored."""

    def __init__(self, filename, content=None, content_type="image/jpeg"):
        self.filename = filename
        self.content_type = content_type
        self._content = PNG_BYTES if content is None else content

    async def read(self):
        return self._content


# ---------------------------------------------------------------------------
# compute_items_hash
# ---------------------------------------------------------------------------


def test_compute_items_hash_deterministic_for_same_inputs():
    h1 = compute_items_hash(5, "2024-01-01T00:00:00")
    h2 = compute_items_hash(5, "2024-01-01T00:00:00")
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 16


def test_compute_items_hash_differs_for_different_count():
    h1 = compute_items_hash(5, "2024-01-01T00:00:00")
    h2 = compute_items_hash(6, "2024-01-01T00:00:00")
    assert h1 != h2


def test_compute_items_hash_differs_for_different_timestamp():
    h1 = compute_items_hash(5, "2024-01-01T00:00:00")
    h2 = compute_items_hash(5, "2024-01-02T00:00:00")
    assert h1 != h2


# ---------------------------------------------------------------------------
# get_items_fingerprint
# ---------------------------------------------------------------------------


def configure_fingerprint(fake_user, *, count=3, latest_updated_at="2024-05-01T00:00:00"):
    data = [{"updated_at": latest_updated_at}] if latest_updated_at is not None else []
    chain = fake_user.table.return_value.select.return_value.is_.return_value
    chain.execute.return_value = make_supabase_result(data=[], count=count)
    chain.order.return_value.limit.return_value.execute.return_value = make_supabase_result(data=data)


def test_get_items_fingerprint_returns_count_and_latest_timestamp(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    configure_fingerprint(fake_supabase, count=7, latest_updated_at="2024-05-01T12:00:00")

    count, max_updated_at = get_items_fingerprint()

    assert count == 7
    assert max_updated_at == "2024-05-01T12:00:00"
    # SPEC-111: an edit (Studio included) bumps updated_at; created_at never moves.
    chain = fake_supabase.table.return_value.select.return_value.is_.return_value
    chain.order.assert_called_once_with("updated_at", desc=True)


def test_get_items_fingerprint_no_rows_returns_zero_count_and_empty_timestamp(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    configure_fingerprint(fake_supabase, count=None, latest_updated_at=None)

    count, max_updated_at = get_items_fingerprint()

    assert count == 0
    assert max_updated_at == ""


# ---------------------------------------------------------------------------
# should_validate_cache
# ---------------------------------------------------------------------------


def test_should_validate_cache_true_when_no_recent_validation():
    assert redis_client.get("items:last_validation") is None
    assert should_validate_cache() is True
    # Marks validation as having happened.
    assert redis_client.get("items:last_validation") == "1"


def test_should_validate_cache_false_within_debounce_window():
    redis_client.setex("items:last_validation", 30, "1")
    assert should_validate_cache() is False


# ---------------------------------------------------------------------------
# get_items
# ---------------------------------------------------------------------------


def configure_full_fetch(fake_user, data):
    chain = fake_user.table.return_value.select.return_value.is_.return_value
    chain.order.return_value.order.return_value.execute.return_value = make_supabase_result(data=data)


def configure_keyword_fetch(fake_user, data):
    chain = fake_user.table.return_value.select.return_value.is_.return_value.ilike.return_value
    chain.order.return_value.order.return_value.execute.return_value = make_supabase_result(data=data)


def test_get_items_no_keyword_cache_miss_fetches_and_caches(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    items_data = [
        {"id": "1", "status": "available", "created_at": "2024-01-01T00:00:00"},
        {"id": "2", "status": "available", "created_at": "2024-01-02T00:00:00"},
    ]
    configure_full_fetch(fake_supabase, items_data)
    configure_fingerprint(fake_supabase, count=2, latest_updated_at="2024-02-02T00:00:00")

    result = get_items()

    assert result == items_data
    # Cached under the fingerprint the validator will compare against — the
    # same query, so an edit to an existing row is not invisible to it.
    from core.cache import get_cached_items_with_hash

    cached, cached_hash = get_cached_items_with_hash()
    assert cached == items_data
    assert cached_hash == compute_items_hash(2, "2024-02-02T00:00:00")


def test_get_items_no_keyword_cache_miss_empty_db_returns_empty_list(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    configure_full_fetch(fake_supabase, [])

    result = get_items()

    assert result == []


def test_get_items_cache_hit_validated_and_matching_returns_cached(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    cached_data = [{"id": "cached-1", "created_at": "2024-03-01T00:00:00"}]
    cached_hash = compute_items_hash(1, "2024-03-01T00:00:00")
    cache_items_with_hash(cached_data, cached_hash)

    # should_validate_cache() must be True (no recent validation marker yet)
    assert redis_client.get("items:last_validation") is None
    configure_fingerprint(fake_supabase, count=1, latest_updated_at="2024-03-01T00:00:00")

    result = get_items()

    assert result == cached_data
    # Validation marker set as a side effect of should_validate_cache().
    assert redis_client.get("items:last_validation") == "1"


def test_get_items_cache_hit_but_skips_validation_returns_cached_without_query(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    cached_data = [{"id": "cached-2", "created_at": "2024-03-01T00:00:00"}]
    cached_hash = compute_items_hash(1, "2024-03-01T00:00:00")
    cache_items_with_hash(cached_data, cached_hash)

    # Mark validation as already having happened recently -> should_validate_cache() False.
    redis_client.setex("items:last_validation", 30, "1")

    result = get_items()

    assert result == cached_data
    # Fingerprint query should never have been attempted.
    fake_supabase.table.assert_not_called()


def test_get_items_cache_stale_invalidates_and_refetches(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    stale_data = [{"id": "old", "created_at": "2024-01-01T00:00:00"}]
    stale_hash = compute_items_hash(1, "2024-01-01T00:00:00")
    cache_items_with_hash(stale_data, stale_hash)

    # Fingerprint reflects a DIFFERENT state than what's cached -> hash mismatch.
    configure_fingerprint(fake_supabase, count=99, latest_updated_at="2024-09-09T00:00:00")

    fresh_data = [{"id": "fresh", "status": "available", "created_at": "2024-09-09T00:00:00"}]
    configure_full_fetch(fake_supabase, fresh_data)

    result = get_items()

    assert result == fresh_data
    from core.cache import get_cached_items_with_hash

    cached, _ = get_cached_items_with_hash()
    assert cached == fresh_data


def test_get_items_with_keyword_bypasses_cache_and_searches(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    # Pre-populate cache to prove keyword search ignores it entirely.
    cache_items_with_hash([{"id": "irrelevant"}], "somehash")

    matched = [{"id": "kw-1", "description": "a red bicycle"}]
    configure_keyword_fetch(fake_supabase, matched)

    result = get_items(keyword="bicycle")

    assert result == matched


def test_get_items_with_keyword_no_matches_returns_empty_list(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    configure_keyword_fetch(fake_supabase, [])

    result = get_items(keyword="nonexistent-thing")

    assert result == []


# ---------------------------------------------------------------------------
# get_featured_items
# ---------------------------------------------------------------------------


def test_get_featured_items_returns_data(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    data = [{"id": "f1", "status": "available"}]
    chain = fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.limit.return_value
    chain.execute.return_value = make_supabase_result(data=data)

    result = get_featured_items(limit=6)

    assert result == data


def test_get_featured_items_empty_data_returns_empty_list(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    chain = fake_supabase.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.limit.return_value
    chain.execute.return_value = make_supabase_result(data=None)

    result = get_featured_items()

    assert result == []


def test_get_featured_items_exception_falls_back_to_empty_list(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", user=fake_supabase)
    fake_supabase.table.side_effect = Exception("supabase is down")

    result = get_featured_items()

    assert result == []


# ---------------------------------------------------------------------------
# upload_item
# ---------------------------------------------------------------------------

CDN = "https://media.example.test"
LEGACY = "https://test-project.supabase.co/storage/v1/object/public/test-images"
_ITEM_KEY = re.compile(r"^items/[0-9a-f-]{36}/[0-9a-f]{16}\.png$")


def _tiny_png(size: int) -> bytes:
    """A distinct, tiny PNG — too small for a re-encode to pay, so stored as-is."""
    buf = io.BytesIO()
    Image.new("RGB", (size, size), (size, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


async def test_upload_item_success_uploads_images_and_inserts_row(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.return_value = make_supabase_result([{"id": "x"}])

    images = [FakeUploadFile("photo.png", content=PNG_BYTES)]
    ok = await upload_item(
        name="Widget",
        description="A nice widget",
        condition="new",
        uploaded_images=images,
        price=19.99,
        min_price=9.99,
    )

    assert ok is True
    key, body, content_type = fake_media.put.call_args.args
    # SPEC-054: the extension and content type come from the DECODE, not from
    # the filename or the client's content_type (which claims jpeg here). This
    # PNG is too small for a re-encode to pay for itself, so the original bytes
    # are what gets stored.
    assert body == PNG_BYTES
    assert content_type == "image/png"
    # SPEC-108: a unique name under the item, so the CDN can cache it forever.
    assert _ITEM_KEY.match(key)

    insert_call = fake_supabase.table.return_value.insert.call_args
    item_data = insert_call.args[0]
    assert item_data["name"] == "Widget"
    assert item_data["description"] == "A nice widget"
    assert item_data["condition"] == "new"
    assert item_data["price"] == 19.99
    assert item_data["min_price"] == 9.99
    assert item_data["status"] == "available"
    # SPEC-066: `created_at` is a `timestamptz`, so a naive literal means
    # whatever zone the API host happens to be in — eight hours out, here.
    created_at = datetime.fromisoformat(item_data["created_at"])
    assert created_at.tzinfo is not None
    assert abs((created_at - datetime.now(UTC)).total_seconds()) < 5
    assert key.startswith(f"items/{item_data['id']}/")
    # SPEC-108: the row holds the key, never a URL.
    assert json.loads(item_data["image_path"]) == {key.rsplit("/", 1)[-1]: key}


async def test_upload_item_without_min_price_omits_it(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.return_value = make_supabase_result([{"id": "x"}])

    images = [FakeUploadFile("photo.jpg")]
    ok = await upload_item(
        name="Gadget",
        description="desc",
        condition="used",
        uploaded_images=images,
        price=5.0,
    )

    assert ok is True
    item_data = fake_supabase.table.return_value.insert.call_args.args[0]
    assert "min_price" not in item_data


async def test_upload_item_ignores_the_filename_entirely(patch_supabase, fake_supabase, fake_media):
    """SPEC-054: the extension used to be `filename.split(".")[-1]`, so a photo
    with no filename was stored as `.dat` and a lying filename decided how the
    CDN would later serve the bytes. The decode decides both now, so a missing
    filename is simply irrelevant."""
    patch_supabase("domains.catalog.items", admin=fake_supabase)

    images = [FakeUploadFile(filename=None, content=PNG_BYTES)]
    ok = await upload_item(
        name="NoExt",
        description="desc",
        condition="used",
        uploaded_images=images,
        price=1.0,
    )

    assert ok is True
    key, _, content_type = fake_media.put.call_args.args
    assert key.endswith(".png")
    assert content_type == "image/png"


async def test_upload_item_rejects_a_payload_that_is_not_an_image(patch_supabase, fake_supabase, fake_media):
    """A listing photo now goes through the same gate as an avatar (SPEC-044/054)."""
    patch_supabase("domains.catalog.items", admin=fake_supabase)

    images = [FakeUploadFile("evil.png", content=b"<svg onload=alert(1)></svg>")]
    ok = await upload_item(name="Nope", description="desc", condition="used", uploaded_images=images, price=1.0)

    assert ok is False
    fake_media.put.assert_not_called()


async def test_upload_item_downscales_and_recompresses_a_large_photo(patch_supabase, fake_supabase, fake_media):
    """The whole point: a phone photo is not served to the storefront at 12 MP."""
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.return_value = make_supabase_result([{"id": "x"}])

    big = _encode_photo((4000, 3000))
    ok = await upload_item(
        name="Big",
        description="desc",
        condition="used",
        uploaded_images=[FakeUploadFile("huge.jpg", content=big)],
        price=1.0,
    )

    assert ok is True
    stored = fake_media.put.call_args.args[1]
    assert len(stored) < len(big)
    assert max(Image.open(io.BytesIO(stored)).size) == MAX_ITEM_EDGE


async def test_upload_item_multiple_images_all_uploaded_under_distinct_keys(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.return_value = make_supabase_result([{"id": "x"}])

    images = [FakeUploadFile("a.jpg"), FakeUploadFile("b.png"), FakeUploadFile("c.gif")]
    ok = await upload_item(
        name="Multi",
        description="desc",
        condition="new",
        uploaded_images=images,
        price=1.0,
    )

    assert ok is True
    assert fake_media.put.call_count == 3
    keys = json.loads(fake_supabase.table.return_value.insert.call_args.args[0]["image_path"])
    # Three identical PNGs, three objects: a name is never reused.
    assert len(set(keys.values())) == 3
    assert all(_ITEM_KEY.match(key) for key in keys.values())


async def test_upload_item_stores_images_in_the_order_they_were_given(patch_supabase, fake_supabase, fake_media):
    """Uploads run concurrently, but the stored map must stay in input order --
    the storefront reads the first entry as the item's thumbnail."""
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.return_value = make_supabase_result([{"id": "x"}])

    bodies = [_tiny_png(n) for n in (1, 2, 3)]
    # Make the first upload the slowest, so a naive gather-and-collect would
    # end up with it last.
    delays = {bodies[0]: 0.03, bodies[1]: 0.02, bodies[2]: 0.0}
    key_for = {}

    def slow_put(key, body, content_type):
        time.sleep(delays[body])
        key_for[body] = key
        return key

    fake_media.put.side_effect = slow_put

    images = [FakeUploadFile(f"{n}.png", content=body) for n, body in enumerate(bodies)]
    ok = await upload_item(
        name="Ordered",
        description="desc",
        condition="new",
        uploaded_images=images,
        price=1.0,
    )

    assert ok is True
    keys = json.loads(fake_supabase.table.return_value.insert.call_args.args[0]["image_path"])
    assert list(keys.values()) == [key_for[body] for body in bodies]


async def test_upload_item_exception_returns_false(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_media.put.side_effect = Exception("storage exploded")

    images = [FakeUploadFile("a.jpg")]
    ok = await upload_item(
        name="Boom",
        description="desc",
        condition="new",
        uploaded_images=images,
        price=1.0,
    )

    assert ok is False
    fake_supabase.table.return_value.insert.assert_not_called()


# ---------------------------------------------------------------------------
# sync_item_images
# ---------------------------------------------------------------------------


def _stub_current_images(fake_supabase, image_path):
    """Point the `select('image_path').eq('id', ...)` chain at a stored map."""
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"image_path": json.dumps(image_path)}]
    )


async def test_sync_item_images_keeps_a_subset_in_the_requested_order(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(
        fake_supabase,
        {"a.jpg": "items/item-1/a.jpg", "b.jpg": "items/item-1/b.jpg", "c.jpg": "items/item-1/c.jpg"},
    )

    # The page sends back photos as it was served them: CDN URLs.
    result = await sync_item_images("item-1", [f"{CDN}/items/item-1/c.jpg", f"{CDN}/items/item-1/a.jpg"])

    assert list(json.loads(result).items()) == [("c.jpg", "items/item-1/c.jpg"), ("a.jpg", "items/item-1/a.jpg")]
    fake_media.put.assert_not_called()


async def test_sync_item_images_rewrites_a_kept_legacy_url_as_its_key(patch_supabase, fake_supabase, fake_media):
    """A pre-SPEC-108 row holds Supabase URLs. Whether the page sends the photo
    back as the CDN URL it is served now or the legacy URL a stale tab still
    holds, the photo is kept — and stored as a key from then on."""
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(
        fake_supabase,
        {"0.jpeg": f"{LEGACY}/items/item-1/0.jpeg?", "1.jpeg": f"{LEGACY}/items/item-1/1.jpeg"},
    )

    result = await sync_item_images("item-1", [f"{CDN}/items/item-1/1.jpeg", f"{LEGACY}/items/item-1/0.jpeg"])

    assert list(json.loads(result).items()) == [("1.jpeg", "items/item-1/1.jpeg"), ("0.jpeg", "items/item-1/0.jpeg")]
    fake_media.delete.assert_not_called()


async def test_sync_item_images_uploads_new_files_at_their_requested_position(
    patch_supabase, fake_supabase, fake_media
):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"a.jpg": "items/item-1/a.jpg"})

    result = await sync_item_images(
        "item-1",
        ["new:0", f"{CDN}/items/item-1/a.jpg"],
        [FakeUploadFile("fresh.png", content=PNG_BYTES, content_type="image/png")],
    )

    key, body, content_type = fake_media.put.call_args.args
    assert list(json.loads(result).values()) == [key, "items/item-1/a.jpg"]
    assert body == PNG_BYTES
    assert key.startswith("items/item-1/") and key.endswith(".png")
    assert content_type == "image/png"


async def test_sync_item_images_names_new_uploads_uniquely(patch_supabase, fake_supabase, fake_media):
    """A new photo must never overwrite the storage object of a kept one."""
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"0.jpg": "items/item-1/0.jpg"})

    result = await sync_item_images(
        "item-1",
        [f"{CDN}/items/item-1/0.jpg", "new:0", "new:1"],
        [FakeUploadFile("x.jpg"), FakeUploadFile("y.jpg")],
    )

    keys = json.loads(result)
    assert len(set(keys.values())) == 3
    assert keys["0.jpg"] == "items/item-1/0.jpg"  # the kept photo survives untouched


async def test_sync_item_images_drops_tokens_the_item_does_not_own(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"a.jpg": "items/item-1/a.jpg"})

    result = await sync_item_images(
        "item-1",
        [
            "https://evil.example.com/x.jpg",
            "new:7",
            f"{CDN}/items/other-item/z.jpg",
            f"{CDN}/items/item-1/a.jpg",
        ],
    )

    assert json.loads(result) == {"a.jpg": "items/item-1/a.jpg"}


async def test_sync_item_images_removes_storage_objects_that_dropped_out(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(
        fake_supabase,
        {"0.jpeg": f"{LEGACY}/items/item-1/0.jpeg?", "b.jpg": "items/item-1/b.jpg"},
    )

    result = await sync_item_images("item-1", [f"{CDN}/items/item-1/b.jpg"])

    assert json.loads(result) == {"b.jpg": "items/item-1/b.jpg"}
    # A legacy URL is deleted by the key it names.
    fake_media.delete.assert_called_once_with(["items/item-1/0.jpeg"])


async def test_sync_item_images_survives_a_failing_storage_remove(patch_supabase, fake_supabase, fake_media):
    """Orphaned bytes are cheaper than a failed save the admin cannot retry."""
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"a.jpg": "items/item-1/a.jpg", "b.jpg": "items/item-1/b.jpg"})
    fake_media.delete.side_effect = Exception("storage down")

    result = await sync_item_images("item-1", [f"{CDN}/items/item-1/b.jpg"])

    assert json.loads(result) == {"b.jpg": "items/item-1/b.jpg"}


async def test_sync_item_images_never_deletes_a_url_that_is_not_ours(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"0.jpg": "https://cdn.example.com/a.jpg"})

    assert json.loads(await sync_item_images("item-1", [])) == {}
    fake_media.delete.assert_not_called()


async def test_sync_item_images_returns_empty_map_when_every_photo_is_dropped(
    patch_supabase, fake_supabase, fake_media
):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"a.jpg": "items/item-1/a.jpg"})

    result = await sync_item_images("item-1", [])

    assert json.loads(result) == {}
    fake_media.delete.assert_called_once_with(["items/item-1/a.jpg"])


async def test_sync_item_images_treats_an_unreadable_image_path_as_empty(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"image_path": "not-json"}]
    )

    result = await sync_item_images("item-1", ["new:0"], [FakeUploadFile("fresh.png")])

    assert list(json.loads(result).values()) == [fake_media.put.call_args.args[0]]
    fake_media.delete.assert_not_called()


async def test_sync_item_images_upload_exception_returns_none(patch_supabase, fake_supabase, fake_media):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"a.jpg": "items/item-1/a.jpg"})
    fake_media.put.side_effect = Exception("storage exploded")

    result = await sync_item_images("item-1", ["new:0"], [FakeUploadFile("fresh.png")])

    assert result is None


async def test_sync_item_images_missing_item_returns_none(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = make_supabase_result([])

    result = await sync_item_images("ghost", ["https://media.example.test/items/ghost/a.jpg"])

    assert result is None


# ---------------------------------------------------------------------------
# delete_item
# ---------------------------------------------------------------------------


def test_delete_item_success_sets_deleted_at(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"id": "item-1"}]
    )

    ok = delete_item("item-1")

    assert ok is True
    update_call = fake_supabase.table.return_value.update.call_args
    update_payload = update_call.args[0]
    deleted_at = datetime.fromisoformat(update_payload["deleted_at"])
    assert deleted_at.tzinfo is not None, "SPEC-066 — a soft delete is dated in UTC"
    assert abs((deleted_at - datetime.now(UTC)).total_seconds()) < 5
    fake_supabase.table.return_value.update.return_value.eq.assert_called_with("id", "item-1")


def test_delete_item_exception_returns_false(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.side_effect = Exception("db unavailable")

    ok = delete_item("item-1")

    assert ok is False


# ---------------------------------------------------------------------------
# update_item
# ---------------------------------------------------------------------------


def test_update_item_no_fields_returns_false(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", admin=fake_supabase)

    ok = update_item("item-1")

    assert ok is False
    fake_supabase.table.assert_not_called()


def test_update_item_success_updates_given_fields(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"id": "item-1"}]
    )

    ok = update_item(
        "item-1",
        name="New Name",
        condition="refurbished",
        price=12,
        min_price=6,
        images=json.dumps({"0.jpg": "http://x"}),
    )

    assert ok is True
    update_payload = fake_supabase.table.return_value.update.call_args.args[0]
    assert update_payload["name"] == "New Name"
    assert update_payload["condition"] == "refurbished"
    assert update_payload["price"] == 12.0
    assert isinstance(update_payload["price"], float)
    assert update_payload["min_price"] == 6.0
    assert update_payload["image_path"] == json.dumps({"0.jpg": "http://x"})
    assert "description" not in update_payload
    fake_supabase.table.return_value.update.return_value.eq.assert_called_with("id", "item-1")


def test_update_item_partial_fields_only_includes_provided(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = make_supabase_result(
        [{"id": "item-1"}]
    )

    ok = update_item("item-1", description="Updated description")

    assert ok is True
    update_payload = fake_supabase.table.return_value.update.call_args.args[0]
    assert update_payload == {"description": "Updated description"}


def test_update_item_exception_returns_false(patch_supabase, fake_supabase):
    patch_supabase("domains.catalog.items", admin=fake_supabase)
    fake_supabase.table.side_effect = Exception("db exploded")

    ok = update_item("item-1", name="whatever")

    assert ok is False


def test_items_updated_at_migration_is_a_trigger_and_publishes_no_secret_column():
    """SPEC-111: the fingerprint reads `updated_at` as the storefront role, so it
    needs its own column grant — and that grant must not carry the floor price."""
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "20261027000000_items_updated_at.sql"
    ).read_text()
    grant = sql[sql.index("grant select") :].split(";")[0]

    assert "updated_at" in grant
    assert "min_price" not in grant and "buyer_id" not in grant
    assert "before update on public.items" in sql
