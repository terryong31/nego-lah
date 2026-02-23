import numpy as np
from typing import List, Optional


# Simple embeddings using sentence similarity
# For production, use langchain_google_genai embeddings
class SimpleEmbedding:
    """Simple word-based embeddings for demo. Replace with real embeddings in production."""
    
    def __init__(self, dimension: int = 384):
        self.dimension = dimension
    
    def embed(self, text: str) -> np.ndarray:
        """Create a simple hash-based embedding."""
        # Simple character-level hash for demo
        # In production, use GoogleGenerativeAIEmbeddings
        np.random.seed(hash(text.lower()) % (2**32))
        return np.random.randn(self.dimension).astype('float32')
    
    def embed_batch(self, texts: List[str]) -> np.ndarray:
        return np.array([self.embed(t) for t in texts])


class VectorMemory:
    """Supabase pgvector-based semantic memory for item knowledge and past negotiations."""
    
    VECTOR_DIM = 384
    
    def __init__(self, persist_directory: str = None):
        self.enabled = False
        self.embedder = SimpleEmbedding(self.VECTOR_DIM)
        self._supabase = None

        try:
            from connector import admin_supabase
            self._supabase = admin_supabase
            # Verify connection by checking the table exists
            result = self._supabase.table('vector_memory').select('id').limit(1).execute()
            self.enabled = True
        except Exception as e:
            logger.info(f"VectorMemory disabled: {e}")
            self.enabled = False
            
    def add_item_knowledge(self, item_id: str, description: str):
        """Store item info for semantic search."""
        if not self.enabled:
            return
        doc_id = f"item:{item_id}"
        embedding = self.embedder.embed(description)
        
        try:
            # Upsert to handle duplicates
            self._supabase.table('vector_memory').upsert({
                "id": doc_id,
                "type": "item",
                "item_id": item_id,
                "content": description,
                "embedding": embedding.tolist()
            }).execute()
        except Exception as e:
            logger.info(f"Error adding item knowledge: {e}")
    
    def add_negotiation_summary(self, user_id: str, item_id: str, summary: str):
        """Store a negotiation summary for future reference."""
        if not self.enabled:
            return
        doc_id = f"neg:{user_id}:{item_id}"
        embedding = self.embedder.embed(summary)
        
        try:
            self._supabase.table('vector_memory').upsert({
                "id": doc_id,
                "type": "negotiation",
                "user_id": user_id,
                "item_id": item_id,
                "content": summary,
                "embedding": embedding.tolist()
            }).execute()
        except Exception as e:
            logger.info(f"Error adding negotiation summary: {e}")
    
    def search_similar(self, query: str, n_results: int = 3, filter_type: str = None) -> List[str]:
        """Find relevant items or past negotiations using pgvector similarity search."""
        if not self.enabled:
            return []
        
        query_embedding = self.embedder.embed(query).tolist()
        
        try:
            result = self._supabase.rpc('match_memory', {
                'query_embedding': query_embedding,
                'match_threshold': 0.0,  # Low threshold for simple hash-based embeddings
                'match_count': n_results,
                'filter_type': filter_type
            }).execute()
            
            if result.data:
                return [doc['content'] for doc in result.data]
            return []
        except Exception as e:
            logger.info(f"Error searching: {e}")
            return []
    
    def count(self) -> int:
        """Return number of documents in the vector store."""
        if not self.enabled:
            return 0
        try:
            result = self._supabase.table('vector_memory').select('id', count='exact').execute()
            return result.count or 0
        except:
            return 0
