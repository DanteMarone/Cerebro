"""Tests for channels and membership API routes."""

import pytest
from httpx import AsyncClient, ASGITransport
from cerebro.api.app import app
from cerebro.config import Settings
from cerebro.hub import Hub


@pytest.mark.asyncio
async def test_create_channel_unconditionally_adds_dante(test_db: Settings):
    """Test POST /api/channels creates channel and automatically enrolls Dante."""
    app.state.hub = Hub()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/channels",
            json={
                "name": "General Chat",
                "topic": "Company-wide discussions",
                "kind": "topic",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["channel"]["id"] == "general-chat"
        assert data["channel"]["name"] == "General Chat"
        assert data["channel"]["created_by"] == "dante"

        # Verify Dante is a member
        members = data["members"]
        assert any(m["member_id"] == "dante" and m["member_kind"] == "user" for m in members)


@pytest.mark.asyncio
async def test_create_channel_with_initial_members(test_db: Settings):
    """Test POST /api/channels with initial agent members."""
    app.state.hub = Hub()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/channels",
            json={
                "name": "Dev War Room",
                "id": "dev-warroom",
                "topic": "Active feature development",
                "kind": "war_room",
                "member_ids": ["jarvis", "claude", "codex"],
            },
        )
        assert res.status_code == 201
        data = res.json()
        members = {m["member_id"] for m in data["members"]}
        assert {"dante", "jarvis", "claude", "codex"}.issubset(members)


@pytest.mark.asyncio
async def test_create_channel_duplicate_returns_409(test_db: Settings):
    """Test POST /api/channels returns 409 for duplicate channel ID."""
    app.state.hub = Hub()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res1 = await client.post("/api/channels", json={"name": "Dup Channel", "id": "dup-chan"})
        assert res1.status_code == 201

        res2 = await client.post("/api/channels", json={"name": "Dup Channel", "id": "dup-chan"})
        assert res2.status_code == 409
        assert "already exists" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_add_and_remove_channel_members(test_db: Settings):
    """Test adding an agent member and removing them, asserting Dante cannot be removed."""
    app.state.hub = Hub()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create channel
        await client.post("/api/channels", json={"name": "Projects", "id": "projects"})

        # Add member
        add_res = await client.post(
            "/api/channels/projects/members",
            json={"member_id": "antigravity", "member_kind": "agent", "listen_mode": "auto"},
        )
        assert add_res.status_code == 201
        members = add_res.json()["members"]
        assert any(m["member_id"] == "antigravity" for m in members)

        # Attempt to remove Dante -> must return 400
        del_dante = await client.delete("/api/channels/projects/members/dante")
        assert del_dante.status_code == 400
        assert "Cannot remove owner 'dante'" in del_dante.json()["detail"]

        # Remove agent -> succeeds
        del_agent = await client.delete("/api/channels/projects/members/antigravity")
        assert del_agent.status_code == 200
        remaining = {m["member_id"] for m in del_agent.json()["members"]}
        assert "antigravity" not in remaining
        assert "dante" in remaining
