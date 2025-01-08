# tab_tools.py

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QHBoxLayout, QPushButton, QListWidgetItem,
    QLabel, QMessageBox, QDialog
)
from dialogs import ToolDialog
from tools import add_tool, edit_tool, delete_tool


class ToolsTab(QWidget):
    """
    Integrated version of Tools management (previously ToolsWindow).
    """
    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app
        self.tools = self.parent_app.tools

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        # Tools List
        self.tools_list = QListWidget()
        self.layout.addWidget(self.tools_list)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Tool")
        btn_layout.addWidget(self.add_button)
        self.layout.addLayout(btn_layout)

        # Connect signals
        self.add_button.clicked.connect(self.add_tool_ui)

        self.refresh_tools_list()

    def refresh_tools_list(self):
        self.tools_list.clear()
        for t in self.tools:
            item = QListWidgetItem()
            item.setText(f"{t['name']}: {t['description']}")
            self.tools_list.addItem(item)

            container = QWidget()
            h_layout = QHBoxLayout(container)
            h_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(f"{t['name']}: {t['description']}")
            edit_btn = QPushButton("Edit")
            del_btn = QPushButton("Delete")

            edit_btn.clicked.connect(lambda _, tn=t['name']: self.edit_tool_ui(tn))
            del_btn.clicked.connect(lambda _, tn=t['name']: self.delete_tool_ui(tn))

            h_layout.addWidget(label)
            h_layout.addWidget(edit_btn)
            h_layout.addWidget(del_btn)
            container.setLayout(h_layout)

            self.tools_list.setItemWidget(item, container)

    def add_tool_ui(self):
        dialog = ToolDialog(title="Add Tool")
        if dialog.exec_() == QDialog.Accepted:
            name, desc, script = dialog.get_data()
            err = add_tool(self.tools, name, desc, script, self.parent_app.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Adding Tool", err)
            else:
                self.parent_app.refresh_tools_list()
                self.tools = self.parent_app.tools
                self.refresh_tools_list()

    def edit_tool_ui(self, tool_name):
        tool = next((t for t in self.tools if t['name'] == tool_name), None)
        if not tool:
            QMessageBox.warning(self, "Error", f"No tool named '{tool_name}' found.")
            return
        dialog = ToolDialog(
            title="Edit Tool",
            name=tool["name"],
            description=tool["description"],
            script=tool["script"]
        )
        if dialog.exec_() == QDialog.Accepted:
            new_name, desc, script = dialog.get_data()
            err = edit_tool(self.tools, tool["name"], new_name, desc, script, self.parent_app.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Editing Tool", err)
            else:
                self.parent_app.refresh_tools_list()
                self.tools = self.parent_app.tools
                self.refresh_tools_list()

    def delete_tool_ui(self, tool_name):
        reply = QMessageBox.question(
            self,
            'Confirm Delete',
            f"Are you sure you want to delete the tool '{tool_name}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            err = delete_tool(self.tools, tool_name, self.parent_app.debug_enabled)
            if err:
                QMessageBox.warning(self, "Error Deleting Tool", err)
            else:
                self.parent_app.refresh_tools_list()
                self.tools = self.parent_app.tools
                self.refresh_tools_list()
