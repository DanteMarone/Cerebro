import chromadb
from chromadb.utils import embedding_functions
import os
import uuid

class VectorStore:
    def __init__(self, persistence_path="cerebro_memory"):
        self.client = chromadb.PersistentClient(path=persistence_path)

        # Use a local embedding model
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

        self.collection = self.client.get_or_create_collection(
            name="cerebro_context",
            embedding_function=self.embedding_fn
        )

    def save_memory(self, text, metadata=None):
        """
        Embeds and stores user facts/preferences.
        """
        if not text or not isinstance(text, str):
            return

        if metadata is None:
            metadata = {}

        # Ensure metadata values are strings, ints, floats, or bools (ChromaDB requirement)
        # We'll just ensure timestamp is present if not provided
        if "timestamp" not in metadata:
            import datetime
            metadata["timestamp"] = datetime.datetime.now().isoformat()

        self.collection.add(
            documents=[text],
            metadatas=[metadata],
            ids=[str(uuid.uuid4())]
        )

    def retrieve_context(self, query, k=3):
        """
        Fetches relevant past interactions.
        """
        if not query:
            return ""

        results = self.collection.query(
            query_texts=[query],
            n_results=k
        )

        # Format results
        # results['documents'] is a list of lists (one list per query)
        if not results['documents'] or not results['documents'][0]:
            return ""

        context_strings = results['documents'][0]
        formatted_context = "Relevant Context:\n" + "\n- ".join(context_strings)
        return formatted_context
