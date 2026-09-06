"""Admin catalogue CRUD: create, update, delete and list item listings.

Unlike the public storefront router, these responses deliberately include
`min_price` — the seller sets it, so the seller's console shows it (SPEC-036).
"""

import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from admin_session import verify_admin, write_audit
from logger import logger

router = APIRouter()


@router.get("/items")
def admin_list_items():
    """List every live item (including sold), newest first. Soft-deleted items are hidden."""
    from connector import admin_supabase
    res = admin_supabase.table('items').select('*').is_('deleted_at', 'null').order('created_at', desc=True).execute()
    return res.data or []


@router.post("/items", status_code=201)
async def admin_create_item(
    name: Annotated[str, Form()],
    description: Annotated[str, Form()],
    condition: Annotated[str, Form()],
    price: Annotated[float, Form()],
    images: Annotated[list[UploadFile], File()],
    min_price: Annotated[float | None, Form()] = None,
    translations: Annotated[str | None, Form()] = None,
    admin: dict = Depends(verify_admin),
):
    """Create a new listing with one or more images."""
    from items import upload_item
    parsed_translations = None
    if translations:
        try:
            parsed_translations = json.loads(translations)
        except (TypeError, ValueError) as e:
            # Malformed JSON from the client: save the listing without
            # translations rather than 500, but say so — a silently untranslated
            # listing looks like a backend bug from the console.
            logger.warning(f"Ignoring unparseable translations payload: {e}")
            parsed_translations = None
    ok = await upload_item(name, description, condition, images, price, min_price, translations=parsed_translations)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to create item")
    write_audit(admin.get("user_id"), admin.get("email"), "item.create", name, admin.get("ip"))
    return {"message": "Item created successfully"}


@router.put("/items/{item_id}")
async def admin_update_item(
    item_id: str,
    name: Annotated[str | None, Form()] = None,
    description: Annotated[str | None, Form()] = None,
    condition: Annotated[str | None, Form()] = None,
    price: Annotated[float | None, Form()] = None,
    min_price: Annotated[float | None, Form()] = None,
    translations: Annotated[str | None, Form()] = None,
    images_order: Annotated[str | None, Form()] = None,
    new_images: Annotated[list[UploadFile] | None, File()] = None,
    admin: dict = Depends(verify_admin),
):
    """Update a listing's fields and, optionally, its photos.

    Multipart rather than JSON because photos ride along with the fields: a
    browser cannot send files as JSON, and splitting them across two requests
    would let an edit half-apply.

    `images_order` is a JSON array with one token per photo in display order
    (see `items.sync_item_images`); omitting it leaves the photos untouched.
    """
    from items import sync_item_images, update_item
    parsed_translations = None
    if translations:
        try:
            parsed_translations = json.loads(translations)
        except (TypeError, ValueError) as e:
            # Malformed JSON from the client: save the listing without
            # translations rather than 500, but say so — a silently untranslated
            # listing looks like a backend bug from the console.
            logger.warning(f"Ignoring unparseable translations payload: {e}")
            parsed_translations = None

    images = None
    if images_order is not None:
        try:
            ordered = json.loads(images_order)
            if not isinstance(ordered, list):
                raise ValueError("images_order must be a list")
        except Exception as e:
            raise HTTPException(status_code=400, detail="Invalid images_order") from e
        # Sync first: if the photos can't be written, the row stays as it was
        # rather than pointing at a half-built image set.
        images = await sync_item_images(item_id, ordered, new_images or [])
        if images is None:
            raise HTTPException(status_code=500, detail="Failed to update item images")

    ok = await asyncio.to_thread(
        update_item,
        item_id=item_id,
        name=name,
        description=description,
        condition=condition,
        price=price,
        min_price=min_price,
        images=images,
        translations=parsed_translations,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found or update failed")
    write_audit(admin.get("user_id"), admin.get("email"), "item.update", item_id, admin.get("ip"))
    return {"message": "Item updated successfully"}


@router.delete("/items/{item_id}")
def admin_delete_item(item_id: str, admin: dict = Depends(verify_admin)):
    """Delete a listing (and its related orders/conversations)."""
    from items import delete_item
    ok = delete_item(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found or delete failed")
    write_audit(admin.get("user_id"), admin.get("email"), "item.delete", item_id, admin.get("ip"))
    return {"message": "Item deleted successfully"}
