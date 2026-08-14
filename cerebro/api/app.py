import mimetypes
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from cerebro import db, agents_loader
from cerebro.auth import (
    SessionStore,
    TokenStore,
    get_session_store,
)
from cerebro.api import leases, routes_agents, routes_channels, routes_usage, ws
from cerebro.config import settings
from cerebro.hub import Hub
from cerebro.service import RuntimeService
from version import __version__

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown lifecycle."""
    settings.ensure_dirs()
    await db.connect()
    await db.migrate()
    _app.state.hub = Hub()
    _app.state.token_store = TokenStore(settings.data_dir / ".secrets.env")
    _app.state.session_store = SessionStore(settings.data_dir / ".session.token")
    _app.state.session_store.issue()
    await agents_loader.bootstrap_seed_data()
    _app.state.runtime = RuntimeService(_app.state.hub)
    await _app.state.runtime.start()
    yield
    if hasattr(_app.state, "runtime") and _app.state.runtime:
        await _app.state.runtime.stop()
    if hasattr(_app.state, "hub") and _app.state.hub:
        await _app.state.hub.aclose()
    await db.close()


app = FastAPI(
    title="Cerebro v2 API",
    version=__version__,
    lifespan=lifespan,
)

# Include API and WebSocket Routers
app.include_router(routes_agents.router)
app.include_router(routes_channels.router)
app.include_router(leases.router)
app.include_router(routes_usage.router)
app.include_router(ws.router)

# Mount Web Assets if directory exists
if WEB_DIR.exists():
    mimetypes.add_type("text/javascript", ".mjs")
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


# -- what this process is actually running -----------------------------------------
#
# Captured once, at import, and never refreshed. That is the entire point: reading git live would
# report whatever HEAD says *now*, which is precisely the value that hides the problem. On
# 2026-08-14 three fixes sat landed-but-not-running for half an hour while the war room read as
# though they had shipped, and it took a human noticing to find out. A process can only honestly
# report the code it loaded.

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _git_commit() -> str | None:
    """Short HEAD, or None when git is unavailable. Never raises: health must not depend on git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() or None
    except Exception:  # noqa: BLE001 - a missing git must not break the health endpoint
        return None


RUNNING_COMMIT = _git_commit()
STARTED_AT = datetime.now(timezone.utc).isoformat()


@app.get("/api/health")
async def health_check() -> dict[str, object]:
    """Health, and honestly whether this process is running the code that is on disk.

    `db` used to be the literal True. A health check that reports a dependency it never contacted
    is the same failure this endpoint now exists to expose, so it is queried.
    """
    db_ok = True
    schema_version = None
    try:
        row = await db.fetch_one("SELECT MAX(version) AS v FROM schema_version")
        schema_version = row["v"] if row else None
    except Exception:  # noqa: BLE001 - report the failure, do not become one
        db_ok = False

    repo_commit = _git_commit()
    stale = bool(RUNNING_COMMIT and repo_commit and RUNNING_COMMIT != repo_commit)

    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "version": __version__,
        "running_commit": RUNNING_COMMIT,
        "repo_commit": repo_commit,
        "stale": stale,
        "schema_version": schema_version,
        "started_at": STARTED_AT,
    }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the Cerebro v2 web single page app and issue loopback session cookie."""
    session_store = getattr(request.app.state, "session_store", None) or get_session_store()
    token = session_store.issue()

    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        response: HTMLResponse = FileResponse(str(index_file))
    else:
        response = HTMLResponse(
            "<!DOCTYPE html>"
            "<html>"
            "<head><title>Cerebro v2</title></head>"
            "<body>"
            "<h1>Cerebro v2</h1>"
            "<p>Agentic headquarters skeleton running.</p>"
            "</body>"
            "</html>"
        )

    # Issue session cookie on loopback / test hosts
    client_ip = getattr(request.client, "host", "") if request.client else ""
    if client_ip in ("127.0.0.1", "::1", "localhost", "testclient", "test", ""):
        response.set_cookie(
            key="cerebro_session",
            value=token,
            httponly=True,
            samesite="lax",
            path="/",
        )
    return response
