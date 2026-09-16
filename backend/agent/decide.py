"""The decider node: route one buyer turn to one tool (SPEC-091).

On the self-hosted Qwen the ReAct agent stops emitting tool calls as soon as the
window holds any prior assistant prose. Measured against the live tunnel with
the SPEC-081 local prompt and the real tool schemas, same item, same offer:
3/3 tool calls with no history, 0/3 after a single prose reply, 0/3 with a
brand-new number, 0/3 with SPEC-087's tool traces replayed. The prompt is
byte-identical across every row, so this is neither prompt length nor the
quotable-script problem SPEC-081 closed. A 3B-active MoE follows what the recent
context *looks like*, and a window of chat prose reads as "keep chatting".

So this node is given a context that looks like routing and nothing else: a
short instruction, a compact brief, the tool schemas, and no persona to
continue. It chooses; it never computes a price and never talks to the buyer.

Measured on 8 turn types (6 needing a named tool, 2 needing none): the ReAct
agent with a trailing reminder scored 3/7 at 6.5s a turn, this node 7/8 at 3.0s.
"""

import re
from dataclasses import dataclass, field

from langchain_core.messages import HumanMessage, SystemMessage

from logger import logger
from payment.pricing import active_negotiated_price

from .config import LOCAL_AGENT_TEMPERATURE
from .llm_factory import get_chat_model

# The routing table, and deliberately nothing else. Every line here earns its
# place by naming a turn shape; a sentence of personality would give the model
# something to continue instead of something to route.
#
# The two shapes called out explicitly are the ones that measurably lost the
# tool call even after SPEC-081: a number the buyer is *rejecting* ("1050 also
# cannot"), and a request that the seller go first ("make me an offer").
DECIDER_PROMPT = """You route ONE buyer message to ONE tool. You never talk to the buyer.

Emit exactly one tool call, or the single word NONE when no tool applies.
Never write prose, never explain, never greet.

ROUTING TABLE
- The buyer names, counters, rejects or asks YOU for a price -> `evaluate_offer` with that
  number. This includes "1050 also cannot", "800 is too expensive", "cannot afford 900",
  "what's your best", "how low can you go", "make me an offer", "last price?".
  A repeat of a number you already evaluated is still a fresh `evaluate_offer`.
- Gives a REASON for needing a discount (student, lost job, hardship) ->
  `assess_discount_eligibility`.
- Asks what is for sale, or names an item you have no id for -> `search_items`.
- Asks to see everything in stock -> `list_all_items`.
- Asks for specs or condition you do not have in the brief -> `get_item_info`.
- Explicitly confirms an agreed price ("yes", "confirm", "deal", "ok go") ->
  `create_checkout_link`.
- Changed their mind after a link was made -> `cancel_payment_link`.
- Gives a name, phone and address -> `collect_shipping_info`.
- Asks about a past order, delivery or tracking -> `check_user_orders`.
- Wants a human, COD, cash, a meet-up or self-collect -> `transfer_to_human`.
- Small talk, thanks, or a question the brief already answers -> NONE.

Use the Context Item ID from the brief. Never invent an id.

`offered_price` IS THE BUYER'S NUMBER, NEVER YOURS.
- Take it from THIS message when it names one.
- When the buyer insists, repeats or demands without naming a new number ("cmon lah",
  "do it again", "use the tool"), pass the brief's `Buyer's last offer` unchanged.
- The prices the brief calls "Listed price" and "Lowest price already quoted" are YOURS.
  Passing one of them as `offered_price` tells the tool the buyer offered your own price
  and hands them a concession they never asked for. Never do it.
- If the brief has no `Buyer's last offer` and this message names no number, the answer
  is NONE, not a guess.
Always pass `current_price` = the brief's `Lowest price already quoted`, or 0 if it has none."""


@dataclass(frozen=True)
class TurnDecision:
    """Which tool this turn routes to, if any."""

    tool: str | None
    args: dict = field(default_factory=dict)

    @property
    def calls_a_tool(self) -> bool:
        return self.tool is not None


@dataclass(frozen=True)
class TurnBrief:
    """Everything the decider is allowed to know about this turn.

    Note what is absent: the transcript, the persona, and `min_price`. The floor
    is confidential (SPEC-036 revoked the column from anon / authenticated), and
    a brief is not an exception to that.
    """

    item_id: str | None
    message: str
    item_name: str | None = None
    listed_price: float | None = None
    condition: str | None = None
    standing_price: float | None = None
    last_buyer_offer: float | None = None

    def as_text(self) -> str:
        lines = []
        if self.item_id:
            lines.append(f"Context Item ID: {self.item_id}")
        if self.item_name:
            lines.append(f"Item: {self.item_name}")
        if self.listed_price is not None:
            lines.append(f"Listed price: RM{self.listed_price:.0f}")
        if self.condition:
            lines.append(f"Condition: {self.condition}")
        if self.standing_price is not None:
            # The lowest this buyer has already been quoted. Disclosing it here
            # is safe — they were told it out loud — and it is what stops the
            # decider passing a `current_price` of 0 on every call (SPEC-084).
            lines.append(f"Lowest price already quoted to this buyer: RM{self.standing_price:.0f}")
        if self.last_buyer_offer is not None:
            # Resolved from the transcript by `last_buyer_offer`, not by the model.
            # Without it, an insisting buyer who names no number ("use the tool
            # damn it") got the SELLER's standing price passed as their offer —
            # which reads to `evaluate_offer` as the buyer meeting our price and
            # hands them a concession they never made.
            lines.append(f"Buyer's last offer: RM{self.last_buyer_offer:.0f}")
        lines.append("")
        lines.append(f"Buyer message: {self.message}")
        return "\n".join(lines)


# A price the buyer typed: 1000, RM1,050, 1050.00. Bounded so a phone number or
# a postcode in a shipping address cannot be read as an offer.
_PRICE_PATTERN = re.compile(r"(?<![\d.])(?:rm\s*)?(\d{1,3}(?:,\d{3})+|\d{2,6})(?:\.\d{1,2})?(?![\d])", re.I)


def last_buyer_offer(message: str, history: list[dict] | None = None) -> float | None:
    """The most recent number the BUYER named, this turn or earlier.

    Resolved here rather than asked of the model, because the model's answer to
    "what did they offer?" was measurably its own standing price. Searches this
    message first, then back through the buyer's turns.
    """
    sources = [message]
    for row in reversed(history or []):
        if row.get("role") == "human":
            sources.append(row.get("content") or "")

    for text in sources:
        found = _PRICE_PATTERN.findall(text or "")
        if found:
            try:
                return float(found[-1].replace(",", ""))
            except ValueError:
                continue
    return None


def build_brief(
    user_id: str | None,
    item_id: str | None,
    message: str,
    item: dict | None = None,
    history: list[dict] | None = None,
) -> TurnBrief:
    """Assemble the brief, resolving the standing price from the server.

    `active_negotiated_price` is the same resolver the item card and checkout
    use, so the decider anchors to the number those surfaces already show
    (SPEC-084) rather than to whatever the model remembers.
    """
    item = item or {}
    standing = None
    try:
        standing = active_negotiated_price(user_id, item_id)
    except Exception as e:  # noqa: BLE001 — a cache hiccup must not block a turn
        logger.warning(f"⚠️ Decider could not resolve standing price: {e}")

    listed = item.get("price")
    return TurnBrief(
        item_id=item_id,
        message=message,
        item_name=item.get("name"),
        listed_price=float(listed) if listed is not None else None,
        condition=item.get("condition"),
        standing_price=float(standing) if standing is not None else None,
        last_buyer_offer=last_buyer_offer(message, history),
    )


def build_messages(brief: TurnBrief) -> list:
    """Exactly one system message and one human message. No transcript."""
    return [SystemMessage(content=DECIDER_PROMPT), HumanMessage(content=brief.as_text())]


# Resolved lazily, and cached: `bot` imports this module, so importing
# `customer_tools` at module scope here would close the cycle.
_DECIDER_TOOLS: list | None = None


def decider_tools() -> list:
    """The tools the routing table can actually reach.

    `web_search` is deliberately absent: it has no routing rule, it is the tool
    an off-topic request reaches for, and the strict-scope invariant says such a
    request gets declined rather than served.
    """
    global _DECIDER_TOOLS
    if _DECIDER_TOOLS is None:
        from .bot import customer_tools

        _DECIDER_TOOLS = [t for t in customer_tools if t.name != "web_search"]
    return _DECIDER_TOOLS


def __getattr__(name):
    """`decide.DECIDER_TOOLS` without paying the import cycle (PEP 562)."""
    if name == "DECIDER_TOOLS":
        return decider_tools()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _tools() -> list:
    return decider_tools()


def decider_model():
    return get_chat_model(temperature=LOCAL_AGENT_TEMPERATURE).bind_tools(_tools())


async def decide_turn(brief: TurnBrief) -> TurnDecision:
    """One pass, one decision. Never raises — a dead router still lets the
    speaker answer, which is strictly better than a dropped turn."""
    try:
        result = await decider_model().ainvoke(build_messages(brief))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"⚠️ Decider pass failed, answering without a tool: {e}")
        return TurnDecision(tool=None)

    calls = getattr(result, "tool_calls", None) or []
    if not calls:
        return TurnDecision(tool=None)

    call = calls[0]
    name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
    args = (call.get("args") if isinstance(call, dict) else getattr(call, "args", None)) or {}
    logger.info(f"🧭 Decider routed turn to `{name}` with {args}")
    return TurnDecision(tool=name, args=args)
