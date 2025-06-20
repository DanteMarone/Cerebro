#app.py
import os
import json
import time
from datetime import datetime, timedelta
from PyQt5 import QtCore
from PyQt5.QtCore import QThread, Qt, QTimer, QObject, pyqtSignal, QUrl
from PyQt5 import sip

from screenshot import ScreenshotManager
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox, QApplication, QAction, QMenu, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QStackedWidget,
    QInputDialog, QScrollArea, QShortcut, QSystemTrayIcon, QStyle
)
from PyQt5.QtGui import QKeySequence

from theme_utils import load_style_sheet
from log_utils import setup_logging, get_log_file_path, format_user_friendly
import logging

from worker import AIWorker
from tools import load_tools, run_tool
from tasks import load_tasks, save_tasks, add_task, delete_task, update_task_due_time
from automation_sequences import load_automations
from workflows import (
    load_workflows,
    save_workflows,
    find_workflow_by_name,
    execute_workflow,
)
from transcripts import (
    load_history,
    append_message,
    clear_history,
    export_history,
    summarize_history,
)
from tab_chat import ChatTab
from tab_agents import AgentsTab
from tab_tools import ToolsTab
from tab_plugins import PluginsTab
from tab_automations import AutomationsTab
from tab_tasks import TasksTab
from tab_metrics import MetricsTab
from tab_finetune import FinetuneTab
from tab_docs import DocumentationTab
from tab_workflows import WorkflowsTab, WorkflowRunnerDialog
from metrics import load_metrics, record_tool_usage, record_response_time
from tool_utils import (
    generate_tool_instructions_message,
    format_tool_call_html,
    format_tool_result_html,
    format_tool_block_html,
)
from local_llm_helper import get_installed_models
import tts

AGENTS_SAVE_FILE = "agents.json"
SETTINGS_FILE = "settings.json"
TOOLS_FILE = "tools.json"
TASKS_FILE = "tasks.json"


class UpdateCheckWorker(QObject):
    """Worker that checks for application updates."""

    finished = pyqtSignal(str)

    def __init__(self, tools, debug_enabled=False):
        super().__init__()
        self.tools = tools
        self.debug_enabled = debug_enabled

    def run(self):
        result = run_tool(self.tools, "update-manager", {"action": "check"}, self.debug_enabled)
        self.finished.emit(result)

class AIChatApp(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Check for debug mode (enabled by default)
        if os.environ.get("DEBUG_MODE", "1") == "0":
            self.debug_enabled = False
        else:
            self.debug_enabled = True
        setup_logging(self.debug_enabled)

        # Basic window settings
        self.setWindowTitle("Cerebro 1.0")
        self.setGeometry(100, 100, 1000, 700)  # Larger default window

        # Variables
        clear_history(self.debug_enabled)
        self.chat_history = []
        self.current_responses = {}
        self.agents_data = {}
        self.include_image = False
        self.include_screenshot = False
        self.current_agent_color = "#000000"
        self.user_name = "You"
        self.user_color = "#0000FF"
        self.accent_color = "#803391"
        self.dark_mode = True
        self.screenshot_interval = 5
        self.ollama_port = 11434
        self.api_url = self.build_api_url()
        self.screenshot_manager = ScreenshotManager()
        self.active_worker_threads = []
        self.notifications_paused = False
        self.screenshot_paused = False
        self.summarization_threshold = 20
        self.agents_onboarding_complete = False
        
        # Initialize notification system
        self.notifications = []
        self.notification_timer = QTimer(self)
        self.notification_timer.timeout.connect(self.process_notifications)
        self.notification_timer.start(3000)  # Check every 3 seconds

        # Load Tools, Automations, Tasks, and Metrics
        self.tools = load_tools(self.debug_enabled)
        self.automations = load_automations(self.debug_enabled)
        self.tasks = load_tasks(self.debug_enabled)
        self.workflows = load_workflows(self.debug_enabled)
        self.metrics = load_metrics(self.debug_enabled)
        self.response_start_times = {}
        
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
        self.nav_buttons["agents"].setToolTip("Manage automated workers that perform tasks.")
        sidebar_layout.addWidget(self.nav_buttons["agents"])
        
        # Tools button
        self.nav_buttons["tools"] = self.create_nav_button("Tools", 2)
        sidebar_layout.addWidget(self.nav_buttons["tools"])

        # Plugins button
        self.nav_buttons["plugins"] = self.create_nav_button("Plugins", 3)
        sidebar_layout.addWidget(self.nav_buttons["plugins"])

        # Automations button
        self.nav_buttons["automations"] = self.create_nav_button("Automations", 4)
        sidebar_layout.addWidget(self.nav_buttons["automations"])

        # Tasks button
        self.nav_buttons["tasks"] = self.create_nav_button("Tasks", 5)
        sidebar_layout.addWidget(self.nav_buttons["tasks"])

        # Workflows button
        self.nav_buttons["workflows"] = self.create_nav_button("Workflows", 6)
        sidebar_layout.addWidget(self.nav_buttons["workflows"])

        # Metrics button
        self.nav_buttons["metrics"] = self.create_nav_button("Metrics", 7)
        sidebar_layout.addWidget(self.nav_buttons["metrics"])

        # Finetune button
        self.nav_buttons["finetune"] = self.create_nav_button("Finetune", 8)
        sidebar_layout.addWidget(self.nav_buttons["finetune"])

        # Docs button
        self.nav_buttons["docs"] = self.create_nav_button("Docs", 9)
        sidebar_layout.addWidget(self.nav_buttons["docs"])
        
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
        self.plugins_tab = PluginsTab(self)
        self.automations_tab = AutomationsTab(self)
        self.tasks_tab = TasksTab(self)
        self.workflows_tab = WorkflowsTab(self)
        self.metrics_tab = MetricsTab(self)
        self.finetune_tab = FinetuneTab(self)
        self.docs_tab = DocumentationTab(self)
        
        # Add pages to stacked widget
        self.content_stack.addWidget(self.chat_tab)
        self.content_stack.addWidget(self.agents_tab)
        self.content_stack.addWidget(self.tools_tab)
        self.content_stack.addWidget(self.plugins_tab)
        self.content_stack.addWidget(self.automations_tab)
        self.content_stack.addWidget(self.tasks_tab)
        self.content_stack.addWidget(self.workflows_tab)
        self.content_stack.addWidget(self.metrics_tab)
        self.content_stack.addWidget(self.finetune_tab)
        self.content_stack.addWidget(self.docs_tab)
        
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
        self.update_screenshot_timer()
        
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
        quit_action.triggered.connect(self.quit_from_tray)
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

        check_updates_action = QAction('Check for Updates', self)
        check_updates_action.triggered.connect(lambda: self.check_for_updates(True))
        help_menu.addAction(check_updates_action)

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

        # Create system tray icon
        self.force_quit = False
        self.create_tray_icon()

        QTimer.singleShot(1000, self.check_for_updates)

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
        # Revert unsaved agent changes when leaving the edit screen
        if (
            self.content_stack.currentIndex() == 1
            and self.agents_tab.stacked.currentWidget() == self.agents_tab.edit_page
        ):
            self.agents_tab.show_agent_list()

        self.content_stack.setCurrentIndex(index)

        if index == 1 and not self.agents_onboarding_complete:
            self.show_agents_onboarding()
        
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
        for i, key in enumerate(['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']):
            shortcut = QShortcut(f"Ctrl+{key}", self)
            shortcut.activated.connect(lambda idx=i: self.change_tab(idx, self.nav_buttons[list(self.nav_buttons.keys())[idx]]))
        
        # Chat actions
        shortcut_send = QShortcut("Ctrl+S", self)
        shortcut_send.activated.connect(lambda: self.chat_tab.on_send_clicked())

        shortcut_clear = QShortcut("Ctrl+L", self)
        shortcut_clear.activated.connect(lambda: self.chat_tab.on_clear_chat_clicked())

    def create_tray_icon(self):
        """Create the system tray icon and its menu."""
        self.tray_icon = QSystemTrayIcon(self)
        icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray_icon.setIcon(icon)

        tray_menu = QMenu(self)

        open_action = QAction("Open Cerebro", self)
        open_action.triggered.connect(self.show)
        tray_menu.addAction(open_action)

        add_task_action = QAction("New Task", self)
        add_task_action.triggered.connect(self.tasks_tab.add_task_ui)
        tray_menu.addAction(add_task_action)

        toggle_action = QAction("Toggle Dark Mode", self)
        toggle_action.triggered.connect(self.toggle_theme)
        tray_menu.addAction(toggle_action)

        self.pause_notifications_action = QAction("Pause Notifications", self)
        self.pause_notifications_action.triggered.connect(self.toggle_notifications)
        tray_menu.addAction(self.pause_notifications_action)

        text = (
            "Stop Screenshot Capture"
            if self.screenshot_manager.timer.isActive()
            else "Start Screenshot Capture"
        )
        self.screenshot_capture_action = QAction(text, self)
        self.screenshot_capture_action.triggered.connect(self.toggle_screenshot_capture)
        tray_menu.addAction(self.screenshot_capture_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_from_tray)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def quit_from_tray(self):
        """Quit the application from the tray icon."""
        self.force_quit = True
        if getattr(self, "tray_icon", None):
            self.tray_icon.hide()
        QApplication.quit()
            
    def show_help_dialog(self):
        """Show the help dialog."""
        QMessageBox.information(self, "Cerebro Help",
                              "Cerebro is a multi-agent AI chat application.\n\n"
                              "• Chat: Interact with AI agents\n"
                              "• Agents: Configure your AI assistants\n"
                              "• Tools: Manage tools for agents to use\n"
                              "• Automations: Record and run button sequences\n"
                              "• Tasks: Schedule future agent actions\n\n"
                              "• Docs: View the built-in user guide\n\n"
                              "Press Ctrl+K to view keyboard shortcuts.")

    def show_agents_onboarding(self):
        """Display a brief onboarding message for the Agents tab."""
        QMessageBox.information(
            self,
            "Welcome to Agents",
            "Agents are automated workers that perform tasks. Configure them here."
        )
        self.agents_onboarding_complete = True
        self.save_settings()
    
    def show_keyboard_shortcuts(self):
        """Show keyboard shortcuts dialog."""
        QMessageBox.information(
            self,
            "Keyboard Shortcuts",
            "Ctrl+1: Chat Tab\n"
            "Ctrl+2: Agents Tab\n"
            "Ctrl+3: Tools Tab\n"
            "Ctrl+4: Plugins Tab\n"
            "Ctrl+5: Automations Tab\n"
            "Ctrl+6: Tasks Tab\n"
            "Ctrl+7: Workflows Tab\n"
            "Ctrl+8: Metrics Tab\n"
            "Ctrl+9: Docs Tab\n"
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
        if not self.notifications_paused:
            self.process_notifications()
        
    def process_notifications(self):
        """Process pending notifications."""
        if self.notifications_paused or not self.notifications:
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
        """Safely remove a notification toast."""
        if not toast or sip.isdeleted(toast):
            return

        try:
            if toast.parentWidget() == self.notification_area:
                self.notification_layout.removeWidget(toast)
                toast.deleteLater()

                # Hide notification area if empty
                if self.notification_layout.count() == 0:
                    self.notification_area.hide()
                else:
                    self.notification_area.setFixedHeight(
                        min(self.height() - 100,
                            self.notification_layout.count() * 80))
        except RuntimeError:
            # The widget was already destroyed
            pass
    
    def toggle_theme(self):
        """Toggle between dark and light mode."""
        self.dark_mode = not self.dark_mode
        self.apply_updated_styles()
        self.save_settings()

        theme_name = "Dark" if self.dark_mode else "Light"
        self.show_notification(f"Switched to {theme_name} Mode")

    def toggle_notifications(self):
        """Pause or resume toast notifications."""
        self.notifications_paused = not self.notifications_paused
        text = "Resume Notifications" if self.notifications_paused else "Pause Notifications"
        self.pause_notifications_action.setText(text)
        if not self.notifications_paused:
            self.process_notifications()
        state = "paused" if self.notifications_paused else "resumed"
        self.show_notification(f"Notifications {state}")

    def toggle_screenshot_capture(self):
        """Start or stop screenshot capture."""
        self.screenshot_paused = not self.screenshot_paused
        if self.screenshot_paused:
            self.screenshot_manager.stop()
            self.screenshot_capture_action.setText("Start Screenshot Capture")
            self.show_notification("Screenshot capture stopped")
        else:
            self.update_screenshot_timer()
            self.screenshot_capture_action.setText("Stop Screenshot Capture")
            self.show_notification("Screenshot capture started")

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
            self.accent_color = settings_data.get("accent_color", self.accent_color)
            self.debug_enabled = settings_data["debug_enabled"]
            self.screenshot_interval = settings_data.get(
                "screenshot_interval", self.screenshot_interval
            )
            self.summarization_threshold = settings_data.get(
                "summarization_threshold", self.summarization_threshold
            )
            self.ollama_port = settings_data.get("ollama_port", self.ollama_port)
            self.api_url = self.build_api_url()
            self.apply_updated_styles()
            self.agents_tab.update_model_dropdown()
            self.update_screenshot_timer()
            self.save_settings()
            self.show_notification("Settings updated successfully")

    def apply_updated_styles(self):
        if self.dark_mode:
            self.apply_dark_mode_style()
        else:
            self.apply_light_mode_style()

    def build_api_url(self):
        """Return the Ollama API URL based on the configured port."""
        return f"http://localhost:{self.ollama_port}/api/chat"

    # -------------------------------------------------------------------------
    # Chat / UI Utility
    # -------------------------------------------------------------------------
    def send_message(self, user_text):
        # Disable send button to prevent multiple clicks
        self.chat_tab.send_button.setEnabled(False)

        if user_text.startswith("/run workflow"):
            parts = user_text.split(None, 3)
            if len(parts) >= 3:
                wf_name = parts[2]
                start_prompt = parts[3] if len(parts) > 3 else ""
                wf = find_workflow_by_name(self.workflows, wf_name)
                if wf:
                    self.execute_workflow_gui(wf, start_prompt, from_chat=True)
                    self.chat_tab.send_button.setEnabled(True)
                    return

        # Show typing indicator
        self.chat_tab.show_typing_indicator()
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        user_message_html = f'<span style="color:{self.user_color};">[{timestamp}] {self.user_name}:</span> {user_text}'
        msg_id = self.chat_tab.append_message_html(user_message_html, from_user=True)
        if msg_id:
            self.chat_tab.update_message_status(msg_id, "sent")

        # Persist the user message once and keep the entry for history building
        user_message = append_message(
            self.chat_history,
            "user",
            user_text,
            debug_enabled=self.debug_enabled,
        )

        # If a Coordinator agent is enabled, send the message to the Coordinator agents only.
        enabled_coordinator_agents = [
            (agent_name, agent_settings)
            for agent_name, agent_settings in self.agents_data.items()
            if agent_settings.get('enabled', False) and agent_settings.get('role') == 'Coordinator'
        ]

        if enabled_coordinator_agents: # If there are coordinators, use them
            enabled_agents = enabled_coordinator_agents
        else: # Otherwise, fall back to other enabled agents (excluding Specialists)
            enabled_agents = [
                (agent_name, agent_settings)
                for agent_name, agent_settings in self.agents_data.items()
                if agent_settings.get('enabled', False)
                and not agent_settings.get('desktop_history_enabled', False)
                and agent_settings.get('role') != 'Specialist'
            ]

        if not enabled_agents:
            self.chat_tab.hide_typing_indicator()
            if self.chat_tab.last_user_message_id:
                self.chat_tab.update_message_status(self.chat_tab.last_user_message_id, "failed")
            QMessageBox.warning(self, "No Agents Enabled", "Please enable at least one Assistant agent or a Coordinator agent.")
            self.chat_tab.send_button.setEnabled(True)  # Re-enable send button
            return
        # The problematic 'else' block has been removed.
        # 'enabled_agents' is now correctly populated by the if/else logic above.

        def process_next_agent(index):
            if index is None or index >= len(enabled_agents):
                self.chat_tab.send_button.setEnabled(True)  # Re-enable send button after all agents have responded
                self.chat_tab.hide_typing_indicator()
                if self.chat_tab.last_user_message_id:
                    self.chat_tab.update_message_status(self.chat_tab.last_user_message_id, "read")
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
            worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.api_url)
            worker.moveToThread(thread)
            self.active_worker_threads.append((worker, thread))

            def on_finished():
                self.worker_finished_sequential(worker, thread, agent_name, index, process_next_agent)

            worker.response_received.connect(self.handle_ai_response_chunk)
            worker.error_occurred.connect(self.handle_worker_error)
            worker.finished.connect(on_finished)

            thread.started.connect(worker.run)
            thread.start()
            self.response_start_times[worker] = time.time()

        process_next_agent(0)

    def clear_chat(self):
        if self.debug_enabled:
            print("[Debug] Clearing chat.")
        self.chat_tab.chat_display.clear()
        clear_history(self.debug_enabled)
        self.chat_history = []
        self.show_notification("Chat cleared")

    def clear_chat_histories(self):
        """Clear persisted chat history from disk."""
        clear_history(self.debug_enabled)
        self.chat_history = []
        self.show_notification("Stored history cleared")

    def export_chat_histories(self):
        """Export persisted chat history to a timestamped file."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = f"chat_history_export_{ts}.json"
        export_history(dest, self.debug_enabled)
        self.show_notification(f"History exported to {dest}")

    def execute_workflow_gui(self, workflow, start_prompt, from_chat=False):
        runner = WorkflowRunnerDialog(workflow['name'], self)
        runner.show()
        log, result = execute_workflow(workflow, start_prompt, self.agents_data)
        for line in log:
            runner.append_line(line)
            QApplication.processEvents()
        if from_chat:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.chat_tab.append_message_html(
                f'<span style="color:{self.user_color};">[{timestamp}] Workflow {workflow["name"]} Result:</span> {result}'
            )
        else:
            QMessageBox.information(self, "Workflow Result", result)

    def handle_ai_response_chunk(self, chunk, agent_name):
        if agent_name not in self.current_responses:
            self.current_responses[agent_name] = ''
        self.current_responses[agent_name] += chunk

    def handle_worker_error(self, error_message):
        logging.error(error_message)
        friendly = format_user_friendly(error_message, self.api_url)
        log_link = QUrl.fromLocalFile(get_log_file_path()).toString()
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.chat_tab.append_message_html(
            f"[{timestamp}] <span style='color:red;'>{friendly} "
            f"<a href='{log_link}'>View Logs</a></span>"
        )
        self.chat_tab.hide_typing_indicator()
        if self.chat_tab.last_user_message_id:
            self.chat_tab.update_message_status(self.chat_tab.last_user_message_id, "failed")
        self.show_notification(f"Error: {friendly}", "error")

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
                if agent_settings.get('tts_enabled'):
                    voice = agent_settings.get('tts_voice')
                    tts.speak_text(clean_content, voice)

                # Store only the clean content without thoughts in history
                append_message(
                    self.chat_history,
                    "assistant",
                    clean_content,
                    agent_name,
                    debug_enabled=self.debug_enabled,
                )
        
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
            if agent_settings.get('tts_enabled'):
                voice = agent_settings.get('tts_voice')
                tts.speak_text(clean_content, voice)

            # Store only the clean content without thoughts in history
            append_message(
                self.chat_history,
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
                append_message(
                    self.chat_history,
                    "assistant",
                    error_msg,
                    agent_name,
                    debug_enabled=self.debug_enabled,
                )
                self.show_notification(f"Tool Error: '{tool_name}' not enabled for agent", "error")
            else:
                self.show_notification(
                    f"Agent '{agent_name}' is using tool: {tool_name}", "info"
                )
                tool_result = run_tool(
                    self.tools, tool_name, tool_args, self.debug_enabled
                )
                record_tool_usage(self.metrics, tool_name, self.debug_enabled)
                self.refresh_metrics_display()

                # Display tool call and result in a collapsible block
                block_html = format_tool_block_html(tool_name, tool_args, tool_result)
                self.chat_tab.append_message_html(
                    f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {block_html}"
                )
                append_message(
                    self.chat_history,
                    "assistant",
                    f"{agent_name} called {tool_name}",
                    agent_name,
                    debug_enabled=self.debug_enabled,
                )
                if tool_result.startswith("[Tool Error]"):
                    error_msg = f"[{timestamp}] <span style='color:red;'>{tool_result}</span>"
                    self.chat_tab.append_message_html(error_msg)
                    append_message(
                        self.chat_history,
                        "assistant",
                        error_msg,
                        agent_name,
                        debug_enabled=self.debug_enabled,
                    )
                    self.show_notification(f"Tool Error: {tool_result}", "error")
                else:
                    append_message(
                        self.chat_history,
                        "assistant",
                        tool_result,
                        agent_name,
                        debug_enabled=self.debug_enabled,
                    )
                    # Send the tool result back to the agent for a follow up
                    self.send_message_to_agent(
                        agent_name, tool_result
                    )
                    self.show_notification(
                        f"Tool executed successfully: {tool_name}", "info"
                    )

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
                    debug_enabled=self.debug_enabled,
                    os_schedule=True,
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

        if sender_worker in self.response_start_times:
            elapsed = time.time() - self.response_start_times.pop(sender_worker)
            record_response_time(self.metrics, agent_name, elapsed, self.debug_enabled)
            self.refresh_metrics_display()

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
        append_message(self.chat_history, "user", formatted_message, debug_enabled=self.debug_enabled)

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
            worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.api_url)
            worker.moveToThread(thread)
            self.active_worker_threads.append((worker, thread))

            def on_finished():
                self.worker_finished_sequential(worker, thread, agent_name, None, process_next_agent=None)

            worker.response_received.connect(self.handle_ai_response_chunk)
            worker.error_occurred.connect(self.handle_worker_error)
            worker.finished.connect(on_finished)

            thread.started.connect(worker.run)
            thread.start()
            self.response_start_times[worker] = time.time()
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
                "role": "Assistant",  # Default role
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

        if hasattr(self.agents_tab, "refresh_agent_table"):
            self.agents_tab.refresh_agent_table()

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
                    "tools_enabled": [],
                    "automations_enabled": [],
                "thinking_enabled": False,
                "thinking_steps": 3,
                "tts_enabled": False,
                "tts_voice": ""
            }
                self.save_agents()
                if self.debug_enabled:
                    print(f"[Debug] Agent '{agent_name}' added.")
                self.show_notification(f"Agent '{agent_name}' created successfully", "info")
                if hasattr(self.agents_tab, "refresh_agent_table"):
                    self.agents_tab.refresh_agent_table()
            else:
                QMessageBox.warning(self, "Agent Exists", "Agent already exists.")
        self.update_send_button_state()

    def delete_agent(self, agent_name=None):
        if agent_name is None:
            agent_name = self.agents_tab.current_agent
        if agent_name and agent_name in self.agents_data:
            del self.agents_data[agent_name]
            self.save_agents()
            if self.debug_enabled:
                print(f"[Debug] Agent '{agent_name}' removed.")
            self.show_notification(f"Agent '{agent_name}' deleted", "info")
            if hasattr(self.agents_tab, "refresh_agent_table"):
                self.agents_tab.refresh_agent_table()
        self.update_send_button_state()

    def save_agents(self):
        try:
            with open(AGENTS_SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.agents_data, f, indent=4)
            if self.debug_enabled:
                print("[Debug] Agents saved.")
            self.update_screenshot_timer()
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

    def update_screenshot_timer(self):
        """Update screenshot timer based on agent settings."""
        enabled_agents = [
            a for a in self.agents_data.values() if a.get("desktop_history_enabled", False)
        ]
        if not enabled_agents or self.screenshot_paused:
            self.screenshot_manager.stop()
            return

        self.screenshot_manager.start(self.screenshot_interval)

    # -------------------------------------------------------------------------
    # Tools Management
    # -------------------------------------------------------------------------
    def refresh_tools_list(self):
        self.tools = load_tools(self.debug_enabled)
        if hasattr(self.tools_tab, "refresh_tools_list"):
            self.tools_tab.tools = self.tools
            self.tools_tab.refresh_tools_list()
        self.show_notification("Tools list refreshed", "info")

    def refresh_automations_list(self):
        self.automations = load_automations(self.debug_enabled)
        if hasattr(self.automations_tab, "refresh_automations_list"):
            self.automations_tab.automations = self.automations
            self.automations_tab.refresh_automations_list()
        self.show_notification("Automations list refreshed", "info")

    # ---------------------------------------------------------------------
    # Update Checks
    # ---------------------------------------------------------------------
    def check_for_updates(self, manual=False):
        """Check GitHub for newer releases."""
        thread = QThread()
        worker = UpdateCheckWorker(self.tools, self.debug_enabled)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        def done(msg):
            if "Update available" in msg or manual:
                self.show_notification(msg)
            thread.quit()
            thread.wait()
            for i, (w, t) in enumerate(self.active_worker_threads):
                if w is worker:
                    del self.active_worker_threads[i]
                    break
            worker.deleteLater()
            thread.deleteLater()

        worker.finished.connect(done)
        thread.started.connect(worker.run)
        thread.start()

    def refresh_metrics_display(self):
        if hasattr(self.metrics_tab, "refresh_metrics"):
            self.metrics_tab.refresh_metrics()

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
                repeat = t.get("repeat_interval", 0)
                if repeat:
                    new_due = (due_dt + timedelta(minutes=repeat)).isoformat()
                    update_task_due_time(
                        self.tasks,
                        t["id"],
                        new_due,
                        debug_enabled=self.debug_enabled,
                        os_schedule=True,
                    )
                else:
                    to_remove.append(t["id"])
                self.show_notification(
                    f"Executing scheduled task for {agent_name}", "info"
                )

        for task_id in to_remove:
            delete_task(
                self.tasks,
                task_id,
                debug_enabled=self.debug_enabled,
                os_schedule=True,
            )
        save_tasks(self.tasks, debug_enabled=self.debug_enabled)
        if hasattr(self, "tasks_tab"):
            self.tasks_tab.refresh_tasks_list()

    def schedule_user_message(self, agent_name, prompt, task_id=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        message_html = f'<span style="color:{self.user_color};">[{timestamp}] (Scheduled) {self.user_name}:</span> {prompt}'
        self.chat_tab.append_message_html(message_html)

        # Persist the scheduled user message
        append_message(self.chat_history, "user", prompt, debug_enabled=self.debug_enabled)

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
        worker = AIWorker(model_name, chat_history, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.api_url)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        def on_finished():
            self.worker_finished_sequential(worker, thread, agent_name, None, None)

        worker.response_received.connect(self.handle_ai_response_chunk)
        worker.error_occurred.connect(self.handle_worker_error)
        worker.finished.connect(on_finished)

        thread.started.connect(worker.run)
        thread.start()
        self.response_start_times[worker] = time.time()

    # -------------------------------------------------------------------------
    # Chat History Helpers
    # -------------------------------------------------------------------------
    def build_agent_chat_history(self, agent_name, user_message=None, is_screenshot=False):
        # Reload history from disk to ensure persistence
        self.chat_history = load_history(self.debug_enabled)
        self.chat_history = summarize_history(
            self.chat_history, threshold=self.summarization_threshold
        )

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
                tool_instructions = generate_tool_instructions_message(self, agent_name)
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

        # Include recent screenshots for agents with desktop history enabled
        if agent_settings.get('desktop_history_enabled', False):
            for img_path in self.screenshot_manager.get_images():
                temp_history.append({"role": "user", "content": "", "images": [img_path]})

        # Add the user message to the history if provided
        if user_message:
            temp_history.append(user_message)

        chat_history.extend(temp_history)
        return chat_history


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
            "accent_color": self.accent_color,
            "dark_mode": self.dark_mode,
            "screenshot_interval": self.screenshot_interval,
            "summarization_threshold": self.summarization_threshold,
            "ollama_port": self.ollama_port,
            "agents_onboarding_complete": self.agents_onboarding_complete,
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f)
            if self.debug_enabled:
                print("[Debug] Settings saved.")
        except Exception as e:
            print(f"[Error] Failed to save settings: {e}")
            self.show_notification(f"Error saving settings: {str(e)}", "error")

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                self.debug_enabled = settings.get("debug_enabled", False)
                self.include_image = settings.get("include_image", False)
                self.include_screenshot = settings.get("include_screenshot", False)
                self.user_name = settings.get("user_name", "You")
                self.user_color = settings.get("user_color", "#0000FF")
                self.accent_color = settings.get("accent_color", "#803391")
                self.dark_mode = settings.get("dark_mode", False)
                self.screenshot_interval = settings.get(
                    "screenshot_interval", self.screenshot_interval
                )
                self.summarization_threshold = settings.get(
                    "summarization_threshold", self.summarization_threshold
                )
                self.ollama_port = settings.get("ollama_port", self.ollama_port)
                self.api_url = self.build_api_url()
                self.agents_onboarding_complete = settings.get(
                    "agents_onboarding_complete", False
                )
                if self.debug_enabled:
                    print("[Debug] Settings loaded.")
            except Exception as e:
                print(f"[Error] Failed to load settings: {e}")
                
        self.agents_tab.load_global_preferences()

    # -------------------------------------------------------------------------
    # Dark/Light Mode
    # -------------------------------------------------------------------------
    def apply_dark_mode_style(self):
        style_sheet = load_style_sheet("dark_mode.qss", self.accent_color)
        self.setStyleSheet(style_sheet)

    def apply_light_mode_style(self):
        style_sheet = load_style_sheet("light_mode.qss", self.accent_color)
        self.setStyleSheet(style_sheet)

    # -------------------------------------------------------------------------
    # Close Event
    # -------------------------------------------------------------------------
    def closeEvent(self, event):
        if not getattr(self, "force_quit", False) and getattr(self, "tray_icon", None):
            event.ignore()
            self.hide()
            return

        for worker, thread in self.active_worker_threads:
            thread.quit()
            thread.wait()
            worker.deleteLater()
            thread.deleteLater()
        self.active_worker_threads.clear()
        event.accept()
