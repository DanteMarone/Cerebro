import unittest
from unittest.mock import patch, MagicMock
from services.vector_store_service import VectorStoreService
import logging
import os

# Disable logging for tests
logging.disable(logging.CRITICAL)

class TestVectorStoreService(unittest.TestCase):
    def setUp(self):
        self.service = VectorStoreService()
        self.test_docs = [
            "This is a test document",
            "Another test document with different content"
        ]
        self.test_metas = [
            {"id": "doc1", "timestamp": "2025-05-12"},
            {"id": "doc2", "timestamp": "2025-05-12"}
        ]

    def test_add_documents(self):
        """Test adding documents to the collection."""
        result = self.service.add_documents(self.test_docs, self.test_metas)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)

    def test_get_by_id(self):
        """Test retrieving a document by ID."""
        # Add documents
        ids = self.service.add_documents(self.test_docs, self.test_metas)
        
        # Get first document
        doc = self.service.get_by_id(ids[0])
        self.assertIsNotNone(doc)
        self.assertIn('document', doc)
        self.assertIn('metadata', doc)

    def test_delete(self):
        """Test deleting a document."""
        # Add documents
        ids = self.service.add_documents(self.test_docs, self.test_metas)
        
        # Delete first document
        self.service.delete(ids[0])
        
        # Verify deletion
        doc = self.service.get_by_id(ids[0])
        self.assertIsNone(doc)

    def test_get_status(self):
        """Test getting vector store status."""
        status = self.service.get_status()
        self.assertIn('status', status)
        self.assertIn('collection_name', status)
        self.assertIn('document_count', status)

    @patch('chromadb.PersistentClient')
    def test_initialize_failure(self, mock_client):
        """Test initialization failure."""
        mock_client.side_effect = Exception("Mock initialization error")
        with self.assertRaises(Exception):
            VectorStoreService()

if __name__ == '__main__':
    unittest.main()
