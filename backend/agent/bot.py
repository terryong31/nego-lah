import sys
sys.path.append('..')

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from env import GEMINI_API_KEY
from .config import SELLER_PERSONA
from .memory import ConversationMemory
from .vector_store import VectorMemory

# Initialize memory systems
conversation_memory = ConversationMemory()
vector_memory = VectorMemory()

# Initialize the model
model = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.7,
    google_api_key=GEMINI_API_KEY
)


# Define tools
@tool
def get_item_info(item_id: str) -> str:
    """
    Get information about an item by its ID.
    Use this when a buyer asks about a specific item.
    
    Args:
        item_id: The unique identifier of the item
    
    Returns:
        Item details including name, description, price, and condition
    """
    from connector import user_supabase
    
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    
    if response.data and len(response.data) > 0:
        item = response.data[0]
        return f"""
Item: {item.get('name', 'Unknown')}
Description: {item.get('description', 'No description')}
Price: RM{item.get('price', 'N/A')}
Condition: {item.get('condition', 'Unknown')}
Status: {item.get('status', 'available')}
"""
    return "Item not found."


@tool
def evaluate_offer(item_id: str, offered_price: float) -> str:
    """
    Evaluate a buyer's price offer against the item's minimum acceptable price.
    
    Args:
        item_id: The item being negotiated
        offered_price: The price the buyer is offering
    
    Returns:
        Recommendation on whether to accept, counter, or reject the offer
    """
    from connector import user_supabase
    
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    
    if not response.data:
        return "Cannot evaluate - item not found."
    
    item = response.data[0]
    listed_price = float(item.get('price', 0))
    min_price = float(item.get('min_price', listed_price * 0.7))  # Default 70% of listed price
    
    if offered_price >= listed_price:
        return f"ACCEPT: Offer of RM{offered_price} meets or exceeds listed price of RM{listed_price}."
    elif offered_price >= min_price:
        counter = (offered_price + listed_price) / 2
        return f"COUNTER: Offer of RM{offered_price} is acceptable but below listed price. Suggest counter-offer of RM{counter:.2f}."
    else:
        return f"REJECT: Offer of RM{offered_price} is below minimum acceptable price. Lowest acceptable is RM{min_price}."


@tool
def create_checkout_link(item_id: str, agreed_price: float) -> str:
    """
    Create a Stripe checkout link for the agreed sale.
    Only use this when both parties have agreed on a final price.
    
    Args:
        item_id: The item to purchase
        agreed_price: The final agreed price
    
    Returns:
        Checkout URL or error message
    """
    import stripe
    from env import STRIPE_API_KEY
    from connector import user_supabase
    
    stripe.api_key = STRIPE_API_KEY
    
    # Get item details
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    if not response.data:
        return "Cannot create checkout - item not found."
    
    item = response.data[0]
    
    try:
        # Create Stripe Payment Link
        price = stripe.Price.create(
            product_data={"name": item.get('name', 'Item')},
            unit_amount=int(agreed_price * 100),  # Convert to cents
            currency="myr"
        )
        
        payment_link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            metadata={"item_id": item_id}
        )
        
        return f"Checkout link created: {payment_link.url}"
    except Exception as e:
        return f"Error creating checkout: {str(e)}"


@tool
def web_search(query: str) -> str:
    """
    Search the web for information about a product or topic.
    Use this to understand the nature, market value, or specifications of items.
    
    Args:
        query: The search query (e.g., "iPhone 12 Pro specifications" or "second hand laptop prices Malaysia")
    
    Returns:
        Search results summary
    """
    import requests
    
    try:
        # Use DuckDuckGo instant answer API (no API key needed)
        url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1"
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            
            # Get abstract if available
            abstract = data.get('AbstractText', '')
            if abstract:
                return f"Search Result: {abstract[:500]}..."
            
            # Try related topics
            related = data.get('RelatedTopics', [])
            if related and len(related) > 0:
                summaries = []
                for topic in related[:3]:
                    if isinstance(topic, dict) and 'Text' in topic:
                        summaries.append(topic['Text'])
                if summaries:
                    return "Search Results:\n" + "\n".join(summaries)
            
            return "No detailed results found. Try a more specific query."
        return "Search failed. Please try again."
    except Exception as e:
        return f"Web search unavailable: {str(e)}"


# Tools for the agent
tools = [get_item_info, evaluate_offer, create_checkout_link, web_search]

# Create the agent using langgraph
agent = create_react_agent(model, tools)


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
    # Get conversation history and convert to LangChain message format
    history_data = conversation_memory.get_history(user_id)
    messages = [SystemMessage(content=SELLER_PERSONA)]
    
    for msg in history_data:
        if msg["role"] == "human":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))
    
    # Build input message with item context if provided
    input_message = message
    if item_id:
        # Fetch item details to provide context without exposing UUID
        item_details = get_item_details_for_context(item_id)
        if item_details:
            context = f"""[Currently discussing: "{item_details.get('name', 'Unknown Item')}"]
[Item Info: {item_details.get('description', 'No description')}, Price: RM{item_details.get('price', 'N/A')}, Condition: {item_details.get('condition', 'Unknown')}]

Buyer: {message}"""
            input_message = context
        else:
            input_message = f"Buyer: {message}"
    
    # Build content for multimodal message
    if files and len(files) > 0:
        # Create multimodal content with text and images
        content_parts = []
        
        # Add text part first
        content_parts.append({"type": "text", "text": input_message})
        
        # Add image parts for each file
        for file in files:
            if file["type"].startswith("image/"):
                # Image file - add as image_url with base64 data
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{file['type']};base64,{file['data']}"
                    }
                })
            else:
                # Non-image file - describe it in text
                content_parts.append({
                    "type": "text",
                    "text": f"\n[Attached file: {file['name']} ({file['type']})]"
                })
        
        messages.append(HumanMessage(content=content_parts))
    else:
        # Text-only message
        messages.append(HumanMessage(content=input_message))
    
    # Save user message to memory (text only for now)
    conversation_memory.add_message(user_id, "human", message, item_id, source="human")
    
    # Get agent response
    result = agent.invoke({"messages": messages})
    
    # Extract the final response - handle both string and list formats
    agent_response = result["messages"][-1].content
    
    # If response is a list (e.g., from Gemini's structured output), extract text
    if isinstance(agent_response, list):
        text_parts = []
        for part in agent_response:
            if isinstance(part, dict):
                # Extract 'text' field from dict parts
                if 'text' in part:
                    text_parts.append(part['text'])
            elif isinstance(part, str):
                text_parts.append(part)
        agent_response = ''.join(text_parts) if text_parts else str(agent_response)
    
    # Save agent response to memory
    conversation_memory.add_message(user_id, "ai", agent_response, item_id)
    
    return agent_response
