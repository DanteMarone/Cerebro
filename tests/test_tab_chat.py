import os
from PyQt5.QtWidgets import QApplication
import tab_chat

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

class DummyApp:
    def __init__(self):
        self.notifications = []
    def show_notification(self, message, type="info"):
        self.notifications.append((message, type))
    def export_chat_histories(self):
        pass
    def clear_chat_histories(self):
        pass
    def clear_chat(self):
        pass
    def send_message(self, msg):
        pass


def test_save_conversation(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    dummy = DummyApp()
    tab = tab_chat.ChatTab(dummy)
    tab.chat_display.setPlainText("hello world")
    dest = tmp_path / "conv.txt"
    monkeypatch.setattr(tab_chat.QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), "txt"))
    tab.save_conversation()
    with open(dest, "r", encoding="utf-8") as f:
        assert f.read() == "hello world"
    assert dummy.notifications
    app.quit()

# Subtask executed successfully: Added this comment.

# --- Test Added by Automated Script ---
from datetime import datetime, date, timedelta
from unittest.mock import patch
from PyQt5.QtWidgets import QApplication
from tab_chat import ChatTab
# Assuming DummyApp is defined in tests/test_tab_chat.py

def new_test_example_single_message(monkeypatch):
    '''Test a single message append operation.'''
    app = QApplication.instance() or QApplication([])
    dummy_app_instance = DummyApp()
    dummy_app_instance.user_name = "TestUser"
    dummy_app_instance.agents_data = {}
    chat_tab = ChatTab(dummy_app_instance)
    chat_tab.user_avatar = "😊"

    mock_now_dt = datetime(2023, 10, 27, 10, 30, 0)
    message_time_dt = mock_now_dt - timedelta(seconds=30)

    monkeypatch.setattr("tab_chat.datetime", type("datetime_mock", (object,), {"now": lambda: mock_now_dt, "strptime": datetime.strptime, "combine": datetime.combine, "today": lambda: mock_now_dt.date()}))
    monkeypatch.setattr("tab_chat.date", type("date_mock", (object,), {"today": lambda: mock_now_dt.date(), "min": date.min, "max": date.max, "resolution": date.resolution, "timedelta": timedelta}))

    input_html = f"<span style=\\\"color:#123456;\\\">[{message_time_dt.strftime('%H:%M:%S')}] {dummy_app_instance.user_name}:</span> Test message content"

    chat_tab.append_message_html(input_html, from_user=True)
    html_output = chat_tab.chat_display.toHtml()

    assert f"<b>{dummy_app_instance.user_name}</b>" in html_output
    assert "just now" in html_output
    assert f'<span title=\\\"{message_time_dt.strftime(\"%I:%M:%S %p on %Y-%m-%d\")}\\\">just now</span>' in html_output
    if QApplication.instance(): QApplication.instance().quit()

# Test function 2 (Agent Message - Minutes Ago)
def new_test_append_agent_message_minutes_ago(monkeypatch):
    '''Test agent message appends correctly with 'Xm ago' timestamp.'''
    app = QApplication.instance() or QApplication([])
    dummy_app_instance = DummyApp()
    dummy_app_instance.user_name = "AnotherUser"
    agent_name = "TestAgent"
    agent_avatar = "🤖"
    dummy_app_instance.agents_data = {agent_name: {"avatar": agent_avatar}}
    chat_tab = ChatTab(dummy_app_instance)

    mock_now_dt = datetime(2023, 10, 27, 10, 30, 0)
    message_time_dt = mock_now_dt - timedelta(minutes=5)

    monkeypatch.setattr("tab_chat.datetime", type("datetime_mock", (object,), {"now": lambda: mock_now_dt, "strptime": datetime.strptime, "combine": datetime.combine, "today": lambda: mock_now_dt.date()}))
    monkeypatch.setattr("tab_chat.date", type("date_mock", (object,), {"today": lambda: mock_now_dt.date(), "min": date.min, "max": date.max, "resolution": date.resolution, "timedelta": timedelta}))

    input_html = f"[{message_time_dt.strftime('%H:%M:%S')}] <span style='color:#654321;'>{agent_name}:</span> Agent message"

    chat_tab.append_message_html(input_html, from_user=False)
    html_output = chat_tab.chat_display.toHtml()

    assert f"<b>{agent_name}</b>" in html_output
    assert "5m ago" in html_output
    assert f'<span title=\\\"{message_time_dt.strftime(\"%I:%M:%S %p on %Y-%m-%d\")}\\\">5m ago</span>' in html_output
    assert agent_avatar in html_output
    if QApplication.instance(): QApplication.instance().quit()

# Test function 3 (Agent Message - Absolute Time)
def new_test_append_message_absolute_time(monkeypatch):
    '''Test message appends correctly with absolute time for older messages.'''
    app = QApplication.instance() or QApplication([])
    dummy_app_instance = DummyApp()
    dummy_app_instance.user_name = "YetAnotherUser"
    agent_name = "TestAgentAbs"
    agent_avatar = "👻"
    dummy_app_instance.agents_data = {agent_name: {"avatar": agent_avatar}}
    chat_tab = ChatTab(dummy_app_instance)

    mock_now_dt = datetime(2023, 10, 27, 15, 0, 0)
    message_time_dt = mock_now_dt - timedelta(hours=4)

    monkeypatch.setattr("tab_chat.datetime", type("datetime_mock", (object,), {"now": lambda: mock_now_dt, "strptime": datetime.strptime, "combine": datetime.combine, "today": lambda: mock_now_dt.date()}))
    monkeypatch.setattr("tab_chat.date", type("date_mock", (object,), {"today": lambda: mock_now_dt.date(), "min": date.min, "max": date.max, "resolution": date.resolution, "timedelta": timedelta}))

    input_html = f"[{message_time_dt.strftime('%H:%M:%S')}] <span style='color:#aabbcc;'>{agent_name}:</span> Absolute time message"
    chat_tab.append_message_html(input_html, from_user=False)
    html_output = chat_tab.chat_display.toHtml()

    expected_time_str = message_time_dt.strftime(\"%I:%M %p\")
    assert f"<b>{agent_name}</b>" in html_output
    assert expected_time_str in html_output
    assert f'<span title=\\\"{message_time_dt.strftime(\"%I:%M:%S %p on %Y-%m-%d\")}\\\">{expected_time_str}</span>' in html_output
    assert agent_avatar in html_output
    if QApplication.instance(): QApplication.instance().quit()

# Test function 4 (Date Separator)
def new_test_date_separator_when_date_changes(monkeypatch):
    '''Test date separator is added when the message date changes.'''
    app = QApplication.instance() or QApplication([])
    dummy_app_instance = DummyApp()
    dummy_app_instance.user_name = "TestUser"
    dummy_app_instance.agents_data = {"AgentSep": {"avatar": "🤖"}}
    chat_tab = ChatTab(dummy_app_instance)

    chat_tab.last_message_date = date(2023, 10, 26)

    current_mocked_day = date(2023, 10, 27)

    monkeypatch.setattr("tab_chat.date", type("date_mock", (object,), {"today": lambda: current_mocked_day, "timedelta": timedelta, "min": date.min, "max": date.max, "resolution": date.resolution }))
    monkeypatch.setattr("tab_chat.datetime", type("datetime_mock", (object,), {"now": lambda: datetime.combine(current_mocked_day, datetime.min.time()), "strptime": datetime.strptime, "combine": datetime.combine, "today": lambda: current_mocked_day }))

    input_html = f\"[10:00:00] <span style='color:#123;'>AgentSep:</span> Message on new day\"
    chat_tab.append_message_html(input_html)
    html_output = chat_tab.chat_display.toHtml()

    assert '<div style=\"text-align:center; color:gray; margin:10px 0;\">--- Today ---</div>' in html_output
    if QApplication.instance(): QApplication.instance().quit()

# --- End of Tests Added by Automated Script ---
