import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connector import supabase
from datetime import datetime

def upload_item(id, name, description, condition, image_path):
    response = supabase.table('items').insert({"id":id, "name":name, "description": description, "condition": condition, "image_path": image_path, "created_at": datetime.now().isoformat()}).execute()
    if response.data:
        return True
    else:
        return False

def delete_item(id):
    response = supabase.table('items').delete().eq("id", id).execute()
    if response.data:
        return True
    else:
        return False