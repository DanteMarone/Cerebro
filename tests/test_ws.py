"""Tests for WebSocket endpoint /ws."""

import asyncio
import json
import pytest
from fastapi import WebSocketDisconnect
from starlette.testclient import TestClient
from cerebro.api.app import app
from cerebro.api.ws import websocket_endpoint
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

    def __init__(self, app_instance, incoming: list[str]):
        self.app = app_instance
        self.incoming = list(incoming)
        self.sent: list[str] = []
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_text(self) -> str:
        if self.incoming:
            return self.incoming.pop(0)
        raise WebSocketDisconnect(code=1000)

    async def send_text(self, text: str):
        self.sent.append(text)


@pytest.mark.asyncio
async def test_websocket_inbound_message_enforces_dante_principal(test_db: Settings):
    """Test that inbound WebSocket messages strictly author as 'dante'."""
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
