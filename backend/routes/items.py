import json
from fastapi import APIRouter, HTTPException, status
from typing import List, Optional
from items import get_items, get_featured_items

# Public items API — READ ONLY.
# All writes (create/update/delete, image management) live under the admin router
# (/admin/items) behind verify_admin. The browser only ever reads items.
router = APIRouter(prefix="/items", tags=["Items"])


def _to_public(row: dict) -> dict:
    """Shape a raw DB row for the storefront.

    The DB stores `id` and `image_path` (a JSON map {filename: url}); the
    frontend expects `item_id` and `images` (a JSON array of URLs). We add those
    aliases without dropping the originals.
    """
    out = dict(row)
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


@router.get('')
async def get_all_items(keyword: Optional[str] = None) -> List[dict]:
    """
    Get all items or search by keyword.

    Returns empty list if no items found (industry standard).
    """
    items = get_items(keyword)
    return [_to_public(i) for i in items] if items else []


@router.get('/featured')
async def get_featured(limit: int = 6) -> List[dict]:
    """
    Get the most-interacted listings for the home page.

    Defined before '/{item_id}' so the literal 'featured' path isn't
    captured as an item id.
    """
    return [_to_public(i) for i in get_featured_items(limit)]


@router.get('/{item_id}')
async def get_item_by_id(item_id: str) -> dict:
    """
    Get a specific item by ID.

    Returns 404 if item not found (this is correct usage).
    """
    from connector import user_supabase

    try:
        response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    except Exception:
        # e.g. malformed UUID ("undefined") — treat as not found, not a 500.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item with id '{item_id}' not found"
        )

    if response.data and len(response.data) > 0:
        return _to_public(response.data[0])

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Item with id '{item_id}' not found"
    )
