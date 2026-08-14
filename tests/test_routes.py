"""Tests for REST API routes (/api/agents and /api/channels)."""

import pytest
from httpx import AsyncClient, ASGITransport
from cerebro import agents_loader
from cerebro.api.app import app
from cerebro.config import Settings
from cerebro.hub import Hub


@pytest.mark.asyncio
async def test_routes_agents_and_channels(test_db: Settings):
    """Test channel listing, message creation, and agent lookup."""
    app.state.hub = Hub()
    await agents_loader.bootstrap_seed_data()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Check agents endpoint
        res = await client.get("/api/agents")
        assert res.status_code == 200
        agents = res.json()["agents"]
        assert any(a["id"] == "jarvis" for a in agents)

        # Check single agent endpoint
        res = await client.get("/api/agents/jarvis")
        assert res.status_code == 200
        assert res.json()["id"] == "jarvis"

        # Check channels endpoint
        res = await client.get("/api/channels")
        assert res.status_code == 200
        channels = res.json()["channels"]
        assert any(c["id"] == "dm-dante-jarvis" for c in channels)

        # Post a message to dm-dante-jarvis
        res = await client.post(
            "/api/channels/dm-dante-jarvis/messages",
            json={"content": "Hello from pytest", "author_id": "dante"},
        )
        assert res.status_code == 200
        msg = res.json()
        assert msg["content"] == "Hello from pytest"
        assert msg["author_id"] == "dante"

        # Fetch messages
        res = await client.get("/api/channels/dm-dante-jarvis/messages")
        assert res.status_code == 200
        messages = res.json()["messages"]
        assert len(messages) >= 1
        assert any(m["content"] == "Hello from pytest" for m in messages)
