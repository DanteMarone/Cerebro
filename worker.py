# worker.py

import json
import requests
import logging
import os
import keyring
import litellm
from PyQt5.QtCore import QObject, pyqtSignal
from transcripts import append_message

# API Configuration
OLLAMA_API_URL = "http://localhost:11434/api/chat"

class AIWorker(QObject):
    response_received = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, model_name, chat_history, temperature, max_tokens,
                 debug_enabled, agent_name, agents_data, api_url=OLLAMA_API_URL, json_format=None):
        super().__init__()
        self.model_name = model_name
        self.chat_history = chat_history
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.debug_enabled = debug_enabled
        self.agent_name = agent_name
        self.agents_data = agents_data  # Store a reference to agents_data
        self.api_url = api_url
        self.json_format = json_format
        settings = self.agents_data.get(self.agent_name, {})
        self.thinking_enabled = settings.get("thinking_enabled", False)
        self.thinking_steps = int(settings.get("thinking_steps", 0))

    def generate_response(self, messages, stream=True):
        """
        Unified method to generate responses from different providers.
        Returns a generator yielding content chunks (if stream=True) or a single string (if stream=False).
        """
        agent_settings = self.agents_data.get(self.agent_name, {})
        provider = agent_settings.get("provider", "ollama")

        if provider == "gemini":
            return self._generate_gemini(agent_settings, messages, stream)
        else:
            return self._generate_ollama(agent_settings, messages, stream)

    def _generate_gemini(self, agent_settings, messages, stream):
        api_key_env = agent_settings.get("api_key_env", "GEMINI_API_KEY")
        # Try env var first, then keyring
        api_key = os.environ.get(api_key_env)
        if not api_key:
            try:
                # In headless environments, keyring might fail if not configured
                # Retrieve API key from keyring (service="cerebro", username="gemini_api_key")
                api_key = keyring.get_password("cerebro", "gemini_api_key")
                # Fallback to legacy key if not found
                if not api_key:
                    api_key = keyring.get_password("cerebro", api_key_env)
            except Exception as e:
                if self.debug_enabled:
                    print(f"[Debug] Keyring access failed: {e}")

        if not api_key:
            raise ValueError(f"Missing API key for {agent_settings.get('model')}. Please check settings.")

        try:
            # LiteLLM handles message formatting for Gemini
            kwargs = {
                "model": self.model_name,
                "messages": messages,
                "stream": stream,
                "api_key": api_key,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            }

            if self.json_format:
                # Pass the schema for structured output
                # LiteLLM/Gemini mapping: response_format with type and response_schema
                kwargs["response_format"] = {
                    "type": "json_object",
                    "response_schema": self.json_format
                }

            response = litellm.completion(**kwargs)

            if stream:
                for chunk in response:
                    if chunk and chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            else:
                yield response.choices[0].message.content

        except Exception as e:
            raise Exception(f"Gemini/LiteLLM Error: {str(e)}")

    def _generate_ollama(self, agent_settings, messages, stream):
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
            "options": {
                "stop": [
                    "</s>",
                    "<|im_end|>"
                ]
            }
        }

        if self.json_format:
            payload["format"] = self.json_format

        if self.debug_enabled:
            payload_copy = json.loads(json.dumps(payload))
            for message in payload_copy.get('messages', []):
                if 'images' in message:
                    message['images'] = ['[Image data omitted in debug output]']
            print("[Debug] Sending request to Ollama API:", json.dumps(payload_copy, indent=2))

        response = requests.post(self.api_url, json=payload, stream=stream, timeout=60 if not stream else None)
        response.raise_for_status()

        if stream:
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    if self.debug_enabled:
                        print(f"[Debug] Received line: {line}")
                    try:
                        line_data = json.loads(line)
                        if "message" in line_data and "content" in line_data["message"]:
                            yield line_data["message"]["content"]
                        elif "error" in line_data:
                            raise Exception(line_data["error"])
                        elif line_data.get("done"):
                            if self.debug_enabled:
                                print(f"[Debug] Stream finished for agent '{self.agent_name}'.")
                            break
                    except ValueError as e:
                        logging.error(f"[Error] Failed to parse line as JSON: {e}")
        else:
            data = response.json()
            yield data.get("message", {}).get("content", "")

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

                    # Use the unified generator for thinking steps
                    thought_generator = self.generate_response(step_history, stream=False)
                    thought = "".join(list(thought_generator)).strip()

                    thoughts.append(thought)
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

            # Main response generation
            for chunk in self.generate_response(self.chat_history, stream=True):
                self.response_received.emit(chunk, self.agent_name)

            self.finished.emit()

        except requests.exceptions.RequestException as e:
            error_msg = f"[Error] Request error: {e}"
            logging.error(error_msg)
            if self.debug_enabled:
                print(error_msg)
            self.error_occurred.emit(error_msg)
            self.finished.emit()

        except Exception as e:
            error_msg = f"[Error] Exception in worker run: {e}"
            logging.error(error_msg)
            if self.debug_enabled:
                print(error_msg)
            self.error_occurred.emit(error_msg)
            self.finished.emit()
