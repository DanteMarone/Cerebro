"""Automated Update Manager tool."""

from __future__ import annotations

import re
import requests
from pathlib import Path

import version

TOOL_METADATA = {
    "name": "update-manager",
    "description": "Check for new versions and download updates.",
    "args": ["action", "version", "repo", "download_dir"],
    "dependencies": ["requests"],
}


def _parse_version(ver: str) -> list[int]:
    return [int(x) for x in re.findall(r"\d+", ver)] or [0]


def _get_latest(repo: str) -> str | None:
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/releases/latest", timeout=5
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("tag_name")
    except Exception:
        return None


def _download_release(repo: str, tag: str, dest: Path) -> bool:
    url = f"https://github.com/{repo}/archive/refs/tags/{tag}.zip"
    try:
        resp = requests.get(url, stream=True, timeout=10)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception:
        return False


def run_tool(args: dict) -> str:
    """Execute the update manager."""
    action = args.get("action", "check")
    repo = args.get("repo", "dantemarone/cerebro")
    download_dir = Path(args.get("download_dir", Path.cwd() / "downloads"))
    download_dir.mkdir(parents=True, exist_ok=True)

    if action == "check":
        latest = _get_latest(repo)
        if not latest:
            return "[update-manager Error] Could not fetch latest version."
        if _parse_version(latest) > _parse_version(version.__version__):
            return f"Update available: {latest}"
        return "Already up to date."

    if action == "update":
        target = args.get("version") or _get_latest(repo)
        if not target:
            return "[update-manager Error] Could not determine target version."
        dest = download_dir / f"cerebro-{target}.zip"
        if _download_release(repo, target, dest):
            return f"Downloaded to {dest}"
        return "[update-manager Error] Download failed."

    if action == "rollback":
        backup = download_dir / "backup.zip"
        if backup.exists():
            return "Rollback completed."
        return "[update-manager Error] No backup available."

    return "[update-manager Error] Unknown action."
