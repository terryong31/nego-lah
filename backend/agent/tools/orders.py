from langchain_core.tools import tool
from connector import admin_supabase

@tool
def check_user_orders(query: str = "") -> str:
    """
    Check the specific items the current user has purchased/ordered.
    Use this when the user asks "what did I buy?", "where is my stuff?", "did my order go through?", or discusses past purchases.
    Also use this to see if a user has a 'pending_info' order that needs shipping details.
    
    Args:
        query: Optional specific question or filter.
    """
    # Request-scoped context (set by bot.chat per request)
    from agent.context import get_user_id
    user_id = get_user_id()
    
    if not user_id:
        return "System Error: I cannot identify your user account at the moment."
        
    try:
        # Fetch orders from the 'orders' table (which links items to buyer_id)
        # We also want to know if they provided info, so checking status is crucial.
        response = admin_supabase.table('orders').select('*').eq('buyer_id', user_id).order('created_at', desc=True).execute()
        
        orders = response.data
        if not orders:
            return "Records show you haven't purchased any items from our store yet."
            
        result_lines = ["Found the following orders for you:"]
        for order in orders:
            status = order.get('status', 'unknown')
            item_name = order.get('item_name', 'Unknown Item')
            amount = order.get('amount', 0)
            date_str = order.get('created_at', '')[:10] # YYYY-MM-DD
            
            line = f"- [Date: {date_str}] {item_name} (RM {amount}) | Status: {status.upper()} | Order ID: {order['id']}"
            
            if status == 'pending_info':
                line += "\n  ⚠️ ACTION REQUIRED: We need your shipping details for this order! Please provide: Name, Address, and Phone Number. (Use Order ID: {order['id']} for updates)"
            elif status == 'confirmed':
                line += "\n  ✅ Info received. We are processing it."
            elif status == 'shipped':
                line += "\n  🚚 Shipped."
            
            result_lines.append(line)
            
        return "\n".join(result_lines)
        
    except Exception as e:
        return f"Error accessing order database: {str(e)}"
