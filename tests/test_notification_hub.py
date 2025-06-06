from tool_plugins import notification_hub as nh


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

