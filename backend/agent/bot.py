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
    # Check context
    current_item_id = getattr(create_checkout_link, '_current_item_id', None)
    current_user_id = getattr(create_checkout_link, '_current_user_id', None)
    
    # 1. Fallback Resolution: If no item_id in context, try to find it from history using Item Agent
    if not current_item_id or current_item_id in ['test-item-id', 'None']:
        print(f"🕵️‍♂️ Missing context item_id. Attempting to resolve from history...")
        
        # Get recent history
        if current_user_id:
            history = conversation_memory.get_history(current_user_id, limit=10)
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
            
            resolution_response = item_agent.invoke({"messages": [HumanMessage(content=resolution_query)]})
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
                print(f"✅ Resolved missing item_id to: {resolved_id}")
                current_item_id = resolved_id
                
                # Update context on tools
                create_checkout_link._current_item_id = current_item_id
                cancel_payment_link._current_item_id = current_item_id
                evaluate_offer._current_item_id = current_item_id
            else:
                print(f"❌ Could not resolve item_id from history.")
    
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




