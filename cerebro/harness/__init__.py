"""Cerebro Harness v1 — canonical contracts (Phase 1A).

Provider-neutral types for durable agent execution: identities, ordered inference items,
provider attempts, tool execution state, and the two adapter boundaries.

This package now includes the additive Phase 1B durable store and conservative recovery scan. It
still does not execute providers or tools. The live production path is `cerebro.runtime`, whose
behaviour this slice deliberately leaves untouched.

Deliberately absent, and owned by later slices:

- `StepSnapshot` and the tool-plan projection (PR 3);
- the pre-side-effect checkpoint transaction (PR 3);
- the reducer/effect cutover and atomic finalization (PR 4/5).

`cerebro.harness.projection` is the one module that knows about collaboration `Message` rows.
Nothing else in the package imports them, so no canonical type depends on the product transcript.
"""

from cerebro.harness.attempts import (
    INFERENCE_ATTEMPT_FORMAT_VERSION,
    InferenceAttempt,
    InferenceCompletionStatus,
    ProviderAttemptSemanticState,
    ProviderDispatchState,
)
from cerebro.harness.content import (
    ContentPart,
    Instruction,
    JsonPart,
    MediaPart,
    OmissionMetadata,
    Provenance,
    TextPart,
)
from cerebro.harness.errors import (
    InferenceError,
    InferenceErrorKind,
    ProviderRecoveryAction,
    SemanticRecoveryDisposition,
    classify_recovery,
    provider_action_for,
)
from cerebro.harness.events import (
    AssistantTextDelta,
    InferenceCompleted,
    InferenceEvent,
    InferenceFailed,
    InferenceStarted,
    OutputItemCompleted,
    OutputItemStarted,
    ProviderMetadata,
    ReasoningSummaryDelta,
    ToolCallInputDelta,
    UsageUpdate,
    is_authoritative,
)
from cerebro.harness.exceptions import (
    ContinuationNotAdmissible,
    DuplicateHarnessIdentity,
    HarnessError,
    HarnessRecordNotFound,
    HarnessStateError,
    StaleHarnessWrite,
    UnknownDialect,
    UnsupportedDialectFeature,
    UnsupportedFormatVersion,
)
from cerebro.harness.execution import (
    TOOL_EXECUTION_FORMAT_VERSION,
    IndeterminateResolution,
    KnownResolution,
    ToolDispatchState,
    ToolExecution,
    ToolResolution,
)
from cerebro.harness.external_agent import (
    ExternalAgentAdapter,
    ExternalAgentEvent,
    ExternalExecutionRequest,
    ExternalPromptTurn,
    ExternalRecoveryCapability,
    OrphanReconciliation,
)
from cerebro.harness.history import InferenceHistory
from cerebro.harness.ids import (
    AgentTurnId,
    ArtifactRef,
    CerebroCallId,
    ConversationTurnId,
    ExternalExecutionId,
    HarnessId,
    InferenceAttemptId,
    InferenceItemId,
    InvalidHarnessId,
    ModelProfileId,
    ProviderConfigId,
    StepSnapshotId,
    ToolBindingGeneration,
)
from cerebro.harness.items import (
    INFERENCE_ITEM_FORMAT_VERSION,
    InferenceItem,
    ItemOrigin,
    MessageItem,
    ProviderOpaqueItem,
    ReasoningSummaryItem,
    ReplayRequirement,
    ReplayRetentionScope,
    ReplaySensitivity,
    ToolCallItem,
    ToolResultItem,
)
from cerebro.harness.model_profile import ModelProfile, ProviderConfig
from cerebro.harness.provider_adapter import (
    AdapterCapabilities,
    CancelToken,
    PreparedProviderRequest,
    ProviderAdapter,
    assert_continuation_admissible,
)
from cerebro.harness.provider_ref import ProviderCallRef
from cerebro.harness.request import (
    InferenceRequest,
    OutputPolicy,
    ReasoningPolicy,
    ToolPolicy,
    request_semantic_hash,
)
from cerebro.harness.recovery import RecoveryDecision, TurnRecoveryDriver
from cerebro.harness.store import (
    HarnessMetadata,
    HarnessStore,
    StepSnapshotIdentity,
    StoredInferenceAttempt,
    StoredToolExecution,
)
from cerebro.harness.tooling import (
    JsonToolInput,
    ProviderOpaqueToolInput,
    TextToolInput,
    ToolBinding,
    ToolDefinition,
    ToolInput,
    ToolKey,
    ToolRecoveryCapability,
    ToolResultStatus,
)
from cerebro.harness.turn import (
    AGENT_TURN_FORMAT_VERSION,
    AgentTurn,
    AgentTurnLifecycle,
    ProductOutcomeKind,
)
from cerebro.harness.wake import CausalWakeKey

__all__ = [
    "AGENT_TURN_FORMAT_VERSION",
    "INFERENCE_ATTEMPT_FORMAT_VERSION",
    "INFERENCE_ITEM_FORMAT_VERSION",
    "TOOL_EXECUTION_FORMAT_VERSION",
    "AdapterCapabilities",
    "AgentTurn",
    "AgentTurnId",
    "AgentTurnLifecycle",
    "ArtifactRef",
    "AssistantTextDelta",
    "CancelToken",
    "CausalWakeKey",
    "CerebroCallId",
    "ContentPart",
    "ContinuationNotAdmissible",
    "ConversationTurnId",
    "DuplicateHarnessIdentity",
    "ExternalAgentAdapter",
    "ExternalAgentEvent",
    "ExternalExecutionId",
    "ExternalExecutionRequest",
    "ExternalPromptTurn",
    "ExternalRecoveryCapability",
    "HarnessError",
    "HarnessMetadata",
    "HarnessRecordNotFound",
    "HarnessId",
    "HarnessStateError",
    "HarnessStore",
    "IndeterminateResolution",
    "InferenceAttempt",
    "InferenceAttemptId",
    "InferenceCompleted",
    "InferenceCompletionStatus",
    "InferenceError",
    "InferenceErrorKind",
    "InferenceEvent",
    "InferenceFailed",
    "InferenceHistory",
    "InferenceItem",
    "InferenceItemId",
    "InferenceRequest",
    "InferenceStarted",
    "Instruction",
    "InvalidHarnessId",
    "ItemOrigin",
    "JsonPart",
    "JsonToolInput",
    "KnownResolution",
    "MediaPart",
    "MessageItem",
    "ModelProfile",
    "ModelProfileId",
    "OmissionMetadata",
    "OrphanReconciliation",
    "OutputItemCompleted",
    "OutputItemStarted",
    "OutputPolicy",
    "PreparedProviderRequest",
    "ProductOutcomeKind",
    "Provenance",
    "ProviderAdapter",
    "ProviderAttemptSemanticState",
    "ProviderCallRef",
    "ProviderConfig",
    "ProviderConfigId",
    "ProviderDispatchState",
    "ProviderMetadata",
    "ProviderOpaqueItem",
    "ProviderOpaqueToolInput",
    "ProviderRecoveryAction",
    "ReasoningPolicy",
    "ReasoningSummaryDelta",
    "ReasoningSummaryItem",
    "RecoveryDecision",
    "ReplayRequirement",
    "ReplayRetentionScope",
    "ReplaySensitivity",
    "SemanticRecoveryDisposition",
    "StepSnapshotId",
    "StepSnapshotIdentity",
    "StaleHarnessWrite",
    "StoredInferenceAttempt",
    "StoredToolExecution",
    "TextPart",
    "TextToolInput",
    "ToolBinding",
    "ToolBindingGeneration",
    "ToolCallInputDelta",
    "ToolCallItem",
    "ToolDefinition",
    "ToolDispatchState",
    "ToolExecution",
    "ToolInput",
    "ToolKey",
    "ToolPolicy",
    "ToolRecoveryCapability",
    "ToolResolution",
    "ToolResultItem",
    "ToolResultStatus",
    "TurnRecoveryDriver",
    "UnknownDialect",
    "UnsupportedDialectFeature",
    "UnsupportedFormatVersion",
    "UsageUpdate",
    "assert_continuation_admissible",
    "classify_recovery",
    "is_authoritative",
    "provider_action_for",
    "request_semantic_hash",
]
