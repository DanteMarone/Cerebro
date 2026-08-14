"""Tests for channels and membership API routes."""

import pytest
from httpx import AsyncClient, ASGITransport
from cerebro.api.app import app
from cerebro.auth import TokenStore
from cerebro.config import Settings
from cerebro.hub import Hub
from cerebro import store


@pytest.mark.asyncio
async def test_create_channel_unconditionally_adds_dante(test_db: Settings):
    """Test POST /api/channels creates channel and automatically enrolls Dante."""
    app.state.hub = Hub()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Obtain loopback session
        await client.get("/")

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
async def test_create_channel_anonymous_refused_with_401(test_db: Settings):
    """Test POST /api/channels without credentials returns 401."""
    app.state.hub = Hub()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/channels",
            json={"name": "Anon Chan", "id": "anon-chan"},
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_create_channel_by_agent_refused_with_403(test_db: Settings):
    """Test POST /api/channels by an agent principal returns 403."""
    app.state.hub = Hub()
    token_store = TokenStore(test_db.data_dir / ".secrets.env")
    token = token_store.issue("claude")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/channels",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "Agent Chan", "id": "agent-chan"},
        )
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_create_channel_with_initial_members(test_db: Settings):
    """Test POST /api/channels with initial agent members."""
    app.state.hub = Hub()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.get("/")
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
        await client.get("/")
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
        await client.get("/")
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


@pytest.mark.asyncio
async def test_agent_message_post_requires_membership(test_db: Settings):
    """Test that an agent can only post messages to channels where it is enrolled."""
    app.state.hub = Hub()
    token_store = TokenStore(test_db.data_dir / ".secrets.env")
    token = token_store.issue("claude")

    await store.create_channel(
        channel_id="private-club",
        name="Private Club",
        team_id="personal-assistant",
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Attempt to post as Claude when not enrolled -> 403 Forbidden
        res = await client.post(
            "/api/channels/private-club/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "Trying to break in"},
        )
        assert res.status_code == 403
        assert "not a member" in res.json()["detail"]

        # Add Claude as member
        await store.add_channel_member(
            channel_id="private-club",
            member_id="claude",
            member_kind="agent",
        )

        # Post again -> succeeds
        res = await client.post(
            "/api/channels/private-club/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "Hello private club!"},
        )
        assert res.status_code == 200
        msg = res.json()
        assert msg["author_id"] == "claude"
        assert msg["author_kind"] == "agent"
