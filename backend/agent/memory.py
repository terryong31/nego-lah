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
                'SELECT id, role, message, source, created_at FROM conversations WHERE user_id = ? ORDER BY created_at ASC',
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
                    "timestamp": r[4]
                })
            
            admin_supabase.table('conversations').upsert({
                'user_id': user_id,
                'messages': messages,
                'updated_at': 'now()'
            }).execute()
            
        except Exception as e:
            print(f"Error in sync_to_supabase: {e}")

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
