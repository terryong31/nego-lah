from connector import user_supabase, admin_supabase
from datetime import datetime
from fastapi import UploadFile
from typing import List
import json
import uuid
import hashlib
from cache import cache_items_with_hash, get_cached_items_with_hash, invalidate_item_cache
import redis
from env import REDIS_URL

# Redis client for fingerprint caching
_redis = redis.from_url(REDIS_URL, decode_responses=True)


def compute_items_hash(count: int, max_created_at: str) -> str:
    """Compute SHA hash from item count and latest timestamp"""
    data = f"{count}:{max_created_at}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]


def get_items_fingerprint():
    """
    Get a lightweight fingerprint of items table.
    Queries only COUNT and MAX(created_at) - much cheaper than full table scan.
    """
    # Query count
    count_response = user_supabase.table('items').select('id', count='exact').execute()
    item_count = count_response.count or 0
    
    # Query latest created_at
    latest_response = user_supabase.table('items').select('created_at').order('created_at', desc=True).limit(1).execute()
    max_created_at = latest_response.data[0]['created_at'] if latest_response.data else ""
    
    return item_count, max_created_at


def should_validate_cache() -> bool:
    """
    Check if we should validate cache against Supabase.
    Returns True only if 30 seconds have passed since last validation.
    This prevents hitting Supabase on every single request.
    """
    last_check = _redis.get("items:last_validation")
    if last_check:
        return False  # Already validated recently, use cache
    
    # Mark that we're validating now (expires in 30 seconds)
    _redis.setex("items:last_validation", 30, "1")
    return True

    
def get_items(keyword: str = None) -> List[str]:
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
        retrieve = user_supabase.table('items').select('*').execute()
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
        retrieve = user_supabase.table('items').select('*').ilike('description', f'%{keyword}%').execute()
        if retrieve.data:
            return retrieve.data
        return []

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
            "status": "available",  # Default status for new items
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