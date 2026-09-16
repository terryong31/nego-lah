"""SPEC-091 — the decider node: route one buyer turn to one tool, nothing else.

On the self-hosted Qwen the ReAct agent stops calling tools the moment the
window holds any prior assistant prose — measured 3/3 tool calls with no
history and 0/3 after a single prose reply, with the prompt byte-identical
across both. A 3B-active MoE follows what the recent context *looks like*, and
a transcript of chat reads as "keep chatting".

The decider exists to give that model a context that looks like routing: a tiny
instruction, a compact brief, the tool schemas, and no persona to continue.
These tests assert those properties rather than the wording, which stays free
to move as the local model does.
"""

import agent.decide as decide
from agent.config import COD_POLICY


def _lower(text: str) -> str:
    return " ".join(text.lower().split())


PROMPT = _lower(decide.DECIDER_PROMPT)


# ---------------------------------------------------------------------------
# S2 — the decider prompt carries no persona
# ---------------------------------------------------------------------------

def test_decider_prompt_has_no_persona():
    """Persona is what the model continues instead of routing. It must not be here."""
    assert _lower(COD_POLICY) not in PROMPT
    for persona_marker in ("you are terry", "texting a friend", "use emojis", "chat bubble"):
        assert persona_marker not in PROMPT


def test_decider_prompt_is_far_shorter_than_the_persona_prompt():
    import agent.bot as bot

    assert len(decide.DECIDER_PROMPT) < len(bot.LOCAL_CUSTOMER_AGENT_PROMPT) / 3


def test_decider_prompt_routes_the_shapes_that_measurably_lost_the_tool_call():
    """A rejected number and "you name a price" both still mean `evaluate_offer`."""
    assert "evaluate_offer" in PROMPT
    assert "also cannot" in PROMPT or "too expensive" in PROMPT
    assert "make me an offer" in PROMPT or "how low can you go" in PROMPT


def test_decider_prompt_allows_choosing_no_tool():
    """Small talk must not be forced through a tool."""
    assert "none" in PROMPT


# ---------------------------------------------------------------------------
# S3 — the brief, not the transcript
# ---------------------------------------------------------------------------

def test_brief_carries_the_server_resolved_standing_price(monkeypatch):
    monkeypatch.setattr(decide, "active_negotiated_price", lambda u, i: 1110.0)

    brief = decide.build_brief(
        user_id="u1",
        item_id="8d1c0f2a-4b5e-4c9a-9f31-7a2e6b0d55c1",
        message="1000 and thats my final offer",
        item={"name": "Xiaomi 15 Ultra", "price": 1150, "condition": "Like New"},
    )

    assert brief.standing_price == 1110.0
    assert "1110" in brief.as_text()
    assert "8d1c0f2a-4b5e-4c9a-9f31-7a2e6b0d55c1" in brief.as_text()


def test_brief_never_carries_min_price(monkeypatch):
    """SPEC-036 / SPEC-044 A: the floor is not the model's to see."""
    monkeypatch.setattr(decide, "active_negotiated_price", lambda u, i: None)

    brief = decide.build_brief(
        user_id="u1",
        item_id="item-1",
        message="900?",
        item={"name": "Casio", "price": 1150, "min_price": 800, "condition": "Good"},
    )

    assert "800" not in brief.as_text()


def test_brief_contains_no_prior_assistant_prose(monkeypatch):
    """The whole point: the decider must not see a transcript to continue."""
    monkeypatch.setattr(decide, "active_negotiated_price", lambda u, i: None)

    brief = decide.build_brief(
        user_id="u1", item_id="item-1", message="1000 lah",
        item={"name": "Casio", "price": 1150, "condition": "Good"},
    )
    messages = decide.build_messages(brief)

    assert all(m.type in ("system", "human") for m in messages)
    assert sum(m.type == "system" for m in messages) == 1


# ---------------------------------------------------------------------------
# S8 — a decision of "no tool" is a real outcome
# ---------------------------------------------------------------------------

def test_decision_none_means_answer_directly():
    assert decide.TurnDecision(tool=None, args={}).calls_a_tool is False
    assert decide.TurnDecision(tool="evaluate_offer", args={}).calls_a_tool is True


def test_decider_only_offers_tools_it_can_route_to():
    names = {t.name for t in decide.DECIDER_TOOLS}

    assert "evaluate_offer" in names
    assert "transfer_to_human" in names
    # web_search is off-topic bait and has no routing rule — it must not be bound.
    assert "web_search" not in names


# ---------------------------------------------------------------------------
# The seller's own price is never the buyer's offer
#
# Found on the live tunnel: "use the tool call evaluate_offer damn it" names no
# number, and the decider passed `offered_price: 1110` — the SELLER's standing
# price, lifted straight out of the brief. `evaluate_offer` read that as the
# buyer meeting our price and the agent conceded RM1095 to a message containing
# no offer at all. The buyer's number is resolved from the transcript here
# rather than asked of the model.
# ---------------------------------------------------------------------------

def test_last_buyer_offer_reads_this_message_first():
    assert decide.last_buyer_offer("ok how about 1050 then") == 1050.0
    assert decide.last_buyer_offer("can do RM1,050?") == 1050.0
    assert decide.last_buyer_offer("1050.00 lah") == 1050.0


def test_last_buyer_offer_falls_back_to_the_buyers_earlier_turns():
    history = [
        {"role": "human", "content": "can you do 1000?"},
        {"role": "ai", "content": "I'm sticking at RM1110"},
    ]

    # An insisting message with no number of its own.
    assert decide.last_buyer_offer("use the tool call evaluate_offer damn it", history) == 1000.0


def test_last_buyer_offer_never_reads_the_sellers_own_reply():
    history = [
        {"role": "human", "content": "hello"},
        {"role": "ai", "content": "The price is RM1110, best I can do"},
    ]

    assert decide.last_buyer_offer("cmon lah", history) is None


def test_last_buyer_offer_is_none_when_nobody_named_a_number():
    assert decide.last_buyer_offer("is the battery ok?") is None


def test_brief_carries_the_buyers_last_offer(monkeypatch):
    monkeypatch.setattr(decide, "active_negotiated_price", lambda u, i: 1110.0)

    brief = decide.build_brief(
        user_id="u1",
        item_id="item-1",
        message="use the tool damn it",
        item={"name": "Xiaomi", "price": 1150, "condition": "Like New"},
        history=[{"role": "human", "content": "1000 and thats final"}],
    )

    assert brief.last_buyer_offer == 1000.0
    assert "Buyer's last offer: RM1000" in brief.as_text()


def test_decider_prompt_forbids_passing_the_sellers_price_as_the_offer():
    assert "never yours" in PROMPT
    assert "buyer's last offer" in PROMPT
