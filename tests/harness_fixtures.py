"""Shared builders for the Harness v1 contract tests.

Kept out of the test modules so a change to a canonical constructor is a one-line edit rather
than a sweep, and so each test reads as the invariant it is checking.
"""

from typing import Any, AsyncIterator

from cerebro.harness import (
    AgentTurnId,
    CerebroCallId,
    InferenceAttempt,
    InferenceAttemptId,
    InferenceItemId,
    JsonToolInput,
    MessageItem,
    ModelProfile,
    ModelProfileId,
    ProviderCallRef,
    ProviderConfig,
    ProviderConfigId,
    Provenance,
    StepSnapshotId,
    TextPart,
    ToolCallItem,
    ToolDefinition,
    ToolKey,
    ToolResultItem,
)
from cerebro.harness.adapters.openai_dialect import DIALECT_ID

PROVIDER_PROVENANCE = Provenance(source_kind="provider_attempt", source_id="lmstudio")
LOCAL_PROVENANCE = Provenance(source_kind="collaboration_message")


def tool_key(name: str = "fs_read") -> ToolKey:
    return ToolKey(source_type="core", source_id="core_tools", namespace="core", name=name)


def mcp_tool_key(server: str = "filesystem", name: str = "read_file") -> ToolKey:
    return ToolKey(source_type="mcp", source_id=server, namespace=server, name=name)


def tool_definition(key: ToolKey | None = None) -> ToolDefinition:
    return ToolDefinition(
        key=key or tool_key(),
        description="Read a file",
        input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
        provenance=LOCAL_PROVENANCE,
    )


def user_item(text: str, *, sequence_no: int | None = None) -> MessageItem:
    return MessageItem(
        item_id=InferenceItemId.generate(),
        origin="context_projection",
        sequence_no=sequence_no,
        role="user",
        content=[TextPart(text=text)],
        provenance=LOCAL_PROVENANCE,
    )


def assistant_item(
    text: str, attempt_id: InferenceAttemptId, *, sequence_no: int | None = None
) -> MessageItem:
    return MessageItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=attempt_id,
        sequence_no=sequence_no,
        role="assistant",
        content=[TextPart(text=text)],
        provenance=PROVIDER_PROVENANCE,
    )


def tool_call_item(
    attempt_id: InferenceAttemptId,
    *,
    native_call_id: str = "call_1",
    key: ToolKey | None = None,
    args: dict[str, Any] | None = None,
    call_id: CerebroCallId | None = None,
    sequence_no: int | None = None,
) -> ToolCallItem:
    return ToolCallItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=attempt_id,
        sequence_no=sequence_no,
        call_id=call_id or CerebroCallId.generate(),
        tool_key=key or tool_key(),
        input=JsonToolInput(value=args if args is not None else {"path": "notes.md"}),
        provider_ref=ProviderCallRef(
            provider_id="lmstudio", native_call_id=native_call_id, replay_required=True
        ),
    )


def tool_result_item(
    call: ToolCallItem, text: str = "ok", *, sequence_no: int | None = None
) -> ToolResultItem:
    return ToolResultItem(
        item_id=InferenceItemId.generate(),
        sequence_no=sequence_no,
        call_id=call.call_id,
        tool_key=call.tool_key,
        status="success",
        content=[TextPart(text=text)],
        provider_ref=call.provider_ref,
    )


def attempt(
    *,
    attempt_id: InferenceAttemptId | None = None,
    turn_id: AgentTurnId | None = None,
    snapshot_id: StepSnapshotId | None = None,
    generation: int = 1,
) -> InferenceAttempt:
    return InferenceAttempt(
        attempt_id=attempt_id or InferenceAttemptId.generate(),
        agent_turn_id=turn_id or AgentTurnId.generate(),
        step_snapshot_id=snapshot_id or StepSnapshotId.generate(),
        attempt_generation=generation,
        request_semantic_hash="0" * 64,
    )


def provider_config(dialect_id: str = DIALECT_ID) -> ProviderConfig:
    return ProviderConfig(
        config_id=ProviderConfigId.generate(),
        provider_id="lmstudio",
        endpoint="http://127.0.0.1:1234",
        dialect_id=dialect_id,
        dialect_version="2026-08-29",
        credential_reference="agent:jarvis:api_key",
    )


def model_profile(**overrides: Any) -> ModelProfile:
    defaults: dict[str, Any] = {
        "profile_id": ModelProfileId.generate(),
        "model_id": "gpt-oss-20b",
        "context_window_tokens": 32768,
        "usable_context_tokens": 24576,
        "max_output_tokens": 2048,
        "tool_calling_mode": "native",
        "reasoning_summary_support": "none",
        "opaque_replay_behavior": "none_required",
        "stateless_lossless_replay": True,
    }
    defaults.update(overrides)
    return ModelProfile(**defaults)


class FakeTransport:
    """Stands in for `OpenAICompatibleProvider` at the `stream_payload` seam.

    Records the payload it was handed so a test can assert on the exact wire shape, and replays a
    scripted delta sequence so streaming order is deterministic.
    """

    name = "lmstudio"

    def __init__(self, deltas: list[Any]) -> None:
        self.deltas = deltas
        self.payloads: list[dict[str, Any]] = []
        self.closed = False

    async def stream_payload(self, payload: dict[str, Any]) -> AsyncIterator[Any]:
        self.payloads.append(payload)
        for delta in self.deltas:
            yield delta

    async def aclose(self) -> None:
        self.closed = True
