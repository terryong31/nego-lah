"""
Tests for items.py:
- compute_items_hash: determinism / sensitivity to inputs.
- get_items_fingerprint: cheap COUNT + MAX(created_at) query.
- should_validate_cache: Redis-backed 30s debounce gate.
- get_items: cache hit / stale-cache / cache-miss / keyword-search paths.
- get_featured_items: success path + broad-except-returns-[] fallback.
- upload_item: async image upload + item insert, and its except-returns-False path.
- delete_item / update_item: soft delete / partial update, and their
  except-returns-False fallback paths.
"""
import json
import time

from cache import cache_items_with_hash, redis_client
from conftest import make_supabase_result
from items import (
    compute_items_hash,
    delete_item,
    get_featured_items,
    get_items,
    get_items_fingerprint,
    should_validate_cache,
    update_item,
    upload_item,
)


class FakeUploadFile:
    """Minimal stand-in for fastapi.UploadFile -- upload_item only touches
    `.filename`, `.content_type`, and `await .read()`."""

    def __init__(self, filename, content=b"fake-bytes", content_type="image/jpeg"):
        self.filename = filename
        self.content_type = content_type
        self._content = content

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

    images = [FakeUploadFile("photo.png", content=b"pngdata")]
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
    assert upload_call.kwargs["file"] == b"pngdata"
    assert upload_call.kwargs["path"].endswith("/0.png")
    assert upload_call.kwargs["file_options"]["content-type"] == "image/jpeg"

    insert_call = fake_supabase.table.return_value.insert.call_args
    item_data = insert_call.args[0]
    assert item_data["name"] == "Widget"
    assert item_data["description"] == "A nice widget"
    assert item_data["condition"] == "new"
    assert item_data["price"] == 19.99
    assert item_data["min_price"] == 9.99
    assert item_data["status"] == "available"
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


async def test_upload_item_missing_filename_defaults_extension_to_dat(patch_supabase, fake_supabase):
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.storage.from_.return_value.get_public_url.return_value = "https://cdn.example.com/img"

    images = [FakeUploadFile(filename=None)]
    ok = await upload_item(
        name="NoExt",
        description="desc",
        condition="used",
        uploaded_images=images,
        price=1.0,
    )

    assert ok is True
    upload_call = fake_supabase.storage.from_.return_value.upload.call_args
    assert upload_call.kwargs["path"].endswith("/0.dat")


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
    assert set(urls.keys()) == {"0.jpg", "1.png", "2.gif"}


async def test_upload_item_stores_images_in_the_order_they_were_given(patch_supabase, fake_supabase):
    """Uploads run concurrently, but the stored map must stay in input order --
    the storefront reads the first entry as the item's thumbnail."""
    patch_supabase("items", admin=fake_supabase)
    fake_supabase.table.return_value.insert.return_value.execute.return_value = make_supabase_result([{"id": "x"}])

    # Make the first upload the slowest, so a naive gather-and-collect would
    # end up with it last.
    delays = {"0.jpg": 0.03, "1.png": 0.02, "2.gif": 0.0}

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
    assert list(urls.keys()) == ["0.jpg", "1.png", "2.gif"]


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
    assert "deleted_at" in update_payload
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
