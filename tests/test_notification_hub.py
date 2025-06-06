from tool_plugins import notification_hub as nh
import sys


def test_run_tool(monkeypatch):
    sent = []

    def fake_post(url, json=None, timeout=5):
        sent.append((url, json))
        class R:
            status_code = 200
        return R()

    monkeypatch.setattr(nh.requests, "post", fake_post)
    result = nh.run_tool({"title": "Hi", "message": "Test", "push_url": "http://x"})
    assert isinstance(result, str)
    assert sent == [("http://x", {"title": "Hi", "message": "Test"})]


def test_win_toast_threaded(monkeypatch):
    """Ensure win10toast uses threaded notifications on Windows."""
    calls = {}

    class FakeToast:
        def show_toast(self, title, message, duration=5, threaded=False):
            calls['threaded'] = threaded

    monkeypatch.setattr(nh, 'sys', type('s', (), {'platform': 'win32'}))
    monkeypatch.setitem(sys.modules, 'win10toast', type('m', (), {'ToastNotifier': lambda: FakeToast()}))
    nh.run_tool({'title': 't', 'message': 'm'})
    assert calls.get('threaded') is True

