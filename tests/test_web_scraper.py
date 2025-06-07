import tool_plugins.web_scraper as ws
import tools

class FakeResponse:
    def __init__(self, text):
        self.text = text
    def raise_for_status(self):
        pass

def fake_get(url, timeout):
    assert url == "http://example.com"
    assert timeout == 5
    html = "<html><body><h1>Hi</h1><script>alert(1)</script><p>test</p></body></html>"
    return FakeResponse(html)

def test_run_tool(monkeypatch):
    monkeypatch.setattr(ws.requests, "get", fake_get)
    result = ws.run_tool({"url": "http://example.com"})
    assert "Hi" in result
    assert "test" in result
    assert "alert" not in result

def test_missing_url():
    assert "[web-scraper Error]" in ws.run_tool({})

def test_plugin_discovery():
    plugins = tools.discover_plugin_tools()
    names = [p["name"] for p in plugins]
    assert "web-scraper" in names
    assert "huggingface-auth" in names
