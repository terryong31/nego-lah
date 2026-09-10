import sys

sys.path.append('..')

import asyncio

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from logger import logger

from .config import AGENT_HISTORY_TURNS, SELLER_PERSONA
from .context import current_item_id, get_item_id, get_user_id, set_context
from .knowledge import item_knowledge_card, turn_needs_vision
from .llm_factory import get_chat_model, hybrid_llm_session
from .memory import ConversationMemory

# Import Sub-Agents
from .sub_agents.item_agent import item_agent
from .sub_agents.stripe_agent import stripe_agent

# Import Tools
from .tools.negotiation import assess_discount_eligibility, evaluate_offer
from .tools.orders import check_user_orders
from .tools.payment import web_search

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

    # 2. Add system notice to memory
    system_msg = "--- The AI has transferred the chat to Terry (human seller) who will take over shortly ---"
    try:
        conversation_memory.add_message(ctx_user_id, "system", system_msg, source="system")
    except Exception as e:
        logger.warning(f"⚠️ Failed to add system transfer message to memory: {e}")

    # 3. Broadcast system notice to live chat
    try:
        from payment.fulfillment import broadcast_to_chat
        broadcast_to_chat(ctx_user_id, system_msg, role="system", source="system")
    except Exception as e:
        logger.warning(f"⚠️ Failed to broadcast transfer message: {e}")

    # 4. Fetch user email & send email alert to admin
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

    return (
        "I have transferred our chat to Terry (our human seller) and sent him an alert. "
        "He will reply to you directly right here in the chat shortly!"
    )


# --- Customer Agent (Supervisor) ---

# The Customer Agent handles the conversation flow, negotiation, and personality.
# It decides when to consult the specialists.
customer_tools = [
    call_item_agent,
    call_stripe_agent,
    evaluate_offer,
    assess_discount_eligibility,
    web_search,
    check_user_orders,
    transfer_to_human,
]

CUSTOMER_AGENT_PROMPT = SELLER_PERSONA + """

SYSTEM INSTRUCTIONS:
You are the Lead Negotiator and Customer Service AI.
You have a team of specialists to help you:
1. `call_item_agent`: For finding items, checking stock, and getting item details.
2. `call_stripe_agent`: For processing payments and cancellations.
3. `check_user_orders`: To see what the user has purchased and if we are waiting for shipping info.
4. `transfer_to_human`: To transfer the chat to Terry (the human seller) if requested, if you are unable to help, or if the buyer wants a cash-on-delivery / meet-up arrangement.

YOUR ROLE:
- Talk to the user in your persona (Nego-Lah).
- Negotiate prices using `evaluate_offer` and your judgment.
- If the user asks about availability/items -> Ask Item Agent.
- If the user asks about past orders or you need to check if they bought something -> Use `check_user_orders`.
- If the deal is struck -> Ask Stripe Agent to create the link.
- If the user asks to speak with a human, wants COD / a meet-up, or you cannot resolve an inquiry -> Call `transfer_to_human`.

IMPORTANT:
- When calling `evaluate_offer` or `call_stripe_agent`, you MUST use the real 36-character UUID of the item. Never invent or guess an ID (like '12345' or '67890').
- If you don't know the item's real UUID, you MUST call `call_item_agent` first to search for the item and get its UUID.
- When calling `call_stripe_agent` to create a link, you MUST include the `item_id` and the `agreed_price`.
- To save shipping info, you NEED the `order_id`. If you don't have it, call `check_user_orders` to find the correct Order ID for the item. Do NOT ask the user for the Order ID.
- Verify you have the IDs before calling tools.
"""

def _select_customer_model(state, runtime):
    """Resolve the model for THIS turn (SPEC-020 dynamic model).

    LangGraph calls this on every LLM step, so the provider pinned by
    `hybrid_llm_session()` is honoured without recompiling the graph. Kept
    synchronous on purpose: with a provider already pinned it never probes, so
    it cannot block the event loop, and a sync callable works under both
    `.ainvoke()` and `.invoke()`.
    """
    return get_chat_model(temperature=0.7).bind_tools(customer_tools)


def _get_customer_agent():
    """The compiled supervisor graph.

    Cached because compiling a LangGraph react agent is expensive; the model is
    NOT cached with it — `_select_customer_model` re-resolves per turn, so the
    process is never frozen to whichever provider happened to be up at boot.
    """
    global _customer_agent
    if _customer_agent is not None:
        return _customer_agent

    agent_graph = create_react_agent(_select_customer_model, customer_tools, prompt=CUSTOMER_AGENT_PROMPT)
    # Allow the main agent up to 15 steps to do complex negotiation/tool chaining
    _customer_agent = agent_graph.with_config({"recursion_limit": 15})
    return _customer_agent


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


def _build_messages(user_id: str, message: str, item_id: str = None, files: list = None) -> list:
    """
    Build the LangChain message list (history + the new human turn) for an agent call.

    Reconstructs prior conversation, injects item context, and attaches item
    images plus any user-uploaded files as multimodal content parts.
    """
    # Get conversation history
    history_data = conversation_memory.get_history(user_id, limit=AGENT_HISTORY_TURNS)
    messages = []

    # Reconstruct history
    for msg in history_data:
        if msg["role"] == "human":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))

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
            context = f"""SYSTEM: Context Item ID: {item_id}
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
            input_message = f"Buyer: {message}"

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


async def chat(user_id: str, message: str, item_id: str = None, files: list = None) -> str:
    """
    Chat with the negotiation agent (awaitable; returns the full response).

    Args:
        user_id: Unique identifier for the buyer
        message: The buyer's message
        item_id: Optional item ID being discussed
        files: Optional list of files with {name, type, data (base64)}

    Returns:
        Agent's response
    """
    # Sync Redis/Supabase I/O is offloaded so it never blocks the event loop.
    messages = await asyncio.to_thread(_build_messages, user_id, message, item_id, files)

    # Save user message
    await asyncio.to_thread(
        conversation_memory.add_message, user_id, "human", message, item_id, source="human"
    )

    # --- CONTEXT INJECTION ---
    # Set request-scoped context (ContextVars) in THIS task so the agent run and
    # its tools see it. Async tasks inherit a copy of the current context, so this
    # is isolated per request and safe under concurrency.
    set_context(user_id=user_id, item_id=item_id)

    # Invoke Customer Agent (async — frees the loop while the LLM works).
    # The hybrid session pins this turn to one provider (self-hosted M5 if its
    # lease is free, Gemini otherwise) and releases the lease on the way out.
    logger.info(f"🤖 Customer Agent processing message for user {user_id}...")
    async with hybrid_llm_session() as provider:
        logger.info(f"⚡ Turn served by {provider.provider} ({provider.model})")
        result = await _get_customer_agent().ainvoke({"messages": messages})

    # Extract response
    agent_response = _extract_text_from_content(result["messages"][-1].content)

    # Save agent response
    await asyncio.to_thread(conversation_memory.add_message, user_id, "ai", agent_response, item_id)

    return agent_response


async def chat_stream(user_id: str, message: str, item_id: str = None, files: list = None):
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

    Yields:
        str: incremental text deltas of the agent's response
    """
    # Offload sync Redis/Supabase setup so it doesn't block the loop.
    messages = await asyncio.to_thread(_build_messages, user_id, message, item_id, files)

    # Save user message
    await asyncio.to_thread(
        conversation_memory.add_message, user_id, "human", message, item_id, source="human"
    )

    # Request-scoped context for tools (see chat() for rationale). Set in THIS
    # task so the agent run + tools inherit it.
    set_context(user_id=user_id, item_id=item_id)

    logger.info(f"🤖 Customer Agent streaming response for user {user_id}...")

    collected = []
    # The lease is held for the whole generator body and released in the context
    # manager's `finally` — including when the buyer disconnects mid-stream and
    # the generator is closed, which frees the laptop for the next turn at once.
    async with hybrid_llm_session() as provider:
        # Announce the engine before the first token so the UI can show its
        # hardware attribution chip while the answer is still generating.
        yield {"provider": provider.as_metadata()}

        async for chunk, _metadata in _get_customer_agent().astream(
            {"messages": messages}, stream_mode="messages"
        ):
            # Forward only assistant text; skip tool messages and tool-call chunks.
            if not isinstance(chunk, AIMessageChunk):
                continue

            # Detect tool calls for real-time status updates
            if getattr(chunk, 'tool_call_chunks', None):
                for tc in chunk.tool_call_chunks:
                    # The tool name usually arrives in the very first chunk of the tool call stream
                    if tc.get("name"):
                        tool_name = tc["name"]
                        status_text = "Cooking..."
                        if tool_name == "call_item_agent":
                            status_text = "Understanding the item..."
                        elif tool_name == "call_stripe_agent":
                            status_text = "Generating payment link..."
                        elif tool_name == "check_user_orders":
                            status_text = "Checking your orders..."
                        elif tool_name == "evaluate_offer":
                            status_text = "Evaluating your offer..."
                        elif tool_name == "web_search":
                            status_text = "Searching the market..."
                        elif tool_name == "assess_discount_eligibility":
                            status_text = "Checking discounts..."

                        yield {"status": status_text}

            text = _extract_text_from_content(chunk.content)
            if text:
                collected.append(text)
                yield text

    # Persist the assembled response once the stream is done.
    agent_response = "".join(collected)
    await asyncio.to_thread(conversation_memory.add_message, user_id, "ai", agent_response, item_id)



