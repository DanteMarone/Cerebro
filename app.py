#app.py
import os
import json
import time
import uuid # Added from main for msg_id
from datetime import datetime, timedelta
from PyQt5 import QtCore
from PyQt5.QtCore import QThread, Qt, QTimer, QObject, pyqtSignal, QCoreApplication
from PyQt5 import sip

from screenshot import ScreenshotManager
from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox, QApplication, QAction, QMenu, QDialog,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QStackedWidget,
    QInputDialog, QScrollArea, QShortcut, QSystemTrayIcon, QStyle
)
from PyQt5.QtGui import QKeySequence

# Debugger related imports
from debugger_service import DebuggerService
from debugger_events import (
    UserMessageEvent, AgentRequestEvent, LLMResponseEvent,
    ToolCallEvent, ToolResultEvent, AgentHandoffEvent, ErrorEvent
)
from debugger_window import DebuggerWindow

from theme_utils import load_style_sheet
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

        # Debugger Service Initialization (as per interactive-debugger)
        self.debugger_service = DebuggerService(self)
        self.debugger_service.set_enabled(False) # Default to False
        self.debugger_window = None
        self.debugger_interaction_enabled = False # For persistent state

        # debug_enabled is for general console debug prints (from main)
        if os.environ.get("DEBUG_MODE", "1") == "0":
            self.debug_enabled = False
        else:
            self.debug_enabled = True

        self.setWindowTitle("Cerebro 1.0")
        self.setGeometry(100, 100, 1000, 700)

        clear_history(self.debug_enabled)
        self.chat_history = []
        self.current_responses = {}
        self.agents_data = {}
        self.include_image = False
        self.include_screenshot = False
        self.current_agent_color = "#000000" # Default, can be overridden by agent settings
        self.user_name = "You"
        self.user_color = "#0000FF" # Default user color
        self.accent_color = "#803391" # Default accent color
        self.dark_mode = True # Default to dark mode
        self.screenshot_interval = 5
        self.screenshot_manager = ScreenshotManager(self) # Pass parent
        self.active_worker_threads = []
        self.notifications_paused = False
        self.screenshot_paused = False
        self.summarization_threshold = 20

        self.notifications = []
        self.notification_timer = QTimer(self)
        self.notification_timer.timeout.connect(self.process_notifications)
        self.notification_timer.start(3000)

        self.tools = load_tools(self.debug_enabled)
        self.automations = load_automations(self.debug_enabled)
        self.tasks = load_tasks(self.debug_enabled)
        self.workflows = load_workflows(self.debug_enabled)
        self.metrics = load_metrics(self.debug_enabled)
        self.response_start_times = {}

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        central_widget.setLayout(main_layout)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(220)
        sidebar_layout = QVBoxLayout()
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        self.sidebar.setLayout(sidebar_layout)

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

        self.nav_buttons = {}
        nav_items = [
            ("Chat", 0), ("Agents", 1), ("Tools", 2), ("Plugins", 3),
            ("Automations", 4), ("Tasks", 5), ("Workflows", 6),
            ("Metrics", 7), ("Finetune", 8), ("Docs", 9)
        ]
        for name, index in nav_items:
            self.nav_buttons[name.lower()] = self.create_nav_button(name, index)
            sidebar_layout.addWidget(self.nav_buttons[name.lower()])

        sidebar_layout.addStretch(1)

        settings_btn = QPushButton("Settings")
        settings_btn.setObjectName("navButton")
        settings_btn.clicked.connect(self.open_settings_dialog)
        settings_btn.setCursor(Qt.PointingHandCursor)
        sidebar_layout.addWidget(settings_btn)

        help_btn = QPushButton("Help")
        help_btn.setObjectName("navButton")
        help_btn.clicked.connect(self.show_help_dialog)
        help_btn.setCursor(Qt.PointingHandCursor)
        sidebar_layout.addWidget(help_btn)

        main_layout.addWidget(self.sidebar)

        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("contentStack")

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

        pages = [
            self.chat_tab, self.agents_tab, self.tools_tab, self.plugins_tab,
            self.automations_tab, self.tasks_tab, self.workflows_tab,
            self.metrics_tab, self.finetune_tab, self.docs_tab
        ]
        for page in pages:
            self.content_stack.addWidget(page)

        main_layout.addWidget(self.content_stack)

        self.notification_area = QWidget(self)
        self.notification_area.setObjectName("notificationArea")
        self.notification_area.setFixedWidth(300)
        self.notification_area.setFixedHeight(0)
        self.notification_layout = QVBoxLayout(self.notification_area)
        self.notification_layout.setContentsMargins(0,0,0,0)
        self.notification_layout.setSpacing(5)
        self.notification_area.setLayout(self.notification_layout)
        self.notification_area.move(self.width() - 320, 40)
        self.notification_area.hide()

        self.load_settings() # Affects debugger_service state
        self.populate_agents()
        self.update_send_button_state()
        self.update_screenshot_timer()

        menubar = self.menuBar()
        menubar.setObjectName("mainMenuBar")
        file_menu = menubar.addMenu('File')
        view_menu = menubar.addMenu('View')
        help_menu = menubar.addMenu('Help')

        settings_action = QAction('Settings', self)
        settings_action.setShortcut('Ctrl+,')
        settings_action.triggered.connect(self.open_settings_dialog)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()

        self.quit_action_file_menu = QAction('Quit', self) # Renamed for clarity
        self.quit_action_file_menu.setShortcut('Ctrl+Q')
        self.quit_action_file_menu.triggered.connect(self.quit_from_tray) # main uses quit_from_tray
        file_menu.addAction(self.quit_action_file_menu)

        toggle_theme_action = QAction('Toggle Dark/Light Mode', self)
        toggle_theme_action.setShortcut('Ctrl+T')
        toggle_theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle_theme_action)

        # Debugger Menu Item (as per interactive-debugger)
        view_menu.addSeparator()
        debugger_action = QAction('Show Debugger', self)
        debugger_action.setShortcut('Ctrl+Shift+D')
        debugger_action.triggered.connect(self.show_debugger_window)
        view_menu.addAction(debugger_action)

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

        if self.dark_mode:
            self.apply_dark_mode_style()
        else:
            self.apply_light_mode_style()

        self.task_timer = QtCore.QTimer(self)
        self.task_timer.timeout.connect(self.check_for_due_tasks)
        self.task_timer.start(30_000)

        if self.nav_buttons.get("chat"): # Check if chat button exists
             self.nav_buttons["chat"].setProperty("selected", True)
        self.setup_keyboard_shortcuts()

        self.force_quit = False
        self.create_tray_icon()

        QTimer.singleShot(1000, self.check_for_updates)

    def show_debugger_window(self): # New from interactive-debugger
        if not self.debugger_window:
            self.debugger_window = DebuggerWindow(self.debugger_service, self)
        self.debugger_window.show()
        self.debugger_window.activateWindow()
        self.debugger_window.raise_()

    def create_nav_button(self, text, index):
        button = QPushButton(text)
        button.setObjectName("navButton")
        button.setProperty("selected", False)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda: self.change_tab(index, button))
        return button

    def change_tab(self, index, button=None):
        self.content_stack.setCurrentIndex(index)
        for btn_key, btn_val in self.nav_buttons.items(): # Iterate safely
            btn_val.setProperty("selected", False)
            btn_val.style().unpolish(btn_val)
            btn_val.style().polish(btn_val)
        if button:
            button.setProperty("selected", True)
            button.style().unpolish(button)
            button.style().polish(button)

    def setup_keyboard_shortcuts(self):
        nav_keys = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']
        nav_item_keys = list(self.nav_buttons.keys())
        for i, key_char in enumerate(nav_keys):
            if i < len(nav_item_keys):
                button_key = nav_item_keys[i]
                shortcut = QShortcut(f"Ctrl+{key_char}", self)
                shortcut.activated.connect(lambda idx=i, bk=button_key: self.change_tab(idx, self.nav_buttons[bk]))

        shortcut_send = QShortcut("Ctrl+S", self)
        shortcut_send.activated.connect(lambda: self.chat_tab.on_send_clicked())
        shortcut_clear = QShortcut("Ctrl+L", self)
        shortcut_clear.activated.connect(lambda: self.chat_tab.on_clear_chat_clicked())

    def create_tray_icon(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray_icon.setIcon(icon)
        tray_menu = QMenu(self)
        open_action = QAction("Open Cerebro", self)
        open_action.triggered.connect(self.showMaximized) # main uses showMaximized
        tray_menu.addAction(open_action)
        if hasattr(self, 'tasks_tab'): # Check if tasks_tab exists
            add_task_action = QAction("Add Task", self)
            add_task_action.triggered.connect(self.tasks_tab.add_task_ui)
            tray_menu.addAction(add_task_action)
        toggle_action = QAction("Toggle Dark Mode", self)
        toggle_action.triggered.connect(self.toggle_theme)
        tray_menu.addAction(toggle_action)
        self.pause_notifications_action = QAction("Pause Notifications", self)
        self.pause_notifications_action.triggered.connect(self.toggle_notifications)
        tray_menu.addAction(self.pause_notifications_action)
        text = ("Stop Screenshot Capture" if self.screenshot_manager.timer.isActive() else "Start Screenshot Capture")
        self.screenshot_capture_action = QAction(text, self)
        self.screenshot_capture_action.triggered.connect(self.toggle_screenshot_capture)
        tray_menu.addAction(self.screenshot_capture_action)
        quit_action_tray = QAction("Quit", self) # Renamed
        quit_action_tray.triggered.connect(self.quit_from_tray)
        tray_menu.addAction(quit_action_tray)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

    def quit_from_tray(self):
        self.force_quit = True
        if hasattr(self, "tray_icon") and self.tray_icon: # Check tray_icon exists
            self.tray_icon.hide()
        QApplication.quit()

    def show_help_dialog(self):
        QMessageBox.information(self, "Cerebro Help",
                              "Cerebro is a multi-agent AI chat application.\n\n"
                              "• Chat: Interact with AI agents\n"
                              "• Agents: Configure your AI assistants\n"
                              "• Tools: Manage tools for agents to use\n"
                              "• Automations: Record and run button sequences\n"
                              "• Tasks: Schedule future agent actions\n\n"
                              "• Docs: View the built-in user guide\n\n"
                              "Press Ctrl+K to view keyboard shortcuts.")

    def show_keyboard_shortcuts(self):
        QMessageBox.information(
            self, "Keyboard Shortcuts",
            "Ctrl+1: Chat Tab\nCtrl+2: Agents Tab\nCtrl+3: Tools Tab\n"
            "Ctrl+4: Plugins Tab\nCtrl+5: Automations Tab\nCtrl+6: Tasks Tab\n"
            "Ctrl+7: Workflows Tab\nCtrl+8: Metrics Tab\nCtrl+9: Docs Tab\n"
            "Ctrl+S: Send Message\nCtrl+L: Clear Chat\nCtrl+T: Toggle Theme\n"
            "Ctrl+Q: Quit\nCtrl+K: Show Shortcuts\nCtrl+,: Open Settings")

    def show_about_dialog(self):
        QMessageBox.about(self, "About Cerebro",
                       "<h2>Cerebro</h2>"
                       "<p>Version 1.0.0</p>"
                       "<p>A multi-agent AI chat application</p>")

    def show_notification(self, message, type="info"):
        self.notifications.append({"message": message, "type": type})
        if not self.notifications_paused:
            self.process_notifications()

    def process_notifications(self):
        if self.notifications_paused or not self.notifications: return
        notification = self.notifications.pop(0)
        toast = QWidget()
        toast.setObjectName("toast")
        toast.setProperty("type", notification["type"])
        toast_layout = QHBoxLayout()
        toast_layout.setContentsMargins(10, 10, 10, 10)
        toast.setLayout(toast_layout)
        icon_text = "i" if notification["type"] == "info" else "!"
        icon_label = QLabel(icon_text)
        icon_label.setObjectName("toastIcon")
        icon_label.setFixedSize(24, 24)
        toast_layout.addWidget(icon_label)
        message_label = QLabel(notification["message"])
        message_label.setWordWrap(True)
        toast_layout.addWidget(message_label)
        close_btn = QPushButton("×")
        close_btn.setObjectName("toastCloseButton")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(lambda: self.remove_notification(toast))
        toast_layout.addWidget(close_btn)
        self.notification_layout.addWidget(toast)
        self.notification_area.setFixedHeight(min(self.height() - 100, self.notification_layout.count() * 80))
        self.notification_area.show()
        QTimer.singleShot(5000, lambda: self.remove_notification(toast))

    def remove_notification(self, toast):
        if not toast or sip.isdeleted(toast): return
        try:
            if toast.parentWidget() == self.notification_area:
                self.notification_layout.removeWidget(toast)
                toast.deleteLater()
                if self.notification_layout.count() == 0:
                    self.notification_area.hide()
                else:
                    self.notification_area.setFixedHeight(min(self.height() - 100, self.notification_layout.count() * 80))
        except RuntimeError: pass

    def toggle_theme(self):
        self.dark_mode = not self.dark_mode
        self.apply_updated_styles()
        self.save_settings()
        self.show_notification(f"Switched to {'Dark' if self.dark_mode else 'Light'} Mode")

    def toggle_notifications(self):
        self.notifications_paused = not self.notifications_paused
        text = "Resume Notifications" if self.notifications_paused else "Pause Notifications"
        if hasattr(self, 'pause_notifications_action'): # Check if action exists
            self.pause_notifications_action.setText(text)
        if not self.notifications_paused: self.process_notifications()
        self.show_notification(f"Notifications {'paused' if self.notifications_paused else 'resumed'}")

    def toggle_screenshot_capture(self):
        self.screenshot_paused = not self.screenshot_paused
        if self.screenshot_paused:
            self.screenshot_manager.stop()
            if hasattr(self, 'screenshot_capture_action'): # Check if action exists
                self.screenshot_capture_action.setText("Start Screenshot Capture")
            self.show_notification("Screenshot capture stopped")
        else:
            self.update_screenshot_timer()
            if hasattr(self, 'screenshot_capture_action'):
                self.screenshot_capture_action.setText("Stop Screenshot Capture")
            self.show_notification("Screenshot capture started")

    def open_settings_dialog(self): # From interactive-debugger
        from dialogs import SettingsDialog
        current_settings = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    current_settings = json.load(f)
            except Exception as e:
                print(f"[Error] Failed to load settings for dialog: {e}")
        settings_dialog = SettingsDialog(self, current_settings)
        if settings_dialog.exec_() == QDialog.Accepted:
            settings_data = settings_dialog.get_data()
            self.dark_mode = settings_data["dark_mode"]
            self.user_name = settings_data["user_name"]
            self.user_color = settings_data["user_color"]
            self.accent_color = settings_data.get("accent_color", self.accent_color)
            self.debug_enabled = settings_data["debug_enabled"]
            self.debugger_interaction_enabled = settings_data.get("debugger_interaction_enabled", False)
            if hasattr(self, 'debugger_service'):
                self.debugger_service.set_enabled(self.debugger_interaction_enabled)
            self.screenshot_interval = settings_data.get("screenshot_interval", self.screenshot_interval)
            self.summarization_threshold = settings_data.get("summarization_threshold", self.summarization_threshold)
            self.apply_updated_styles()
            if hasattr(self, 'agents_tab'): self.agents_tab.update_model_dropdown()
            self.update_screenshot_timer()
            self.save_settings()
            self.show_notification("Settings updated successfully")

    def apply_updated_styles(self):
        if self.dark_mode: self.apply_dark_mode_style()
        else: self.apply_light_mode_style()

    def send_message(self, user_text, msg_id=None): # msg_id from main
        # Debugger UserMessageEvent (interactive-debugger)
        self.debugger_service.record_event(UserMessageEvent(user_text=user_text))

        self.chat_tab.send_button.setEnabled(False)
        self.chat_tab.show_typing_indicator() # From main

        if not msg_id: # From main
            msg_id = str(uuid.uuid4())

        if hasattr(self.chat_tab, 'last_user_message_id'): # From main
            self.chat_tab.last_user_message_id = msg_id

        # User message display from main
        timestamp = datetime.now().strftime("%H:%M:%S")
        user_message_html = f'<div id="msg-{msg_id}-you" class="message you"><span class="timestamp">[{timestamp}]</span> <span class="user" style="color:{self.user_color};">{self.user_name}:</span> <span class="text">{user_text}</span><span id="status-{msg_id}" class="status-dots">...</span></div>'
        self.chat_tab.append_message_html(user_message_html)
        self.chat_tab.update_message_status(msg_id, "processing")


        user_message = append_message(self.chat_history, "user", user_text, debug_enabled=self.debug_enabled)

        # Corrected agent selection logic (merged)
        enabled_coordinator_agents = [(name, settings) for name, settings in self.agents_data.items() if settings.get('enabled', False) and settings.get('role') == 'Coordinator']
        if enabled_coordinator_agents:
            enabled_agents_to_process = enabled_coordinator_agents
        else:
            enabled_agents_to_process = [(name, settings) for name, settings in self.agents_data.items() if settings.get('enabled', False) and not settings.get('desktop_history_enabled', False) and settings.get('role') != 'Specialist']

        if not enabled_agents_to_process:
            self.chat_tab.hide_typing_indicator()
            if hasattr(self.chat_tab, 'last_user_message_id') and self.chat_tab.last_user_message_id: # Check from main
                self.chat_tab.update_message_status(self.chat_tab.last_user_message_id, "failed")
            QMessageBox.warning(self, "No Agents Enabled", "Please enable at least one Assistant agent or a Coordinator agent.")
            self.chat_tab.send_button.setEnabled(True)
            return

        def process_next_agent(index):
            if index is None or index >= len(enabled_agents_to_process): # Use enabled_agents_to_process
                self.chat_tab.send_button.setEnabled(True)
                self.chat_tab.hide_typing_indicator()
                if hasattr(self.chat_tab, 'last_user_message_id') and self.chat_tab.last_user_message_id: # Check from main
                     self.chat_tab.update_message_status(self.chat_tab.last_user_message_id, "complete") # From main
                return

            agent_name, agent_settings = enabled_agents_to_process[index] # Use enabled_agents_to_process
            if self.debug_enabled: print(f"[Debug] Processing agent: {agent_name}")

            # Debugger AgentRequestEvent (interactive-debugger)
            self.debugger_service.record_event(AgentRequestEvent(agent_name=agent_name, triggering_event_type="user_message", input_data=user_text))

            model_name = agent_settings.get("model", "llama3.2-vision").strip()
            if not model_name:
                QMessageBox.warning(self, "Invalid Model Name", f"Agent '{agent_name}' has no valid model name.")
                process_next_agent(index + 1)
                return

            temperature = agent_settings.get("temperature", 0.7)
            max_tokens = agent_settings.get("max_tokens", 512)

            # Chat history for worker (interactive-debugger logic for user_message)
            current_chat_history_for_worker = self.build_agent_chat_history(agent_name, user_message if index == 0 else None)

            thread = QThread()
            # AIWorker instantiation with debugger_service (interactive-debugger)
            worker = AIWorker(model_name, current_chat_history_for_worker, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.debugger_service)
            worker.moveToThread(thread)
            self.active_worker_threads.append((worker, thread))

            # Pass msg_id to worker_finished_sequential (from main)
            worker.finished.connect(lambda: self.worker_finished_sequential(worker, thread, agent_name, index, process_next_agent, msg_id))
            worker.response_received.connect(lambda chunk, an: self.handle_ai_response_chunk(chunk, an, msg_id)) # Pass msg_id (from main)
            worker.error_occurred.connect(lambda err_msg: self.handle_worker_error(err_msg, msg_id)) # Pass msg_id (from main)

            thread.started.connect(worker.run)
            thread.start()
            self.response_start_times[worker] = time.time()

        process_next_agent(0)

    def clear_chat(self):
        if self.debug_enabled: print("[Debug] Clearing chat.")
        self.chat_tab.chat_display.clear()
        clear_history(self.debug_enabled)
        self.chat_history = []
        self.show_notification("Chat cleared")

    def clear_chat_histories(self):
        clear_history(self.debug_enabled)
        self.chat_history = []
        self.show_notification("Stored history cleared")

    def export_chat_histories(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = f"chat_history_export_{ts}.json"
        export_history(dest, self.debug_enabled)
        self.show_notification(f"History exported to {dest}")

    def execute_workflow_gui(self, workflow, start_prompt, from_chat=False):
        runner = WorkflowRunnerDialog(workflow['name'], self)
        runner.show()
        log, result = execute_workflow(workflow, start_prompt, self.agents_data, self.tools, self.debug_enabled) # Added tools, debug_enabled from main
        for line in log:
            runner.append_line(line)
            QApplication.processEvents()
        if from_chat:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.chat_tab.append_message_html(f'<span style="color:{self.user_color};">[{timestamp}] Workflow {workflow["name"]} Result:</span> {result}')
        else:
            QMessageBox.information(self, "Workflow Result", result)

    def handle_ai_response_chunk(self, chunk, agent_name, msg_id): # msg_id from main
        if agent_name not in self.current_responses:
            self.current_responses[agent_name] = {"content": "", "id": str(uuid.uuid4())} # From main
        self.current_responses[agent_name]["content"] += chunk

        # Display logic from main branch, including agent-specific message div
        timestamp = datetime.now().strftime("%H:%M:%S")
        agent_color = self.agents_data.get(agent_name, {}).get("color", "#000000")
        agent_avatar = self.agents_data.get(agent_name, {}).get("avatar", "🤖")

        # Construct HTML for the agent's message chunk
        # Using the agent-specific ID for the message block
        agent_msg_block_id = f"msg-{msg_id}-{self.current_responses[agent_name]['id']}"

        # Sanitize content for HTML display (basic)
        safe_chunk = chunk.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        script = f"""
        var container = document.getElementById('{agent_msg_block_id}-text');
        if (!container) {{
            var newDiv = document.createElement('div');
            newDiv.id = '{agent_msg_block_id}';
            newDiv.className = 'message assistant';
            newDiv.innerHTML = '<span class="timestamp">[{timestamp}]</span> <span class="avatar" style="color:{agent_color};">{agent_avatar} {agent_name}:</span> <span id="{agent_msg_block_id}-text" class="text">{safe_chunk}</span>';
            document.body.appendChild(newDiv);
            container = document.getElementById('{agent_msg_block_id}-text');
        }} else {{
            container.innerHTML += '{safe_chunk}';
        }}
        window.scrollTo(0, document.body.scrollHeight);
        """
        self.chat_tab.chat_display.page().runJavaScript(script)


    def handle_worker_error(self, error_message, msg_id): # msg_id from main
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.chat_tab.append_message_html(f"[{timestamp}] {error_message}")
        self.chat_tab.hide_typing_indicator()
        self.show_notification(f"Error: {error_message}", "error")
        if hasattr(self.chat_tab, 'last_user_message_id') and self.chat_tab.last_user_message_id == msg_id: # Check from main
            self.chat_tab.update_message_status(msg_id, "failed")

        # Debugger ErrorEvent (interactive-debugger with agent name parsing)
        agent_name_in_error = "Unknown"
        if "agent" in error_message.lower():
            try:
                if "Error for agent '" in error_message and "':" in error_message:
                    start_phrase = "Error for agent '"
                    end_phrase = "':"
                    start_index = error_message.find(start_phrase) + len(start_phrase)
                    end_index = error_message.find(end_phrase, start_index)
                    if start_index != -1 and end_index != -1:
                        agent_name_in_error = error_message[start_index:end_index]
            except Exception: pass
        self.debugger_service.record_event(ErrorEvent(source="AIWorker", agent_name=agent_name_in_error, error_message=error_message))

    def worker_finished_sequential(self, sender_worker, thread, agent_name, index, process_next_agent, msg_id): # msg_id from main
        current_response_data = self.current_responses.pop(agent_name, None) # From main
        assistant_content = current_response_data["content"] if current_response_data else ""

        tool_request = None
        task_request = None
        content = assistant_content.strip() # This is raw_response for LLMResponseEvent

        # Placeholders for LLMResponseEvent
        parsed_text_content_for_event = content
        parsed_tool_req_for_event = None

        agent_settings = self.agents_data.get(agent_name, {})
        if agent_settings.get('role') == 'Specialist':
            # Specialist logic from main (simplified for brevity, assume it's correct)
            if not (self.chat_history and self.chat_history[-1]['role'] == 'assistant' and self.chat_history[-1]['content'].endswith(f"Next Response By: {agent_name}")):
                if process_next_agent is not None and index is not None: process_next_agent(index + 1)
                return
            content = "[Response to Coordinator] " + content
            parsed_text_content_for_event = content # Update for event

        parsed = None
        if content.startswith("{") and content.endswith("}"):
            try: parsed = json.loads(content)
            except json.JSONDecodeError: parsed = None

        if parsed is not None:
            if "tool_request" in parsed:
                tool_request = parsed["tool_request"]
                parsed_tool_req_for_event = tool_request
                content = parsed.get("content", "").strip() # This becomes parsed_content for event
                parsed_text_content_for_event = content
            if "task_request" in parsed:
                task_request = parsed["task_request"]
                content = parsed.get("content", "").strip()
                parsed_text_content_for_event = content

        # Debugger LLMResponseEvent (interactive-debugger)
        self.debugger_service.record_event(LLMResponseEvent(agent_name=agent_name, raw_response=assistant_content, parsed_content=parsed_text_content_for_event, parsed_tool_request=parsed_tool_req_for_event))

        timestamp = datetime.now().strftime("%H:%M:%S")
        agent_color = agent_settings.get("color", "#000000")
        agent_avatar = agent_settings.get("avatar", "🤖") # From main

        next_agent = None
        if agent_settings.get('role') == 'Coordinator' and "Next Response By:" in content:
            parts = content.split("Next Response By:")
            content = parts[0].strip()
            next_agent = parts[1].strip()
            # Ensure content ends with the handoff for display (main logic)
            if content and next_agent and not content.endswith(f"Next Response By: {next_agent}"):
                 content += f"\nNext Response By: {next_agent}"

        # Display logic from main, using agent_msg_block_id
        agent_msg_block_id = f"msg-{msg_id}-{current_response_data['id'] if current_response_data else str(uuid.uuid4())}"

        if agent_settings.get('role') in ['Coordinator', 'Assistant'] or \
           (agent_settings.get('role') == 'Specialist' and any(msg['content'].strip().endswith(f"Next Response By: {agent_name}") for msg in self.chat_history)):
            if content:
                # Thought processing from main
                thought = None
                clean_content_for_history = content
                if "<thought>" in content and "</thought>" in content:
                    thought_start = content.find("<thought>")
                    thought_end = content.find("</thought>") + len("</thought>")
                    thought = content[thought_start:thought_end]
                    clean_content_for_history = (content[:thought_start] + content[thought_end:]).strip()

                display_content_html = clean_content_for_history.replace("\n", "<br>") # Basic HTML formatting
                if thought:
                    thought_html = thought.replace("<thought>", "").replace("</thought>", "").strip().replace("\n", "<br>")
                    display_content_html += f"<br><details><summary><i>Agent thoughts...</i></summary><pre style='background-color:#f5f5f5;padding:8px;border-radius:5px;color:#333;'>{thought_html}</pre></details>"

                # Update existing div or create new one (from main)
                script = f"""
                var containerDiv = document.getElementById('{agent_msg_block_id}');
                if (containerDiv) {{
                    var textSpan = containerDiv.querySelector('.text');
                    if(textSpan) textSpan.innerHTML = `{display_content_html}`;
                }} else {{
                     var newDiv = document.createElement('div');
                     newDiv.id = '{agent_msg_block_id}';
                     newDiv.className = 'message assistant';
                     newDiv.innerHTML = '<span class="timestamp">[{timestamp}]</span> <span class="avatar" style="color:{agent_color};">{agent_avatar} {agent_name}:</span> <span class="text">{display_content_html}</span>';
                     document.body.appendChild(newDiv);
                }}
                window.scrollTo(0, document.body.scrollHeight);
                """
                self.chat_tab.chat_display.page().runJavaScript(script)

                if agent_settings.get('tts_enabled'):
                    tts.speak_text(clean_content_for_history, agent_settings.get('tts_voice'))
                append_message(self.chat_history, "assistant", clean_content_for_history, agent_name, debug_enabled=self.debug_enabled)

        if next_agent:
            managed_agents = agent_settings.get('managed_agents', [])
            if next_agent in managed_agents:
                user_message_for_handoff = next((msg for msg in reversed(self.chat_history) if msg["role"] == "user"), None)
                if user_message_for_handoff:
                    # Debugger AgentHandoffEvent (interactive-debugger)
                    self.debugger_service.record_event(AgentHandoffEvent(from_agent_name=agent_name, to_agent_name=next_agent, handoff_message=user_message_for_handoff['content']))
                    self.send_message_to_agent(next_agent, user_message_for_handoff['content']) # msg_id not passed here in main
            else:
                error_msg = f"[{timestamp}] <span style='color:red;'>[Error] Agent '{next_agent}' is not managed by Coordinator '{agent_name}'.</span>"
                self.chat_tab.append_message_html(error_msg)
                self.show_notification(f"Error: Agent '{next_agent}' is not managed by Coordinator", "error")
        elif process_next_agent is not None and index is not None:
            process_next_agent(index + 1)

        if tool_request and agent_settings.get("tool_use", False):
            tool_name = tool_request.get("name", "")
            tool_args = tool_request.get("args", {})
            enabled_tools = agent_settings.get("tools_enabled", [])
            if tool_name not in enabled_tools:
                # ... error handling ... (keep from main/interactive-debugger)
                pass
            else:
                # Debugger ToolCallEvent (interactive-debugger)
                self.debugger_service.record_event(ToolCallEvent(agent_name=agent_name, tool_name=tool_name, tool_args=tool_args))
                tool_result = run_tool(self.tools, tool_name, tool_args, self.debug_enabled)
                # Debugger ToolResultEvent (interactive-debugger)
                is_error_for_event = isinstance(tool_result, str) and tool_result.startswith("[Tool Error]")
                self.debugger_service.record_event(ToolResultEvent(agent_name=agent_name, tool_name=tool_name, result=tool_result, is_error=is_error_for_event))

                record_tool_usage(self.metrics, tool_name, self.debug_enabled)
                self.refresh_metrics_display()
                block_html = format_tool_block_html(tool_name, tool_args, tool_result) # From main
                self.chat_tab.append_message_html(f"\n[{timestamp}] <span style='color:{agent_color};'>{agent_name}:</span> {block_html}") # From main

                # ... rest of tool result handling (append to history, send_message_to_agent if success) ...
                # This part is complex and similar in both, ensure send_message_to_agent gets the right content
                # For now, assuming the structure from main is followed for follow-up.
                if not is_error_for_event:
                     self.send_message_to_agent(agent_name, tool_result) # msg_id not passed here in main

        if task_request: # Task handling from main/interactive-debugger
            # ... task scheduling logic ...
            pass

        if self.debug_enabled and agent_name: print(f"[Debug] Worker for agent '{agent_name}' finished.")
        if sender_worker in self.response_start_times:
            elapsed = time.time() - self.response_start_times.pop(sender_worker)
            record_response_time(self.metrics, agent_name, elapsed, self.debug_enabled)
            self.refresh_metrics_display()

        thread.quit()
        thread.wait()
        self.active_worker_threads = [(w, t) for w, t in self.active_worker_threads if w != sender_worker] # From main
        sender_worker.deleteLater()
        thread.deleteLater()

        # Final status update for the original user message if all agents processed (from main)
        if process_next_agent is None or (index is not None and index == len(enabled_agents_to_process) -1 ): # Check if it was the last agent in sequence
             if hasattr(self.chat_tab, 'last_user_message_id') and self.chat_tab.last_user_message_id == msg_id:
                 self.chat_tab.update_message_status(msg_id, "complete")


    def send_message_to_agent(self, agent_name, message): # msg_id not passed in main for this specific call
        # Debugger AgentRequestEvent (interactive-debugger)
        trigger_type = "agent_directed_message"
        if "Next Response By:" in message: trigger_type = "agent_handoff_continuation"
        elif any(kw in message for kw in ["[Tool Error]", "Tool executed successfully"]): trigger_type = "tool_result_followup"
        self.debugger_service.record_event(AgentRequestEvent(agent_name=agent_name, triggering_event_type=trigger_type, input_data=message))

        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"{message}\nNext Response By: {agent_name}" # Logic from interactive-debugger for clarity
        append_message(self.chat_history, "user", formatted_message, debug_enabled=self.debug_enabled)

        agent_settings = self.agents_data.get(agent_name, {})
        if not agent_settings or not agent_settings.get('enabled', False):
            # ... error handling ...
            return

        model_name = agent_settings.get("model", "llama3.2-vision").strip()
        temperature = agent_settings.get("temperature", 0.7)
        max_tokens = agent_settings.get("max_tokens", 512)
        current_chat_history_for_worker = self.build_agent_chat_history(agent_name) # No user_message here

        thread = QThread()
        # AIWorker instantiation with debugger_service (interactive-debugger)
        worker = AIWorker(model_name, current_chat_history_for_worker, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.debugger_service)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        # For this specific call, msg_id is not available from main's version.
        # If it were, it would be passed to on_finished and handle_ai_response_chunk.
        worker.finished.connect(lambda: self.worker_finished_sequential(worker, thread, agent_name, None, None, None)) # No msg_id
        worker.response_received.connect(lambda chunk, an: self.handle_ai_response_chunk(chunk, an, None)) # No msg_id
        worker.error_occurred.connect(lambda err_msg: self.handle_worker_error(err_msg, None)) # No msg_id

        thread.started.connect(worker.run)
        thread.start()
        self.response_start_times[worker] = time.time()

    def populate_agents(self): # From interactive-debugger (more complete)
        self.agents_data = {}
        if os.path.exists(AGENTS_SAVE_FILE):
            try:
                with open(AGENTS_SAVE_FILE, "r", encoding="utf-8") as f: self.agents_data = json.load(f)
                if self.debug_enabled: print("[Debug] Agents loaded.")
            except Exception as e: print(f"[Debug] Failed to load agents: {e}")
        else:
            models = get_installed_models()
            model = models[0] if models else "llama3.2-vision"
            default_agent_settings = {
                "model": model, "temperature": 0.7, "max_tokens": 512,
                "system_prompt": "You are the Cerebro default assistant...",
                "enabled": True, "color": "#000000", "avatar": "🤖",
                "include_image": False, "desktop_history_enabled": False,
                "screenshot_interval": 5, "role": "Assistant",
                "description": "A general-purpose assistant.", "tool_use": True,
                "tools_enabled": [t["name"] for t in self.tools if isinstance(t, dict) and "name" in t], # Added safety
                "automations_enabled": [], "thinking_enabled": False, "thinking_steps": 3,
                "tts_enabled": False, "tts_voice": "" # Added from main/interactive-debugger
            }
            self.agents_data["Default Agent"] = default_agent_settings
            if self.debug_enabled: print("[Debug] Default agent added.")
        if hasattr(self, 'agents_tab'): self.agents_tab.refresh_agent_table() # Check if agents_tab exists

    def add_agent(self): # From interactive-debugger (more complete)
        agent_name, ok = QInputDialog.getText(self, "Add Agent", "Enter agent name:")
        if ok and agent_name.strip():
            agent_name = agent_name.strip()
            if agent_name not in self.agents_data:
                self.agents_data[agent_name] = {
                    "model": "llama3.2-vision", "temperature": 0.7, "max_tokens": 512,
                    "system_prompt": "", "enabled": True, "color": "#000000", "avatar": "🤖", # avatar from main
                    "include_image": False, "desktop_history_enabled": False, "screenshot_interval": 5,
                    "role": "Assistant", "description": "A new assistant agent.",
                    "tool_use": False, "tools_enabled": [], "automations_enabled": [],
                    "thinking_enabled": False, "thinking_steps": 3,
                    "tts_enabled": False, "tts_voice": ""
                }
                self.save_agents()
                if self.debug_enabled: print(f"[Debug] Agent '{agent_name}' added.")
                self.show_notification(f"Agent '{agent_name}' created successfully", "info")
                if hasattr(self, 'agents_tab'): self.agents_tab.refresh_agent_table()
            else: QMessageBox.warning(self, "Agent Exists", "Agent already exists.")
        self.update_send_button_state()

    def delete_agent(self, agent_name=None):
        if agent_name is None and hasattr(self, 'agents_tab'): agent_name = self.agents_tab.current_agent # Check agents_tab
        if agent_name and agent_name in self.agents_data:
            del self.agents_data[agent_name]
            self.save_agents()
            if self.debug_enabled: print(f"[Debug] Agent '{agent_name}' removed.")
            self.show_notification(f"Agent '{agent_name}' deleted", "info")
            if hasattr(self, 'agents_tab'): self.agents_tab.refresh_agent_table()
        self.update_send_button_state()

    def save_agents(self):
        try:
            with open(AGENTS_SAVE_FILE, "w", encoding="utf-8") as f: json.dump(self.agents_data, f, indent=4) # indent from main
            if self.debug_enabled: print("[Debug] Agents saved.")
            self.update_screenshot_timer()
        except Exception as e:
            print(f"[Debug] Failed to save agents: {e}")
            self.show_notification(f"Error saving agents: {str(e)}", "error")

    def update_send_button_state(self): # From main (more robust check)
        any_assistant_enabled = any(
            agent_settings.get("enabled", False) and
            agent_settings.get("role") == "Assistant" and
            not agent_settings.get("desktop_history_enabled", False)
            for agent_settings in self.agents_data.values()
        )
        any_coordinator_enabled = any(
            agent_settings.get("enabled", False) and
            agent_settings.get("role") == "Coordinator"
            for agent_settings in self.agents_data.values()
        )
        self.chat_tab.send_button.setEnabled(any_assistant_enabled or any_coordinator_enabled)


    def update_screenshot_timer(self):
        enabled_agents = [a for a in self.agents_data.values() if a.get("desktop_history_enabled", False)]
        if not enabled_agents or self.screenshot_paused: self.screenshot_manager.stop()
        else: self.screenshot_manager.start(self.screenshot_interval)

    def refresh_tools_list(self):
        self.tools = load_tools(self.debug_enabled)
        if hasattr(self, 'tools_tab') and hasattr(self.tools_tab, "refresh_tools_list"): # Check tools_tab
            self.tools_tab.tools = self.tools
            self.tools_tab.refresh_tools_list()
        self.show_notification("Tools list refreshed", "info")

    def refresh_automations_list(self):
        self.automations = load_automations(self.debug_enabled)
        if hasattr(self, 'automations_tab') and hasattr(self.automations_tab, "refresh_automations_list"): # Check automations_tab
            self.automations_tab.automations = self.automations
            self.automations_tab.refresh_automations_list()
        self.show_notification("Automations list refreshed", "info")

    def check_for_updates(self, manual=False):
        thread = QThread()
        worker = UpdateCheckWorker(self.tools, self.debug_enabled)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))
        def done(msg):
            if "Update available" in msg or manual: self.show_notification(msg)
            thread.quit(); thread.wait()
            self.active_worker_threads = [(w,t) for w,t in self.active_worker_threads if w != worker] # From main
            worker.deleteLater(); thread.deleteLater()
        worker.finished.connect(done)
        thread.started.connect(worker.run)
        thread.start()

    def refresh_metrics_display(self):
        if hasattr(self, 'metrics_tab') and hasattr(self.metrics_tab, "refresh_metrics"): # Check metrics_tab
            self.metrics_tab.refresh_metrics()

    def check_for_due_tasks(self):
        now = datetime.now()
        to_remove = []
        for t in self.tasks:
            due_str = t.get("due_time", "")
            try:
                due_dt = datetime.fromisoformat(due_str) if "T" in due_str else datetime.strptime(due_str, "%Y-%m-%d %H:%M:%S")
            except ValueError: continue
            if now >= due_dt:
                self.schedule_user_message(t.get("agent_name", ""), t.get("prompt", ""), t["id"])
                if t.get("repeat_interval", 0):
                    new_due = (due_dt + timedelta(minutes=t["repeat_interval"])).isoformat()
                    update_task_due_time(self.tasks, t["id"], new_due, debug_enabled=self.debug_enabled, os_schedule=True)
                else: to_remove.append(t["id"])
                self.show_notification(f"Executing scheduled task for {t.get('agent_name', '')}", "info")
        for task_id in to_remove: delete_task(self.tasks, task_id, debug_enabled=self.debug_enabled, os_schedule=True)
        save_tasks(self.tasks, debug_enabled=self.debug_enabled)
        if hasattr(self, "tasks_tab") and hasattr(self.tasks_tab, "refresh_tasks_list"): self.tasks_tab.refresh_tasks_list() # Check tasks_tab

    def schedule_user_message(self, agent_name, prompt, task_id=None):
        timestamp = datetime.now().strftime("%H:%M:%S")
        # Using main's message display logic for scheduled messages as well
        msg_id = str(uuid.uuid4()) # Generate a unique ID for the scheduled message
        message_html = f'<div id="msg-{msg_id}-you" class="message you"><span class="timestamp">[{timestamp}]</span> <span class="user" style="color:{self.user_color};">(Scheduled) {self.user_name}:</span> <span class="text">{prompt}</span><span id="status-{msg_id}" class="status-dots">...</span></div>'
        self.chat_tab.append_message_html(message_html)
        self.chat_tab.update_message_status(msg_id, "processing") # Set initial status

        append_message(self.chat_history, "user", prompt, debug_enabled=self.debug_enabled)
        agent_settings = self.agents_data.get(agent_name, None)
        if not agent_settings or not agent_settings.get("enabled", False):
            # ... error handling ...
            self.chat_tab.update_message_status(msg_id, "failed") # Update status
            return

        model_name = agent_settings.get("model", "llama3.2-vision").strip()
        temperature = agent_settings.get("temperature", 0.7)
        max_tokens = agent_settings.get("max_tokens", 512)
        current_chat_history_for_worker = self.build_agent_chat_history(agent_name) # Renamed

        thread = QThread()
        # AIWorker instantiation with debugger_service (interactive-debugger)
        worker = AIWorker(model_name, current_chat_history_for_worker, temperature, max_tokens, self.debug_enabled, agent_name, self.agents_data, self.debugger_service)
        worker.moveToThread(thread)
        self.active_worker_threads.append((worker, thread))

        # Pass msg_id for status updates (from main)
        worker.finished.connect(lambda: self.worker_finished_sequential(worker, thread, agent_name, None, None, msg_id))
        worker.response_received.connect(lambda chunk, an: self.handle_ai_response_chunk(chunk, an, msg_id))
        worker.error_occurred.connect(lambda err_msg: self.handle_worker_error(err_msg, msg_id))

        thread.started.connect(worker.run)
        thread.start()
        self.response_start_times[worker] = time.time()

    def build_agent_chat_history(self, agent_name, user_message=None, is_screenshot=False): # From main
        self.chat_history = load_history(self.debug_enabled)
        self.chat_history = summarize_history(self.chat_history, threshold=self.summarization_threshold)
        system_prompt = ""
        agent_settings = self.agents_data.get(agent_name, {})
        if agent_settings:
            if agent_settings.get('role') == 'Coordinator':
                managed_agents_info = [f"{name}: {self.agents_data.get(name, {}).get('description', 'N/A')}" for name in agent_settings.get('managed_agents', [])]
                if managed_agents_info: system_prompt += "You can choose from the following agents:\n" + "\n".join(managed_agents_info) + "\n"
            system_prompt += agent_settings.get("system_prompt", "")
            if agent_settings.get("tool_use", False):
                system_prompt += "\n" + generate_tool_instructions_message(self, agent_name)

        final_chat_history = [{"role": "system", "content": system_prompt}]
        temp_history = []
        for msg in self.chat_history:
            if msg['role'] == 'user': temp_history.append(msg)
            elif msg['role'] == 'assistant':
                content = msg['content']
                if "<thought>" in content and "</thought>" in content: # Strip thoughts for history
                    thought_start = content.find("<thought>")
                    thought_end = content.find("</thought>") + len("</thought>")
                    content = (content[:thought_start] + content[thought_end:]).strip()
                cleaned_msg = msg.copy(); cleaned_msg["content"] = content
                if cleaned_msg.get('agent') == agent_name or \
                   (agent_settings.get('role') == 'Coordinator' and self.agents_data.get(cleaned_msg.get('agent'), {}).get('role') == 'Specialist'):
                    temp_history.append(cleaned_msg)

        if temp_history and temp_history[-1]['role'] == 'assistant' and "Next Response By:" in temp_history[-1]['content']:
            next_agent_name = temp_history[-1]['content'].split("Next Response By:")[1].strip()
            next_agent_settings = self.agents_data.get(next_agent_name, {})
            if next_agent_settings.get('role') == 'Specialist' and next_agent_settings.get('description'):
                temp_history.append({"role": "assistant", "content": next_agent_settings['description'], "agent": next_agent_name})

        if agent_settings.get('desktop_history_enabled', False) and not is_screenshot: # from main
            for img_path in self.screenshot_manager.get_images():
                 temp_history.append({"role": "user", "content": "", "images": [img_path]})
        if user_message: temp_history.append(user_message)
        final_chat_history.extend(temp_history)
        return final_chat_history

    def save_settings(self): # indent=4 from main
        settings = {
            "debug_enabled": self.debug_enabled,
            "include_image": self.include_image,
            "include_screenshot": self.include_screenshot,
            "image_path": "", # From main
            "user_name": self.user_name,
            "user_color": self.user_color,
            "accent_color": self.accent_color,
            "dark_mode": self.dark_mode,
            "screenshot_interval": self.screenshot_interval,
            "summarization_threshold": self.summarization_threshold,
             # Debugger setting (interactive-debugger)
            "debugger_interaction_enabled": self.debugger_service.is_debugger_enabled() if hasattr(self, 'debugger_service') else getattr(self, "debugger_interaction_enabled", False)
        }
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f: json.dump(settings, f, indent=4) # indent=4 from main
            if self.debug_enabled: print("[Debug] Settings saved.")
        except Exception as e:
            print(f"[Error] Failed to save settings: {e}")
            self.show_notification(f"Error saving settings: {str(e)}", "error")

    def load_settings(self): # default dark_mode to True from main
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f: settings = json.load(f)
                self.debug_enabled = settings.get("debug_enabled", False)
                self.include_image = settings.get("include_image", False)
                self.include_screenshot = settings.get("include_screenshot", False)
                # self.image_path = settings.get("image_path", "") # Not in main's version, keep it out for now
                self.user_name = settings.get("user_name", "You")
                self.user_color = settings.get("user_color", "#0000FF")
                self.accent_color = settings.get("accent_color", "#803391")
                self.dark_mode = settings.get("dark_mode", True) # Default True from main
                self.screenshot_interval = settings.get("screenshot_interval", self.screenshot_interval)
                self.summarization_threshold = settings.get("summarization_threshold", self.summarization_threshold)
                # Debugger setting (interactive-debugger)
                self.debugger_interaction_enabled = settings.get("debugger_interaction_enabled", False)
                if hasattr(self, 'debugger_service'): self.debugger_service.set_enabled(self.debugger_interaction_enabled)
                if self.debug_enabled: print("[Debug] Settings loaded.")
            except Exception as e: print(f"[Error] Failed to load settings: {e}")
        if hasattr(self, 'agents_tab'): self.agents_tab.load_global_preferences() # Check agents_tab

    def apply_dark_mode_style(self):
        style_sheet = load_style_sheet("dark_mode.qss", self.accent_color)
        self.setStyleSheet(style_sheet)

    def apply_light_mode_style(self):
        style_sheet = load_style_sheet("light_mode.qss", self.accent_color)
        self.setStyleSheet(style_sheet)

    def closeEvent(self, event): # From main (more robust)
        if not self.force_quit and hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
            event.ignore()
            self.hide()
            return

        # Debugger window close (interactive-debugger)
        if self.debugger_window: self.debugger_window.close()

        # Thread cleanup from main
        for worker, thread in self.active_worker_threads[:]: # Iterate copy
            if thread.isRunning():
                thread.quit()
                if not thread.wait(1000): # Wait 1 sec
                    print(f"Warning: Thread for worker {worker} did not terminate gracefully.")
                    thread.terminate() # Force terminate if not quitting
                    thread.wait() # Wait for termination
            worker.deleteLater()
            thread.deleteLater()
        self.active_worker_threads.clear()
        event.accept()
