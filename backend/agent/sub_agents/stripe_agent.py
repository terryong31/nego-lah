from langgraph.prebuilt import create_react_agent

from ..llm_factory import get_chat_model
from ..tools.payment import cancel_payment_link, collect_shipping_info, create_checkout_link

STRIPE_AGENT_TOOLS = [create_checkout_link, cancel_payment_link, collect_shipping_info]


def _select_stripe_model(state, runtime):
    """Resolve this sub-agent's model per invocation (SPEC-020) — see item_agent."""
    return get_chat_model(temperature=0.1).bind_tools(STRIPE_AGENT_TOOLS)

# Define the system prompt for the Stripe Agent
STRIPE_AGENT_PROMPT = """You are a Payment Processor Agent for 'Nego-Lah'.
Your ONLY job is to handle payment links and shipping info.

Using your tools:
1. `create_checkout_link`: Use when a price is AGREED upon.
   - CHECK: Does the user look like they are ready to pay?
   - CHECK: Is the price final?
   - If yes, create the link.
2. `cancel_payment_link`: Use when user wants to cancel.
3. `collect_shipping_info`: Use after payment is confirmed.

RULES:
- VERIFY context before creating links.
- Only create ONE active link per item for a user (handled by tool, but act as a gatekeeper).
- Be professional and efficient.
"""

stripe_agent_graph = create_react_agent(
    _select_stripe_model,
    tools=STRIPE_AGENT_TOOLS,
    prompt=STRIPE_AGENT_PROMPT
)

# Allow more steps for retry logic
stripe_agent = stripe_agent_graph.with_config({"recursion_limit": 10})
