#app.py
import os
import json
from datetime import datetime
from PyQt5 import QtCore
from PyQt5.QtCore import QThread, Qt, QTimer
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox, QApplication, QAction, QMenu, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QStackedWidget,
    QInputDialog, QScrollArea, QShortcut
)
from PyQt5.QtGui import QKeySequence

from worker import AIWorker
from tools import load_tools, run_tool
from tasks import load_tasks, save_tasks, add_task, delete_task
from tab_chat import ChatTab
from tab_agents import AgentsTab
from tab_tools import ToolsTab
from tab_tasks import TasksTab

AGENTS_SAVE_FILE = "agents.json"
SETTINGS_FILE = "settings.json"
TOOLS_FILE = "tools.json"
TASKS_FILE = "tasks.json"

class AIChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Check for debug mode
        if os.environ.get("DEBUG_MODE", "") == "1":
            self.debug_enabled = True
        else:
            self.debug_enabled = False

        # Basic window settings
        self.setWindowTitle("Cerebro 1.0")
        self.setGeometry(100, 100, 1000, 700)  # Larger default window

        # Variables
        self.chat_history = []
        self.current_responses = {}
        self.agents_data = {}
        self.include_image = False
        self.include_screenshot = False
        self.current_agent_color = "#000000"
        self.user_name = "You"
        self.user_color = "#0000FF"
        self.dark_mode = False
        self.active_worker_threads = []
        
        # Initialize notification system
        self.notifications = []
        self.notification_timer = QTimer(self)
        self.notification_timer.timeout.connect(self.process_notifications)
        self.notification_timer.start(3000)  # Check every 3 seconds

        # Load Tools and Tasks
        self.tools = load_tools(self.debug_enabled)
        self.tasks = load_tasks(self.debug_enabled)
        
        # Create main layout with sidebar
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)  # Remove margins
        central_widget.setLayout(main_layout)
        
        # Create sidebar
        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        self.sidebar.setLayout(sidebar_layout)
        
        # App logo/title
        logo_container = QWidget()
        logo_container.setObjectName("logoContainer")
        logo_layout = QVBoxLayout()
        logo_layout.setContentsMargins(15, 15, 15, 15)
        logo_container.setLayout(logo_layout)
        
        logo_label = QLabel("CEREBRO")
        logo_label.setObjectName("appLogo")
        logo_label.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(logo_label)
        
        tagline = QLabel("Multi-Agent AI Platform")
        tagline.setObjectName("appTagline")
        tagline.setAlignment(Qt.AlignCenter)
        logo_layout.addWidget(tagline)
        
        sidebar_layout.addWidget(logo_container)
        
        # Create navigation buttons for sidebar
        self.nav_buttons = {}
        
        # Chat button
        self.nav_buttons["chat"] = self.create_nav_button("Chat", 0)
        sidebar_layout.addWidget(self.nav_buttons["chat"])
        
        # Agents button
        self.nav_buttons["agents"] = self.create_nav_button("Agents", 1)
        sidebar_layout.addWidget(self.nav_buttons["agents"])
        
        # Tools button
        self.nav_buttons["tools"] = self.create_nav_button("Tools", 2)
        sidebar_layout.addWidget(self.nav_buttons["tools"])
        
        # Tasks button
        self.nav_buttons["tasks"] = self.create_nav_button("Tasks", 3)
        sidebar_layout.addWidget(self.nav_buttons["tasks"])
        
        # Add stretcher to push settings button to bottom
        sidebar_layout.addStretch(1)
        
        # Settings button
        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("navButton")
        settings_btn.clicked.connect(self.open_settings_dialog)
        settings_btn.setCursor(Qt.PointingHandCursor)
        sidebar_layout.addWidget(settings_btn)
        
        # Help button
        help_btn = QPushButton("Help")
        help_btn.setObjectName("navButton")
        help_btn.clicked.connect(self.show_help_dialog)
        help_btn.setCursor(Qt.PointingHandCursor)
        sidebar_layout.addWidget(help_btn)
        
        main_layout.addWidget(self.sidebar)
        
        # Create stacked widget for content
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("contentStack")
        
        # Create content pages
        self.chat_tab = ChatTab(self)
        self.agents_tab = AgentsTab(self)
        self.tools_tab = ToolsTab(self)
        self.tasks_tab = TasksTab(self)
        
        # Add pages to stacked widget
        self.content_stack.addWidget(self.chat_tab)
        self.content_stack.addWidget(self.agents_tab)
        self.content_stack.addWidget(self.tools_tab)
        self.content_stack.addWidget(self.tasks_tab)
        
        main_layout.addWidget(self.content_stack)
        
        # Create notification area
        self.notification_area = QWidget(self)
        self.notification_area.setObjectName("notificationArea")
        self.notification_area.setFixedWidth(300)
        self.notification_area.setFixedHeight(0)  # Start with 0 height
        self.notification_layout = QVBoxLayout(self.notification_area)
        self.notification_layout.setContentsMargins(0, 0, 0, 0)
        self.notification_layout.setSpacing(5)
        self.notification_area.setLayout(self.notification_layout)
        self.notification_area.move(self.width() - 320, 40)
        self.notification_area.hide()

        # Load settings and agents
        self.load_settings()
        self.populate_agents()
        self.update_send_button_state()
        
        # Create a menu bar with expanded options
        menubar = self.menuBar()
        menubar.setObjectName("mainMenuBar")
        file_menu = menubar.addMenu('File')
        view_menu = menubar.addMenu('View')
        help_menu = menubar.addMenu('Help')
        
        # File menu actions
        settings_action = QAction('Settings', self)
        settings_action.setShortcut('Ctrl+,')
        settings_action.triggered.connect(self.open_settings_dialog)
        file_menu.addAction(settings_action)
        
        file_menu.addSeparator()
        
        quit_action = QAction('Quit', self)
        quit_action.setShortcut('Ctrl+Q')
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        
        # View menu actions
        toggle_theme_action = QAction('Toggle Dark/Light Mode', self)
        toggle_theme_action.setShortcut('Ctrl+T')
        toggle_theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle_theme_action)
        
        # Help menu actions
        keyboard_shortcuts_action = QAction('Keyboard Shortcuts', self)
        keyboard_shortcuts_action.setShortcut('Ctrl+K')
        keyboard_shortcuts_action.triggered.connect(self.show_keyboard_shortcuts)
        help_menu.addAction(keyboard_shortcuts_action)
        
        about_action = QAction('About Cerebro', self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        # Apply dark mode if relevant
        if self.dark_mode:
            self.apply_dark_mode_style()
        else:
            self.apply_light_mode_style()

        # Check tasks regularly
        self.task_timer = QtCore.QTimer(self)
        self.task_timer.timeout.connect(self.check_for_due_tasks)
        self.task_timer.start(30_000)
        
        # Select chat tab initially and set keyboard shortcuts
        self.nav_buttons["chat"].setProperty("selected", True)
        self.setup_keyboard_shortcuts()

    def create_nav_button(self, text, index):
        """Create a navigation button for the sidebar."""
        button = QPushButton(text)
        button.setObjectName("navButton")
        button.setProperty("selected", False)
        button.setCursor(Qt.PointingHandCursor)
        
        # Connect button click to change content stack
        button.clicked.connect(lambda: self.change_tab(index, button))
        
        return button
        
    def change_tab(self, index, button=None):
        """Change the active tab and update button styles."""
        self.content_stack.setCurrentIndex(index)
        
        # Update button styles
        for btn in self.nav_buttons.values():
            btn.setProperty("selected", False)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        
        if button:
            button.setProperty("selected", True)
            button.style().unpolish(button)
            button.style().polish(button)
        
    def setup_keyboard_shortcuts(self):
        """Set up keyboard shortcuts for navigation and actions."""
        # Tab navigation shortcuts
        for i, key in enumerate(['1', '2', '3', '4']):
            shortcut = QShortcut(f"Ctrl+{key}", self)
            shortcut.activated.connect(lambda idx=i: self.change_tab(idx, self.nav_buttons[list(self.nav_buttons.keys())[idx]]))
        
        # Chat actions
        shortcut_send = QShortcut("Ctrl+S", self)
        shortcut_send.activated.connect(lambda: self.chat_tab.on_send_clicked())
        
        shortcut_clear = QShortcut("Ctrl+L", self)
        shortcut_clear.activated.connect(lambda: self.chat_tab.on_clear_chat_clicked())
            
    def show_help_dialog(self):
        """Show the help dialog."""
        QMessageBox.information(self, "Cerebro Help", 
                              "Cerebro is a multi-agent AI chat application.\n\n"
                              "• Chat: Interact with AI agents\n"
                              "• Agents: Configure your AI assistants\n"
                              "• Tools: Manage tools for agents to use\n"
                              "• Tasks: Schedule future agent actions\n\n"
                              "Press Ctrl+K to view keyboard shortcuts.")
    
    def show_keyboard_shortcuts(self):
        """Show keyboard shortcuts dialog."""
        QMessageBox.information(self, "Keyboard Shortcuts",
                              "Ctrl+1: Chat Tab\n"
                              "Ctrl+2: Agents Tab\n"
                              "Ctrl+3: Tools Tab\n"
                              "Ctrl+4: Tasks Tab\n"
                              "Ctrl+S: Send Message\n"
                              "Ctrl+L: Clear Chat\n"
                              "Ctrl+T: Toggle Theme\n"
                              "Ctrl+Q: Quit\n"
                              "Ctrl+K: Show Shortcuts\n"
                              "Ctrl+,: Open Settings")
    
    def show_about_dialog(self):
        """Show about dialog."""
        QMessageBox.about(self, "About Cerebro",
                       "<h2>Cerebro</h2>"
                       "<p>Version 1.0.0</p>"
                       "<p>A multi-agent AI chat application</p>")
                       
    def show_notification(self, message, type="info"):
        """Show a toast notification."""
        self.notifications.append({"message": message, "type": type})
        self.process_notifications()
        
    def process_notifications(self):
        """Process pending notifications."""
        if not self.notifications:
            return
            
        # Get the next notification
        notification = self.notifications.pop(0)
        
        # Create notification widget
        toast = QWidget()
        toast.setObjectName("toast")
        toast.setProperty("type", notification["type"])
        
        toast_layout = QHBoxLayout()
        toast_layout.setContentsMargins(10, 10, 10, 10)
        toast.setLayout(toast_layout)
        
        # Icon based on type (we're not generating images, just using text)
        icon_text = "i" if notification["type"] == "info" else "!"
        icon_label = QLabel(icon_text)
        icon_label.setObjectName("toastIcon")
        icon_label.setFixedSize(24, 24)
        toast_layout.addWidget(icon_label)
        
        # Message
        message_label = QLabel(notification["message"])
        message_label.setWordWrap(True)
        toast_layout.addWidget(message_label)
        
        # Close button
        close_btn = QPushButton("×")
        close_btn.setObjectName("toastCloseButton")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(lambda: self.remove_notification(toast))
        toast_layout.addWidget(close_btn)
        
        # Add to notification area
        self.notification_layout.addWidget(toast)
        self.notification_area.setFixedHeight(
            min(self.height() - 100, 
                self.notification_layout.count() * 80))
        self.notification_area.show()
        
        # Auto-remove after 5 seconds
        QTimer.singleShot(5000, lambda: self.remove_notification(toast))
    
    def remove_notification(self, toast):
        """Remove a notification toast."""
        if toast and toast.parentWidget() == self.notification_area: # Robust check: Widget exists and is parented correctly
            self.notification_layout.removeWidget(toast)
            toast.deleteLater()

            # Hide notification area if empty
            if self.notification_layout.count() == 0:
                self.notification_area.hide()
            else:
                self.notification_area.setFixedHeight(
                    min(self.height() - 100,
                        self.notification_layout.count() * 80))
    
    def toggle_theme(self):
        """Toggle between dark and light mode."""
        self.dark_mode = not self.dark_mode
        self.apply_updated_styles()
        self.save_settings()
        
        theme_name = "Dark" if self.dark_mode else "Light"
        self.show_notification(f"Switched to {theme_name} Mode")

    # -------------------------------------------------------------------------
    # Settings Dialog
    # -------------------------------------------------------------------------
    def open_settings_dialog(self):
        # Create a QDialog for settings
        from dialogs import SettingsDialog
        settings_dialog = SettingsDialog(self)
        if settings_dialog.exec_() == QDialog.Accepted:
            # Update settings based on user input
            settings_data = settings_dialog.get_data()
            self.dark_mode = settings_data["dark_mode"]
            self.user_name = settings_data["user_name"]
            self.user_color = settings_data["user_color"]
            self.debug_enabled = settings_data["debug_enabled"]
            self.apply_updated_styles()
            self.agents_tab.load_global_preferences()
            self.save_settings()
            self.show_notification("Settings updated successfully")

    def apply_updated_styles(self):
        if self.dark_mode:
            self.apply_dark_mode_style()
        else:
            self.apply_light_mode_style()

    # -------------------------------------------------------------------------
    # Chat / UI Utility
    # -------------------------------------------------------------------------
    def send_message(self, user_text):
        # Disable send button to prevent multiple clicks
        self.chat_tab.send_button.setEnabled(False)
        
        # Show typing indicator
        self.chat_tab.show_typing_indicator()
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        user_message_html = f'<span style="color:{self.user_color};">[{timestamp}] {self.user_name}:</span> {user_text}'
        self.chat_tab.append_message_html(user_message_html)

        user_message = {"role": "user", "content": user_text}
        self.chat_history.append(user_message)

        # If a Coordinator agent is enabled, send the message to the Coordinator agents only.
        enabled_coordinator_agents = [
            (agent_name, agent_settings)
            for agent_name, agent_settings in self.agents_data.items()
            if agent_settings.get('enabled', False) and agent_settings.get('role') == 'Coordinator'
        ]

        # If no Coordinator is enabled, fall back to the old logic of sending to all enabled agents, except Specialists.
        if not enabled_coordinator_agents:
            enabled_agents = [
                (agent_name, agent_settings)
                for agent_name, agent_settings in self.agents_data.items()
                if agent_settings.get('enabled', False)
                and not agent_settings.get('desktop_history_enabled', False)
                and agent_settings.get('role') != 'Specialist'
            ]

            if not enabled_agents:
                self.chat_tab.hide_typing_indicator()
                QMessageBox.warning(self, "No Agents Enabled", "Please enable at least one Assistant agent or a Coordinator agent.")
                self.chat_tab.send_button.setEnabled(True)  # Re-enable send button
                return
        else:
            enabled_agents = enabled_coordinator_agents

        def process_next_agent(index):
            if index is None or index >= len(enabled_agents):
                self.chat_tab.send_button.setEnabled(True)  # Re-enable send button after all agents have responded
                self.chat_tab.hide_typing_indicator()
                return

            agent_name, agent_settings = enabled_agents[index]
            if self.debug_enabled:
                print(f"[Debug] Processing agent: {agent_name}")

            model_name = agent_settings.get("model", "llama3.2-vision").strip()
            if not model_name:
                QMessageBox.warning(self, "Invalid Model Name", f"Agent '{agent_name}' has no valid model name.")
                process_next_agent(index + 1)
                return

            temperature = agent_settings.get("temperature", 0.7)
            max_tokens = agent_settings.get("max_tokens", 512)
            
            # Build appropriate chat history
            if agent_settings.get('role') == 'Coordinator':
                chat_history = self.build_agent_chat_history(agent_name, user_message)
            elif agent_settings.get('role') == 'Specialist':
                chat_history = self.build_agent_chat_history(agent_name)
            else: # Default to old behavior for Assistant agents
                chat_history = self.build_agent_chat_history(agent_name)
            
            thread = QThread()
            # Pass the agents_data to the AIWorker
            worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data)
            worker.moveToThread(thread)
            self.active_worker_threads.append((worker, thread))

            def on_finished():
                self.worker_finished_sequential(worker, thread, agent_name, index, process_next_agent)

            worker.response_received.connect(self.handle_ai_response_chunk)
            worker.error_occurred.connect(self.handle_worker_error)
            worker.finished.connect(on_finished)

            thread.started.connect(worker.run)
            thread.start()

        process_next_agent(0)

    def clear_chat(self):
        if self.debug_enabled:
            print("[Debug] Clearing chat.")
        self.chat_tab.chat_display.clear()
        self.chat_history = []
        self.show_notification("Chat cleared")

    def handle_ai_response_chunk(self, chunk, agent_name):
        if agent_name not in self.current_responses:
            self.current_responses[agent_name] = ''
        self.current_responses[agent_name] += chunk

    def handle_worker_error(self, error_message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.chat_tab.append_message_html(f"[{timestamp}] {error_message}")
        self.chat_tab.hide_typing_indicator()
        self.show_notification(f"Error: {error_message}", "error")

    def worker_finished_sequential(self, sender_worker, thread, agent_name, index, process_next_agent):
        assistant_content = self.current_responses.get(agent_name, "")
        if agent_name in self.current_responses:
            del self.current_responses[agent_name]

        tool_request = None
        task_request = None
        content = assistant_content.strip()

        # Get the agent's settings
        agent_settings = self.agents_data.get(agent_name, {})

        # Check if this is a Specialist agent and if it was called by the Coordinator
        if agent_settings.get('role') == 'Specialist':
            if self.chat_history and self.chat_history[-1]['role'] == 'assistant':
                last_message = self.chat_history[-1]['content']
                if last_message.endswith(f"Next Response By: {agent_name}"):
                    # This is a valid response from a Specialist to the Coordinator
                    content = "[Response to Coordinator] " + content
                else:
                    # Specialist is not supposed to respond unless called by the Coordinator
                    if process_next_agent is not None and index is not None:
                        process_next_agent(index + 1)
                    return
            else:
                if process_next_agent is not None and index is not None:
                    process_next_agent(index + 1)
                return

        # Parse the content as JSON if it's a Coordinator or Specialist response
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
        agent_color = self.agents_data.get(agent_name, {}).get("color", "#000000")

        # If the message is from a Coordinator and contains "Next Response By:", extract the next agent's name.
        next_agent = None
        if agent_settings.get('role') == 'Coordinator' and "Next Response By:" in content:
            parts = content.split("Next Response By:")
            content = parts[0].strip()  # The part before "Next Response By:"
            next_agent = parts[1].strip()

        # Debugging: Print content before modification
        if self.debug_enabled:
            print(f"[Debug] Content before modification: '{content}'")

        if agent_settings.get('role') == 'Coordinator':
            # Ensure the Coordinator's message ends with "Next Response By: [Agent Name]"
            if content and next_agent and not content.endswith(f"Next Response By: {next_agent}"):
                content += f"\nNext Response By: {next_agent}"
                
        # Debugging: Print content after modification
        if self.debug_enabled:
            print(f"[Debug] Content after modification: '{content}'")

        # Display the message from the Coordinator or Assistant
        if agent_settings.get('role') in ['Coordinator', 'Assistant']:
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
                
                # Check if the message is from a Specialist responding to Coordinator
                if clean_content.startswith("[Response to Coordinator]"):
                    clean_content = clean_content.replace("[Response to Coordinator]", "").strip()
                
                # Create displayed content with collapsible thought if present
                if thought:
                    thought_content = thought.replace("<thought>", "").replace("</thought>", "").strip()
                    display_content = f"{clean_content}<br><details><summary><i>Agent thoughts...</i></summary><pre style='background-color:#f5f5f5;padding:8px;border-radius:5px;color:#333;'>{thought_content}</pre></details>"
                else:
                    display_content = clean_content
                
                self.chat_tab.append_message_html(
                    f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {display_content}"
                )
                
                # Store only the clean content without thoughts in history
                self.chat_history.append({"role": "assistant", "content": clean_content, "agent": agent_name})
        
        # Display the message from a Specialist if specified by Coordinator
        elif agent_settings.get('role') == 'Specialist' and any(msg['content'].strip().endswith(f"Next Response By: {agent_name}") for msg in self.chat_history):
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
            
            # Create displayed content with collapsible thought if present
            if thought:
                thought_content = thought.replace("<thought>", "").replace("</thought>", "").strip()
                display_content = f"{clean_content}<br><details><summary><i>Agent thoughts...</i></summary><pre style='background-color:#f5f5f5;padding:8px;border-radius:5px;color:#333;'>{thought_content}</pre></details>"
            else:
                display_content = clean_content
            
            self.chat_tab.append_message_html(
                f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {display_content}"
            )
            
            # Store only the clean content without thoughts in history
            self.chat_history.append({"role": "assistant", "content": clean_content, "agent": agent_name})

        # If there's a next agent specified and it's managed by the Coordinator, process it.
        if next_agent:
            managed_agents = agent_settings.get('managed_agents', [])
            if next_agent in managed_agents:
                # Send the user's original message to the next agent.
                # We assume that the user's message is always the last message with role 'user'.
                user_message = next((msg for msg in reversed(self.chat_history) if msg["role"] == "user"), None)
                if user_message:
                    self.send_message_to_agent(next_agent, user_message['content'])
            else:
                error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{next_agent}' is not managed by Coordinator '{agent_name}'.</span>"
                self.chat_tab.append_message_html(error_msg)
                self.show_notification(f"Error: Agent '{next_agent}' is not managed by Coordinator", "error")
        
        # We should always call process_next_agent if there is one to trigger the next agent.
        elif process_next_agent is not None and index is not None:
            process_next_agent(index + 1)

        # Handle tool request if any, only if the agent is allowed to use tools
        if tool_request and agent_settings.get("tool_use", False):
            tool_name = tool_request.get("name", "")
            tool_args = tool_request.get("args", {})
            
            # Check if the requested tool is enabled for the agent
            enabled_tools = agent_settings.get("tools_enabled", [])
            if tool_name not in enabled_tools:
                error_msg = f"[{timestamp}] <span style='color:red;'>[Tool Error] Tool '{tool_name}' is not enabled for agent '{agent_name}'.</span>"
                self.chat_tab.append_message_html(error_msg)
                self.chat_history.append({"role": "assistant", "content": error_msg, "agent": agent_name})
                self.show_notification(f"Tool Error: '{tool_name}' not enabled for agent", "error")
            else:
                self.show_notification(f"Agent '{agent_name}' is using tool: {tool_name}", "info")
                tool_result = run_tool(self.tools, tool_name, tool_args, self.debug_enabled)

                # Check for tool errors and handle them
                if tool_result.startswith("[Tool Error]"):
                    error_msg = f"[{timestamp}] <span style='color:red;'>{tool_result}</span>"
                    self.chat_tab.append_message_html(error_msg)
                    # Append error message to chat history
                    self.chat_history.append({"role": "assistant", "content": error_msg, "agent": agent_name})
                    self.show_notification(f"Tool Error: {tool_result}", "error")
                else:
                    display_message = f"{agent_name} used {tool_name} with args {tool_args}\nTool Result: {tool_result}"
                    self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:{agent_color};'>{display_message}</span>")
                    self.chat_history.append({"role": "assistant", "content": display_message, "agent": agent_name})
                    self.show_notification(f"Tool executed successfully: {tool_name}", "info")

        # Handle task request if any
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
                    debug_enabled=self.debug_enabled
                )
                note = f"Agent '{agent_name}' scheduled a new task for '{agent_for_task}' at {due_time}."
                self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:{agent_color};'>{note}</span>")
                self.show_notification(f"New task scheduled for {due_time}", "info")
            else:
                warn_msg = "[Task Error] Missing due_time in request."
                self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:red;'>{warn_msg}</span>")
                self.show_notification("Task Error: Missing due time", "error")

        if self.debug_enabled and agent_name:
            print(f"[Debug] Worker for agent '{agent_name}' finished.")

        thread.quit()
        thread.wait()

        for i, (worker_item, thread_item) in enumerate(self.active_worker_threads):
            if worker_item == sender_worker:
                del self.active_worker_threads[i]
                break

        sender_worker.deleteLater()
        thread.deleteLater()

        if process_next_agent is not None and index is not None:
            process_next_agent(index + 1)

    def send_message_to_agent(self, agent_name, message):
        """
        Sends a message to a specific agent.
        This is used by the Coordinator to direct messages to managed agents.
        """
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Construct a message to indicate which agent should respond next
        formatted_message = f"{message}\nNext Response By: {agent_name}"

        # Add this message to the chat history
        self.chat_history.append({"role": "user", "content": formatted_message})

        # Find the agent settings
        agent_settings = self.agents_data.get(agent_name, {})
        if not agent_settings:
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{agent_name}' not found.</span>"
            self.chat_tab.append_message_html(error_msg)
            self.show_notification(f"Error: Agent '{agent_name}' not found", "error")
            return

        # If the agent is enabled, start a worker thread to process the message
        if agent_settings.get('enabled', False):
            model_name = agent_settings.get("model", "llama3.2-vision").strip()
            temperature = agent_settings.get("temperature", 0.7)
            max_tokens = agent_settings.get("max_tokens", 512)
            chat_history = self.build_agent_chat_history(agent_name)

            thread = QThread()
            # Pass the agents_data to the AIWorker
            worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data)
            worker.moveToThread(thread)
            self.active_worker_threads.append((worker, thread))

            def on_finished():
                self.worker_finished_sequential(worker, thread, agent_name, None, process_next_agent=None)

            worker.response_received.connect(self.handle_ai_response_chunk)
            worker.error_occurred.connect(self.handle_worker_error)
            worker.finished.connect(on_finished)

            thread.started.connect(worker.run)
            thread.start()
        else:
            error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{agent_name}' is not enabled.</span>"
            self.chat_tab.append_message_html(error_msg)
            self.show_notification(f"Error: Agent '{agent_name}' is not enabled", "error")

    # -------------------------------------------------------------------------
    # Agents / Settings Management
    # -------------------------------------------------------------------------
    def populate_agents(self):
        self.agents_data = {}
        if os.path.exists(AGENTS_SAVE_FILE):
            try:
                with open(AGENTS_SAVE_FILE, "r") as f:
                    self.agents_data = json.load(f)
                if self.debug_enabled:
                    print("[Debug] Agents loaded.")
            except Exception as e:
                print(f"[Debug] Failed to load agents: {e}")
        else:
            default_agent_settings = {
                "model": "llama3.2-vision",
                "temperature": 0.7,
                "max_tokens": 512,
                "system_prompt": "",
                "enabled": True,
                "color": "#000000",
                "include_image": False,
                "desktop_history_enabled": False,
                "screenshot_interval": 5,
                "role": "Assistant",  # Default role
                "description": "A general-purpose assistant.", # Default description
                "tool_use": False,
                "tools_enabled": []
            }
            self.agents_data["Default Agent"] = default_agent_settings
            if self.debug_enabled:
                print("[Debug] Default agent added.")

        self.agents_tab.agent_selector.clear()
        for agent_name in self.agents_data.keys():
            self.agents_tab.agent_selector.addItem(agent_name)

        if self.agents_tab.agent_selector.count() > 0:
            self.agents_tab.load_agent_settings(self.agents_tab.agent_selector.currentText())

    def add_agent(self):
        from PyQt5.QtWidgets import QInputDialog
        agent_name, ok = QInputDialog.getText(self, "Add Agent", "Enter agent name:")
        if ok and agent_name.strip():
            agent_name = agent_name.strip()
            if agent_name not in self.agents_data:
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
                    "tools_enabled": []
                }
                self.agents_tab.agent_selector.addItem(agent_name)
                self.save_agents()
                if self.debug_enabled:
                    print(f"[Debug] Agent '{agent_name}' added.")
                self.show_notification(f"Agent '{agent_name}' created successfully", "info")
            else:
                QMessageBox.warning(self, "Agent Exists", "Agent already exists.")
        self.update_send_button_state()

    def delete_agent(self):
        current_agent = self.agents_tab.agent_selector.currentText()
        if current_agent:
            if current_agent in self.agents_data:
                del self.agents_data[current_agent]
                idx = self.agents_tab.agent_selector.currentIndex()
                self.agents_tab.agent_selector.removeItem(idx)
                self.save_agents()
                if self.debug_enabled:
                    print(f"[Debug] Agent '{current_agent}' removed.")
                self.show_notification(f"Agent '{current_agent}' deleted", "info")
        self.update_send_button_state()

    def save_agents(self):
        try:
            with open(AGENTS_SAVE_FILE, "w") as f:
                json.dump(self.agents_data, f, indent=4)
            if self.debug_enabled:
                print("[Debug] Agents saved.")
        except Exception as e:
            print(f"[Debug] Failed to save agents: {e}")
            self.show_notification(f"Error saving agents: {str(e)}", "error")

    def update_send_button_state(self):
        any_enabled = any(
            a.get("enabled", False)
            for a in self.agents_data.values()
            if not a.get("desktop_history_enabled", False)
            and a.get("role") != 'Specialist'
        )
        self.chat_tab.send_button.setEnabled(any_enabled)

    # -------------------------------------------------------------------------
    # Tools Management
    # -------------------------------------------------------------------------
    def refresh_tools_list(self):
        self.tools = load_tools(self.debug_enabled)
        if hasattr(self.tools_tab, "refresh_tools_list"):
            self.tools_tab.tools = self.tools
            self.tools_tab.refresh_tools_list()
            self.show_notification("Tools list refreshed", "info")

    # -------------------------------------------------------------------------
    # Tasks / Scheduling
    # -------------------------------------------------------------------------
    def check_for_due_tasks(self):
        now = datetime.now()
        to_remove = []
        for t in self.tasks:
            due_str = t.get("due_time", "")
            try:
                if "T" in due_str:
                    due_dt = datetime.fromisoformat(due_str)
                else:
                    due_dt = datetime.strptime(due_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            if now >= due_dt:
                agent_name = t.get("agent_name", "")
                prompt = t.get("prompt", "")
                self.schedule_user_message(agent_name, prompt, t["id"])
                to_remove.append(t["id"])
                self.show_notification(f"Executing scheduled task for {agent_name}", "info")

        for task_id in to_remove:
            delete_task(self.tasks, task_id, debug_enabled=self.debug_enabled)
            save_tasks(self.tasks, debug_enabled=self.debug_enabled)

    def schedule_user_message(self, agent_name, prompt, task_id=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        message_html = f'<span style="color:{self.user_color};">[{timestamp}] (Scheduled) {self.user_name}:</span> {prompt}'
        self.chat_tab.append_message_html(message_html)

        user_message = {"role": "user", "content": prompt}
        self.chat_history.append(user_message)

        agent_settings = self.agents_data.get(agent_name, None)
        if not agent_settings:
            msg = f"[Task Error] Agent '{agent_name}' not found for Task '{task_id}'"
            self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:red;'>{msg}</span>")
            self.show_notification(msg, "error")
            return

        if not agent_settings.get("enabled", False):
            msg = f"[Task Error] Agent '{agent_name}' is disabled. Task '{task_id}' skipped."
            self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:red;'>{msg}</span>")
            self.show_notification(msg, "error")
            return

        model_name = agent_settings.get("model", "llama3.2-vision").strip()
        temperature = agent_settings.get("temperature", 0.7)
        max_tokens = agent_settings.get("max_tokens", 512)
        chat_history = self.build_agent_chat_history(agent_name)

        thread = QThread()
        # Pass the agents_data to the AIWorker
        worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        def on_finished():
            self.worker_finished_sequential(worker, thread, agent_name, None, None)

        worker.response_received.connect(self.handle_ai_response_chunk)
        worker.error_occurred.connect(self.handle_worker_error)
        worker.finished.connect(on_finished)

        thread.started.connect(worker.run)
        thread.start()

    # -------------------------------------------------------------------------
    # Chat History Helpers
    # -------------------------------------------------------------------------
    def build_agent_chat_history(self, agent_name, user_message=None, is_screenshot=False):
        system_prompt = ""
        agent_settings = self.agents_data.get(agent_name, {})

        if agent_settings:
            # If the agent is a Coordinator, include managed agents and their descriptions in the system prompt
            if agent_settings.get('role') == 'Coordinator':
                managed_agents_info = []
                for managed_agent_name in agent_settings.get('managed_agents', []):
                    managed_agent_settings = self.agents_data.get(managed_agent_name, {})
                    if managed_agent_settings:
                        managed_agent_desc = managed_agent_settings.get('description', 'No description available')
                        managed_agents_info.append(f"{managed_agent_name}: {managed_agent_desc}")
                
                if managed_agents_info:
                    system_prompt += "You can choose from the following agents:\n" + "\n".join(managed_agents_info) + "\n"

            # Include the agent's specific system prompt
            system_prompt += agent_settings.get("system_prompt", "")

            # Include tool instructions only if tool_use is enabled
            if agent_settings.get("tool_use", False):
                tool_instructions = self.generate_tool_instructions_message(agent_name)
                system_prompt += "\n" + tool_instructions

        # Build the chat history with the constructed system prompt
        chat_history = [{"role": "system", "content": system_prompt}]

        # Filter messages for the chat history
        temp_history = []
        for msg in self.chat_history:
            # For user messages, include them as is
            if msg['role'] == 'user':
                temp_history.append(msg)
            elif msg['role'] == 'assistant':
                # Remove any thought tags before adding to history
                content = msg['content']
                if "<thought>" in content and "</thought>" in content:
                    thought_start = content.find("<thought>")
                    thought_end = content.find("</thought>") + len("</thought>")
                    clean_content = content[:thought_start] + content[thought_end:]
                    clean_content = clean_content.strip()
                    # Create a new message with the clean content
                    cleaned_msg = msg.copy()
                    cleaned_msg["content"] = clean_content
                    
                    # Only include messages from this agent or specialists to coordinator
                    if cleaned_msg.get('agent') == agent_name:
                        temp_history.append(cleaned_msg)
                    elif agent_settings.get('role') == 'Coordinator' and self.agents_data.get(cleaned_msg.get('agent'), {}).get('role') == 'Specialist':
                        temp_history.append(cleaned_msg)
                else:
                    # No thought tags, include message if from this agent or specialists to coordinator
                    if msg.get('agent') == agent_name:
                        temp_history.append(msg)
                    elif agent_settings.get('role') == 'Coordinator' and self.agents_data.get(msg.get('agent'), {}).get('role') == 'Specialist':
                        temp_history.append(msg)

        # If the last message indicates a handoff to a Specialist, insert the Specialist's description AFTER the handoff message
        if temp_history:
            last_message = temp_history[-1]
            if last_message['role'] == 'assistant' and "Next Response By:" in last_message['content']:
                next_agent_name = last_message['content'].split("Next Response By:")[1].strip()
                next_agent_settings = self.agents_data.get(next_agent_name, {})
                if next_agent_settings.get('role') == 'Specialist':
                    specialist_description = next_agent_settings.get('description', '')
                    if specialist_description:
                        # Append the specialist description as an assistant message
                        temp_history.append({"role": "assistant", "content": specialist_description, "agent": next_agent_name})

        # Add the user message to the history if provided
        if user_message:
            temp_history.append(user_message)

        chat_history.extend(temp_history)
        return chat_history


    def generate_tool_instructions_message(self, agent_name):
        agent_settings = self.agents_data.get(agent_name, {})
        if agent_settings.get("tool_use", False):
            enabled_tools = agent_settings.get("tools_enabled", [])
            tool_list_str = ""
            for t in self.tools:
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
                '     "name": "<tool_name>",\n'
                '     "args": { ... }\n'
                ' }\n'
                '}\n'
                "No extra text outside this JSON when calling a tool.\n"
                f"Available tools:\n{tool_list_str}"
            )
            return instructions
        else:
            return ""

    # -------------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------------
    def save_settings(self):
        settings = {
            "debug_enabled": self.debug_enabled,
            "include_image": self.include_image,
            "include_screenshot": self.include_screenshot,
            "image_path": "",
            "user_name": self.user_name,
            "user_color": self.user_color,
            "dark_mode": self.dark_mode
        }
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(settings, f)
            if self.debug_enabled:
                print("[Debug] Settings saved.")
        except Exception as e:
            print(f"[Error failed to save settings: {e}")
            self.show_notification(f"Error saving settings: {str(e)}", "error")

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    settings = json.load(f)
                self.debug_enabled = settings.get("debug_enabled", False)
                self.include_image = settings.get("include_image", False)
                self.include_screenshot = settings.get("include_screenshot", False)
                self.user_name = settings.get("user_name", "You")
                self.user_color = settings.get("user_color", "#0000FF")
                self.dark_mode = settings.get("dark_mode", False)
                if self.debug_enabled:
                    print("[Debug] Settings loaded.")
            except Exception as e:
                print(f"[Error] Failed to load settings: {e}")
                
        self.agents_tab.load_global_preferences()

    # -------------------------------------------------------------------------
    # Dark/Light Mode
    # -------------------------------------------------------------------------
    def apply_dark_mode_style(self):
        with open("dark_mode.qss", "r") as f:
            style_sheet = f.read()
        self.setStyleSheet(style_sheet)

    def apply_light_mode_style(self):
        with open("light_mode.qss", "r") as f:
            style_sheet = f.read()
        self.setStyleSheet(style_sheet)

    # -------------------------------------------------------------------------
    # Close Event
    # -------------------------------------------------------------------------
    def closeEvent(self, event):
        for worker, thread in self.active_worker_threads:
            thread.quit()
            thread.wait()
            worker.deleteLater()
            thread.deleteLater()
        self.active_worker_threads.clear()
        event.accept()