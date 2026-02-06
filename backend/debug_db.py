from connector import admin_supabase
import sys

def check_broken_orders():
    print("Checking broken orders (buyer_id is NULL)...")
    try:
        # Get orders with no buyer_id
        response = admin_supabase.table('orders').select('*').is_('buyer_id', 'null').execute()
        orders = response.data
        
        if not orders:
            print("No broken orders found.")
            return

        print(f"Found {len(orders)} broken orders.")
        
        for order in orders:
            stripe_id = order.get('stripe_payment_id')
            print(f"Order {order['id']} (Item: {order['item_name']})")
            print(f"  Stripe ID: {stripe_id}")
            
            # Check Item Status
            item_id = order.get('item_id')
            if item_id:
                item_res = admin_supabase.table('items').select('*').eq('id', item_id).execute()
                if item_res.data:
                    item = item_res.data[0]
                    print(f"  Item Status: {item.get('status')}")
                    print(f"  Item Buyer ID: {item.get('buyer_id')}")
                else:
                    print("  Item not found.")
            
            print("-" * 30)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_broken_orders()
