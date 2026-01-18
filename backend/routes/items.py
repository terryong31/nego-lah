from fastapi import APIRouter, HTTPException, status, File, UploadFile, Form
from typing import List, Annotated, Optional
from items import get_items, upload_item, delete_item, update_item
from schemas import ItemSchema

router = APIRouter(prefix="/items", tags=["Items"])


@router.get('')
async def get_all_items(keyword: Optional[str] = None) -> List[dict]:
    """
    Get all items or search by keyword.
    
    Returns empty list if no items found (industry standard).
    """
    items = get_items(keyword)
    
    # Return empty list instead of 404 for no items
    # 404 should be reserved for "resource not found" (specific item by ID)
    if items:
        return items
    return []


@router.get('/{item_id}')
async def get_item_by_id(item_id: str) -> dict:
    """
    Get a specific item by ID.
    
    Returns 404 if item not found (this is correct usage).
    """
    from connector import user_supabase
    
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    
    if response.data and len(response.data) > 0:
        return response.data[0]
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, 
        detail=f"Item with id '{item_id}' not found"
    )


@router.post('', status_code=status.HTTP_201_CREATED)
async def upload(
    name: Annotated[str, Form()],
    description: Annotated[str, Form()],
    condition: Annotated[str, Form()],
    price: Annotated[float, Form()],
    images: Annotated[List[UploadFile], File()],
    min_price: Annotated[float, Form()] = None
) -> dict:
    """Create a new item."""
    item_creation_status = await upload_item(name, description, condition, images, price, min_price)
    
    if item_creation_status:
        return {"message": "Item created successfully"}
    
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
        detail="Failed to create item"
    )


@router.delete('/{item_id}')
def delete_by_id_path(item_id: str) -> dict:
    """Delete an item by ID (path parameter - preferred)."""
    response = delete_item(item_id)
    
    if response:
        return {"message": "Item deleted successfully"}
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, 
        detail=f"Item with id '{item_id}' not found or failed to delete"
    )


@router.delete('')
def delete_by_id_body(items: ItemSchema) -> dict:
    """Delete an item by ID (body - legacy support)."""
    response = delete_item(items.item_id)
    
    if response:
        return {"message": "Item deleted successfully"}
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, 
        detail="Item not found or failed to delete"
    )


@router.put('/{item_id}')
def update_by_id(
    item_id: str,
    items: ItemSchema
) -> dict:
    """Update an item by ID."""
    item_update_status = update_item(
        item_id=item_id, 
        name=items.name, 
        description=items.description, 
        condition=items.condition,
        price=items.price,
        min_price=items.min_price,
        images=items.images
    )
    
    if item_update_status:
        return {"message": "Item updated successfully"}
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, 
        detail=f"Item with id '{item_id}' not found or failed to update"
    )


@router.put('')
def update_legacy(items: ItemSchema) -> dict:
    """Update an item (legacy support)."""
    item_update_status = update_item(
        item_id=items.item_id, 
        name=items.name, 
        description=items.description, 
        condition=items.condition,
        price=items.price,
        min_price=items.min_price,
        images=items.images
    )
    
    if item_update_status:
        return {"message": "Item updated successfully"}
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, 
        detail="Item not found or failed to update"
    )


@router.delete('/{item_id}/images/{image_index}')
def delete_image(item_id: str, image_index: int) -> dict:
    """Delete a specific image from an item by index."""
    from connector import admin_supabase
    import json
    
    # Get current item
    response = admin_supabase.table('items').select('image_path').eq('id', item_id).execute()
    
    if not response.data or len(response.data) == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    
    current_images_json = response.data[0].get('image_path')
    images_map = {}
    
    if current_images_json:
        try:
            images_map = json.loads(current_images_json)
        except:
            images_map = {}
            
    # Convert map values to list to identify which one to delete
    # This is tricky because the backend stores a map {filename: url}
    # But the frontend sends an index. 
    # We should probably trust the order of keys/values?
    # Or refactor frontend to send the filename/key.
    # Assuming frontend sends index based on Object.values() order.
    
    image_keys = list(images_map.keys())
    
    if image_index < 0 or image_index >= len(image_keys):
        raise HTTPException(status_code=400, detail="Invalid image index")
    
    key_to_delete = image_keys[image_index]
    
    # Remove from map
    del images_map[key_to_delete]
    
    # Update item
    new_json = json.dumps(images_map)
    admin_supabase.table('items').update({'image_path': new_json}).eq('id', item_id).execute()
    
    return {"message": "Image deleted successfully", "remaining_images": list(images_map.values())}


@router.post('/{item_id}/images', status_code=status.HTTP_201_CREATED)
async def add_images(
    item_id: str,
    images: Annotated[List[UploadFile], File()]
) -> dict:
    """Add new images to an existing item."""
    from connector import admin_supabase
    import base64
    import json
    
    # Get current item
    response = admin_supabase.table('items').select('image_path').eq('id', item_id).execute()
    
    if not response.data or len(response.data) == 0:
        raise HTTPException(status_code=404, detail="Item not found")
    
    current_images_json = response.data[0].get('image_path')
    images_map = {}
    
    if current_images_json:
        try:
            images_map = json.loads(current_images_json)
        except:
            images_map = {}
    
    # Upload new images and get URLs
    for i, image in enumerate(images):
        contents = await image.read()
        base64_image = base64.b64encode(contents).decode('utf-8')
        
        # Use a unique filename
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{unique_id}_{image.filename}"
        
        file_path = f"items/{item_id}/{filename}"
        
        try:
            # Try to upload to storage
            admin_supabase.storage.from_('item-images').upload(
                file_path, 
                contents,
                {"content-type": image.content_type}
            )
            # Get public URL
            public_url = admin_supabase.storage.from_('item-images').get_public_url(file_path)
            images_map[filename] = public_url
        except Exception:
            # Fallback to base64 data URL
            data_url = f"data:{image.content_type};base64,{base64_image}"
            images_map[filename] = data_url
    
    # Update item with new map
    new_json = json.dumps(images_map)
    admin_supabase.table('items').update({'image_path': new_json}).eq('id', item_id).execute()
    
    return {"message": "Images added successfully", "images": list(images_map.values())}
