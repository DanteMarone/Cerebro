"""Screenshot capture utilities."""

import os
from datetime import datetime
from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtGui import QGuiApplication


class ScreenshotManager(QObject):
    """Periodically capture screenshots of the primary screen."""

    def __init__(self, output_dir="screenshots", interval=5, max_images=10, parent=None):
        super().__init__(parent)
        self.output_dir = output_dir
        self.interval = interval
        self.max_images = max_images
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.capture)
        self.images = []
        os.makedirs(self.output_dir, exist_ok=True)

    def start(self, interval=None):
        """Start capturing screenshots."""
        if interval:
            self.interval = interval
        self.timer.start(int(self.interval * 1000))

    def stop(self):
        """Stop capturing screenshots."""
        self.timer.stop()

    def capture(self):
        """Capture the current screen and store the file path."""
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return None
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.output_dir, f"screenshot_{timestamp}.png")
        pixmap = screen.grabWindow(0)
        if pixmap.save(path, "png"):
            self.images.append(path)
            if len(self.images) > self.max_images:
                self.images.pop(0)
            return path
        return None

    def get_images(self):
        """Return list of recently captured images."""
        return list(self.images)
