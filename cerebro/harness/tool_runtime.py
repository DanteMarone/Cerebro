"""The standalone Harness tool-effect primitive (sections 17-18, and clarified AR-06).

This is the only code in Cerebro that is allowed to make an external tool call on behalf of a
snapshotted step, and it is deliberately not reachable from production. `RuntimeService`,
`ChannelPoller` and the live `AgentRuntime` do not import it; Phase 1D establishes one execution
authority per causal wake, and until then two authorities that can both dispatch would be a
worse bug than anything this module fixes.

The invariant it exists to enforce is one ordering:

1. load the current turn, the immutable snapshot and the exact `ToolExecution` and binding;
2. reject terminal turns, superseded snapshots, non-current calls, revoked security epochs and
   stale bindings;
3. verify the whole executable pre-side-effect checkpoint is durable;
4. commit `dispatch_may_have_escaped`;
5. only then invoke the exact snapshotted executor binding.

Steps 3 and 4 happen in one writer transaction, because verifying in one transaction and
marking in another leaves a window where a revocation lands between them. Nothing invokes an
executor before that commit returns, so a crash at any earlier point leaves a call that is not
executable and an external world that has not been touched.

What happens after step 5 is governed by the frozen `ToolRecoveryCapability` and nothing else.
Cerebro does not promise generic exactly-once external effects; an unknown outcome stays
unknown unless the executor's own declared semantics say a repeat or a reconciliation is safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Protocol, Sequence, Union

from pydantic import BaseModel, Field

from cerebro.harness.artifacts import ArtifactStore, StagedArtifact
from cerebro.harness.content import OmissionMetadata, TextPart
from cerebro.harness.exceptions import HarnessRecordNotFound, HarnessStateError
from cerebro.harness.ids import AgentTurnId, CerebroCallId, InferenceItemId
from cerebro.harness.items import ToolCallItem, ToolResultItem
from cerebro.harness.snapshot import StepSnapshot
from cerebro.harness.tool_plan import ToolPlanSource, resolve_current_binding
from cerebro.harness.tooling import JsonToolInput, ToolBinding, ToolResultStatus

__all__ = [
    "MODEL_PROJECTION_LIMIT_CHARS",
    "HarnessToolRuntime",
    "KnownInvocation",
    "ToolInvocation",
    "ToolInvocationRequest",
    "ToolExecutorGateway",
    "ToolRuntimeOutcome",
    "UnknownInvocation",
]

# The model sees a bounded projection. The complete output is always durable as an artifact, so
# this limit trades context for nothing except the illusion that a truncated result is whole --
# which is exactly what `OmissionMetadata` exists to prevent.
MODEL_PROJECTION_LIMIT_CHARS = 4096

_MAX_AUTOMATIC_REPEATS = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ToolInvocationRequest:
    """Everything an executor needs, and nothing that could rebind the call."""

    call_id: CerebroCallId
    agent_turn_id: AgentTurnId
    binding: ToolBinding
    wire_name: str
    arguments: Any
    stable_operation_key: str | None = None
    attempt_number: int = 1


class KnownInvocation(BaseModel):
    """The executor gave an authoritative answer about what happened."""

    model_config = {"frozen": True}

    outcome_kind: Literal["known"] = "known"
    status: ToolResultStatus = "success"
    raw_output: str = ""
    content_type: str = "text/plain; charset=utf-8"
    timing: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class UnknownInvocation(BaseModel):
    """The executor could not say whether the effect happened.

    Returning this is a positive statement, not a fallback. A gateway that cannot distinguish a
    transport failure from a tool-reported error must return this for a side-effecting binding,
    because calling it a known failure would license a retry that duplicates a real mutation.
    """

    model_config = {"frozen": True}

    outcome_kind: Literal["unknown"] = "unknown"
    reason: str
    raw_output: str | None = None


ToolInvocation = Annotated[
    Union[KnownInvocation, UnknownInvocation], Field(discriminator="outcome_kind")
]


class ToolExecutorGateway(Protocol):
    """The seam an executor is reached through."""

    async def invoke(self, request: ToolInvocationRequest) -> Any:
        """Run the exact snapshotted binding."""

    async def reconcile(self, request: ToolInvocationRequest) -> Any | None:
        """Authoritatively look up whether a possibly-escaped effect happened, or None."""


ToolRuntimeDisposition = Literal[
    "resolved_known",
    "resolved_indeterminate",
    "denied_security_revocation",
    "unavailable_stale_binding",
    "cancelled_before_dispatch",
    "not_executable",
]


@dataclass(frozen=True)
class ToolRuntimeOutcome:
    """What one standalone execution did, in terms safe to log."""

    call_id: CerebroCallId
    disposition: ToolRuntimeDisposition
    status: ToolResultStatus | None = None
    reason: str | None = None
    invocations: int = 0
    result_item_id: InferenceItemId | None = None
    artifact: dict[str, Any] | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        """Log/Hub-safe projection. Never carries raw tool output."""
        return {
            "call_id": str(self.call_id),
            "disposition": self.disposition,
            "status": self.status,
            "reason": self.reason,
            "invocations": self.invocations,
            "artifact": self.artifact,
        }


def project_model_visible(
    raw_output: str, *, limit: int = MODEL_PROJECTION_LIMIT_CHARS
) -> tuple[list[Any], OmissionMetadata | None, int]:
    """Bound the model-visible text and say explicitly what was left out.

    A bounded projection with no omission record is indistinguishable from a short result, which
    is how a truncated tool output quietly becomes a wrong answer.
    """
    original_size = len(raw_output.encode("utf-8"))
    if len(raw_output) <= limit:
        return [TextPart(text=raw_output)], None, original_size
    kept = raw_output[:limit]
    omitted_bytes = original_size - len(kept.encode("utf-8"))
    omission = OmissionMetadata(
        reason="raw_output_exceeds_model_projection_limit",
        omitted_bytes=omitted_bytes,
        original_size=original_size,
        detail=(
            f"kept the first {limit} characters; the complete output is durable as the "
            f"referenced artifact"
        ),
    )
    return [TextPart(text=kept)], omission, original_size


class HarnessToolRuntime:
    """Executes one checkpointed call against its exact frozen binding.

    Not wired into any production wake. Tests and internal standalone callers drive it directly
    until Phase 1D decides who owns execution for a causal wake.
    """

    def __init__(
        self,
        store: Any,
        *,
        catalog: ToolPlanSource,
        gateway: ToolExecutorGateway,
        artifacts: ArtifactStore | None = None,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.gateway = gateway
        self.artifacts = artifacts or ArtifactStore()

    # -- public entry points ----------------------------------------------------------

    async def execute_call(
        self,
        call_id: CerebroCallId,
        *,
        require_provider_call_ref: bool = False,
        required_opaque_kinds: tuple[str, ...] = (),
        at: str | None = None,
    ) -> ToolRuntimeOutcome:
        """Run one checkpointed call end to end, in the ordering this module exists for."""
        moment = at or _now()
        loaded = await self._load(call_id)
        execution = loaded["execution"].execution
        if execution.dispatch_state != "not_dispatched":
            raise HarnessStateError(
                f"ToolExecution {call_id} is already {execution.dispatch_state}; use "
                f"resume_uncertain_call for a call whose dispatch may have escaped"
            )

        guard = await self._reject_or_none(loaded, at=moment)
        if guard is not None:
            return guard

        # Steps 3 and 4: verify the entire barrier and commit dispatch uncertainty atomically.
        stored, turn = await self.store.mark_tool_dispatch_after_barrier(
            call_id,
            binding=loaded["binding"],
            expected_tool_version=loaded["execution"].row_version,
            expected_turn_version=loaded["turn"].state_version,
            expected_history_version=loaded["history_version"],
            expected_replay_version=loaded["replay_version"],
            require_provider_call_ref=require_provider_call_ref,
            required_opaque_kinds=required_opaque_kinds,
            at=moment,
        )

        # Step 5. Not one line earlier.
        return await self._invoke_and_resolve(
            stored=stored,
            turn=turn,
            binding=loaded["binding"],
            wire_name=loaded["wire_name"],
            arguments=loaded["arguments"],
            attempt_number=1,
            at=moment,
        )

    async def resume_uncertain_call(
        self, call_id: CerebroCallId, *, at: str | None = None
    ) -> ToolRuntimeOutcome:
        """Continue a call whose dispatch may already have escaped, after a restart.

        Repeating is only ever authorised by the frozen recovery capability, and a
        `stable_idempotency_key` retry reuses the exact durably persisted key. Minting a fresh
        one would be a second mutation with extra steps.
        """
        moment = at or _now()
        loaded = await self._load(call_id)
        stored = loaded["execution"]
        execution = stored.execution
        if execution.dispatch_state != "dispatch_may_have_escaped":
            raise HarnessStateError(
                f"ToolExecution {call_id} is {execution.dispatch_state}; there is no uncertain "
                f"dispatch to resume"
            )
        guard = await self._reject_or_none(loaded, at=moment, post_dispatch=True)
        if guard is not None:
            return guard
        if not execution.may_repeat_dispatch():
            return await self._resolve_indeterminate(
                stored,
                loaded["turn"],
                reason=(
                    f"repeat_semantics={execution.recovery_capability.repeat_semantics!r} does "
                    f"not authorise an automatic second dispatch"
                ),
                at=moment,
                invocations=0,
            )
        return await self._invoke_and_resolve(
            stored=stored,
            turn=loaded["turn"],
            binding=loaded["binding"],
            wire_name=loaded["wire_name"],
            arguments=loaded["arguments"],
            attempt_number=2,
            at=moment,
        )

    async def execute_step_calls(
        self,
        call_ids: Sequence[CerebroCallId],
        *,
        require_provider_call_ref: bool = False,
        at: str | None = None,
    ) -> list[ToolRuntimeOutcome]:
        """Execute several admitted calls strictly in their original provider order.

        Sequential by construction. Parallel client tools are explicitly out of Phase 1 scope,
        and running two effects concurrently would make the ordering guarantee above meaningless
        for the second one.
        """
        outcomes: list[ToolRuntimeOutcome] = []
        for call_id in call_ids:
            outcomes.append(
                await self.execute_call(
                    call_id, require_provider_call_ref=require_provider_call_ref, at=at
                )
            )
        return outcomes

    async def cancel_before_dispatch(
        self, call_id: CerebroCallId, *, reason: str, at: str | None = None
    ) -> ToolRuntimeOutcome:
        """Record the one cancellation outcome that is provable: nothing was dispatched."""
        moment = at or _now()
        loaded = await self._load(call_id)
        stored = loaded["execution"]
        if stored.execution.dispatch_state != "not_dispatched":
            raise HarnessStateError(
                "this call may already have escaped; cancellation cannot prove it did not"
            )
        return await self._resolve_pre_dispatch(
            stored,
            loaded["turn"],
            status="cancelled_before_dispatch",
            disposition="cancelled_before_dispatch",
            reason=reason,
            at=moment,
        )

    # -- loading and rejection --------------------------------------------------------

    async def _load(self, call_id: CerebroCallId) -> dict[str, Any]:
        """Step 1: current turn, immutable snapshot, exact execution, binding and arguments."""
        stored = await self.store.get_tool_execution(call_id)
        execution = stored.execution
        turn = await self.store.get_turn(execution.agent_turn_id)
        snapshot: StepSnapshot = await self.store.get_step_snapshot(execution.step_snapshot_id)
        binding = snapshot.tool_plan.binding_for(execution.tool_key)
        if binding is None:
            raise HarnessStateError(
                f"tool {execution.tool_key.canonical()} is not in the snapshotted tool plan"
            )
        if not execution.binds_exactly(binding):
            raise HarnessStateError(
                "the durable ToolExecution and the snapshotted plan disagree about this call's "
                "executable identity"
            )
        wire_name = next(
            (
                name
                for name, key in snapshot.tool_plan.provider_wire_name_to_tool_key.items()
                if key == execution.tool_key
            ),
            None,
        )
        if wire_name is None:
            raise HarnessStateError("the frozen plan has no wire name for this ToolKey")
        call_item = await self._call_item(turn, execution.tool_call_item_id)
        arguments = (
            call_item.input.value
            if isinstance(call_item.input, JsonToolInput)
            else call_item.input
        )
        return {
            "execution": stored,
            "turn": turn,
            "snapshot": snapshot,
            "binding": binding,
            "wire_name": wire_name,
            "arguments": arguments,
            "history_version": await self.store.history_version(turn.conversation_turn_id),
            "replay_version": await self.store.replay_version(turn.conversation_turn_id),
        }

    async def _call_item(self, turn: Any, item_id: InferenceItemId) -> ToolCallItem:
        items = await self.store.list_inference_items(
            turn.conversation_turn_id, include_superseded=True
        )
        for item in items:
            if item.item_id == item_id:
                if not isinstance(item, ToolCallItem):
                    raise HarnessStateError("the referenced item is not a ToolCallItem")
                return item
        raise HarnessRecordNotFound(f"ToolCallItem {item_id} is not durable")

    async def _reject_or_none(
        self, loaded: dict[str, Any], *, at: str, post_dispatch: bool = False
    ) -> ToolRuntimeOutcome | None:
        """Step 2: everything that must stop a dispatch, checked before anything is marked.

        Each of these resolves the call under its original identity. None of them rebinds it to
        a newer grant or a newer binding generation; that substitution is the exact failure the
        binding generation exists to catch.
        """
        stored = loaded["execution"]
        execution = stored.execution
        turn = loaded["turn"]
        snapshot: StepSnapshot = loaded["snapshot"]

        if turn.is_terminal:
            return ToolRuntimeOutcome(
                call_id=execution.call_id,
                disposition="not_executable",
                reason=f"AgentTurn is terminal ({turn.lifecycle})",
            )
        if turn.active_step_snapshot_id != snapshot.snapshot_id:
            return ToolRuntimeOutcome(
                call_id=execution.call_id,
                disposition="not_executable",
                reason="the call's snapshot is no longer the turn's active step",
            )

        current_epoch = await self.store.security_revocation_epoch()
        if current_epoch != snapshot.security_revocation_epoch:
            reason = (
                f"security revocation epoch advanced "
                f"{snapshot.security_revocation_epoch} -> {current_epoch}"
            )
            if post_dispatch:
                return await self._resolve_indeterminate(
                    stored, turn, reason=reason, at=at, invocations=0
                )
            return await self._resolve_pre_dispatch(
                stored,
                turn,
                status="denied",
                disposition="denied_security_revocation",
                reason=reason,
                at=at,
            )

        live = resolve_current_binding(
            self.catalog, execution.tool_key, execution.binding_generation
        )
        if live is None or not execution.binds_exactly(live.binding):
            same_name = resolve_current_binding(self.catalog, execution.tool_key)
            found = None if same_name is None else str(same_name.binding.binding_generation)
            reason = (
                f"frozen binding generation {execution.binding_generation} is no longer "
                f"addressable (live generation for this ToolKey: {found})"
            )
            if post_dispatch:
                return await self._resolve_indeterminate(
                    stored, turn, reason=reason, at=at, invocations=0
                )
            return await self._resolve_pre_dispatch(
                stored,
                turn,
                status="unavailable",
                disposition="unavailable_stale_binding",
                reason=reason,
                at=at,
            )
        if live.grant.policy_version != snapshot.tool_plan.policy_version:
            reason = (
                f"grant policy version changed "
                f"{snapshot.tool_plan.policy_version} -> {live.grant.policy_version}"
            )
            if post_dispatch:
                return await self._resolve_indeterminate(
                    stored, turn, reason=reason, at=at, invocations=0
                )
            return await self._resolve_pre_dispatch(
                stored,
                turn,
                status="denied",
                disposition="denied_security_revocation",
                reason=reason,
                at=at,
            )
        return None

    # -- invocation and resolution ----------------------------------------------------

    async def _invoke_and_resolve(
        self,
        *,
        stored: Any,
        turn: Any,
        binding: ToolBinding,
        wire_name: str,
        arguments: Any,
        attempt_number: int,
        at: str,
    ) -> ToolRuntimeOutcome:
        execution = stored.execution
        request = ToolInvocationRequest(
            call_id=execution.call_id,
            agent_turn_id=execution.agent_turn_id,
            binding=binding,
            wire_name=wire_name,
            arguments=arguments,
            stable_operation_key=execution.stable_operation_key,
            attempt_number=attempt_number,
        )
        invocations = 0
        outcome: Any
        try:
            outcome = await self.gateway.invoke(request)
            invocations += 1
        except Exception as exc:  # noqa: BLE001 - a raising executor proves nothing either way
            outcome = UnknownInvocation(reason=f"executor raised {type(exc).__name__}: {exc}")
            invocations += 1

        if isinstance(outcome, UnknownInvocation):
            resolved = await self._handle_unknown(
                stored=stored,
                turn=turn,
                request=request,
                unknown=outcome,
                invocations=invocations,
                at=at,
            )
            return resolved
        return await self._resolve_known(
            stored=stored,
            turn=turn,
            known=outcome,
            invocations=invocations,
            at=at,
        )

    async def _handle_unknown(
        self,
        *,
        stored: Any,
        turn: Any,
        request: ToolInvocationRequest,
        unknown: UnknownInvocation,
        invocations: int,
        at: str,
    ) -> ToolRuntimeOutcome:
        execution = stored.execution
        capability = execution.recovery_capability

        if capability.repeat_semantics == "reconcile_before_repeat":
            reconcile = getattr(self.gateway, "reconcile", None)
            if reconcile is not None and capability.reconciliation_binding:
                try:
                    reconciled = await reconcile(request)
                except Exception as exc:  # noqa: BLE001
                    reconciled = None
                    unknown = UnknownInvocation(
                        reason=f"reconciliation raised {type(exc).__name__}: {exc}"
                    )
                if isinstance(reconciled, KnownInvocation):
                    return await self._resolve_known(
                        stored=stored,
                        turn=turn,
                        known=reconciled,
                        invocations=invocations,
                        at=at,
                        reconciled=True,
                    )
            return await self._resolve_indeterminate(
                stored,
                turn,
                reason=unknown.reason,
                at=at,
                invocations=invocations,
                reconciliation_attempted=True,
            )

        if (
            capability.allows_automatic_repeat_after_escape
            and request.attempt_number <= _MAX_AUTOMATIC_REPEATS
        ):
            retry = ToolInvocationRequest(
                call_id=request.call_id,
                agent_turn_id=request.agent_turn_id,
                binding=request.binding,
                wire_name=request.wire_name,
                arguments=request.arguments,
                # The same durable key, never a fresh one: that is the whole point of it.
                stable_operation_key=execution.stable_operation_key,
                attempt_number=request.attempt_number + 1,
            )
            try:
                outcome = await self.gateway.invoke(retry)
                invocations += 1
            except Exception as exc:  # noqa: BLE001
                outcome = UnknownInvocation(
                    reason=f"executor raised {type(exc).__name__}: {exc}"
                )
                invocations += 1
            if isinstance(outcome, KnownInvocation):
                return await self._resolve_known(
                    stored=stored, turn=turn, known=outcome, invocations=invocations, at=at
                )
            unknown = outcome

        return await self._resolve_indeterminate(
            stored, turn, reason=unknown.reason, at=at, invocations=invocations
        )

    async def _resolve_known(
        self,
        *,
        stored: Any,
        turn: Any,
        known: KnownInvocation,
        invocations: int,
        at: str,
        reconciled: bool = False,
    ) -> ToolRuntimeOutcome:
        """Section 18: durable raw evidence, bounded projection, one canonical result item."""
        execution = stored.execution
        staged: StagedArtifact = self.artifacts.stage(
            known.raw_output,
            agent_turn_id=execution.agent_turn_id,
            call_id=execution.call_id,
            tool_key=execution.tool_key,
            binding_generation=execution.binding_generation,
            created_at=at,
            content_type=known.content_type,
            provenance={
                "status": known.status,
                "reconciled": reconciled,
                "executor_identity": execution.binding_executor_identity,
            },
        )
        content, omission, original_size = project_model_visible(known.raw_output)
        call_item = await self._call_item(turn, execution.tool_call_item_id)
        result_item = ToolResultItem(
            item_id=InferenceItemId.generate(),
            call_id=execution.call_id,
            tool_key=execution.tool_key,
            status=known.status,
            content=content,
            raw_output_ref=staged.artifact_ref,
            original_size=original_size,
            omission=omission,
            provider_ref=call_item.provider_ref,
            timing=known.timing,
            error=known.error,
        )
        history_version = await self.store.history_version(turn.conversation_turn_id)
        updated, _ = await self.store.resolve_tool_known(
            execution.call_id,
            known.status,
            expected_tool_version=stored.row_version,
            expected_turn_version=turn.state_version,
            result_item=result_item,
            expected_history_version=history_version,
            artifact=staged,
            at=at,
        )
        return ToolRuntimeOutcome(
            call_id=execution.call_id,
            disposition="resolved_known",
            status=known.status,
            invocations=invocations,
            result_item_id=updated.execution.model_output_item_id,
            artifact={
                "artifact_ref": str(staged.artifact_ref),
                "byte_size": staged.byte_size,
                "content_sha256": staged.content_sha256,
                "storage_backend": staged.storage_backend,
            },
            detail={"reconciled": reconciled, "truncated": omission is not None},
        )

    async def _resolve_indeterminate(
        self,
        stored: Any,
        turn: Any,
        *,
        reason: str,
        at: str,
        invocations: int,
        reconciliation_attempted: bool = False,
    ) -> ToolRuntimeOutcome:
        execution = stored.execution
        await self.store.resolve_tool_indeterminate(
            execution.call_id,
            reason,
            expected_tool_version=stored.row_version,
            expected_turn_version=turn.state_version,
            reconciliation_attempted=reconciliation_attempted,
            at=at,
        )
        return ToolRuntimeOutcome(
            call_id=execution.call_id,
            disposition="resolved_indeterminate",
            reason=reason,
            invocations=invocations,
            detail={"reconciliation_attempted": reconciliation_attempted},
        )

    async def _resolve_pre_dispatch(
        self,
        stored: Any,
        turn: Any,
        *,
        status: ToolResultStatus,
        disposition: ToolRuntimeDisposition,
        reason: str,
        at: str,
    ) -> ToolRuntimeOutcome:
        """Resolve a call that provably never reached an executor, under its original identity."""
        execution = stored.execution
        call_item = await self._call_item(turn, execution.tool_call_item_id)
        result_item = ToolResultItem(
            item_id=InferenceItemId.generate(),
            call_id=execution.call_id,
            tool_key=execution.tool_key,
            status=status,
            content=[TextPart(text=reason)],
            provider_ref=call_item.provider_ref,
            error={"reason": reason, "binding_generation": str(execution.binding_generation)},
        )
        history_version = await self.store.history_version(turn.conversation_turn_id)
        updated, _ = await self.store.resolve_tool_known(
            execution.call_id,
            status,
            expected_tool_version=stored.row_version,
            expected_turn_version=turn.state_version,
            result_item=result_item,
            expected_history_version=history_version,
            at=at,
        )
        return ToolRuntimeOutcome(
            call_id=execution.call_id,
            disposition=disposition,
            status=status,
            reason=reason,
            invocations=0,
            result_item_id=updated.execution.model_output_item_id,
        )
