import httpx
from fastapi import APIRouter, HTTPException, Request
from svix.webhooks import Webhook, WebhookVerificationError

from env import (
    RESEND_ALLOWED_RECIPIENTS,
    RESEND_API_KEY,
    RESEND_FORWARD_FROM,
    RESEND_FORWARD_TO,
    RESEND_WEBHOOK_SECRET,
)
from logger import logger

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/resend")
async def resend_webhook(request: Request):
    """
    Handle Resend inbound-email webhooks (event: email.received).

    negolah.my has no real mailbox yet, so every received email is simply
    forwarded to RESEND_FORWARD_TO via Resend's send API.
    """
    payload = await request.body()
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }

    try:
        event = Webhook(RESEND_WEBHOOK_SECRET).verify(payload, headers)
    except (WebhookVerificationError, ValueError):
        # ValueError also covers malformed (non-base64) signature/header values that
        # the svix/standardwebhooks library doesn't wrap in WebhookVerificationError.
        logger.error("❌ Resend webhook signature verification FAILED")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event.get("type")
    if event_type != "email.received":
        logger.info(f"ℹ️ Ignoring Resend event type: {event_type}")
        return {"status": "ignored"}

    data = event.get("data", {})
    sender = data.get("from", "")
    subject = data.get("subject", "(no subject)")
    # "to" is a list — inbound receiving is domain-wide, so this is the only
    # place we learn whether the mail was sent to contact@, support@, etc.
    recipients = data.get("to") or []
    allowed_recipients = [r for r in recipients if r.strip().lower() in RESEND_ALLOWED_RECIPIENTS]

    if not allowed_recipients:
        logger.info(f"ℹ️ Ignoring inbound email — recipient(s) not forwarded: {recipients}")
        return {"status": "ignored"}

    recipient = allowed_recipients[0]
    logger.info(f"📧 Inbound email received — to={recipient} from={sender} subject={subject!r}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
                json={
                    "from": RESEND_FORWARD_FROM,
                    "to": RESEND_FORWARD_TO,
                    "reply_to": sender,
                    "subject": f"[{recipient}] {subject}",
                    "html": data.get("html") or f"<pre>{data.get('text', '')}</pre>",
                    "text": data.get("text"),
                },
                timeout=10,
            )
            response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"❌ Failed to forward inbound email: {e}")
        raise HTTPException(status_code=503, detail="Forwarding failed, retry")

    return {"status": "success"}
