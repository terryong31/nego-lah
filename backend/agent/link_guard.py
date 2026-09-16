"""Only a payment link this server issued may reach the buyer (SPEC-088).

SPEC-056 #4 allowlisted the *host* a PayCard may point at. A model can invent
more than a host: observed in production, with the SPEC-087 trace proving no
tool ran,

    [Pay RM2500 Now](https://checkout.stripe.com/pay/<the item's own uuid>?price=2500)

The host is genuine, so it passed, and the buyer was shown the "Deal Agreed /
Secured by Stripe" tile over a URL that does not exist.

The server knows which URL it issued — `create_checkout_link` stores it in
`payment_state` — so that is what the agent's text is checked against. A link is
kept only if it matches exactly. Everything else is removed, including a link on
a trusted host, and including every link when no payment was ever created.
"""

import re

from logger import logger

# The same shape `frontend/app/utils/chatBlocks.ts` looks for when it decides
# whether to render a PayCard.
PAY_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^\s)]+)\)")

# Said in place of a link the agent invented. Silence would be worse: the
# sentences around it usually still say "here's your link", and a buyer left
# looking for one that is not there will assume the app is broken rather than
# that nothing was ever created.
STRIPPED_NOTICE = "(No payment link was created — ask me to generate one and I'll sort it out.)"


def issued_payment_urls(user_id: str | None, item_id: str | None) -> set[str]:
    """Every checkout URL this server has actually issued to this buyer.

    Scoped to the pair when an item is in context, and widened to the buyer's
    other live links otherwise — the agent can legitimately hand back a link
    created in an earlier turn whose item context has since been dropped.

    Returns an empty set on any failure: a cache hiccup must strip links, not
    trust them.
    """
    urls: set[str] = set()
    if not user_id:
        return urls

    try:
        from payment.payment_state import get_active_payments_for_user, get_pending_payment

        if item_id:
            pending = get_pending_payment(user_id, item_id)
            if pending and pending.get("payment_url"):
                urls.add(str(pending["payment_url"]))

        for entry in get_active_payments_for_user(user_id) or []:
            url = entry.get("payment_url") if isinstance(entry, dict) else entry
            if url:
                urls.add(str(url))
    except Exception as e:  # noqa: BLE001 — fail closed
        logger.warning(f"⚠️ Could not resolve issued payment links, stripping all: {e}")
        return set()

    return urls


def sanitize_payment_links(text: str, user_id: str | None, item_id: str | None) -> str:
    """Remove every markdown link whose URL this server did not issue."""
    if not text or "](" not in text:
        return text

    allowed = issued_payment_urls(user_id, item_id)

    def replace(match: re.Match) -> str:
        url = match.group(2)
        if url in allowed:
            return match.group(0)
        logger.warning(f"🚫 Stripped a payment link the server never issued: {url}")
        return STRIPPED_NOTICE

    return PAY_LINK_RE.sub(replace, text)


def split_safe_prefix(buffer: str) -> tuple[str, str]:
    """Split streamed text into (safe to emit now, hold back).

    A link cannot be validated until its URL is complete, and text cannot be
    unsent — so everything from an unclosed `[` onwards is held. Mirrors what
    `chatBlocks.ts` already does client-side for a half-written link, except
    here it is what stops a fabricated URL being shown at all.
    """
    opened = buffer.rfind("[")
    if opened == -1:
        return buffer, ""
    if ")" in buffer[opened:]:
        # Closed — `sanitize_payment_links` can judge it.
        return buffer, ""
    return buffer[:opened], buffer[opened:]
