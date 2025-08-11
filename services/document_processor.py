"""
Service for processing and managing documents in the knowledge base.
"""

import os
import fitz  # PyMuPDF for PDF processing
import re
from typing import Dict, List, Optional, Tuple
import logging
from pathlib import Path
import tempfile
from datetime import datetime

from services.vector_store_service import VectorStoreService

# Optional token-aware chunking
try:
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    tiktoken = None

logger = logging.getLogger(__name__)

# Configuration
SUPPORTED_FILE_TYPES = ['.pdf', '.txt']
DEFAULT_CHUNK_SIZE = 1000  # characters
DEFAULT_CHUNK_OVERLAP = 100  # characters
DEFAULT_TOKEN_CHUNK_SIZE = 1000
DEFAULT_TOKEN_CHUNK_OVERLAP = 100


class DocumentProcessor:
    def __init__(self):
        """Initialize the document processor."""
        self.vector_store = VectorStoreService()
        self._initialize()

    def _initialize(self):
        """Initialize any required resources."""
        try:
            # Ensure data directory exists
            os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data", "documents"), exist_ok=True)
            logger.info("Document processor initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize document processor: {str(e)}")
            raise

    def validate_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Validate if a file is supported.
        
        Args:
            file_path: Path to the file to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                return False, "File does not exist"

            # Check file size
            if os.path.getsize(file_path) > 100 * 1024 * 1024:  # 100MB limit
                return False, "File is too large (max 100MB)"

            # Check file extension
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext not in SUPPORTED_FILE_TYPES:
                return False, f"Unsupported file type. Supported types: {', '.join(SUPPORTED_FILE_TYPES)}"

            return True, ""

        except Exception as e:
            logger.error(f"File validation failed: {str(e)}")
            return False, f"Error validating file: {str(e)}"

    def process_document(self, file_path: str, metadata: Dict) -> Tuple[bool, str]:
        """
        Process a document and store it in the vector store.
        
        Args:
            file_path: Path to the document file
            metadata: Additional metadata to store with the document
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Validate file
            is_valid, error = self.validate_file(file_path)
            if not is_valid:
                return False, error

            # Generate unique document ID
            doc_id = f"doc_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            # Extract text based on file type
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext == '.pdf':
                text = self._extract_text_from_pdf(file_path)
            else:  # .txt
                text = self._extract_text_from_txt(file_path)

            if not text:
                return False, "Failed to extract text from document"

            # Split into chunks (token-aware if available)
            chunks = self._split_text(text)
            if not chunks:
                return False, "Failed to split text into chunks"

            # Prepare metadata
            base_metadata = {
                "id": doc_id,
                "file_name": os.path.basename(file_path),
                "file_type": file_ext[1:],
                "processed_at": datetime.now().isoformat(),
                **metadata
            }

            # Store in vector store
            try:
                ids = self.vector_store.add_documents(
                    documents=chunks,
                    metadatas=[base_metadata | {"chunk_index": i} for i in range(len(chunks))]
                )
                logger.info(f"Processed document {file_path} successfully. Added {len(chunks)} chunks")
                return True, f"Document processed successfully. Added {len(chunks)} chunks"
            except Exception as e:
                logger.error(f"Failed to store document in vector store: {str(e)}")
                return False, f"Failed to store document: {str(e)}"

        except Exception as e:
            logger.error(f"Document processing failed: {str(e)}")
            return False, f"Error processing document: {str(e)}"

    def _extract_text_from_pdf(self, file_path: str) -> str:
        """Extract text from a PDF file."""
        try:
            document = fitz.open(file_path)
            text = ""
            for page_num in range(len(document)):
                page = document.load_page(page_num)
                text += page.get_text()
            document.close()
            return text
        except Exception as e:
            logger.error(f"Failed to extract text from PDF: {str(e)}")
            raise

    def _extract_text_from_txt(self, file_path: str) -> str:
        """Extract text from a text file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read text file: {str(e)}")
            raise

    def _split_text(self, text: str) -> List[str]:
        """Split text by tokens if tiktoken is available, else fallback to char-based."""
        if not text:
            return []
        if tiktoken is None:
            return self._split_text_into_chunks(text)
        try:
            encoding = tiktoken.get_encoding("cl100k_base")
            tokens = encoding.encode(text)
            size = DEFAULT_TOKEN_CHUNK_SIZE
            overlap = DEFAULT_TOKEN_CHUNK_OVERLAP
            chunks: List[str] = []
            start = 0
            while start < len(tokens):
                end = min(start + size, len(tokens))
                chunk_text = encoding.decode(tokens[start:end]).strip()
                if chunk_text:
                    chunks.append(chunk_text)
                if end >= len(tokens):
                    break
                start = max(end - overlap, 0)
            return chunks
        except Exception:
            # Fallback to char-based splitting on any error
            return self._split_text_into_chunks(text)

    def _split_text_into_chunks(self, text: str) -> List[str]:
        """
        Split text into chunks with overlap.
        
        Args:
            text: Input text to split
            
        Returns:
            List of text chunks
        """
        if not text:
            return []
            
        chunks = []
        start = 0
        text_length = len(text)
        
        while start < text_length:
            # Find end of chunk
            end = min(start + DEFAULT_CHUNK_SIZE, text_length)
            
            # If we're at the end, add the last chunk and break
            if end >= text_length:
                chunk = text[start:].strip()
                if chunk:
                    chunks.append(chunk)
                break
                
            # Find the last space before the chunk end
            split_point = text.rfind(' ', start, end)
            
            # If no space found, split at the chunk size
            if split_point == -1 or split_point <= start:
                split_point = end
            
            # Add chunk
            chunk = text[start:split_point].strip()
            if chunk:  # Only add non-empty chunks
                chunks.append(chunk)
            
            # Move start to next chunk with overlap
            start = split_point
            
            # If we're not at the end, move back for overlap
            if start < text_length:
                overlap_start = max(start - DEFAULT_CHUNK_OVERLAP, 0)
                if overlap_start < start:  # Only if we can actually overlap
                    start = overlap_start
        
        return chunks

    def get_document_status(self, document_id: str) -> Optional[Dict]:
        """
        Get the status of a processed document.
        
        Args:
            document_id: ID of the document to get status for
            
        Returns:
            Dictionary containing document status, or None if not found
        """
        try:
            # Get all chunks with the matching document ID
            results = self.vector_store.collection.get(
                where={"id": document_id}
            )
            
            if not results or not results.get('documents'):
                return None

            # Get metadata from first chunk
            metadata = results['metadatas'][0] if results.get('metadatas') else {}
            return {
                'id': document_id,
                'file_name': metadata.get('file_name', ''),
                'file_type': metadata.get('file_type', ''),
                'processed_at': metadata.get('processed_at', ''),
                'chunk_count': len(results.get('documents', []))
            }

        except Exception as e:
            logger.error(f"Failed to get document status: {str(e)}")
            return None

    def _count_document_chunks(self, document_id: str) -> int:
        """Count the number of chunks for a document."""
        try:
            # Get first chunk to get metadata
            result = self.vector_store.get_by_id(document_id)
            if not result:
                return 0

            # Get all chunks with the same file name
            metadata = result['metadata']
            file_name = metadata.get('file_name', '')
            if not file_name:
                return 0

            # Count chunks with the same file name
            return len(self.vector_store.collection.get(
                where={"file_name": file_name}
            )['documents'])

        except Exception as e:
            logger.error(f"Failed to count document chunks: {str(e)}")
            return 0

    def delete_document(self, document_id: str) -> Tuple[bool, str]:
        """
        Delete a document and all its chunks from the vector store.
        
        Args:
            document_id: ID of the document to delete
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # First check if document exists
            status = self.get_document_status(document_id)
            if not status:
                return False, "Document not found"
            
            # Delete all chunks with this document ID
            self.vector_store.collection.delete(
                where={"id": document_id}
            )
            
            logger.info(f"Deleted document {document_id} successfully")
            return True, "Document deleted successfully"

        except Exception as e:
            logger.error(f"Failed to delete document: {str(e)}")
            return False, f"Error deleting document: {str(e)}"

# Initialize service
document_processor = DocumentProcessor()
