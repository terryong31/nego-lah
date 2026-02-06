"""
Conversation Memory - Supabase-based storage
No more SQLite! All data goes directly to Supabase.

Table structure (conversations):
- id: uuid
- user_id: text
- item_id: text (optional)
- messages: jsonb array [{role, content, source, timestamp}]
- created_at: timestamp
- updated_at: timestamp
"""

from typing import List, Dict
from datetime import datetime
import json


class ConversationMemory:
    """Supabase-based conversation memory for storing chat history."""
    
    def __init__(self):
        self._supabase = None
    
    @property
    def supabase(self):
        """Lazy load Supabase client."""
        if self._supabase is None:
            from connector import admin_supabase
            self._supabase = admin_supabase
        return self._supabase
    
    def add_message(
        self, 
        user_id: str, 
        role: str, 
        message: str, 
        item_id: str = None, 
        source: str = 'ai'
    ):
        """Save a message to conversation history in Supabase.
        
        Args:
            user_id: User identifier
            role: 'human', 'ai', 'system', 'admin'
            message: The message content
            item_id: Optional item context
            source: 'ai' | 'admin' | 'system' | 'human'
        """
        # Convert list to string if needed
        if isinstance(message, list):
            message = json.dumps(message)
        
        try:
            # Get existing conversation
            result = self.supabase.table('conversations').select('id, messages').eq('user_id', user_id).execute()
            
            new_msg = {
                "role": role,
                "content": message,
                "source": source,
                "item_id": item_id,
                "timestamp": datetime.now().isoformat()
            }
            
            if result.data and len(result.data) > 0:
                # Append to existing messages
                existing = result.data[0]
                messages = existing.get('messages', []) or []
                messages.append(new_msg)
                
                self.supabase.table('conversations').update({
                    'messages': messages,
                    'updated_at': 'now()'
                }).eq('id', existing['id']).execute()
            else:
                # Create new conversation
                self.supabase.table('conversations').insert({
                    'user_id': user_id,
                    'item_id': item_id,
                    'messages': [new_msg]
                }).execute()
                
        except Exception as e:
            print(f"[ConversationMemory] Error saving message: {e}")
    
    def get_history(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get conversation history for a user from Supabase."""
        try:
            result = self.supabase.table('conversations').select('messages').eq('user_id', user_id).execute()
            
            if not result.data or len(result.data) == 0:
                return []
            
            messages = result.data[0].get('messages', []) or []
            
            # Apply pagination (offset from end, return in chronological order)
            if offset > 0:
                messages = messages[:-offset] if offset < len(messages) else []
            if limit:
                messages = messages[-limit:] if len(messages) > limit else messages
            
            # Return in format expected by agent
            return [
                {
                    "role": m.get("role"),
                    "content": m.get("content"),
                    "source": m.get("source", "ai")
                }
                for m in messages
            ]
            
        except Exception as e:
            print(f"[ConversationMemory] Error getting history: {e}")
            return []
    
    def get_all_histories(self) -> Dict[str, List[Dict]]:
        """Get all conversation histories grouped by user_id."""
        try:
            result = self.supabase.table('conversations').select('user_id, messages').execute()
            
            all_histories = {}
            for row in result.data or []:
                user_id = row.get('user_id')
                messages = row.get('messages', []) or []
                
                all_histories[user_id] = [
                    {
                        "role": m.get("role"),
                        "content": m.get("content"),
                        "source": m.get("source", "ai")
                    }
                    for m in messages[-50:]  # Last 50 messages
                ]
            
            return all_histories
            
        except Exception as e:
            print(f"[ConversationMemory] Error getting all histories: {e}")
            return {}
    
    def clear_history(self, user_id: str):
        """Clear conversation history for a user."""
        try:
            self.supabase.table('conversations').delete().eq('user_id', user_id).execute()
        except Exception as e:
            print(f"[ConversationMemory] Error clearing history: {e}")
    
    def broadcast_message(self, user_id: str, role: str, message: str, source: str):
        """Broadcast is handled by Supabase Realtime automatically."""
        pass  # Frontend subscribes to DB changes via Supabase Realtime


# Singleton instance
conversation_memory = ConversationMemory()
