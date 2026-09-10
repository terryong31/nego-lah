"""
Tests for items.py:
- compute_items_hash: determinism / sensitivity to inputs.
- get_items_fingerprint: cheap COUNT + MAX(created_at) query.
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
import time
from datetime import UTC, datetime

from PIL import Image, ImageFilter

from cache import cache_items_with_hash, redis_client
from conftest import PNG_BYTES, make_supabase_result
from core.images import MAX_ITEM_EDGE
from items import (
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

def configure_fingerprint(fake_user, *, count=3, latest_created_at="2024-05-01T00:00:00"):
    data = [{"created_at": latest_created_at}] if latest_created_at is not None else []
    chain = fake_user.table.return_value.select.return_value.is_.return_value
    chain.execute.return_value = make_supabase_result(data=[], count=count)
    chain.order.return_value.limit.return_value.execute.return_value = make_supabase_result(data=data)


def test_get_items_fingerprint_returns_count_and_latest_timestamp(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
    configure_fingerprint(fake_supabase, count=7, latest_created_at="2024-05-01T12:00:00")

    count, max_created_at = get_items_fingerprint()

    assert count == 7
    assert max_created_at == "2024-05-01T12:00:00"


def test_get_items_fingerprint_no_rows_returns_zero_count_and_empty_timestamp(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
    configure_fingerprint(fake_supabase, count=None, latest_created_at=None)

    count, max_created_at = get_items_fingerprint()

    assert count == 0
    assert max_created_at == ""


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
    patch_supabase("items", user=fake_supabase)
    items_data = [
        {"id": "1", "status": "available", "created_at": "2024-01-01T00:00:00"},
        {"id": "2", "status": "available", "created_at": "2024-01-02T00:00:00"},
    ]
    configure_full_fetch(fake_supabase, items_data)

    result = get_items()

    assert result == items_data
    # Should now be cached with a matching hash.
    from cache import get_cached_items_with_hash
    cached, cached_hash = get_cached_items_with_hash()
    assert cached == items_data
    expected_hash = compute_items_hash(2, "2024-01-02T00:00:00")
    assert cached_hash == expected_hash


def test_get_items_no_keyword_cache_miss_empty_db_returns_empty_list(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
    configure_full_fetch(fake_supabase, [])

    result = get_items()

    assert result == []


def test_get_items_cache_hit_validated_and_matching_returns_cached(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
    cached_data = [{"id": "cached-1", "created_at": "2024-03-01T00:00:00"}]
    cached_hash = compute_items_hash(1, "2024-03-01T00:00:00")
    cache_items_with_hash(cached_data, cached_hash)

    # should_validate_cache() must be True (no recent validation marker yet)
    assert redis_client.get("items:last_validation") is None
    configure_fingerprint(fake_supabase, count=1, latest_created_at="2024-03-01T00:00:00")

    result = get_items()

    assert result == cached_data
    # Validation marker set as a side effect of should_validate_cache().
    assert redis_client.get("items:last_validation") == "1"


def test_get_items_cache_hit_but_skips_validation_returns_cached_without_query(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
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
    patch_supabase("items", user=fake_supabase)
    stale_data = [{"id": "old", "created_at": "2024-01-01T00:00:00"}]
    stale_hash = compute_items_hash(1, "2024-01-01T00:00:00")
    cache_items_with_hash(stale_data, stale_hash)

    # Fingerprint reflects a DIFFERENT state than what's cached -> hash mismatch.
    configure_fingerprint(fake_supabase, count=99, latest_created_at="2024-09-09T00:00:00")

    fresh_data = [{"id": "fresh", "status": "available", "created_at": "2024-09-09T00:00:00"}]
    configure_full_fetch(fake_supabase, fresh_data)

    result = get_items()

    assert result == fresh_data
    from cache import get_cached_items_with_hash
    cached, _ = get_cached_items_with_hash()
    assert cached == fresh_data


def test_get_items_with_keyword_bypasses_cache_and_searches(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
    # Pre-populate cache to prove keyword search ignores it entirely.
    cache_items_with_hash([{"id": "irrelevant"}], "somehash")

    matched = [{"id": "kw-1", "description": "a red bicycle"}]
    configure_keyword_fetch(fake_supabase, matched)

    result = get_items(keyword="bicycle")

    assert result == matched


def test_get_items_with_keyword_no_matches_returns_empty_list(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
    configure_keyword_fetch(fake_supabase, [])

    result = get_items(keyword="nonexistent-thing")

    assert result == []


# ---------------------------------------------------------------------------
# get_featured_items
# ---------------------------------------------------------------------------

def test_get_featured_items_returns_data(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
    data = [{"id": "f1", "status": "available"}]
    chain = (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .is_.return_value.order.return_value.limit.return_value
    )
    chain.execute.return_value = make_supabase_result(data=data)

    result = get_featured_items(limit=6)

    assert result == data


def test_get_featured_items_empty_data_returns_empty_list(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
    chain = (
        fake_supabase.table.return_value.select.return_value.eq.return_value
        .is_.return_value.order.return_value.limit.return_value
    )
    chain.execute.return_value = make_supabase_result(data=None)

    result = get_featured_items()

    assert result == []


def test_get_featured_items_exception_falls_back_to_empty_list(patch_supabase, fake_supabase):
    patch_supabase("items", user=fake_supabase)
    fake_supabase.table.side_effect = Exception("supabase is down")

    result = get_featured_items()

    assert result == []


# ---------------------------------------------------------------------------
# upload_item
# ---------------------------------------------------------------------------

async def test_upload_item_success_uploads_images_and_inserts_row(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/img0.jpg"
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
    fake_supabase.storage.from_.assert_any_call("test-images")
    upload_call = fake_supabase.storage.from_.return_value.upload.call_args
    # SPEC-054: the extension and content type come from the DECODE, not from
    # the filename or the client's content_type (which claims jpeg here). This
    # PNG is too small for a re-encode to pay for itself, so the original bytes
    # are what gets stored.
    assert upload_call.kwargs["file"] == PNG_BYTES
    assert upload_call.kwargs["path"].endswith("/0.png")
    assert upload_call.kwargs["file_options"]["content-type"] == "image/png"

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
    urls = json.loads(item_data["image_path"])
    assert urls == {"0.png": "https://cdn.example.com/img0.jpg"}


async def test_upload_item_without_min_price_omits_it(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/img0.jpg"
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


async def test_upload_item_ignores_the_filename_entirely(patch_supabase, fake_supabase):
    """SPEC-054: the extension used to be `filename.split(".")[-1]`, so a photo
    with no filename was stored as `.dat` and a lying filename decided how the
    CDN would later serve the bytes. The decode decides both now, so a missing
    filename is simply irrelevant."""
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/img"

    images = [FakeUploadFile(filename=None, content=PNG_BYTES)]
    ok = await upload_item(
        name="NoExt",
        description="desc",
        condition="used",
        uploaded_images=images,
        price=1.0,
    )

    assert ok is True
    upload_call = fake_supabase.storage.from_.return_value.upload.call_args
    assert upload_call.kwargs["path"].endswith("/0.png")
    assert upload_call.kwargs["file_options"]["content-type"] == "image/png"


async def test_upload_item_rejects_a_payload_that_is_not_an_image(patch_supabase, fake_supabase):
    """A listing photo now goes through the same gate as an avatar (SPEC-044/054)."""
    patch_supabase("items", admin=fake_supabase)

    images = [FakeUploadFile("evil.png", content=b"<svg onload=alert(1)></svg>")]
    ok = await upload_item(
        name="Nope", description="desc", condition="used", uploaded_images=images, price=1.0
    )

    assert ok is False
    fake_supabase.storage.from_.return_value.upload.assert_not_called()


async def test_upload_item_downscales_and_recompresses_a_large_photo(patch_supabase, fake_supabase):
    """The whole point: a phone photo is not served to the storefront at 12 MP."""
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/img"
    fake_supabase.table.return_value.insert.return_value.execute.return_value = make_supabase_result([{"id": "x"}])

    big = _encode_photo((4000, 3000))
    ok = await upload_item(
        name="Big", description="desc", condition="used",
        uploaded_images=[FakeUploadFile("huge.jpg", content=big)], price=1.0,
    )

    assert ok is True
    stored = fake_supabase.storage.from_.return_value.upload.call_args.kwargs["file"]
    assert len(stored) < len(big)
    assert max(Image.open(io.BytesIO(stored)).size) == MAX_ITEM_EDGE


async def test_upload_item_multiple_images_all_uploaded(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/img"
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
    assert fake_supabase.storage.from_.return_value.upload.call_count == 3
    item_data = fake_supabase.table.return_value.insert.call_args.args[0]
    urls = json.loads(item_data["image_path"])
    # All three are the same PNG regardless of what they were named.
    assert set(urls.keys()) == {"0.png", "1.png", "2.png"}


async def test_upload_item_stores_images_in_the_order_they_were_given(patch_supabase, fake_supabase):
    """Uploads run concurrently, but the stored map must stay in input order --
    the storefront reads the first entry as the item's thumbnail."""
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.return_value = make_supabase_result([{"id": "x"}])

    # Make the first upload the slowest, so a naive gather-and-collect would
    # end up with it last.
    delays = {"0.png": 0.03, "1.png": 0.02, "2.png": 0.0}

    def slow_upload(*, file, path, file_options):
        time.sleep(delays[path.rsplit("/", 1)[-1]])

    fake_supabase.storage.from_.return_value.upload.side_effect = slow_upload
    fake_supabase.storage.from_.return_value.get_public_url.side_effect = (
        lambda path: f"https://cdn.example.com/{path}"
    )

    images = [FakeUploadFile("a.jpg"), FakeUploadFile("b.png"), FakeUploadFile("c.gif")]
    ok = await upload_item(
        name="Ordered",
        description="desc",
        condition="new",
        uploaded_images=images,
        price=1.0,
    )

    assert ok is True
    urls = json.loads(fake_supabase.table.return_value.insert.call_args.args[0]["image_path"])
    assert list(urls.keys()) == ["0.png", "1.png", "2.png"]


async def test_upload_item_exception_returns_false(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.storage.from_.return_value.upload.side_effect = Exception("storage exploded")

    images = [FakeUploadFile("a.jpg")]
    ok = await upload_item(
        name="Boom",
        description="desc",
        condition="new",
        uploaded_images=images,
        price=1.0,
    )

    assert ok is False


# ---------------------------------------------------------------------------
# sync_item_images
# ---------------------------------------------------------------------------


def _stub_current_images(fake_supabase, image_path):
    """Point the `select('image_path').eq('id', ...)` chain at a stored map."""
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"image_path": json.dumps(image_path)}])
    )


async def test_sync_item_images_keeps_a_subset_in_the_requested_order(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {
        "0.jpg": "https://cdn.example.com/a.jpg",
        "1.jpg": "https://cdn.example.com/b.jpg",
        "2.jpg": "https://cdn.example.com/c.jpg",
    })

    result = await sync_item_images(
        "item-1",
        ["https://cdn.example.com/c.jpg", "https://cdn.example.com/a.jpg"],
    )

    urls = json.loads(result)
    assert list(urls.items()) == [
        ("2.jpg", "https://cdn.example.com/c.jpg"),
        ("0.jpg", "https://cdn.example.com/a.jpg"),
    ]
    fake_supabase.storage.from_.return_value.upload.assert_not_called()


async def test_sync_item_images_uploads_new_files_at_their_requested_position(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"0.jpg": "https://cdn.example.com/a.jpg"})
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/new.png"

    result = await sync_item_images(
        "item-1",
        ["new:0", "https://cdn.example.com/a.jpg"],
        [FakeUploadFile("fresh.png", content=PNG_BYTES, content_type="image/png")],
    )

    urls = json.loads(result)
    assert list(urls.values()) == ["https://cdn.example.com/new.png", "https://cdn.example.com/a.jpg"]

    upload_call = fake_supabase.storage.from_.return_value.upload.call_args
    assert upload_call.kwargs["file"] == PNG_BYTES
    assert upload_call.kwargs["path"].startswith("items/item-1/")
    assert upload_call.kwargs["path"].endswith(".png")
    assert upload_call.kwargs["file_options"]["content-type"] == "image/png"


async def test_sync_item_images_names_new_uploads_uniquely(patch_supabase, fake_supabase):
    """A new photo must never overwrite the storage object of a kept one."""
    patch_supabase("items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"0.jpg": "https://cdn.example.com/a.jpg"})
    fake_supabase.storage.from_.return_value.get_public_url.side_effect = (
        lambda path: f"https://cdn.example.com/{path}"
    )

    result = await sync_item_images(
        "item-1",
        ["https://cdn.example.com/a.jpg", "new:0", "new:1"],
        [FakeUploadFile("x.jpg"), FakeUploadFile("y.jpg")],
    )

    urls = json.loads(result)
    assert len(urls) == 3
    assert "0.jpg" in urls  # the kept photo's key survives untouched
    assert urls["0.jpg"] == "https://cdn.example.com/a.jpg"


async def test_sync_item_images_drops_tokens_the_item_does_not_own(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"0.jpg": "https://cdn.example.com/a.jpg"})

    result = await sync_item_images(
        "item-1",
        ["https://evil.example.com/x.jpg", "new:7", "https://cdn.example.com/a.jpg"],
    )

    assert json.loads(result) == {"0.jpg": "https://cdn.example.com/a.jpg"}


async def test_sync_item_images_removes_storage_objects_that_dropped_out(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {
        "0.jpg": "https://cdn.example.com/a.jpg",
        "1.jpg": "https://cdn.example.com/b.jpg",
    })

    result = await sync_item_images("item-1", ["https://cdn.example.com/b.jpg"])

    assert json.loads(result) == {"1.jpg": "https://cdn.example.com/b.jpg"}
    fake_supabase.storage.from_.return_value.remove.assert_called_once_with(["items/item-1/0.jpg"])


async def test_sync_item_images_survives_a_failing_storage_remove(patch_supabase, fake_supabase):
    """Orphaned bytes are cheaper than a failed save the admin cannot retry."""
    patch_supabase("items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {
        "0.jpg": "https://cdn.example.com/a.jpg",
        "1.jpg": "https://cdn.example.com/b.jpg",
    })
    fake_supabase.storage.from_.return_value.remove.side_effect = Exception("storage down")

    result = await sync_item_images("item-1", ["https://cdn.example.com/b.jpg"])

    assert json.loads(result) == {"1.jpg": "https://cdn.example.com/b.jpg"}


async def test_sync_item_images_returns_empty_map_when_every_photo_is_dropped(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"0.jpg": "https://cdn.example.com/a.jpg"})

    result = await sync_item_images("item-1", [])

    assert json.loads(result) == {}
    fake_supabase.storage.from_.return_value.remove.assert_called_once_with(["items/item-1/0.jpg"])


async def test_sync_item_images_treats_an_unreadable_image_path_as_empty(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"image_path": "not-json"}])
    )
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/new.png"

    result = await sync_item_images("item-1", ["new:0"], [FakeUploadFile("fresh.png")])

    assert list(json.loads(result).values()) == ["https://cdn.example.com/new.png"]
    fake_supabase.storage.from_.return_value.remove.assert_not_called()


async def test_sync_item_images_upload_exception_returns_none(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    _stub_current_images(fake_supabase, {"0.jpg": "https://cdn.example.com/a.jpg"})
    fake_supabase.storage.from_.return_value.upload.side_effect = Exception("storage exploded")

    result = await sync_item_images("item-1", ["new:0"], [FakeUploadFile("fresh.png")])

    assert result is None


async def test_sync_item_images_missing_item_returns_none(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([])
    )

    result = await sync_item_images("ghost", ["https://cdn.example.com/a.jpg"])

    assert result is None


# ---------------------------------------------------------------------------
# delete_item
# ---------------------------------------------------------------------------

def test_delete_item_success_sets_deleted_at(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"id": "item-1"}])
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
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.table.side_effect = Exception("db unavailable")

    ok = delete_item("item-1")

    assert ok is False


# ---------------------------------------------------------------------------
# update_item
# ---------------------------------------------------------------------------

def test_update_item_no_fields_returns_false(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)

    ok = update_item("item-1")

    assert ok is False
    fake_supabase.table.assert_not_called()


def test_update_item_success_updates_given_fields(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"id": "item-1"}])
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
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        make_supabase_result([{"id": "item-1"}])
    )

    ok = update_item("item-1", description="Updated description")

    assert ok is True
    update_payload = fake_supabase.table.return_value.update.call_args.args[0]
    assert update_payload == {"description": "Updated description"}


def test_update_item_exception_returns_false(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.table.side_effect = Exception("db exploded")

    ok = update_item("item-1", name="whatever")

    assert ok is False
