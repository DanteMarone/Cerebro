import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
import tab_automations

class DummyApp:
    def __init__(self):
        self.automations = []
        self.debug_enabled = False
        self.main_window = None

def test_clear_parameter_editor_safe():
    app = QApplication.instance() or QApplication([])
    tab = tab_automations.AutomationsTab(DummyApp())
    tab._clear_parameter_editor()
    tab.placeholder_param_label.setText("Placeholder")
    assert tab.param_form_layout.rowCount() == 1
    app.quit()


def test_populate_parameter_editor_ask_agent_qcheckbox():
    app = QApplication.instance() or QApplication([])
    tab = tab_automations.AutomationsTab(DummyApp())
    step_data = {
        "type": tab_automations.STEP_TYPE_ASK_AGENT,
        "params": {
            "prompt": "hi",
            "agent_name": "(No Agent)",
            "send_screenshot": True,
        },
    }
    tab._populate_parameter_editor(step_data)
    widget = tab.current_param_widgets.get("send_screenshot")
    assert isinstance(widget, tab_automations.QCheckBox)
    assert widget.isChecked()
    app.quit()


def test_double_click_adds_step_to_sequence():
    app = QApplication.instance() or QApplication([])
    tab = tab_automations.AutomationsTab(DummyApp())
    first_item = tab.available_steps_list.item(0)
    tab.available_steps_list.itemDoubleClicked.emit(first_item)
    assert tab.step_sequence_list.count() == 1
    assert tab.step_sequence_list.item(0).text().startswith(first_item.text())
    app.quit()


def test_step_sequence_is_reorderable():
    app = QApplication.instance() or QApplication([])
    tab = tab_automations.AutomationsTab(DummyApp())
    assert tab.step_sequence_list.dragDropMode() == tab_automations.QAbstractItemView.InternalMove
    app.quit()
