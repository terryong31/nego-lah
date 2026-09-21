from langchain_core.tools import tool

from core.logger import logger


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
    from core.connector import user_supabase

    logger.info(f"\n{'=' * 50}")
    logger.info("🔍 GET_ITEM_INFO CALLED")
    logger.info(f"📦 Item ID: {item_id}")
    logger.info(f"{'=' * 50}")

    from domains.catalog import CatalogService

    item = CatalogService.get_public_item_by_id(item_id, supabase_client=user_supabase)

    logger.info(f"📊 Query result: {'1 item found' if item else '0 items found'}")
    if item:
        logger.info(f"📋 Data: {item}")
        result = f"""
item_id: {item.get("id")}
Item: {item.get("name", "Unknown")}
Description: {item.get("description", "No description")}
Price: RM{item.get("price", "N/A")}
Condition: {item.get("condition", "Unknown")}
Status: {item.get("status", "available")}
"""
        logger.info("✅ Returning item info")
        return result
    logger.info("❌ Item not found!")
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
    from core.connector import user_supabase

    logger.info(f"\n{'=' * 50}")
    logger.info("🔎 SEARCH_ITEMS CALLED")
    logger.info(f"🔤 Search term: '{search_term}'")
    logger.info(f"{'=' * 50}")

    # Search by name (case-insensitive)
    from domains.catalog import CatalogService

    items = CatalogService.search_items(search_term, limit=5, supabase_client=user_supabase)

    logger.info(f"📊 Query result: {len(items)} items found")
    if items:
        results = []
        for item in items:
            status = item.get("status")
            logger.info(f"  - {item.get('name')}: status={status}")

            # Use 'available' as the default status if it's missing or stick to what's in DB
            display_status = status if status else "available"

            # Format the output for the LLM
            results.append(
                f"• ID: {item.get('id')} | Name: {item.get('name')} | Price: RM{item.get('price')} | Status: {display_status}"
            )

        result_str = "\n".join(results)
        logger.info(f"✅ Returning {len(results)} items")
        return result_str

    logger.info("❌ No matching items found")
    return "No matching items found."


@tool
def list_all_items() -> str:
    """
    List all available items in the store.
    Use this when a buyer asks "what do you have?" or "show me your items".

    Returns:
        List of all items with their IDs, names, and prices
    """
    from core.connector import user_supabase

    logger.info(f"\n{'=' * 50}")
    logger.info("📋 LIST_ALL_ITEMS CALLED")
    logger.info(f"{'=' * 50}")

    from domains.catalog import CatalogService

    items = CatalogService.list_available_items(limit=10, supabase_client=user_supabase)

    if items:
        results = []
        for item in items:
            results.append(f"• ID: {item.get('id')} | Name: {item.get('name')} | Price: RM{item.get('price')}")

        logger.info(f"✅ Returning {len(results)} items")
        return "\n".join(results)

    logger.info("❌ No available items found")
    return "No available items found."
