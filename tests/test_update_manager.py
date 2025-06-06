from tool_plugins import update_manager
import version


class FakeResponse:
    def __init__(self, data=b"x"):
        self.data = data
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return {"tag_name": "0.2.0"}

    def iter_content(self, chunk_size=8192):
        yield self.data


def fake_get(url, stream=False, timeout=5):
    return FakeResponse()


def test_check_update(monkeypatch):
    monkeypatch.setattr(update_manager.requests, "get", fake_get)
    monkeypatch.setattr(version, "__version__", "0.1.0")
    result = update_manager.run_tool({"action": "check"})
    assert "Update available" in result


def test_update_download(monkeypatch, tmp_path):
    monkeypatch.setattr(update_manager.requests, "get", fake_get)
    result = update_manager.run_tool({"action": "update", "version": "0.2.0", "download_dir": tmp_path})
    assert (tmp_path / "cerebro-0.2.0.zip").exists()
    assert "Downloaded" in result


def test_rollback(tmp_path):
    backup = tmp_path / "backup.zip"
    backup.write_text("data")
    result = update_manager.run_tool({"action": "rollback", "download_dir": tmp_path})
    assert "Rollback completed" in result
