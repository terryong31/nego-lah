from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from backend.env import GEMINI_API_KEY
from ..tools.payment import create_checkout_link, cancel_payment_link, collect_shipping_info

# Initialize the model
model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.1, # Extremely low temperature for strict payment logic
    google_api_key=GEMINI_API_KEY
)

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

stripe_agent = create_react_agent(
    model, 
    tools=[create_checkout_link, cancel_payment_link, collect_shipping_info],
    prompt=STRIPE_AGENT_PROMPT
)
