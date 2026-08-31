"""OpenAI chat-completions wire translation.

Every OpenAI-shaped concept — chat roles, `tool_calls`, `tool_call_id`, the assistant-then-tool
sequence — lives in this module and nowhere else. Generic Harness code works in canonical items
and has never heard of any of it.

The wire rules encoded here are the ones the current LM Studio/OpenAI-compatible path already
depends on: a tool round is one assistant turn carrying `tool_calls`, then one `tool` turn per
call carrying the matching `tool_call_id`. Anything this dialect cannot express is refused
explicitly. A dialect that silently drops what it cannot encode produces a request the model
answers confidently and wrongly.
"""

from __future__ import annotations

from typing import Any, Iterable

from pydantic import BaseModel

from cerebro.harness.content import Instruction, TextPart, text_of
from cerebro.harness.exceptions import UnsupportedDialectFeature
from cerebro.harness.tooling import (
    JsonToolInput,
    TextToolInput,
    ToolDefinition,
    ToolKey,
)

__all__ = [
    "DIALECT_ID",
    "DIALECT_VERSION",
    "OpenAIDialectOptions",
    "UNRESOLVED_TOOL_NAMESPACE",
    "UNRESOLVED_TOOL_SOURCE_ID",
    "is_unresolved_tool_key",
    "tool_key_for_wire_name",
    "to_wire_messages",
    "to_wire_tools",
    "unresolved_tool_key",
    "wire_name_for_tool_key",
]

DIALECT_ID = "openai.chat_completions"
DIALECT_VERSION = "2026-08-29"

# Reserved coordinates for a tool the model named but the frozen plan does not contain. A
# hallucinated name has to stay representable and stay obviously unbound: fabricating a plausible
# ToolKey would let it collide with a real binding later.
UNRESOLVED_TOOL_SOURCE_ID = "provider_wire"
UNRESOLVED_TOOL_NAMESPACE = "unresolved"


class OpenAIDialectOptions(BaseModel):
    """Dialect assumptions, stated rather than assumed.

    `supports_developer_role` is the one that matters in practice. The OpenAI Responses API has a
    developer authority; the chat-completions servers Cerebro talks to today do not, and LM Studio
    will happily accept a `developer` role and ignore it. Making the fallback a declared option
    means a future endpoint that does support it changes one flag instead of inheriting a silent
    downgrade.
    """

    model_config = {"frozen": True}

    supports_developer_role: bool = False
    developer_instruction_fallback: str = "system"
    supports_reasoning_replay: bool = False
    emit_empty_assistant_turns: bool = False


def unresolved_tool_key(wire_name: str) -> ToolKey:
    return ToolKey(
        source_type="extension",
        source_id=UNRESOLVED_TOOL_SOURCE_ID,
        namespace=UNRESOLVED_TOOL_NAMESPACE,
        name=wire_name,
    )


def is_unresolved_tool_key(key: ToolKey) -> bool:
    return (
        key.source_id == UNRESOLVED_TOOL_SOURCE_ID
        and key.namespace == UNRESOLVED_TOOL_NAMESPACE
    )


def wire_name_for_tool_key(key: ToolKey) -> str:
    """The name this dialect puts on the wire for a canonical tool key.

    Mirrors the names Cerebro already exposes: bare for core tools, `server__tool` for MCP. The
    mapping is one-way information: the wire name is a serialization detail, and the canonical
    key stays the identity.
    """
    if is_unresolved_tool_key(key):
        return key.name
    if key.source_type == "mcp":
        return f"{key.source_id}__{key.name}"
    return key.name


def tool_key_for_wire_name(wire_name: str, wire_tool_names: dict[str, str]) -> ToolKey:
    """Resolve a streamed wire name back to the canonical key it was offered under.

    The frozen plan is the authority. A name that is not in it resolves to an unresolved key,
    which the tool runtime later resolves as unavailable — the truthful outcome for a tool the
    model invented.
    """
    canonical = wire_tool_names.get(wire_name)
    if canonical is None:
        return unresolved_tool_key(wire_name)
    return ToolKey.parse(canonical)


def to_wire_tools(tools: Iterable[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": wire_name_for_tool_key(tool.key),
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def _instruction_role(instruction: Instruction, options: OpenAIDialectOptions) -> str:
    if instruction.authority == "system":
        return "system"
    if options.supports_developer_role:
        return "developer"
    if options.developer_instruction_fallback == "system":
        return "system"
    raise UnsupportedDialectFeature(
        f"{DIALECT_ID} has no developer authority and the configured fallback is "
        f"{options.developer_instruction_fallback!r}"
    )


def _wire_content(content: list[Any]) -> str:
    """Flatten canonical content for a dialect whose message content is a string.

    JSON and media parts are refused rather than stringified. A base64 blob pasted into a text
    field is not multimodal input; it is a very long word.
    """
    for part in content:
        if not isinstance(part, TextPart):
            raise UnsupportedDialectFeature(
                f"{DIALECT_ID} message content accepts text parts only; got "
                f"{getattr(part, 'part_type', type(part).__name__)!r}"
            )
    return text_of(content)


def _tool_call_arguments(item: Any) -> str:
    from cerebro.harness.serialization import canonical_json

    tool_input = item.input
    if isinstance(tool_input, JsonToolInput):
        return canonical_json(tool_input.value)
    if isinstance(tool_input, TextToolInput):
        # Preserved verbatim. The model produced this text; re-encoding it would either hide a
        # malformed-arguments bug or invent arguments the model never sent.
        return tool_input.text
    raise UnsupportedDialectFeature(
        f"{DIALECT_ID} tool arguments must be JSON or text; got "
        f"{getattr(tool_input, 'input_form', type(tool_input).__name__)!r}"
    )


def _native_call_id(item: Any, known: dict[str, str]) -> str:
    """The provider-owned id this dialect requires on the wire.

    Never derived from `CerebroCallId`. If the provider never issued a ref, the harness has
    nothing valid to send and says so, rather than passing off a Cerebro identity as a provider
    one.
    """
    ref = item.provider_ref
    if ref is not None and ref.native_call_id:
        return ref.native_call_id
    inherited = known.get(str(item.call_id))
    if inherited:
        return inherited
    raise UnsupportedDialectFeature(
        f"{DIALECT_ID} requires a provider-issued tool_call_id for call "
        f"{str(item.call_id)!r}; no ProviderCallRef is recorded and a CerebroCallId is not a "
        f"substitute"
    )


def to_wire_messages(
    instructions: list[Instruction],
    history: list[Any],
    *,
    options: OpenAIDialectOptions | None = None,
) -> list[dict[str, Any]]:
    """Render canonical instructions and ordered items as chat-completions messages.

    Superseded items are the caller's business to exclude; this function renders what it is
    given, so a test can prove the filter happened upstream.
    """
    opts = options or OpenAIDialectOptions()
    out: list[dict[str, Any]] = []

    for instruction in instructions:
        out.append(
            {
                "role": _instruction_role(instruction, opts),
                "content": _wire_content(instruction.content),
            }
        )

    pending_text: str | None = None
    pending_attempt: Any = None
    pending_calls: list[dict[str, Any]] = []
    native_ids: dict[str, str] = {}

    def flush() -> None:
        nonlocal pending_text, pending_attempt, pending_calls
        if pending_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": pending_text or None,
                    "tool_calls": pending_calls,
                }
            )
        elif pending_text is not None and (pending_text.strip() or opts.emit_empty_assistant_turns):
            out.append({"role": "assistant", "content": pending_text})
        pending_text = None
        pending_attempt = None
        pending_calls = []

    for item in history:
        kind = item.item_type

        if kind == "message" and item.role == "assistant":
            flush()
            pending_text = _wire_content(item.content)
            pending_attempt = item.producing_attempt_id
            continue

        if kind == "tool_call":
            # A call joins the assistant turn that produced it. A call from a different attempt
            # starts its own turn, so two attempts never merge into one wire message.
            if pending_calls and pending_attempt != item.producing_attempt_id:
                flush()
            elif pending_text is not None and pending_attempt != item.producing_attempt_id:
                flush()
            native = _native_call_id(item, native_ids)
            native_ids[str(item.call_id)] = native
            pending_attempt = item.producing_attempt_id
            pending_calls.append(
                {
                    "id": native,
                    "type": "function",
                    "function": {
                        "name": wire_name_for_tool_key(item.tool_key),
                        "arguments": _tool_call_arguments(item) or "{}",
                    },
                }
            )
            continue

        flush()

        if kind == "message":
            out.append({"role": "user", "content": _wire_content(item.content)})
            continue

        if kind == "tool_result":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": _native_call_id(item, native_ids),
                    "content": _wire_content(item.content),
                }
            )
            continue

        if kind == "reasoning_summary":
            # Chat completions has no slot for it and never requires it back. Dropping it here is
            # a stated dialect decision, not an oversight: it is a summary, not replay state.
            continue

        if kind == "provider_opaque":
            raise UnsupportedDialectFeature(
                f"{DIALECT_ID} carries no provider-opaque replay material; item "
                f"{str(item.item_id)!r} (kind={item.kind!r}) cannot be replayed through this "
                f"dialect"
            )

        raise UnsupportedDialectFeature(f"{DIALECT_ID} cannot render item type {kind!r}")

    flush()
    return out
