"""SPEC-091 — the speaker node: say the tool result in persona, with no tools.

Two failures live here. The model may state a number no tool gave it, and — the
one Terry hit in production — it copies its own previous reply word for word
when the tool result carries no new figure. Measured on the live tunnel: a
result with a new number (`COUNTER ... RM1095`) produced 3/3 distinct replies; a
result with none (`REJECT_FLOOR: restate RM1110`) produced a byte-identical copy
of the previous reply 3/3 times, with an anti-repeat directive already in the
prompt. So the directive is necessary and not sufficient — the previous reply is
also handed over explicitly as text not to reuse.
"""

import domains.negotiation.speak as speak
from domains.negotiation.config import COD_POLICY


def _lower(text: str) -> str:
    return " ".join(text.lower().split())


PROMPT = _lower(speak.LOCAL_SPEAKER_PROMPT)


# ---------------------------------------------------------------------------
# S4 — a speaker turn cannot call a tool by construction
# ---------------------------------------------------------------------------


def test_speaker_model_is_built_with_no_tools(monkeypatch):
    built = {}

    class _Model:
        def bind_tools(self, tools):  # pragma: no cover - must never run
            built["bound"] = tools
            return self

    monkeypatch.setattr(speak, "get_chat_model", lambda **kw: _Model())

    speak.speaker_model()

    assert "bound" not in built


def test_speaker_prompt_lists_no_tools():
    for tool_name in ("evaluate_offer", "create_checkout_link", "search_items"):
        assert tool_name not in PROMPT


# ---------------------------------------------------------------------------
# S5 — what the speaker is allowed to say
# ---------------------------------------------------------------------------


def test_speaker_prompt_bans_floor_vocabulary():
    assert "lowest i can go" in PROMPT
    assert "minimum" in PROMPT or "floor" in PROMPT


def test_speaker_prompt_forbids_reusing_earlier_replies():
    assert "reuse" in PROMPT or "rephrase" in PROMPT


def test_speaker_prompt_keeps_the_invariants():
    assert _lower(COD_POLICY) in PROMPT or "cod" in PROMPT
    assert "id" in PROMPT  # never mention item IDs


def test_speaker_prompt_forbids_unlicensed_numbers():
    assert "tool" in PROMPT and ("exact" in PROMPT or "only" in PROMPT)


# ---------------------------------------------------------------------------
# S5 (cont.) — the previous reply is handed over as text not to reuse
# ---------------------------------------------------------------------------


def test_previous_reply_is_included_as_a_do_not_reuse_block():
    previous = "RM1000 is still quite a bit lower than what I'm asking, bro!"

    messages = speak.build_messages(
        brief_text="ITEM: Casio | listed RM1150\n\nBuyer: 1000 final",
        tool_name="evaluate_offer",
        tool_result="REJECT_FLOOR: ... Your standing price is still RM1110. ...",
        previous_reply=previous,
    )

    body = "\n".join(str(m.content) for m in messages)
    assert previous in body
    assert "do not reuse" in body.lower() or "not reuse" in body.lower()


def test_previous_reply_is_never_replayed_as_an_assistant_turn():
    """Replaying it as assistant prose is exactly what the model copies."""
    messages = speak.build_messages(
        brief_text="Buyer: 1000 final",
        tool_name="evaluate_offer",
        tool_result="REJECT_FLOOR: hold at RM1110.",
        previous_reply="RM1000 is too low bro",
    )

    assert all(m.type in ("system", "human") for m in messages)


def test_no_previous_reply_omits_the_block_entirely():
    messages = speak.build_messages(
        brief_text="Buyer: hi",
        tool_name=None,
        tool_result=None,
        previous_reply=None,
    )

    # The prompt's standing directive stays; it's the quoted block that must be absent.
    turn_block = str(messages[-1].content).lower()
    assert "do not reuse or rephrase these words" not in turn_block


def test_tool_result_is_carried_verbatim():
    result = "COUNTER: Offer of RM1050 is below your price of RM1110. Counter with RM1095"

    messages = speak.build_messages(
        brief_text="Buyer: 1050?",
        tool_name="evaluate_offer",
        tool_result=result,
        previous_reply=None,
    )

    assert result in "\n".join(str(m.content) for m in messages)


def test_speaker_runs_warmer_than_the_decider():
    from domains.negotiation.config import LOCAL_AGENT_TEMPERATURE, LOCAL_SPEAKER_TEMPERATURE

    assert LOCAL_SPEAKER_TEMPERATURE > LOCAL_AGENT_TEMPERATURE


# ---------------------------------------------------------------------------
# One price per reply
#
# Found on the live tunnel: given `COUNTER ... Counter with RM1095`, the speaker
# said "I'm holding at RM1110 / Come up with RM1095" — two prices in one reply,
# one of them an instruction to come UP to a number below the other. And asked
# to sound firm it reached for "that's my best for you", which is the floor
# vocabulary SPEC-044 A bans, just worded around the blocklist.
# ---------------------------------------------------------------------------


def test_counter_says_only_the_counter_amount():
    assert "only that amount" in PROMPT
    assert "exactly one price per reply" in PROMPT


def test_banned_floor_vocabulary_covers_the_best_i_can_do_family():
    for phrase in ("my best", "the best i can do", "my final offer", "last offer", "last price"):
        assert phrase in PROMPT
