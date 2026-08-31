"""Builders and fakes for the Phase 1C snapshot/checkpoint/tool-runtime fixtures.

Every adversarial test here drives fake catalogues and fake executors. Nothing in this module
reaches a paid provider, a real MCP subprocess or the production runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cerebro.harness import (
    AgentTurn,
    AgentTurnId,
    CausalWakeKey,
    CerebroCallId,
    ConversationTurnId,
    InferenceAttempt,
    InferenceAttemptId,
    InferenceItemId,
    JsonToolInput,
    ModelProfileId,
    OutputItemCompleted,
    ProviderCallRef,
    ProviderConfigId,
    ProviderOpaqueItem,
    ProviderOutputCoordinator,
    Provenance,
    StepSnapshot,
    StepSnapshotId,
    ToolBindingGeneration,
    ToolCallItem,
    ToolCatalogEntry,
    ToolGrantEvidence,
    ToolKey,
    ToolRecoveryCapability,
    project_tool_plan,
)
from cerebro.harness.store import HarnessStore
from cerebro.harness.tool_runtime import (
    KnownInvocation,
    ToolInvocationRequest,
    UnknownInvocation,
)
from cerebro.harness.tooling import ToolBinding, ToolDefinition

NOW = "2026-08-31T10:00:00+00:00"
LATER = "2026-08-31T10:01:00+00:00"

CATALOG_VERSION = 41
POLICY_VERSION = 7

SIDE_EFFECTING = ToolRecoveryCapability(
    effect_class="side_effecting", repeat_semantics="never_automatic_repeat"
)
IDEMPOTENT = ToolRecoveryCapability(
    effect_class="read_only", repeat_semantics="idempotent"
)
KEYED = ToolRecoveryCapability(
    effect_class="side_effecting",
    repeat_semantics="stable_idempotency_key",
    operation_key_policy="idempotency_key",
)
RECONCILABLE = ToolRecoveryCapability(
    effect_class="side_effecting",
    repeat_semantics="reconcile_before_repeat",
    reconciliation_binding="payments.lookup_by_operation_key",
)


def mcp_key(server: str = "payments", name: str = "charge") -> ToolKey:
    return ToolKey(source_type="mcp", source_id=server, namespace=server, name=name)


def catalog_entry(
    key: ToolKey,
    *,
    generation: str,
    capability: ToolRecoveryCapability = SIDE_EFFECTING,
    catalog_version: int = CATALOG_VERSION,
    policy_version: int = POLICY_VERSION,
    wire_name: str | None = None,
    schema: dict[str, Any] | None = None,
) -> ToolCatalogEntry:
    """One offered tool with an explicit binding generation, for deterministic arms."""
    input_schema = schema or {"type": "object", "properties": {"amount": {"type": "number"}}}
    return ToolCatalogEntry(
        key=key,
        wire_name=wire_name or f"{key.namespace}__{key.name}",
        definition=ToolDefinition(
            key=key,
            description=f"{key.name} tool",
            input_schema=input_schema,
            provenance=Provenance(source_kind="test_catalog", source_id=key.source_id),
        ),
        binding=ToolBinding(
            key=key,
            executor_identity=f"test/{key.canonical()}/{generation}",
            binding_generation=ToolBindingGeneration(f"tbg_{generation}"),
            catalog_version=catalog_version,
            policy_version=policy_version,
            recovery_capability=capability,
        ),
        grant=ToolGrantEvidence(
            grant_id=f"grant:{key.canonical()}",
            policy_version=policy_version,
            trust_tier="standard",
            reason="test fixture grant",
        ),
    )


class FakeToolCatalog:
    """A mutable `ToolPlanSource` whose entries a test can replace, remove or revoke."""

    def __init__(
        self,
        entries: list[ToolCatalogEntry],
        *,
        catalog_version: int = CATALOG_VERSION,
        policy_version: int = POLICY_VERSION,
    ) -> None:
        self._entries = list(entries)
        self._catalog_version = catalog_version
        self._policy_version = policy_version

    def catalog_version(self) -> int:
        return self._catalog_version

    def policy_version(self) -> int:
        return self._policy_version

    def entries(self) -> list[ToolCatalogEntry]:
        return list(self._entries)

    # -- test manipulation ----------------------------------------------------------

    def replace(self, key: ToolKey, entry: ToolCatalogEntry) -> None:
        """Swap the live binding for one key, dropping the previous generation entirely."""
        self._entries = [item for item in self._entries if item.key != key] + [entry]

    def add(self, entry: ToolCatalogEntry) -> None:
        """Offer an additional generation alongside the existing one."""
        self._entries.append(entry)

    def remove(self, key: ToolKey) -> None:
        self._entries = [item for item in self._entries if item.key != key]

    def revoke_grant(self, policy_version: int) -> None:
        """Advance the grant policy version without changing any binding generation.

        Mirrors a real tier or glob change: the executor behind the tool is the same process,
        so its generation is unchanged, but the permission decision that offered it is not.
        """
        self._policy_version = policy_version
        self._entries = [
            ToolCatalogEntry(
                key=item.key,
                wire_name=item.wire_name,
                definition=item.definition,
                binding=item.binding.model_copy(update={"policy_version": policy_version}),
                grant=ToolGrantEvidence(
                    grant_id=item.grant.grant_id,
                    policy_version=policy_version,
                    trust_tier=item.grant.trust_tier,
                    reason="revoked in test",
                ),
            )
            for item in self._entries
        ]


@dataclass
class RecordedInvocation:
    call_id: str
    executor_identity: str
    binding_generation: str
    stable_operation_key: str | None
    attempt_number: int
    arguments: Any


class FakeExecutorGateway:
    """Records every invocation per binding generation and replays scripted outcomes."""

    def __init__(
        self,
        outcomes: list[Any] | None = None,
        *,
        reconcile_outcome: Any | None = None,
    ) -> None:
        self.outcomes = list(outcomes or [KnownInvocation(raw_output="ok")])
        self.reconcile_outcome = reconcile_outcome
        self.invocations: list[RecordedInvocation] = []
        self.reconciliations: list[RecordedInvocation] = []
        self.raise_on_invoke: Exception | None = None

    def count_for(self, generation: str) -> int:
        marker = f"tbg_{generation}"
        return len([call for call in self.invocations if call.binding_generation == marker])

    def _record(self, request: ToolInvocationRequest) -> RecordedInvocation:
        return RecordedInvocation(
            call_id=str(request.call_id),
            executor_identity=request.binding.executor_identity,
            binding_generation=str(request.binding.binding_generation),
            stable_operation_key=request.stable_operation_key,
            attempt_number=request.attempt_number,
            arguments=request.arguments,
        )

    async def invoke(self, request: ToolInvocationRequest) -> Any:
        self.invocations.append(self._record(request))
        if self.raise_on_invoke is not None:
            raise self.raise_on_invoke
        index = min(len(self.invocations) - 1, len(self.outcomes) - 1)
        return self.outcomes[index]

    async def reconcile(self, request: ToolInvocationRequest) -> Any | None:
        self.reconciliations.append(self._record(request))
        return self.reconcile_outcome


class KeyedRemote:
    """A fake remote that enforces idempotency by operation key and loses one response."""

    def __init__(self, *, lose_first_response: bool = True) -> None:
        self.mutations: list[str] = []
        self.lose_first_response = lose_first_response
        self.invocations: list[RecordedInvocation] = []

    def count_for(self, generation: str) -> int:
        marker = f"tbg_{generation}"
        return len([call for call in self.invocations if call.binding_generation == marker])

    async def invoke(self, request: ToolInvocationRequest) -> Any:
        self.invocations.append(
            RecordedInvocation(
                call_id=str(request.call_id),
                executor_identity=request.binding.executor_identity,
                binding_generation=str(request.binding.binding_generation),
                stable_operation_key=request.stable_operation_key,
                attempt_number=request.attempt_number,
                arguments=request.arguments,
            )
        )
        key = request.stable_operation_key
        assert key, "the fake remote refuses a mutation with no idempotency key"
        first_time = key not in self.mutations
        if first_time:
            self.mutations.append(key)
            if self.lose_first_response:
                return UnknownInvocation(reason="response lost after the remote committed")
        return KnownInvocation(raw_output=f"charged under {key}")


@dataclass
class ExecutableFixture:
    """One turn carried all the way to a committed executable pre-side-effect checkpoint."""

    store: HarnessStore
    catalog: FakeToolCatalog
    turn: AgentTurn
    snapshot: StepSnapshot
    attempt: InferenceAttempt
    call_items: list[ToolCallItem] = field(default_factory=list)
    call_ids: list[CerebroCallId] = field(default_factory=list)

    @property
    def call_item(self) -> ToolCallItem:
        return self.call_items[0]

    @property
    def call_id(self) -> CerebroCallId:
        return self.call_ids[0]

    async def reload(self) -> AgentTurn:
        self.turn = await self.store.get_turn(self.turn.id)
        return self.turn


def make_turn(*, occurrence: str, created_at: str = NOW) -> AgentTurn:
    wake = CausalWakeKey(
        wake_kind="explicit_turn",
        target_agent_id="jarvis",
        channel_id="channel-1",
        occurrence_id=occurrence,
    )
    return AgentTurn(
        id=AgentTurnId.generate(),
        conversation_turn_id=ConversationTurnId.generate(),
        causal_wake_key=wake,
        channel_id="channel-1",
        agent_id="jarvis",
        created_at=created_at,
        updated_at=created_at,
    )


def build_snapshot(
    turn: AgentTurn,
    catalog: FakeToolCatalog,
    *,
    security_revocation_epoch: int,
    history_version: int,
    replay_version: int,
    step_index: int = 0,
    **overrides: Any,
) -> StepSnapshot:
    """A complete executable snapshot frozen against the current catalogue."""
    payload: dict[str, Any] = {
        "snapshot_id": StepSnapshotId.generate(),
        "agent_turn_id": turn.id,
        "step_index": step_index,
        "turn_version_at_creation": turn.state_version,
        "provider_config_id": ProviderConfigId.generate(),
        "provider_id": "lmstudio",
        "adapter_dialect": "openai_chat_completions",
        "adapter_dialect_version": "2026-08-29",
        "model_profile_id": ModelProfileId.generate(),
        "model_profile_version": 3,
        "provider_semantic_options": {"temperature": 0.2},
        "inference_history_version": history_version,
        "provider_replay_version": replay_version,
        "context_projection_version": 1,
        "token_budget": 24576,
        "tool_plan": project_tool_plan(
            catalog, security_revocation_epoch=security_revocation_epoch
        ),
        "permission_policy_version": catalog.policy_version(),
        "security_revocation_epoch": security_revocation_epoch,
        "workspace_ref": "workspace:default",
        "cwd": "D:/Code Projects/Cerebro/workspace",
        "environment_ref": "env:test",
        "environment_version": 2,
        "completion_policy_version": 1,
        "trace_metadata": {"trace_id": "trace-1"},
        "created_at": NOW,
    }
    payload.update(overrides)
    return StepSnapshot(**payload)


async def running_turn(
    store: HarnessStore, *, occurrence: str
) -> AgentTurn:
    turn = await store.admit_turn(make_turn(occurrence=occurrence))
    return await store.transition_turn(
        turn.id, expected_version=0, lifecycle="running", at=NOW
    )


async def snapshotted_turn(
    store: HarnessStore,
    catalog: FakeToolCatalog,
    *,
    occurrence: str,
    **overrides: Any,
) -> tuple[AgentTurn, StepSnapshot, InferenceAttempt]:
    """Turn -> running -> executable snapshot -> admitted active attempt."""
    turn = await running_turn(store, occurrence=occurrence)
    snapshot = build_snapshot(
        turn,
        catalog,
        security_revocation_epoch=await store.security_revocation_epoch(),
        history_version=await store.history_version(turn.conversation_turn_id),
        replay_version=await store.replay_version(turn.conversation_turn_id),
        **overrides,
    )
    snapshot, turn = await store.commit_step_snapshot(
        snapshot, expected_turn_version=turn.state_version
    )
    attempt = InferenceAttempt(
        attempt_id=InferenceAttemptId.generate(),
        agent_turn_id=turn.id,
        step_snapshot_id=snapshot.snapshot_id,
        turn_version_admitted=turn.state_version,
        request_semantic_hash="c" * 64,
    )
    _, turn = await store.admit_inference_attempt(
        attempt, expected_turn_version=turn.state_version, at=NOW
    )
    return turn, snapshot, attempt


def opaque_item(attempt: InferenceAttempt, *, kind: str = "reasoning_state") -> ProviderOpaqueItem:
    return ProviderOpaqueItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=attempt.attempt_id,
        provider_id="lmstudio",
        adapter_dialect="openai_chat_completions",
        kind=kind,
        exact_payload='{"state":"opaque"}',
        replay_requirement="required_for_correctness",
        retention_scope="current_turn",
    )


def tool_call(
    attempt: InferenceAttempt,
    key: ToolKey,
    *,
    native_call_id: str = "call_1",
    replay_required: bool = True,
    with_provider_ref: bool = True,
    args: dict[str, Any] | None = None,
) -> ToolCallItem:
    return ToolCallItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=attempt.attempt_id,
        call_id=CerebroCallId.generate(),
        tool_key=key,
        input=JsonToolInput(value=args if args is not None else {"amount": 10}),
        provider_ref=(
            ProviderCallRef(
                provider_id="lmstudio",
                native_call_id=native_call_id,
                replay_required=replay_required,
            )
            if with_provider_ref
            else None
        ),
    )


async def admit_output(
    store: HarnessStore,
    turn: AgentTurn,
    snapshot: StepSnapshot,
    attempt: InferenceAttempt,
    items: list[Any],
    *,
    extra_events: list[Any] | None = None,
) -> Any:
    """Push finalized items through the authoritative coordinator, deltas included."""
    coordinator = ProviderOutputCoordinator(store)
    events: list[Any] = list(extra_events or [])
    events.extend(
        OutputItemCompleted(attempt_id=attempt.attempt_id, item=item) for item in items
    )
    return await coordinator.accept(
        events,
        turn=turn,
        snapshot_id=snapshot.snapshot_id,
        active_attempt_id=attempt.attempt_id,
        expected_history_version=await store.history_version(turn.conversation_turn_id),
        at=NOW,
    )


async def executable_call(
    store: HarnessStore,
    catalog: FakeToolCatalog,
    *,
    occurrence: str,
    key: ToolKey | None = None,
    stable_operation_key: str | None = None,
    with_opaque: bool = False,
    with_provider_ref: bool = True,
    require_provider_call_ref: bool = False,
    required_opaque_kinds: tuple[str, ...] = (),
    call_count: int = 1,
) -> ExecutableFixture:
    """Drive one turn to a committed executable pre-side-effect checkpoint per call."""
    tool_key = key or mcp_key()
    turn, snapshot, attempt = await snapshotted_turn(
        store, catalog, occurrence=occurrence
    )
    items: list[Any] = []
    if with_opaque:
        items.append(opaque_item(attempt))
    calls = [
        tool_call(
            attempt,
            tool_key,
            native_call_id=f"call_{index}",
            with_provider_ref=with_provider_ref,
            args={"amount": 10 + index},
        )
        for index in range(call_count)
    ]
    items.extend(calls)
    admission = await admit_output(store, turn, snapshot, attempt, items)
    stored_calls = [item for item in admission.accepted if isinstance(item, ToolCallItem)]
    turn = await store.get_turn(turn.id)

    binding = snapshot.tool_plan.binding_for(tool_key)
    assert binding is not None
    fixture = ExecutableFixture(
        store=store,
        catalog=catalog,
        turn=turn,
        snapshot=snapshot,
        attempt=attempt,
        call_items=stored_calls,
    )
    for stored in stored_calls:
        checkpoint = await store.commit_executable_call_checkpoint(
            agent_turn_id=turn.id,
            snapshot_id=snapshot.snapshot_id,
            attempt_id=attempt.attempt_id,
            tool_call_item_id=stored.item_id,
            call_id=stored.call_id,
            binding=binding,
            expected_turn_version=turn.state_version,
            expected_history_version=await store.history_version(turn.conversation_turn_id),
            expected_replay_version=await store.replay_version(turn.conversation_turn_id),
            stable_operation_key=stable_operation_key,
            require_provider_call_ref=require_provider_call_ref,
            required_opaque_kinds=required_opaque_kinds,
            at=NOW,
        )
        turn = checkpoint.turn
        fixture.call_ids.append(stored.call_id)
    fixture.turn = turn
    return fixture
