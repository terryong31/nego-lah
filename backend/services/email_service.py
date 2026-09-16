"""
Email Service Module
Handles sending transactional emails via Resend (production) or a local SMTP
sink / Mailpit (development, SPEC-074):
- Purchase receipts to buyers
- Sale alert notifications to sellers
- Unread message alerts to offline users
- Human-in-the-loop escalation alerts to admin
"""

import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape

from env import (
    ADMIN_NOTIFY_EMAIL,
    FRONTEND_URL,
    RESEND_API_KEY,
    RESEND_FORWARD_FROM,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PORT,
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


def _send_email(to_email: str, subject: str, html_content: str) -> bool:
    """Route one outbound email: local SMTP (Mailpit) when SMTP_HOST is set, Resend otherwise.

    Dev machines point SMTP_HOST at Mailpit (SPEC-074), so mail is caught
    locally instead of going to the real Resend API. SMTP wins even when a
    RESEND_API_KEY is still present in the dev environment — no dev machine
    should silently keep sending real mail. Production never sets SMTP_HOST
    and keeps the Resend path unchanged.
    """
    if SMTP_HOST:
        return _send_email_via_smtp(to_email, subject, html_content)
    return _send_email_via_resend(to_email, subject, html_content)


def send_email_raw(to_email: str, subject: str, html_content: str) -> bool:
    """Send pre-rendered HTML through the shared funnel.

    Escape hatch for senders outside this module that render their own
    templates (e.g. the admin OTP fallback) — they get the same
    Mailpit/Resend routing and failure semantics as every email_service sender.
    """
    return _send_email(to_email, subject, html_content)


def _send_email_via_smtp(to_email: str, subject: str, html_content: str) -> bool:
    """Deliver an email to the local dev SMTP sink (Mailpit)."""
    message = EmailMessage()
    message["From"] = SMTP_FROM or RESEND_FORWARD_FROM or "Nego-Lah <noreply@negolah.my>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(html_content, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10.0) as server:
            server.send_message(message)
        logger.info(
            f"📧 Email '{subject}' delivered to {to_email} via SMTP ({SMTP_HOST}:{SMTP_PORT})"
        )
        return True
    except Exception as err:
        logger.warning(f"⚠️ SMTP send to {to_email!r} via {SMTP_HOST}:{SMTP_PORT} failed: {err}")
        return False


def _send_email_via_resend(to_email: str, subject: str, html_content: str) -> bool:
    """Send an email via Resend API from the single verified domain sender."""
    if not RESEND_API_KEY:
        logger.warning("⚠️ RESEND_API_KEY is not configured; skipping email delivery.")
        return False

    # SPEC-074 Phase 2: one sender — the verified domain address. The old
    # multi-sender loop retried through Resend's onboarding@resend.dev sandbox
    # address, which only ever delivered to the account owner; dev mail goes to
    # Mailpit now, so a missing sender fails closed instead.
    if not RESEND_FORWARD_FROM:
        logger.error("❌ RESEND_FORWARD_FROM is not configured; refusing to send via Resend.")
        return False

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info(
        f"📧 _send_email_via_resend — to={to_email!r} subject={subject!r} "
        f"sender={RESEND_FORWARD_FROM!r}"
    )

    payload = {
        "from": RESEND_FORWARD_FROM,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }
    try:
        with httpx.Client(timeout=10.0) as http_client:
            resp = http_client.post("https://api.resend.com/emails", headers=headers, json=payload)
            if resp.status_code < 300:
                logger.info(f"📧 Email '{subject}' delivered to {to_email} via Resend")
                return True
            logger.warning(
                f"⚠️ Resend send → {to_email!r} returned HTTP {resp.status_code}: {resp.text}"
            )
    except Exception as err:
        logger.warning(f"⚠️ Resend send to {to_email!r} failed: {err}")

    logger.error(f"❌ Resend send failed for {to_email!r} (subject: {subject!r})")
    return False


def send_purchase_receipt(buyer_email: str, order: dict) -> bool:
    """Send an order purchase receipt to the buyer."""
    item_name = order.get("item_name") or "Item"
    amount = float(order.get("amount") or 0.0)
    order_id = order.get("id") or order.get("order_id") or "N/A"
    date_str = datetime.now(UTC).strftime("%B %d, %Y")

    subject = f"Payment confirmed — {item_name}"
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
    return _send_email(buyer_email, subject, html)


def send_shipment_notice(buyer_email: str, order: dict, delivered: bool = False) -> bool:
    """Tell the buyer their order has shipped (or arrived).

    SPEC-057. The facts come from `shipping_notice.shipment_summary` rather than
    being pulled off the order here, so this email, the chat bubble and the
    agent's answer cannot end up describing different shipments.
    """
    from services.shipping_notice import shipment_summary

    if not buyer_email:
        logger.warning("No buyer email on this order; skipping shipment notice.")
        return False

    facts = shipment_summary(order)
    item_name = facts["item_name"]
    subject = (
        f"Delivered — {item_name}" if delivered else f"On its way — {item_name}"
    )

    context = {
        "subject": subject,
        "date_str": datetime.now(UTC).strftime("%B %d, %Y"),
        "chat_url": f"{FRONTEND_URL}/chat",
        "orders_url": f"{FRONTEND_URL}/orders",
        "delivered": delivered,
        **facts,
    }
    html = render_email_template("shipment_notice.html", context)
    return _send_email(buyer_email, subject, html)


def send_seller_sale_alert(seller_email: str, order: dict) -> bool:
    """Send an email alert to the seller notifying them that an item was bought."""
    item_name = order.get("item_name") or "Item"
    amount = float(order.get("amount") or 0.0)
    order_id = order.get("id") or order.get("order_id") or "N/A"
    buyer_email = order.get("buyer_email") or order.get("buyer_id") or "Nego-Lah Buyer"
    date_str = datetime.now(UTC).strftime("%B %d, %Y")

    subject = f"You sold {item_name} for RM{amount:.2f}"
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

    target_email = seller_email or ADMIN_NOTIFY_EMAIL
    if not target_email:
        logger.warning("No seller email configured; skipping seller sale alert.")
        return False
    return _send_email(target_email, subject, html)


def send_unread_message_email(buyer_email: str, message_snippet: str, item_name: str | None = None) -> bool:
    """Send an email alert to a buyer notifying them of unread messages from the seller."""
    subject = "New message from the seller" + (f" — {item_name}" if item_name else "")
    chat_url = f"{FRONTEND_URL}/chat"

    context = {
        "subject": subject,
        "message_snippet": message_snippet,
        "item_name": item_name,
        "chat_url": chat_url,
    }
    html = render_email_template("unread_message.html", context)
    return _send_email(buyer_email, subject, html)


def send_unread_digest_email(
    buyer_email: str,
    messages: list[dict],
    item_name: str | None = None,
) -> bool:
    """Send ONE email covering every seller message queued for this buyer.

    SPEC-052: replaces the per-message send. `messages` are oldest-first, each
    a dict with at least `content`; anything without content is dropped rather
    than rendering an empty quote block.
    """
    bodies = [
        {"content": (m.get("content") or "").strip()}
        for m in (messages or [])
        if (m.get("content") or "").strip()
    ]
    if not bodies:
        logger.info("No message bodies to digest; skipping unread digest email.")
        return False

    count = len(bodies)
    if count == 1:
        subject = "New message from the seller" + (f" — {item_name}" if item_name else "")
    else:
        subject = f"{count} new messages from the seller" + (f" — {item_name}" if item_name else "")

    chat_url = f"{FRONTEND_URL}/chat"
    context = {
        "subject": subject,
        "messages": bodies,
        "count": count,
        "item_name": item_name,
        "chat_url": chat_url,
    }
    html = render_email_template("unread_digest.html", context)
    return _send_email(buyer_email, subject, html)


def send_human_transfer_alert(user_id: str, reason: str, user_email: str = None, summary: str = None) -> bool:
    """Send an urgent alert to the admin/seller when an AI chat is transferred to human."""
    admin_email = ADMIN_NOTIFY_EMAIL or "terry@negolah.my"
    user_display = user_email or user_id
    subject = f"Action needed: chat handed to you — {user_display}"
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
    return _send_email(admin_email, subject, html)
