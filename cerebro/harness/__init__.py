"""Cerebro Harness v1 — canonical contracts (Phase 1A).

Provider-neutral types for durable agent execution: identities, ordered inference items,
provider attempts, tool execution state, and the two adapter boundaries.

It now also includes the Phase 1C executable `StepSnapshot`, the frozen `ToolPlanSnapshot`
projection of current CoreTools/MCP exposure, the atomic pre-side-effect checkpoint, durable
raw/model tool-output separation, and a standalone tool-effect primitive.

That primitive can invoke an external tool, and deliberately nothing routes to it.
`RuntimeService`, `ChannelPoller` and `AgentRuntime` do not import `tool_runtime`; Phase 1D
establishes one execution authority per causal wake, and two authorities that could both
dispatch would be worse than anything this slice fixes. `cerebro.runtime.AgentRuntime` remains
the only active production execution path.

Deliberately absent, and owned by Phase 1D:

- the durable reducer and direct-provider cutover;
- the semantic provider retry/re-entry loop and cancellation orchestration;
- automatic recovery resumption of executable work;
- atomic product finalization.

`cerebro.harness.projection` is the one module that knows about collaboration `Message` rows.
Nothing else in the package imports them, so no canonical type depends on the product transcript.
"""

from cerebro.harness.artifacts import (
    ARTIFACT_RETENTION_POLICY,
    INLINE_THRESHOLD_BYTES,
    ArtifactStore,
    ArtifactWriteFailed,
    StagedArtifact,
    StoredArtifact,
)
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
from cerebro.harness.output_checkpoint import (
    OutputAdmission,
    ProviderOutputCoordinator,
    RejectedOutput,
)
from cerebro.harness.recovery import RecoveryDecision, TurnRecoveryDriver
from cerebro.harness.snapshot import (
    STEP_SNAPSHOT_FORMAT_VERSION,
    TOOL_PLAN_FORMAT_VERSION,
    StepSnapshot,
    ToolGrantEvidence,
    ToolPlanSnapshot,
)
from cerebro.harness.tool_gateway import CerebroToolGateway
from cerebro.harness.tool_plan import (
    CerebroToolCatalog,
    ToolCatalogEntry,
    ToolPlanSource,
    core_binding_generation,
    core_tool_key,
    mcp_binding_generation,
    mcp_tool_key,
    project_tool_plan,
    resolve_current_binding,
)
from cerebro.harness.tool_runtime import (
    MODEL_PROJECTION_LIMIT_CHARS,
    HarnessToolRuntime,
    KnownInvocation,
    ToolExecutorGateway,
    ToolInvocationRequest,
    ToolRuntimeOutcome,
    UnknownInvocation,
    project_model_visible,
)
from cerebro.harness.store import (
    ExecutableBarrierFacts,
    ExecutableCallCheckpoint,
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
    "ARTIFACT_RETENTION_POLICY",
    "AdapterCapabilities",
    "AgentTurn",
    "AgentTurnId",
    "AgentTurnLifecycle",
    "ArtifactRef",
    "ArtifactStore",
    "ArtifactWriteFailed",
    "AssistantTextDelta",
    "CancelToken",
    "CausalWakeKey",
    "CerebroCallId",
    "CerebroToolCatalog",
    "CerebroToolGateway",
    "ContentPart",
    "ContinuationNotAdmissible",
    "ConversationTurnId",
    "DuplicateHarnessIdentity",
    "ExecutableBarrierFacts",
    "ExecutableCallCheckpoint",
    "ExternalAgentAdapter",
    "ExternalAgentEvent",
    "ExternalExecutionId",
    "ExternalExecutionRequest",
    "ExternalPromptTurn",
    "ExternalRecoveryCapability",
    "HarnessError",
    "HarnessId",
    "HarnessMetadata",
    "HarnessRecordNotFound",
    "HarnessStateError",
    "HarnessStore",
    "HarnessToolRuntime",
    "INFERENCE_ATTEMPT_FORMAT_VERSION",
    "INFERENCE_ITEM_FORMAT_VERSION",
    "INLINE_THRESHOLD_BYTES",
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
    "KnownInvocation",
    "KnownResolution",
    "MODEL_PROJECTION_LIMIT_CHARS",
    "MediaPart",
    "MessageItem",
    "ModelProfile",
    "ModelProfileId",
    "OmissionMetadata",
    "OrphanReconciliation",
    "OutputAdmission",
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
    "ProviderOutputCoordinator",
    "ProviderRecoveryAction",
    "ReasoningPolicy",
    "ReasoningSummaryDelta",
    "ReasoningSummaryItem",
    "RecoveryDecision",
    "RejectedOutput",
    "ReplayRequirement",
    "ReplayRetentionScope",
    "ReplaySensitivity",
    "STEP_SNAPSHOT_FORMAT_VERSION",
    "SemanticRecoveryDisposition",
    "StagedArtifact",
    "StaleHarnessWrite",
    "StepSnapshot",
    "StepSnapshotId",
    "StepSnapshotIdentity",
    "StoredArtifact",
    "StoredInferenceAttempt",
    "StoredToolExecution",
    "TOOL_EXECUTION_FORMAT_VERSION",
    "TOOL_PLAN_FORMAT_VERSION",
    "TextPart",
    "TextToolInput",
    "ToolBinding",
    "ToolBindingGeneration",
    "ToolCallInputDelta",
    "ToolCallItem",
    "ToolCatalogEntry",
    "ToolDefinition",
    "ToolDispatchState",
    "ToolExecution",
    "ToolExecutorGateway",
    "ToolGrantEvidence",
    "ToolInput",
    "ToolInvocationRequest",
    "ToolKey",
    "ToolPlanSnapshot",
    "ToolPlanSource",
    "ToolPolicy",
    "ToolRecoveryCapability",
    "ToolResolution",
    "ToolResultItem",
    "ToolResultStatus",
    "ToolRuntimeOutcome",
    "TurnRecoveryDriver",
    "UnknownDialect",
    "UnknownInvocation",
    "UnsupportedDialectFeature",
    "UnsupportedFormatVersion",
    "UsageUpdate",
    "assert_continuation_admissible",
    "classify_recovery",
    "core_binding_generation",
    "core_tool_key",
    "is_authoritative",
    "mcp_binding_generation",
    "mcp_tool_key",
    "project_model_visible",
    "project_tool_plan",
    "provider_action_for",
    "request_semantic_hash",
    "resolve_current_binding",
]
