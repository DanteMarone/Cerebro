"""Tests for the lease commit guard and the path-check endpoint it depends on (§8.7).

The guard exists because three lease violations on 2026-08-14 were all found by review after the
fact rather than at the moment of the mistake. Two of them were mine. So the cases that matter here
are the ones that would have caught them: a file nobody declared, and a file inside somebody else's
declared set.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from cerebro import store
from cerebro.api.app import app
from cerebro.api.leases import _covers
from cerebro.auth import TokenStore
from cerebro.config import Settings
from cerebro.hub import Hub

REPO_ROOT = Path(__file__).resolve().parent.parent


def _headers(settings: Settings, agent_id: str) -> dict[str, str]:
    token = TokenStore(settings.data_dir / ".secrets.env").issue(agent_id)
    return {"Authorization": f"Bearer {token}"}


# -- coverage rules ---------------------------------------------------------------


@pytest.mark.parametrize(
    "resource,path,covered",
    [
        ("file:cerebro/usage.py", "cerebro/usage.py", True),
        ("file:cerebro/", "cerebro/usage.py", True),
        ("file:cerebro", "cerebro/usage.py", True),
        # A directory lease covers descendants; a shared prefix is not a descendant.
        ("file:cerebro/us", "cerebro/usage.py", False),
        ("file:cerebro/usage.py", "cerebro/usage_other.py", False),
        # Only file: leases govern file contents. Holding HEAD is permission to move the
        # branch, not to edit anything in it.
        ("repo:Cerebro:HEAD", "cerebro/usage.py", False),
        ("port:8765", "cerebro/usage.py", False),
        # Windows paths arrive with backslashes from some git plumbing.
        ("file:cerebro/usage.py", "cerebro\\usage.py", True),
    ],
)
def test_lease_coverage_rules(resource, path, covered):
    assert _covers(resource, path) is covered


# -- the check endpoint -----------------------------------------------------------


@pytest.mark.asyncio
async def test_check_reports_a_path_the_caller_holds(test_db: Settings):
    app.state.hub = Hub()
    await store.acquire_lease("file:cerebro/usage.py", "claude")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/api/leases/check",
            params={"path": "cerebro/usage.py"},
            headers=_headers(test_db, "claude"),
        )

    body = res.json()
    assert res.status_code == 200
    assert body["all_held"] is True
    assert body["results"][0]["matched_resource"] == "file:cerebro/usage.py"


@pytest.mark.asyncio
async def test_check_blocks_a_path_nobody_declared(test_db: Settings):
    """The 9c4bd33 case: edited and committed with no lease at all."""
    app.state.hub = Hub()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/api/leases/check",
            params={"path": "cerebro/service.py"},
            headers=_headers(test_db, "claude"),
        )

    body = res.json()
    assert body["all_held"] is False
    assert body["results"][0]["held_by"] is None, "nobody holds it; it was simply never declared"


@pytest.mark.asyncio
async def test_check_names_the_other_holder(test_db: Settings):
    """A useful refusal says who to talk to, not merely that you are refused."""
    app.state.hub = Hub()
    await store.acquire_lease("file:cerebro/db.py", "antigravity")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/api/leases/check",
            params={"path": "cerebro/db.py"},
            headers=_headers(test_db, "claude"),
        )

    entry = res.json()["results"][0]
    assert entry["held"] is False
    assert entry["held_by"] == "antigravity"


@pytest.mark.asyncio
async def test_a_directory_lease_covers_files_beneath_it(test_db: Settings):
    app.state.hub = Hub()
    await store.acquire_lease("file:cerebro/providers", "claude")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/api/leases/check",
            params={"path": "cerebro/providers/fake.py"},
            headers=_headers(test_db, "claude"),
        )

    assert res.json()["all_held"] is True


@pytest.mark.asyncio
async def test_identity_comes_from_the_principal_not_the_query(test_db: Settings):
    """Otherwise the guard could be told whose leases to consult, which defeats the point."""
    app.state.hub = Hub()
    await store.acquire_lease("file:cerebro/usage.py", "antigravity")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/api/leases/check",
            params={"path": "cerebro/usage.py", "principal": "antigravity", "agent": "antigravity"},
            headers=_headers(test_db, "claude"),
        )

    body = res.json()
    assert body["principal"] == "claude"
    assert body["all_held"] is False, "claude must not inherit antigravity's lease by asking nicely"


@pytest.mark.asyncio
async def test_the_check_refuses_anonymous_callers(test_db: Settings):
    app.state.hub = Hub()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/api/leases/check",
            params={"path": "cerebro/usage.py"},
            headers={"Authorization": "Bearer nope"},
        )
    assert res.status_code in (401, 403)


# -- the guard itself -------------------------------------------------------------


def _run_guard(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "lease_guard.py"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_guard_fails_closed_when_the_api_is_unreachable():
    """A guard that fails open is decoration.

    The moment it is most likely to be unreachable is a messy session -- exactly when the
    coordination it protects matters most.
    """
    result = _run_guard(
        "--paths", "cerebro/usage.py", "--base-url", "http://127.0.0.1:9", "--agent", "claude"
    )
    assert result.returncode != 0
    assert "CANNOT VERIFY" in result.stderr
    assert "refusing the commit" in result.stderr


def test_the_guard_fails_closed_without_an_identity(monkeypatch):
    """It must not fall back to "some agent" and check the wrong principal's leases."""
    env = {k: v for k, v in __import__("os").environ.items() if k != "CEREBRO_AGENT"}
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "lease_guard.py"),
         "--paths", "cerebro/usage.py", "--agent", "definitely-not-a-real-agent"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, env=env,
    )
    assert result.returncode != 0
    assert "CANNOT VERIFY" in result.stderr


def test_the_guard_passes_when_nothing_is_staged():
    """An empty commit has nothing to check and must not be blocked."""
    result = _run_guard("--paths")
    assert result.returncode == 0


def test_the_hook_is_executable_and_advisory():
    """The hook must say what it is. An advisory guard sold as enforcement is worse than none."""
    hook = (REPO_ROOT / ".githooks" / "pre-commit").read_text(encoding="utf-8")
    assert "Advisory only" in hook
    assert "--no-verify" in hook
    assert "scripts/lease_guard.py" in hook
