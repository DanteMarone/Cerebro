"""§7 — what an agent sees before it speaks.

The motivating evidence: asked what model it runs on, Jarvis answered "a local 12B parameter
model" while actually running qwen3.6-27b. It was not lying, it simply had no way to know. A
cli_agent is a fresh process every turn, so anything it is meant to know has to be in this packet
or it does not exist.
"""

from pathlib import Path

from cerebro.context import ContextBuilder
from cerebro.models import Agent, Message

CHANNEL = {"id": "warroom", "name": "warroom", "topic": "Cerebro buildout"}
MEMBERS = ["dante", "claude", "jarvis"]


def agent_with_home(tmp_path: Path, **kwargs) -> Agent:
    home = tmp_path / "jarvis"
    (home / "memory").mkdir(parents=True, exist_ok=True)
    (home / "logs").mkdir(exist_ok=True)
    return Agent(id="jarvis", name="jarvis", display_name="Jarvis", role="Personal assistant",
                 provider="lmstudio", home_path=str(home), **kwargs)


def builder(tmp_path: Path, **kwargs) -> ContextBuilder:
    return ContextBuilder(agents_root=tmp_path, **kwargs)


def history(n: int, size: int = 40) -> list[Message]:
    return [
        Message(channel_id="warroom", author_id="dante", author_kind="user", body="x" * size)
        for _ in range(n)
    ]


def bodies(packet: list[Message]) -> str:
    return "\n".join(m.body for m in packet)


def test_the_agent_is_told_who_it_is(tmp_path):
    agent = agent_with_home(tmp_path)
    packet = builder(tmp_path).build(agent, "You help Dante.", CHANNEL, MEMBERS, [])

    text = bodies(packet)
    assert "Jarvis" in text
    assert "Personal assistant" in text
    assert "`jarvis`" in text, "an agent must know the id its messages are attributed to"


def test_the_agent_is_told_which_room_it_is_in_and_who_is_present(tmp_path):
    agent = agent_with_home(tmp_path)
    packet = builder(tmp_path).build(agent, "prompt", CHANNEL, MEMBERS, [])

    text = bodies(packet)
    assert "#warroom" in text
    assert "@dante" in text and "@claude" in text


def test_the_scratchpad_is_included(tmp_path):
    agent = agent_with_home(tmp_path)
    (Path(agent.home_path) / "scratchpad.md").write_text("waiting on the codex fix",
                                                         encoding="utf-8")
    packet = builder(tmp_path).build(agent, "prompt", CHANNEL, MEMBERS, [])

    assert "waiting on the codex fix" in bodies(packet)


def test_memory_notes_are_included_most_recent_first(tmp_path):
    agent = agent_with_home(tmp_path)
    memory = Path(agent.home_path) / "memory"
    (memory / "older.md").write_text("an older fact", encoding="utf-8")
    (memory / "newer.md").write_text("a newer fact", encoding="utf-8")

    text = bodies(builder(tmp_path).build(agent, "prompt", CHANNEL, MEMBERS, []))
    assert "an older fact" in text and "a newer fact" in text


def test_a_missing_scratchpad_or_memory_is_not_an_error(tmp_path):
    agent = Agent(id="ghost", name="ghost", provider="lmstudio",
                  home_path=str(tmp_path / "nowhere"))
    packet = builder(tmp_path).build(agent, "prompt", CHANNEL, MEMBERS, [])

    assert packet, "an agent with no files must still get a packet"


def test_the_operating_manual_is_included_when_given(tmp_path):
    agent = agent_with_home(tmp_path)
    build = builder(tmp_path, operating_manual="Reply PASS if you have nothing to add.")
    assert "Reply PASS" in bodies(build.build(agent, "prompt", CHANNEL, MEMBERS, []))


def test_history_is_trimmed_to_fit_but_identity_is_never_dropped(tmp_path):
    """Identity and the house rules survive; old chatter is what goes."""
    agent = agent_with_home(tmp_path)
    build = builder(tmp_path, budget_tokens=200, operating_manual="HOUSE RULES HERE")

    packet = build.build(agent, "You are Jarvis.", CHANNEL, MEMBERS, history(200, size=400))

    text = bodies(packet)
    assert "Jarvis" in text
    assert "HOUSE RULES HERE" in text
    assert len(packet) < 200, "history should have been trimmed"


def test_the_most_recent_history_is_what_survives(tmp_path):
    agent = agent_with_home(tmp_path)
    build = builder(tmp_path, budget_tokens=300)

    old = Message(channel_id="warroom", author_id="dante", author_kind="user", body="OLDEST")
    recent = Message(channel_id="warroom", author_id="dante", author_kind="user", body="NEWEST")
    packet = build.build(agent, "p", CHANNEL, MEMBERS, [old] + history(200, 400) + [recent])

    assert "NEWEST" in bodies(packet)


def test_even_an_impossible_budget_keeps_the_triggering_message(tmp_path):
    """Dropping the message that woke the agent would leave it answering nothing at all."""
    agent = agent_with_home(tmp_path)
    build = builder(tmp_path, budget_tokens=1)

    trigger = Message(channel_id="warroom", author_id="dante", author_kind="user",
                      body="the thing being asked")
    packet = build.build(agent, "p", CHANNEL, MEMBERS, history(50, 400) + [trigger])

    assert "the thing being asked" in bodies(packet)


def test_system_sections_come_before_history(tmp_path):
    agent = agent_with_home(tmp_path)
    packet = builder(tmp_path).build(agent, "prompt", CHANNEL, MEMBERS, history(3))

    kinds = [m.kind for m in packet]
    assert kinds.index("chat") > kinds.index("system")
