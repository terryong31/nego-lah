import os
from typing import List
import faiss
import numpy as np
import json

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
    """FAISS-based semantic memory for item knowledge and past negotiations."""
    
    def __init__(self, persist_directory: str = "./faiss_db"):
        self.persist_directory = persist_directory
        self.dimension = 384
        self.embedder = SimpleEmbedding(self.dimension)
        
        # Create directory if it doesn't exist
        os.makedirs(persist_directory, exist_ok=True)
        
        self.index_path = os.path.join(persist_directory, "index.faiss")
        self.metadata_path = os.path.join(persist_directory, "metadata.json")
        
        # Load or create index
        if os.path.exists(self.index_path):
            self.index = faiss.read_index(self.index_path)
            with open(self.metadata_path, 'r') as f:
                self.metadata = json.load(f)
        else:
            self.index = faiss.IndexFlatL2(self.dimension)
            self.metadata = {"documents": [], "ids": [], "meta": []}
    
    def _save(self):
        """Persist index and metadata to disk."""
        faiss.write_index(self.index, self.index_path)
        with open(self.metadata_path, 'w') as f:
            json.dump(self.metadata, f)
    
    def add_item_knowledge(self, item_id: str, description: str):
        """Store item info for semantic search."""
        doc_id = f"item_{item_id}"
        
        # Check if already exists
        if doc_id in self.metadata["ids"]:
            idx = self.metadata["ids"].index(doc_id)
            self.metadata["documents"][idx] = description
            self.metadata["meta"][idx] = {"type": "item", "item_id": item_id}
        else:
            # Add new
            embedding = self.embedder.embed(description).reshape(1, -1)
            self.index.add(embedding)
            self.metadata["documents"].append(description)
            self.metadata["ids"].append(doc_id)
            self.metadata["meta"].append({"type": "item", "item_id": item_id})
        
        self._save()
    
    def add_negotiation_summary(self, user_id: str, item_id: str, summary: str):
        """Store a negotiation summary for future reference."""
        doc_id = f"negotiation_{user_id}_{item_id}"
        
        if doc_id in self.metadata["ids"]:
            idx = self.metadata["ids"].index(doc_id)
            self.metadata["documents"][idx] = summary
            self.metadata["meta"][idx] = {"type": "negotiation", "user_id": user_id, "item_id": item_id}
        else:
            embedding = self.embedder.embed(summary).reshape(1, -1)
            self.index.add(embedding)
            self.metadata["documents"].append(summary)
            self.metadata["ids"].append(doc_id)
            self.metadata["meta"].append({"type": "negotiation", "user_id": user_id, "item_id": item_id})
        
        self._save()
    
    def search_similar(self, query: str, n_results: int = 3) -> List[str]:
        """Find relevant items or past negotiations."""
        if self.index.ntotal == 0:
            return []
        
        query_embedding = self.embedder.embed(query).reshape(1, -1)
        k = min(n_results, self.index.ntotal)
        distances, indices = self.index.search(query_embedding, k)
        
        results = []
        for idx in indices[0]:
            if idx < len(self.metadata["documents"]):
                results.append(self.metadata["documents"][idx])
        
        return results
    
    def count(self) -> int:
        """Return number of documents in the index."""
        return self.index.ntotal
