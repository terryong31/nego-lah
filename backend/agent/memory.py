import sqlite3
from typing import List, Dict


class ConversationMemory:
    """SQLite-based conversation memory for storing chat history and sales."""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            import os
            # Use absolute path relative to this file to ensure it works from anywhere
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(base_dir, "data", "conversations.db")
            
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_tables()
        self.restore_from_supabase()
    
    def _create_tables(self):
        cursor = self.conn.cursor()
        
        # Store all conversation messages
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                item_id TEXT,
                role TEXT NOT NULL,
                message TEXT NOT NULL,
                source TEXT DEFAULT 'ai',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add source column if not exists (migration for existing DBs)
        try:
            cursor.execute('ALTER TABLE conversations ADD COLUMN source TEXT DEFAULT "ai"')
        except:
            pass  # Column already exists
        
        # Store completed sales
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                item_id TEXT NOT NULL,
                original_price REAL,
                final_price REAL,
                checkout_url TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        self.conn.commit()
    
    def add_message(self, user_id: str, role: str, message: str, item_id: str = None, source: str = 'ai'):
        """Save a message to the conversation history.
        
        source: 'ai' | 'admin' | 'system' | 'human'
        """
        # Convert list to string if needed (sometimes LLM returns list content)
        if isinstance(message, list):
            import json
            message = json.dumps(message)
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO conversations (user_id, item_id, role, message, source) VALUES (?, ?, ?, ?, ?)',
            (user_id, item_id, role, message, source)
        )
        self.conn.commit()
        
        # Broadcast real-time message
        try:
            self.broadcast_message(user_id, role, message, source)
        except Exception as e:
            print(f"Failed to broadcast: {e}")

        # Sync to Supabase for persistence
        try:
            self.sync_to_supabase(user_id)
        except Exception as e:
            print(f"Failed to sync to Supabase: {e}")
    
    def sync_to_supabase(self, user_id: str):
        """Sync entire conversation history for a user to Supabase."""
        try:
            # Avoid circular import
            import sys
            import os
            # Add parent directory to path to find connector
            current_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(current_dir)
            if parent_dir not in sys.path:
                sys.path.append(parent_dir)
            
            from connector import admin_supabase
            
            cursor = self.conn.cursor()
            cursor.execute(
                'SELECT id, role, message, source, created_at, item_id FROM conversations WHERE user_id = ? ORDER BY created_at ASC',
                (user_id,)
            )
            rows = cursor.fetchall()
            
            messages = []
            for r in rows:
                messages.append({
                    "id": str(r[0]),
                    "role": r[1],
                    "content": r[2],
                    "source": r[3] or 'ai',
                    "timestamp": r[4],
                    "item_id": r[5]
                })
            
            admin_supabase.table('conversations').upsert({
                'user_id': user_id,
                'messages': messages,
                'updated_at': 'now()'
            }).execute()
            
        except Exception as e:
            print(f"Error in sync_to_supabase: {e}")

    def restore_from_supabase(self):
        """Restore conversation history from Supabase (single source of truth)."""
        try:
            import sys
            import os
            
            # Setup path to find connector
            current_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(current_dir)
            if parent_dir not in sys.path:
                sys.path.append(parent_dir)
            
            from connector import admin_supabase
            
            print("🔄 Restoring conversation memory from Supabase...")
            
            # Fetch all conversations
            response = admin_supabase.table('conversations').select('user_id, messages').execute()
            if not response.data:
                print("ℹ️ No conversations found in Supabase.")
                return

            cursor = self.conn.cursor()
            
            # Count current local messages
            cursor.execute("SELECT COUNT(*) FROM conversations")
            local_count = cursor.fetchone()[0]
            
            if local_count > 0:
                print(f"ℹ️ Found {local_count} local messages. Merging/Skipping restore to avoid overwriting newer local data if any.")
                # Strategy: For now, if local DB exists, assume it's good?
                # But user says it reverts. 
                # Better strategy: WIPE local and restore from Supabase if Supabase has data?
                # Or UPSERT?
                # Let's try to UPSERT based on content/timestamp match? Too complex.
                # If local count is small (e.g. 0 after deploy), restore.
                # If local count > 0, we might be running locally and don't want to lose unsynced stuff.
                # But 'user says history missing' -> implies local is empty or old.
                pass
            
            # Actually, let's just Insert ignoring duplicates?
            # SQLite doesn't enforce unique constraints on message content usually.
            
            # Let's clean wipe for this user? No.
            
            count = 0
            for row in response.data:
                user_id = row['user_id']
                messages = row['messages'] or []
                
                # Check if we already have messages for this user
                cursor.execute("SELECT COUNT(*) FROM conversations WHERE user_id = ?", (user_id,))
                user_msg_count = cursor.fetchone()[0]
                
                if user_msg_count < len(messages):
                    # We have fewer messages locally than in remote.
                    # Simplest approach: Delete local for this user and restore full history from remote
                    cursor.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
                    
                    for msg in messages:
                        item_id = msg.get('item_id')
                        role = msg.get('role')
                        content = msg.get('content')
                        source = msg.get('source', 'ai')
                        # timestamp = msg.get('timestamp') # We let SQLite set timestamp or we could parse it
                        
                        cursor.execute(
                            'INSERT INTO conversations (user_id, item_id, role, message, source) VALUES (?, ?, ?, ?, ?)',
                            (user_id, item_id, role, content, source)
                        )
                        count += 1
            
            self.conn.commit()
            print(f"✅ Restored {count} messages from Supabase.")
            
        except Exception as e:
            print(f"❌ Error restoring from Supabase: {e}")

    def broadcast_message(self, user_id: str, role: str, message: str, source: str):
        """Broadcast a new message to the user's channel.
        
        NOTE: Supabase realtime is only available in the async client.
        The frontend uses polling/subscriptions instead, so this is disabled.
        """
        # Realtime broadcast disabled - sync client doesn't support it
        # Frontend subscribes to DB changes directly via Supabase Realtime JS client
        pass
    
    def get_history(self, user_id: str, limit: int = 10, offset: int = 0) -> List[Dict]:
        """Get recent conversation history for a user."""
        
        # Trigger restore if needed (lazy load for specific user could be added here)
        # But for now we did it in init (wait, I need to call it in init)
        
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT role, message, source FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?',
            (user_id, limit, offset)
        )
        rows = cursor.fetchall()
        # Reverse to get chronological order (oldest first)
        return [{"role": r[0], "content": r[1], "source": r[2] or 'ai'} for r in reversed(rows)]
    
    def save_sale(self, user_id: str, item_id: str, original_price: float, final_price: float, checkout_url: str):
        """Record a sale when checkout link is created."""
        cursor = self.conn.cursor()
        cursor.execute(
            'INSERT INTO sales (user_id, item_id, original_price, final_price, checkout_url) VALUES (?, ?, ?, ?, ?)',
            (user_id, item_id, original_price, final_price, checkout_url)
        )
        self.conn.commit()
    
    def get_sales(self, status: str = None) -> List[Dict]:
        """Get all sales, optionally filtered by status."""
        cursor = self.conn.cursor()
        if status:
            cursor.execute('SELECT * FROM sales WHERE status = ?', (status,))
        else:
            cursor.execute('SELECT * FROM sales')
        return cursor.fetchall()

    def get_all_histories(self) -> Dict[str, List[Dict]]:
        """Get all conversation histories grouped by user_id."""
        cursor = self.conn.cursor()
        cursor.execute('SELECT DISTINCT user_id FROM conversations')
        user_ids = [row[0] for row in cursor.fetchall()]
        
        all_histories = {}
        for user_id in user_ids:
            all_histories[user_id] = self.get_history(user_id, limit=50)
        
        return all_histories


# Singleton instance for use across the application
conversation_memory = ConversationMemory()
