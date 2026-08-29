"""Tests for cerebro.service's turn-routing decisions."""

import pytest

from cerebro import store
from cerebro.hub import Hub
from cerebro.service import RuntimeService, _channels_for


@pytest.mark.asyncio
async def test_responder_skips_a_muted_dm_partner(test_db):
    """A muted DM member must not be offered the turn, even though it is still on the roster.

    This is the enforcement half of the mute/"kick" feature: store.set_member_listen_mode flips
    the flag, and RuntimeService._responder has to actually honor it or a "kicked" agent keeps
    answering.
    """
    await store.create_channel(channel_id="dm-mute-test", name="dm-mute-test", kind="dm")
    await store.add_channel_member("dm-mute-test", "codex", member_kind="agent")
    await store.upsert_agent({"id": "codex", "provider": "cli_agent", "enabled": True})

    service = RuntimeService(Hub())

    agent = await service._responder("dm-mute-test")
    assert agent is not None and agent.id == "codex", "an active DM member must be offered the turn"

    await store.set_member_listen_mode("dm-mute-test", "codex", "muted")
    agent = await service._responder("dm-mute-test")
    assert agent is None, "a muted DM member must not be offered the turn"

    await store.set_member_listen_mode("dm-mute-test", "codex", "active")
    agent = await service._responder("dm-mute-test")
    assert agent is not None and agent.id == "codex", "unmuting must restore the responder"


@pytest.mark.asyncio
async def test_channels_for_excludes_muted_membership(test_db):
    """The poller must not wake an agent in a channel where it has been muted."""
    await store.create_channel(channel_id="c1", name="c1")
    await store.create_channel(channel_id="c2", name="c2")
    await store.add_channel_member("c1", "jarvis", member_kind="agent")
    await store.add_channel_member("c2", "jarvis", member_kind="agent")

    assert set(await _channels_for("jarvis")) == {"c1", "c2"}

    await store.set_member_listen_mode("c1", "jarvis", "muted")
    assert set(await _channels_for("jarvis")) == {"c2"}


def test_provider_for_cli_agent_sandboxed_cwd(tmp_path):
    """CLI agents default to a dedicated workspace cwd to prevent scanning the repo root."""
    from cerebro.models import Agent
    from cerebro.service import _provider_for
    from cerebro.providers.cli_agent import CliAgentProvider

    agent = Agent(id="opus", name="opus", provider="cli_agent", model="opus")
    prov = _provider_for(agent)
    assert isinstance(prov, CliAgentProvider)
    assert prov.backend == "claude"
    assert prov.cwd is not None
    assert "opus" in prov.cwd and "workspace" in prov.cwd
