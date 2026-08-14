"""Tests for WebSocket endpoint /ws."""

import asyncio
import json
import pytest
from fastapi import WebSocketDisconnect
from starlette.testclient import TestClient
from cerebro.api.app import app
from cerebro.api.ws import websocket_endpoint
from cerebro.auth import TokenStore
from cerebro.config import Settings
from cerebro.hub import Hub
from cerebro import store


def test_websocket_connect_and_receive_events(test_db: Settings):
    """Test WebSocket connection and event delivery via Hub."""
    app.state.hub = Hub()
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        # Publish an event on hub
        loop = asyncio.get_event_loop()
        loop.run_until_complete(
            app.state.hub.publish(
                "message.new",
                {
                    "channel_id": "dm-dante-jarvis",
                    "message": {"id": 100, "content": "Test WS broadcast"},
                },
            )
        )

        data_text = ws.receive_text()
        data = json.loads(data_text)
        assert data["type"] == "message.new"
        assert data["payload"]["message"]["content"] == "Test WS broadcast"
        assert "seq" in data


class MockWebSocket:
    """Async WebSocket test double running directly on pytest's event loop."""

    def __init__(
        self,
        app_instance,
        incoming: list[str],
        headers: dict | None = None,
        query_params: dict | None = None,
    ):
        self.app = app_instance
        self.incoming = list(incoming)
        self.headers = headers or {}
        self.query_params = query_params or {}
        self.sent: list[str] = []
        self.accepted = False
        self.closed_code = None
        self.closed_reason = None

    async def accept(self):
        self.accepted = True

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed_code = code
        self.closed_reason = reason

    async def receive_text(self) -> str:
        if self.incoming:
            return self.incoming.pop(0)
        raise WebSocketDisconnect(code=1000)

    async def send_text(self, text: str):
        self.sent.append(text)


@pytest.mark.asyncio
async def test_websocket_inbound_message_enforces_dante_principal(test_db: Settings):
    """Test that inbound anonymous WebSocket messages strictly author as 'dante'."""
    app.state.hub = Hub()
    await store.create_channel(
        channel_id="test-chan",
        name="test",
        team_id="personal-assistant",
    )

    payload = json.dumps(
        {
            "type": "message.send",
            "payload": {
                "channel_id": "test-chan",
                "content": "Hello from WS client",
                "author_id": "impostor",
            },
        }
    )

    ws = MockWebSocket(app, [payload])
    await websocket_endpoint(ws)

    messages = await store.list_messages("test-chan")
    assert len(messages) == 1
    assert messages[0]["author_id"] == "dante"
    assert messages[0]["body"] == "Hello from WS client"


@pytest.mark.asyncio
async def test_websocket_inbound_message_with_agent_token_authors_as_agent(test_db: Settings):
    """Test that WebSocket authenticated with agent bearer token authors as that agent."""
    app.state.hub = Hub()
    token_store = TokenStore(test_db.data_dir / ".secrets.env")
    token = token_store.issue("claude")

    await store.create_channel(
        channel_id="test-chan-agent",
        name="agent-test",
        team_id="personal-assistant",
    )

    payload = json.dumps(
        {
            "type": "message.send",
            "payload": {
                "channel_id": "test-chan-agent",
                "content": "Hello from Claude agent",
                "author_id": "impostor-dante",
            },
        }
    )

    ws = MockWebSocket(app, [payload], headers={"authorization": f"Bearer {token}"})
    await websocket_endpoint(ws)

    messages = await store.list_messages("test-chan-agent")
    assert len(messages) == 1
    assert messages[0]["author_id"] == "claude"
    assert messages[0]["body"] == "Hello from Claude agent"


@pytest.mark.asyncio
async def test_websocket_invalid_token_rejects_with_4401(test_db: Settings):
    """Test that WebSocket connection with invalid token is closed with code 4401."""
    app.state.hub = Hub()
    ws = MockWebSocket(app, [], headers={"authorization": "Bearer invalid-token-xyz"})
    await websocket_endpoint(ws)

    assert ws.accepted is False
    assert ws.closed_code == 4401
