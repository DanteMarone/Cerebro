import mimetypes
from pathlib import Path
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from cerebro import db, agents_loader
from cerebro.auth import Principal, TokenStore, parse_bearer, principal_for
from cerebro.api import routes_agents, routes_channels, ws
from cerebro.config import settings
from cerebro.hub import Hub
from cerebro.service import RuntimeService
from version import __version__

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def get_token_store() -> TokenStore:
    return TokenStore(settings.data_dir / ".secrets.env")


async def get_current_principal(
    authorization: str | None = Header(default=None),
) -> Principal:
    """Resolve who is speaking, per §6.2 and §6.3.

    No Authorization header is the local human — we bind to 127.0.0.1 and there is one person
    here. A bearer token is an agent speaking as itself. An unrecognised token is a 401 and never
    a quiet downgrade to Dante's identity: that would turn a typo into an impersonation.
    """
    try:
        return principal_for(parse_bearer(authorization), get_token_store())
    except PermissionError:
        raise HTTPException(status_code=401, detail="unrecognised agent token")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown lifecycle."""
    settings.ensure_dirs()
    await db.connect()
    await db.migrate()
    _app.state.hub = Hub()
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
app.include_router(ws.router)

# Mount Web Assets if directory exists
if WEB_DIR.exists():
    # Python resolves static MIME types from the Windows registry, where .mjs is commonly
    # text/plain. Browsers enforce strict MIME checking on ES modules, so the vendored
    # preact.mjs and htm.mjs are rejected and the entire UI renders blank -- with a green test
    # suite, because no test exercises a browser. Register the types explicitly rather than
    # trusting the host machine's registry.
    mimetypes.add_type("text/javascript", ".mjs")
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/api/health")
async def health_check(_principal: Principal = Depends(get_current_principal)) -> dict[str, object]:
    """Health check endpoint confirming API, DB, and version."""
    return {
        "status": "ok",
        "db": True,
        "version": __version__,
    }


@app.get("/", response_class=HTMLResponse)
async def index(_principal: Principal = Depends(get_current_principal)):
    """Serve the Cerebro v2 web single page app or fallback placeholder."""
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return (
        "<!DOCTYPE html>"
        "<html>"
        "<head><title>Cerebro v2</title></head>"
        "<body>"
        "<h1>Cerebro v2</h1>"
        "<p>Agentic headquarters skeleton running.</p>"
        "</body>"
        "</html>"
    )
