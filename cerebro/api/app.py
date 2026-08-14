"""FastAPI application for Cerebro v2."""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse

from cerebro import db
from cerebro.config import settings
from version import __version__


@dataclass(frozen=True)
class Principal:
    """Local user identity. Serves as authentication seam for future multi-user / Tailscale."""
    id: str = "user_local"
    name: str = "Dante"
    role: str = "owner"


async def get_current_principal() -> Principal:
    """Dependency returning the active principal."""
    return Principal()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown lifecycle."""
    settings.ensure_dirs()
    await db.connect()
    await db.migrate()
    yield
    await db.close()


app = FastAPI(
    title="Cerebro v2 API",
    version=__version__,
    lifespan=lifespan,
)


@app.get("/api/health")
async def health_check(_principal: Principal = Depends(get_current_principal)) -> dict[str, object]:
    """Health check endpoint confirming API, DB, and version."""
    return {
        "status": "ok",
        "db": True,
        "version": __version__,
    }


@app.get("/", response_class=HTMLResponse)
async def index(_principal: Principal = Depends(get_current_principal)) -> str:
    """Root placeholder page."""
    return (
        "<!DOCTYPE html>"
        "<html>"
        "<head><title>Cerebro v2</title></head>"
        "<body>"
        "<h1>Cerebro v2</h1>"
        "<p>Agentic headquarters skeleton running. Ready for Slice 1.</p>"
        "</body>"
        "</html>"
    )
