import asyncio
import hashlib
import json
import uuid
from datetime import datetime

from fastapi import UploadFile

from cache import (
    cache_items_with_hash,
    get_cached_items_with_hash,
    invalidate_item_cache,
    redis_client,
)
from connector import admin_supabase, user_supabase
from env import STORAGE_BUCKET
from logger import logger


def compute_items_hash(count: int, max_created_at: str) -> str:
    """Compute SHA hash from item count and latest timestamp"""
    data = f"{count}:{max_created_at}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def get_items_fingerprint():
    """
    Get a lightweight fingerprint of items table.
    Queries only COUNT and MAX(created_at) - much cheaper than full table scan.
    """
    # Query count (excluding soft-deleted items so the fingerprint matches the
    # filtered storefront data we actually cache below).
    count_response = user_supabase.table('items').select('id', count='exact').is_('deleted_at', 'null').execute()
    item_count = count_response.count or 0

    # Query latest created_at
    latest_response = user_supabase.table('items').select('created_at').is_('deleted_at', 'null').order('created_at', desc=True).limit(1).execute()
    max_created_at = latest_response.data[0]['created_at'] if latest_response.data else ""

    return item_count, max_created_at


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

        # Cache miss or stale - get full data from DB
        # Order by status (available first) then by created_at (newest first)
        retrieve = user_supabase.table('items').select('*').is_('deleted_at', 'null').order('status', desc=False).order('created_at', desc=True).execute()
        if retrieve.data:
            # Compute hash and cache with it
            count = len(retrieve.data)
            max_timestamp = max((item.get('created_at', '') for item in retrieve.data), default='')
            data_hash = compute_items_hash(count, max_timestamp)
            cache_items_with_hash(retrieve.data, data_hash)
            return retrieve.data
        return []
    else:
        # Keyword search - don't cache as results vary
        retrieve = user_supabase.table('items').select('*').is_('deleted_at', 'null').ilike('description', f'%{keyword}%').order('status', desc=False).order('created_at', desc=True).execute()
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
            user_supabase.table('items')
            .select('*')
            .eq('status', 'available')
            .is_('deleted_at', 'null')
            .order('created_at', desc=True)
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
    translations: dict = None
    ) -> bool:
    """
    Uploads images to Supabase Storage and creates an item in the database.

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

        async def upload_image(i: int, img: UploadFile) -> tuple[str, str]:
            img_extension = img.filename.split(".")[-1] if img.filename else "dat"
            img_name = f"{i}.{img_extension}"
            file_content = await img.read()
            # The storage client is synchronous, so each upload gets its own
            # thread — otherwise a five-photo listing pays for five round trips
            # back to back.
            await asyncio.to_thread(
                admin_supabase.storage.from_(STORAGE_BUCKET).upload,
                file=file_content,
                path=f"items/{random_uuid}/{img_name}",
                file_options={"content-type": img.content_type or "application/octet-stream"}
            )
            public_url_response = admin_supabase.storage.from_(STORAGE_BUCKET).get_public_url(path=f"items/{random_uuid}/{img_name}")
            return img_name, public_url_response

        # gather preserves input order, so image 0 stays the thumbnail.
        urls = dict(await asyncio.gather(
            *(upload_image(i, img) for i, img in enumerate(uploaded_images))
        ))

        item_data = {
            "id" : random_uuid,
            "name" : name,
            "price" : price,
            "description" : description,
            "condition" : condition,
            "image_path": json.dumps(urls),
            "status": "available",  # Default status for new items
            "created_at": datetime.now().isoformat()
        }

        # Only include min_price if provided
        if min_price is not None:
            item_data["min_price"] = min_price

        if translations is not None:
            item_data["translations"] = translations

        admin_supabase.table('items').insert(item_data).execute()

        # Invalidate cache so new item shows up
        invalidate_item_cache()
        return True

    except Exception as e:
        logger.error(f"An error has occured! Error: {e}")
        return False

async def sync_item_images(
    item_id: str,
    ordered: list[str],
    new_images: list[UploadFile] = None
    ) -> str | None:
    """
    Rebuild an item's image map from an ordered list of tokens (edit flow).

    `image_path` is a {filename: url} map whose insertion order *is* the display
    order, so this returns a freshly built map rather than patching the old one.

    Args:
        item_id: Item whose photos are being replaced
        ordered: One token per photo, in display order (first = thumbnail).
            A token is either the public URL of a photo the item already has,
            or "new:<n>" naming the nth file in `new_images`. Anything else is
            dropped, so a stale client can never write a foreign URL into the row.
        new_images: Newly uploaded files referenced by the "new:<n>" tokens

    Returns:
        The JSON string for `image_path`, or None if the rebuild failed.
    """
    try:
        response = admin_supabase.table('items').select('image_path').eq('id', item_id).execute()
        if not response.data:
            return None

        try:
            current = json.loads(response.data[0].get('image_path') or '{}')
        except (TypeError, ValueError):
            current = {}
        if not isinstance(current, dict):
            current = {}

        # Kept photos arrive as URLs; map back to the filename that keys them.
        by_url = {url: name for name, url in current.items()}

        async def upload_new(img: UploadFile) -> tuple[str, str]:
            img_extension = img.filename.split(".")[-1] if img.filename else "dat"
            # Random names, not positional ones: a photo added at slot 0 must
            # never overwrite the object of a photo the listing still points at.
            img_name = f"{uuid.uuid4().hex[:8]}.{img_extension}"
            path = f"items/{item_id}/{img_name}"
            file_content = await img.read()
            await asyncio.to_thread(
                admin_supabase.storage.from_(STORAGE_BUCKET).upload,
                file=file_content,
                path=path,
                file_options={"content-type": img.content_type or "application/octet-stream"}
            )
            return img_name, admin_supabase.storage.from_(STORAGE_BUCKET).get_public_url(path=path)

        uploaded = list(await asyncio.gather(
            *(upload_new(img) for img in (new_images or []))
        ))

        urls = {}
        for token in ordered:
            if token.startswith("new:"):
                try:
                    img_name, url = uploaded[int(token[4:])]
                except (ValueError, IndexError):
                    continue
                urls[img_name] = url
            elif token in by_url:
                urls[by_url[token]] = token

        dropped = [f"items/{item_id}/{name}" for name in current if name not in urls]
        if dropped:
            try:
                await asyncio.to_thread(
                    admin_supabase.storage.from_(STORAGE_BUCKET).remove, dropped
                )
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
        admin_supabase.table('items').update(
            {"deleted_at": datetime.now().isoformat()}
        ).eq("id", item_id).execute()
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
    translations: dict = None
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

        admin_supabase.table('items').update(update).eq("id", item_id).execute()
        invalidate_item_cache(item_id)  # Clear cache
        return True
    except Exception as e:
        logger.error(f"Something wrong! Error: {e}")
        return False
