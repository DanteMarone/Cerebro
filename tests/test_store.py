"""Tests for cerebro/store.py persistence layer."""

import pytest
from cerebro import store
from cerebro.config import Settings


@pytest.mark.asyncio
async def test_store_agent_crud(test_db: Settings):
    """Test upsert_agent, get_agent, and list_agents."""
    agent_data = {
        "id": "test-agent",
        "name": "test-agent",
        "display_name": "Test Agent",
        "avatar": "🧪",
        "role": "Tester",
        "system_prompt": "Test prompt",
        "provider": "fake",
        "model": "fake-model",
        "params": {"temperature": 0.5},
        "tools_enabled": ["test:tool"],
        "delegation_enabled": False,
        "enabled": True,
    }

    await store.upsert_agent(agent_data)
    agent = await store.get_agent("test-agent")
    assert agent is not None
    assert agent["id"] == "test-agent"
    assert agent["display_name"] == "Test Agent"
    assert agent["params"] == {"temperature": 0.5}
    assert agent["tools_enabled"] == ["test:tool"]

    agents = await store.list_agents()
    assert any(a["id"] == "test-agent" for a in agents)


@pytest.mark.asyncio
async def test_store_channel_and_messages(test_db: Settings):
    """Test create_channel, add_channel_member, append_message, list_messages."""
    ch = await store.create_channel(
        channel_id="ch-test",
        name="test-channel",
        channel_type="public",
        topic="Testing",
    )
    assert ch["id"] == "ch-test"

    # Dante is automatically a member (§6.1)
    members = await store.get_channel_members("ch-test")
    assert any(m["member_id"] == "dante" for m in members)

    msg_id1 = await store.append_message(
        channel_id="ch-test",
        author_id="dante",
        content="First message",
    )
    msg_id2 = await store.append_message(
        channel_id="ch-test",
        author_id="jarvis",
        content="Second message",
    )
    assert msg_id2 > msg_id1

    all_msgs = await store.list_messages("ch-test")
    assert len(all_msgs) == 2
    assert all_msgs[0]["content"] == "First message"
    assert all_msgs[1]["content"] == "Second message"

    after_msgs = await store.list_messages("ch-test", after_id=msg_id1)
    assert len(after_msgs) == 1
    assert after_msgs[0]["content"] == "Second message"


@pytest.mark.asyncio
async def test_dante_channel_owner_invariants(test_db: Settings):
    """Test that Dante is always a member and cannot be removed (§6.1)."""
    ch = await store.create_channel(
        channel_id="ch-owner-test",
        name="owner-test",
        created_by="other",
    )
    assert ch["id"] == "ch-owner-test"

    members = await store.get_channel_members("ch-owner-test")
    assert any(m["member_id"] == "dante" for m in members)

    # Attempting to remove Dante must raise ValueError
    with pytest.raises(ValueError, match="Cannot remove owner 'dante'"):
        await store.remove_channel_member("ch-owner-test", "dante")


@pytest.mark.asyncio
async def test_list_messages_recent_limit_order(test_db: Settings):
    """Test that list_messages without after_id returns latest messages in chronological order."""
    ch_id = "ch-paging-test"
    await store.create_channel(ch_id, "paging-test")

    for i in range(1, 6):
        await store.append_message(
            channel_id=ch_id,
            author_id="dante",
            content=f"Message {i}",
        )

    recent_3 = await store.list_messages(ch_id, limit=3)
    assert len(recent_3) == 3
    assert [m["content"] for m in recent_3] == ["Message 3", "Message 4", "Message 5"]
