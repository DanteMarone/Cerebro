# core/orchestrator.py
import json
import time
from datetime import datetime
from PyQt5.QtCore import QObject, pyqtSignal, QThread

# Imports from root
from worker import AIWorker
from tools import run_tool
from tasks import add_task
from transcripts import load_history, append_message, summarize_history
from metrics import record_tool_usage, record_response_time
from tool_utils import generate_tool_instructions_message, format_tool_block_html


class Orchestrator(QObject):
    """
    The Brain of Cerebro.
    Manages the conversation flow, agent execution, and tool usage.
    """

    # Signals
    chunk_received = pyqtSignal(str, str)  # agent_name, chunk
    # response_finished emits: agent_name, full_clean_content, html_display_content
    response_finished = pyqtSignal(str, str, str)
    error_occurred = pyqtSignal(str)
    notification = pyqtSignal(str, str)  # message, type (info/error)
    typing_started = pyqtSignal()
    typing_stopped = pyqtSignal()

    def __init__(self, agents_data, tools, tasks, metrics, screenshot_provider, debug_enabled=False, api_url="", parent=None):
        super().__init__(parent)
        self.agents_data = agents_data
        self.tools = tools
        self.tasks = tasks
        self.metrics = metrics
        self.screenshot_provider = screenshot_provider
        self.debug_enabled = debug_enabled
        self.api_url = api_url
        self.summarization_threshold = 20  # Default, can be updated

        self.active_worker_threads = []
        self.response_start_times = {}
        self.current_responses = {}

    def update_settings(self, debug_enabled=None, api_url=None, summarization_threshold=None):
        """Update runtime settings."""
        if debug_enabled is not None:
            self.debug_enabled = debug_enabled
        if api_url is not None:
            self.api_url = api_url
        if summarization_threshold is not None:
            self.summarization_threshold = summarization_threshold

    def set_agents_data(self, agents_data):
        self.agents_data = agents_data

    def stop_all_workers(self):
        """Stop all active worker threads."""
        for worker, thread in self.active_worker_threads:
            thread.quit()
            thread.wait()
            worker.deleteLater()
            thread.deleteLater()
        self.active_worker_threads.clear()

    def handle_user_message(self, user_text, user_name="You", user_color="#0000FF"):
        """
        Main entry point for handling a user message.
        """
        # 1. Determine enabled agents
        # If a Coordinator agent is enabled, send the message to the Coordinator agents only.
        enabled_coordinator_agents = [
            (agent_name, agent_settings)
            for agent_name, agent_settings in self.agents_data.items()
            if agent_settings.get('enabled', False) and agent_settings.get('role') == 'Coordinator'
        ]

        if enabled_coordinator_agents:  # If there are coordinators, use them
            enabled_agents = enabled_coordinator_agents
        else:  # Otherwise, fall back to other enabled agents (excluding Specialists)
            enabled_agents = [
                (agent_name, agent_settings)
                for agent_name, agent_settings in self.agents_data.items()
                if agent_settings.get('enabled', False)
                and not agent_settings.get('desktop_history_enabled', False)
                and agent_settings.get('role') != 'Specialist'
            ]

        if not enabled_agents:
            self.error_occurred.emit("Please enable at least one Assistant agent or a Coordinator agent.")
            return

        self.typing_started.emit()

        # 3. Start execution chain
        self._process_next_agent(0, enabled_agents)

    def _process_next_agent(self, index, enabled_agents):
        """
        Recursive function to process a list of agents sequentially.
        """
        if index is None or index >= len(enabled_agents):
            self.typing_stopped.emit()
            return

        agent_name, agent_settings = enabled_agents[index]
        if self.debug_enabled:
            print(f"[Debug] Processing agent: {agent_name}")

        model_name = agent_settings.get("model", "llama3.2-vision").strip()
        if not model_name:
            self.notification.emit(f"Agent '{agent_name}' has no valid model name.", "error")
            self._process_next_agent(index + 1, enabled_agents)
            return

        temperature = agent_settings.get("temperature", 0.7)
        max_tokens = agent_settings.get("max_tokens", 512)

        # Build chat history
        chat_history = self._build_agent_chat_history(agent_name, agent_settings)

        thread = QThread()
        # Pass the agents_data to the AIWorker
        worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.api_url)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        def on_finished():
            self._worker_finished_sequential(worker, thread, agent_name, index, enabled_agents)

        worker.response_received.connect(self._handle_ai_response_chunk)
        worker.error_occurred.connect(self._handle_worker_error)
        worker.finished.connect(on_finished)

        thread.started.connect(worker.run)
        thread.start()
        self.response_start_times[worker] = time.time()

    def _handle_ai_response_chunk(self, chunk, agent_name):
        if agent_name not in self.current_responses:
            self.current_responses[agent_name] = ''
        self.current_responses[agent_name] += chunk
        self.chunk_received.emit(agent_name, chunk)

    def _handle_worker_error(self, error_message):
        self.error_occurred.emit(error_message)
        self.typing_stopped.emit()

    def _worker_finished_sequential(self, sender_worker, thread, agent_name, index, enabled_agents):
        assistant_content = self.current_responses.get(agent_name, "")
        if agent_name in self.current_responses:
            del self.current_responses[agent_name]

        tool_request = None
        task_request = None
        content = assistant_content.strip()

        # Get the agent's settings
        agent_settings = self.agents_data.get(agent_name, {})

        # NOTE: logic regarding Specialist response validation:
        chat_history = load_history(self.debug_enabled)  # Reload to check recent context

        if agent_settings.get('role') == 'Specialist':
            if chat_history and chat_history[-1]['role'] == 'assistant':
                last_message = chat_history[-1]['content']
                if last_message.endswith(f"Next Response By: {agent_name}"):
                    # This is a valid response from a Specialist to the Coordinator
                    content = "[Response to Coordinator] " + content
                else:
                    # Specialist is not supposed to respond unless called by the Coordinator
                    if enabled_agents is not None:
                        self._process_next_agent(index + 1, enabled_agents)
                    return
            else:
                if enabled_agents is not None:
                    self._process_next_agent(index + 1, enabled_agents)
                return

        # Parse JSON content for any agent
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

        # If the message is from a Coordinator and contains "Next Response By:", extract the next agent's name.
        next_agent = None
        if agent_settings.get('role') == 'Coordinator' and "Next Response By:" in content:
            parts = content.split("Next Response By:")
            content = parts[0].strip()  # The part before "Next Response By:"
            next_agent = parts[1].strip()

        if agent_settings.get('role') == 'Coordinator':
            # Ensure the Coordinator's message ends with "Next Response By: [Agent Name]"
            if content and next_agent and not content.endswith(f"Next Response By: {next_agent}"):
                content += f"\nNext Response By: {next_agent}"

        # Prepare display content
        display_content = ""
        should_display = False

        if agent_settings.get('role') in ['Coordinator', 'Assistant']:
            should_display = True

        elif agent_settings.get('role') == 'Specialist' and any(msg.get('content', '').strip().endswith(f"Next Response By: {agent_name}") for msg in chat_history):
            should_display = True

        if should_display:
            if content:
                # Extract thought tags if present
                thought = None
                if "<thought>" in content and "</thought>" in content:
                    thought_start = content.find("<thought>")
                    thought_end = content.find("</thought>") + len("</thought>")
                    thought = content[thought_start:thought_end]
                    # Remove thought from content for history
                    clean_content = content[:thought_start] + content[thought_end:]
                    clean_content = clean_content.strip()
                else:
                    clean_content = content

                if clean_content.startswith("[Response to Coordinator]"):
                    clean_content = clean_content.replace("[Response to Coordinator]", "").strip()

                # Create displayed content with collapsible thought if present
                if thought:
                    thought_content = thought.replace("<thought>", "").replace("</thought>", "").strip()
                    display_content = f"{clean_content}<br><details><summary><i>Agent thoughts...</i></summary><pre style='background-color:#f5f5f5;padding:8px;border-radius:5px;color:#333;'>{thought_content}</pre></details>"
                else:
                    display_content = clean_content

                # Emit finished signal with formatted HTML
                html = f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {display_content}"
                self.response_finished.emit(agent_name, clean_content, html)

                # Store only the clean content without thoughts in history
                append_message(
                    chat_history,  # This is a local copy, append_message modifies list AND saves to file
                    "assistant",
                    clean_content,
                    agent_name,
                    debug_enabled=self.debug_enabled,
                )

        # If there's a next agent specified and it's managed by the Coordinator, process it.
        if next_agent:
            managed_agents = agent_settings.get('managed_agents', [])
            if next_agent in managed_agents:
                # Send the user's original message to the next agent.
                user_message = next((msg for msg in reversed(chat_history) if msg["role"] == "user"), None)
                if user_message:
                    self.send_message_to_agent(next_agent, user_message['content'])
            else:
                error_html = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{next_agent}' is not managed by Coordinator '{agent_name}'.</span>"
                self.response_finished.emit(agent_name, "", error_html)
                self.notification.emit(f"Error: Agent '{next_agent}' is not managed by Coordinator", "error")

        elif enabled_agents is not None:
            self._process_next_agent(index + 1, enabled_agents)
        else:
            self.typing_stopped.emit()

        # Handle tool request
        if tool_request and agent_settings.get("tool_use", False):
            self._handle_tool_request(tool_request, agent_name, agent_color, timestamp)

        # Handle task request
        if task_request:
            self._handle_task_request(task_request, agent_name, agent_color, timestamp)

        # Clean up worker thread
        self._cleanup_worker(sender_worker, thread, agent_name)

    def _handle_tool_request(self, tool_request, agent_name, agent_color, timestamp):
        tool_name = tool_request.get("name", "")
        tool_args = tool_request.get("args", {})
        agent_settings = self.agents_data.get(agent_name, {})

        enabled_tools = agent_settings.get("tools_enabled", [])
        if tool_name not in enabled_tools:
            error_msg = f"[{timestamp}] <span style='color:red;'>[Tool Error] Tool '{tool_name}' is not enabled for agent '{agent_name}'.</span>"
            self.response_finished.emit(agent_name, "", error_msg)
            # Append error to history
            chat_history = load_history(self.debug_enabled)
            append_message(chat_history, "assistant", f"[Tool Error] Tool '{tool_name}' is not enabled.", agent_name, debug_enabled=self.debug_enabled)
            self.notification.emit(f"Tool Error: '{tool_name}' not enabled for agent", "error")
        else:
            self.notification.emit(f"Agent '{agent_name}' is using tool: {tool_name}", "info")
            tool_result = run_tool(self.tools, tool_name, tool_args, self.debug_enabled)
            record_tool_usage(self.metrics, tool_name, self.debug_enabled)

            block_html = format_tool_block_html(tool_name, tool_args, tool_result)
            self.response_finished.emit(agent_name, "", f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {block_html}")

            chat_history = load_history(self.debug_enabled)
            append_message(chat_history, "assistant", f"{agent_name} called {tool_name}", agent_name, debug_enabled=self.debug_enabled)

            if tool_result.startswith("[Tool Error]"):
                error_msg = f"[{timestamp}] <span style='color:red;'>{tool_result}</span>"
                self.response_finished.emit(agent_name, "", error_msg)
                append_message(chat_history, "assistant", error_msg, agent_name, debug_enabled=self.debug_enabled)
                self.notification.emit(f"Tool Error: {tool_result}", "error")
            else:
                append_message(chat_history, "assistant", tool_result, agent_name, debug_enabled=self.debug_enabled)
                # Send result back to agent
                self.send_message_to_agent(agent_name, tool_result)
                self.notification.emit(f"Tool executed successfully: {tool_name}", "info")

    def _handle_task_request(self, task_request, agent_name, agent_color, timestamp):
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
            self.response_finished.emit(agent_name, "", f"\n[{timestamp}] <span style='color:{agent_color};'>{note}</span>")
            self.notification.emit(f"New task scheduled for {due_time}", "info")
        else:
            warn_msg = "[Task Error] Missing due_time in request."
            self.response_finished.emit(agent_name, "", f"\n[{timestamp}] <span style='color:red;'>{warn_msg}</span>")
            self.notification.emit("Task Error: Missing due time", "error")

    def send_message_to_agent(self, agent_name, message):
        """
        Sends a message to a specific agent (e.g. from Coordinator).
        """
        formatted_message = f"{message}\nNext Response By: {agent_name}"

        # Add to history
        chat_history = load_history(self.debug_enabled)
        append_message(chat_history, "user", formatted_message, debug_enabled=self.debug_enabled)

        agent_settings = self.agents_data.get(agent_name, {})
        if not agent_settings:
            self.error_occurred.emit(f"Agent '{agent_name}' not found.")
            return

        if agent_settings.get('enabled', False):
            self.typing_started.emit()
            model_name = agent_settings.get("model", "llama3.2-vision").strip()
            temperature = agent_settings.get("temperature", 0.7)
            max_tokens = agent_settings.get("max_tokens", 512)

            chat_history_for_agent = self._build_agent_chat_history(agent_name, agent_settings)

            thread = QThread()
            worker = AIWorker(model_name, chat_history_for_agent, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.api_url)
            worker.moveToThread(thread)
            self.active_worker_threads.append((worker, thread))

            def on_finished():
                self._worker_finished_sequential(worker, thread, agent_name, None, None)

            worker.response_received.connect(self._handle_ai_response_chunk)
            worker.error_occurred.connect(self._handle_worker_error)
            worker.finished.connect(on_finished)

            thread.started.connect(worker.run)
            thread.start()
            self.response_start_times[worker] = time.time()
        else:
            self.error_occurred.emit(f"Agent '{agent_name}' is not enabled.")

    def _cleanup_worker(self, sender_worker, thread, agent_name):
        if sender_worker in self.response_start_times:
            elapsed = time.time() - self.response_start_times.pop(sender_worker)
            record_response_time(self.metrics, agent_name, elapsed, self.debug_enabled)

        thread.quit()
        thread.wait()

        for i, (worker_item, thread_item) in enumerate(self.active_worker_threads):
            if worker_item == sender_worker:
                del self.active_worker_threads[i]
                break

        sender_worker.deleteLater()
        thread.deleteLater()

    def _build_agent_chat_history(self, agent_name, agent_settings):
        # Reload history
        chat_history = load_history(self.debug_enabled)
        chat_history = summarize_history(chat_history, threshold=self.summarization_threshold)

        system_prompt = ""

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
            # We need a dummy object to pass to generate_tool_instructions_message because it expects 'self.tools'
            # The function signature is generate_tool_instructions_message(app, agent_name)
            # app.tools is accessed. Orchestrator has self.tools.
            # We can mock it or refactor tool_utils.
            # Ideally refactor tool_utils but for now I will pass self.
            tool_instructions = generate_tool_instructions_message(self, agent_name)
            system_prompt += "\n" + tool_instructions

        final_history = [{"role": "system", "content": system_prompt}]

        temp_history = []
        for msg in chat_history:
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
                try:
                    next_agent_name = last_message['content'].split("Next Response By:")[1].strip()
                    next_agent_settings = self.agents_data.get(next_agent_name, {})
                    if next_agent_settings.get('role') == 'Specialist':
                        specialist_description = next_agent_settings.get('description', '')
                        if specialist_description:
                            temp_history.append({"role": "assistant", "content": specialist_description, "agent": next_agent_name})
                except IndexError:
                    pass

        # Include screenshots
        if agent_settings.get('desktop_history_enabled', False) and self.screenshot_provider:
            for img_path in self.screenshot_provider():
                temp_history.append({"role": "user", "content": "", "images": [img_path]})

        final_history.extend(temp_history)
        return final_history
