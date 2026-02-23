from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from env import GEMINI_API_KEY
from ..tools.items import get_item_info, search_items, list_all_items

# Initialize the model
model = ChatGoogleGenerativeAI(
    model="gemini-3-flash-preview",
    temperature=0.3, # Low temperature for factual retrieval
    google_api_key=GEMINI_API_KEY
)

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
    model, 
    tools=[get_item_info, search_items, list_all_items], 
    prompt=ITEM_AGENT_PROMPT
)

# Allow more steps for retry logic
item_agent = item_agent_graph.with_config({"recursion_limit": 10})
