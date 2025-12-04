import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.connector import supabase

def all_items() -> str:
    retrieve = supabase.table('items').select('*').execute()
    if retrieve.data:
        return retrieve
    else:
        return False
    
def get_item_by_id(id: str) -> str:
    retrieve = supabase.table('items').select('*').eq('id', id).execute()
    if retrieve.data:
        return retrieve
    else:
        return False