"""Tests for cerebro/agents_loader.py."""

import json
import pytest
from cerebro import agents_loader, store
from cerebro.config import Settings


@pytest.mark.asyncio
async def test_load_all_agents_from_dir(tmp_path, test_db: Settings):
    """Test scanning a directory of agent folders."""
    agent_dir = tmp_path / "bot1"
    agent_dir.mkdir()
    (agent_dir / "profile.json").write_text(
        json.dumps({
            "id": "bot1",
            "name": "bot1",
            "display_name": "Bot One",
            "role": "Assistant",
            "provider": "fake",
            "model": "m1",
        }),
        encoding="utf-8",
    )
    (agent_dir / "system_prompt.md").write_text(
        "You are Bot One.", encoding="utf-8"
    )

    loaded = await agents_loader.load_all_agents(agents_dir=tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["id"] == "bot1"

    agent = await store.get_agent("bot1")
    assert agent is not None
    assert agent["system_prompt"] == "You are Bot One."


@pytest.mark.asyncio
async def test_bootstrap_seed_data(test_db: Settings):
    """Test bootstrapping Jarvis and the DM channel."""
    await agents_loader.bootstrap_seed_data()

    # Check jarvis agent exists
    jarvis = await store.get_agent("jarvis")
    assert jarvis is not None
    assert jarvis["id"] == "jarvis"

    # Check DM channel exists
    dm = await store.get_channel("dm-dante-jarvis")
    assert dm is not None
    assert dm["type"] == "dm"

    # Check members
    members = await store.get_channel_members("dm-dante-jarvis")
    member_ids = {m["agent_id"] for m in members}
    assert "dante" in member_ids
    assert "jarvis" in member_ids

    # Check sonnet agent exists
    sonnet = await store.get_agent("sonnet")
    assert sonnet is not None
    assert sonnet["id"] == "sonnet"
    assert sonnet["display_name"] == "Sonnet 5"
    assert sonnet["provider"] == "cli_agent"

    # Check Sonnet DM channel exists
    dm_sonnet = await store.get_channel("dm-dante-sonnet")
    assert dm_sonnet is not None
    assert dm_sonnet["type"] == "dm"

    # Check opus agent exists
    opus = await store.get_agent("opus")
    assert opus is not None
    assert opus["id"] == "opus"
    assert opus["display_name"] == "Opus 5"
    assert opus["provider"] == "cli_agent"

    # Check Opus DM channel exists
    dm_opus = await store.get_channel("dm-dante-opus")
    assert dm_opus is not None
    assert dm_opus["type"] == "dm"
