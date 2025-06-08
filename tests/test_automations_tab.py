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
