import sys
import os
import json

# Ensure we can import from local modules
sys.path.append(os.getcwd())

# Mock FastAPI dependencies if needed, but get_all_orders just imports inside
from routes.admin import get_all_orders

def test_enrichment():
    try:
        print("Fetching orders...")
        data = get_all_orders()
        
        print("\n=== STATS ===")
        print(json.dumps(data.get('stats'), indent=2))
        
        orders = data.get('orders', [])
        print(f"\n=== ORDERS ({len(orders)}) ===")
        
        if orders:
            # Check first 3 orders
            for i, order in enumerate(orders[:3]):
                print(f"\nOrder #{i+1}:")
                print(f"  Item: {order.get('item_name')}")
                print(f"  Amount: {order.get('amount')}")
                print(f"  Status: {order.get('status')}")
                print(f"  Buyer ID: {order.get('buyer_id')}")
                print(f"  Buyer Name: {order.get('buyer_name')}")   # Should be populated
                print(f"  Buyer Email: {order.get('buyer_email')}") # Should be populated
        else:
            print("No orders found.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_enrichment()
