"""
Tests for the document processor service.
"""

import unittest
from unittest.mock import patch, MagicMock, ANY, call
from services.document_processor import DocumentProcessor, SUPPORTED_FILE_TYPES
import logging
import os
import tempfile
import fitz  # PyMuPDF
from datetime import datetime
import sys

# Enable debug logging for tests
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# Disable logging for tests
logging.disable(logging.CRITICAL)

class TestDocumentProcessor(unittest.TestCase):
    """Test cases for DocumentProcessor."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a mock vector store
        self.mock_vector_store = MagicMock()
        self.mock_vector_store.collection = MagicMock()
        
        # Patch the VectorStoreService instance in DocumentProcessor
        self.vector_store_patcher = patch('services.document_processor.VectorStoreService')
        self.mock_vector_store_class = self.vector_store_patcher.start()
        self.mock_vector_store_class.return_value = self.mock_vector_store
        
        # Initialize the processor
        self.processor = DocumentProcessor()
        
        # Verify the vector store was properly initialized
        self.mock_vector_store_class.assert_called_once()
        self.test_file = None
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        # Clean up files
        if self.test_file and os.path.exists(self.test_file):
            try:
                os.remove(self.test_file)
            except PermissionError:
                pass
                
        # Clean up temp directory
        if os.path.exists(self.temp_dir):
            try:
                os.rmdir(self.temp_dir)
            except OSError:
                # Directory not empty, try to remove files first
                import shutil
                shutil.rmtree(self.temp_dir, ignore_errors=True)
                
        # Stop all patches
        self.vector_store_patcher.stop()

    def create_test_file(self, content: str, extension: str = '.txt') -> str:
        """Create a temporary test file."""
        test_file = os.path.join(self.temp_dir, f"test{extension}")
        os.makedirs(os.path.dirname(test_file), exist_ok=True)
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write(content)
        return test_file

    def test_validate_file_success(self):
        """Test successful file validation."""
        test_file = self.create_test_file("Test content")
        with patch('os.path.getsize', return_value=1024), \
             patch('os.path.exists', return_value=True):
            is_valid, error = self.processor.validate_file(test_file)
            self.assertTrue(is_valid)
            self.assertEqual(error, "")

    def test_validate_file_nonexistent(self):
        """Test validation of non-existent file."""
        is_valid, error = self.processor.validate_file("nonexistent.txt")
        self.assertFalse(is_valid)
        self.assertIn("File does not exist", error)

    def test_validate_file_too_large(self):
        """Test validation of too large file."""
        test_file = self.create_test_file("Test content")
        with patch('os.path.getsize', return_value=101 * 1024 * 1024), \
             patch('os.path.exists', return_value=True):
            is_valid, error = self.processor.validate_file(test_file)
            self.assertFalse(is_valid)
            self.assertIn("File is too large", error)

    def test_validate_file_unsupported_type(self):
        """Test validation of unsupported file type."""
        test_file = self.create_test_file("Test content", ".docx")
        is_valid, error = self.processor.validate_file(test_file)
        self.assertFalse(is_valid)
        self.assertIn("Unsupported file type", error)

    @patch('services.document_processor.DocumentProcessor._extract_text_from_txt')
    @patch('os.path.exists', return_value=True)
    @patch('os.path.getsize', return_value=1024)
    def test_process_document_success(self, mock_getsize, mock_exists, mock_extract):
        """Test successful document processing."""
        logger.info("Starting test_process_document_success")
        
        # Setup test content and file
        test_content = "This is a test document. It contains multiple sentences. Each sentence should be split into chunks."
        test_file = self.create_test_file(test_content)
        logger.debug(f"Created test file at: {test_file}")
        
        # Mock text extraction
        mock_extract.return_value = test_content
        logger.debug("Mocked text extraction")
        
        # Mock vector store responses
        doc_id = f"doc_{int(datetime.now().timestamp())}"
        self.mock_vector_store.add_documents.return_value = [doc_id]
        logger.debug(f"Mocked add_documents to return doc_id: {doc_id}")
        
        # Mock collection.get to return document chunks
        def mock_collection_get(where=None):
            logger.debug(f"mock_collection_get called with where={where}")
            if where and 'id' in where:
                result = {
                    'ids': [doc_id],
                    'documents': [test_content],
                    'metadatas': [{'file_name': os.path.basename(test_file), 'file_type': 'txt', 'id': doc_id}]
                }
                logger.debug(f"Returning mock collection data: {result}")
                return result
            empty_result = {'ids': [], 'documents': [], 'metadatas': []}
            logger.debug(f"Returning empty collection data: {empty_result}")
            return empty_result
            
        self.mock_vector_store.collection.get.side_effect = mock_collection_get
        
        # Process the document
        logger.info("Calling process_document")
        success, message = self.processor.process_document(test_file, {"user_id": "test_user"})
        logger.info(f"process_document result: success={success}, message={message}")
        
        # Verify results
        self.assertTrue(success, f"Expected success=True, got {success}")
        self.assertIn("Document processed successfully", message, f"Unexpected message: {message}")
        
        # Verify vector store was called with correct arguments
        logger.info("Verifying vector store calls")
        self.mock_vector_store.add_documents.assert_called_once()
        
        # Get the arguments passed to add_documents
        call_args = self.mock_vector_store.add_documents.call_args
        logger.debug(f"add_documents called with: {call_args}")
        
        # Check documents and metadatas arguments
        self.assertIn('documents', call_args[1], "'documents' not in call args")
        self.assertIn('metadatas', call_args[1], "'metadatas' not in call args")
        
        documents = call_args[1]['documents']
        metadatas = call_args[1]['metadatas']
        
        self.assertGreater(len(documents), 0, "No documents were passed to add_documents")
        self.assertEqual(len(metadatas), len(documents), "Number of metadatas doesn't match number of documents")
        
        # Verify metadata contains expected fields
        for meta in metadatas:
            self.assertIn('file_name', meta, "'file_name' not in metadata")
            self.assertEqual(meta['file_name'], os.path.basename(test_file), 
                           f"Unexpected file_name in metadata: {meta}")
        
        logger.info("All assertions passed")

    @patch('os.path.exists', return_value=True)
    @patch('os.path.getsize', return_value=1024)
    @patch('services.document_processor.DocumentProcessor._extract_text_from_txt')
    def test_process_document_failure(self, mock_extract, mock_getsize, mock_exists):
        """Test document processing failure."""
        test_file = self.create_test_file("Test content")
        mock_extract.return_value = "Test content"
        
        # Test vector store failure
        self.mock_vector_store.add_documents.side_effect = Exception("Test error")
        success, message = self.processor.process_document(test_file, {"user_id": "test_user"})
        self.assertFalse(success)
        self.assertIn("Failed to store document", message)
        
        # Reset side effect
        self.mock_vector_store.add_documents.side_effect = None
        
        # Test with invalid file
        with patch('os.path.exists', return_value=False):
            success, message = self.processor.process_document("nonexistent.txt", {"user_id": "test_user"})
            self.assertFalse(success)
            self.assertIn("File does not exist", message)
            
        # Test with empty content
        mock_extract.return_value = ""
        success, message = self.processor.process_document(test_file, {"user_id": "test_user"})
        self.assertFalse(success)
        self.assertIn("Failed to extract text", message)

    def test_get_document_status(self):
        """Test getting document status."""
        # Mock the vector store response
        self.mock_vector_store.collection.get.return_value = {
            'ids': ['doc1_1', 'doc1_2'],
            'documents': ['chunk1', 'chunk2'],
            'metadatas': [
                {'file_name': 'test.txt', 'file_type': 'txt', 'id': 'doc1'},
                {'file_name': 'test.txt', 'file_type': 'txt', 'id': 'doc1'}
            ]
        }
        
        # Test with valid document
        status = self.processor.get_document_status("doc1")
        self.assertIsNotNone(status)
        self.assertEqual(status['file_name'], 'test.txt')
        self.assertEqual(status['chunk_count'], 2)
        
        # Test with non-existent document
        self.mock_vector_store.collection.get.return_value = {'ids': [], 'documents': [], 'metadatas': []}
        status = self.processor.get_document_status("nonexistent")
        self.assertIsNone(status)

    def test_delete_document(self):
        """Test document deletion."""
        # Mock successful deletion
        with patch.object(self.processor, 'get_document_status', return_value={'id': 'doc1'}):
            success, message = self.processor.delete_document("doc1")
            self.assertTrue(success)
            self.assertIn("Document deleted successfully", message)
            self.mock_vector_store.collection.delete.assert_called_once_with(where={"id": "doc1"})
        
        # Reset mock for next test
        self.mock_vector_store.collection.delete.reset_mock()
        
        # Test document not found
        with patch.object(self.processor, 'get_document_status', return_value=None):
            success, message = self.processor.delete_document("nonexistent")
            self.assertFalse(success)
            self.assertIn("Document not found", message)
            self.mock_vector_store.collection.delete.assert_not_called()

    def test_chunking(self):
        """Test text chunking functionality."""
        # Test with empty string
        self.assertEqual(self.processor._split_text_into_chunks(""), [])
        
        # Test with small text
        small_text = "This is a small text."
        chunks = self.processor._split_text_into_chunks(small_text)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], small_text)
        
        # Test with text larger than chunk size
        large_text = "a " * 1500  # 3000 characters with spaces
        chunks = self.processor._split_text_into_chunks(large_text)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 1000)  # Default chunk size
        
        # Test with text without spaces
        no_spaces = "a" * 1500
        chunks = self.processor._split_text_into_chunks(no_spaces)
        self.assertGreaterEqual(len(chunks), 1)  # At least one chunk
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 1000)  # Each chunk within size limit
        
        # Test with exactly chunk size
        exact_chunk = "a" * 1000
        chunks = self.processor._split_text_into_chunks(exact_chunk)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], exact_chunk)


if __name__ == '__main__':
    unittest.main()
