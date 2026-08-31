"""Canonical inference stream events.

Deltas exist for the user interface and for parser progress. `OutputItemCompleted` is the only
semantic authority. No delta may enter durable history, authorise a tool, satisfy a completion
policy, or stand in for a native call reference that has not arrived yet.

That distinction is enforced by the types themselves: a delta carries text or a fragment, and no
delta carries an `InferenceItem`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from cerebro.harness.attempts import InferenceCompletionStatus
from cerebro.harness.errors import InferenceError
from cerebro.harness.ids import InferenceAttemptId
from cerebro.harness.items import InferenceItem

__all__ = [
    "AssistantTextDelta",
    "InferenceCompleted",
    "InferenceEvent",
    "InferenceFailed",
    "InferenceStarted",
    "OutputItemCompleted",
    "OutputItemStarted",
    "ProviderMetadata",
    "ReasoningSummaryDelta",
    "ToolCallInputDelta",
    "UsageUpdate",
    "is_authoritative",
]


class _AttemptScoped(BaseModel):
    """Every event names the attempt it came from, so a late one can be fenced."""

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    attempt_id: InferenceAttemptId


class InferenceStarted(_AttemptScoped):
    event_type: Literal["inference_started"] = "inference_started"


class OutputItemStarted(_AttemptScoped):
    event_type: Literal["output_item_started"] = "output_item_started"
    item_index: int
    item_type: str


class AssistantTextDelta(_AttemptScoped):
    event_type: Literal["assistant_text_delta"] = "assistant_text_delta"
    text: str


class ReasoningSummaryDelta(_AttemptScoped):
    event_type: Literal["reasoning_summary_delta"] = "reasoning_summary_delta"
    summary_fragment: str


class ToolCallInputDelta(_AttemptScoped):
    """A fragment of a tool call being assembled. Never executable."""

    event_type: Literal["tool_call_input_delta"] = "tool_call_input_delta"
    call_index: int
    provider_native_call_id: str | None = None
    tool_wire_name: str | None = None
    arguments_fragment: str = ""


class OutputItemCompleted(_AttemptScoped):
    """The authoritative event. Carries a finalized canonical item."""

    event_type: Literal["output_item_completed"] = "output_item_completed"
    item: InferenceItem


class UsageUpdate(_AttemptScoped):
    event_type: Literal["usage_update"] = "usage_update"
    input_tokens: int = 0
    output_tokens: int = 0


class ProviderMetadata(_AttemptScoped):
    event_type: Literal["provider_metadata"] = "provider_metadata"
    metadata: dict[str, Any] = Field(default_factory=dict)


class InferenceCompleted(_AttemptScoped):
    """Provider-side completion. Not Cerebro turn completion, and not product acceptance."""

    event_type: Literal["inference_completed"] = "inference_completed"
    status: InferenceCompletionStatus
    provider_request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InferenceFailed(_AttemptScoped):
    event_type: Literal["inference_failed"] = "inference_failed"
    error: InferenceError


InferenceEvent = Annotated[
    Union[
        InferenceStarted,
        OutputItemStarted,
        AssistantTextDelta,
        ReasoningSummaryDelta,
        ToolCallInputDelta,
        OutputItemCompleted,
        UsageUpdate,
        ProviderMetadata,
        InferenceCompleted,
        InferenceFailed,
    ],
    Field(discriminator="event_type"),
]


def is_authoritative(event: Any) -> bool:
    """Whether an event may change durable semantic history.

    Used by generic code so the rule lives in one place rather than in every consumer's
    `isinstance` chain.
    """
    return isinstance(event, (OutputItemCompleted, InferenceCompleted, InferenceFailed))
