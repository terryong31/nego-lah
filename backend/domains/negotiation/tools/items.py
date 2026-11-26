from langchain_core.tools import tool

from core import connector
from core.logger import logger
from domains.catalog import CatalogService


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
    item = CatalogService.get_public_item_by_id(item_id, supabase_client=connector.user_supabase)
    logger.info(f"get_item_info item_id={item_id} found={bool(item)}")

    if item:
        return f"""
item_id: {item.get("id")}
Item: {item.get("name", "Unknown")}
Description: {item.get("description", "No description")}
Price: RM{item.get("price", "N/A")}
Condition: {item.get("condition", "Unknown")}
Status: {item.get("status", "available")}
"""
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
    items = CatalogService.search_items(search_term, limit=5, supabase_client=connector.user_supabase)
    logger.info(f"search_items query={search_term!r} count={len(items)}")

    if items:
        results = [
            (
                f"• ID: {item.get('id')} | Name: {item.get('name')} | "
                f"Price: RM{item.get('price')} | Status: {item.get('status') or 'available'}"
            )
            for item in items
        ]
        return "\n".join(results)

    return "No matching items found."


@tool
def list_all_items() -> str:
    """
    List all available items in the store.
    Use this when a buyer asks "what do you have?" or "show me your items".

    Returns:
        List of all items with their IDs, names, and prices
    """
    items = CatalogService.list_available_items(limit=10, supabase_client=connector.user_supabase)
    logger.info(f"list_all_items count={len(items)}")

    if items:
        results = [
            f"• ID: {item.get('id')} | Name: {item.get('name')} | Price: RM{item.get('price')}"
            for item in items
        ]
        return "\n".join(results)

    return "No available items found."
