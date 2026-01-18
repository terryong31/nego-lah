from connector import user_supabase, admin_supabase
from datetime import datetime
from fastapi import UploadFile
from typing import List
import json
import uuid
from cache import cache_items, get_cached_items, invalidate_item_cache
    
def get_items(keyword: str = None) -> List[str]:
    if keyword is None:
        # Try cache first
        cached = get_cached_items()
        if cached:
            return cached
        
        # Cache miss - get from DB and cache
        retrieve = user_supabase.table('items').select('*').execute()
        if retrieve.data:
            cache_items(retrieve.data)  # Cache for 5 min
            return retrieve.data
        return False
    else:
        retrieve = user_supabase.table('items').select('*').ilike('description', f'%{keyword}%').execute()
        if retrieve.data:
            return retrieve.data
        return False

async def upload_item(
    name: str, 
    description: str, 
    condition: str, 
    uploaded_images: List[UploadFile],
    price: float,
    min_price: float = None
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
    """
    
    try:
        random_uuid = str(uuid.uuid4())
        
        urls = {}
        
        for i, img in enumerate(uploaded_images):
            img_extension = img.filename.split(".")[-1] if img.filename else "dat"
            img_name =f"{i}.{img_extension}"
            file_content = await img.read()
            admin_supabase.storage.from_(f"images").upload(
                file = file_content,
                path = f"items/{random_uuid}/{img_name}",
                file_options={"content-type": img.content_type or "application/octet-stream"}
            )
            public_url_response = admin_supabase.storage.from_('images').get_public_url(path=f"items/{random_uuid}/{img_name}")
            urls[f'{img_name}'] = public_url_response
            
        item_data = {
            "id" : random_uuid, 
            "name" : name,
            "price" : price,
            "description" : description,
            "condition" : condition, 
            "image_path": json.dumps(urls),
            "created_at": datetime.now().isoformat()
        }
        
        # Only include min_price if provided
        if min_price is not None:
            item_data["min_price"] = min_price
            
        admin_supabase.table('items').insert(item_data).execute()

        # Invalidate cache so new item shows up
        invalidate_item_cache()
        return True

    except Exception as e:
        print(f"An error has occured! Error: {e}")
        return False

def delete_item(item_id: str) -> bool:
    try:
        admin_supabase.table('items').delete().eq("id", item_id).execute()
        invalidate_item_cache(item_id)  # Clear cache
        return True
    except Exception as e:
        print(f"Something wrong! Error: {e}")
        return False

def update_item(
    item_id: str,
    name: str = None,
    description: str = None, 
    condition: str = None, 
    price: float = None,
    min_price: float = None,
    images: str = None
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
            
        if not update:
            return False
            
        admin_supabase.table('items').update(update).eq("id", item_id).execute()
        invalidate_item_cache(item_id)  # Clear cache
        return True
    except Exception as e:
        print(f"Something wrong! Error: {e}")
        return False