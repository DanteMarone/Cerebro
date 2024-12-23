import json
import requests
from PyQt5.QtCore import QObject, pyqtSignal

# API Configuration
OLLAMA_API_URL = "http://localhost:11434/api/chat"

class AIWorker(QObject):
    response_received = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, model_name, chat_history, temperature, max_tokens, debug_enabled, agent_name):
        super().__init__()
        self.model_name = model_name
        self.chat_history = chat_history
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.debug_enabled = debug_enabled
        self.agent_name = agent_name

    def run(self):
        try:
            if self.debug_enabled:
                print(f"[Debug] Worker run started for agent '{self.agent_name}'.")
            payload = {
                "model": self.model_name,
                "messages": self.chat_history,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens
            }

            if self.debug_enabled:
                payload_copy = json.loads(json.dumps(payload))
                for message in payload_copy.get('messages', []):
                    if 'images' in message:
                        message['images'] = ['[Image data omitted in debug output]']
                print("[Debug] Sending request to Ollama API:", json.dumps(payload_copy, indent=2))

            response = requests.post(OLLAMA_API_URL, json=payload, stream=True)
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if line:
                    if self.debug_enabled:
                        print(f"[Debug] Received line: {line}")
                    try:
                        line_data = json.loads(line)
                        if "message" in line_data and "content" in line_data["message"]:
                            chunk = line_data["message"]["content"]
                            self.response_received.emit(chunk, self.agent_name)
                        elif "error" in line_data:
                            error_msg = line_data["error"]
                            self.error_occurred.emit(f"[Error] {error_msg}")
                            if self.debug_enabled:
                                print(f"[Debug] Error in response: {error_msg}")
                            break
                    except ValueError as e:
                        error_msg = f"[Error] Failed to parse line as JSON: {e}"
                        if self.debug_enabled:
                            print(error_msg)
                        self.error_occurred.emit(error_msg)
            self.finished.emit()
        except Exception as e:
            error_msg = f"[Error] Exception in worker run: {e}"
            if self.debug_enabled:
                print(error_msg)
            self.error_occurred.emit(error_msg)
            self.finished.emit()
