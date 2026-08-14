"""End-to-end WebSocket proofs using the app's real ASGI route and lifespan."""

import importlib

from fastapi.testclient import TestClient

from cerebro import config, db
from cerebro.api.app import app
from cerebro.auth import SessionStore, TokenStore
from cerebro.config import Settings

app_module = importlib.import_module("cerebro.api.app")


def _configure_lifespan(monkeypatch, tmp_path) -> Settings:
    """Point every lifespan-owned persistence path at a disposable test directory."""
    test_settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "test_cerebro.db",
        workspace_path=tmp_path / "workspace",
        agents_path=tmp_path / "agents",
        vault_path=tmp_path / "vault",
        claude_memory_path=tmp_path / "claude_memory_nonexistent",
    )
    monkeypatch.setattr(config, "settings", test_settings)
    monkeypatch.setattr(db, "settings", test_settings)
    monkeypatch.setattr(app_module, "settings", test_settings)
    app.state.token_store = TokenStore(test_settings.data_dir / ".secrets.env")
    app.state.session_store = SessionStore(test_settings.data_dir / ".session.token")
    return test_settings


def test_real_websocket_route_authors_agent_as_itself(monkeypatch, tmp_path):
    """The lifespan, ASGI handshake, inbound frame, hub, and database work on one loop."""
    settings = _configure_lifespan(monkeypatch, tmp_path)
    token = app.state.token_store.issue("codex")

    with TestClient(app) as client:
        created = client.post(
            "/api/channels",
            json={
                "id": "ws-integration-proof",
                "name": "WebSocket integration proof",
                "member_ids": ["codex"],
            },
        )
        assert created.status_code == 201

        with client.websocket_connect(
            "/ws",
            headers={"Authorization": f"Bearer {token}"},
        ) as websocket:
            websocket.send_json(
                {
                    "type": "message.send",
                    "payload": {
                        "channel_id": "ws-integration-proof",
                        "content": "real ASGI path",
                        "author_id": "dante",
                    },
                }
            )
            event = websocket.receive_json()

        assert event["type"] == "message.new"
        message = event["payload"]["message"]
        assert message["author_id"] == "codex"
        assert message["author_kind"] == "agent"
        assert message["body"] == "real ASGI path"

        history = client.get("/api/channels/ws-integration-proof/messages")
        assert history.status_code == 200
        assert history.json()["messages"][-1]["id"] == message["id"]

    assert settings.db_path.exists()


def test_websocket_query_parameter_never_authenticates(monkeypatch, tmp_path):
    """Bearer material in a URL is ignored so it cannot become a supported secret channel."""
    _configure_lifespan(monkeypatch, tmp_path)

    def fail_if_resolved(_token: str) -> str | None:
        raise AssertionError("WebSocket query parameter reached token resolution")

    monkeypatch.setattr(app.state.token_store, "resolve", fail_if_resolved)
    with TestClient(app) as client:
        with client.websocket_connect("/ws?token=must-not-be-read"):
            pass


def test_real_websocket_anonymous_write_is_refused(monkeypatch, tmp_path):
    """An anonymous socket may listen, but a message.send frame cannot create identity."""
    _configure_lifespan(monkeypatch, tmp_path)

    with TestClient(app) as client:
        created = client.post(
            "/api/channels",
            json={
                "id": "ws-anonymous-proof",
                "name": "WebSocket anonymous proof",
            },
        )
        assert created.status_code == 201

        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "message.send",
                    "payload": {
                        "channel_id": "ws-anonymous-proof",
                        "content": "must not be persisted",
                        "author_id": "dante",
                    },
                }
            )

        history = client.get("/api/channels/ws-anonymous-proof/messages")
        assert history.status_code == 200
        assert history.json()["messages"] == []


def test_real_websocket_session_authors_human_as_dante(monkeypatch, tmp_path):
    """A positive UI session cookie, not credential absence, supplies the human principal."""
    _configure_lifespan(monkeypatch, tmp_path)

    with TestClient(app) as client:
        opened = client.get("/")
        assert opened.status_code == 200
        assert client.cookies.get("cerebro_session")

        created = client.post(
            "/api/channels",
            json={
                "id": "ws-session-proof",
                "name": "WebSocket session proof",
            },
        )
        assert created.status_code == 201

        with client.websocket_connect("/ws") as websocket:
            websocket.send_json(
                {
                    "type": "message.send",
                    "payload": {
                        "channel_id": "ws-session-proof",
                        "content": "positive human session",
                        "author_id": "codex",
                    },
                }
            )
            event = websocket.receive_json()

        message = event["payload"]["message"]
        assert message["author_id"] == "dante"
        assert message["author_kind"] == "user"
        assert message["body"] == "positive human session"
