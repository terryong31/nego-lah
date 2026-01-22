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
    
    print(f"\n{'='*50}")
    print(f"🔍 GET_ITEM_INFO CALLED")
    print(f"📦 Item ID: {item_id}")
    print(f"{'='*50}")
    
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    
    print(f"📊 Query result: {len(response.data) if response.data else 0} items found")
    if response.data:
        print(f"📋 Data: {response.data}")
    
    if response.data and len(response.data) > 0:
        item = response.data[0]
        result = f"""
item_id: {item.get('id')}
Item: {item.get('name', 'Unknown')}
Description: {item.get('description', 'No description')}
Price: RM{item.get('price', 'N/A')}
Condition: {item.get('condition', 'Unknown')}
Status: {item.get('status', 'available')}
"""
        print(f"✅ Returning item info")
        return result
    print(f"❌ Item not found!")
    return "Item not found."


@tool
def search_items(search_term: str) -> str:
    """
    Search for items by name or description.
    Use this when a buyer mentions an item by name but you don't have the item_id.
    
    Args:
        search_term: The search query (item name or keywords)
    
    Returns:
        List of matching items with their IDs, names, and prices
    """
    from connector import user_supabase
    
    print(f"\n{'='*50}")
    print(f"🔎 SEARCH_ITEMS CALLED")
    print(f"🔤 Search term: '{search_term}'")
    print(f"{'='*50}")
    
    # Search by name (case-insensitive)
    query = f'%{search_term}%'
    print(f"📝 SQL ILIKE query: name ILIKE '{query}'")
    
    response = user_supabase.table('items').select('id, name, price, condition, status').ilike('name', query).limit(5).execute()
    
    print(f"📊 Query result: {len(response.data) if response.data else 0} items found")
    if response.data:
        print(f"📋 Raw data: {response.data}")
    
    if response.data and len(response.data) > 0:
        results = []
        for item in response.data:
            status = item.get('status')
            print(f"  - {item.get('name')}: status={status}")
            if status == 'available':
                results.append(f"- {item.get('name')}: RM{item.get('price')} (Condition: {item.get('condition')}) [item_id: {item.get('id')}]")
        
        if results:
            print(f"✅ Returning {len(results)} available items")
            return "Found items:\n" + "\n".join(results) + "\n\nUse the item_id when calling evaluate_offer or create_checkout_link."
        print(f"⚠️ Items found but none are available")
        return "No available items found matching that search."
    print(f"❌ No items found matching search")
    return "No items found matching that search."


@tool
def list_all_items() -> str:
    """
    List all available items in the store.
    Use this when a buyer asks what items you have, what's for sale, or wants to browse your inventory.
    
    Returns:
        List of all available items with names, prices, and conditions
    """
    from connector import user_supabase
    
    print(f"\n{'='*50}")
    print(f"📦 LIST_ALL_ITEMS CALLED")
    print(f"{'='*50}")
    
    # First, get all items to see what statuses exist
    all_items_response = user_supabase.table('items').select('id, name, price, condition, status').limit(20).execute()
    print(f"📊 All items in DB: {len(all_items_response.data) if all_items_response.data else 0}")
    if all_items_response.data:
        for item in all_items_response.data:
            print(f"  - {item.get('name')}: status='{item.get('status')}'")
    
    # Get available items (or all items if none are 'available')
    available_items = [item for item in (all_items_response.data or []) if item.get('status') in ['available', 'Active', 'active', None, '']]
    
    if not available_items:
        # If no items match 'available' status, just return all items
        available_items = all_items_response.data or []
        print(f"⚠️ No items with 'available' status, returning all {len(available_items)} items")
    
    if available_items and len(available_items) > 0:
        results = []
        for item in available_items:
            results.append(f"- {item.get('name')}: RM{item.get('price')} ({item.get('condition')})")
        
        print(f"✅ Returning {len(results)} items")
        return f"Here are my available items:\n" + "\n".join(results) + "\n\nLet me know which one catches your eye! 😊"
    
    print(f"❌ No items available")
    return "I don't have any items listed right now. Check back later!"


@tool
def assess_discount_eligibility(buyer_reason: str) -> str:
    """
    Assess if a buyer's reason for requesting a discount is genuine and deserving.
    Use your judgment to evaluate sincerity, relevance, and impact.
    
    Args:
        buyer_reason: The buyer's stated reason for wanting a discount
    
    Returns:
        Assessment with recommended discount percentage (0%, 5%, or 10%)
    """
    from .config import DISCOUNT_SCORING_GUIDE
    
    # LOG: Tool was called
    print(f"\n{'='*50}")
    print(f"🎯 ASSESS_DISCOUNT_ELIGIBILITY CALLED")
    print(f"📝 Buyer's reason: {buyer_reason}")
    print(f"{'='*50}\n")
    
    # This tool returns the scoring guide for the AI to use in its assessment
    # The AI will evaluate and decide based on the guide
    result = f"""
Use this guide to assess the buyer's reason:
{DISCOUNT_SCORING_GUIDE}

Buyer's reason: "{buyer_reason}"

Provide your assessment:
1. SINCERITY score (1-10):
2. RELEVANCE score (1-10):
3. IMPACT score (1-10):
4. Average score:
5. Recommended extra discount: 0%, 5%, or 10%
"""
    return result


@tool
def evaluate_offer(item_id: str, offered_price: float, extra_discount_percent: float = 0) -> str:
    """
    Evaluate a buyer's price offer against the item's minimum acceptable price.
    
    Args:
        item_id: The item being negotiated
        offered_price: The price the buyer is offering
        extra_discount_percent: Extra discount earned via assess_discount_eligibility (0, 5, or 10)
    
    Returns:
        Recommendation on whether to accept, counter, or reject the offer
    """
    from connector import user_supabase
    
    # LOG: Tool was called
    print(f"\n{'='*50}")
    print(f"💰 EVALUATE_OFFER CALLED")
    print(f"📦 Item ID: {item_id}")
    print(f"💵 Offered Price: RM{offered_price}")
    print(f"🎁 Extra Discount: {extra_discount_percent}%")
    print(f"{'='*50}")
    
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    
    if not response.data:
        print("❌ Item not found!")
        return "Cannot evaluate - item not found."
    
    item = response.data[0]
    listed_price = float(item.get('price', 0))
    min_price = float(item.get('min_price', listed_price * 0.7))  # Absolute floor from DB
    
    # Apply extra discount to the acceptable threshold (not below min_price)
    discount_amount = listed_price * (extra_discount_percent / 100)
    adjusted_threshold = max(listed_price - discount_amount, min_price)
    
    # LOG: Price calculations
    print(f"📊 Listed Price: RM{listed_price}")
    print(f"🔻 Min Price (floor): RM{min_price}")
    print(f"🎯 Adjusted Threshold: RM{adjusted_threshold}")
    print(f"{'='*50}\n")
    
    if offered_price >= listed_price:
        result = f"ACCEPT: Offer of RM{offered_price} meets or exceeds listed price of RM{listed_price}."
    elif offered_price >= adjusted_threshold:
        if offered_price <= min_price:
            result = f"ACCEPT_FLOOR: Offer of RM{offered_price} hits the absolute minimum. Tell buyer: 'This is the lowest I can go, friend! Take it or leave it 😅'"
        else:
            # Counter should be HIGHER than what buyer offered, not lower!
            counter = (offered_price + listed_price) / 2
            # Ensure counter is never below what buyer offered
            counter = max(counter, offered_price + 1)
            result = f"COUNTER: Offer of RM{offered_price} is acceptable but below listed price. Suggest counter-offer of RM{counter:.2f}."
    elif offered_price >= min_price:
        # Offer is between min and adjusted threshold - buyer needs to come up
        # Counter with something between their offer and the listed price
        counter = (offered_price + listed_price) / 2
        # Ensure counter is never below what buyer offered
        counter = max(counter, offered_price + 1)
        result = f"COUNTER: Offer of RM{offered_price} is low but negotiable. Counter with RM{counter:.2f}. You can accept offers above RM{min_price}."
    else:
        result = f"REJECT_FLOOR: Offer of RM{offered_price} is below the absolute minimum of RM{min_price}. Tell buyer: 'Sorry, that's below my cost. The lowest I can do is RM{min_price}.'"
    
    print(f"📋 RESULT: {result}")
    return result



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
    
    print(f"\n{'='*50}")
    print(f"💳 CREATE_CHECKOUT_LINK CALLED")
    print(f"📦 Item ID: {item_id}")
    print(f"💰 Agreed Price: RM{agreed_price}")
    print(f"{'='*50}")
    
    stripe.api_key = STRIPE_API_KEY
    print(f"🔑 Stripe API Key: {'*' * 20}{STRIPE_API_KEY[-4:] if STRIPE_API_KEY else 'NOT SET'}")
    
    # Get item details
    response = user_supabase.table('items').select('*').eq('id', item_id).execute()
    print(f"📊 Item lookup result: {len(response.data) if response.data else 0} items")
    
    if not response.data:
        print(f"❌ Item not found!")
        return "Cannot create checkout - item not found."
    
    item = response.data[0]
    print(f"✅ Item found: {item.get('name')}")
    
    try:
        # Create Stripe Payment Link
        print(f"🔄 Creating Stripe Price...")
        price = stripe.Price.create(
            product_data={"name": item.get('name', 'Item')},
            unit_amount=int(agreed_price * 100),  # Convert to cents
            currency="myr"
        )
        print(f"✅ Price created: {price.id}")
        
        print(f"🔄 Creating Stripe PaymentLink...")
        payment_link = stripe.PaymentLink.create(
            line_items=[{"price": price.id, "quantity": 1}],
            metadata={"item_id": item_id}
        )
        print(f"✅ PaymentLink created: {payment_link.url}")
        
        result = f"SUCCESS: Here's the checkout link for {item.get('name', 'the item')} at RM{agreed_price:.2f}. Use this markdown format when sharing with buyer: [Pay RM{agreed_price:.2f} Now]({payment_link.url})"
        print(f"📋 Returning: {result}")
        return result
    except Exception as e:
        print(f"❌ Error: {str(e)}")
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
tools = [get_item_info, search_items, list_all_items, assess_discount_eligibility, evaluate_offer, create_checkout_link, web_search]

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
            context = f"""SYSTEM: You are negotiating for the following item. IMPORTANT: When using tools like evaluate_offer or create_checkout_link, use the exact item_id provided below.
item_id: {item_id}
Item Name: "{item_details.get('name', 'Unknown Item')}"
Price: RM{item_details.get('price', 'N/A')}
Condition: {item_details.get('condition', 'Unknown')}
Description: {item_details.get('description', 'No description')}

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




