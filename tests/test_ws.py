"""Tests for WebSocket endpoint /ws."""

import asyncio
import json
from starlette.testclient import TestClient
from cerebro.api.app import app
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


def test_websocket_inbound_message_enforces_dante_principal(test_db: Settings):
    """Test that inbound WebSocket messages strictly author as 'dante'."""
    app.state.hub = Hub()
    client = TestClient(app)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        store.create_channel(
            channel_id="test-chan",
            name="test",
            team_id="personal-assistant",
        )
    )

    with client.websocket_connect("/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "message.send",
                    "payload": {
                        "channel_id": "test-chan",
                        "content": "Hello from WS client",
                        "author_id": "impostor",
                    },
                }
            )
        )

        # Receive broadcast
        data_text = ws.receive_text()
        data = json.loads(data_text)
        assert data["type"] == "message.new"
        assert data["payload"]["message"]["author_id"] == "dante"
        assert data["payload"]["message"]["body"] == "Hello from WS client"
