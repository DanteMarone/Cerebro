"""§6 polling — agents wake themselves, on their own interval, and stop being woken when paused.

This replaces three hand-rolled watchers living outside Cerebro, none of which survived their
session closing. The behaviours worth pinning are the ones that made those watchers wrong: joining
a channel should not trigger a reply to its backlog, a slow agent must not accumulate overlapping
turns, and the kill switch must stop agents waking rather than only stopping turns already running.
"""

import pytest

from cerebro.models import Agent
from cerebro.poller import ChannelPoller


@pytest.fixture
def clock():
    now = [1000.0]

    def read():
        return now[0]

    read.advance = lambda s: now.__setitem__(0, now[0] + s)
    return read


class World:
    """A tiny fake Cerebro: agents, their channels, and where each channel has got to."""

    def __init__(self, agents, membership, latest):
        self.agents = agents
        self.membership = membership
        self.latest = latest
        self.turns: list[tuple[str, str]] = []
        self.turn_hook = None

    async def list_agents(self):
        return self.agents

    async def channels_for(self, agent_id):
        return self.membership.get(agent_id, [])

    async def latest_message_id(self, channel_id):
        return self.latest.get(channel_id, 0)

    async def run_turn(self, agent, channel_id):
        self.turns.append((agent.id, channel_id))
        if self.turn_hook:
            await self.turn_hook(agent, channel_id)


def build(world, clock, **kwargs):
    return ChannelPoller(
        list_agents=world.list_agents,
        channels_for=world.channels_for,
        latest_message_id=world.latest_message_id,
        run_turn=world.run_turn,
        clock=clock,
        **kwargs,
    )


CLAUDE = Agent(id="claude", name="claude", provider="cli_agent")
JARVIS = Agent(id="jarvis", name="jarvis", provider="lmstudio")


async def test_first_sight_of_a_channel_is_not_news(clock):
    """Joining a room must not make an agent answer a year of backlog."""
    world = World([CLAUDE], {"claude": ["warroom"]}, {"warroom": 500})
    poller = build(world, clock)

    assert await poller.tick() == 0
    assert world.turns == []


async def test_a_new_message_wakes_the_agent(clock):
    world = World([CLAUDE], {"claude": ["warroom"]}, {"warroom": 500})
    poller = build(world, clock)
    await poller.tick()

    world.latest["warroom"] = 501
    clock.advance(60)

    assert await poller.tick() == 1
    assert world.turns == [("claude", "warroom")]


async def test_the_agent_is_not_woken_again_for_the_same_messages(clock):
    world = World([CLAUDE], {"claude": ["warroom"]}, {"warroom": 500})
    poller = build(world, clock)
    await poller.tick()
    world.latest["warroom"] = 501

    clock.advance(60)
    await poller.tick()
    clock.advance(60)
    await poller.tick()

    assert world.turns == [("claude", "warroom")]


async def test_five_new_messages_produce_one_turn(clock):
    """Batching is what makes N agents affordable: cost is per round, not per message."""
    world = World([CLAUDE], {"claude": ["warroom"]}, {"warroom": 500})
    poller = build(world, clock)
    await poller.tick()

    world.latest["warroom"] = 505
    clock.advance(60)
    await poller.tick()

    assert len(world.turns) == 1


async def test_the_interval_is_respected(clock):
    world = World([CLAUDE], {"claude": ["warroom"]}, {"warroom": 500})
    poller = build(world, clock, default_interval_s=45)
    await poller.tick()
    world.latest["warroom"] = 501

    clock.advance(10)
    assert await poller.tick() == 0

    clock.advance(40)
    assert await poller.tick() == 1


async def test_per_agent_interval_from_the_profile(clock):
    fast = Agent(id="jarvis", name="jarvis", provider="lmstudio",
                 params_json='{"poll_interval_s": 5}')
    world = World([fast], {"jarvis": ["warroom"]}, {"warroom": 1})
    poller = build(world, clock, default_interval_s=45)
    await poller.tick()

    world.latest["warroom"] = 2
    clock.advance(6)

    assert await poller.tick() == 1


async def test_an_agent_mid_turn_is_not_woken_again(clock):
    """A slow harness would otherwise accumulate overlapping subprocesses on a stale view."""
    world = World([CLAUDE], {"claude": ["a", "b"]}, {"a": 1, "b": 1})
    poller = build(world, clock)
    await poller.tick()

    async def reenter(agent, channel_id):
        world.latest["b"] = 99
        await poller.tick()

    world.turn_hook = reenter
    world.latest["a"] = 2
    clock.advance(60)
    await poller.tick()

    assert world.turns == [("claude", "a")]


async def test_pause_stops_agents_waking(clock):
    """§8.6 -- the kill switch must stop wakeups, not only turns already in flight."""
    world = World([CLAUDE], {"claude": ["warroom"]}, {"warroom": 1})
    poller = build(world, clock)
    await poller.tick()

    poller.pause()
    world.latest["warroom"] = 2
    clock.advance(60)

    assert poller.paused
    poller.resume()
    assert await poller.tick() == 1


async def test_only_channels_the_agent_belongs_to(clock):
    world = World([CLAUDE, JARVIS], {"claude": ["warroom"], "jarvis": ["dm-dante-jarvis"]},
                  {"warroom": 1, "dm-dante-jarvis": 1})
    poller = build(world, clock)
    await poller.tick()

    world.latest["dm-dante-jarvis"] = 2
    clock.advance(60)
    await poller.tick()

    assert world.turns == [("jarvis", "dm-dante-jarvis")]


async def test_a_failing_turn_does_not_stop_the_poller(clock):
    world = World([CLAUDE], {"claude": ["warroom"]}, {"warroom": 1})
    poller = build(world, clock)
    await poller.tick()

    async def explode(agent, channel_id):
        raise RuntimeError("harness died")

    world.turn_hook = explode
    world.latest["warroom"] = 2
    clock.advance(60)
    await poller.tick()

    world.turn_hook = None
    world.latest["warroom"] = 3
    clock.advance(60)
    assert await poller.tick() == 1
