"""
Payment State Management Module

Manages payment link lifecycle with 3-day TTL in Redis.
Stores Stripe IDs for cleanup when links expire or are cancelled.
"""

import json
from datetime import datetime
from typing import Optional, Dict
import stripe
from cache import redis_client
from env import STRIPE_API_KEY

stripe.api_key = STRIPE_API_KEY

# 3 days in seconds
PAYMENT_TTL = 3 * 24 * 60 * 60


def store_pending_payment(
    user_id: str,
    item_id: str,
    agreed_price: float,
    payment_link_id: str,
    product_id: str,
    price_id: str,
    payment_url: str
) -> bool:
    """
    Store payment link in Redis with 3-day TTL.
    
    Args:
        user_id: The user who will pay
        item_id: The item being purchased
        agreed_price: Agreed negotiated price
        payment_link_id: Stripe PaymentLink ID (for deactivation)
        product_id: Stripe Product ID (for archival)
        price_id: Stripe Price ID
        payment_url: The checkout URL
        
    Returns:
        True if stored successfully
    """
    key = f"payment:{user_id}:{item_id}"
    data = {
        "user_id": user_id,
        "item_id": item_id,
        "agreed_price": agreed_price,
        "payment_link_id": payment_link_id,
        "product_id": product_id,
        "price_id": price_id,
        "payment_url": payment_url,
        "created_at": datetime.now().isoformat()
    }
    
    try:
        redis_client.setex(key, PAYMENT_TTL, json.dumps(data))
        
        # Also add to cleanup queue (sorted set by expiry time)
        expiry_time = datetime.now().timestamp() + PAYMENT_TTL
        redis_client.zadd("payment:cleanup_queue", {key: expiry_time})
        
        return True
    except Exception as e:
        print(f"Error storing payment: {e}")
        return False


def get_pending_payment(user_id: str, item_id: str) -> Optional[Dict]:
    """
    Get active payment link for a user/item pair.
    
    Returns:
        Payment data dict or None if not found/expired
    """
    key = f"payment:{user_id}:{item_id}"
    data = redis_client.get(key)
    
    if data:
        return json.loads(data)
    return None

def get_active_payments_for_user(user_id: str) -> list:
    """
    Get all active payment links for a user.
    
    Returns:
        List of active payment URLs
    """
    pattern = f"payment:{user_id}:*"
    keys = redis_client.keys(pattern)
    
    urls = []
    for key in keys:
        if key != "payment:cleanup_queue":
            data = redis_client.get(key)
            if data:
                payment = json.loads(data)
                if payment.get('payment_url'):
                    urls.append(payment['payment_url'])
    
    return urls

def has_active_payment(user_id: str, item_id: str) -> bool:
    """Check if there's an active payment link for this user/item."""
    return get_pending_payment(user_id, item_id) is not None


def delete_pending_payment(user_id: str, item_id: str, cleanup_stripe: bool = True) -> bool:
    """
    Delete payment link from Redis and optionally deactivate in Stripe.
    
    Args:
        user_id: User ID
        item_id: Item ID
        cleanup_stripe: If True, deactivate payment link and archive product in Stripe
        
    Returns:
        True if deleted successfully
    """
    key = f"payment:{user_id}:{item_id}"
    
    # Get payment data before deleting
    payment = get_pending_payment(user_id, item_id)
    
    if payment and cleanup_stripe:
        try:
            # Deactivate payment link
            if payment.get("payment_link_id"):
                stripe.PaymentLink.modify(
                    payment["payment_link_id"],
                    active=False
                )
                print(f"✅ Deactivated PaymentLink: {payment['payment_link_id']}")
            
            # Archive product
            if payment.get("product_id"):
                stripe.Product.modify(
                    payment["product_id"],
                    active=False
                )
                print(f"✅ Archived Product: {payment['product_id']}")
                
        except Exception as e:
            print(f"Error cleaning up Stripe: {e}")
    
    # Delete from Redis
    redis_client.delete(key)
    
    # Remove from cleanup queue
    redis_client.zrem("payment:cleanup_queue", key)
    
    return True


def cleanup_expired_payments() -> int:
    """
    Background job: Clean up expired payment links from Stripe.
    
    This should be called periodically (e.g., hourly cron job).
    Checks the cleanup queue for entries that have expired.
    
    Returns:
        Number of cleaned up payments
    """
    now = datetime.now().timestamp()
    
    # Get expired entries from sorted set
    expired_keys = redis_client.zrangebyscore("payment:cleanup_queue", 0, now)
    
    cleaned = 0
    for key in expired_keys:
        # Check if the key still exists (might have been deleted already by successful payment)
        data = redis_client.get(key)
        
        if data:
            payment = json.loads(data)
            
            try:
                # Deactivate payment link
                if payment.get("payment_link_id"):
                    stripe.PaymentLink.modify(
                        payment["payment_link_id"],
                        active=False
                    )
                    print(f"🧹 Cleaned up expired PaymentLink: {payment['payment_link_id']}")
                
                # Archive product
                if payment.get("product_id"):
                    stripe.Product.modify(
                        payment["product_id"],
                        active=False
                    )
                    print(f"🧹 Archived expired Product: {payment['product_id']}")
                    
                cleaned += 1
            except Exception as e:
                print(f"Error cleaning up expired payment: {e}")
        
        # Remove from cleanup queue regardless
        redis_client.zrem("payment:cleanup_queue", key)
        redis_client.delete(key)
    
    if cleaned > 0:
        print(f"🧹 Cleaned up {cleaned} expired payment links")
    
    return cleaned


def get_all_pending_payments() -> list:
    """
    Get all pending payments (for admin/debugging).
    
    Returns:
        List of all pending payment dicts
    """
    pattern = "payment:*:*"
    keys = redis_client.keys(pattern)
    
    payments = []
    for key in keys:
        if key != "payment:cleanup_queue":
            data = redis_client.get(key)
            if data:
                payments.append(json.loads(data))
    
    return payments
