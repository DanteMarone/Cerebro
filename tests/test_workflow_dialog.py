import os
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
import tab_workflows

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

def test_selected_agents():
    app = QApplication.instance() or QApplication([])
    dlg = tab_workflows.WorkflowDialog(["a1", "a2", "a3"])
    for i in range(dlg.agent_list.count()):
        item = dlg.agent_list.item(i)
        if item.text() in {"a1", "a3"}:
            item.setCheckState(Qt.Checked)
    data = dlg.get_data()
    assert set(data["agents"]) == {"a1", "a3"}
    app.quit()
