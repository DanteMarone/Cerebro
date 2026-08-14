"""Cross-layer proofs for the Slice 2 identity and channel invariants."""

import pytest
from httpx import ASGITransport, AsyncClient

from cerebro.api.app import app
from cerebro.auth import SessionStore, TokenStore
from cerebro.config import Settings
from cerebro.hub import Hub


def _member_ids(payload: dict) -> set[str]:
    """Return member ids from a channel API response."""
    return {member["member_id"] for member in payload["members"]}


@pytest.mark.asyncio
async def test_channel_api_keeps_dante_in_every_room(test_db: Settings):
    """Omitting Dante at creation and requesting removal must both leave him enrolled."""
    app.state.hub = Hub()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/channels",
            json={
                "id": "part-c-owner-proof",
                "name": "Part C owner proof",
                "kind": "war_room",
                "member_ids": ["codex"],
            },
        )
        assert created.status_code == 201
        assert _member_ids(created.json()) == {"codex", "dante"}

        removed = await client.delete(
            "/api/channels/part-c-owner-proof/members/dante"
        )
        assert removed.status_code == 400

        roster = await client.get("/api/channels/part-c-owner-proof/members")
        assert roster.status_code == 200
        assert "dante" in _member_ids(roster.json())


@pytest.mark.asyncio
async def test_agent_message_authorship_is_assigned_and_visible_to_dante(
    test_db: Settings,
):
    """Caller identity wins, while recipient-like extras cannot hide history from Dante."""
    app.state.hub = Hub()
    token_store = TokenStore(test_db.data_dir / ".secrets.env")
    app.state.token_store = token_store
    token = token_store.issue("codex")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/channels",
            json={
                "id": "part-c-attribution-proof",
                "name": "Part C attribution proof",
                "member_ids": ["codex"],
            },
        )
        assert created.status_code == 201

        posted = await client.post(
            "/api/channels/part-c-attribution-proof/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "content": "Codex owns this sentence",
                "author_id": "dante",
                "recipient": "claude",
                "metadata": {"visible_to": ["claude"]},
            },
        )
        assert posted.status_code == 200
        assert posted.json()["author_id"] == "codex"
        assert posted.json()["author_kind"] == "agent"

        history = await client.get(
            "/api/channels/part-c-attribution-proof/messages"
        )
        assert history.status_code == 200
        assert [message["body"] for message in history.json()["messages"]] == [
            "Codex owns this sentence"
        ]


@pytest.mark.asyncio
async def test_revoked_and_malformed_credentials_never_become_dante(
    test_db: Settings,
):
    """Revoked, malformed, and wrong-scheme credentials must all fail closed with 401."""
    app.state.hub = Hub()
    token_store = TokenStore(test_db.data_dir / ".secrets.env")
    app.state.token_store = token_store
    token = token_store.issue("codex")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/channels",
            json={
                "id": "part-c-revocation-proof",
                "name": "Part C revocation proof",
                "member_ids": ["codex"],
            },
        )
        assert created.status_code == 201
        assert token_store.revoke("codex") is True

        attempts = [
            {"Authorization": f"Bearer {token}"},
            {"Authorization": "Bearer"},
            {"Authorization": "Basic not-a-bearer"},
        ]
        for headers in attempts:
            response = await client.post(
                "/api/channels/part-c-revocation-proof/messages",
                headers=headers,
                json={"content": "must not be persisted", "author_id": "dante"},
            )
            assert response.status_code == 401

        history = await client.get(
            "/api/channels/part-c-revocation-proof/messages"
        )
        assert history.status_code == 200
        assert history.json()["messages"] == []


@pytest.mark.asyncio
async def test_human_message_requires_a_positive_valid_session(test_db: Settings):
    """No credentials and an invalid cookie fail; only a server-issued session is Dante."""
    app.state.hub = Hub()
    app.state.session_store = SessionStore(test_db.data_dir / ".session.token")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/api/channels",
            json={
                "id": "part-c-session-proof",
                "name": "Part C session proof",
            },
        )
        assert created.status_code == 201

        anonymous = await client.post(
            "/api/channels/part-c-session-proof/messages",
            json={"content": "anonymous must fail", "author_id": "dante"},
        )
        assert anonymous.status_code == 401

        client.cookies.set("cerebro_session", "invalid-session")
        invalid = await client.post(
            "/api/channels/part-c-session-proof/messages",
            json={"content": "invalid must fail", "author_id": "dante"},
        )
        assert invalid.status_code == 401

        opened = await client.get("/")
        assert opened.status_code == 200
        assert opened.cookies.get("cerebro_session")

        posted = await client.post(
            "/api/channels/part-c-session-proof/messages",
            json={"content": "Dante typed this", "author_id": "codex"},
        )
        assert posted.status_code == 200
        assert posted.json()["author_id"] == "dante"
        assert posted.json()["author_kind"] == "user"

        history = await client.get("/api/channels/part-c-session-proof/messages")
        assert [message["body"] for message in history.json()["messages"]] == [
            "Dante typed this"
        ]
