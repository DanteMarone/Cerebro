#tab_tools.py
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QHBoxLayout, QPushButton, QListWidgetItem,
    QLabel, QMessageBox, QDialog, QStyle, QAbstractItemView
)
from PyQt5.QtCore import Qt  # Import Qt from PyQt5.QtCore
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
        self.tools_list.setSelectionMode(QAbstractItemView.SingleSelection)  # Enforce single selection
        self.tools_list.itemSelectionChanged.connect(self.on_item_selection_changed) # Connect selection change
        self.layout.addWidget(self.tools_list)

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Tool")
        self.add_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileIcon')))
        self.add_button.setToolTip("Add a new tool.")
        btn_layout.addWidget(self.add_button)
        self.layout.addLayout(btn_layout)

        # Edit and Delete Buttons (initially hidden)
        self.edit_button = QPushButton("Edit")
        self.edit_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileDialogDetailedView')))
        self.edit_button.setToolTip("Edit the selected tool.")
        self.edit_button.hide()
        btn_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_TrashIcon')))
        self.delete_button.setToolTip("Delete the selected tool.")
        self.delete_button.hide()
        btn_layout.addWidget(self.delete_button)

        # Connect signals
        self.add_button.clicked.connect(self.add_tool_ui)
        self.edit_button.clicked.connect(self.edit_tool_ui)
        self.delete_button.clicked.connect(self.delete_tool_ui)

        self.refresh_tools_list()

    def on_item_selection_changed(self):
        """
        Show or hide the Edit/Delete buttons based on whether an item is selected.
        """
        selected_items = self.tools_list.selectedItems()
        if selected_items:
            self.edit_button.show()
            self.delete_button.show()
        else:
            self.edit_button.hide()
            self.delete_button.hide()

    def refresh_tools_list(self):
        self.tools_list.clear()
        user_tools = [t for t in self.tools if 'plugin_module' not in t]
        if not user_tools:
            label = QLabel("No tools available.")
            label.setAlignment(Qt.AlignCenter)
            self.layout.addWidget(label)
        else:
            for t in user_tools:
                item = QListWidgetItem()
                item.setText(f"{t['name']}: {t['description']}")
                item.setData(Qt.UserRole, t['name'])
                self.tools_list.addItem(item)

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

    def edit_tool_ui(self):
        selected_items = self.tools_list.selectedItems()
        if not selected_items:
            return
        
        # Get the tool name from the selected item's data
        tool_name = selected_items[0].data(Qt.UserRole)

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

    def delete_tool_ui(self):
        selected_items = self.tools_list.selectedItems()
        if not selected_items:
            return

        # Get the tool name from the selected item's data
        tool_name = selected_items[0].data(Qt.UserRole)

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