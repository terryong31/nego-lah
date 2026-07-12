"""
Script to check for fulfillment anomalies:
- Orders that are stuck in 'pending_info' (or not 'refunded') for items that were sold to someone else.
- Orders indicating a buyer mismatch or stuck refunds that require manual intervention.

This script should be run periodically (e.g. daily via cron or GitHub Actions).
"""

import logging
import os
import sys
from datetime import UTC, datetime, timedelta

# Add parent directory to path so we can import backend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sentry_sdk
import stripe

from connector import admin_supabase
from env import STRIPE_API_KEY

stripe.api_key = STRIPE_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize sentry if configured
sentry_dsn = os.environ.get("SENTRY_DSN")
if sentry_dsn:
    sentry_sdk.init(dsn=sentry_dsn, environment=os.environ.get("ENV", "development"))

def check_anomalies():
    logger.info("Starting fulfillment anomaly check...")
    anomalies_found = 0

    # 1. Find orders that are 'pending_info' but the item is sold to someone else.
    orders_res = admin_supabase.table("orders").select("id, item_id, buyer_id, stripe_payment_id, created_at, status").eq("status", "pending_info").execute()

    if not orders_res.data:
        logger.info("No pending_info orders found.")
        return

    now = datetime.now(UTC)

    for order in orders_res.data:
        order_id = order["id"]
        item_id = order["item_id"]
        buyer_id = order["buyer_id"]
        payment_intent_id = order.get("stripe_payment_id")
        created_at_str = order.get("created_at")

        try:
            if "." in created_at_str:
                created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%S.%f%z")
            else:
                created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%S%z")
        except Exception:
            created_at = now

        age = now - created_at

        item_res = admin_supabase.table("items").select("status, buyer_id").eq("id", item_id).execute()
        if not item_res.data:
            continue

        item = item_res.data[0]

        # If item is sold to someone else
        if item.get("status") == "sold" and item.get("buyer_id") != buyer_id:
            # SLA: check if older than 24 hours to alert manually
            if age > timedelta(hours=24):
                if payment_intent_id and payment_intent_id.startswith("pi_"):
                    try:
                        pi = stripe.PaymentIntent.retrieve(payment_intent_id)

                        if pi.status == "succeeded":
                            latest_charge = pi.latest_charge
                            if latest_charge:
                                charge = stripe.Charge.retrieve(latest_charge)
                                if not charge.refunded:
                                    msg = (
                                        f"🚨 SLA Violation / Stuck Refund: Order {order_id} (buyer {buyer_id}) stuck in pending_info >24h. "
                                        f"Item {item_id} sold to {item.get('buyer_id')}. "
                                        f"Payment {payment_intent_id} succeeded but is NOT refunded."
                                    )
                                    logger.error(msg)
                                    sentry_sdk.capture_message(
                                        msg,
                                        level="fatal",
                                        tags={"alert": "stuck_refund_sla", "order_id": order_id, "payment_intent": payment_intent_id}
                                    )
                                    anomalies_found += 1
                                    continue
                    except Exception as e:
                        logger.error(f"Error checking Stripe for {payment_intent_id}: {e}")

                # General >24h warning if not caught above
                msg = f"⚠️ Order {order_id} (buyer {buyer_id}) stuck >24h for item {item_id} sold to someone else."
                logger.warning(msg)
                sentry_sdk.capture_message(
                    msg,
                    level="warning",
                    tags={"alert": "stuck_order_sla", "order_id": order_id}
                )
                anomalies_found += 1

    logger.info(f"Anomaly check complete. Found {anomalies_found} anomalies.")

if __name__ == "__main__":
    check_anomalies()
