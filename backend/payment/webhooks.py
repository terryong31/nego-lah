import stripe
import requests
from connector import admin_supabase
from env import STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET, SUPABASE_URL, USER_SUPABASE_KEY

stripe.api_key = STRIPE_API_KEY


def broadcast_to_chat(user_id: str, content: str, role: str = "ai", source: str = "ai"):
    """
    Broadcast a message to user's chat channel via Supabase Realtime.
    This allows real-time display of AI messages triggered by webhooks.
    """
    try:
        # Broadcast to chat channel
        broadcast_url = f"{SUPABASE_URL}/realtime/v1/api/broadcast"
        headers = {
            "apikey": USER_SUPABASE_KEY,
            "Authorization": f"Bearer {USER_SUPABASE_KEY}",
            "Content-Type": "application/json"
        }
        
        # Broadcast to chat channel (for real-time chat display)
        payload = {
            "messages": [{
                "topic": f"realtime:chat:{user_id}",
                "event": "broadcast",
                "payload": {
                    "event": "new_message",
                    "payload": {
                        "role": role,
                        "source": source,
                        "content": content
                    }
                }
            }]
        }
        requests.post(broadcast_url, json=payload, headers=headers, timeout=2)
        
        # Also broadcast to notifications channel
        payload["messages"][0]["topic"] = f"realtime:notifications:{user_id}"
        requests.post(broadcast_url, json=payload, headers=headers, timeout=2)
        
        print(f"📡 Broadcasted message to user {user_id}")
    except Exception as e:
        print(f"❌ Broadcast error: {e}")


def handle_checkout_completed(event) -> bool:
    """
    Called when a Stripe payment is successful.
    
    1. Gets item_id and user_id from payment metadata
    2. Marks item as 'sold' and sets buyer_id
    3. Creates order record with status 'pending_info'
    4. Deletes pending payment from Redis
    5. Inserts AI message into conversation
    6. Broadcasts to user's chat for real-time display
    """
    session = event['data']['object']
    
    # Get metadata (we set this when creating checkout)
    metadata = session.get('metadata', {})
    item_id = metadata.get('item_id')
    user_id = metadata.get('user_id')
    item_name = metadata.get('item_name', 'Item')
    agreed_price = metadata.get('agreed_price')
    
    buyer_email = session.get('customer_details', {}).get('email')
    stripe_amount = session.get('amount_total', 0) / 100  # Convert from cents
    payment_intent = session.get('payment_intent')
    
    # Get the actual amount paid - priority order:
    # 1. agreed_price from Redis (set during AI negotiation)
    # 2. amount_total from Stripe session
    amount = stripe_amount  # Default to Stripe amount
    
    if user_id and item_id:
        try:
            from payment.payment_state import get_pending_payment
            pending = get_pending_payment(user_id, item_id)
            if pending and pending.get('agreed_price'):
                amount = float(pending['agreed_price'])
                print(f"✅ Using negotiated price from Redis: RM{amount}")
            else:
                print(f"ℹ️ No Redis price found, using Stripe amount: RM{amount}")
        except Exception as e:
            print(f"⚠️ Could not check pending payment: {e}")
    
    print(f"\n{'='*50}")
    print(f"💰 PAYMENT COMPLETED!")
    print(f"📦 Item: {item_name} (ID: {item_id})")
    print(f"👤 Buyer: {user_id} ({buyer_email})")
    print(f"💵 Amount: RM{amount}")
    print(f"{'='*50}")
    
    # FALLBACK: If user_id missing but we have email, warn about it
    # We relying on user_id being passed in metadata. 
    # Querying auth.users directly via client is not simple/efficient here without admin API.
    if not user_id and buyer_email:
        print(f"⚠️ Missing user_id in metadata. Email was: {buyer_email}")
        # Note: Previous fallback using public.users table was removed as table doesn't exist.

    if not item_id or not user_id:
        print("❌ Missing item_id or user_id in metadata")
        return False
    
    try:
        # 1. Mark item as sold and set buyer_id
        admin_supabase.table('items').update({
            'status': 'sold',
            'buyer_id': user_id
        }).eq('id', item_id).execute()
        print(f"✅ Item marked as sold, buyer_id set")
        
        # Invalidate cache so the status change shows up immediately
        try:
            from cache import invalidate_item_cache
            invalidate_item_cache(item_id)
            print(f"✅ Cache invalidated for item {item_id}")
        except Exception as e:
            print(f"⚠️ Could not invalidate cache: {e}")
        
        # 2. Create order record
        order_result = admin_supabase.table('orders').insert({
            'item_id': item_id,
            'item_name': item_name,
            'buyer_id': user_id,
            'amount': amount,
            'status': 'pending_info',
            'stripe_payment_id': payment_intent
        }).execute()
        
        order_id = order_result.data[0]['id'] if order_result.data else None
        print(f"✅ Order created: {order_id}")
        
        # 3. Delete pending payment from Redis
        try:
            from payment.payment_state import delete_pending_payment
            delete_pending_payment(user_id, item_id, cleanup_stripe=False)  # Don't cleanup Stripe - payment succeeded!
            print(f"✅ Removed from pending payments")
        except Exception as e:
            print(f"⚠️ Could not delete pending payment: {e}")
        
        # 4. Insert AI message into conversation memory
        thank_you_msg = f"""🎉 **Payment Confirmed!** 

Thank you for purchasing **{item_name}** for RM{amount:.2f}!

To complete your order, please provide your shipping details:
1. **Full Name** (recipient)
2. **Phone Number**
3. **Shipping Address**

Just reply with these details and I'll process your order right away!"""
        
        try:
            from agent.memory import conversation_memory
            conversation_memory.add_message(user_id, "ai", thank_you_msg, source="ai")
            print(f"✅ AI message added to conversation")
        except Exception as e:
            print(f"⚠️ Could not add message to memory: {e}")
        
        # 5. Broadcast to user's chat for real-time display
        broadcast_to_chat(user_id, thank_you_msg, role="ai", source="ai")
        
        # 6. Also record transaction (legacy table if exists)
        try:
            admin_supabase.table('transactions').insert({
                'item_id': item_id,
                'buyer_email': buyer_email,
                'amount': amount,
                'stripe_payment_id': payment_intent,
                'status': 'completed'
            }).execute()
        except Exception as e:
            print(f"⚠️ Could not record transaction: {e}")
        
        print(f"✅ Payment processing complete!")
        return True
        
    except Exception as e:
        print(f"❌ Error processing payment: {e}")
        return False


def verify_webhook(payload: bytes, sig_header: str):
    """
    Verify that the webhook actually came from Stripe.
    Returns the event if valid, None if invalid.
    """
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
        return event
    except ValueError:
        print("❌ Invalid payload")
        return None
    except stripe.error.SignatureVerificationError:
        print("❌ Invalid signature")
        return None
