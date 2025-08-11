"""
Vector Store Service for managing embeddings and document storage using ChromaDB.
"""

import chromadb
from typing import List, Dict, Optional
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# Configuration
COLLECTION_NAME = "knowledge_base"


class VectorStoreService:
    def __init__(self):
        """Initialize the vector store service."""
        self.client = None
        self.collection = None
        self._initialize()

    def _initialize(self):
        """Initialize ChromaDB client and collection."""
        try:
            # Initialize ChromaDB client
            self.client = chromadb.PersistentClient(
                path=os.path.join(os.path.dirname(__file__), "..", "data", "chroma")
            )

            # Create or get collection without embedding function
            self.collection = self.client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )

            logger.info("Vector store service initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize vector store: {str(e)}")
            raise

    def add_documents(self, documents: List[str], metadatas: List[Dict]) -> List[str]:
        """
        Add documents to the collection with their embeddings.
        
        Args:
            documents: List of document texts
            metadatas: List of metadata dictionaries
            
        Returns:
            List of IDs for the added documents
        """
        try:
            if not documents or not metadatas:
                raise ValueError("Documents and metadatas must be provided")

            # Generate unique IDs
            ids = [f"doc_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}" for i in range(len(documents))]

            # Add to collection
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )

            logger.info(f"Added {len(documents)} documents to collection")
            return ids

        except Exception as e:
            logger.error(f"Failed to add documents: {str(e)}")
            raise

    def query(self, query: str, n_results: int = 5) -> Dict:
        """
        Perform a semantic search query on the collection.
        
        Args:
            query: Search query text
            n_results: Number of results to return
            
        Returns:
            Dictionary containing query results
        """
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            logger.info(f"Query executed successfully. Found {len(results['documents'][0])} results")
            return results

        except Exception as e:
            logger.error(f"Query failed: {str(e)}")
            raise

    def get_by_id(self, document_id: str) -> Optional[Dict]:
        """
        Retrieve a document by its ID.
        
        Args:
            document_id: ID of the document to retrieve
            
        Returns:
            Dictionary containing document and metadata, or None if not found
        """
        try:
            results = self.collection.get(ids=[document_id])
            if results and results['documents']:
                return {
                    'document': results['documents'][0],
                    'metadata': results['metadatas'][0]
                }
            return None

        except Exception as e:
            logger.error(f"Failed to retrieve document: {str(e)}")
            raise

    def delete(self, document_id: str) -> None:
        """
        Delete a document from the collection.
        
        Args:
            document_id: ID of the document to delete
        """
        try:
            self.collection.delete(ids=[document_id])
            logger.info(f"Document {document_id} deleted successfully")
        except Exception as e:
            logger.error(f"Failed to delete document: {str(e)}")
            raise

    def get_status(self) -> Dict:
        """
        Get the status of the vector store.
        
        Returns:
            Dictionary containing vector store status information
        """
        try:
            collection_info = self.collection.get() if self.collection else None
            return {
                'status': 'healthy' if self.client else 'uninitialized',
                'collection_name': COLLECTION_NAME,
                'document_count': len(collection_info['documents']) if collection_info else 0,
                'last_updated': datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to get status: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }

    def list_documents(self) -> List[Dict]:
        """Return a list of unique documents with basic metadata and chunk counts."""
        try:
            data = self.collection.get()
            metadatas = data.get('metadatas', []) or []

            # Group by logical document id stored in metadata key 'id'
            docs: Dict[str, Dict] = {}
            for meta in metadatas:
                doc_id = meta.get('id')
                if not doc_id:
                    # Fallback: use filename if no id present
                    doc_id = meta.get('file_name') or "unknown"
                entry = docs.setdefault(doc_id, {
                    'id': doc_id,
                    'file_name': meta.get('file_name', ''),
                    'file_type': meta.get('file_type', ''),
                    'processed_at': meta.get('processed_at', ''),
                    'chunk_count': 0,
                })
                entry['chunk_count'] += 1

            return list(docs.values())
        except Exception as e:
            logger.error(f"Failed to list documents: {str(e)}")
            return []

# Initialize service
vector_store_service = VectorStoreService()
