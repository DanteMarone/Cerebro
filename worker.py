# worker.py

import json
import requests
from PyQt5.QtCore import QObject, pyqtSignal
from transcripts import append_message
from debugger_events import LLMRequestEvent, AgentThoughtEvent, ErrorEvent # Assuming debugger_service is passed

# API Configuration
OLLAMA_API_URL = "http://localhost:11434/api/chat"

class AIWorker(QObject):
    response_received = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, model_name, chat_history, temperature, max_tokens,
                 debug_enabled, agent_name, agents_data, debugger_service=None): # Modified
        super().__init__()
        self.model_name = model_name
        self.chat_history = chat_history
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.debug_enabled = debug_enabled
        self.agent_name = agent_name
        self.agents_data = agents_data  # Store a reference to agents_data
        self.debugger_service = debugger_service # Added
        settings = self.agents_data.get(self.agent_name, {})
        self.thinking_enabled = settings.get("thinking_enabled", False)
        self.thinking_steps = int(settings.get("thinking_steps", 0))

    def run(self):
        try:
            if self.debug_enabled:
                print(f"[Debug] Worker run started for agent '{self.agent_name}'.")

            # Access agent settings using the provided agents_data
            agent_settings = self.agents_data.get(self.agent_name, {})

            if agent_settings.get('role') == 'Specialist':
                # Check if the last message indicates that this specialist should respond
                if not self.chat_history[-1]['content'].endswith(f"Next Response By: {self.agent_name}"):
                    if self.debug_enabled:
                        print(f"[Debug] Specialist '{self.agent_name}' not addressed. Skipping response.")
                    self.finished.emit()
                    return

            if self.thinking_enabled and self.thinking_steps > 0:
                original_prompt = self.chat_history[-1]["content"]
                thoughts = []

                def single_request(history):
                    payload = {
                        "model": self.model_name,
                        "messages": history,
                        "temperature": self.temperature,
                        "max_tokens": self.max_tokens,
                        "stream": False,
                    }
                    resp = requests.post(OLLAMA_API_URL, json=payload, timeout=60)
                    resp.raise_for_status()
                    data = resp.json()
                    return data.get("message", {}).get("content", "")

                for step in range(1, self.thinking_steps + 1):
                    prompt = f"{original_prompt}\nStep {step} of {self.thinking_steps}: think about the task."
                    if thoughts:
                        previous = "\n".join(
                            f"Step {i + 1}: {t}" for i, t in enumerate(thoughts)
                        )
                        prompt += f"\nPrevious steps:\n{previous}"
                    step_history = self.chat_history[:-1] + [
                        {"role": "user", "content": prompt}
                    ]
                    thought = single_request(step_history).strip()
                    thoughts.append(thought)
                    if self.debugger_service:
                        self.debugger_service.record_event(
                            AgentThoughtEvent(
                                agent_name=self.agent_name,
                                thought_step=step,
                                thought_text=thought
                            )
                        )
                    append_message(
                        self.chat_history,
                        "assistant",
                        f"<thought>Step {step}: {thought}</thought>",
                        self.agent_name,
                        debug_enabled=self.debug_enabled,
                    )

                thinking_text = "\n".join(
                    f"Step {i + 1}: {t}" for i, t in enumerate(thoughts)
                )
                final_prompt = (
                    f"{original_prompt}\nHere is your thinking:\n{thinking_text}\n"
                    "Answer the original prompt using this context."
                )
                self.chat_history[-1]["content"] = final_prompt

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
                print("[Debug] Sending request to Ollama API:", json.dumps(payload_copy, indent=2))

            if self.debugger_service:
                self.debugger_service.record_event(
                    LLMRequestEvent(
                        agent_name=self.agent_name,
                        model_name=self.model_name,
                        messages=self.chat_history, # This is the prepared history for the LLM
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                        other_params={"stream": True, "options": payload.get("options")} # Capture relevant other params
                    )
                )

            response = requests.post(OLLAMA_API_URL, json=payload, stream=True)
            response.raise_for_status()  # Raise an exception for bad status codes

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
                        elif line_data.get("done"):
                            if self.debug_enabled:
                                print(f"[Debug] Stream finished for agent '{self.agent_name}'.")
                            break
                    except ValueError as e:
                        error_msg = f"[Error] Failed to parse line as JSON: {e}"
                        if self.debug_enabled:
                            print(error_msg)
                        self.error_occurred.emit(error_msg)
            self.finished.emit()

        except requests.exceptions.RequestException as e:
            error_msg_str = f"Request error: {e}"
            if self.debugger_service:
                self.debugger_service.record_event(
                    ErrorEvent(
                        source="AIWorker.run.RequestException",
                        agent_name=self.agent_name,
                        error_message=error_msg_str,
                        details=str(e) # More detailed exception string
                    )
                )
            error_msg = f"[Error] Request error: {e}" # Keep existing error message format for signal
            if self.debug_enabled:
                print(error_msg)
            self.error_occurred.emit(error_msg)
            self.finished.emit()

        except Exception as e:
            error_msg_str = f"Exception in worker run: {e}"
            if self.debugger_service:
                self.debugger_service.record_event(
                    ErrorEvent(
                        source="AIWorker.run.Exception",
                        agent_name=self.agent_name,
                        error_message=error_msg_str,
                        details=str(e)
                    )
                )
            error_msg = f"[Error] Exception in worker run: {e}" # Keep existing error message format for signal
            if self.debug_enabled:
                print(error_msg)
            self.error_occurred.emit(error_msg)
            self.finished.emit()
