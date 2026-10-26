import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import UploadFile

from core.cache import (
    cache_items_with_hash,
    get_cached_items_with_hash,
    invalidate_item_cache,
    redis_client,
)
from core.connector import admin_supabase, user_supabase
from core.images import MAX_ITEM_EDGE, process_upload
from core.logger import logger
from core.media import media_key, media_store, media_url, new_key

# ---------------------------------------------------------------------------
# Column boundary (SPEC-036)
# ---------------------------------------------------------------------------
# `items` holds seller-confidential data alongside the storefront's own fields.
# `min_price` is the negotiation floor — publishing it hands every buyer the
# reserve and makes the agent's haggling theatre. `buyer_id` names the
# purchaser, and `deleted_at` is bookkeeping.
#
# This is the allowlist, and it is closed: a column added to the table later
# does NOT start shipping publicly until it is named here. Postgres enforces
# the same split via column-level grants (see the items_column_privileges
# migration), so the anon key cannot read the confidential columns even by
# talking to PostgREST directly. Because of that revoke, `select('*')` on the
# anon client is now an *error*, not just a leak — the explicit select lists
# below are load-bearing.
PUBLIC_ITEM_COLUMNS: tuple[str, ...] = (
    "id",
    "name",
    "description",
    "condition",
    "price",
    "image_path",
    "status",
    "created_at",
    "translations",
)

CONFIDENTIAL_ITEM_COLUMNS: frozenset[str] = frozenset(
    {
        "min_price",
        "buyer_id",
        "deleted_at",
    }
)

# PostgREST select list for every query issued with the anon key.
PUBLIC_ITEM_SELECT = ", ".join(PUBLIC_ITEM_COLUMNS)


def image_urls(image_path: str | None) -> list[str]:
    """An item's photo URLs in display order, resolved for the client (SPEC-108).

    `image_path` is a JSON {filename: key} map; rows from before SPEC-108 hold
    Supabase URLs instead, and older still a JSON list or a bare string. Every
    shape resolves through `media_url`, so the client only ever sees the CDN.
    """
    if not image_path:
        return []
    try:
        parsed = json.loads(image_path)
    except (TypeError, ValueError):
        parsed = image_path
    if isinstance(parsed, dict):
        values = list(parsed.values())
    elif isinstance(parsed, list):
        values = parsed
    else:
        values = [image_path]
    return [media_url(value) for value in values if value]


def resolve_image_path(image_path: str | None) -> str | None:
    """`image_path` with each value resolved to its URL, shape and order kept.

    For the admin console, which edits the map: it sends kept photos back as
    the URLs it was given, and `sync_item_images` maps them back to keys.
    """
    try:
        parsed = json.loads(image_path) if image_path else None
    except (TypeError, ValueError):
        return image_path
    if not isinstance(parsed, dict):
        return image_path
    return json.dumps({name: media_url(value) for name, value in parsed.items()})


def compute_items_hash(count: int, max_created_at: str) -> str:
    """Compute SHA hash from item count and latest timestamp"""
    data = f"{count}:{max_created_at}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def get_items_fingerprint():
    """
    Get a lightweight fingerprint of items table.
    Queries only COUNT and MAX(updated_at) - much cheaper than full table scan.

    `updated_at` is set by a trigger on every write (SPEC-111), so an edit made
    outside the API — which never calls `invalidate_item_cache` — still changes
    the fingerprint. MAX(created_at) only ever moved on an insert.
    """
    # Query count (excluding soft-deleted items so the fingerprint matches the
    # filtered storefront data we actually cache below).
    count_response = user_supabase.table("items").select("id", count="exact").is_("deleted_at", "null").execute()
    item_count = count_response.count or 0

    # Query latest updated_at
    latest_response = (
        user_supabase.table("items")
        .select("updated_at")
        .is_("deleted_at", "null")
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    max_updated_at = latest_response.data[0]["updated_at"] if latest_response.data else ""

    return item_count, max_updated_at


def should_validate_cache() -> bool:
    """
    Check if we should validate cache against Supabase.
    Returns True only if 30 seconds have passed since last validation.
    This prevents hitting Supabase on every single request.
    """
    last_check = redis_client.get("items:last_validation")
    if last_check:
        return False  # Already validated recently, use cache

    # Mark that we're validating now (expires in 30 seconds)
    redis_client.setex("items:last_validation", 30, "1")
    return True


def get_items(keyword: str = None) -> list[str]:
    if keyword is None:
        # Get cached data and its hash
        cached, cached_hash = get_cached_items_with_hash()

        if cached and cached_hash:
            # Only validate against Supabase every 30 seconds
            if should_validate_cache():
                # Time to check if data has changed
                count, max_timestamp = get_items_fingerprint()
                current_hash = compute_items_hash(count, max_timestamp)

                if current_hash != cached_hash:
                    # Cache is stale - invalidate and refetch below
                    invalidate_item_cache()
                    cached = None
                else:
                    # Cache validated - return cached data
                    return cached
            else:
                # Skip validation - trust the cache
                return cached

        # Cache miss or stale - get full data from DB. The fingerprint is read
        # FIRST: if an edit lands between the two reads, the stored hash is the
        # older one and the next validation refetches. Read after, it could
        # pin stale rows behind a current hash.
        count, max_timestamp = get_items_fingerprint()
        # Order by status (available first) then by created_at (newest first)
        retrieve = (
            user_supabase.table("items")
            .select(PUBLIC_ITEM_SELECT)
            .is_("deleted_at", "null")
            .order("status", desc=False)
            .order("created_at", desc=True)
            .execute()
        )
        if retrieve.data:
            cache_items_with_hash(retrieve.data, compute_items_hash(count, max_timestamp))
            return retrieve.data
        return []
    else:
        # Keyword search - don't cache as results vary
        retrieve = (
            user_supabase.table("items")
            .select(PUBLIC_ITEM_SELECT)
            .is_("deleted_at", "null")
            .ilike("description", f"%{keyword}%")
            .order("status", desc=False)
            .order("created_at", desc=True)
            .execute()
        )
        if retrieve.data:
            return retrieve.data
        return []


def get_featured_items(limit: int = 6) -> list[dict]:
    """
    Get the most-interacted listings to feature on the home page.

    TODO: Once view/like tracking is in place, order by those metrics
    (e.g. .order('views', desc=True) or a popularity score). For now we
    fall back to the newest available listings as a sensible placeholder.
    """
    try:
        retrieve = (
            user_supabase.table("items")
            .select(PUBLIC_ITEM_SELECT)
            .eq("status", "available")
            .is_("deleted_at", "null")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return retrieve.data or []
    except Exception as e:
        logger.error(f"Failed to fetch featured items: {e}")
        return []


async def upload_item(
    name: str,
    description: str,
    condition: str,
    uploaded_images: list[UploadFile],
    price: float,
    min_price: float = None,
    translations: dict = None,
) -> bool:
    """
    Uploads images to the media store and creates an item in the database.

    Args:
        name: Item name
        description: Item description
        condition: Item condition
        uploaded_images: List of uploaded image files
        price: Listed price
        min_price: Base price (minimum acceptable price for negotiation)
        translations: Trilingual translations dictionary {en: {...}, ms: {...}, zh: {...}}
    """

    try:
        random_uuid = str(uuid.uuid4())

        async def upload_image(img: UploadFile) -> tuple[str, str]:
            raw = await img.read()
            # SPEC-054: the extension and content type come from what actually
            # decoded, never from `filename` / `content_type` — the browser's
            # word for both. Decoding also caps the pixels, compresses, and
            # converts a phone's HEIC into something a browser can render.
            # CPU-bound, so it goes to a thread like the upload itself.
            file_content, content_type, img_extension = await asyncio.to_thread(
                process_upload, raw, max_edge=MAX_ITEM_EDGE
            )
            # SPEC-108: a unique name, so the CDN can cache it forever, and the
            # row keeps the key — the URL is built when the item is served.
            # Each upload gets its own thread — otherwise a five-photo listing
            # pays for five round trips back to back.
            key = await asyncio.to_thread(
                media_store.put, new_key(f"items/{random_uuid}", img_extension), file_content, content_type
            )
            return key.rsplit("/", 1)[-1], key

        # gather preserves input order, so image 0 stays the thumbnail.
        keys = dict(await asyncio.gather(*(upload_image(img) for img in uploaded_images)))

        item_data = {
            "id": random_uuid,
            "name": name,
            "price": price,
            "description": description,
            "condition": condition,
            "image_path": json.dumps(keys),
            "status": "available",  # Default status for new items
            "created_at": datetime.now(UTC).isoformat(),
        }

        # Only include min_price if provided
        if min_price is not None:
            item_data["min_price"] = min_price

        if translations is not None:
            item_data["translations"] = translations

        admin_supabase.table("items").insert(item_data).execute()

        # Invalidate cache so new item shows up
        invalidate_item_cache()
        return True

    except Exception as e:
        logger.error(f"An error has occured! Error: {e}")
        return False


async def sync_item_images(item_id: str, ordered: list[str], new_images: list[UploadFile] = None) -> str | None:
    """
    Rebuild an item's image map from an ordered list of tokens (edit flow).

    `image_path` is a {filename: key} map whose insertion order *is* the display
    order, so this returns a freshly built map rather than patching the old one.
    Rows written before SPEC-108 hold Supabase URLs instead of keys; both resolve
    through `media_url`, and a kept photo is rewritten as its key.

    Args:
        item_id: Item whose photos are being replaced
        ordered: One token per photo, in display order (first = thumbnail).
            A token is either the public URL of a photo the item already has
            (as served now, or the legacy URL a stale page may still hold),
            or "new:<n>" naming the nth file in `new_images`. Anything else is
            dropped, so a stale client can never write a foreign URL into the row.
        new_images: Newly uploaded files referenced by the "new:<n>" tokens

    Returns:
        The JSON string for `image_path`, or None if the rebuild failed.
    """
    try:
        response = admin_supabase.table("items").select("image_path").eq("id", item_id).execute()
        if not response.data:
            return None

        try:
            current = json.loads(response.data[0].get("image_path") or "{}")
        except (TypeError, ValueError):
            current = {}
        if not isinstance(current, dict):
            current = {}

        # Kept photos arrive as URLs; map back to the filename that keys them.
        by_url = {media_url(value): name for name, value in current.items()}

        async def upload_new(img: UploadFile) -> tuple[str, str]:
            raw = await img.read()
            file_content, content_type, img_extension = await asyncio.to_thread(
                process_upload, raw, max_edge=MAX_ITEM_EDGE
            )
            # Random names, not positional ones: a photo added at slot 0 must
            # never overwrite the object of a photo the listing still points at.
            key = await asyncio.to_thread(
                media_store.put, new_key(f"items/{item_id}", img_extension), file_content, content_type
            )
            return key.rsplit("/", 1)[-1], key

        uploaded = list(await asyncio.gather(*(upload_new(img) for img in (new_images or []))))

        urls = {}
        for token in ordered:
            if token.startswith("new:"):
                try:
                    img_name, key = uploaded[int(token[4:])]
                except (ValueError, IndexError):
                    continue
                urls[img_name] = key
            elif media_url(token) in by_url:
                name = by_url[media_url(token)]
                urls[name] = media_key(current[name]) or current[name]

        dropped = [key for name, value in current.items() if name not in urls if (key := media_key(value))]
        if dropped:
            try:
                await asyncio.to_thread(media_store.delete, dropped)
            except Exception as e:
                # Orphaned bytes are cheaper than a save the admin can't retry.
                logger.warning(f"Failed to remove dropped images for item {item_id}: {e}")

        return json.dumps(urls)

    except Exception as e:
        logger.error(f"Failed to sync images for item {item_id}: {e}")
        return None


def delete_item(item_id: str) -> bool:
    """Soft-delete an item: hide it from the storefront without destroying history.

    We deliberately do NOT hard-delete the row, nor touch the related orders /
    conversations. Buyers who purchased this item keep it in their order history,
    and the order view can still read the (now-hidden) item for its name/image.
    Storefront and admin listings filter out rows where `deleted_at` is set.
    """
    try:
        admin_supabase.table("items").update({"deleted_at": datetime.now(UTC).isoformat()}).eq("id", item_id).execute()
        invalidate_item_cache(item_id)  # Clear cache so it drops off the storefront
        return True
    except Exception as e:
        logger.error(f"Failed to delete item {item_id}: {e}")
        return False


def update_item(
    item_id: str,
    name: str = None,
    description: str = None,
    condition: str = None,
    price: float = None,
    min_price: float = None,
    images: str = None,
    translations: dict = None,
):
    """
    Update an item in the database.

    Args:
        item_id: Item ID to update
        name: New name (optional)
        description: New description (optional)
        condition: New condition (optional)
        price: New listed price (optional)
        min_price: New base price (optional)
        images: New images JSON (optional)
        translations: New translations dict (optional)
    """
    try:
        update = {}
        if name:
            update["name"] = name
        if description:
            update["description"] = description
        if condition:
            update["condition"] = condition
        if price is not None:
            update["price"] = float(price)
        if min_price is not None:
            update["min_price"] = float(min_price)
        if images:
            update["image_path"] = images
        if translations is not None:
            update["translations"] = translations

        if not update:
            return False

        admin_supabase.table("items").update(update).eq("id", item_id).execute()
        invalidate_item_cache(item_id)  # Clear cache
        return True
    except Exception as e:
        logger.error(f"Something wrong! Error: {e}")
        return False
