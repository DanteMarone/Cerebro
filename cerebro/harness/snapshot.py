"""The immutable executable `StepSnapshot` and its frozen `ToolPlanSnapshot` (sections 13/14).

A snapshot is not a convenience cache of current configuration. It is the only thing that says
what was executable for one step, and recovery must be able to rebuild that without reading
mutable current configuration. So every field that changes request or dispatch semantics is
frozen here by value, and everything that would let a later provider, model, tool binding or
policy version silently substitute itself is refused on read.

Credentials never appear. `ProviderConfig.credential_reference` names a secret the transport
resolves at call time; a snapshot carries the reference, never the value.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cerebro.harness.ids import (
    AgentTurnId,
    ModelProfileId,
    ProviderConfigId,
    StepSnapshotId,
)
from cerebro.harness.tooling import ToolBinding, ToolDefinition, ToolKey

__all__ = [
    "STEP_SNAPSHOT_FORMAT_VERSION",
    "TOOL_PLAN_FORMAT_VERSION",
    "StepSnapshot",
    "ToolGrantEvidence",
    "ToolPlanSnapshot",
]

# Version 1 is the Phase 1B identity-only seam (`StepSnapshotIdentity`). Version 2 is the
# executable snapshot. They share a table and are never interchangeable: an identity-only
# snapshot can never satisfy the executable pre-side-effect barrier.
STEP_SNAPSHOT_FORMAT_VERSION = 2
TOOL_PLAN_FORMAT_VERSION = 1

# Keys that must never appear in a frozen options/environment payload. A snapshot is read back
# by recovery long after the turn ended, so a secret placed here outlives every rotation.
_FORBIDDEN_OPTION_KEYS = frozenset(
    {"api_key", "apikey", "authorization", "token", "secret", "password", "credential"}
)


def _reject_secret_like(payload: dict[str, Any], where: str) -> None:
    leaked = sorted(_FORBIDDEN_OPTION_KEYS & {str(key).lower() for key in payload})
    if leaked:
        raise ValueError(
            f"{where} must not carry credential material: {leaked}; freeze a stable reference "
            f"instead"
        )


class ToolGrantEvidence(BaseModel):
    """Why one tool was offered for this step, frozen at snapshot time.

    `grant_id` plus `policy_version` is what execution re-checks. The human-readable `reason`
    exists for the operator surface and carries no authority of its own.
    """

    model_config = {"frozen": True}

    grant_id: str
    policy_version: int
    trust_tier: str
    reason: str | None = None


class ToolPlanSnapshot(BaseModel):
    """The exact executable tool exposure for one step.

    The plan freezes executable identity, not a menu. Two tools may answer to the same provider
    wire name across a reconnect; only `ToolKey` plus `ToolBindingGeneration` says whether the
    thing that answers now is the thing the model was offered then.
    """

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    format_version: int = TOOL_PLAN_FORMAT_VERSION
    catalog_version: int = Field(ge=0)
    policy_version: int = Field(ge=0)
    security_revocation_epoch: int = Field(ge=0)
    definitions: tuple[ToolDefinition, ...] = ()
    bindings: tuple[ToolBinding, ...] = ()
    provider_wire_name_to_tool_key: dict[str, ToolKey] = Field(default_factory=dict)
    grant_evidence: dict[str, ToolGrantEvidence] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _plan_is_internally_consistent(self) -> "ToolPlanSnapshot":
        if self.format_version != TOOL_PLAN_FORMAT_VERSION:
            raise ValueError(
                f"unsupported ToolPlanSnapshot format_version {self.format_version!r}"
            )
        definition_keys = [definition.key for definition in self.definitions]
        if len(set(definition_keys)) != len(definition_keys):
            raise ValueError("a ToolPlanSnapshot cannot define one ToolKey twice")
        binding_keys = [binding.key for binding in self.bindings]
        if len(set(binding_keys)) != len(binding_keys):
            raise ValueError("a ToolPlanSnapshot cannot bind one ToolKey twice")
        if set(definition_keys) != set(binding_keys):
            raise ValueError(
                "every offered ToolDefinition needs exactly one executable ToolBinding; an "
                "unbound definition is a tool the model can name but nothing can run"
            )
        for binding in self.bindings:
            if binding.catalog_version != self.catalog_version:
                raise ValueError(
                    f"binding {binding.key.canonical()} freezes catalog_version "
                    f"{binding.catalog_version} but the plan froze {self.catalog_version}"
                )
            if binding.policy_version != self.policy_version:
                raise ValueError(
                    f"binding {binding.key.canonical()} freezes policy_version "
                    f"{binding.policy_version} but the plan froze {self.policy_version}"
                )
        mapped = set(self.provider_wire_name_to_tool_key.values())
        if mapped != set(definition_keys):
            raise ValueError(
                "the provider wire-name map must cover exactly the offered ToolKeys; a wire "
                "name with no key is an unroutable call and a key with no wire name is a tool "
                "the provider can never name"
            )
        if len(self.provider_wire_name_to_tool_key) != len(mapped):
            raise ValueError("two provider wire names cannot resolve to one ToolKey")
        evidence_keys = set(self.grant_evidence)
        offered = {key.canonical() for key in definition_keys}
        if evidence_keys and evidence_keys != offered:
            raise ValueError(
                "grant evidence must cover exactly the offered ToolKeys or be absent entirely"
            )
        for key_text, evidence in self.grant_evidence.items():
            if evidence.policy_version != self.policy_version:
                raise ValueError(
                    f"grant evidence for {key_text} freezes policy_version "
                    f"{evidence.policy_version} but the plan froze {self.policy_version}"
                )
        return self

    def binding_for(self, key: ToolKey) -> ToolBinding | None:
        """The frozen executable binding for one canonical key, or None."""
        for binding in self.bindings:
            if binding.key == key:
                return binding
        return None

    def definition_for(self, key: ToolKey) -> ToolDefinition | None:
        """The frozen offered definition for one canonical key, or None."""
        for definition in self.definitions:
            if definition.key == key:
                return definition
        return None

    def key_for_wire_name(self, wire_name: str) -> ToolKey | None:
        """Resolve a provider wire name to canonical identity.

        A wire name is an edge serialization detail of one dialect. It resolves through the
        frozen map or not at all; it is never parsed for meaning.
        """
        return self.provider_wire_name_to_tool_key.get(wire_name)

    def evidence_for(self, key: ToolKey) -> ToolGrantEvidence | None:
        """The frozen grant evidence for one canonical key, or None."""
        return self.grant_evidence.get(key.canonical())

    def plan_hash(self) -> str:
        """Deterministic digest of the frozen plan, used as a queryable snapshot column."""
        from cerebro.harness.serialization import canonical_json

        return hashlib.sha256(
            canonical_json(self.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()


class StepSnapshot(BaseModel):
    """One immutable executable step definition.

    Everything here is by value or by stable reference. Recovery reads this and nothing else to
    decide what was executable; if a field were left to "whatever is configured now", a model
    swap between crash and restart would silently rewrite history.
    """

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True, protected_namespaces=())

    snapshot_id: StepSnapshotId
    format_version: int = STEP_SNAPSHOT_FORMAT_VERSION
    agent_turn_id: AgentTurnId
    step_index: int = Field(ge=0)
    turn_version_at_creation: int = Field(ge=0)

    provider_config_id: ProviderConfigId
    provider_id: str
    adapter_dialect: str
    adapter_dialect_version: str
    model_profile_id: ModelProfileId
    model_profile_version: int = Field(ge=1)
    provider_semantic_options: dict[str, Any] = Field(default_factory=dict)

    inference_history_version: int = Field(ge=0)
    provider_replay_version: int = Field(ge=0)
    context_projection_version: int = Field(ge=0)
    token_budget: int = Field(ge=0)

    tool_plan: ToolPlanSnapshot
    permission_policy_version: int = Field(ge=0)
    security_revocation_epoch: int = Field(ge=0)

    workspace_ref: str
    cwd: str
    environment_ref: str
    environment_version: int = Field(ge=0)

    completion_policy_version: int = Field(ge=0)
    trace_metadata: dict[str, str] = Field(default_factory=dict)
    created_at: str

    @model_validator(mode="after")
    def _executable_snapshot_is_coherent(self) -> "StepSnapshot":
        if self.format_version != STEP_SNAPSHOT_FORMAT_VERSION:
            raise ValueError(
                f"unsupported executable StepSnapshot format_version {self.format_version!r}"
            )
        _reject_secret_like(self.provider_semantic_options, "provider_semantic_options")
        _reject_secret_like(dict(self.trace_metadata), "trace_metadata")
        if self.tool_plan.policy_version != self.permission_policy_version:
            raise ValueError(
                "the frozen tool plan and the snapshot must agree on permission_policy_version"
            )
        if self.tool_plan.security_revocation_epoch != self.security_revocation_epoch:
            raise ValueError(
                "the frozen tool plan and the snapshot must agree on security_revocation_epoch"
            )
        if not self.workspace_ref or not self.cwd or not self.environment_ref:
            raise ValueError(
                "workspace_ref, cwd and environment_ref are required; an unrecorded execution "
                "location cannot be reconstructed"
            )
        return self

    def queryable_columns(self) -> dict[str, Any]:
        """The projection stored in indexed SQL columns beside the canonical envelope.

        Reads compare every one of these against the decoded envelope, so a hand-edited column
        cannot make a snapshot describe an execution it never froze.
        """
        return {
            "provider_config_id": str(self.provider_config_id),
            "provider_id": self.provider_id,
            "adapter_dialect": self.adapter_dialect,
            "adapter_dialect_version": self.adapter_dialect_version,
            "model_profile_id": str(self.model_profile_id),
            "model_profile_version": self.model_profile_version,
            "inference_history_version": self.inference_history_version,
            "provider_replay_version": self.provider_replay_version,
            "context_projection_version": self.context_projection_version,
            "token_budget": self.token_budget,
            "tool_plan_hash": self.tool_plan.plan_hash(),
            "tool_plan_catalog_version": self.tool_plan.catalog_version,
            "permission_policy_version": self.permission_policy_version,
            "security_revocation_epoch": self.security_revocation_epoch,
            "workspace_ref": self.workspace_ref,
            "cwd": self.cwd,
            "environment_ref": self.environment_ref,
            "environment_version": self.environment_version,
            "completion_policy_version": self.completion_policy_version,
        }
