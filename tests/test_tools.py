"""§10.2 core tools and §8.8 trust tiers.

Dante's threat model, in his words: "The local agents have not proven themselves to not totally
fuck up my system. So my main goal there was to narrow the local agent blast radius."

So the tests that matter here are not "does the tool work" but "can an agent reach anything it
should not". A sandboxed agent must not be *offered* a dangerous tool, because a model that can
see a capability will eventually try it, and every path must be confined at execution time as
well as at catalogue time.
"""

import pytest

from cerebro.models import Agent
from cerebro.tools import CoreTools, ToolError, _confined_path


@pytest.fixture
def tools(tmp_path):
    return CoreTools(agents_root=tmp_path)


@pytest.fixture
def jarvis(tmp_path):
    return Agent(id="jarvis", name="jarvis", provider="lmstudio",
                 home_path=str(tmp_path / "jarvis"))


SANDBOXED = {"trust": "sandboxed"}
FULL = {"trust": "full"}


def names(specs):
    return {s.name for s in specs}


# -- the catalogue ----------------------------------------------------------------

def test_a_sandboxed_agent_is_never_offered_a_dangerous_tool(tools, jarvis):
    """Not refused when it asks — absent, so it never asks."""
    offered = names(tools.specs_for(jarvis, SANDBOXED))

    for dangerous in ("run_command", "delegate_coding_task", "publish_tool", "fs_write"):
        assert dangerous not in offered


def test_a_missing_trust_field_is_treated_as_sandboxed(tools, jarvis):
    """Forgetting to set trust must fail safe, not open."""
    assert tools.tier_of(jarvis, {}) == "sandboxed"
    assert tools.tier_of(jarvis, None) == "sandboxed"
    assert tools.tier_of(jarvis, {"trust": "nonsense"}) == "sandboxed"


def test_a_sandboxed_agent_can_still_keep_notes(tools, jarvis):
    offered = names(tools.specs_for(jarvis, SANDBOXED))
    assert {"scratchpad_read", "scratchpad_append", "memory_write"} <= offered


async def test_calling_an_unoffered_tool_is_refused_even_if_the_model_invents_it(tools, jarvis):
    result = await tools.execute(jarvis, "run_command", {"cmd": "rm -rf /"}, SANDBOXED)
    assert "not available" in result


async def test_an_unknown_tool_name_is_refused(tools, jarvis):
    """A name that does not exist gets the same answer as one that is merely forbidden.

    That is deliberate rather than sloppy: distinguishing "no such tool" from "not permitted"
    tells a caller which capabilities exist and would let a model map the catalogue by guessing.
    """
    result = await tools.execute(jarvis, "nonsense_tool", {}, FULL)
    assert "error" in result
    assert "nonsense_tool" in result


# -- confinement ------------------------------------------------------------------

@pytest.mark.parametrize(
    "name",
    ["../escape", "../../etc/passwd", "sub/dir/note", "..\\windows", ".hidden", ""],
)
async def test_a_note_name_cannot_escape_the_memory_directory(tools, jarvis, name):
    result = await tools.execute(jarvis, "memory_write", {"name": name, "body": "x"}, SANDBOXED)
    assert "not a usable note name" in result or "error" in result


async def test_writes_land_inside_the_agents_own_home(tools, jarvis, tmp_path):
    await tools.execute(jarvis, "memory_write", {"name": "fact", "body": "the sky is up"},
                        SANDBOXED)

    written = list((tmp_path / "jarvis" / "memory").glob("*.md"))
    assert [p.name for p in written] == ["fact.md"]
    assert "the sky is up" in written[0].read_text(encoding="utf-8")


async def test_symlinked_note_outside_root_is_rejected_on_read(tools, jarvis, tmp_path):
    """An attacker or compromised process creates a symlink in memory/ pointing to an
    external secret."""
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("SUPER_SECRET_TOKEN", encoding="utf-8")

    mem_dir = tmp_path / "jarvis" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    symlink_file = mem_dir / "secret.md"

    try:
        symlink_file.symlink_to(outside_file)
    except OSError:
        pytest.skip("Symlink creation not permitted on this platform/account")

    # Reading the symlink must be blocked by confinement check
    result = await tools.execute(jarvis, "memory_read", {"name": "secret"}, SANDBOXED)
    assert "confinement violation" in result or "error" in result
    assert "SUPER_SECRET_TOKEN" not in result


async def test_symlinked_note_outside_root_is_excluded_from_list(tools, jarvis, tmp_path):
    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("SECRET", encoding="utf-8")

    mem_dir = tmp_path / "jarvis" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    symlink_file = mem_dir / "external.md"

    try:
        symlink_file.symlink_to(outside_file)
    except OSError:
        pytest.skip("Symlink creation not permitted on this platform/account")

    # Listing must not include the escaped symlink
    listed = await tools.execute(jarvis, "memory_list", {}, SANDBOXED)
    assert "external.md" not in listed


def test_confined_path_rejects_escaping_targets(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    outside = tmp_path / "outside.txt"

    with pytest.raises(ToolError, match="confinement violation"):
        _confined_path(root, outside)

    with pytest.raises(ToolError, match="confinement violation"):
        _confined_path(root, "../outside.txt")


def test_confined_path_allows_strictly_contained_targets(tmp_path):
    root = tmp_path / "sandbox"
    root.mkdir()
    safe = _confined_path(root, "valid.md")
    assert safe == (root / "valid.md").resolve()


async def test_home_outside_agents_root_is_rejected(tools, tmp_path):
    rogue = Agent(
        id="rogue",
        name="rogue",
        provider="lmstudio",
        home_path=str(tmp_path.parent / "escape_dir"),
    )
    result = await tools.execute(rogue, "scratchpad_read", {}, SANDBOXED)
    assert "confinement violation" in result


async def test_junction_home_escaping_agents_root_is_rejected(tmp_path):
    agents_root = tmp_path / "agents"
    agents_root.mkdir()
    outside_dir = tmp_path / "outside_victim"
    outside_dir.mkdir()

    junction_path = agents_root / "attacker"
    try:
        import _winapi
        _winapi.CreateJunction(str(outside_dir), str(junction_path))
    except (ImportError, OSError, AttributeError):
        pytest.skip("Directory junction creation not available on this platform")

    attacker = Agent(id="attacker", name="attacker", provider="lmstudio")
    tools = CoreTools(agents_root=agents_root)

    result = await tools.execute(attacker, "scratchpad_append", {"text": "leak"}, SANDBOXED)
    assert "confinement violation" in result
    assert not list(outside_dir.glob("*")), "Victim directory must not be modified"


# -- behaviour --------------------------------------------------------------------

async def test_scratchpad_round_trip(tools, jarvis):
    assert "empty" in await tools.execute(jarvis, "scratchpad_read", {}, SANDBOXED)

    await tools.execute(jarvis, "scratchpad_append", {"text": "waiting on codex"}, SANDBOXED)
    read = await tools.execute(jarvis, "scratchpad_read", {}, SANDBOXED)

    assert "waiting on codex" in read


async def test_scratchpad_entries_are_timestamped_and_accumulate(tools, jarvis):
    await tools.execute(jarvis, "scratchpad_append", {"text": "first"}, SANDBOXED)
    await tools.execute(jarvis, "scratchpad_append", {"text": "second"}, SANDBOXED)

    read = await tools.execute(jarvis, "scratchpad_read", {}, SANDBOXED)
    assert "first" in read and "second" in read
    assert read.count("- [") == 2


async def test_an_empty_append_is_refused_rather_than_silently_ignored(tools, jarvis):
    assert "error" in await tools.execute(jarvis, "scratchpad_append", {"text": "   "}, SANDBOXED)


async def test_memory_survives_and_can_be_listed_and_read_back(tools, jarvis):
    await tools.execute(jarvis, "memory_write",
                        {"name": "decision", "body": "we chose SQLite"}, SANDBOXED)

    listed = await tools.execute(jarvis, "memory_list", {}, SANDBOXED)
    assert "decision.md" in listed

    note = await tools.execute(jarvis, "memory_read", {"name": "decision"}, SANDBOXED)
    assert "we chose SQLite" in note
    assert "by: jarvis" in note, "a note should record who wrote it"


async def test_reading_a_missing_note_explains_itself(tools, jarvis):
    assert "no note called" in await tools.execute(
        jarvis, "memory_read", {"name": "nothing"}, SANDBOXED
    )


async def test_an_oversized_note_is_refused_with_the_limit(tools, jarvis):
    result = await tools.execute(
        jarvis, "memory_write", {"name": "huge", "body": "x" * 50_000}, SANDBOXED
    )
    assert "too long" in result


async def test_the_scratchpad_is_trimmed_rather_than_growing_without_bound(tools, jarvis):
    for _ in range(400):
        await tools.execute(jarvis, "scratchpad_append", {"text": "y" * 200}, SANDBOXED)

    read = await tools.execute(jarvis, "scratchpad_read", {}, SANDBOXED)
    assert len(read) < 60_000
    assert "older notes trimmed" in read
