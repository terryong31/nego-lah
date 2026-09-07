"""
Email Service Module
Handles sending transactional emails via Resend:
- Purchase receipts to buyers
- Sale alert notifications to sellers
- Unread message alerts to offline users
- Human-in-the-loop escalation alerts to admin
"""

from datetime import UTC, datetime
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from env import (
    FRONTEND_URL,
    RESEND_API_KEY,
    RESEND_FORWARD_FROM,
    RESEND_FORWARD_TO,
    STORAGE_BUCKET,
    SUPABASE_URL,
)
from logger import logger

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"

_jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def get_brand_logo_url() -> str:
    """Return the public CDN URL for the brand logo."""
    base_url = SUPABASE_URL.rstrip("/") if SUPABASE_URL else "https://umtsegjkgpfefjvhyysh.supabase.co"
    bucket = STORAGE_BUCKET or "images"
    return f"{base_url}/storage/v1/object/public/{bucket}/branding/logo.png"


def render_email_template(template_name: str, context: dict) -> str:
    """Render an email HTML template using Jinja2 with default brand context."""
    defaults = {
        "brand_logo_url": get_brand_logo_url(),
        "frontend_url": FRONTEND_URL,
    }
    merged_context = {**defaults, **context}
    template = _jinja_env.get_template(template_name)
    return template.render(**merged_context)


def _send_email_via_resend(to_email: str, subject: str, html_content: str) -> bool:
    """Send an email via Resend API."""
    if not RESEND_API_KEY:
        logger.warning("⚠️ RESEND_API_KEY is not configured; skipping email delivery.")
        return False

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    senders = []
    if RESEND_FORWARD_FROM:
        senders.append(RESEND_FORWARD_FROM)
    senders.append("Nego-lah <onboarding@resend.dev>")

    seen = set()
    unique_senders = [s for s in senders if s and not (s in seen or seen.add(s))]

    logger.info(
        f"📧 _send_email_via_resend — to={to_email!r} subject={subject!r} "
        f"senders={unique_senders}"
    )

    # NOTE (sandbox / dev): Resend's onboarding@resend.dev test sender can ONLY
    # deliver to the verified Resend account owner's email address. Any other
    # recipient will be silently rejected (HTTP 2xx but no delivery). If you're
    # hitting this in development, set RESEND_FORWARD_FROM to a custom domain
    # you've verified in Resend, or set RESEND_TEST_OVERRIDE_TO to redirect all
    # outbound mail to your own inbox.

    for sender in unique_senders:
        payload = {
            "from": sender,
            "to": [to_email],
            "subject": subject,
            "html": html_content,
        }
        try:
            with httpx.Client(timeout=10.0) as http_client:
                resp = http_client.post("https://api.resend.com/emails", headers=headers, json=payload)
                if resp.status_code < 300:
                    logger.info(f"📧 Email '{subject}' delivered to {to_email} via Resend (sender: {sender})")
                    return True
                logger.warning(
                    f"⚠️ Resend send attempt from {sender!r} → {to_email!r} "
                    f"returned HTTP {resp.status_code}: {resp.text}"
                )
        except Exception as err:
            logger.warning(f"Resend send attempt from {sender} failed: {err}")

    logger.error(f"❌ All Resend send attempts failed for {to_email!r} (subject: {subject!r})")
    return False


def send_purchase_receipt(buyer_email: str, order: dict) -> bool:
    """Send an order purchase receipt to the buyer."""
    item_name = order.get("item_name") or "Item"
    amount = float(order.get("amount") or 0.0)
    order_id = order.get("id") or order.get("order_id") or "N/A"
    date_str = datetime.now(UTC).strftime("%B %d, %Y")

    subject = f"Receipt for your purchase: {item_name} - Nego-Lah"
    chat_url = f"{FRONTEND_URL}/chat"
    orders_url = f"{FRONTEND_URL}/orders"

    context = {
        "subject": subject,
        "item_name": item_name,
        "amount": amount,
        "order_id": order_id,
        "date_str": date_str,
        "chat_url": chat_url,
        "orders_url": orders_url,
    }
    html = render_email_template("purchase_receipt.html", context)
    return _send_email_via_resend(buyer_email, subject, html)


def send_seller_sale_alert(seller_email: str, order: dict) -> bool:
    """Send an email alert to the seller notifying them that an item was bought."""
    item_name = order.get("item_name") or "Item"
    amount = float(order.get("amount") or 0.0)
    order_id = order.get("id") or order.get("order_id") or "N/A"
    buyer_email = order.get("buyer_email") or order.get("buyer_id") or "Nego-Lah Buyer"
    date_str = datetime.now(UTC).strftime("%B %d, %Y")

    subject = f"🎉 Item Sold: {item_name} (RM{amount:.2f}) - Nego-Lah"
    admin_orders_url = f"{FRONTEND_URL}/_console/orders"

    context = {
        "subject": subject,
        "item_name": item_name,
        "amount": amount,
        "order_id": order_id,
        "buyer_email": buyer_email,
        "date_str": date_str,
        "admin_orders_url": admin_orders_url,
    }
    html = render_email_template("seller_sale_alert.html", context)

    target_email = seller_email or RESEND_FORWARD_TO
    if not target_email:
        logger.warning("No seller email configured; skipping seller sale alert.")
        return False
    return _send_email_via_resend(target_email, subject, html)


def send_unread_message_email(buyer_email: str, message_snippet: str, item_name: str | None = None) -> bool:
    """Send an email alert to a buyer notifying them of unread messages from the seller."""
    subject = f"New message from seller on Nego-Lah{f': {item_name}' if item_name else ''}"
    chat_url = f"{FRONTEND_URL}/chat"

    context = {
        "subject": subject,
        "message_snippet": message_snippet,
        "item_name": item_name,
        "chat_url": chat_url,
    }
    html = render_email_template("unread_message.html", context)
    return _send_email_via_resend(buyer_email, subject, html)


def send_human_transfer_alert(user_id: str, reason: str, user_email: str = None, summary: str = None) -> bool:
    """Send an urgent alert to the admin/seller when an AI chat is transferred to human."""
    admin_email = RESEND_FORWARD_TO or "terry@negolah.my"
    user_display = user_email or user_id
    subject = f"🚨 Human Transfer Required: {user_display} - Nego-Lah"
    console_chat_url = f"{FRONTEND_URL}/_console/chats?user={user_id}"
    date_str = datetime.now(UTC).strftime("%B %d, %Y %H:%M UTC")

    reason_str = reason or "Customer requested human intervention"
    summary_str = summary or "The conversation requires human assistance."

    context = {
        "subject": subject,
        "user_id": user_id,
        "user_display": user_display,
        "reason": reason_str,
        "summary": summary_str,
        "console_chat_url": console_chat_url,
        "date_str": date_str,
    }
    html = render_email_template("human_transfer_alert.html", context)
    return _send_email_via_resend(admin_email, subject, html)
