import asyncio
import json

from fastapi import APIRouter, HTTPException, Request, status

from auth_middleware import get_optional_user_id
from items import PUBLIC_ITEM_COLUMNS, PUBLIC_ITEM_SELECT, get_featured_items, get_items
from logger import logger

# Public items API — READ ONLY.
# All writes (create/update/delete, image management) live under the admin router
# (/admin/items) behind verify_admin. The browser only ever reads items.
router = APIRouter(prefix="/items", tags=["Items"])


def _to_public(row: dict) -> dict:
    """Project a raw DB row onto the fields the storefront is allowed to see.

    This is an allowlist, not a copy. `dict(row)` would forward whatever the
    query happened to return — which is how `min_price`, the negotiation floor,
    used to ship in every public items response (SPEC-036). Building the payload
    up from `PUBLIC_ITEM_COLUMNS` means a column added to the table later stays
    server-side until someone deliberately adds it to that list.

    The DB stores `id` and `image_path` (a JSON map {filename: url}); the
    frontend expects `item_id` and `images` (a JSON array of URLs). We add those
    aliases alongside the originals.
    """
    out = {column: row[column] for column in PUBLIC_ITEM_COLUMNS if column in row}
    out['item_id'] = row.get('id')

    urls: list = []
    image_path = row.get('image_path')
    if image_path:
        try:
            parsed = json.loads(image_path)
            if isinstance(parsed, dict):
                urls = list(parsed.values())
            elif isinstance(parsed, list):
                urls = parsed
            else:
                urls = [image_path]
        except Exception:
            urls = [image_path]
    out['images'] = json.dumps(urls)
    return out


def _apply_discount(item: dict, user_id: str | None) -> dict:
    """If user has an active negotiated offer lower than the listed price, attach discounted_price."""
    if not user_id:
        return item
    item_id = item.get("id") or item.get("item_id")
    if not item_id:
        return item

    discount = None
    # 1. Check pending payment in payment_state
    try:
        from payment.payment_state import get_pending_payment
        pending = get_pending_payment(user_id, item_id)
        if pending and "agreed_price" in pending:
            discount = float(pending["agreed_price"])
    except Exception as e:
        logger.debug(f"Could not load active offer discount from payment state: {e}")

    # 2. Check negotiated_price in redis
    try:
        from cache import redis_client
        cached = redis_client.get(f"negotiated_price:{user_id}:{item_id}")
        if cached:
            cached_val = float(cached)
            discount = min(discount, cached_val) if discount is not None else cached_val
    except Exception as e:
        logger.debug(f"Could not load active offer discount from redis: {e}")

    price = item.get("price")
    if discount is not None and price is not None and discount < float(price):
        item["discounted_price"] = discount

    return item


@router.get('')
async def get_all_items(request: Request, keyword: str | None = None) -> list[dict]:
    """
    Get all items or search by keyword.

    Returns empty list if no items found (industry standard).
    """
    user_id = await get_optional_user_id(request)

    # One thread hop for the Supabase read AND the per-item discount decoration:
    # each item costs a couple of synchronous Redis lookups, so a 20-item page
    # would otherwise run 40 round trips on the event loop.
    def _load() -> list[dict]:
        items = get_items(keyword)
        return [_apply_discount(_to_public(i), user_id) for i in items] if items else []

    return await asyncio.to_thread(_load)


@router.get('/featured')
async def get_featured(request: Request, limit: int = 6) -> list[dict]:
    """
    Get the most-interacted listings for the home page.

    Defined before '/{item_id}' so the literal 'featured' path isn't
    captured as an item id.
    """
    user_id = await get_optional_user_id(request)

    def _load() -> list[dict]:
        return [_apply_discount(_to_public(i), user_id) for i in get_featured_items(limit)]

    return await asyncio.to_thread(_load)


@router.get('/{item_id}')
async def get_item_by_id(item_id: str, request: Request) -> dict:
    """
    Get a specific item by ID.

    Returns 404 if item not found (this is correct usage).
    """
    from connector import user_supabase

    try:
        # Soft-deleted items are hidden from the public storefront (treated as 404).
        response = await asyncio.to_thread(
            lambda: user_supabase.table('items')
            .select(PUBLIC_ITEM_SELECT).eq('id', item_id).is_('deleted_at', 'null').execute()
        )
    except Exception:
        # e.g. malformed UUID ("undefined") — treat as not found, not a 500.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item with id '{item_id}' not found"
        ) from None

    if response.data and len(response.data) > 0:
        user_id = await get_optional_user_id(request)
        row = response.data[0]
        return await asyncio.to_thread(lambda: _apply_discount(_to_public(row), user_id))

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Item with id '{item_id}' not found"
    )
