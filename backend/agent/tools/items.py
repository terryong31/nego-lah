from langchain_core.tools import tool

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
    
    print(f"\n{'='*50}")
    print(f"🔍 GET_ITEM_INFO CALLED")
    print(f"📦 Item ID: {item_id}")
    print(f"{'='*50}")
    
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    
    print(f"📊 Query result: {len(response.data) if response.data else 0} items found")
    if response.data:
        print(f"📋 Data: {response.data}")
    
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
        print(f"✅ Returning item info")
        return result
    print(f"❌ Item not found!")
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
    
    print(f"\n{'='*50}")
    print(f"🔎 SEARCH_ITEMS CALLED")
    print(f"🔤 Search term: '{search_term}'")
    print(f"{'='*50}")
    
    # Search by name (case-insensitive)
    query = f'%{search_term}%'
    print(f"📝 SQL ILIKE query: name ILIKE '{query}'")
    
    response = user_supabase.table('items').select('id, name, price, condition, status').ilike('name', query).limit(5).execute()
    
    print(f"📊 Query result: {len(response.data) if response.data else 0} items found")
    if response.data:
        print(f"📋 Raw data: {response.data}")
    
    if response.data and len(response.data) > 0:
        results = []
        for item in response.data:
            status = item.get('status')
            print(f"  - {item.get('name')}: status={status}")
            
            # Use 'available' as the default status if it's missing or stick to what's in DB
            display_status = status if status else 'available'
            
            # Format the output for the LLM
            results.append(f"• ID: {item.get('id')} | Name: {item.get('name')} | Price: RM{item.get('price')} | Status: {display_status}")
            
        result_str = "\n".join(results)
        print(f"✅ Returning {len(results)} items")
        return result_str
        
    print(f"❌ No matching items found")
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
    
    print(f"\n{'='*50}")
    print(f"📋 LIST_ALL_ITEMS CALLED")
    print(f"{'='*50}")
    
    response = user_supabase.table('items').select('id, name, price, condition, status').eq('status', 'available').limit(10).execute()
    
    if response.data and len(response.data) > 0:
        results = []
        for item in response.data:
            results.append(f"• ID: {item.get('id')} | Name: {item.get('name')} | Price: RM{item.get('price')}")
        
        print(f"✅ Returning {len(results)} items")
        return "\n".join(results)
        
    print(f"❌ No available items found")
    return "No available items found."
