import unittest
from unittest.mock import MagicMock, patch
import os
import shutil
import sys

# Define a proper MockQObject class to avoid MagicMock inheritance issues
class MockQObject:
    def __init__(self, parent=None):
        pass

    def moveToThread(self, thread):
        pass

    def deleteLater(self):
        pass

# Mock PyQt5 before importing orchestrator
mock_pyqt = MagicMock()
mock_pyqt.QObject = MockQObject
mock_pyqt.pyqtSignal = lambda *args: MagicMock()
mock_pyqt.QThread = MagicMock

sys.modules['PyQt5'] = mock_pyqt
sys.modules['PyQt5.QtCore'] = mock_pyqt
sys.modules['PyQt5.QtWidgets'] = mock_pyqt

import chromadb
from chromadb.utils import embedding_functions

from core.memory import VectorStore
import core.orchestrator
from core.orchestrator import Orchestrator

# Mock Embedding Function Class
class MockEmbeddingFunction:
    def __call__(self, input):
        return self.embed_documents(input)

    def embed_documents(self, input):
        return [[0.1] * 384 for _ in input]

    def embed_query(self, input):
        return [[0.1] * 384 for _ in input]

    def name(self):
        return "mock_embedding"

class TestMemoryIntegration(unittest.TestCase):
    def setUp(self):
        self.client_patcher = patch('core.memory.chromadb.PersistentClient')
        self.mock_persistent_client_class = self.client_patcher.start()
        self.mock_persistent_client_class.side_effect = lambda path: chromadb.EphemeralClient()

        self.mock_ef_instance = MockEmbeddingFunction()
        self.vector_store_patcher = patch('core.memory.embedding_functions.SentenceTransformerEmbeddingFunction', return_value=self.mock_ef_instance)
        self.vector_store_patcher.start()

        self.memory = VectorStore(persistence_path="dummy_path")

    def tearDown(self):
        self.vector_store_patcher.stop()
        self.client_patcher.stop()

    def test_save_and_retrieve(self):
        self.memory.save_memory("My favorite color is blue.", {"role": "user"})
        context = self.memory.retrieve_context("What is my favorite color?")
        self.assertIn("Relevant Context:", context)
        self.assertIn("My favorite color is blue.", context)

    @patch('core.orchestrator.VectorStore')
    @patch('core.orchestrator.RouterAgent')
    @patch('core.orchestrator.AIWorker')
    def test_orchestrator_integration(self, MockWorker, MockRouter, MockVectorStore):
        mock_memory_instance = MockVectorStore.return_value
        mock_memory_instance.retrieve_context.return_value = "Relevant Context:\n- Past interaction"

        agents_data = {"TestAgent": {"role": "Assistant", "system_prompt": "You are a test agent."}}
        tools = {}
        tasks = []
        metrics = MagicMock()
        screenshot_provider = MagicMock()

        orchestrator = Orchestrator(agents_data, tools, tasks, metrics, screenshot_provider)

        MockVectorStore.assert_called()

        orchestrator.handle_user_message("Hello world")
        mock_memory_instance.save_memory.assert_called_with("Hello world", {"role": "user", "timestamp": unittest.mock.ANY})

        with patch('core.orchestrator.load_history', return_value=[{"role": "user", "content": "Hello world"}]):
            # Need to mock summarize_history as well since it's called
            with patch('core.orchestrator.summarize_history', side_effect=lambda h, threshold: h):
                history = orchestrator._build_agent_chat_history("TestAgent", agents_data["TestAgent"])

                mock_memory_instance.retrieve_context.assert_called_with("Hello world")
                system_msg = history[0]['content']
                self.assertIn("Relevant Context:", system_msg)
                self.assertIn("- Past interaction", system_msg)

if __name__ == '__main__':
    unittest.main()
