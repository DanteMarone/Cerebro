"""Tests for Cerebro v2 FastAPI application endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
from cerebro.api.app import app
from version import __version__


@pytest.mark.asyncio
async def test_health_check_endpoint():
    """Verify /api/health returns status ok, db True, and version."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["db"] is True
        assert data["version"] == __version__


@pytest.mark.asyncio
async def test_index_placeholder():
    """Verify root / returns HTML placeholder page."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "<title>Cerebro v2</title>" in response.text
