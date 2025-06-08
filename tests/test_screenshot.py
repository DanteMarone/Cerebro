import os
import builtins
from tempfile import TemporaryDirectory
import screenshot

class FakePixmap:
    def save(self, path, fmt):
        with open(path, 'wb') as f:
            f.write(b'fake')
        return True

class FakeScreen:
    def grabWindow(self, _):
        return FakePixmap()

def test_capture_base64(monkeypatch):
    monkeypatch.setattr(screenshot.QGuiApplication, 'primaryScreen', lambda: FakeScreen())
    with TemporaryDirectory() as tmpdir:
        mgr = screenshot.ScreenshotManager(output_dir=tmpdir, interval=1, max_images=2)
        img1 = mgr.capture()
        assert isinstance(img1, str)
        assert len(mgr.get_images()) == 1
        img2 = mgr.capture()
        assert len(mgr.get_images()) == 2
        mgr.capture()
        assert len(mgr.get_images()) == 2  # respect max_images


def test_capture_screenshot_to_tempfile(monkeypatch):
    """capture_screenshot_to_tempfile should save image to a temporary file."""
    monkeypatch.setattr(screenshot.QGuiApplication, 'primaryScreen', lambda: FakeScreen())
    path = screenshot.capture_screenshot_to_tempfile()
    try:
        with open(path, 'rb') as f:
            data = f.read()
        assert data == b'fake'
    finally:
        os.remove(path)

