"""What the agent knows about an item, and when it still needs to look (SPEC-059).

`_build_messages` used to attach the item's photos to every single turn. Gemini
bills each image at roughly 258 tokens plus vision prefill, so a twenty-turn
haggle over one item paid for forty image ingests — all of them showing the model
something it had already seen on turn one.

The waste is total rather than partial, because `items.description` was written
*from those same photos* by `image_analyzer.analyze()` when the listing was
created. The model was being handed a picture and a description of the picture,
every turn, forever. Sending the description alone loses nothing on the ordinary
turn and costs a couple of dozen tokens instead of several hundred.

The photos are not gone; they are conditional. A buyer asking "any scratches on
the back?" is asking something the listing copy may genuinely not cover, and that
turn gets the images. So does any turn where the buyer uploaded a photo of their
own — cost control must never silently drop something the buyer chose to send.
"""

import re

# Long enough for a real listing description, short enough that a seller who
# pasted an essay cannot undo the saving this module exists to make.
MAX_DESCRIPTION_CHARS = 600


def item_knowledge_card(item: dict | None) -> str:
    """A compact text block describing the item under negotiation.

    Fields that are missing are left out entirely rather than rendered as
    "None" — a model handed `Condition: None` will cheerfully read it back to
    the buyer.
    """
    if not item:
        return ""

    lines = []
    if item.get("name"):
        lines.append(f'Item Name: "{item["name"]}"')
    if item.get("price") is not None:
        lines.append(f"Listed Price: RM{item['price']}")
    if item.get("condition"):
        lines.append(f"Condition: {item['condition']}")

    description = (item.get("description") or "").strip()
    if description:
        if len(description) > MAX_DESCRIPTION_CHARS:
            description = description[:MAX_DESCRIPTION_CHARS].rstrip() + "…"
        lines.append(f"Listing Description: {description}")

    return "\n".join(lines)


# Words that mean "look at the photo" — things the listing copy plausibly does
# not cover, where paying for vision is the right call. Malay and Chinese are
# here because the store is trilingual and a Malay buyer asking about scratches
# deserves the same answer as an English one.
#
# Kept as stems matched on word boundaries: "scratch" must fire on "scratches"
# but "sched" must not fire on "reschedule".
#
# Deliberately absent: bare "see" and "show". They are the two most common verbs
# in a buying conversation ("show me the link", "see you later"), so including
# them fired on a large share of ordinary turns and gave back the entire saving.
# The sentences that actually want them — "show me the picture", "can I see a
# photo" — are already caught by their object.
#
# The list errs generous otherwise: a false positive costs one turn's worth of
# image tokens, while a false negative has the agent claim it cannot see
# something it could have looked at.
_VISION_STEMS = (
    # English
    r"scratch\w*", r"scuff\w*", r"dent\w*", r"crack\w*", r"chip(?:ped|s)?",
    r"colou?rs?", r"photos?", r"pictures?", r"images?", r"pics?",
    r"looks?", r"looking", r"appear\w*", r"condition", r"damage\w*",
    r"worn", r"wear", r"stain\w*", r"rust\w*", r"faded?", r"marks?",
    # Malay
    r"calar\w*", r"warna", r"gambar", r"rosak", r"kesan", r"lecet\w*",
    r"tengok", r"lihat", r"nampak",
)
_VISION_PATTERN = re.compile(r"\b(?:" + "|".join(_VISION_STEMS) + r")\b", re.IGNORECASE)

# CJK has no word boundaries, so these are matched as plain substrings.
_VISION_SUBSTRINGS = (
    "刮痕", "刮花", "划痕", "照片", "图片", "圖片", "颜色", "顏色",
    "外观", "外觀", "磨损", "磨損", "损坏", "損壞", "看看", "看一下", "成色",
)


def turn_needs_vision(message: str, files=None, has_description: bool = True) -> bool:
    """Whether this turn should carry the item's photos.

    Three reasons to say yes, in order of how obvious they are:

    1. The buyer uploaded something. Always send it — dropping a photo the buyer
       chose to attach would be a bug wearing an optimisation's clothes.
    2. The listing has no description. Name, price and condition say nothing
       about what the thing LOOKS like, so with no description the photos are
       the only visual information there is and the old behaviour is correct.
    3. The buyer asked a visual question, which is exactly the case a written
       description is most likely not to cover.

    Note the hinge is the description specifically, not "is the card non-empty".
    A card built from name and price alone is not a substitute for a photo.
    """
    if files:
        return True
    if not has_description:
        return True

    text = message or ""
    if _VISION_PATTERN.search(text):
        return True
    return any(token in text for token in _VISION_SUBSTRINGS)
