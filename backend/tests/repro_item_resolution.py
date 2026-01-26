
import sys
import os
from unittest.mock import MagicMock

# Add backend to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock Stripe Agent BEFORE importing bot
# We need to mock it in the module where it is used.
# Since we will import agent.bot, we can patch it after import or mock the module.

from langchain_core.messages import AIMessage

# Mock the stripe_agent invoke method to avoid real calls
mock_stripe_agent = MagicMock()
mock_stripe_agent.invoke.return_value = {"messages": [AIMessage(content="Payment link created (MOCKED)")]}

import agent.bot
from agent.bot import call_stripe_agent, conversation_memory, create_checkout_link

# Replace the real stripe_agent in bot module with our mock
agent.bot.stripe_agent = mock_stripe_agent

def test_item_resolution():
    print("🚀 Starting Item Resolution Test")
    
    # 1. Setup Context
    user_id = "test_user_resolution_1"
    item_id = "2c2cf0ca-5b01-4293-9a65-68a65cbe45c8" # "Some Dices"
    
    # Clear any existing memory for this user (if any) - though simpler to just use unique user_id
    
    # Add conversation history about "Some Dices"
    print(f"📝 Seeding conversation history for user {user_id}...")
    conversation_memory.add_message(user_id, "human", "Do you have any dices?", source="human")
    conversation_memory.add_message(user_id, "ai", "Yes, we have 'Some Dices' available for RM888.", item_id)
    conversation_memory.add_message(user_id, "human", "Can I get a discount?", source="human")
    conversation_memory.add_message(user_id, "ai", "I can offer it for RM800.", item_id)
    conversation_memory.add_message(user_id, "human", "Okay, deal. Please create a checkout link.", source="human")
    
    # 2. Simulate the Agent calling the tool WITHOUT item_id
    # Ensure tool context is CLEARED or set to None
    create_checkout_link._current_user_id = user_id
    create_checkout_link._current_item_id = None # simulating missing context
    
    # Also need to set _current_user_id on call_stripe_agent if it uses it?
    # No, call_stripe_agent uses create_checkout_link to CHECK context.
    # But wait, call_stripe_agent itself doesn't take user_id as arg, it takes 'request'.
    # Does it use `create_checkout_link._current_user_id`?
    # My implementation:
    # current_user_id = getattr(create_checkout_link, '_current_user_id', None)
    # YES.
    
    # 3. Call call_stripe_agent
    print("📞 Calling call_stripe_agent with missing item_id...")
    request = "Create checkout link for agreed price RM800"
    
    try:
        response = call_stripe_agent.invoke(request)
        print(f"🤖 Response: {response}")
        
        # 4. Verify Resolution
        resolved_id = getattr(create_checkout_link, '_current_item_id', None)
        print(f"🧐 Resolved Item ID: {resolved_id}")
        
        if resolved_id == item_id:
            print("✅ TEST PASSED: Item ID was correctly resolved from history!")
        else:
            print(f"❌ TEST FAILED: Expected {item_id}, got {resolved_id}")
            
    except Exception as e:
        print(f"❌ TEST FAILED with Exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_item_resolution()
