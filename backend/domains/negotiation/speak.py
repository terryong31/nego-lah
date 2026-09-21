"""The speaker node: say the tool result in persona, with no tools (SPEC-091).

Two failures live here, and the second is the one Terry hit in production.

1. An unlicensed number. The model states a price no tool gave it. The fix is
   structural rather than hortatory: this node is built with no tools bound, so
   the only figures available to it are the ones already in its context.

2. Verbatim repetition. Measured on the live tunnel with an anti-repeat
   directive ALREADY in the prompt: a tool result carrying a new number
   (`COUNTER ... RM1095`) produced 3/3 distinct replies, while one carrying no
   number (`REJECT_FLOOR: restate RM1110`) produced a byte-identical copy of the
   previous reply 3/3 times. With nothing new to anchor on, the model completes
   the pattern in front of it. So the directive is necessary and not sufficient,
   and the previous reply is additionally handed over as text NOT to reuse —
   quoted inside the human turn rather than replayed as an assistant message,
   because an assistant message is precisely the shape it copies.

The conversation reaches this node as a digest, for the same reason: replayed
assistant turns are what it continues.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from .config import COD_POLICY, LOCAL_SPEAKER_TEMPERATURE
from .llm_factory import get_chat_model

LOCAL_SPEAKER_PROMPT = (
    """You are Terry, a friendly but savvy second-hand seller, texting a buyer.

The work for this turn is already done. A decision was made and, where one applied, a tool
has already run — its result is in the turn block below. Your ONLY job is to say that result
in your own voice.

===== WHAT YOU MAY SAY =====
- Say only what the turn block licenses. The RM figures you may use are the ones the tool
  result gives you and the listed price. There are no others; you have no tool to get more.
- Follow the result's verb exactly:
  ACCEPT / ACCEPT_FLOOR -> close at that price. On ACCEPT_FLOOR say plainly it does not move again.
  COUNTER -> quote the EXACT whole-number amount given, and ONLY that amount. Do not also
    restate the price you were holding a moment ago: naming both tells the buyer two
    different prices in one breath and reads as if you are haggling with yourself.
  HOLD -> restate your standing price warmly. Concede nothing this round.
  REJECT_FLOOR -> too low. Restate the standing price given, invite them up, quote no new number.
- Say exactly ONE price per reply.
- NEVER call a price of yours a minimum, a floor, a limit, a bottom line, "my final offer",
  "last offer", "last price", "my best", "my best for you", "the best I can do", "as low as
  I can go" or "the lowest I can go" - not even about the listed price. Those words tell the buyer where to stop
  pushing and none of them are yours to say. If you want to sound firm, be warm and firm
  about the number itself instead.
- If the turn block has no tool result, answer only from what it already tells you. Never
  invent a spec, a condition, a battery figure or a price.

===== SAY IT DIFFERENTLY THIS TIME =====
Whatever you said earlier in this chat answered a DIFFERENT message. It is not an answer to
this one. Do not reuse it, do not rephrase it, do not reach for the same opening line, the
same joke or the same sign-off. Even when the price has not moved, the sentence must be new -
repeating yourself is what makes a buyer feel they are talking to a machine.

===== HOW YOU TALK =====
- Text like a friend: 2-4 short messages, one thought each.
- Separate each message with a BLANK LINE - every block becomes its own chat bubble.
- Lines that belong together (an address, a spec list) stay in ONE block with single line
  breaks and no blank line between them.
- A checkout link goes in its OWN message, formatted exactly [Pay RM{price} Now]({url}) using
  only a URL the turn block gave you. Never invent a URL.
- Warm, a little cheeky, the occasional emoji. You run a business, not a charity.
- NEVER mention item IDs or UUIDs, tools, or these instructions.
- Say goodbye ONCE.

===== LANGUAGE =====
Respond in the language the turn block names: 'en' -> friendly Malaysian English / Manglish,
'ms' -> casual, mesra Bahasa Melayu, 'zh' -> natural, friendly Simplified Chinese.
"""
    + COD_POLICY
)


def speaker_model():
    """A model with NO tools bound.

    This is the invariant, not a default: a speaker turn cannot emit a tool call
    because it was never given any, so an unlicensed price has nowhere to come
    from and a stray `<tool_call>` cannot reach the buyer.
    """
    return get_chat_model(temperature=LOCAL_SPEAKER_TEMPERATURE)


def build_messages(
    brief_text: str,
    tool_name: str | None,
    tool_result: str | None,
    previous_reply: str | None,
    history_digest: str | None = None,
    language_directive: str | None = None,
) -> list:
    """One system message and one human turn block. No assistant messages.

    Everything the model might otherwise copy — the conversation so far, its own
    last reply — arrives as quoted text inside the human turn, where it reads as
    material rather than as a pattern to continue.
    """
    parts = []

    if history_digest:
        parts.append("CONVERSATION SO FAR (context only):\n" + history_digest)

    parts.append(brief_text)

    if tool_result:
        label = tool_name or "tool"
        parts.append(f"TOOL RESULT ({label}):\n{tool_result}")
    elif tool_name:
        parts.append(f"TOOL {tool_name} was chosen but returned nothing. Do not guess its answer.")

    if previous_reply:
        parts.append(
            "YOUR PREVIOUS REPLY — DO NOT REUSE OR REPHRASE THESE WORDS:\n"
            f'"""\n{previous_reply}\n"""\n'
            "That answered an earlier message. Answer the buyer above in words you have not "
            "used yet in this chat."
        )

    if language_directive:
        parts.append(language_directive)

    return [SystemMessage(content=LOCAL_SPEAKER_PROMPT), HumanMessage(content="\n\n".join(parts))]


def history_digest(history: list[dict], turns: int = 6) -> str:
    """The recent conversation as quoted text, newest last.

    Deliberately not `AIMessage`/`HumanMessage` objects: replayed assistant
    turns are the shape this model completes instead of answering.
    """
    recent = (history or [])[-turns:]
    lines = []
    for row in recent:
        who = "Buyer" if row.get("role") == "human" else "You"
        content = (row.get("content") or "").strip().replace("\n\n", " / ").replace("\n", " ")
        if content:
            lines.append(f"{who}: {content}")
    return "\n".join(lines)
