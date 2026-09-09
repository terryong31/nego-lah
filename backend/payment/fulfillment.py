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
import sentry_sdk
import stripe

from connector import admin_supabase
from env import ADMIN_SUPABASE_KEY, STRIPE_API_KEY, SUPABASE_URL, USER_SUPABASE_KEY
from logger import logger

stripe.api_key = STRIPE_API_KEY


def broadcast_to_chat(user_id: str, content: str, role: str = "ai", source: str = "ai"):
    """
    Broadcast a message to the user's chat + notifications channels via Supabase
    Realtime and the SSE notification broker, so messages show up live.
    """
    try:
        broadcast_url = f"{SUPABASE_URL}/realtime/v1/api/broadcast"
        key = ADMIN_SUPABASE_KEY or USER_SUPABASE_KEY
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        payload = {
            "messages": [{
                "topic": f"chat:{user_id}",
                "event": "new_message",
                "payload": {"role": role, "source": source, "content": content},
            }]
        }
        requests.post(broadcast_url, json=payload, headers=headers, timeout=2)
        payload["messages"][0]["topic"] = f"notifications:{user_id}"
        requests.post(broadcast_url, json=payload, headers=headers, timeout=2)
        logger.info(f"📡 Broadcasted message to user {user_id}")
    except Exception as e:
        logger.warning(f"❌ Broadcast error: {e}")

    # The SSE stream is the buyer's "someone messaged you" channel, so only
    # messages addressed TO them belong on it. Their own outgoing text
    # (source="human", broadcast purely to sync the admin console) and system
    # separators stay on Realtime — otherwise the buyer gets toasted for
    # sentences they just typed.
    if source in ("human", "system"):
        return

    try:
        from notifications import notification_broker
        notification_broker.publish(user_id, {
            "type": "new_message",
            "message": content,
            "source": source,
            "role": role,
        })
    except Exception as e:
        logger.debug(f"Notification broker publish skipped: {e}")


# Postgres SQLSTATE for unique_violation. This is the idempotency anchor for the
# whole payment webhook: orders.stripe_payment_id is UNIQUE, so a duplicate
# insert means "already processed", not "broken".
UNIQUE_VIOLATION_SQLSTATE = "23505"


def _is_unique_violation(err: Exception) -> bool:
    """True when `err` is a Postgres unique-constraint violation.

    Prefers the structured SQLSTATE that PostgREST's `APIError` carries in
    `.code`. Matching on the message text instead is guesswork on a string
    formatted for humans: a row whose own data contains "already exists" reads
    as a duplicate, and a foreign-key violation that quotes a duplicate key in
    its detail line reads as one too — either way the webhook would swallow a
    real failure as successful idempotency (SPEC-037).

    A code that is present but *not* 23505 is positive evidence this is some
    other error, so it short-circuits to False. Text matching survives only as
    a fallback for exceptions carrying no code at all (transport failures, and
    the plain `Exception`s raised by test doubles).
    """
    code = getattr(err, "code", None)
    if code:
        return str(code) == UNIQUE_VIOLATION_SQLSTATE

    text = str(err).lower()
    return (
        "duplicate key" in text
        or UNIQUE_VIOLATION_SQLSTATE in text
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
    """Post + broadcast the post-purchase shipping-info prompt (once). Plain text without markdown formatting."""
    thank_you_msg = f"""🎉 Payment Confirmed!

Thank you for purchasing {item_name} for RM{amount:.2f}!

To complete your order, please provide your shipping details:
1. Full Name (recipient)
2. Phone Number
3. Shipping Address

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


def _finalize_won_sale(item_id, user_id, payment_intent, amount, item_name, buyer_email, order_id=None):
    """Side effects that run exactly once — only on the call that wins the claim."""
    if (not item_name or item_name.strip().lower() == "item") and item_id:
        try:
            item_res = admin_supabase.table('items').select('name').eq('id', item_id).execute()
            if item_res and item_res.data and item_res.data[0].get('name'):
                item_name = item_res.data[0]['name']
        except Exception as err:
            logger.warning(f"⚠️ Could not look up item name for {item_id}: {err}")

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

    # Deliver receipt to buyer and alert to seller
    try:
        # SPEC-048: the email Stripe captured at checkout is now pre-filled from
        # the buyer's account (SPEC-047's `customer_email`), so it's normally
        # reliable. Fall back to a direct account lookup when Stripe passed none
        # — a receipt that can't be addressed is a support ticket ("I paid and
        # got nothing").
        from payment.buyer import account_email

        resolved_buyer_email = buyer_email or account_email(user_id)

        from env import RESEND_FORWARD_TO, STRIPE_API_KEY
        from services.email_service import send_purchase_receipt, send_seller_sale_alert

        # In sandbox / dev mode (Stripe test key) the buyer email typed at
        # checkout is synthetic and Resend won't deliver to it via the
        # onboarding@resend.dev test sender. Fall back to RESEND_FORWARD_TO so
        # the receipt always reaches the developer's inbox during testing.
        is_sandbox = bool(STRIPE_API_KEY and STRIPE_API_KEY.startswith("sk_test_"))
        effective_buyer_email = resolved_buyer_email
        if is_sandbox and not effective_buyer_email and RESEND_FORWARD_TO:
            logger.info(
                f"ℹ️ Sandbox mode: no resolved buyer email for {user_id}; "
                f"redirecting receipt to RESEND_FORWARD_TO ({RESEND_FORWARD_TO})"
            )
            effective_buyer_email = RESEND_FORWARD_TO
        elif is_sandbox and effective_buyer_email and RESEND_FORWARD_TO:
            logger.info(
                f"ℹ️ Sandbox mode: buyer email is {effective_buyer_email!r}. "
                f"Note — onboarding@resend.dev can only deliver to your Resend account "
                f"owner email. If receipts aren't arriving, set RESEND_FORWARD_FROM to "
                f"a verified custom domain, or check your Resend dashboard logs."
            )

        logger.info(
            f"📧 Preparing order emails — buyer={effective_buyer_email!r} "
            f"order_id={order_id} item={item_name!r} amount=RM{amount:.2f}"
        )

        order_info = {
            "id": order_id or "N/A",
            "item_name": item_name,
            "amount": amount,
            "buyer_email": resolved_buyer_email,
            "buyer_id": user_id,
        }
        if effective_buyer_email:
            # SPEC-048: a receipt that silently fails to send is a support
            # ticket waiting to happen ("I paid and got nothing"). Make it loud.
            sent = send_purchase_receipt(effective_buyer_email, order_info)
            if not sent:
                msg = (
                    f"❌ Purchase receipt NOT delivered for order {order_id} "
                    f"(buyer {user_id}, {effective_buyer_email!r}) — Resend rejected every send attempt"
                )
                logger.error(msg)
                sentry_sdk.capture_message(
                    msg,
                    level="error",
                    tags={"alert": "receipt_undelivered", "order_id": str(order_id or "")},
                )
        else:
            msg = (
                f"❌ No buyer email resolved for order {order_id} (buyer {user_id}) — "
                f"receipt not sent. Set RESEND_FORWARD_TO to catch receipts in dev/sandbox."
            )
            logger.error(msg)
            sentry_sdk.capture_message(
                msg, level="error", tags={"alert": "receipt_no_address", "order_id": str(order_id or "")}
            )
        seller_target = RESEND_FORWARD_TO
        if seller_target:
            send_seller_sale_alert(seller_target, order_info)
    except Exception as mail_err:
        logger.warning(f"⚠️ Could not send order notifications via email: {mail_err}")


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

    # Resolve real item name from DB if missing or generic placeholder
    if (not item_name or item_name.strip().lower() == "item") and item_id:
        try:
            item_res = admin_supabase.table('items').select('name').eq('id', item_id).execute()
            if item_res and item_res.data and item_res.data[0].get('name'):
                item_name = item_res.data[0]['name']
        except Exception as err:
            logger.warning(f"⚠️ Could not look up item name for {item_id}: {err}")

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
        msg = f"❌ Order/buyer mismatch for {payment_intent}: {order_buyer} != {user_id}"
        logger.error(msg)
        sentry_sdk.capture_message(
            msg,
            level="fatal",
            tags={"alert": "buyer_mismatch", "payment_intent": payment_intent}
        )
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
        _finalize_won_sale(item_id, user_id, payment_intent, amount, item_name, buyer_email, order_id=order_id)
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
        msg = f"🚨 Auto-refund FAILED for {payment_intent} — order {order_id} left for retry"
        logger.error(msg)
        sentry_sdk.capture_message(
            msg,
            level="fatal",
            tags={"alert": "refund_failed", "payment_intent": payment_intent, "order_id": order_id}
        )
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
