import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connector import supabase

def upload_item(id, name, description, condition, image_path, created_at):
    upload = supabase.table('items').insert('').execute()
    