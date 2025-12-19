import os
import pytest
from unittest.mock import MagicMock, patch
import sys

# Mock PyQt5 before importing worker which inherits from QObject
sys.modules["PyQt5"] = MagicMock()
sys.modules["PyQt5.QtCore"] = MagicMock()


# Mock QObject for AIWorker inheritance
class MockQObject:
    def __init__(self, parent=None):
        pass


sys.modules["PyQt5.QtCore"].QObject = MockQObject
sys.modules["PyQt5.QtCore"].pyqtSignal = MagicMock()

from worker import AIWorker  # noqa: E402

# Mock data
AGENTS_DATA_GEMINI = {
    "Gemini Agent": {
        "model": "gemini/gemini-1.5-flash",
        "provider": "gemini",
        "api_key_env": "GEMINI_API_KEY",
        "temperature": 0.7,
        "max_tokens": 100,
        "role": "Assistant"
    }
}

AGENTS_DATA_OLLAMA = {
    "Ollama Agent": {
        "model": "llama3",
        "provider": "ollama",
        "temperature": 0.7,
        "max_tokens": 100,
        "role": "Assistant"
    }
}


@pytest.fixture
def mock_worker_gemini():
    return AIWorker(
        model_name="gemini/gemini-1.5-flash",
        chat_history=[{"role": "user", "content": "Hello"}],
        temperature=0.7,
        max_tokens=100,
        debug_enabled=True,
        agent_name="Gemini Agent",
        agents_data=AGENTS_DATA_GEMINI
    )


@pytest.fixture
def mock_worker_ollama():
    return AIWorker(
        model_name="llama3",
        chat_history=[{"role": "user", "content": "Hello"}],
        temperature=0.7,
        max_tokens=100,
        debug_enabled=True,
        agent_name="Ollama Agent",
        agents_data=AGENTS_DATA_OLLAMA
    )


def test_gemini_provider_call(mock_worker_gemini):
    with patch("worker.litellm.completion") as mock_completion, \
         patch("worker.keyring.get_password", return_value="fake_key"):

        # Mock streaming response
        mock_chunk = MagicMock()
        mock_chunk.choices = [MagicMock()]
        mock_chunk.choices[0].delta.content = "Hello world"
        mock_completion.return_value = [mock_chunk]

        # Run generator
        response = list(mock_worker_gemini.generate_response(mock_worker_gemini.chat_history, stream=True))

        assert response == ["Hello world"]
        mock_completion.assert_called_once()
        args, kwargs = mock_completion.call_args
        assert kwargs["model"] == "gemini/gemini-1.5-flash"
        assert kwargs["api_key"] == "fake_key"
        assert kwargs["stream"] is True


def test_gemini_missing_key(mock_worker_gemini):
    with patch("worker.keyring.get_password", return_value=None), \
         patch.dict(os.environ, {}, clear=True):

        with pytest.raises(ValueError, match="Missing API key"):
            list(mock_worker_gemini.generate_response(mock_worker_gemini.chat_history, stream=True))


def test_ollama_provider_call(mock_worker_ollama):
    with patch("worker.requests.post") as mock_post:
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [
            b'{"message": {"content": "Ollama response"}}',
            b'{"done": true}'
        ]
        mock_post.return_value = mock_response

        response = list(mock_worker_ollama.generate_response(mock_worker_ollama.chat_history, stream=True))

        assert response == ["Ollama response"]
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["model"] == "llama3"
