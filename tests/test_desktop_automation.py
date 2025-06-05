import os
import platform
import subprocess
import shutil
from tool_plugins import desktop_automation as da


def test_launch_windows(monkeypatch):
    called = {}
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(os, "startfile", lambda path: called.setdefault("path", path), raising=False)
    result = da.run_tool({"action": "launch", "target": "calc.exe"})
    assert "Launched" in result
    assert called["path"] == "calc.exe"


def test_move_file(monkeypatch, tmp_path):
    src = tmp_path / "a.txt"
    dst_dir = tmp_path / "dest"
    dst_dir.mkdir()
    src.write_text("data")

    moved = {}
    monkeypatch.setattr(shutil, "move", lambda s, d: moved.setdefault("args", (s, d)))
    result = da.run_tool({"action": "move", "target": str(src), "destination": str(dst_dir)})
    assert "Moved" in result
    assert moved["args"] == (str(src), str(dst_dir))


def test_launch_linux_fallback(monkeypatch):
    called = {}
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    monkeypatch.setattr(subprocess, "Popen", lambda args: called.setdefault("args", args))
    result = da.run_tool({"action": "launch", "target": "myapp"})
    assert "Launched" in result
    assert called["args"] == ["myapp"]
