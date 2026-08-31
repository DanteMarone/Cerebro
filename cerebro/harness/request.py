"""`InferenceRequest` and its semantic hash.

The request separates three kinds of state that look similar and behave differently:

- `provider_options` are semantic. They change what the model does and are frozen in the step
  snapshot;
- `cache_hints` are performance state. Losing them must never change an answer;
- required replay material lives in the ordered history and in `ProviderCallRef`s, never here.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from cerebro.harness.content import Instruction
from cerebro.harness.ids import ModelProfileId, ProviderConfigId, StepSnapshotId
from cerebro.harness.items import InferenceItem
from cerebro.harness.tooling import ToolDefinition

__all__ = [
    "InferenceRequest",
    "OutputPolicy",
    "ReasoningPolicy",
    "ToolChoice",
    "ToolPolicy",
    "request_semantic_hash",
]

ToolChoice = Literal["auto", "none", "required"]


class ToolPolicy(BaseModel):
    model_config = {"frozen": True}

    choice: ToolChoice = "auto"
    allow_parallel_calls: bool = False
    max_calls_per_step: int | None = None


class ReasoningPolicy(BaseModel):
    model_config = {"frozen": True}

    effort: str | None = None
    request_summary: bool = False


class OutputPolicy(BaseModel):
    model_config = {"frozen": True}

    temperature: float = 0.7
    max_output_tokens: int | None = None
    stop: list[str] | None = None
    structured_output_schema: dict[str, Any] | None = None


class InferenceRequest(BaseModel):
    """What one provider step is asking for, in canonical terms only."""

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    step_snapshot_id: StepSnapshotId
    provider_config_ref: ProviderConfigId
    model_profile_ref: ModelProfileId

    instructions: list[Instruction] = Field(default_factory=list)
    history: list[InferenceItem] = Field(default_factory=list)
    tools: list[ToolDefinition] = Field(default_factory=list)

    tool_policy: ToolPolicy = Field(default_factory=ToolPolicy)
    reasoning_policy: ReasoningPolicy | None = None
    output_policy: OutputPolicy = Field(default_factory=OutputPolicy)

    trace_metadata: dict[str, str] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)
    cache_hints: dict[str, Any] = Field(default_factory=dict)


def request_semantic_hash(request: InferenceRequest) -> str:
    """A stable hash of the parts of a request that change the answer.

    `trace_metadata` and `cache_hints` are excluded on purpose: a new trace id or a lost cache
    handle must not make recovery think it is looking at a different request.
    """
    payload = request.model_dump(mode="json", exclude={"trace_metadata", "cache_hints"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
