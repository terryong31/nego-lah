import sys

sys.path.append('..')

import asyncio
import json
import uuid

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from logger import logger

from .config import (
    AGENT_HISTORY_TURNS,
    AGENT_TOOL_RESULT_MAX_CHARS,
    AGENT_TOOL_TRACE_TURNS,
    CLOUD_AGENT_TEMPERATURE,
    LOCAL_AGENT_TEMPERATURE,
    LOCAL_SELLER_PERSONA,
    SELLER_PERSONA,
)
from .context import (
    current_item_id,
    get_item_id,
    get_user_id,
    get_user_language,
    pending_handoff,
    set_context,
)
from .decide import TurnDecision, build_brief, decide_turn
from .knowledge import item_knowledge_card, turn_needs_vision
from .link_guard import sanitize_payment_links, split_safe_prefix
from .llm_factory import ProviderInfo, current_provider, get_chat_model, hybrid_llm_session
from .memory import ConversationMemory
from .speak import build_messages as build_speaker_messages
from .speak import history_digest, speaker_model

# Legacy Sub-Agents (retained for backward compatibility / tests)
from .sub_agents.item_agent import item_agent
from .sub_agents.stripe_agent import stripe_agent

# Import Direct Tools (Unified Single-Agent Architecture - SPEC-079 / ADR-0026)
from .tools.items import get_item_info, list_all_items, search_items
from .tools.negotiation import assess_discount_eligibility, evaluate_offer
from .tools.orders import check_user_orders
from .tools.payment import (
    cancel_payment_link,
    collect_shipping_info,
    create_checkout_link,
    web_search,
)

conversation_memory = ConversationMemory()

_customer_agent = None

# --- Sub-Agent Wrapper Tools ---

@tool
async def call_item_agent(query: str) -> str:
    """
    Call the Inventory/Item Agent to search for items, get details, or check availability.
    Use this for ANY question regarding "what do you have", "search for X", or "details of item Y".
    The Item Agent has direct access to the database.

    Args:
        query: The user's question or search request regarding items
    """
    logger.info(f"📞 Calling Item Agent with: {query}")
    response = await item_agent.ainvoke({"messages": [HumanMessage(content=query)]})
    return response['messages'][-1].content

@tool
async def call_stripe_agent(request: str) -> str:
    """
    Call the Payment/Stripe Agent to create checkout links, cancel payments, or handle shipping info.
    Use this ONLY when:
    1. A price has been AGREED upon and the user wants to pay.
    2. The user wants to cancel a payment.
    3. The user is providing shipping information.

    Args:
        request: The specific action request (e.g. "Create link for item_id at price X", "Cancel link", "Shipping info is...")
    """
    # Check context
    ctx_item_id = get_item_id()
    ctx_user_id = get_user_id()

    # 1. Fallback Resolution: If no item_id in context, try to find it from history using Item Agent
    if not ctx_item_id or ctx_item_id in ['test-item-id', 'None']:
        logger.info("🕵️‍♂️ Missing context item_id. Attempting to resolve from history...")

        # Get recent history
        if ctx_user_id:
            history = conversation_memory.get_history(ctx_user_id, limit=10)
            history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in history])

            # Ask Item Agent to identify the item
            resolution_query = f"""
            Based on this conversation history, identify the exact UUID of the item the user wants to buy.

            HISTORY:
            {history_text}

            INSTRUCTIONS:
            1. Identify the item name mentioned in the history.
            2. Use your 'search_items' tool to find this item in the database.
            3. Return ONLY the UUID string of the matched item.
            4. If multiple items match, choose the one with the closest name.
            5. If not found in database, return 'NOT_FOUND'.
            """

            resolution_response = await item_agent.ainvoke({"messages": [HumanMessage(content=resolution_query)]})
            resolution_content = resolution_response['messages'][-1].content
            if isinstance(resolution_content, list):
                # Join text parts if it's a list (e.g. from Gemini)
                text_parts = []
                for part in resolution_content:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict) and 'text' in part:
                        text_parts.append(part['text'])
                resolved_id = "".join(text_parts).strip()
            else:
                resolved_id = str(resolution_content).strip()

            # Clean up response (remove markdown code blocks if any)
            resolved_id = resolved_id.replace('```', '').strip()

            if resolved_id and resolved_id != 'NOT_FOUND' and len(resolved_id) > 10: # Basic UUID sanity check
                logger.info(f"✅ Resolved missing item_id to: {resolved_id}")
                # Update request-scoped context so downstream tools see the resolved id
                current_item_id.set(resolved_id)
            else:
                logger.info("❌ Could not resolve item_id from history.")

    response = await stripe_agent.ainvoke({"messages": [HumanMessage(content=request)]})
    return response['messages'][-1].content


# SPEC-086. SPEC-055 requires BOTH halves of the COD answer: Terry will arrange
# it, and items are first come first served so only a paid order holds one. The
# second half lived in `COD_POLICY`, inside the persona, and the self-hosted
# model dropped it — it called this tool and then paraphrased the return string
# and nothing else. So the requirement moves into the return string, which is
# the most specific and most recent instruction the model has when it composes
# the reply (the same reasoning `evaluate_offer` documents for the floor).
COD_TRANSFER_KEYWORDS = (
    "cod",
    "cash on delivery",
    "cash-on-delivery",
    "cash",
    "meet",
    "jumpa",
    "self-collect",
    "self collect",
    "collect",
)

# Both halves are enumerated because a terse model relays only the last thing it
# was told: with the caveat simply appended, Qwen dropped the handoff half and
# answered with the caveat alone, leaving the buyer no idea Terry was coming.
FCFS_CAVEAT = (
    " Tell the buyer BOTH of these, in your own words and in their language: "
    "(1) Terry will take over from here and sort the COD out with them directly; "
    "(2) items here are FIRST COME FIRST SERVED — nothing is reserved by talking about it, "
    "only a PAID order holds the item, so if someone else pays before the meet-up happens, "
    "that arrangement is off."
)


def _is_cod_transfer(reason: str, summary: str = "") -> bool:
    """Whether this handoff is a meet-up case, and so needs the FCFS caveat.

    Checks the summary as well as the reason: the persona is told to pass
    `reason="Cash-on-delivery arrangement requested"`, but a model that writes
    its own reason often puts the detail in the summary instead.
    """
    haystack = f"{reason or ''} {summary or ''}".lower()
    return any(keyword in haystack for keyword in COD_TRANSFER_KEYWORDS)


@tool
async def transfer_to_human(reason: str, summary: str = "") -> str:
    """
    Transfer this conversation to Terry (the human seller/admin).
    Use this tool when:
    1. The user asks to speak with a real person, human, seller, or manager.
    2. You cannot resolve the user's inquiry, or there is a dispute, conflict, or complaint.
    3. Negotiation has reached an impasse and cannot continue.
    4. You are unable to continue or handle the user's specific request.
    5. The user wants cash on delivery (COD), a meet-up, self-collect, or to pay cash on
       arrival. The app cannot do any of those — only Terry can arrange them.

    Args:
        reason: Why the chat is being transferred (e.g. "Customer requested human seller",
            "Cash-on-delivery arrangement requested", "Dispute", "Unresolved inquiry").
        summary: A brief 1-2 sentence summary of what the customer needs.
    """
    ctx_user_id = get_user_id()
    if not ctx_user_id:
        return "Unable to transfer: user context missing."

    logger.info(f"🤝 Transferring chat for user {ctx_user_id} to human. Reason: {reason}")

    # 1. Update chat_settings to disable AI and flag admin intervention
    try:
        from connector import admin_supabase
        admin_supabase.table('chat_settings').upsert({
            'user_id': ctx_user_id,
            'ai_enabled': False,
            'admin_intervening': True,
            'updated_at': 'now()'
        }).execute()
    except Exception as e:
        logger.warning(f"⚠️ Failed to update chat_settings for human transfer: {e}")

    # 2. Hand the separator to the turn runner (SPEC-070). Writing it here put
    # it in the transcript above the farewell the agent is still composing, and
    # sent it to the buyer mid-stream — where a push into the live message list
    # makes the AI SDK re-append the whole reply. It goes out after the reply.
    pending_handoff.set(
        "--- The AI has transferred the chat to Terry (human seller) who will take over shortly ---"
    )

    # 3. Fetch user email & send email alert to admin
    try:
        from connector import admin_supabase
        user_email = None
        user_res = admin_supabase.auth.admin.get_user_by_id(ctx_user_id)
        if user_res and hasattr(user_res, "user") and user_res.user:
            user_email = user_res.user.email
        elif user_res and isinstance(user_res, dict):
            user_email = user_res.get("email") or (user_res.get("user") or {}).get("email")

        from services.email_service import send_human_transfer_alert
        send_human_transfer_alert(
            user_id=ctx_user_id,
            reason=reason,
            user_email=user_email,
            summary=summary,
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to send human transfer email alert: {e}")

    handoff = (
        "I have transferred our chat to Terry (our human seller) and sent him an alert. "
        "He will reply to you directly right here in the chat shortly!"
    )
    # Only for a meet-up: on a dispute or a plain "I want a human" the caveat is
    # noise, and noise in a tool result is the thing that makes models ignore it.
    if _is_cod_transfer(reason, summary):
        handoff += FCFS_CAVEAT
    return handoff


# --- Customer Agent (Supervisor) ---

# The Customer Agent handles the conversation flow, negotiation, and personality.
# In the Unified Architecture (SPEC-079), all domain tools are bound directly.
customer_tools = [
    # Catalog tools
    get_item_info,
    search_items,
    list_all_items,
    # Payment & fulfillment tools
    create_checkout_link,
    cancel_payment_link,
    collect_shipping_info,
    # Negotiation & guardrail tools
    evaluate_offer,
    assess_discount_eligibility,
    # External context tool
    web_search,
    # Order inspection tool
    check_user_orders,
    # Human escalation tool
    transfer_to_human,
]

CUSTOMER_AGENT_PROMPT = SELLER_PERSONA + """

SYSTEM INSTRUCTIONS:
You are the Lead Negotiator and Customer Service AI for 'Nego-Lah'.
You have direct access to domain tools to assist buyers:
1. `search_items` / `list_all_items` / `get_item_info`: For finding items, checking stock, and inspecting listing details.
2. `create_checkout_link` / `cancel_payment_link`: For generating Stripe checkout links or cancelling active sessions.
3. `collect_shipping_info`: For saving buyer delivery details (name, phone, address).
4. `check_user_orders`: To inspect past orders or check fulfillment status.
5. `evaluate_offer`: To verify buyer price offers against minimum floor price guardrails.
6. `assess_discount_eligibility`: To evaluate buyer reasons for custom discounts.
7. `web_search`: To search external market benchmarks when additional context is needed.
8. `transfer_to_human`: To transfer the chat to Terry (the human seller) if requested, if you are unable to help, or if the buyer wants cash on delivery (COD) or a physical meet-up.

YOUR ROLE:
- Talk to the user in your persona (Nego-Lah).
- Negotiate prices using `evaluate_offer` and your judgment.
- If the user asks about availability/items -> Use catalog search and lookup tools directly.
- If the user asks about past orders or you need to check if they bought something -> Use `check_user_orders`.
- If the deal is struck and price agreed upon -> Call `create_checkout_link`.
- If the user provides shipping details after purchase -> Call `collect_shipping_info`.
- If the user asks to speak with a human, wants COD / a meet-up, or you cannot resolve an inquiry -> Call `transfer_to_human`.

IMPORTANT:
- When calling `evaluate_offer` or `create_checkout_link`, you MUST use the real 36-character UUID of the item. Never invent or guess an ID (like '12345' or '67890').
- If you don't know the item's real UUID, use `search_items` first to search for the item and get its UUID.
- When calling `create_checkout_link`, you MUST include the `item_id` and the `agreed_price`.
- To save shipping info, you NEED the `order_id`. If you don't have it, call `check_user_orders` to find the correct Order ID for the item. Do NOT ask the user for the Order ID.
- Verify you have the IDs before calling tools.
"""

LOCAL_CUSTOMER_AGENT_PROMPT = LOCAL_SELLER_PERSONA + """

===== YOUR JOB, IN ORDER =====
You are the negotiator and customer service agent for 'Nego-Lah'.

1. The buyer names a price -> call `evaluate_offer`, then say what its verb tells you.
2. The buyer asks what is available -> call `search_items` or `list_all_items`.
3. The buyer asks about an item you do not have an id for -> call `search_items` first.
4. The buyer asks about a past order or delivery -> call `check_user_orders`.
5. A price is agreed AND confirmed -> call `create_checkout_link`.
6. The buyer gives shipping details -> call `collect_shipping_info`.
7. The buyer wants a human, COD, a meet-up, or you are stuck -> call `transfer_to_human`.

IDS:
- `evaluate_offer` and `create_checkout_link` need the item's REAL 36-character UUID.
  Never invent one. If you do not have it, call `search_items` and use what it returns.
- `create_checkout_link` needs both `item_id` and `agreed_price`.
- `collect_shipping_info` needs an `order_id`. Get it from `check_user_orders`. Never ask
  the buyer for it.
"""


def customer_prompt_for(info: ProviderInfo | None) -> str:
    """The system prompt for the engine serving this turn (SPEC-081).

    The self-hosted Qwen and Gemini fail differently enough that one prompt
    cannot serve both: see `LOCAL_SELLER_PERSONA` for what the shared prompt
    did to Qwen's tool calling. `None` — a script, a standalone tool call, a
    test outside `hybrid_llm_session()` — takes the cloud prompt, matching the
    cloud default everywhere else in the dispatcher.
    """
    return LOCAL_CUSTOMER_AGENT_PROMPT if (info is not None and info.is_local) else CUSTOMER_AGENT_PROMPT


def _select_customer_prompt(state):
    """Resolve the system prompt for THIS turn from the pinned provider.

    Passed to `create_react_agent` as a callable for the same reason
    `_select_customer_model` is: the graph is compiled once and cached, so a
    frozen string would pin every future turn to whichever engine happened to
    be up at boot. LangGraph calls this on each LLM step, and `current_provider`
    was pinned for the whole turn by `hybrid_llm_session()` — so a turn can
    never run on one engine under the other engine's prompt.
    """
    return [SystemMessage(content=customer_prompt_for(current_provider.get()))] + state["messages"]


def customer_temperature_for(info: ProviderInfo | None) -> float:
    """Sampling temperature for the engine serving this turn (SPEC-081).

    The two engines do not tolerate the same heat. At 0.7 the self-hosted Qwen
    answers a bare offer with improvised prose instead of calling
    `evaluate_offer` — measured 0/3 at 0.7 against 3/3 at 0.3 on the live
    tunnel, same prompt, same offer. Gemini keeps the warmer setting it was
    tuned at.
    """
    return LOCAL_AGENT_TEMPERATURE if (info is not None and info.is_local) else CLOUD_AGENT_TEMPERATURE


def _select_customer_model(state, runtime):
    """Resolve the model for THIS turn (SPEC-020 dynamic model).

    LangGraph calls this on every LLM step, so the provider pinned by
    `hybrid_llm_session()` is honoured without recompiling the graph. Kept
    synchronous on purpose: with a provider already pinned it never probes, so
    it cannot block the event loop, and a sync callable works under both
    `.ainvoke()` and `.invoke()`.
    """
    temperature = customer_temperature_for(current_provider.get())
    return get_chat_model(temperature=temperature).bind_tools(customer_tools)


def _get_customer_agent():
    """The compiled supervisor graph.

    Cached because compiling a LangGraph react agent is expensive; neither the
    model nor the prompt is cached with it — `_select_customer_model` and
    `_select_customer_prompt` re-resolve per turn, so the process is never
    frozen to whichever provider happened to be up at boot.
    """
    global _customer_agent
    if _customer_agent is not None:
        return _customer_agent

    agent_graph = create_react_agent(_select_customer_model, customer_tools, prompt=_select_customer_prompt)
    # Allow the main agent up to 15 steps to do complex negotiation/tool chaining
    _customer_agent = agent_graph.with_config({"recursion_limit": 15})
    return _customer_agent


# --- Local decide-then-speak turn (SPEC-091) --------------------------------
#
# The ReAct loop above works on Gemini and does not work on the self-hosted
# Qwen: measured against the live tunnel, tool calls go 3/3 with an empty window
# and 0/3 once the window holds a single prior assistant reply, with the prompt
# byte-identical across both. What the model needs is not a better prompt but a
# context that looks like the job — so a local turn runs two narrow passes
# instead of one wide loop. See `agent/decide.py` and `agent/speak.py`.

_TOOLS_BY_NAME = {t.name: t for t in customer_tools}


def uses_decide_then_speak(info: ProviderInfo | None) -> bool:
    """Whether this turn runs the two-pass local path.

    Keyed off the provider `hybrid_llm_session()` already pinned, exactly as the
    prompt and temperature are (SPEC-081), so a turn can never be routed by one
    architecture and spoken under the other. Unpinned — scripts, evals,
    standalone tool calls — keeps the ReAct agent it has always used.
    """
    return info is not None and info.is_local


async def execute_decision(decision: TurnDecision) -> str:
    """Run the tool the decider chose, through the tool object itself.

    Dispatch goes via the bound `customer_tools` registry rather than a lookup
    by attribute, so argument validation, the ContextVar scoping in
    `agent/context.py` and every domain guardrail apply exactly as they do on
    the cloud path.
    """
    tool_obj = _TOOLS_BY_NAME[decision.tool]
    return await tool_obj.ainvoke(decision.args or {})


async def run_decision(decision: TurnDecision) -> str | None:
    """The tool result for this turn, or None when there isn't one.

    None is a first-class outcome, not an error: the turn may legitimately need
    no tool, the decider may have named one that does not exist, or the tool may
    have failed. In all three the speaker still answers — a buyer waiting on a
    dropped turn is worse than a buyer answered without a tool result, and the
    speaker has no numbers of its own to invent with.
    """
    if not decision.calls_a_tool:
        return None

    if decision.tool not in _TOOLS_BY_NAME:
        logger.warning(f"⚠️ Decider named an unknown tool `{decision.tool}` — answering without it.")
        return None

    try:
        return await execute_decision(decision)
    except Exception as e:  # noqa: BLE001 — a dead tool must not drop the turn
        logger.warning(f"⚠️ Tool `{decision.tool}` failed during a local turn: {e}")
        return None


def _decider_brief(user_id: str, message: str, item_id: str | None, history: list[dict] | None = None):
    """The decider's brief for this turn, with the listing it is negotiating over."""
    item = get_item_details_for_context(item_id) if item_id else None
    return build_brief(
        user_id=user_id, item_id=item_id, message=message, item=item, history=history
    )


def _speaker_messages(
    brief,
    decision: TurnDecision,
    tool_result: str | None,
    history: list[dict],
    language: str | None,
) -> list:
    """Assemble the speaker's turn, including the reply it must not repeat."""
    previous = next(
        (row.get("content") for row in reversed(history or []) if row.get("role") != "human"),
        None,
    )
    target_lang = (language or get_user_language() or "en").lower().strip()
    directive = LANGUAGE_DIRECTIVES.get(target_lang, LANGUAGE_DIRECTIVES["en"])

    return build_speaker_messages(
        brief_text=brief.as_text(),
        tool_name=decision.tool,
        tool_result=tool_result,
        previous_reply=previous,
        history_digest=history_digest(history),
        language_directive=directive,
    )


def get_item_details_for_context(item_id: str) -> dict:
    """Helper to get item details for building context message."""
    from connector import user_supabase

    try:
        response = user_supabase.table('items').select('name, description, price, condition, image_path').eq('id', item_id).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
    except Exception as e:
        logger.debug(f"get_item_details_for_context failed for {item_id}: {e}")
    return None


def _extract_text_from_content(content) -> str:
    """Normalize LangChain message content (str or list of parts) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and 'text' in part:
                parts.append(part['text'])
        return ''.join(parts)
    return str(content) if content is not None else ""


LANGUAGE_DIRECTIVES = {
    "ms": (
        "SYSTEM LANGUAGE DIRECTIVE:\n"
        "The user's preferred language setting is Bahasa Melayu (ms).\n"
        "You MUST respond in natural, friendly Malaysian Bahasa Melayu (santai dan mesra). "
        "Do not default to English. Negotiate, answer questions, and converse entirely in Bahasa Melayu."
    ),
    "zh": (
        "SYSTEM LANGUAGE DIRECTIVE:\n"
        "The user's preferred language setting is Simplified Chinese (zh).\n"
        "You MUST respond in natural, friendly Simplified Chinese (简体中文). "
        "Do not default to English. Negotiate, answer questions, and converse entirely in Simplified Chinese."
    ),
    "en": (
        "SYSTEM LANGUAGE DIRECTIVE:\n"
        "The user's preferred language setting is English (en).\n"
        "You MUST respond in natural, friendly Malaysian English / Manglish."
    ),
}


def _truncate_tool_result(text) -> str:
    """One tool result, short enough that it cannot dominate the window."""
    text = _extract_text_from_content(text)
    if len(text) <= AGENT_TOOL_RESULT_MAX_CHARS:
        return text
    return text[:AGENT_TOOL_RESULT_MAX_CHARS] + "…"


def extract_tool_trace(result_messages) -> list[dict]:
    """The tool calls this turn made, paired with their results (SPEC-087).

    Shaped for storage and for replay: `[{name, args, id, result}]`. A call whose
    result never arrived is dropped rather than stored half-formed — replaying an
    `AIMessage` with a tool call and no matching `ToolMessage` is rejected by
    every provider.
    """
    results: dict[str, str] = {}
    for message in result_messages or []:
        if isinstance(message, ToolMessage) and message.tool_call_id:
            results[message.tool_call_id] = _truncate_tool_result(message.content)

    trace = []
    for message in result_messages or []:
        for call in getattr(message, "tool_calls", None) or []:
            call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            args = call.get("args") if isinstance(call, dict) else getattr(call, "args", None)
            if not call_id or not name or call_id not in results:
                continue
            trace.append({"name": name, "args": args or {}, "id": call_id, "result": results[call_id]})
    return trace


def _replay_ai_turn(messages: list, row: dict, with_trace: bool) -> None:
    """Append one stored assistant turn to the context being rebuilt.

    With a trace, the turn is replayed as it actually happened — the tool call,
    its result, then what the agent said — so the transcript demonstrates that a
    price question is answered by calling a tool. Without one (a turn that called
    nothing, an older turn, or anything written before SPEC-087) it replays as
    the plain assistant message it always did.
    """
    trace = row.get("tool_calls") if with_trace else None
    if isinstance(trace, str):
        try:
            trace = json.loads(trace)
        except ValueError:
            trace = None

    if trace:
        calls = [{"name": c["name"], "args": c.get("args") or {}, "id": c["id"]} for c in trace]
        messages.append(AIMessage(content="", tool_calls=calls))
        # One ToolMessage per call, in the same order: a dangling tool call is a
        # hard error on both providers.
        for call in trace:
            messages.append(ToolMessage(content=call.get("result", ""), tool_call_id=call["id"]))

    messages.append(AIMessage(content=row["content"]))


def fetch_history(user_id: str) -> list[dict]:
    """This turn's window of prior messages, with SPEC-087 tool traces.

    Read once per turn and handed to whichever path serves it, so the ReAct
    agent and the local decide-then-speak turn can never disagree about what
    was said — and so it is read BEFORE the new human message is appended,
    which is what keeps that message out of its own history.
    """
    return conversation_memory.get_history(
        user_id, limit=AGENT_HISTORY_TURNS, include_tool_calls=True
    )


def _build_messages(
    user_id: str,
    message: str,
    item_id: str = None,
    files: list = None,
    language: str = None,
    history_data: list[dict] | None = None,
) -> list:
    """
    Build the LangChain message list (history + the new human turn) for an agent call.

    Reconstructs prior conversation, injects item context and user preferred language,
    and attaches item images plus any user-uploaded files as multimodal content parts.
    """
    if history_data is None:
        history_data = fetch_history(user_id)
    messages = []

    # Which assistant turns get their tool trace replayed: the most recent ones
    # only (SPEC-087 — the demonstration works by adjacency, and every trace
    # costs context).
    ai_rows = [i for i, m in enumerate(history_data) if m.get("role") != "human"]
    traced = set(ai_rows[-AGENT_TOOL_TRACE_TURNS:]) if AGENT_TOOL_TRACE_TURNS > 0 else set()

    # Reconstruct history
    for index, msg in enumerate(history_data):
        if msg["role"] == "human":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            _replay_ai_turn(messages, msg, with_trace=index in traced)

    target_lang = (language or get_user_language() or "en").lower().strip()
    lang_directive = LANGUAGE_DIRECTIVES.get(target_lang, LANGUAGE_DIRECTIVES["en"])
    should_inject_lang = (language is not None) or (target_lang in ("ms", "zh"))

    # Build input message with item context
    input_message = message
    item_images = []

    if item_id:
        item_details = get_item_details_for_context(item_id)
        if item_details:
            # SPEC-059: the knowledge card carries what the photos were being
            # re-sent to say. `items.description` was itself written from those
            # photos by image_analyzer at listing time, so on an ordinary turn
            # the card is the same information at a fraction of the tokens.
            card = item_knowledge_card(item_details)
            # The hinge is the DESCRIPTION, not the card: name and price say
            # nothing about what the thing looks like.
            has_description = bool((item_details.get('description') or '').strip())
            lang_block = f"\n{lang_directive}" if should_inject_lang else ""
            context = f"""SYSTEM: Context Item ID: {item_id}{lang_block}
{card}

Buyer: {message}"""
            input_message = context

            # The photos come back only when this particular turn needs to look:
            # a visual question, a buyer upload, or a listing with no description
            # (where the photos are the only description there is).
            if turn_needs_vision(message, files=files, has_description=has_description):
                try:
                    if item_details.get('image_path'):
                        import json
                        images_map = json.loads(item_details['image_path'])
                        # Two is enough to answer "what does it look like"; more
                        # is mostly duplicate angles at full price each.
                        item_images = list(images_map.values())[:2]
                except Exception as e:
                    logger.info(f"Failed to parse item images: {e}")
        else:
            if should_inject_lang:
                input_message = f"{lang_directive}\n\nBuyer: {message}"
            else:
                input_message = f"Buyer: {message}"
    elif should_inject_lang:
        input_message = f"{lang_directive}\n\nBuyer: {message}"

    # Handle files (multimodal - user uploads + item images)
    content_parts = [{"type": "text", "text": input_message}]

    # Add Item Images (if any)
    for img_url in item_images:
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": img_url}
        })

    # Add User Uploaded Files (if any)
    if files and len(files) > 0:
        for file in files:
            if file["type"].startswith("image/"):
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{file['type']};base64,{file['data']}"}
                })
            else:
                content_parts.append({"type": "text", "text": f"\n[Attached: {file['name']}]"})

    # Send message
    if len(content_parts) > 1:
        messages.append(HumanMessage(content=content_parts))
    else:
        messages.append(HumanMessage(content=input_message))

    return messages


async def _local_decide(user_id, message, item_id, history):
    """Route this turn, then run whatever it routed to.

    Returns `(brief, decision, tool_result)`. The brief is built off the thread
    because it reads the listing and the standing price from Supabase/Redis.
    """
    brief = await asyncio.to_thread(_decider_brief, user_id, message, item_id, history)
    decision = await decide_turn(brief)
    tool_result = await run_decision(decision)
    return brief, decision, tool_result


def _local_trace(decision: TurnDecision, tool_result: str | None) -> list[dict]:
    """The SPEC-087 trace for a local turn.

    A decision that ran nothing stores nothing: replaying a tool call with no
    result is rejected by every provider, and inventing one would put a tool
    result in the transcript that no tool produced.
    """
    if not decision.calls_a_tool or tool_result is None:
        return []
    return [{
        "name": decision.tool,
        "args": decision.args or {},
        "id": f"local_{uuid.uuid4().hex[:8]}",
        "result": _truncate_tool_result(tool_result),
    }]


async def _run_local_turn(user_id, message, item_id, language, history):
    """decide -> execute -> speak, awaited whole. Returns `(reply, trace)`."""
    brief, decision, tool_result = await _local_decide(user_id, message, item_id, history)
    messages = _speaker_messages(brief, decision, tool_result, history, language)
    reply = await speaker_model().ainvoke(messages)
    return _extract_text_from_content(reply.content), _local_trace(decision, tool_result)


async def chat(
    user_id: str,
    message: str,
    item_id: str = None,
    files: list = None,
    language: str = None,
) -> str:
    """
    Chat with the negotiation agent (awaitable; returns the full response).

    Args:
        user_id: Unique identifier for the buyer
        message: The buyer's message
        item_id: Optional item ID being discussed
        files: Optional list of files with {name, type, data (base64)}
        language: Optional language preference ('en', 'ms', 'zh')

    Returns:
        Agent's response
    """
    # Sync Redis/Supabase I/O is offloaded so it never blocks the event loop.
    # Read BEFORE the new human message is saved, so it isn't in its own history.
    history = await asyncio.to_thread(fetch_history, user_id)

    # Save user message
    await asyncio.to_thread(
        conversation_memory.add_message, user_id, "human", message, item_id, source="human"
    )

    # --- CONTEXT INJECTION ---
    # Set request-scoped context (ContextVars) in THIS task so the agent run and
    # its tools see it. Async tasks inherit a copy of the current context, so this
    # is isolated per request and safe under concurrency.
    set_context(user_id=user_id, item_id=item_id, language=language)

    # Invoke Customer Agent (async — frees the loop while the LLM works).
    # The hybrid session pins this turn to one provider (self-hosted M5 if its
    # lease is free, Gemini otherwise) and releases the lease on the way out.
    logger.info(f"🤖 Customer Agent processing message for user {user_id} (lang={language or 'en'})...")
    async with hybrid_llm_session() as provider:
        logger.info(f"⚡ Turn served by {provider.provider} ({provider.model})")

        if uses_decide_then_speak(provider):
            agent_response, trace = await _run_local_turn(
                user_id, message, item_id, language, history
            )
        else:
            messages = await asyncio.to_thread(
                _build_messages, user_id, message, item_id, files, language, history
            )
            result = await _get_customer_agent().ainvoke({"messages": messages})
            agent_response = _extract_text_from_content(result["messages"][-1].content)
            trace = extract_tool_trace(result.get("messages"))

    # SPEC-088: a payment URL leaves here only if this server issued it.
    agent_response = sanitize_payment_links(agent_response, user_id, item_id)

    # Save agent response, with the tools it called (SPEC-087) so the next turn's
    # transcript shows the call rather than just its conclusion.
    await asyncio.to_thread(
        conversation_memory.add_message, user_id, "ai", agent_response, item_id, "ai", trace
    )

    return agent_response


TOOL_STATUS_TEXT = {
    "call_item_agent": "Understanding the item...",
    "get_item_info": "Understanding the item...",
    "search_items": "Understanding the item...",
    "list_all_items": "Understanding the item...",
    "create_checkout_link": "Generating payment link...",
    "cancel_payment_link": "Cancelling your payment link...",
    "collect_shipping_info": "Saving your shipping details...",
    "check_user_orders": "Checking your orders...",
    "evaluate_offer": "Evaluating your offer...",
    "web_search": "Searching the market...",
    "assess_discount_eligibility": "Checking discounts...",
    "transfer_to_human": "Connecting to human seller...",
}


def tool_status_text(tool_name: str) -> str:
    """The SSE status frame for a tool call, shared by both turn architectures."""
    return TOOL_STATUS_TEXT.get(tool_name, "Cooking...")


def _classify_stripe_request(request_text: str) -> str:
    """What is the Stripe sub-agent actually being asked to do?

    `call_stripe_agent` is one wrapper tool fronting three very different
    jobs (create a checkout link, cancel one, save shipping info), and the
    top-level stream never sees inside it — sub-agent tokens don't leak into
    this stream (see the module docstring). The `request` argument the
    supervisor writes when it decides to call it is the only signal
    available, so the SSE status is picked from that text instead of being
    hardcoded to the payment-link case (SPEC-078).
    """
    lowered = (request_text or "").lower()
    if "cancel" in lowered:
        return "Cancelling your payment link..."
    if any(kw in lowered for kw in ("ship", "address", "phone", "recipient", "deliver")):
        return "Saving your shipping details..."
    return "Generating payment link..."


async def _persist_stream(user_id, item_id, collected, streamed_calls, streamed_results):
    """Store the streamed reply and the tool trace that produced it (SPEC-087).

    Shared by both turn architectures so they cannot drift on what a stored turn
    looks like. A call whose result never arrived is dropped rather than stored
    half-formed — replaying an assistant tool call with no matching tool result
    is rejected by every provider.
    """
    trace = []
    for call_id, call in streamed_calls.items():
        if not call["name"] or call_id not in streamed_results:
            continue
        try:
            args = json.loads(call["args"]) if call["args"] else {}
        except ValueError:
            args = {}
        trace.append({
            "name": call["name"],
            "args": args,
            "id": call_id,
            "result": streamed_results[call_id],
        })

    await asyncio.to_thread(
        conversation_memory.add_message,
        user_id, "ai", "".join(collected), item_id, "ai", trace,
    )


async def chat_stream(
    user_id: str,
    message: str,
    item_id: str = None,
    files: list = None,
    language: str = None,
):
    """
    Streaming variant of chat(). Async generator yielding text deltas as the
    agent produces them, using LangGraph's native async streaming (.astream) so
    the LLM's network I/O never blocks the event loop.

    Uses LangGraph's token-level streaming (stream_mode="messages"). Only text
    from the supervisor's own LLM turns is forwarded - tool-call decision chunks
    (empty content) are skipped, and sub-agents run inside tool calls so their
    tokens do not leak into this stream. The full response is persisted to memory
    once streaming completes.

    Args:
        user_id: Unique identifier for the buyer
        message: The buyer's message
        item_id: Optional item ID being discussed
        files: Optional list of files with {name, type, data (base64)}
        language: Optional language preference ('en', 'ms', 'zh')

    Yields:
        str: incremental text deltas of the agent's response
    """
    # Offload sync Redis/Supabase setup so it doesn't block the loop. Read BEFORE
    # the new human message is saved, so it isn't in its own history.
    history = await asyncio.to_thread(fetch_history, user_id)

    # Save user message
    await asyncio.to_thread(
        conversation_memory.add_message, user_id, "human", message, item_id, source="human"
    )

    # Request-scoped context for tools (see chat() for rationale). Set in THIS
    # task so the agent run + tools inherit it.
    set_context(user_id=user_id, item_id=item_id, language=language)

    logger.info(f"🤖 Customer Agent streaming response for user {user_id} (lang={language or 'en'})...")

    collected = []
    # Text withheld mid-stream because it may be the start of a payment link
    # (SPEC-088); flushed, validated, once the link closes or the stream ends.
    link_buffer = ""
    # SPEC-087. The trace has to be assembled from the stream: `astream` hands
    # over tool-call fragments (name and id first, args in pieces) and, later,
    # the ToolMessage carrying the result. Keyed by call id so the two halves
    # meet again.
    streamed_calls: dict[str, dict] = {}
    streamed_results: dict[str, str] = {}
    # call_stripe_agent's args ("request": "...") stream in piecemeal across
    # several tool_call_chunks, keyed by tool-call id. Buffered here until they
    # parse as complete JSON, at which point _classify_stripe_request picks the
    # status from what the request actually says (SPEC-078).
    pending_stripe_args: dict[str, str] = {}

    # The lease is held for the whole generator body and released in the context
    # manager's `finally` — including when the buyer disconnects mid-stream and
    # the generator is closed, which frees the laptop for the next turn at once.
    async with hybrid_llm_session() as provider:
        # Announce the engine before the first token so the UI can show its
        # hardware attribution chip while the answer is still generating.
        yield {"provider": provider.as_metadata()}

        if uses_decide_then_speak(provider):
            # SPEC-091. Two narrow passes instead of one wide ReAct loop: the
            # decider routes the turn with no persona in its window, then the
            # speaker renders the result with no tools bound.
            brief, decision, tool_result = await _local_decide(
                user_id, message, item_id, history
            )
            if decision.calls_a_tool:
                yield {"status": tool_status_text(decision.tool)}
            for call in _local_trace(decision, tool_result):
                streamed_calls[call["id"]] = {"name": call["name"], "args": json.dumps(call["args"])}
                streamed_results[call["id"]] = call["result"]

            speaker_messages = _speaker_messages(brief, decision, tool_result, history, language)
            async for chunk in speaker_model().astream(speaker_messages):
                text = _extract_text_from_content(getattr(chunk, "content", ""))
                if not text:
                    continue
                # SPEC-088, same contract as the cloud path: hold everything
                # from an unclosed `[` until the link can be judged.
                link_buffer += text
                safe, link_buffer = split_safe_prefix(link_buffer)
                if safe:
                    safe = sanitize_payment_links(safe, user_id, item_id)
                    collected.append(safe)
                    yield safe
            trailing = link_buffer
            link_buffer = ""
            if trailing:
                tail = sanitize_payment_links(trailing, user_id, item_id)
                if tail:
                    collected.append(tail)
                    yield tail
            await _persist_stream(user_id, item_id, collected, streamed_calls, streamed_results)
            return

        messages = await asyncio.to_thread(
            _build_messages, user_id, message, item_id, files, language, history
        )
        async for chunk, _metadata in _get_customer_agent().astream(
            {"messages": messages}, stream_mode="messages"
        ):
            # A tool's result is not forwarded to the buyer, but it is half of
            # the trace this turn gets stored with.
            if isinstance(chunk, ToolMessage):
                if chunk.tool_call_id:
                    streamed_results[chunk.tool_call_id] = _truncate_tool_result(chunk.content)
                continue

            # Forward only assistant text; skip tool messages and tool-call chunks.
            if not isinstance(chunk, AIMessageChunk):
                continue

            # Detect tool calls for real-time status updates
            if getattr(chunk, 'tool_call_chunks', None):
                for tc in chunk.tool_call_chunks:
                    tc_id = tc.get("id") or f"idx:{tc.get('index')}"
                    tool_name = tc.get("name")

                    # Accumulate the call itself for the stored trace. The name
                    # lands on the first fragment; the args arrive as a JSON
                    # string across the rest.
                    entry = streamed_calls.setdefault(tc_id, {"name": None, "args": ""})
                    if tool_name:
                        entry["name"] = tool_name
                    entry["args"] += tc.get("args") or ""

                    # The tool name usually arrives in the very first chunk of the tool call stream
                    if tool_name and tool_name != "call_stripe_agent":
                        yield {"status": tool_status_text(tool_name)}
                        continue

                    # call_stripe_agent (or one of its continuation chunks): don't
                    # guess yet — buffer the `request` argument until it parses as
                    # complete JSON, then pick the status from what it actually says.
                    if tool_name == "call_stripe_agent":
                        pending_stripe_args[tc_id] = tc.get("args") or ""
                    elif tc_id in pending_stripe_args:
                        pending_stripe_args[tc_id] += tc.get("args") or ""
                    else:
                        continue  # not a call_stripe_agent we're tracking

                    try:
                        parsed_args = json.loads(pending_stripe_args[tc_id])
                    except ValueError:
                        continue  # still incomplete — keep buffering
                    del pending_stripe_args[tc_id]
                    request_text = parsed_args.get("request", "") if isinstance(parsed_args, dict) else ""
                    yield {"status": _classify_stripe_request(request_text)}

            text = _extract_text_from_content(chunk.content)
            if text:
                # SPEC-088. A link cannot be judged until its URL is complete,
                # and text cannot be unsent — so everything from an unclosed `[`
                # is held back, then validated before it goes out.
                link_buffer += text
                safe, link_buffer = split_safe_prefix(link_buffer)
                if safe:
                    safe = sanitize_payment_links(safe, user_id, item_id)
                    collected.append(safe)
                    yield safe

    # Anything still held back was never closed — judge it and let it go.
    if link_buffer:
        tail = sanitize_payment_links(link_buffer, user_id, item_id)
        if tail:
            collected.append(tail)
            yield tail

    await _persist_stream(user_id, item_id, collected, streamed_calls, streamed_results)



