# worker.py

import json
import requests
from debug_logger import log_debug
from PyQt5.QtCore import QObject, pyqtSignal

# API Configuration
OLLAMA_API_URL = "http://localhost:11434/api/chat"

class AIWorker(QObject):
    response_received = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, model_name, chat_history, temperature, max_tokens, debug_enabled, agent_name, agents_data):
        super().__init__()
        self.model_name = model_name
        self.chat_history = chat_history
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.debug_enabled = debug_enabled
        self.agent_name = agent_name
        self.agents_data = agents_data  # Store a reference to agents_data

    def run(self):
        try:
            if self.debug_enabled:
                log_debug(f"Worker run started for agent '{self.agent_name}'", True)

            # Access agent settings using the provided agents_data
            agent_settings = self.agents_data.get(self.agent_name, {})

            if agent_settings.get('role') == 'Specialist':
                # Check if the last message indicates that this specialist should respond
                if not self.chat_history[-1]['content'].endswith(f"Next Response By: {self.agent_name}"):
                    if self.debug_enabled:
                        log_debug(f"Specialist '{self.agent_name}' not addressed. Skipping response.", True)
                    self.finished.emit()
                    return

            payload = {
                "model": self.model_name,
                "messages": self.chat_history,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": True,
                "options": {
                    "stop": [
                        "</s>",
                        "<|im_end|>"
                    ]
                }
            }

            if self.debug_enabled:
                payload_copy = json.loads(json.dumps(payload))
                for message in payload_copy.get('messages', []):
                    if 'images' in message:
                        message['images'] = ['[Image data omitted in debug output]']
                log_debug("Sending request to Ollama API: " + json.dumps(payload_copy, indent=2), True)

            response = requests.post(OLLAMA_API_URL, json=payload, stream=True)
            response.raise_for_status()  # Raise an exception for bad status codes

            for line in response.iter_lines(decode_unicode=True):
                if line:
                    if self.debug_enabled:
                        log_debug(f"Received line: {line}", True)
                    try:
                        line_data = json.loads(line)
                        if "message" in line_data and "content" in line_data["message"]:
                            chunk = line_data["message"]["content"]
                            self.response_received.emit(chunk, self.agent_name)
                        elif "error" in line_data:
                            error_msg = line_data["error"]
                            self.error_occurred.emit(f"[Error] {error_msg}")
                            if self.debug_enabled:
                                log_debug(f"Error in response: {error_msg}", True)
                            break
                        elif line_data.get("done"):
                            if self.debug_enabled:
                                log_debug(f"Stream finished for agent '{self.agent_name}'.", True)
                            break
                    except ValueError as e:
                        error_msg = f"[Error] Failed to parse line as JSON: {e}"
                        if self.debug_enabled:
                            log_debug(error_msg, True)
                        self.error_occurred.emit(error_msg)
            self.finished.emit()

        except requests.exceptions.RequestException as e:
            error_msg = f"[Error] Request error: {e}"
            if self.debug_enabled:
                log_debug(error_msg, True)
            self.error_occurred.emit(error_msg)
            self.finished.emit()

        except Exception as e:
            error_msg = f"[Error] Exception in worker run: {e}"
            if self.debug_enabled:
                log_debug(error_msg, True)
            self.error_occurred.emit(error_msg)
            self.finished.emit()