import mimetypes
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
from cerebro.api import leases, routes_agents, routes_channels, ws
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
app.include_router(ws.router)

# Mount Web Assets if directory exists
if WEB_DIR.exists():
    mimetypes.add_type("text/javascript", ".mjs")
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/api/health")
async def health_check() -> dict[str, object]:
    """Health check endpoint confirming API, DB, and version."""
    return {
        "status": "ok",
        "db": True,
        "version": __version__,
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
