from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QHBoxLayout, QPushButton,
    QListWidgetItem, QFileDialog, QMessageBox, QStyle
)
from PyQt5.QtCore import Qt

from tools import (
    get_available_plugins,
    install_plugin,
    set_plugin_enabled,
)
import tools


class PluginsTab(QWidget):
    """UI for managing plugin-based tools."""

    def __init__(self, parent_app):
        super().__init__()
        self.parent_app = parent_app

        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

        self.plugins_list = QListWidget()
        self.plugins_list.itemChanged.connect(self.on_item_changed)
        self.layout.addWidget(self.plugins_list)

        btn_layout = QHBoxLayout()
        self.install_btn = QPushButton("Install Plugin")
        self.install_btn.setIcon(self.style().standardIcon(getattr(QStyle, "SP_DialogOpenButton")))
        btn_layout.addWidget(self.install_btn)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setIcon(self.style().standardIcon(getattr(QStyle, "SP_BrowserReload")))
        btn_layout.addWidget(self.reload_btn)
        self.layout.addLayout(btn_layout)

        self.install_btn.clicked.connect(self.install_plugin_ui)
        self.reload_btn.clicked.connect(self.refresh_plugins_list)

        self.refresh_plugins_list()

    def refresh_plugins_list(self):
        """Reload the plugin list."""
        self.plugins_list.blockSignals(True)
        self.plugins_list.clear()
        plugins = get_available_plugins(self.parent_app.debug_enabled)
        for plug in plugins:
            item = QListWidgetItem(f"{plug['name']}: {plug['description']}")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if plug.get("enabled") else Qt.Unchecked)
            item.setData(Qt.UserRole, plug['name'])
            self.plugins_list.addItem(item)
        self.plugins_list.blockSignals(False)
        # Update loaded tools without triggering notifications
        self.parent_app.tools = tools.load_tools(self.parent_app.debug_enabled)
        if hasattr(self.parent_app.tools_tab, "refresh_tools_list"):
            self.parent_app.tools_tab.tools = self.parent_app.tools
            self.parent_app.tools_tab.refresh_tools_list()

    def on_item_changed(self, item):
        name = item.data(Qt.UserRole)
        enabled = item.checkState() == Qt.Checked
        set_plugin_enabled(name, enabled)
        self.parent_app.refresh_tools_list()

    def install_plugin_ui(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Plugin", "", "Python Files (*.py)")
        if not path:
            return
        err = install_plugin(path, self.parent_app.debug_enabled)
        if err:
            QMessageBox.warning(self, "Install Error", err)
        self.refresh_plugins_list()

