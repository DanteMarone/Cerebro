import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from cerebro.auth import TokenStore
from scripts.poll_channels import (
    fetch_channel_members,
    fetch_channels,
    get_agent_token,
    load_state,
    poll_all_channels,
    post_message,
    save_state,
)


def test_load_state_missing_or_corrupt_returns_empty(tmp_path: Path):
    missing_file = tmp_path / ".agent_seen_jarvis.json"
    assert load_state("jarvis", state_file=missing_file) == {}

    corrupt_file = tmp_path / ".agent_seen_corrupt.json"
    corrupt_file.write_text("invalid json content{", encoding="utf-8")
    assert load_state("corrupt", state_file=corrupt_file) == {}


def test_save_and_load_state_per_agent_isolation(tmp_path: Path):
    jarvis_file = tmp_path / ".agent_seen_jarvis.json"
    claude_file = tmp_path / ".agent_seen_claude.json"

    save_state("jarvis", {"warroom": 42}, state_file=jarvis_file)
    save_state("claude", {"general": 100}, state_file=claude_file)

    assert load_state("jarvis", state_file=jarvis_file) == {"warroom": 42}
    assert load_state("claude", state_file=claude_file) == {"general": 100}

    # Ensure no leftover .tmp files
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert not tmp_files


def test_get_agent_token_from_tokenstore(tmp_path: Path):
    secrets_path = tmp_path / ".secrets.env"
    store = TokenStore(secrets_path)
    issued_token = store.issue("codex")

    token = get_agent_token("codex", secrets_path=secrets_path)
    assert token == issued_token

    assert get_agent_token("unknown_agent", secrets_path=secrets_path) is None


def test_fetch_channels_requires_token_and_sends_bearer_header():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"channels": [{"id": "warroom"}]}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        channels = fetch_channels(agent_id="jarvis", token="token-123", base_url="http://test:8765")
        assert channels == [{"id": "warroom"}]
        req = mock_open.call_args[0][0]
        assert req.headers["Authorization"] == "Bearer token-123"
        assert req.full_url == "http://test:8765/api/channels"


def test_fetch_channel_members_sends_auth():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"members": [{"member_id": "jarvis"}]}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        members = fetch_channel_members(
            "warroom",
            agent_id="jarvis",
            token="tok",
            base_url="http://test:8765",
        )
        assert members == [{"member_id": "jarvis"}]
        req = mock_open.call_args[0][0]
        assert req.headers["Authorization"] == "Bearer tok"
        assert req.full_url == "http://test:8765/api/channels/warroom/members"


def test_post_message_sends_json_payload_and_auth():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"id": 99, "content": "hello"}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
        res = post_message(
            channel_id="warroom",
            agent_id="jarvis",
            content="hello",
            token="tok-456",
            base_url="http://test:8765",
        )
        assert res == {"id": 99, "content": "hello"}
        req = mock_open.call_args[0][0]
        assert req.headers["Authorization"] == "Bearer tok-456"
        assert req.headers["Content-type"] == "application/json"
        assert json.loads(req.data.decode("utf-8")) == {"content": "hello"}


def test_poll_all_channels_filters_non_member_channels(tmp_path: Path):
    state_file = tmp_path / "state.json"

    # Channels: warroom (member) and secret-room (not member)
    channels_mock = [{"id": "warroom"}, {"id": "secret-room"}]
    members_warroom = [{"member_id": "jarvis"}, {"member_id": "dante"}]
    members_secret = [{"member_id": "dante"}]

    def mock_urlopen(req, timeout=10.0):
        url = req.full_url
        mock = MagicMock()
        mock.__enter__.return_value = mock
        if url.endswith("/api/channels"):
            mock.read.return_value = json.dumps({"channels": channels_mock}).encode("utf-8")
        elif url.endswith("/api/channels/warroom/members"):
            mock.read.return_value = json.dumps({"members": members_warroom}).encode("utf-8")
        elif url.endswith("/api/channels/secret-room/members"):
            mock.read.return_value = json.dumps({"members": members_secret}).encode("utf-8")
        elif "/messages" in url:
            msg_payload = {"messages": [{"id": 1, "content": "hi"}]}
            mock.read.return_value = json.dumps(msg_payload).encode("utf-8")
        return mock

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        unseen = poll_all_channels(
            agent_id="jarvis",
            token="tok",
            state_file=state_file,
            base_url="http://test:8765",
        )

        # Only warroom was polled; secret-room was skipped
        assert "warroom" in unseen
        assert "secret-room" not in unseen
        assert load_state("jarvis", state_file=state_file) == {"warroom": 1}
