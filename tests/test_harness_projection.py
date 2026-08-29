"""F-01: collaboration `Message` rows project into canonical instructions and items.

The point of these tests is that the projection preserves current authorship semantics exactly,
and that no provider tool protocol is required in `meta_json` to do it.
"""

import pytest

from cerebro.harness import AgentTurnId, ToolKey
from cerebro.harness.projection import (
    project_history,
    project_instructions,
    tool_key_from_wire_name,
)
from cerebro.models import Message
from cerebro.providers.openai_compatible import to_chat_messages


def _row(author_id: str, author_kind: str, body: str, kind: str = "chat", **extra) -> Message:
    return Message(
        channel_id="c1", author_id=author_id, author_kind=author_kind, kind=kind,
        body=body, **extra,
    )


def test_the_system_prompt_becomes_an_instruction_not_a_history_item():
    rows = [
        _row("system", "system", "You are Jarvis.", kind="system"),
        _row("dante", "user", "hello"),
    ]
    instructions = project_instructions(rows)
    items = project_history(rows, "jarvis")

    assert [i.authority for i in instructions] == ["system"]
    assert instructions[0].content[0].text == "You are Jarvis."
    assert [i.role for i in items] == ["user"]


def test_the_agents_own_rows_project_to_assistant():
    rows = [
        _row("dante", "user", "hello"),
        _row("jarvis", "agent", "hi"),
    ]
    items = project_history(rows, "jarvis")
    assert [i.role for i in items] == ["user", "assistant"]
    assert items[1].content[0].text == "hi"


def test_another_agents_rows_keep_their_speaker_label():
    """Three agents in a room must not collapse into one anonymous `user` voice."""
    rows = [_row("friday", "agent", "I looked already")]
    items = project_history(rows, "jarvis")
    assert items[0].role == "user"
    assert items[0].content[0].text == "friday: I looked already"


def test_projection_matches_the_current_wire_mapping():
    """The canonical projection produces the same text the live path already sends."""
    rows = [
        _row("system", "system", "You are Jarvis.", kind="system"),
        _row("dante", "user", "read notes.md"),
        _row("friday", "agent", "already did"),
        _row("jarvis", "agent", "on it"),
    ]
    current = to_chat_messages(rows, "jarvis")
    projected = [
        {"role": "system", "content": i.content[0].text} for i in project_instructions(rows)
    ] + [
        {"role": item.role, "content": item.content[0].text}
        for item in project_history(rows, "jarvis")
    ]
    assert projected == current


def test_projected_items_are_ordered_and_carry_no_producing_attempt():
    rows = [_row("dante", "user", "one"), _row("dante", "user", "two")]
    items = project_history(rows, "jarvis", agent_turn_id=AgentTurnId.generate())
    assert [i.sequence_no for i in items] == [0, 1]
    assert all(i.origin == "context_projection" for i in items)
    assert all(i.producing_attempt_id is None for i in items)
    assert all(i.agent_turn_id is not None for i in items)


def test_tool_rows_are_not_projected_from_the_product_transcript():
    """Tool calls and results are Harness items; rebuilding them from meta_json is the old way."""
    rows = [_row("tool", "system", "result body", kind="tool", meta_json='{"tool_call_id": "x"}')]
    with pytest.raises(ValueError, match="own identity"):
        project_history(rows, "jarvis")


def test_wire_tool_names_map_onto_canonical_keys():
    assert tool_key_from_wire_name("fs_read") == ToolKey(
        source_type="core", source_id="core_tools", namespace="core", name="fs_read"
    )
    assert tool_key_from_wire_name("filesystem__read_file") == ToolKey(
        source_type="mcp", source_id="filesystem", namespace="filesystem", name="read_file"
    )
