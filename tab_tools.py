#tab_tools.py
from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QMessageBox,
    QDialog,
    QStyle,
    QAbstractItemView,
    QInputDialog,
    QLineEdit,
)
from importlib import util as importlib_util
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from dialogs import ToolDialog
from tools import add_tool, edit_tool, delete_tool, run_tool, get_available_plugins
import json

# Mapping of status text to display color and icon
TOOL_STATUS_STYLES = {
    "Enabled": {"color": "#4caf50", "icon": QStyle.SP_DialogApplyButton},
    "Disabled": {"color": "#9e9e9e", "icon": QStyle.SP_DialogCancelButton},
    "Error": {"color": "#f44336", "icon": QStyle.SP_MessageBoxCritical},
    "Needs Configuration": {"color": "#ff9800", "icon": QStyle.SP_MessageBoxWarning},
}


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
        self.tools_list = QTreeWidget()
        self.tools_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tools_list.setHeaderLabels(["Name", "Description", "Status"])
        self.tools_list.itemSelectionChanged.connect(self.on_item_selection_changed)
        self.layout.addWidget(self.tools_list)

        # Label shown when no tools are present
        self.no_tools_label = QLabel("No tools available.")
        self.no_tools_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.no_tools_label)
        self.no_tools_label.hide()

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_button = QPushButton("Add Tool")
        self.add_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileIcon')))
        self.add_button.setToolTip("Add a new tool.")
        btn_layout.addWidget(self.add_button)
        self.layout.addLayout(btn_layout)

        # Edit, Delete and Run Buttons (start disabled)
        self.edit_tool_button = QPushButton("Edit Tool")
        self.edit_tool_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_FileDialogDetailedView')))
        self.edit_tool_button.setToolTip("Edit the selected tool.")
        self.edit_tool_button.setEnabled(False)
        btn_layout.addWidget(self.edit_tool_button)

        self.delete_button = QPushButton("Delete")
        self.delete_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_TrashIcon')))
        self.delete_button.setToolTip("Delete the selected tool.")
        self.delete_button.setEnabled(False)
        btn_layout.addWidget(self.delete_button)

        self.run_button = QPushButton("Run")
        self.run_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_MediaPlay')))
        self.run_button.setToolTip("Run the selected tool for testing.")
        self.run_button.setEnabled(False)
        btn_layout.addWidget(self.run_button)

        self.setup_button = QPushButton("Setup")
        self.setup_button.setIcon(self.style().standardIcon(getattr(QStyle, 'SP_DialogHelpButton')))
        self.setup_button.setToolTip("Configure the selected tool.")
        self.setup_button.setEnabled(False)
        btn_layout.addWidget(self.setup_button)

        # Connect signals
        self.add_button.clicked.connect(self.add_tool_ui)
        self.edit_tool_button.clicked.connect(self.edit_tool_ui)
        self.delete_button.clicked.connect(self.delete_tool_ui)
        self.run_button.clicked.connect(self.run_tool_ui)
        self.setup_button.clicked.connect(self.setup_tool_ui)

        self.refresh_tools_list()

    def on_item_selection_changed(self):
        """
        Enable or disable buttons based on whether an item is selected.
        """
        selected_items = self.tools_list.selectedItems()
        if not selected_items:
            self.edit_tool_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.run_button.setEnabled(False)
            self.setup_button.setEnabled(False)
            return

        self.run_button.setEnabled(True)
        self.edit_tool_button.setEnabled(True)
        self.delete_button.setEnabled(True)

        tool_name = selected_items[0].data(Qt.UserRole)
        tool = next((t for t in self.tools if t['name'] == tool_name), None)
        needs_setup = tool and (self.missing_dependencies(tool) or tool.get('needs_config'))
        self.setup_button.setEnabled(bool(needs_setup))

    def refresh_tools_list(self):
        self.tools_list.clear()
        self.no_tools_label.hide()
        self.edit_tool_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.run_button.setEnabled(False)

        builtins = [t for t in self.tools if 'plugin_module' not in t]
        plugins = get_available_plugins(self.parent_app.debug_enabled)

        if not builtins and not plugins:
            self.no_tools_label.show()
            return

        for tool in all_tools:
            # Determine the status of the tool
            if self.missing_dependencies(tool) or tool.get('needs_config'):
                status_text = "Needs Configuration"
            elif not tool.get('enabled', True): # Default to True for built-ins
                status_text = "Disabled"
            else:
                status_text = "Enabled"

            # Create the tree widget item with columns
            item = QTreeWidgetItem([tool['name'], tool['description'], status_text])
            
            # Store metadata in the item
            item.setData(0, Qt.UserRole, tool['name'])
            item.setData(0, Qt.UserRole + 1, 'plugin_module' in tool)

            # Apply visual styling based on the status
            style_info = TOOL_STATUS_STYLES.get(status_text, {})
            if style_info.get('icon'):
                icon = self.style().standardIcon(style_info['icon'])
                item.setIcon(2, icon)
            
            if status_text == "Disabled":
                for i in range(3): # Gray out all columns
                    item.setForeground(i, QColor('gray'))
                # Keep item selectable but not enabled for interaction
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            
            elif status_text == "Needs Configuration":
                 for i in range(3): # Use a distinct color for configuration needed
                    item.setForeground(i, QColor('#c67500')) # An orange/amber color
            
            # For non-editable plugin tools
            if 'plugin_module' in tool:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)

            self.tools_list.addTopLevelItem(item)

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

    def run_tool_ui(self):
        selected_items = self.tools_list.selectedItems()
        if not selected_items:
            return

        tool_name = selected_items[0].data(Qt.UserRole)

        text, ok = QInputDialog.getText(
            self,
            "Run Tool",
            "Arguments (JSON):",
            QLineEdit.Normal,
            "{}",
        )
        if not ok:
            return

        try:
            args = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            QMessageBox.warning(self, "Invalid Input", "Arguments must be valid JSON.")
            return

        output = run_tool(self.tools, tool_name, args, self.parent_app.debug_enabled)
        QMessageBox.information(self, "Tool Output", output)

    def missing_dependencies(self, tool):
        missing = []
        for dep in tool.get('dependencies', []):
            if importlib_util.find_spec(dep) is None:
                missing.append(dep)
        return missing

    def setup_tool_ui(self):
        selected_items = self.tools_list.selectedItems()
        if not selected_items:
            return

        tool_name = selected_items[0].data(Qt.UserRole)
        tool = next((t for t in self.tools if t['name'] == tool_name), None)
        if not tool:
            return

        missing = self.missing_dependencies(tool)
        msg = tool.get('description', '')
        if missing:
            msg += f"\nMissing dependencies: {', '.join(missing)}\nInstall with: pip install {' '.join(missing)}"
        if tool.get('needs_config'):
            msg += "\nAdditional configuration is required in Settings."
        QMessageBox.information(self, "Tool Setup", msg)
        if tool.get('needs_config'):
            self.parent_app.open_settings_dialog()
