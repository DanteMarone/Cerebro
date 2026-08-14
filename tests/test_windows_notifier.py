from tool_plugins import windows_notifier as wn
import sys


def test_windows_notifier_threaded(monkeypatch):
    """Notification should use threaded=True to avoid blocking."""
    calls = {}

    class FakeToast:
        def show_toast(self, title, message, duration=5, threaded=False):
            calls['threaded'] = threaded
            return True

    fake_toast_mod = type('m', (), {'ToastNotifier': lambda: FakeToast()})
    monkeypatch.setitem(sys.modules, 'win10toast', fake_toast_mod)
    result = wn.run_tool({'title': 'T', 'message': 'M'})
    assert result == "Notification sent"
    assert calls.get('threaded') is True
