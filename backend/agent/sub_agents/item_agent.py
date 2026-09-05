from langgraph.prebuilt import create_react_agent

from ..llm_factory import get_chat_model
from ..tools.items import get_item_info, list_all_items, search_items

ITEM_AGENT_TOOLS = [get_item_info, search_items, list_all_items]


def _select_item_model(state, runtime):
    """Resolve this sub-agent's model per invocation (SPEC-020).

    Runs inside the supervisor's turn, so `hybrid_llm_session()` has already
    pinned the provider — the sub-agent lands on the same engine as the rest of
    the conversation, and takes no lease of its own.
    """
    return get_chat_model(temperature=0.3).bind_tools(ITEM_AGENT_TOOLS)

# Define the system prompt for the Item Agent
ITEM_AGENT_PROMPT = """You are an Inventory Specialist Agent for 'Nego-Lah'.
Your ONLY job is to help users find items and get details about them.
You have direct access to the database via tools.

Using your tools:
1. `list_all_items`: Use when user asks "what do you have" or general browsing.
2. `search_items`: Use when user searches for something specific (e.g., "iphone").
3. `get_item_info`: Use when user asks about a specific item ID.

RULES:
- NEVER hallucinate items. Only talk about items returned by your tools.
- If a user asks for something you don't have, say so clearly.
- Provide concise, accurate details (Price, Condition, Status).
- Do NOT negotiate prices. That is the job of the Negotiator Agent.
"""

item_agent_graph = create_react_agent(
    _select_item_model,
    tools=ITEM_AGENT_TOOLS,
    prompt=ITEM_AGENT_PROMPT
)

# Allow more steps for retry logic
item_agent = item_agent_graph.with_config({"recursion_limit": 10})
