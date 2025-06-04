# message_broker.py
import json
from datetime import datetime
from PyQt5.QtCore import QThread
from worker import AIWorker
from tools import run_tool
from tasks import add_task, delete_task, save_tasks
from transcripts import (
    load_history,
    append_message,
    clear_history,
    export_history,
    summarize_history,
)

class MessageBroker:
    """
    Handles communication between agents and the UI.
    """
    def __init__(self, app):
        self.app = app  # Reference to the main application
        self.chat_history = load_history(app.debug_enabled if app else False)
        self.active_worker_threads = []

    def send_message(self, sender, recipient, message):
        """
        Entry point for sending a message.

        Args:
            sender (str): The sender of the message ("user" or agent name).
            recipient (str): The recipient agent (name or None for broadcast).
            message (str): The message content.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        if sender == "user":
            user_message_html = f'<span style="color:{self.app.user_color};">[{timestamp}] {self.app.user_name}:</span> {message}'
            self.app.chat_tab.append_message_html(user_message_html)

        user_message = {"role": "user", "content": message}
        self.chat_history.append(user_message)
        append_message(self.chat_history, "user", message, debug_enabled=self.app.debug_enabled if self.app else False)

        if recipient:
            # If we have a direct recipient, route there
            self._route_message(sender, recipient, message)
        else:
            # Otherwise, we fall back to the old logic, unless in sequential mode
            if self.app and self.app.sequential_mode:
                # In sequential mode, if there's no explicit recipient, we do nothing
                # or potentially choose a single default agent. The user might have
                # typed text but didn't specify who should respond. We can decide:
                #  - If "Director" is available, route to "Director"
                #  - Otherwise do nothing or produce an error message
                fallback_agent = None
                if "Director" in self.app.agents_data and self.app.agents_data["Director"].get("enabled", False):
                    fallback_agent = "Director"

                if fallback_agent:
                    self._route_message("user", fallback_agent, message)
                else:
                    # If no fallback, display an error
                    error_msg = f"[{timestamp}] <span style='color:red;'>[Error] No suitable agent found.</span>"
                    self.app.chat_tab.append_message_html(error_msg)
            else:
                # Old logic: send to all enabled coordinators, or if none, to all enabled assistants
                if self.app and self.app.agents_data:
                    enabled_coordinator_agents = [
                        agent_name
                        for agent_name, agent_settings in self.app.agents_data.items()
                        if agent_settings.get('enabled', False) and agent_settings.get('role') == 'Coordinator'
                    ]

                    if enabled_coordinator_agents:
                        for agent_name in enabled_coordinator_agents:
                            self._route_message("user", agent_name, message)
                    else:
                        enabled_assistant_agents = [
                            agent_name
                            for agent_name, agent_settings in self.app.agents_data.items()
                            if agent_settings.get('enabled', False) and agent_settings.get('role') == 'Assistant'
                        ]

                        if enabled_assistant_agents:
                            for agent_name in enabled_assistant_agents:
                                self._route_message("user", agent_name, message)
                        else:
                            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] No agents are enabled.</span>"
                            self.app.chat_tab.append_message_html(error_msg)

    def _route_message(self, sender, recipient, message):
        """
        Routes a message to the specified recipient agent.

        Args:
            sender (str): The sender of the message.
            recipient (str): The recipient agent's name.
            message (str): The message content.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")
        agent_settings = self.app.agents_data.get(recipient) if self.app else None

        if not agent_settings:
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{recipient}' not found.</span>"
            self.app.chat_tab.append_message_html(error_msg)
            return

        if not agent_settings.get('enabled', False):
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{recipient}' is not enabled.</span>"
            self.app.chat_tab.append_message_html(error_msg)
            return

        # Only allow users to send messages to the Director agent
        if sender == "user" and recipient != "Director":
            return

        # Role-based checks
        # If a Specialist, only allow messages from Coordinator.
        if agent_settings.get('role') == 'Specialist' and sender != 'Coordinator':
            return

        # Start a worker thread to process the message with Ollama
        model_name = agent_settings.get("model", "phi4").strip()
        temperature = agent_settings.get("temperature", 0.7)
        max_tokens = agent_settings.get("max_tokens", 512)
        chat_history = self.build_agent_chat_history(recipient)

        thread = QThread()
        worker = AIWorker(
            model_name,
            chat_history,
            temperature,
            max_tokens,
            self.app.debug_enabled if self.app else False,
            recipient,
            self.app.agents_data if self.app else {}
        )
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        def on_finished():
            self.worker_finished_sequential(worker, thread, recipient)

        worker.response_received.connect(self.app.handle_ai_response_chunk)
        worker.error_occurred.connect(self.app.handle_worker_error)
        worker.finished.connect(on_finished)

        thread.started.connect(worker.run)
        thread.start()

    def worker_finished_sequential(self, sender_worker, thread, agent_name):
        """
        Handles the completion of a worker thread in sequential mode.

        Args:
            sender_worker (AIWorker): The worker that finished.
            thread (QThread): The thread the worker was running in.
            agent_name (str): The name of the agent the worker was processing.
        """
        assistant_content = self.app.current_responses.get(agent_name, "")
        if agent_name in self.app.current_responses:
            del self.app.current_responses[agent_name]

        tool_request = None
        task_request = None
        content = assistant_content.strip()

        agent_settings = self.app.agents_data.get(agent_name, {})

        # Specialist agent response condition check
        if agent_settings.get('role') == 'Specialist':
            if not self.chat_history:
                return
            last_message = self.chat_history[-1]['content']

            if not last_message.endswith(f"Next Response By: {agent_name}"):
                return

        # Attempt to parse if agent is "Coordinator" or "Specialist" and returned JSON
        parsed = None
        if agent_settings.get('role') in ['Coordinator', 'Specialist']:
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
        agent_color = agent_settings.get("color", "#000000")

        # Extract "Next Response By: NextAgent" if present
        next_agent = None
        if agent_settings.get('role') == 'Coordinator' and "Next Response By:" in content:
            parts = content.split("Next Response By:")
            content = parts[0].strip()
            next_agent = parts[1].strip()

        # Display in the UI if there's content
        if agent_settings.get('role') in ['Coordinator', 'Assistant', 'Specialist']:
            if content:
                self.app.chat_tab.append_message_html(
                    f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {content}"
                )
                self.chat_history.append({"role": "assistant", "content": content, "agent": agent_name})
                append_message(self.chat_history, "assistant", content, agent_name, debug_enabled=self.app.debug_enabled if self.app else False)

        # If there's a next agent specified and it's managed by the coordinator
        if next_agent and agent_settings.get('role') == 'Coordinator':
            managed_agents = agent_settings.get('managed_agents', [])
            if next_agent in managed_agents:
                self.send_message_to_agent(next_agent, content)
            else:
                error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{next_agent}' is not managed by Coordinator '{agent_name}'.</span>"
                self.app.chat_tab.append_message_html(error_msg)

        # Handle any tool request
        if tool_request and agent_settings.get("tool_use", False):
            tool_name = tool_request.get("name", "")
            tool_args = tool_request.get("args", {})

            enabled_tools = agent_settings.get("tools_enabled", [])
            if tool_name not in enabled_tools:
                error_msg = f"[{timestamp}] <span style='color:red;'>[Tool Error] Tool '{tool_name}' is not enabled for agent '{agent_name}'.</span>"
                self.app.chat_tab.append_message_html(error_msg)
                self.chat_history.append({"role": "assistant", "content": error_msg, "agent": agent_name})
                append_message(self.chat_history, "assistant", error_msg, agent_name, debug_enabled=self.app.debug_enabled if self.app else False)
            else:
                tool_result = run_tool(self.app.tools, tool_name, tool_args, self.app.debug_enabled)
                if tool_result.startswith("[Tool Error]"):
                    error_msg = f"[{timestamp}] <span style='color:red;'>{tool_result}</span>"
                    self.app.chat_tab.append_message_html(error_msg)
                    self.chat_history.append({"role": "assistant", "content": error_msg, "agent": agent_name})
                    append_message(self.chat_history, "assistant", error_msg, agent_name, debug_enabled=self.app.debug_enabled if self.app else False)
                else:
                    display_message = f"{agent_name} used {tool_name} with args {tool_args}\nTool Result: {tool_result}"
                    self.app.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:{agent_color};'>{display_message}</span>")
                    self.chat_history.append({"role": "assistant", "content": display_message, "agent": agent_name})
                    append_message(self.chat_history, "assistant", display_message, agent_name, debug_enabled=self.app.debug_enabled if self.app else False)

        # Handle any task request
        if task_request:
            agent_for_task = task_request.get("agent_name", "Default Agent")
            prompt_for_task = task_request.get("prompt", "No prompt provided")
            due_time = task_request.get("due_time", "")
            if due_time:
                add_task(
                    self.app.tasks,
                    agent_for_task,
                    prompt_for_task,
                    due_time,
                    creator="agent",
                    debug_enabled=self.app.debug_enabled
                )
                note = f"Agent '{agent_name}' scheduled a new task for '{agent_for_task}' at {due_time}."
                self.app.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:{agent_color};'>{note}</span>")
            else:
                warn_msg = "[Task Error] Missing due_time in request."
                self.app.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:red;'>{warn_msg}</span>")

        if self.app.debug_enabled and agent_name:
            print(f"[Debug] Worker for agent '{agent_name}' finished.")

        thread.quit()
        thread.wait()

        # Remove the worker-thread pair
        for i, (worker_item, thread_item) in enumerate(self.active_worker_threads):
            if worker_item == sender_worker:
                del self.active_worker_threads[i]
                break

        sender_worker.deleteLater()
        thread.deleteLater()

    def get_chat_history(self, agent_name=None):
        """
        Retrieves the chat history.

        Args:
            agent_name (str, optional): The agent's name to filter by. 
                                         Defaults to None (all history).

        Returns:
            list: The chat history.
        """
        if agent_name:
            return self.build_agent_chat_history(agent_name)
        else:
            return self.chat_history

    def register_agent(self, agent):
        """Registers an agent (Not currently used)."""
        pass

    def unregister_agent(self, agent):
        """Unregisters an agent (Not currently used)."""
        pass

    def build_agent_chat_history(self, agent_name, user_message=None):
        """
        Builds a chat history for a specific agent.

        Args:
            agent_name (str): The name of the agent.
            user_message (dict, optional): A new user message to include.

        Returns:
            list: The chat history for the agent.
        """
        self.chat_history = load_history(self.app.debug_enabled if self.app else False)
        self.chat_history = summarize_history(self.chat_history)
        system_prompt = ""
        agent_settings = self.app.agents_data.get(agent_name, {}) if self.app else {}

        if agent_settings:
            # If coordinator, include managed agents info
            if agent_settings.get('role') == 'Coordinator':
                managed_agents_info = []
                for managed_agent_name in agent_settings.get('managed_agents', []):
                    managed_agent_settings = self.app.agents_data.get(managed_agent_name, {})
                    if managed_agent_settings:
                        desc = managed_agent_settings.get('description', 'No description available')
                        managed_agents_info.append(f"{managed_agent_name}: {desc}")
                if managed_agents_info:
                    system_prompt += "You can choose from the following agents:\n" + "\n".join(managed_agents_info) + "\n"

            system_prompt += agent_settings.get("system_prompt", "")

            # If the agent can use tools, add the instructions
            if agent_settings.get("tool_use", False):
                tool_instructions = self.generate_tool_instructions_message(agent_name)
                system_prompt += "\n" + tool_instructions

        chat_history = [{"role": "system", "content": system_prompt}]

        # Filter messages for relevant roles
        for msg in self.chat_history:
            if msg['role'] == 'user':
                chat_history.append(msg)
            elif msg['role'] == 'assistant':
                # Include messages from this agent
                if msg.get('agent') == agent_name:
                    chat_history.append(msg)
                # If agent_name is coordinator, also see specialist responses
                elif (agent_settings.get('role') == 'Coordinator'
                      and self.app.agents_data.get(msg.get('agent'), {}).get('role') == 'Specialist'):
                    chat_history.append(msg)

        # If last message indicates a handoff to a Specialist, insert that specialist's
        # description if relevant
        if len(chat_history) > 1:
            last_msg = chat_history[-1]
            if last_msg['role'] == 'assistant' and "Next Response By:" in last_msg['content']:
                next_agent_name = last_msg['content'].split("Next Response By:")[1].strip()
                next_agent_settings = self.app.agents_data.get(next_agent_name, {})
                if next_agent_settings.get('role') == 'Specialist':
                    spec_desc = next_agent_settings.get('description', '')
                    if spec_desc:
                        chat_history.append({"role": "assistant", "content": spec_desc, "agent": next_agent_name})

        if user_message:
            chat_history.append(user_message)

        return chat_history

    def generate_tool_instructions_message(self, agent_name):
        """
        Generates tool usage instructions for an agent.

        Args:
            agent_name (str): The name of the agent.

        Returns:
            str: The tool instructions message.
        """
        agent_settings = self.app.agents_data.get(agent_name, {})
        if agent_settings.get("tool_use", False):
            enabled_tools = agent_settings.get("tools_enabled", [])
            tool_list_str = ""
            for t in self.app.tools:
                if t['name'] in enabled_tools:
                    tool_list_str += f"- {t['name']}: {t['description']}\n"

            instructions = (
                "You are a knowledgeable assistant. You can answer most questions directly.\n"
                "ONLY use a tool if you cannot answer from your own knowledge. If you can answer directly, do so.\n"
                "If using a tool, respond ONLY in the following exact JSON format and nothing else:\n"
                "{\n"
                ' "role": "assistant",\n'
                ' "content": "<explanation>",\n'
                ' "tool_request": {\n'
                '    "name": "<tool_name>",\n'
                '    "args": { ... }\n'
                ' }\n'
                '}\n'
                "No extra text outside this JSON when calling a tool.\n"
                f"Available tools:\n{tool_list_str}"
            )
            return instructions
        else:
            return ""

    def close_all_threads(self):
        """
        Stops all worker threads.
        """
        for worker, thread in self.active_worker_threads:
            thread.quit()
            thread.wait()
            worker.deleteLater()
            thread.deleteLater()
        self.active_worker_threads.clear()

    def clear_chat(self):
        """Clears the chat history."""
        self.chat_history = []

    def send_message_to_agent(self, agent_name, message):
        """
        Sends a message directly to a specified agent.

        Args:
            agent_name (str): The name of the recipient agent.
            message (str): The message content.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Check if the agent exists and is enabled
        agent_settings = self.app.agents_data.get(agent_name, {})
        if not agent_settings:
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{agent_name}' not found.</span>"
            self.app.chat_tab.append_message_html(error_msg)
            return
        if not agent_settings.get("enabled", False):
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{agent_name}' is not enabled.</span>"
            self.app.chat_tab.append_message_html(error_msg)
            return

        # Check if calling agent is allowed to call the target agent
        
        # Get the current agent's name 
        current_agent_name = None
        for name, settings in self.app.agents_data.items():
            if settings.get("system_prompt") and agent_name in settings.get("system_prompt") and "Next Response By:" in settings.get("system_prompt"):
                current_agent_name = name
                break
        current_agent_settings = self.app.agents_data.get(current_agent_name, {})

        # Allow all Coordinators to call each other
        if agent_settings.get("role") != "Coordinator":
            # If the current agent is a Coordinator, it should manage the agent it is trying to call
            
            if not current_agent_settings or current_agent_settings.get("role") != "Coordinator" or agent_name not in current_agent_settings.get("managed_agents", []):
                error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{agent_name}' cannot be called in this context.</span>"
                self.app.chat_tab.append_message_html(error_msg)
                return

        # Append "Next Response By" if not already present
        if not message.endswith(f"Next Response By: {agent_name}"):
            message = message + f"\nNext Response By: {agent_name}"

        self.chat_history.append({"role": "user", "content": message})
        append_message(self.chat_history, "user", message, debug_enabled=self.app.debug_enabled if self.app else False)

        # Start worker thread
        model_name = agent_settings.get("model", "phi4").strip()
        temperature = agent_settings.get("temperature", 0.7)
        max_tokens = agent_settings.get("max_tokens", 512)
        chat_history = self.build_agent_chat_history(agent_name)

        thread = QThread()
        worker = AIWorker(
            model_name,
            chat_history,
            temperature,
            max_tokens,
            self.app.debug_enabled,
            agent_name,
            self.app.agents_data
        )
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        def on_finished():
            self.worker_finished_sequential(worker, thread, agent_name)

        worker.response_received.connect(self.app.handle_ai_response_chunk)
        worker.error_occurred.connect(self.app.handle_worker_error)
        worker.finished.connect(on_finished)

        thread.started.connect(worker.run)
        thread.start()