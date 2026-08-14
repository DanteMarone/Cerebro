"""Loop control. These tests are the reason full autonomy is safe to run overnight:
each one pins a ceiling that an agent conversation cannot climb past."""

import pytest

from cerebro.turnguard import (
    AgentRateLimiter,
    TurnFrozen,
    TurnGuard,
    TurnLimits,
    new_turn_id,
)


@pytest.fixture
def clock():
    """A hand-cranked clock so no test ever sleeps."""

    now = [0.0]

    def read():
        return now[0]

    read.advance = lambda seconds: now.__setitem__(0, now[0] + seconds)
    return read


def test_depth_cap_freezes_the_turn(clock):
    guard = TurnGuard(TurnLimits(max_depth=3, max_agent_messages=99), clock)
    guard.start("T1")

    for depth in (1, 2, 3):
        assert guard.check("T1", depth).allowed
        guard.record_agent_message("T1", depth)

    verdict = guard.check("T1", 4)
    assert not verdict.allowed
    assert "depth" in verdict.reason
    assert guard.is_frozen("T1")


def test_message_count_cap_freezes_the_turn(clock):
    guard = TurnGuard(TurnLimits(max_depth=99, max_agent_messages=3), clock)
    guard.start("T2")
    for _ in range(3):
        guard.record_agent_message("T2", 1)

    verdict = guard.check("T2", 1)
    assert not verdict.allowed
    assert "agent messages" in verdict.reason


def test_wallclock_cap_freezes_the_turn(clock):
    guard = TurnGuard(TurnLimits(max_depth=99, max_agent_messages=99, max_wallclock_s=60), clock)
    guard.start("T3")
    assert guard.check("T3", 1).allowed

    clock.advance(61)
    verdict = guard.check("T3", 1)
    assert not verdict.allowed
    assert "limit" in verdict.reason


def test_frozen_turn_refuses_further_agent_messages(clock):
    guard = TurnGuard(TurnLimits(max_depth=1), clock)
    guard.start("T4")
    guard.check("T4", 5)

    with pytest.raises(TurnFrozen):
        guard.record_agent_message("T4", 1)


def test_two_agents_mentioning_each_other_forever_are_stopped(clock):
    """The failure this module exists to prevent: A @mentions B, B @mentions A, ad infinitum."""
    guard = TurnGuard(TurnLimits(max_depth=8, max_agent_messages=12), clock)
    guard.start("LOOP")

    produced = 0
    for depth in range(1, 100):
        if not guard.check("LOOP", depth).allowed:
            break
        guard.record_agent_message("LOOP", depth)
        produced += 1

    assert guard.is_frozen("LOOP")
    assert produced <= 12


def test_checking_an_unknown_turn_opens_it_rather_than_failing(clock):
    guard = TurnGuard(clock=clock)
    assert guard.check("never-seen", 1).allowed
    assert guard.get("never-seen") is not None


def test_explicit_freeze_is_available_to_the_kill_switch(clock):
    guard = TurnGuard(clock=clock)
    guard.start("T5")
    guard.freeze("T5", "paused by Dante")

    assert guard.is_frozen("T5")
    assert "paused by Dante" in guard.freeze_message("T5")


def test_sweep_drops_state_nothing_can_reference(clock):
    guard = TurnGuard(clock=clock)
    guard.start("old")
    guard.record_agent_message("old", 1)
    clock.advance(5000)

    assert guard.sweep(3600) == 1
    assert guard.live_turns == 0


def test_turn_ids_are_unique():
    assert len({new_turn_id() for _ in range(500)}) == 500


def test_rate_limiter_caps_self_initiated_conversations(clock):
    limiter = AgentRateLimiter(max_per_hour=2, clock=clock)

    assert limiter.check("forge").allowed
    limiter.record("forge")
    limiter.record("forge")

    assert not limiter.check("forge").allowed
    assert limiter.remaining("forge") == 0
    # One agent hitting its ceiling must not silence the rest of the team.
    assert limiter.check("scout").allowed


def test_rate_limiter_window_slides(clock):
    limiter = AgentRateLimiter(max_per_hour=1, window_s=3600, clock=clock)
    limiter.record("jarvis")
    assert not limiter.check("jarvis").allowed

    clock.advance(3601)
    assert limiter.check("jarvis").allowed
    assert limiter.remaining("jarvis") == 1
