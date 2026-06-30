"""
Order fulfillment — the single source of truth for turning a successful Stripe
payment into a sold item + order record.

Both entry points (the Stripe webhook and the frontend `confirm-payment`
fallback) funnel through `fulfill_purchase`. It is designed to be:

  * Idempotent — the same payment can be delivered/confirmed any number of
    times and will only ever produce ONE order. The idempotency key is the
    Stripe PaymentIntent id, persisted as orders.stripe_payment_id which has a
    UNIQUE constraint (see migrations/ note). The first writer wins the insert;
    every subsequent attempt hits the unique violation and no-ops.

  * Race-safe — if two different buyers pay for the same item at the same time,
    the item is claimed with an atomic conditional UPDATE (only succeeds while
    status = 'available'). Exactly one buyer wins; the loser is automatically
    refunded so nobody is left charged for an item they can't receive.
"""

import requests
import stripe

from connector import admin_supabase
from env import STRIPE_API_KEY, SUPABASE_URL, USER_SUPABASE_KEY
from logger import logger

stripe.api_key = STRIPE_API_KEY


def broadcast_to_chat(user_id: str, content: str, role: str = "ai", source: str = "ai"):
    """
    Broadcast a message to the user's chat + notifications channels via Supabase
    Realtime, so AI messages triggered by webhooks show up live.
    """
    try:
        broadcast_url = f"{SUPABASE_URL}/realtime/v1/api/broadcast"
        headers = {
            "apikey": USER_SUPABASE_KEY,
            "Authorization": f"Bearer {USER_SUPABASE_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "messages": [{
                "topic": f"chat:{user_id}",
                "event": "broadcast",
                "payload": {
                    "event": "new_message",
                    "payload": {"role": role, "source": source, "content": content},
                },
            }]
        }
        requests.post(broadcast_url, json=payload, headers=headers, timeout=2)
        payload["messages"][0]["topic"] = f"notifications:{user_id}"
        requests.post(broadcast_url, json=payload, headers=headers, timeout=2)
        logger.info(f"📡 Broadcasted message to user {user_id}")
    except Exception as e:
        logger.warning(f"❌ Broadcast error: {e}")


def _is_unique_violation(err: Exception) -> bool:
    """Best-effort detection of a Postgres unique-constraint violation."""
    text = str(err).lower()
    return (
        "duplicate key" in text
        or "23505" in text
        or "already exists" in text
        or "unique constraint" in text
    )


def _refund(payment_intent: str, reason: str = "duplicate") -> bool:
    """
    Refund a PaymentIntent. Returns True on success.

    Uses a deterministic Stripe idempotency key so that retries / webhook
    re-deliveries for the same payment can never create a second refund.
    """
    if not payment_intent or payment_intent.startswith("nopi_"):
        return False
    try:
        stripe.Refund.create(
            payment_intent=payment_intent,
            reason=reason,
            idempotency_key=f"auto_refund_{payment_intent}",
        )
        logger.info(f"💸 Auto-refunded payment {payment_intent} ({reason})")
        return True
    except stripe.error.InvalidRequestError as e:
        # e.g. charge already refunded — treat as already-done, not a failure.
        logger.warning(f"↩️ Refund for {payment_intent} not needed/possible: {e}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to auto-refund {payment_intent}: {e}")
        return False


def _send_thank_you(user_id: str, item_name: str, amount: float):
    """Post + broadcast the post-purchase shipping-info prompt (once)."""
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
    except Exception as e:
        logger.warning(f"⚠️ Could not add thank-you to memory: {e}")
    broadcast_to_chat(user_id, thank_you_msg, role="ai", source="ai")


def _get_or_create_order(payment_intent, item_id, user_id, amount, item_name):
    """
    Ensure exactly one order exists for this PaymentIntent (the idempotency
    anchor — orders.stripe_payment_id is UNIQUE). Returns
    (order_id, status, buyer_id) or (None, None, None) on hard error.
    """
    try:
        res = admin_supabase.table('orders').insert({
            'item_id': item_id,
            'item_name': item_name,
            'buyer_id': user_id,
            'amount': amount,
            'status': 'pending_info',
            'stripe_payment_id': payment_intent,
        }).execute()
        row = res.data[0] if res.data else {}
        return row.get('id'), 'pending_info', user_id
    except Exception as e:
        if _is_unique_violation(e):
            existing = (admin_supabase.table('orders')
                        .select('id, status, buyer_id')
                        .eq('stripe_payment_id', payment_intent)
                        .limit(1).execute())
            if existing.data:
                r = existing.data[0]
                return r.get('id'), r.get('status'), r.get('buyer_id')
        logger.error(f"❌ Order upsert failed for {payment_intent}: {e}")
        return None, None, None


def _finalize_won_sale(item_id, user_id, payment_intent, amount, item_name, buyer_email):
    """Side effects that run exactly once — only on the call that wins the claim."""
    logger.info(f"✅ Item {item_id} sold to {user_id} (payment {payment_intent})")

    try:
        from cache import invalidate_item_cache
        invalidate_item_cache(item_id)
    except Exception as e:
        logger.warning(f"⚠️ Cache invalidate failed: {e}")

    try:
        from payment.payment_state import delete_pending_payment
        delete_pending_payment(user_id, item_id, cleanup_stripe=True)
    except Exception as e:
        logger.warning(f"⚠️ Could not delete pending payment: {e}")

    try:
        admin_supabase.table('transactions').insert({
            'item_id': item_id,
            'buyer_email': buyer_email,
            'amount': amount,
            'stripe_payment_id': payment_intent,
            'status': 'completed',
        }).execute()
    except Exception as e:
        if not _is_unique_violation(e):
            logger.warning(f"⚠️ Could not record transaction: {e}")

    _send_thank_you(user_id, item_name, amount)


def fulfill_purchase(
    item_id: str,
    user_id: str,
    payment_intent: str,
    amount: float,
    item_name: str = "Item",
    buyer_email: str = None,
) -> dict:
    """
    Idempotently + atomically fulfil a paid purchase. Safe to call any number of
    times for the same payment (webhook retries, frontend confirm), and
    re-entrant if a previous attempt died partway.

    Returns a dict with a "status" of:
      - "fulfilled"  : this call claimed the item (the one-time transition)
      - "duplicate"  : already fulfilled to this buyer — no-op
      - "race_lost"  : item went to another buyer; this payment refunded
      - "error"      : transient failure (caller should let Stripe retry)
    """
    if not item_id or not user_id:
        logger.error("❌ fulfill_purchase missing item_id or user_id")
        return {"status": "error", "error": "missing_item_or_user"}

    if not payment_intent:
        # Without a PaymentIntent we cannot guarantee idempotency or refund.
        logger.warning("⚠️ fulfill_purchase called without payment_intent — idempotency degraded")
        payment_intent = f"nopi_{user_id}_{item_id}"

    # --- Step 1: ensure the canonical order exists (idempotency anchor) -----
    order_id, order_status, order_buyer = _get_or_create_order(
        payment_intent, item_id, user_id, amount, item_name
    )
    if order_id is None:
        return {"status": "error", "error": "order_upsert_failed"}

    # A redelivery of a payment we already refunded — never refund/charge twice.
    if order_status == 'refunded':
        logger.info(f"ℹ️ Payment {payment_intent} already refunded — no-op")
        return {"status": "race_lost", "refunded": True, "order_id": order_id}

    # Guard: the order on file must belong to the same buyer as this payment.
    if order_buyer and order_buyer != user_id:
        logger.error(f"❌ Order/buyer mismatch for {payment_intent}: {order_buyer} != {user_id}")
        return {"status": "error", "error": "buyer_mismatch"}

    # --- Step 2: claim the ITEM atomically --------------------------------
    # This is the single authority. It transitions available -> sold exactly
    # once; whichever concurrent payment runs this UPDATE first wins. Because it
    # is conditional on status='available', it is also safe to re-run after a
    # partial failure (a previous attempt that created the order but died here).
    claim = (admin_supabase.table('items')
             .update({'status': 'sold', 'buyer_id': user_id})
             .eq('id', item_id)
             .eq('status', 'available')
             .execute())

    if claim.data:
        # We performed the transition — run the one-time side effects.
        _finalize_won_sale(item_id, user_id, payment_intent, amount, item_name, buyer_email)
        return {"status": "fulfilled", "order_id": order_id}

    # --- Claim failed: already sold. Ours (duplicate) or someone else's? ----
    item_res = admin_supabase.table('items').select('status, buyer_id').eq('id', item_id).execute()
    item_row = item_res.data[0] if item_res.data else None

    if item_row and item_row.get('status') == 'sold' and item_row.get('buyer_id') == user_id:
        # Already fulfilled to this buyer (duplicate delivery / concurrent path).
        logger.info(f"ℹ️ Payment {payment_intent} already fulfilled to buyer — no-op")
        return {"status": "duplicate", "order_id": order_id}

    # Lost the race to a different buyer (or item gone). Refund this payment.
    logger.warning(f"⚠️ Item {item_id} went to another buyer — refunding {payment_intent}")
    refunded = _refund(payment_intent, reason="duplicate")

    if not refunded:
        # The refund did NOT go through. Do not lie to the buyer or mark the
        # order refunded — leave it for retry so we never report a refund that
        # didn't happen. Returning "error" makes the webhook caller signal Stripe
        # to redeliver; the Stripe idempotency key prevents a double refund.
        logger.error(f"🚨 Auto-refund FAILED for {payment_intent} — order {order_id} left for retry")
        return {"status": "error", "error": "refund_failed", "order_id": order_id}

    try:
        admin_supabase.table('orders').update({'status': 'refunded'}).eq('id', order_id).execute()
    except Exception as e:
        logger.warning(f"⚠️ Could not mark losing order refunded: {e}")
    broadcast_to_chat(
        user_id,
        "😔 Sorry — that item was bought by someone else moments before your payment. "
        "You have been fully refunded; it may take a few days to appear.",
        role="ai", source="ai",
    )
    return {"status": "race_lost", "refunded": True, "order_id": order_id}
