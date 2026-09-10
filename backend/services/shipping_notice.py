"""What the buyer is told when their order ships (SPEC-057).

The same event reaches them three ways: an email, a chat bubble that arrives
live, and whatever the agent says the next time they ask. Letting each of those
compose its own sentence is three chances to disagree about what actually
shipped — and the buyer, holding all three, is exactly who notices. So the facts
are assembled once, here, and everything downstream renders the same dict.
"""

from domains.catalog.shipping import resolve_tracking_url


def shipment_summary(order: dict) -> dict:
    """The shipment facts, with the tracking URL filled in if it can be.

    `tracking_url` is stored on the order, but only because the seller may have
    typed one by hand. When it is absent and the carrier is a known one, the
    link is computable — so callers never have to decide whether to derive it.
    """
    courier = order.get("courier")
    tracking_number = order.get("tracking_number")

    return {
        "item_name": order.get("item_name") or "your order",
        "order_id": order.get("id") or order.get("order_id"),
        "courier": courier,
        "tracking_number": tracking_number,
        "tracking_url": order.get("tracking_url") or resolve_tracking_url(courier, tracking_number),
    }


def shipment_chat_message(order: dict, delivered: bool = False) -> str:
    """The message posted into the buyer's chat, in the seller's voice.

    Written as plain text with a bare URL, never markdown. `chatBlocks.ts` lifts
    `[label](https://…)` out of an assistant message and renders it as a payment
    card — a tracking link arriving under a "Secured by Stripe" badge would be
    our own doing rather than an attacker's (SPEC-056 #4).

    Line breaks are single, not blank: SPEC-027 makes a blank line a bubble
    boundary in assistant messages, and these lines belong together.
    """
    facts = shipment_summary(order)
    item = facts["item_name"]

    if delivered:
        lines = [f"Your {item} has been marked as delivered 🎉"]
        if facts["tracking_number"]:
            lines.append(f"Tracking: {facts['tracking_number']}")
        lines.append("Hope everything's in good shape — shout if anything's off!")
        return "\n".join(lines)

    lines = [f"Good news — your {item} is on its way! 📦"]
    if facts["courier"] and facts["tracking_number"]:
        lines.append(f"{facts['courier']} · {facts['tracking_number']}")
    elif facts["courier"]:
        lines.append(f"Shipped with {facts['courier']}")
    elif facts["tracking_number"]:
        lines.append(f"Tracking: {facts['tracking_number']}")

    if facts["tracking_url"]:
        lines.append(f"Track it here: {facts['tracking_url']}")

    return "\n".join(lines)
