import sys
sys.path.append('..')

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from env import GEMINI_API_KEY
from .config import SELLER_PERSONA
from .memory import ConversationMemory
from .vector_store import VectorMemory

# Import Tools
from .tools.negotiation import evaluate_offer, assess_discount_eligibility
from .tools.payment import web_search
# Import Sub-Agents
from .sub_agents.item_agent import item_agent
from .sub_agents.stripe_agent import stripe_agent
from .tools.payment import create_checkout_link, cancel_payment_link # Need to inject context into these

# Initialize memory systems
conversation_memory = ConversationMemory()
vector_memory = VectorMemory()

# Initialize the model
model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.7,
    google_api_key=GEMINI_API_KEY
)

# --- Sub-Agent Wrapper Tools ---

@tool
def call_item_agent(query: str) -> str:
    """
    Call the Inventory/Item Agent to search for items, get details, or check availability.
    Use this for ANY question regarding "what do you have", "search for X", or "details of item Y".
    The Item Agent has direct access to the database.
    
    Args:
        query: The user's question or search request regarding items
    """
    print(f"📞 Calling Item Agent with: {query}")
    response = item_agent.invoke({"messages": [HumanMessage(content=query)]})
    return response['messages'][-1].content

@tool
def call_stripe_agent(request: str) -> str:
    """
    Call the Payment/Stripe Agent to create checkout links, cancel payments, or handle shipping info.
    Use this ONLY when:
    1. A price has been AGREED upon and the user wants to pay.
    2. The user wants to cancel a payment.
    3. The user is providing shipping information.
    
    Args:
        request: The specific action request (e.g. "Create link for item_id at price X", "Cancel link", "Shipping info is...")
    """
    print(f"📞 Calling Stripe Agent with: {request}")
    # We need to pass context (user_id/item_id) to the underlying tools.
    # The sub-agent runs in its own scope, but the tools it uses (create_checkout_link)
    # rely on the *module level* context injection we do in the `chat` function.
    # Since we import `create_checkout_link` here to inject, and the stripe_agent imports it from tools,
    # python modules are singletons, so modifying the function attributes HERE should work 
    # if `stripe_agent` uses the SAME function object.
    
    response = stripe_agent.invoke({"messages": [HumanMessage(content=request)]})
    return response['messages'][-1].content


# --- Customer Agent (Supervisor) ---

# The Customer Agent handles the conversation flow, negotiation, and personality.
# It decides when to consult the specialists.
customer_tools = [
    call_item_agent,
    call_stripe_agent,
    evaluate_offer, 
    assess_discount_eligibility,
    web_search
]

CUSTOMER_AGENT_PROMPT = SELLER_PERSONA + """

SYSTEM INSTRUCTIONS:
You are the Lead Negotiator and Customer Service AI.
You have a team of specialists to help you:
1. `call_item_agent`: For finding items, checking stock, and getting item details.
2. `call_stripe_agent`: For processing payments and cancellations.

YOUR ROLE:
- Talk to the user in your persona (Nego-Lah).
- Negotiate prices using `evaluate_offer` and your judgment.
- If the user asks about availability/items -> Ask Item Agent.
- If the deal is struck -> Ask Stripe Agent to create the link.

IMPORTANT:
- When calling `call_stripe_agent` to create a link, you MUST include the `item_id` and the `agreed_price` in your request string so the agent knows what to do.
- Verify you have the `item_id` before calling payment tools.
"""

customer_agent = create_react_agent(model, customer_tools, prompt=CUSTOMER_AGENT_PROMPT)


def get_item_details_for_context(item_id: str) -> dict:
    """Helper to get item details for building context message."""
    from connector import user_supabase
    
    try:
        response = user_supabase.table('items').select('name, description, price, condition').eq('id', item_id).execute()
        if response.data and len(response.data) > 0:
            return response.data[0]
    except Exception:
        pass
    return None


def chat(user_id: str, message: str, item_id: str = None, files: list = None) -> str:
    """
    Chat with the negotiation agent.
    
    Args:
        user_id: Unique identifier for the buyer
        message: The buyer's message
        item_id: Optional item ID being discussed
        files: Optional list of files with {name, type, data (base64)}
    
    Returns:
        Agent's response
    """
    # Get conversation history
    history_data = conversation_memory.get_history(user_id, limit=50)
    messages = []
    
    # Reconstruct history
    for msg in history_data:
        if msg["role"] == "human":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
    
    # Build input message with item context
    input_message = message
    if item_id:
        item_details = get_item_details_for_context(item_id)
        if item_details:
            context = f"""SYSTEM: Context Item ID: {item_id}
Item Name: "{item_details.get('name', 'Unknown')}"
Listed Price: RM{item_details.get('price', 'N/A')}

Buyer: {message}"""
            input_message = context
        else:
            input_message = f"Buyer: {message}"
    
    # Handle files (multimodal)
    if files and len(files) > 0:
        content_parts = [{"type": "text", "text": input_message}]
        for file in files:
            if file["type"].startswith("image/"):
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{file['type']};base64,{file['data']}"}
                })
            else:
                content_parts.append({"type": "text", "text": f"\n[Attached: {file['name']}]"})
        messages.append(HumanMessage(content=content_parts))
    else:
        messages.append(HumanMessage(content=input_message))
    
    # Save user message
    conversation_memory.add_message(user_id, "human", message, item_id, source="human")
    
    # --- CONTEXT INJECTION ---
    # We inject context into the tools directly.
    # Note: Since the sub-agents use the same tool definitions (imported from the same modules),
    # setting attributes on the imported functions here should reflect in the sub-agents.
    
    # Inject into Negotiation Tools (Directly used by Customer Agent)
    evaluate_offer._current_item_id = item_id
    
    # Inject into Payment Tools (Used by Stripe Agent)
    create_checkout_link._current_user_id = user_id
    create_checkout_link._current_item_id = item_id
    cancel_payment_link._current_user_id = user_id
    cancel_payment_link._current_item_id = item_id
    
    # Inject into Item Tools (Used by Item Agent - if they needed context, but they mostly take args)
    # create_checkout_link is imported from .tools.payment, so we match the reference.
    
    # Invoke Customer Agent
    print(f"🤖 Customer Agent processing message for user {user_id}...")
    result = customer_agent.invoke({"messages": messages})
    
    # Extract response
    agent_response = result["messages"][-1].content
    
    # Handle list response
    if isinstance(agent_response, list):
        text_parts = []
        for part in agent_response:
            if isinstance(part, dict) and 'text' in part:
                text_parts.append(part['text'])
            elif isinstance(part, str):
                text_parts.append(part)
        agent_response = ''.join(text_parts) if text_parts else str(agent_response)
    
    # Save agent response
    conversation_memory.add_message(user_id, "ai", agent_response, item_id)
    
    return agent_response




