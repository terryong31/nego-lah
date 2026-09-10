"""Courier names and tracking URLs (SPEC-057).

A tracking number on its own is a worse version of a link — the buyer has to
copy it, guess which carrier's website to paste it into, and get the form right.
This module turns "J&T, 630123456789" into something clickable.

It is a lookup table on purpose. No carrier APIs, no keys, no polling: for a
single seller posting a few parcels a week the seller IS the source of truth,
and a table that occasionally needs a new row is a far smaller liability than a
set of integrations that can rate-limit, expire or change shape.

The table is also allowed to miss. An unknown carrier is still worth recording,
so `resolve_tracking_url` returns None rather than raising, and the rest of the
system simply offers no link for that order.
"""

from urllib.parse import quote

# Canonical name -> tracking URL template, plus the spellings a seller in a hurry
# actually types. Ordered roughly by how often this store uses them.
_REGISTRY: dict[str, tuple[str, tuple[str, ...]]] = {
    "J&T Express": (
        "https://www.jtexpress.my/tracking?billcode={tracking}",
        ("jt", "j&t", "jt express", "j and t", "jnt", "j&t express"),
    ),
    "Pos Laju": (
        "https://track.pos.com.my/postal-services/quick-access/?track-trace={tracking}",
        ("pos", "poslaju", "pos malaysia", "pos laju"),
    ),
    "Ninja Van": (
        "https://www.ninjavan.co/en-my/tracking?id={tracking}",
        ("ninja", "ninjavan", "ninja van"),
    ),
    "City-Link Express": (
        "https://www.citylinkexpress.com/tracking-results/?track={tracking}",
        ("citylink", "city link", "city-link", "city-link express"),
    ),
    "DHL eCommerce": (
        "https://ecommerceportal.dhl.com/track/?ref={tracking}",
        ("dhl", "dhl ecommerce", "dhl express"),
    ),
    "Flash Express": (
        "https://www.flashexpress.my/tracking/?se={tracking}",
        ("flash", "flash express"),
    ),
    "GDEX": (
        "https://web.gdexpress.com/official/etracking2.php?capture={tracking}",
        ("gdex", "gd express", "gdexpress"),
    ),
    "Shopee Express": (
        "https://spx.com.my/track?{tracking}",
        ("spx", "shopee", "shopee express"),
    ),
}

# What the console offers in its dropdown. The seller can still type anything.
COURIER_CHOICES: tuple[str, ...] = tuple(_REGISTRY)

# Every alias, plus each canonical name lowercased, resolving to the canonical name.
_ALIASES: dict[str, str] = {
    alias: canonical
    for canonical, (_template, aliases) in _REGISTRY.items()
    for alias in (*aliases, canonical.lower())
}


def normalise_courier(courier: str | None) -> str | None:
    """Map whatever the seller typed onto a canonical carrier name.

    Unrecognised input is returned tidied but otherwise intact — the point is to
    recognise the common carriers, not to refuse the uncommon ones.
    """
    if not courier:
        return None
    cleaned = " ".join(courier.split())
    if not cleaned:
        return None
    return _ALIASES.get(cleaned.lower(), cleaned)


def resolve_tracking_url(courier: str | None, tracking_number: str | None) -> str | None:
    """Build the carrier's tracking URL, or None if we cannot.

    A missing number, a blank one, or a carrier not in the table all mean the
    same thing here: this order has no link to offer.
    """
    if not tracking_number or not tracking_number.strip():
        return None

    canonical = normalise_courier(courier)
    entry = _REGISTRY.get(canonical) if canonical else None
    if not entry:
        return None

    template, _aliases = entry
    # `safe=""` so a slash inside a tracking code becomes %2F rather than a path
    # segment pointing somewhere else on the carrier's site.
    return template.format(tracking=quote(tracking_number.strip(), safe=""))
