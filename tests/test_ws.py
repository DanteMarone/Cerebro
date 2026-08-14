"""Tests for WebSocket endpoint /ws."""

import json
from starlette.testclient import TestClient
from cerebro.api.app import app
from cerebro.config import Settings
from cerebro.hub import Hub


def test_websocket_connect_and_receive_events(test_db: Settings):
    """Test WebSocket connection and event delivery via Hub."""
    app.state.hub = Hub()
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        # Publish an event on hub
        import asyncio

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
