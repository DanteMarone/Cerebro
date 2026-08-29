"""Compatibility projection: collaboration `Message` rows into canonical Harness state.

This module is the only place in the Harness that knows what a `Message` is. Everything above it
sees instructions and ordered items. That direction matters: `messages` is the product
transcript, and it is not, and must not become, the execution/replay log.

Two current behaviours are preserved exactly, because the models Cerebro runs today depend on
them:

- the agent's own past rows project to `assistant`, so it can tell what it already said;
- another agent's rows project to `user` prefixed with the speaker's id, so a room with three
  agents does not collapse into one anonymous voice.

Tool rounds are deliberately not projected from `messages`. A tool call and its result are
canonical Harness items with their own identity and their own durable execution state; rebuilding
them from `meta_json` would make the product transcript the source of execution truth again.
"""

from __future__ import annotations

from cerebro.harness.content import Instruction, Provenance, TextPart
from cerebro.harness.ids import AgentTurnId, InferenceItemId
from cerebro.harness.items import MessageItem
from cerebro.harness.tooling import ToolKey
from cerebro.models import Message

__all__ = [
    "project_history",
    "project_instructions",
    "tool_key_from_wire_name",
]


def _provenance(msg: Message) -> Provenance:
    return Provenance(
        source_kind="collaboration_message",
        source_id=str(msg.id) if msg.id is not None else None,
        author_id=msg.author_id,
        created_at=msg.created_at,
        metadata={"channel_id": msg.channel_id, "message_kind": msg.kind},
    )


def project_instructions(messages: list[Message]) -> list[Instruction]:
    """Take the system-authority rows out of a context packet.

    Current local-chat behaviour is a single leading system message. That is an adapter
    projection detail, not a canonical rule, so this returns however many the packet contains.
    """
    return [
        Instruction(
            authority="system",
            content=[TextPart(text=msg.body)],
            provenance=_provenance(msg),
        )
        for msg in messages
        if msg.author_kind == "system" and msg.kind == "system"
    ]


def project_history(
    messages: list[Message],
    self_id: str,
    *,
    agent_turn_id: AgentTurnId | None = None,
    start_sequence: int = 0,
) -> list[MessageItem]:
    """Project conversation rows into ordered canonical `MessageItem`s.

    Items are `context_projection` origin and carry no producing attempt: they came from product
    state, not from a provider. That is exactly the distinction AR-02 relies on when it decides
    which items an abandoned attempt may take with it.
    """
    items: list[MessageItem] = []
    sequence = start_sequence

    for msg in messages:
        if msg.author_kind == "system" and msg.kind == "system":
            continue
        if msg.kind == "tool":
            raise ValueError(
                "tool rows are not projected from collaboration messages; canonical tool calls "
                "and results are Harness items with their own identity and execution state"
            )

        if msg.author_kind == "agent" and msg.author_id == self_id:
            role = "assistant"
            body = msg.body
        else:
            role = "user"
            body = f"{msg.author_id}: {msg.body}" if msg.author_kind == "agent" else msg.body

        items.append(
            MessageItem(
                item_id=InferenceItemId.generate(),
                origin="context_projection",
                agent_turn_id=agent_turn_id,
                sequence_no=sequence,
                role=role,  # type: ignore[arg-type]
                content=[TextPart(text=body)],
                provenance=_provenance(msg),
            )
        )
        sequence += 1

    return items


def tool_key_from_wire_name(wire_name: str) -> ToolKey:
    """Map a current Cerebro tool name onto a canonical key.

    Mirrors what `CompositeToolExecutor` already does: `server__tool` is MCP, anything else is a
    core tool. Compatibility only — PR 3 builds keys from the frozen tool plan, where the source
    is known rather than inferred from punctuation.
    """
    if "__" in wire_name:
        server, name = wire_name.split("__", 1)
        return ToolKey(source_type="mcp", source_id=server, namespace=server, name=name)
    return ToolKey(
        source_type="core", source_id="core_tools", namespace="core", name=wire_name
    )
