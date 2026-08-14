"""Unit tests for scripts/poll_channels.py CLI tool."""

from pathlib import Path
from scripts.poll_channels import (
    get_agent_token,
    load_state,
    save_state,
)
from cerebro.auth import TokenStore


def test_load_state_missing_or_corrupt_returns_empty(tmp_path: Path):
    missing_file = tmp_path / "nonexistent.json"
    assert load_state(missing_file) == {}

    corrupt_file = tmp_path / "corrupt.json"
    corrupt_file.write_text("invalid json content{", encoding="utf-8")
    assert load_state(corrupt_file) == {}


def test_save_and_load_state_atomic_roundtrip(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state_data = {"antigravity:warroom": 42, "claude:general": 100}

    save_state(state_data, state_file=state_file)
    loaded = load_state(state_file=state_file)

    assert loaded == state_data
    assert not state_file.with_suffix(".tmp").exists()


def test_get_agent_token_from_tokenstore(tmp_path: Path):
    secrets_path = tmp_path / ".secrets.env"
    store = TokenStore(secrets_path)
    issued_token = store.issue("antigravity")

    token = get_agent_token("antigravity", secrets_path=secrets_path)
    assert token == issued_token

    assert get_agent_token("unknown_agent", secrets_path=secrets_path) is None
