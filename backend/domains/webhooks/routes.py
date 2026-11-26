import base64
import email as email_lib
import html
import json
import re
from email import policy as email_policy

import httpx
from fastapi import APIRouter, HTTPException, Request
from svix.webhooks import Webhook, WebhookVerificationError

from core.env import (
    RESEND_ALLOWED_RECIPIENTS,
    RESEND_API_KEY,
    RESEND_FORWARD_FROM,
    RESEND_FORWARD_TO,
    RESEND_WEBHOOK_SECRET,
)
from core.logger import logger
from core.url import is_safe_http_url

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# SPEC-116 / SEC-23: prevent path traversal in Resend email_id URL interpolation
# and cap raw email downloads so a single inbound message cannot OOM a 2 GB host.
_EMAIL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
MAX_INBOUND_RAW_BYTES = 25 * 1024 * 1024


@router.post("/resend")
async def resend_webhook(request: Request):
    """
    Handle Resend inbound-email webhooks (event: email.received).

    negolah.my has no real mailbox yet, so every received email — including
    inline images and real file attachments — is forwarded to RESEND_FORWARD_TO
    via Resend's send API.
    """
    payload = await request.body()
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }

    try:
        # svix's verify() only validates the signature and returns None — it does
        # not hand back the parsed body — so the event still has to be parsed
        # from the raw payload separately below.
        Webhook(RESEND_WEBHOOK_SECRET).verify(payload, headers)
    except (WebhookVerificationError, ValueError):
        # ValueError also covers malformed (non-base64) signature/header values that
        # the svix/standardwebhooks library doesn't wrap in WebhookVerificationError.
        logger.warning("Resend webhook signature verification failed: invalid signature or headers")
        raise HTTPException(status_code=400, detail="Invalid webhook signature") from None

    event = json.loads(payload)
    event_type = event.get("type")
    if event_type != "email.received":
        logger.info(f"ℹ️ Ignoring Resend event type: {event_type}")
        return {"status": "ignored"}

    data = event.get("data", {})
    sender = data.get("from", "")
    subject = data.get("subject", "(no subject)")
    email_id = data.get("email_id")
    if not isinstance(email_id, str) or not _EMAIL_ID_RE.match(email_id):
        logger.warning("Rejecting Resend webhook with invalid email_id")
        raise HTTPException(status_code=400, detail="Invalid email_id")
    # "to" is a list — inbound receiving is domain-wide, so this is the only
    # place we learn whether the mail was sent to contact@, support@, etc.
    recipients = data.get("to") or []
    allowed_recipients = [r for r in recipients if r.strip().lower() in RESEND_ALLOWED_RECIPIENTS]

    if not allowed_recipients:
        logger.info(f"ℹ️ Ignoring inbound email — recipient(s) not forwarded: {recipients}")
        return {"status": "ignored"}

    # A single email can be addressed to more than one allowlisted alias at
    # once (e.g. support@ + admin@ + contact@ all in "to"). Tag all of them
    # rather than just the first — one forwarded copy still goes out either way.
    recipient_tag = ", ".join(allowed_recipients)
    logger.info(f"Inbound email received — to={recipient_tag} from={sender} subject={subject!r}")

    try:
        async with httpx.AsyncClient() as client:
            auth_headers = {"Authorization": f"Bearer {RESEND_API_KEY}"}

            # The webhook payload only carries metadata (from/to/subject/etc.) —
            # the actual body has to be fetched separately by email_id.
            # html_format=data_uri inlines any embedded images as base64 data:
            # URIs directly in the html; otherwise they're left as cid: references
            # that only resolve against the original message's own attachments,
            # which we don't carry over — Gmail would show a broken image icon.
            fetch_resp = await client.get(
                f"https://api.resend.com/emails/receiving/{email_id}",
                headers=auth_headers,
                params={"html_format": "data_uri"},
                timeout=10,
            )
            fetch_resp.raise_for_status()
            email_content = fetch_resp.json()

            # Real (non-inline) attachments aren't in this payload at all — only
            # their metadata is. To get the actual file bytes we have to download
            # the whole original message and pull the attachment parts out of it.
            outbound_attachments = []
            real_attachments = [
                a for a in (email_content.get("attachments") or []) if a.get("content_disposition") != "inline"
            ]
            download_url = (email_content.get("raw") or {}).get("download_url")
            if real_attachments and download_url and is_safe_http_url(download_url):
                raw_resp = await client.get(download_url, timeout=30)
                raw_resp.raise_for_status()
                raw_headers = getattr(raw_resp, "headers", None)
                declared_len: int | None = None
                if raw_headers is not None and hasattr(raw_headers, "get"):
                    raw_cl = raw_headers.get("content-length")
                    if isinstance(raw_cl, (int, str)):
                        try:
                            declared_len = int(raw_cl)
                        except ValueError:
                            declared_len = None
                if (declared_len is not None and declared_len > MAX_INBOUND_RAW_BYTES) or (
                    len(raw_resp.content) > MAX_INBOUND_RAW_BYTES
                ):
                    logger.warning("Rejecting oversized Resend raw email payload")
                    raise HTTPException(status_code=413, detail="Inbound email payload too large")
                msg = email_lib.message_from_bytes(raw_resp.content, policy=email_policy.default)
                for part in msg.iter_attachments():
                    # Inline images are already embedded in the html above — skip
                    # them here so they aren't sent twice.
                    if part.get_content_disposition() == "inline":
                        continue
                    content = part.get_payload(decode=True)
                    if not content:
                        continue
                    outbound_attachments.append(
                        {
                            "filename": part.get_filename() or "attachment",
                            "content": base64.b64encode(content).decode(),
                            "content_type": part.get_content_type(),
                        }
                    )
                logger.info(f"Forwarding {len(outbound_attachments)} attachment(s)")

            send_payload = {
                "from": RESEND_FORWARD_FROM,
                "to": RESEND_FORWARD_TO,
                "reply_to": sender,
                "subject": f"[{recipient_tag}] {subject}",
                # A text-only email is text: escaped, or its `<` would be markup.
                "html": email_content.get("html") or f"<pre>{html.escape(email_content.get('text') or '')}</pre>",
                "text": email_content.get("text"),
            }
            if outbound_attachments:
                send_payload["attachments"] = outbound_attachments

            response = await client.post(
                "https://api.resend.com/emails",
                headers=auth_headers,
                json=send_payload,
                timeout=30,
            )
            response.raise_for_status()
    except httpx.HTTPError as e:
        logger.error(f"Failed to fetch/forward inbound email: {e}")
        raise HTTPException(status_code=503, detail="Forwarding failed, retry") from e

    return {"status": "success"}
