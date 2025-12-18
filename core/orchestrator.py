import json
import time
import os
import logging
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal, QThread

from .worker import AIWorker
from tools import run_tool
from tasks import add_task
from metrics import record_tool_usage, record_response_time
from transcripts import load_history, summarize_history, append_message
from tool_utils import generate_tool_instructions_message, format_tool_block_html
from local_llm_helper import get_installed_models
from log_utils import format_user_friendly
import tts

AGENTS_SAVE_FILE = "agents.json"

class Orchestrator(QObject):
    # Signals
    typing_started = pyqtSignal()
    typing_stopped = pyqtSignal()
    # html_content, agent_name, agent_color
    message_received = pyqtSignal(str, str, str)
    chunk_received = pyqtSignal(str, str)  # chunk, agent_name
    error_occurred = pyqtSignal(str)  # message
    all_agents_finished = pyqtSignal()
    refresh_agents_requested = pyqtSignal()
    task_scheduled = pyqtSignal(str)  # message

    def __init__(self, tools, tasks, metrics, debug_enabled=True, api_url="http://localhost:11434/api/chat", screenshot_manager=None):
        super().__init__()
        self.tools = tools
        self.tasks = tasks
        self.metrics = metrics
        self.debug_enabled = debug_enabled
        self.api_url = api_url
        self.screenshot_manager = screenshot_manager

        self.agents_data = {}
        self.active_worker_threads = []
        self.current_responses = {}
        self.response_start_times = {}
        self.chat_history = []
        self.summarization_threshold = 20

        self.populate_agents()

    def set_summarization_threshold(self, threshold):
        self.summarization_threshold = threshold

    def populate_agents(self):
        self.agents_data = {}
        if os.path.exists(AGENTS_SAVE_FILE):
            try:
                with open(AGENTS_SAVE_FILE, "r", encoding="utf-8") as f:
                    self.agents_data = json.load(f)
                if self.debug_enabled:
                    print("[Debug] Agents loaded.")
            except Exception as e:
                print(f"[Debug] Failed to load agents: {e}")
        else:
            models = get_installed_models()
            model = models[0] if models else "llama3.2-vision"
            default_agent_settings = {
                "model": model,
                "temperature": 0.7,
                "max_tokens": 512,
                "system_prompt": (
                    "You are the Cerebro default assistant with full tool access. "
                    "Use tools whenever they help and keep replies concise."
                ),
                "enabled": True,
                "color": "#000000",
                "avatar": "🤖",
                "include_image": False,
                "desktop_history_enabled": False,
                "screenshot_interval": 5,
                "role": "Assistant",
                "description": "A general-purpose assistant.",
                "tool_use": True,
                "tools_enabled": [t["name"] for t in self.tools],
                "automations_enabled": [],
                "thinking_enabled": False,
                "thinking_steps": 3,
                "tts_enabled": False,
            }
            self.agents_data["Default Agent"] = default_agent_settings
            if self.debug_enabled:
                print("[Debug] Default agent added.")

        self.refresh_agents_requested.emit()

    def save_agents(self):
        try:
            with open(AGENTS_SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.agents_data, f, indent=4)
            if self.debug_enabled:
                print("[Debug] Agents saved.")
        except Exception as e:
            print(f"[Debug] Failed to save agents: {e}")
            self.error_occurred.emit(f"Error saving agents: {str(e)}")

    def add_agent(self, agent_name, settings=None):
        if agent_name in self.agents_data:
            return False, "Agent already exists."

        if settings:
            self.agents_data[agent_name] = settings
        else:
            # Default settings
            self.agents_data[agent_name] = {
                "model": "llama3.2-vision",
                "temperature": 0.7,
                "max_tokens": 512,
                "system_prompt": "",
                "enabled": True,
                "color": "#000000",
                "include_image": False,
                "desktop_history_enabled": False,
                "screenshot_interval": 5,
                "role": "Assistant",
                "description": "A new assistant agent.",
                "tool_use": False,
                "tools_enabled": [],
                "automations_enabled": [],
                "thinking_enabled": False,
                "thinking_steps": 3,
                "tts_enabled": False,
                "tts_voice": ""
            }

        self.save_agents()
        self.refresh_agents_requested.emit()
        return True, f"Agent '{agent_name}' created successfully"

    def delete_agent(self, agent_name):
        if agent_name and agent_name in self.agents_data:
            del self.agents_data[agent_name]
            self.save_agents()
            self.refresh_agents_requested.emit()
            return True, f"Agent '{agent_name}' deleted"
        return False, "Agent not found"

    def get_agent_settings(self, agent_name):
        return self.agents_data.get(agent_name)

    def handle_user_message(self, user_text, user_message_object=None):
        """
        Main entry point for handling a user message.
        """
        if not user_message_object:
            user_message_object = append_message(
                self.chat_history,
                "user",
                user_text,
                debug_enabled=self.debug_enabled,
            )

        # Logic to determine enabled agents
        enabled_coordinator_agents = [
            (agent_name, agent_settings)
            for agent_name, agent_settings in self.agents_data.items()
            if agent_settings.get('enabled', False) and agent_settings.get('role') == 'Coordinator'
        ]

        if enabled_coordinator_agents:
            enabled_agents = enabled_coordinator_agents
        else:
            enabled_agents = [
                (agent_name, agent_settings)
                for agent_name, agent_settings in self.agents_data.items()
                if agent_settings.get('enabled', False)
                and not agent_settings.get('desktop_history_enabled', False)
                and agent_settings.get('role') != 'Specialist'
            ]

        if not enabled_agents:
            self.typing_stopped.emit()
            self.all_agents_finished.emit()
            return False, "No Agents Enabled"

        self.process_next_agent(0, enabled_agents, user_message_object)
        return True, "Processing started"

    def process_next_agent(self, index, enabled_agents, user_message):
        if index is None or index >= len(enabled_agents):
            self.typing_stopped.emit()
            self.all_agents_finished.emit()
            return

        agent_name, agent_settings = enabled_agents[index]
        if self.debug_enabled:
            print(f"[Debug] Processing agent: {agent_name}")

        self.typing_started.emit()

        model_name = agent_settings.get("model", "llama3.2-vision").strip()
        if not model_name:
            self.error_occurred.emit(f"Agent '{agent_name}' has no valid model name.")
            self.process_next_agent(index + 1, enabled_agents, user_message)
            return

        temperature = agent_settings.get("temperature", 0.7)
        max_tokens = agent_settings.get("max_tokens", 512)

        # Build chat history
        if agent_settings.get('role') == 'Coordinator':
            chat_history = self.build_agent_chat_history(agent_name, user_message)
        elif agent_settings.get('role') == 'Specialist':
            chat_history = self.build_agent_chat_history(agent_name)
        else:
            chat_history = self.build_agent_chat_history(agent_name)

        thread = QThread()
        worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.api_url)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        def on_finished():
            self.worker_finished_sequential(worker, thread, agent_name, index, enabled_agents, user_message)

        worker.response_received.connect(self.handle_ai_response_chunk)
        worker.error_occurred.connect(self.handle_worker_error)
        worker.finished.connect(on_finished)

        thread.started.connect(worker.run)
        thread.start()
        self.response_start_times[worker] = time.time()

    def handle_ai_response_chunk(self, chunk, agent_name):
        if agent_name not in self.current_responses:
            self.current_responses[agent_name] = ''
        self.current_responses[agent_name] += chunk
        self.chunk_received.emit(chunk, agent_name)

    def handle_worker_error(self, error_message):
        logging.error(error_message)
        friendly = format_user_friendly(error_message, self.api_url)
        self.error_occurred.emit(friendly)
        self.typing_stopped.emit()

    def worker_finished_sequential(self, sender_worker, thread, agent_name, index, enabled_agents, user_message):
        assistant_content = self.current_responses.get(agent_name, "")
        if agent_name in self.current_responses:
            del self.current_responses[agent_name]

        tool_request = None
        task_request = None
        content = assistant_content.strip()
        agent_settings = self.agents_data.get(agent_name, {})

        # Specialist Logic
        if agent_settings.get('role') == 'Specialist':
            if self.chat_history and self.chat_history[-1]['role'] == 'assistant':
                last_message = self.chat_history[-1]['content']
                if last_message.endswith(f"Next Response By: {agent_name}"):
                    content = "[Response to Coordinator] " + content
                else:
                    if enabled_agents is not None and index is not None:
                        self.process_next_agent(index + 1, enabled_agents, user_message)
                    return
            else:
                if enabled_agents is not None and index is not None:
                    self.process_next_agent(index + 1, enabled_agents, user_message)
                return

        # JSON parsing
        parsed = None
        if content.startswith("{") and content.endswith("}"):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None

        if parsed is not None:
            if "tool_request" in parsed:
                tool_request = parsed["tool_request"]
                content = parsed.get("content", "").strip()
            if "task_request" in parsed:
                task_request = parsed["task_request"]
                content = parsed.get("content", "").strip()

        timestamp = datetime.now().strftime("%H:%M:%S")
        agent_color = self.agents_data.get(agent_name, {}).get("color", "#000000")

        next_agent = None
        if agent_settings.get('role') == 'Coordinator' and "Next Response By:" in content:
            parts = content.split("Next Response By:")
            content = parts[0].strip()
            next_agent = parts[1].strip()

        if agent_settings.get('role') == 'Coordinator':
            if content and next_agent and not content.endswith(f"Next Response By: {next_agent}"):
                content += f"\nNext Response By: {next_agent}"

        # Display and History logic
        display_content = ""
        clean_content = content

        if agent_settings.get('role') in ['Coordinator', 'Assistant'] or \
           (agent_settings.get('role') == 'Specialist' and any(msg.get('content', '').strip().endswith(f"Next Response By: {agent_name}") for msg in self.chat_history)):

            # Extract thought tags
            thought = None
            if "<thought>" in content and "</thought>" in content:
                thought_start = content.find("<thought>")
                thought_end = content.find("</thought>") + len("</thought>")
                thought = content[thought_start:thought_end]
                clean_content = content[:thought_start] + content[thought_end:]
                clean_content = clean_content.strip()
            else:
                clean_content = content

            if clean_content.startswith("[Response to Coordinator]"):
                clean_content = clean_content.replace("[Response to Coordinator]", "").strip()

            # Build display HTML
            if thought:
                thought_content = thought.replace("<thought>", "").replace("</thought>", "").strip()
                display_content = f"{clean_content}<br><details><summary><i>Agent thoughts...</i></summary><pre style='background-color:#f5f5f5;padding:8px;border-radius:5px;color:#333;'>{thought_content}</pre></details>"
            else:
                display_content = clean_content

            # Emit message for display
            html_msg = f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {display_content}"
            self.message_received.emit(html_msg, agent_name, agent_color)

            # TTS
            if agent_settings.get('tts_enabled'):
                voice = agent_settings.get('tts_voice')
                tts.speak_text(clean_content, voice)

            # Append to history (clean content)
            append_message(
                self.chat_history,
                "assistant",
                clean_content,
                agent_name,
                debug_enabled=self.debug_enabled,
            )

        # Handle Next Agent
        if next_agent:
            managed_agents = agent_settings.get('managed_agents', [])
            if next_agent in managed_agents:
                # Find user message to forward
                user_msg_hist = next((msg for msg in reversed(self.chat_history) if msg["role"] == "user"), None)
                if user_msg_hist:
                    self.send_message_to_agent(next_agent, user_msg_hist['content'])
            else:
                error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{next_agent}' is not managed by Coordinator '{agent_name}'.</span>"
                self.message_received.emit(error_msg, "System", "red")
                self.error_occurred.emit(f"Error: Agent '{next_agent}' is not managed by Coordinator")

        elif enabled_agents is not None and index is not None:
            self.process_next_agent(index + 1, enabled_agents, user_message)

        # Handle Tools
        if tool_request and agent_settings.get("tool_use", False):
            tool_name = tool_request.get("name", "")
            tool_args = tool_request.get("args", {})
            enabled_tools = agent_settings.get("tools_enabled", [])

            if tool_name not in enabled_tools:
                error_msg = f"[{timestamp}] <span style='color:red;'>[Tool Error] Tool '{tool_name}' is not enabled for agent '{agent_name}'.</span>"
                self.message_received.emit(error_msg, "System", "red")
                append_message(self.chat_history, "assistant", error_msg, agent_name, debug_enabled=self.debug_enabled)
                self.error_occurred.emit(f"Tool Error: '{tool_name}' not enabled for agent")
            else:
                # Run tool
                tool_result = run_tool(self.tools, tool_name, tool_args, self.debug_enabled)
                record_tool_usage(self.metrics, tool_name, self.debug_enabled)

                block_html = format_tool_block_html(tool_name, tool_args, tool_result)
                self.message_received.emit(
                    f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {block_html}",
                    agent_name, agent_color
                )
                append_message(self.chat_history, "assistant", f"{agent_name} called {tool_name}", agent_name, debug_enabled=self.debug_enabled)

                if tool_result.startswith("[Tool Error]"):
                    error_msg = f"[{timestamp}] <span style='color:red;'>{tool_result}</span>"
                    self.message_received.emit(error_msg, "System", "red")
                    append_message(self.chat_history, "assistant", error_msg, agent_name, debug_enabled=self.debug_enabled)
                    self.error_occurred.emit(f"Tool Error: {tool_result}")
                else:
                    append_message(self.chat_history, "assistant", tool_result, agent_name, debug_enabled=self.debug_enabled)
                    self.send_message_to_agent(agent_name, tool_result)

        # Handle Tasks
        if task_request:
            agent_for_task = task_request.get("agent_name", "Default Agent")
            prompt_for_task = task_request.get("prompt", "No prompt provided")
            due_time = task_request.get("due_time", "")
            if due_time:
                add_task(
                    self.tasks,
                    agent_for_task,
                    prompt_for_task,
                    due_time,
                    creator="agent",
                    debug_enabled=self.debug_enabled,
                    os_schedule=True,
                )
                note = f"Agent '{agent_name}' scheduled a new task for '{agent_for_task}' at {due_time}."
                self.message_received.emit(f"\n[{timestamp}] <span style='color:{agent_color};'>{note}</span>", agent_name, agent_color)
                self.task_scheduled.emit(f"New task scheduled for {due_time}")
            else:
                warn_msg = "[Task Error] Missing due_time in request."
                self.message_received.emit(f"\n[{timestamp}] <span style='color:red;'>{warn_msg}</span>", "System", "red")
                self.error_occurred.emit("Task Error: Missing due time")

        if self.debug_enabled and agent_name:
            print(f"[Debug] Worker for agent '{agent_name}' finished.")

        if sender_worker in self.response_start_times:
            elapsed = time.time() - self.response_start_times.pop(sender_worker)
            record_response_time(self.metrics, agent_name, elapsed, self.debug_enabled)

        thread.quit()
        thread.wait()

        # Cleanup
        for i, (worker_item, thread_item) in enumerate(self.active_worker_threads):
            if worker_item == sender_worker:
                del self.active_worker_threads[i]
                break

        sender_worker.deleteLater()
        thread.deleteLater()

    def send_message_to_agent(self, agent_name, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"{message}\nNext Response By: {agent_name}"
        append_message(self.chat_history, "user", formatted_message, debug_enabled=self.debug_enabled)

        agent_settings = self.agents_data.get(agent_name, {})
        if not agent_settings:
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{agent_name}' not found.</span>"
            self.message_received.emit(error_msg, "System", "red")
            self.error_occurred.emit(f"Error: Agent '{agent_name}' not found")
            return

        if agent_settings.get('enabled', False):
            self.typing_started.emit()
            model_name = agent_settings.get("model", "llama3.2-vision").strip()
            temperature = agent_settings.get("temperature", 0.7)
            max_tokens = agent_settings.get("max_tokens", 512)
            chat_history = self.build_agent_chat_history(agent_name)

            thread = QThread()
            worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.api_url)
            worker.moveToThread(thread)
            self.active_worker_threads.append((worker, thread))

            def on_finished():
                self.worker_finished_sequential(worker, thread, agent_name, None, None, None)

            worker.response_received.connect(self.handle_ai_response_chunk)
            worker.error_occurred.connect(self.handle_worker_error)
            worker.finished.connect(on_finished)

            thread.started.connect(worker.run)
            thread.start()
            self.response_start_times[worker] = time.time()
        else:
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{agent_name}' is not enabled.</span>"
            self.message_received.emit(error_msg, "System", "red")
            self.error_occurred.emit(f"Error: Agent '{agent_name}' is not enabled")

    def build_agent_chat_history(self, agent_name, user_message=None):
        self.chat_history = load_history(self.debug_enabled)
        self.chat_history = summarize_history(
            self.chat_history, threshold=self.summarization_threshold
        )

        system_prompt = ""
        agent_settings = self.agents_data.get(agent_name, {})

        if agent_settings:
            if agent_settings.get('role') == 'Coordinator':
                managed_agents_info = []
                for managed_agent_name in agent_settings.get('managed_agents', []):
                    managed_agent_settings = self.agents_data.get(managed_agent_name, {})
                    if managed_agent_settings:
                        managed_agent_desc = managed_agent_settings.get('description', 'No description available')
                        managed_agents_info.append(f"{managed_agent_name}: {managed_agent_desc}")

                if managed_agents_info:
                    system_prompt += "You can choose from the following agents:\n" + "\n".join(managed_agents_info) + "\n"

            system_prompt += agent_settings.get("system_prompt", "")

            if agent_settings.get("tool_use", False):
                # We need self (Orchestrator) to pass to generate_tool_instructions_message?
                # generate_tool_instructions_message expects 'app' which has agents_data, tools.
                # So we can pass 'self' as it has agents_data and tools.
                tool_instructions = generate_tool_instructions_message(self, agent_name)
                system_prompt += "\n" + tool_instructions

        chat_history = [{"role": "system", "content": system_prompt}]

        temp_history = []
        for msg in self.chat_history:
            if msg['role'] == 'user':
                temp_history.append(msg)
            elif msg['role'] == 'assistant':
                content = msg['content']
                if "<thought>" in content and "</thought>" in content:
                    thought_start = content.find("<thought>")
                    thought_end = content.find("</thought>") + len("</thought>")
                    clean_content = content[:thought_start] + content[thought_end:]
                    clean_content = clean_content.strip()
                    cleaned_msg = msg.copy()
                    cleaned_msg["content"] = clean_content

                    if cleaned_msg.get('agent') == agent_name:
                        temp_history.append(cleaned_msg)
                    elif agent_settings.get('role') == 'Coordinator' and self.agents_data.get(cleaned_msg.get('agent'), {}).get('role') == 'Specialist':
                        temp_history.append(cleaned_msg)
                else:
                    if msg.get('agent') == agent_name:
                        temp_history.append(msg)
                    elif agent_settings.get('role') == 'Coordinator' and self.agents_data.get(msg.get('agent'), {}).get('role') == 'Specialist':
                        temp_history.append(msg)

        if temp_history:
            last_message = temp_history[-1]
            if last_message['role'] == 'assistant' and "Next Response By:" in last_message['content']:
                next_agent_name = last_message['content'].split("Next Response By:")[1].strip()
                next_agent_settings = self.agents_data.get(next_agent_name, {})
                if next_agent_settings.get('role') == 'Specialist':
                    specialist_description = next_agent_settings.get('description', '')
                    if specialist_description:
                        temp_history.append({"role": "assistant", "content": specialist_description, "agent": next_agent_name})

        if agent_settings.get('desktop_history_enabled', False) and self.screenshot_manager:
            for img_path in self.screenshot_manager.get_images():
                temp_history.append({"role": "user", "content": "", "images": [img_path]})

        if user_message:
            temp_history.append(user_message)

        chat_history.extend(temp_history)
        return chat_history

    def cleanup(self):
        for worker, thread in self.active_worker_threads:
            thread.quit()
            thread.wait()
            worker.deleteLater()
            thread.deleteLater()
        self.active_worker_threads.clear()

    # Scheduler method logic
    def schedule_user_message(self, agent_name, prompt, task_id=None, user_name="You", user_color="#0000FF"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        message_html = f'<span style="color:{user_color};">[{timestamp}] (Scheduled) {user_name}:</span> {prompt}'
        self.message_received.emit(message_html, user_name, user_color)

        append_message(self.chat_history, "user", prompt, debug_enabled=self.debug_enabled)

        agent_settings = self.agents_data.get(agent_name, None)
        if not agent_settings:
            msg = f"[Task Error] Agent '{agent_name}' not found for Task '{task_id}'"
            self.message_received.emit(f"\n[{timestamp}] <span style='color:red;'>{msg}</span>", "System", "red")
            self.error_occurred.emit(msg)
            return

        if not agent_settings.get("enabled", False):
            msg = f"[Task Error] Agent '{agent_name}' is disabled. Task '{task_id}' skipped."
            self.message_received.emit(f"\n[{timestamp}] <span style='color:red;'>{msg}</span>", "System", "red")
            self.error_occurred.emit(msg)
            return

        self.typing_started.emit()
        model_name = agent_settings.get("model", "llama3.2-vision").strip()
        temperature = agent_settings.get("temperature", 0.7)
        max_tokens = agent_settings.get("max_tokens", 512)
        chat_history = self.build_agent_chat_history(agent_name)

        thread = QThread()
        worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.api_url)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        def on_finished():
            self.worker_finished_sequential(worker, thread, agent_name, None, None, None)

        worker.response_received.connect(self.handle_ai_response_chunk)
        worker.error_occurred.connect(self.handle_worker_error)
        worker.finished.connect(on_finished)

        thread.started.connect(worker.run)
        thread.start()
        self.response_start_times[worker] = time.time()
