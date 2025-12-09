import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connector import user_supabase, admin_supabase
from datetime import datetime
from fastapi import UploadFile
from typing import List
import json
import uuid

def all_items() -> str:
    retrieve = user_supabase.table('items').select('*').execute()
    if retrieve.data:
        return retrieve.data
    else:
        return False
    
def get_item_by_name(name: str) -> str:
    retrieve = user_supabase.table('items').select('*').ilike('name', f'%{name}%').execute()
    if retrieve.data:
        return retrieve
    else:
        return False

async def upload_item(name, description, condition, uploaded_images: List[UploadFile]) -> bool:
    try:
        random_uuid = str(uuid.uuid4())
        
        urls = {}
        
        for i, img in enumerate(uploaded_images):
            img_extension = img.filename.split(".")[-1] if img.filename else "dat"
            img_name =f"{i}.{img_extension}"
            file_content = await img.read()
            admin_supabase.storage.from_(f"item_images").upload(
                file = file_content,
                path = f"items/{random_uuid}/{img_name}",
                file_options={"content-type": img.content_type or "application/octet-stream"}
            )
            public_url_response = admin_supabase.storage.from_('item_images').get_public_url(path=f"items/{random_uuid}/{img_name}")
            urls[f'{img_name}'] = public_url_response
            
        admin_supabase.table('items').insert(
            {
                "id" : random_uuid, 
                "name" : name,
                "description" : description,
                "condition" : condition, 
                "image_path": json.dumps(urls),
                "created_at": datetime.now().isoformat()
            }
        ).execute()
        return True

    except Exception as e:
        print(f"An error has occured! Error: {e}")
        return False

def delete_item(id) -> bool:
    try:
        admin_supabase.table('items').delete().eq("id", id).execute()
        return True
    except Exception as e:
        print(f"Something wrong! Error: {e}")
        return False

def update_item(id, name = None, description = None, condition = None, images = None):
    try:
        update = {}
        if name:
            update["name"] = name
        if description:
            update["description"] = description
        if condition:
            update["condition"] = condition
        if images:
            update[images] = images
        admin_supabase.table('items').update(update).eq("id", id).execute()
        return True
    except Exception as e:
        print(f"Something wrong! Error: {e}")
        return False