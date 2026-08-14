"""Tests for the deploy script and the version-visibility it depends on.

The deployment gap was real and cost half a day of confusion: three fixes landed, the app looked
healthy, and it was running older code. The cases pinned here are the ones that make the tool
trustworthy rather than reassuring -- a backup that silently loses rows, and a check that says "fine"
about a question it could not ask.
"""

import sqlite3
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from cerebro.api.app import app
from cerebro.config import Settings

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import deploy  # noqa: E402


def _point_settings_at(monkeypatch, db_path, data_dir):
    """Settings is a frozen dataclass, so replace the object rather than a field."""
    import dataclasses

    monkeypatch.setattr(
        deploy, "settings",
        dataclasses.replace(deploy.settings, db_path=db_path, data_dir=data_dir),
    )


# -- version visibility -----------------------------------------------------------


@pytest.mark.asyncio
async def test_health_reports_the_commit_it_is_running(test_db: Settings):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/api/health")).json()

    assert "running_commit" in body
    assert "repo_commit" in body
    assert "stale" in body
    assert body["schema_version"] is not None, "a real migration level, not a hardcoded True"


def test_the_running_commit_is_captured_once_at_import():
    """It must be a snapshot, not a live read.

    Reading git on every request would report whatever HEAD says *now* -- which is exactly the value
    that hides the problem, because HEAD moves the moment somebody commits while the old process
    keeps serving. A process can only honestly report the code it loaded.
    """
    app_module = sys.modules["cerebro.api.app"]

    assert isinstance(app_module.RUNNING_COMMIT, (str, type(None)))
    assert "RUNNING_COMMIT = _git_commit()" in (
        Path(app_module.__file__).read_text(encoding="utf-8")
    ), "must be a module-level snapshot, not computed per request"


# -- backup -----------------------------------------------------------------------


def test_backup_refuses_when_the_copy_loses_rows(tmp_path, monkeypatch):
    """A backup that silently loses data is worse than none: the restore reports success.

    This is not hypothetical. Copying cerebro.db alone, with the database in WAL mode, produced a
    file with 0 messages while the live database held 363.
    """
    src = tmp_path / "cerebro.db"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
    con.executemany("INSERT INTO messages (id) VALUES (?)", [(i,) for i in range(10)])
    con.commit()
    con.close()

    _point_settings_at(monkeypatch, src, tmp_path)

    real_connect = sqlite3.connect

    class LosesRows:
        """A connection whose backup produces the schema but drops the data."""

        def __init__(self, conn):
            self._conn = conn

        def backup(self, target, **kwargs):
            target.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY)")

        def __getattr__(self, item):
            return getattr(self._conn, item)

        # Dunder lookups bypass __getattr__, and deploy.backup() uses `with target:`.
        def __enter__(self):
            return self._conn.__enter__()

        def __exit__(self, *exc):
            return self._conn.__exit__(*exc)

    def lossy_connect(*args, **kwargs):
        return LosesRows(real_connect(*args, **kwargs))

    monkeypatch.setattr(deploy.sqlite3, "connect", lossy_connect)

    with pytest.raises(deploy.DeployRefused, match="Refusing to restart"):
        deploy.backup()


def test_backup_verifies_and_returns_a_matching_copy(tmp_path, monkeypatch):
    src = tmp_path / "cerebro.db"
    con = sqlite3.connect(src)
    con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
    con.executemany("INSERT INTO messages (id) VALUES (?)", [(i,) for i in range(42)])
    con.commit()
    con.close()

    _point_settings_at(monkeypatch, src, tmp_path)

    dest = deploy.backup()

    check = sqlite3.connect(dest)
    assert check.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 42
    check.close()


# -- refusals ---------------------------------------------------------------------


def test_it_refuses_to_stop_a_process_it_cannot_identify(monkeypatch):
    """Owning the port is not identity.

    The hand-rolled restart this replaces force-killed whatever was listening on 8765, which would
    have taken an unrelated process with it.
    """
    monkeypatch.setattr(deploy, "owning_pids", lambda: [4321])
    monkeypatch.setattr(deploy, "command_line", lambda pid: "C:\\Windows\\notepad.exe")

    with pytest.raises(deploy.DeployRefused, match="does not look like Cerebro"):
        deploy.stop_service()


def test_check_treats_an_unanswerable_question_as_stale(monkeypatch, capsys):
    """A server that cannot report its commit predates the feature, so it is stale by definition.

    Found by running --check against the live server: it answered health happily, reported
    stale=None, and the first version of this cheerfully said "up to date" about a process it could
    not interrogate.
    """
    monkeypatch.setattr(deploy, "git_state", lambda: {
        "head": "abc1234", "branch": "v2", "dirty": False, "origin": "abc1234"})
    monkeypatch.setattr(deploy, "health", lambda: {"status": "ok", "db": True})
    monkeypatch.setattr(sys, "argv", ["deploy.py", "--check"])

    assert deploy.main() == 1
    assert "CANNOT DETERMINE" in capsys.readouterr().out


def test_check_reports_a_stale_server(monkeypatch, capsys):
    monkeypatch.setattr(deploy, "git_state", lambda: {
        "head": "newcommit", "branch": "v2", "dirty": False, "origin": "newcommit"})
    monkeypatch.setattr(deploy, "health", lambda: {
        "status": "ok", "db": True, "running_commit": "oldcommit",
        "repo_commit": "newcommit", "stale": True, "schema_version": 4})
    monkeypatch.setattr(sys, "argv", ["deploy.py", "--check"])

    assert deploy.main() == 1
    assert "STALE" in capsys.readouterr().out


def test_deploy_refuses_a_dirty_tree(monkeypatch, capsys):
    """What restarts must be what is committed, or the reported commit is a lie."""
    monkeypatch.setattr(deploy, "git_state", lambda: {
        "head": "abc1234", "branch": "v2", "dirty": True, "origin": "abc1234"})
    monkeypatch.setattr(deploy, "health", lambda: None)
    monkeypatch.setattr(sys, "argv", ["deploy.py"])

    assert deploy.main() == 2
    assert "working tree is dirty" in capsys.readouterr().err


def test_deploy_exits_0_early_when_already_up_to_date(monkeypatch, capsys):
    monkeypatch.setattr(deploy, "git_state", lambda: {
        "head": "current1", "branch": "v2", "dirty": False, "origin": "current1"})
    monkeypatch.setattr(deploy, "health", lambda: {
        "status": "ok", "db": True, "running_commit": "current1",
        "repo_commit": "current1", "stale": False, "schema_version": 4})
    monkeypatch.setattr(sys, "argv", ["deploy.py"])

    assert deploy.main() == 0
    assert "Already up to date" in capsys.readouterr().out


def test_deploy_lease_mutual_exclusion_and_lifecycle(tmp_path, monkeypatch):
    """Proves acquisition inserts real schema rows, blocks second acquire, and releases cleanly."""
    db_file = tmp_path / "cerebro.db"
    con = sqlite3.connect(db_file)
    con.execute(
        "CREATE TABLE leases ("
        "  resource TEXT PRIMARY KEY, holder_id TEXT NOT NULL, holder_kind TEXT NOT NULL, "
        "  channel_id TEXT, reason TEXT, acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL"
        ")"
    )
    con.commit()
    con.close()

    _point_settings_at(monkeypatch, db_file, tmp_path)

    # 1. First acquisition succeeds
    assert deploy.acquire_deploy_lease("agent1", ttl=60) is True

    # 2. Verify row exists with correct columns
    con = sqlite3.connect(db_file)
    row = con.execute("SELECT * FROM leases WHERE resource = ?", (deploy.DEPLOY_RESOURCE,)).fetchone()
    con.close()
    assert row is not None
    assert row[0] == deploy.DEPLOY_RESOURCE
    assert row[1] == "agent1"
    assert row[2] == "cli"

    # 3. Second acquisition while active is refused
    assert deploy.acquire_deploy_lease("agent2", ttl=60) is False

    # 4. Release removes the lease
    deploy.release_deploy_lease("agent1")
    con = sqlite3.connect(db_file)
    row = con.execute("SELECT * FROM leases WHERE resource = ?", (deploy.DEPLOY_RESOURCE,)).fetchone()
    con.close()
    assert row is None

    # 5. Acquisition succeeds again after release
    assert deploy.acquire_deploy_lease("agent2", ttl=60) is True
    deploy.release_deploy_lease("agent2")


def test_deploy_refuses_when_deploy_lease_is_held(tmp_path, monkeypatch, capsys):
    db_file = tmp_path / "cerebro.db"
    con = sqlite3.connect(db_file)
    con.execute(
        "CREATE TABLE leases ("
        "  resource TEXT PRIMARY KEY, holder_id TEXT NOT NULL, holder_kind TEXT NOT NULL, "
        "  channel_id TEXT, reason TEXT, acquired_at TEXT NOT NULL, expires_at TEXT NOT NULL"
        ")"
    )
    con.execute(
        "INSERT INTO leases VALUES "
        "('service:cerebro:deploy', 'other_agent', 'cli', NULL, 'deploying', "
        "'2026-08-14T00:00:00Z', '2099-01-01T00:00:00Z')"
    )
    con.commit()
    con.close()

    _point_settings_at(monkeypatch, db_file, tmp_path)
    monkeypatch.setattr(deploy, "git_state", lambda: {
        "head": "abc1234", "branch": "v2", "dirty": False, "origin": "abc1234"})
    monkeypatch.setattr(deploy, "health", lambda: None)
    monkeypatch.setattr(sys, "argv", ["deploy.py"])

    assert deploy.main() == 2
    assert "deployment lease 'service:cerebro:deploy' is held" in capsys.readouterr().err


def test_deploy_fails_closed_when_lease_registry_corrupt(tmp_path, monkeypatch, capsys):
    """If the lease table cannot be queried, deploy fails closed rather than proceeding silently."""
    db_file = tmp_path / "cerebro.db"
    db_file.write_bytes(b"corrupt-database-bytes")

    _point_settings_at(monkeypatch, db_file, tmp_path)
    monkeypatch.setattr(deploy, "git_state", lambda: {
        "head": "abc1234", "branch": "v2", "dirty": False, "origin": "abc1234"})
    monkeypatch.setattr(deploy, "health", lambda: None)
    monkeypatch.setattr(sys, "argv", ["deploy.py"])

    assert deploy.main() == 2
    assert "cannot reach lease registry" in capsys.readouterr().err
