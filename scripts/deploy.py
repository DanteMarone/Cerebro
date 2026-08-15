"""Deploy Cerebro: back up, verify, restart, prove it came back.

Exists because "landed" and "running" were the same word in the war room and are not the same
thing. On 2026-08-14 three fixes sat in git for half an hour while the live service ran older code,
the app looked completely healthy, and the only symptom was already-fixed bugs reappearing. A human
found it by accident.

There are no judgement calls in here. That is the point: the previous restart was improvised, and
what got improvised was `taskkill /F` against whatever happened to own the port.

Safety properties, in the order they matter:

- **It refuses to deploy an unclean tree.** What restarts must be what is committed, or the running
  commit it reports afterwards is a lie.
- **It backs up first, with SQLite's own backup API** -- not a file copy. The database is in WAL
  mode, so `cp cerebro.db` captures a fraction of the data (once: 0 messages out of 363), and
  copying db/wal/shm under load is a torn snapshot. `Connection.backup()` is online-safe.
  The `sqlite3` CLI is not installed on this machine, so `VACUUM INTO` is not an option here.
- **It verifies the backup before touching the service.** Message count must match. If the backup
  is wrong, nothing is restarted.
- **It only stops a process it has identified as ours.** Owning the port is not proof of identity.

Usage:

    python scripts/deploy.py              # backup, verify, restart, health-check
    python scripts/deploy.py --check      # report only, change nothing
    python scripts/deploy.py --no-restart # backup and verify, leave the service alone
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cerebro.config import settings  # noqa: E402

PORT = 8765
BASE_URL = f"http://127.0.0.1:{PORT}"
HEALTH_TIMEOUT_S = 60
DEPLOY_RESOURCE = "service:cerebro:deploy"


def acquire_deploy_lease(holder: str = "deploy.py", ttl: int = 120) -> bool:
    """Acquire the deployment mutex across the SQLite WAL lease registry (§8.7). Fail closed."""
    db_file = Path(settings.db_path)
    if not db_file.exists():
        return True
    try:
        conn = sqlite3.connect(str(db_file), timeout=5.0)
        try:
            conn.execute("BEGIN IMMEDIATE;")
            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat()
            conn.execute("DELETE FROM leases WHERE expires_at <= ?;", (now,))
            cur = conn.execute(
                "SELECT holder_id, expires_at, reason FROM leases WHERE resource = ?;",
                (DEPLOY_RESOURCE,),
            )
            row = cur.fetchone()
            if row:
                conn.rollback()
                return False
            expires = (now_dt + timedelta(seconds=ttl)).isoformat()
            conn.execute(
                "INSERT INTO leases ("
                "  resource, holder_id, holder_kind, channel_id, reason, acquired_at, expires_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?);",
                (DEPLOY_RESOURCE, holder, "cli", None, "deploying update", now, expires),
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as exc:
        raise DeployRefused(
            f"cannot reach lease registry to acquire deployment mutex: {exc}"
        ) from exc


def release_deploy_lease(holder: str = "deploy.py") -> None:
    """Release the deployment mutex."""
    db_file = Path(settings.db_path)
    if not db_file.exists():
        return
    try:
        conn = sqlite3.connect(str(db_file), timeout=5.0)
        try:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                "DELETE FROM leases WHERE resource = ? AND holder_id = ?;",
                (DEPLOY_RESOURCE, holder),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


class DeployRefused(Exception):
    """A precondition failed. Nothing has been changed."""


def _run(args, **kwargs):
    return subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True, **kwargs)


def git_state() -> dict:
    head = _run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    dirty = bool(_run(["git", "status", "--porcelain"]).stdout.strip())
    remote = _run(["git", "ls-remote", "--heads", "origin", branch]).stdout.split()
    return {
        "head": head,
        "branch": branch,
        "dirty": dirty,
        "origin": (remote[0][:7] if remote else None),
    }


def health() -> dict | None:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=10) as response:
            return json.loads(response.read())
    except Exception:  # noqa: BLE001 - "not running" is an answer, not a failure
        return None


def backup() -> Path:
    """Online, consistent snapshot via SQLite's backup API, verified by message count."""
    source = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True)
    live_count = source.execute("SELECT COUNT(*) FROM messages").fetchone()[0]

    dest_dir = settings.data_dir / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"cerebro_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.db"

    target = sqlite3.connect(dest_path)
    with target:
        source.backup(target)
    target.close()
    source.close()

    check = sqlite3.connect(f"file:{dest_path}?mode=ro", uri=True)
    integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    copied = check.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    check.close()

    if integrity != "ok":
        raise DeployRefused(f"backup failed integrity_check: {integrity}")
    if copied != live_count:
        raise DeployRefused(
            f"backup has {copied} messages, live has {live_count}. Refusing to restart."
        )

    print(f"  backup    {dest_path.name}  {copied} messages, integrity ok")
    return dest_path


def owning_pids() -> list[int]:
    out = _run(["netstat", "-ano", "-p", "TCP"]).stdout
    pids = []
    for line in out.splitlines():
        if f"127.0.0.1:{PORT}" in line and "LISTENING" in line:
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.append(int(parts[-1]))
    return sorted(set(pids))


def command_line(pid: int) -> str:
    result = _run([
        "powershell", "-NoProfile", "-NonInteractive", "-Command",
        f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine",
    ])
    return (result.stdout or "").strip()


def stop_service() -> None:
    """Stop the process on our port, but only after confirming it is ours.

    Owning a port is not identity. The previous hand-rolled restart force-killed whatever was
    listening, which would have taken an unrelated process with it.
    """
    for pid in owning_pids():
        cmdline = command_line(pid)
        is_cerebro = (
            "cerebro" in cmdline.lower()
            or str(REPO_ROOT).lower() in cmdline.lower()
            or "main.py" in cmdline.lower()
        )
        if not is_cerebro:
            raise DeployRefused(
                f"PID {pid} owns port {PORT} but does not look like Cerebro:\n"
                f"    {cmdline or '<command line unavailable>'}\n"
                "Refusing to stop a process I cannot identify. Stop it yourself, or free the port."
            )
        print(f"  stopping  PID {pid}")
        _run(["taskkill", "/PID", str(pid), "/T"])
        for _ in range(20):
            if pid not in owning_pids():
                break
            time.sleep(0.5)
        else:
            print(f"  escalating to force for PID {pid} (did not exit in 10s)")
            _run(["taskkill", "/PID", str(pid), "/F"])


def start_service() -> None:
    python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    subprocess.Popen(
        [str(python), "main.py"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
    )
    print("  starting  main.py")


def wait_for_health() -> dict:
    deadline = time.time() + HEALTH_TIMEOUT_S
    while time.time() < deadline:
        got = health()
        if got:
            return got
        time.sleep(1)
    raise DeployRefused(
        f"the service did not answer /api/health within {HEALTH_TIMEOUT_S}s. "
        "It has been stopped and may not have restarted -- check manually."
    )


def report(label: str, state: dict | None) -> None:
    if not state:
        print(f"  {label:<9} not running")
        return
    print(
        f"  {label:<9} commit {state.get('running_commit')}  schema {state.get('schema_version')}"
        f"  db {state.get('db')}  stale {state.get('stale')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report only, change nothing")
    parser.add_argument("--force", action="store_true",
                        help="deploy even if the service is already running the current repo HEAD")
    parser.add_argument("--no-restart", action="store_true", help="back up and verify only")
    parser.add_argument("--allow-dirty", action="store_true",
                        help="deploy with uncommitted changes (what runs will not be what is committed)")
    args = parser.parse_args()

    git = git_state()
    before = health()

    print("cerebro deploy")
    print(f"  repo      {git['branch']} at {git['head']}"
          f"{' (DIRTY)' if git['dirty'] else ''}  origin {git['origin']}")
    report("before", before)

    if args.check:
        if not before:
            print("\n  not running")
            return 1
        if before.get("running_commit") is None:
            print(
                "\n  CANNOT DETERMINE: this server does not report its running commit, so it "
                "predates\n  the version-visibility change -- which means it is stale by "
                "definition. Deploy."
            )
            return 1
        if before.get("stale"):
            print("\n  STALE: the running process is older than the working tree.")
            return 1
        print("\n  up to date")
        return 0

    # If running commit already matches and is not stale, exit 0 early unless --force
    if not args.force and not args.no_restart and before and not before.get("stale"):
        if before.get("running_commit") == git["head"]:
            print("\n  Already up to date (running commit matches repo HEAD). Use --force to redeploy.")
            return 0

    holder = f"deploy.py:{git['head']}"
    lease_acquired = False
    try:
        if git["dirty"] and not args.allow_dirty:
            raise DeployRefused(
                "the working tree is dirty. What restarts would not be what is committed, and the "
                "commit this server reports afterwards would be a lie. Commit, stash, or pass "
                "--allow-dirty."
            )
        if git["origin"] and not git["origin"].startswith(git["head"][:7]) \
                and not git["head"].startswith(git["origin"][:7]):
            print(f"  note      HEAD {git['head']} differs from origin {git['origin']}")

        if not acquire_deploy_lease(holder):
            raise DeployRefused(
                "deployment lease 'service:cerebro:deploy' is held by another process. "
                "Wait or release it before deploying."
            )
        lease_acquired = True

        backup()
        if args.no_restart:
            print("\n  backup verified; service left alone (--no-restart)")
            return 0

        stop_service()
        start_service()
        after = wait_for_health()
        report("after", after)

        if after.get("stale"):
            print("\n  WARNING: the service reports itself stale after restart.")
            return 1
        print("\n  deployed")
        return 0

    except DeployRefused as exc:
        print(f"\n  REFUSED: {exc}", file=sys.stderr)
        return 2
    finally:
        if lease_acquired:
            release_deploy_lease(holder)


if __name__ == "__main__":
    raise SystemExit(main())
