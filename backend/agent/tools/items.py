from langchain_core.tools import tool
from logger import logger

@tool
def get_item_info(item_id: str) -> str:
    """
    Get information about an item by its ID.
    Use this when a buyer asks about a specific item.
    
    Args:
        item_id: The unique identifier of the item
    
    Returns:
        Item details including name, description, price, and condition
    """
    from connector import user_supabase
    
    logger.info(f"\n{'='*50}")
    logger.info(f"🔍 GET_ITEM_INFO CALLED")
    logger.info(f"📦 Item ID: {item_id}")
    logger.info(f"{'='*50}")
    
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    
    logger.info(f"📊 Query result: {len(response.data) if response.data else 0} items found")
    if response.data:
        logger.info(f"📋 Data: {response.data}")
    
    if response.data and len(response.data) > 0:
        item = response.data[0]
        result = f"""
item_id: {item.get('id')}
Item: {item.get('name', 'Unknown')}
Description: {item.get('description', 'No description')}
Price: RM{item.get('price', 'N/A')}
Condition: {item.get('condition', 'Unknown')}
Status: {item.get('status', 'available')}
"""
        logger.info(f"✅ Returning item info")
        return result
    logger.info(f"❌ Item not found!")
    return "Item not found."


@tool
def search_items(search_term: str) -> str:
    """
    Search for items by name or description.
    Use this when a buyer mentions an item by name but you don't have the item_id.
    
    Args:
        search_term: The search query (item name or keywords)
    
    Returns:
        List of matching items with their IDs, names, and prices
    """
    from connector import user_supabase
    
    logger.info(f"\n{'='*50}")
    logger.info(f"🔎 SEARCH_ITEMS CALLED")
    logger.info(f"🔤 Search term: '{search_term}'")
    logger.info(f"{'='*50}")
    
    # Search by name (case-insensitive)
    query = f'%{search_term}%'
    logger.info(f"📝 SQL ILIKE query: name ILIKE '{query}'")
    
    response = user_supabase.table('items').select('id, name, price, condition, status').ilike('name', query).limit(5).execute()
    
    logger.info(f"📊 Query result: {len(response.data) if response.data else 0} items found")
    if response.data:
        logger.info(f"📋 Raw data: {response.data}")
    
    if response.data and len(response.data) > 0:
        results = []
        for item in response.data:
            status = item.get('status')
            logger.info(f"  - {item.get('name')}: status={status}")
            
            # Use 'available' as the default status if it's missing or stick to what's in DB
            display_status = status if status else 'available'
            
            # Format the output for the LLM
            results.append(f"• ID: {item.get('id')} | Name: {item.get('name')} | Price: RM{item.get('price')} | Status: {display_status}")
            
        result_str = "\n".join(results)
        logger.info(f"✅ Returning {len(results)} items")
        return result_str
        
    logger.info(f"❌ No matching items found")
    return "No matching items found."


@tool
def list_all_items() -> str:
    """
    List all available items in the store.
    Use this when a buyer asks "what do you have?" or "show me your items".
    
    Returns:
        List of all items with their IDs, names, and prices
    """
    from connector import user_supabase
    
    logger.info(f"\n{'='*50}")
    logger.info(f"📋 LIST_ALL_ITEMS CALLED")
    logger.info(f"{'='*50}")
    
    response = user_supabase.table('items').select('id, name, price, condition, status').eq('status', 'available').limit(10).execute()
    
    if response.data and len(response.data) > 0:
        results = []
        for item in response.data:
            results.append(f"• ID: {item.get('id')} | Name: {item.get('name')} | Price: RM{item.get('price')}")
        
        logger.info(f"✅ Returning {len(results)} items")
        return "\n".join(results)
        
    logger.info(f"❌ No available items found")
    return "No available items found."
