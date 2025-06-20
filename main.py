# main.py

import sys
from PyQt5.QtWidgets import QApplication
from app import AIChatApp

if __name__ == '__main__':
    print("[Debug] Starting AIChatApp...")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    main_window = AIChatApp()
    main_window.show()
    sys.exit(app.exec_())
