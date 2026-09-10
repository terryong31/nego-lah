"""The item knowledge card, and when a turn still needs the photos (SPEC-059).

`_build_messages` used to attach the item's images on EVERY turn an item_id was
in context — turn 1 and, identically, turn 20. Gemini bills each image at
roughly 258 tokens plus vision prefill, so a twenty-turn haggle paid for forty
image ingests to learn nothing it did not know after the first.

What makes it pure waste rather than a trade-off is that `items.description` was
itself written from those same photos by `image_analyzer.analyze()` at listing
time. The model was being shown a picture and a description of the picture, over
and over. So the ordinary turn now carries the description; the photos come back
only when the buyer asks something the words cannot answer.
"""

import pytest

from agent.knowledge import (
    MAX_DESCRIPTION_CHARS,
    item_knowledge_card,
    turn_needs_vision,
)

ITEM = {
    "name": "Casio VX-4 Pocket Computer",
    "price": 180,
    "condition": "Good",
    "description": "Working 1980s pocket computer. Minor shelf wear on the case.",
}


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------

def test_the_card_carries_what_a_negotiation_actually_needs():
    card = item_knowledge_card(ITEM)
    assert "Casio VX-4 Pocket Computer" in card
    assert "180" in card
    assert "Good" in card
    assert "Minor shelf wear" in card


def test_absent_fields_are_omitted_rather_than_rendered_as_none():
    """A model handed "Condition: None" will read it out to the buyer."""
    card = item_knowledge_card({"name": "Mystery Box", "price": 20})
    assert "Mystery Box" in card
    assert "None" not in card
    assert "condition" not in card.lower()


def test_a_card_for_nothing_is_empty():
    assert item_knowledge_card({}) == ""
    assert item_knowledge_card(None) == ""


def test_a_long_description_is_trimmed():
    """The point of the card is that it is cheaper than the photos. A listing
    with a 4,000-character essay would undo that."""
    card = item_knowledge_card({**ITEM, "description": "x" * 5000})
    assert len(card) < MAX_DESCRIPTION_CHARS + 400
    assert "…" in card or "..." in card


def test_the_price_is_rendered_as_ringgit():
    assert "RM" in item_knowledge_card(ITEM)


# ---------------------------------------------------------------------------
# When vision is still worth paying for
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "can you do RM80?",
    "is this still available?",
    "ok deal, send me the link",
    "how much for two?",
    "",
])
def test_an_ordinary_turn_does_not_need_the_photos(message):
    assert turn_needs_vision(message, files=None, has_description=True) is False


@pytest.mark.parametrize("message", [
    "any scratches on the back?",
    "what colour is it exactly?",
    "can you send a photo of the screen?",
    "does it look worn?",
    "is there a dent anywhere?",
    "show me the picture again",
    "how bad is the damage",
])
def test_a_visual_question_brings_the_photos_back(message):
    assert turn_needs_vision(message, files=None, has_description=True) is True


@pytest.mark.parametrize("message", [
    "ada calar tak?",          # any scratches?
    "warna apa ni?",           # what colour is this?
    "boleh tengok gambar?",    # can I see the picture?
    "有刮痕吗?",                # any scratches?
    "可以看照片吗?",             # can I see photos?
])
def test_visual_questions_work_in_the_other_two_languages(message):
    """The store is trilingual; a Malay buyer asking about scratches must get
    the same answer as an English one."""
    assert turn_needs_vision(message, files=None, has_description=True) is True


def test_a_buyer_upload_is_always_sent_whatever_the_text_says():
    """Cost control must never silently drop a photo the buyer chose to send."""
    files = [{"name": "mine.jpg", "type": "image/jpeg", "data": "..."}]
    assert turn_needs_vision("can you do RM80?", files=files, has_description=True) is True


def test_without_a_description_the_photos_are_the_only_visual_information():
    """Name, price and condition do not say what a thing looks like, so a
    listing with no description falls back to what it always did."""
    assert turn_needs_vision("can you do RM80?", files=None, has_description=False) is True


def test_the_match_is_on_words_not_substrings():
    """"scratch" inside another word must not trigger a vision turn."""
    assert turn_needs_vision("from scratch I built one", files=None, has_description=True) is True
    # ...but an unrelated word that merely contains a trigger must not.
    assert turn_needs_vision("I need to reschedule", files=None, has_description=True) is False
    assert turn_needs_vision("my budget is limited", files=None, has_description=True) is False


@pytest.mark.parametrize("message", [
    "show me the link",
    "see you later",
    "can you show me the checkout",
    "I'll see if my friend wants it too",
])
def test_the_commonest_verbs_in_a_sale_do_not_trigger_vision(message):
    """"see" and "show" are how people talk about links, times and each other.
    Firing on them would put the photos back on most turns and give back the
    entire saving — the sentences that really want a photo name one."""
    assert turn_needs_vision(message, files=None, has_description=True) is False


def test_naming_the_photo_still_triggers_even_with_those_verbs():
    assert turn_needs_vision("show me the picture", files=None, has_description=True) is True
    assert turn_needs_vision("can I see a photo?", files=None, has_description=True) is True
