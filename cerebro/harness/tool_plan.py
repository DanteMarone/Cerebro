"""Projection of the live Cerebro tool surface into a frozen `ToolPlanSnapshot`.

Two questions decide everything in this module.

**What is a tool's executable identity?** Not its provider wire name. `filesystem__read_file` is
one dialect's spelling; the same spelling can address a different subprocess after a reconnect.
Identity is `ToolKey` plus `ToolBindingGeneration`, and the generation is what execution
re-checks before it lets an effect escape.

**When must the generation change?** Exactly when the executable binding meaningfully changes,
and never otherwise — a generation that churns on every restart would make every recovered
snapshot stale and quietly turn crash recovery into "give up", while one that never changes
would let a replacement server answer for a call the model never made to it.

That gives two different sources, documented here because they are the frozen decision:

- **CoreTools** run in-process from code. There is no connection to lose, so the generation is a
  content digest over the tool's source, canonical name and exact offered schema. It is stable
  across a Cerebro restart, and it changes when the offered contract changes.
- **MCP** tools run in a subprocess behind `StdioMCPClient`. A respawn is a genuinely different
  executor, so the generation additionally mixes in that client's per-connection identity. A
  reconnect, a `tools/list` refresh that changes the schema, or a Cerebro restart all produce a
  new generation, and a snapshot frozen against the old one resolves stale rather than being
  rebound.

Trust tier and the enabled-tool globs are *grant* state, not binding identity. They land in
`ToolGrantEvidence` and are re-checked separately, so revoking a tier denies the call under its
original identity instead of pretending the executor changed.
"""

from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from cerebro.harness.content import Provenance
from cerebro.harness.ids import ToolBindingGeneration
from cerebro.harness.snapshot import ToolGrantEvidence, ToolPlanSnapshot
from cerebro.harness.tooling import (
    ToolBinding,
    ToolDefinition,
    ToolKey,
    ToolRecoveryCapability,
)

__all__ = [
    "CORE_SOURCE_ID",
    "CerebroToolCatalog",
    "ToolCatalogEntry",
    "ToolPlanSource",
    "core_binding_generation",
    "core_tool_key",
    "mcp_binding_generation",
    "mcp_tool_key",
    "project_tool_plan",
    "resolve_current_binding",
    "stable_version_of",
]

CORE_SOURCE_ID = "core_tools"
CORE_NAMESPACE = "core"

# Core tools that mutate state outside the calling step. Everything else in the current core
# catalogue reads. Being wrong in the read-only direction would authorise an automatic repeat of
# a real mutation, so an unrecognised name is treated as side-effecting.
_CORE_SIDE_EFFECTING = frozenset(
    {
        "scratchpad_append",
        "memory_write",
        "create_channel",
        "post_message",
        "task_create",
        "task_update",
    }
)


def stable_version_of(payload: Any) -> int:
    """A deterministic non-negative integer version derived from canonical content.

    Used where the contract asks for an integer catalog/policy version but the underlying truth
    is a set of definitions. It is restart-stable, which is the property that matters: a version
    that changed on every boot would invalidate every recovered snapshot.
    """
    from cerebro.harness.serialization import canonical_json

    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def core_tool_key(name: str) -> ToolKey:
    """Canonical identity for one in-process core tool."""
    return ToolKey(
        source_type="core", source_id=CORE_SOURCE_ID, namespace=CORE_NAMESPACE, name=name
    )


def mcp_tool_key(server: str, raw_name: str) -> ToolKey:
    """Canonical identity for one MCP tool, independent of its provider wire spelling."""
    return ToolKey(source_type="mcp", source_id=server, namespace=server, name=raw_name)


def _generation(parts: dict[str, Any]) -> ToolBindingGeneration:
    from cerebro.harness.serialization import canonical_json

    digest = hashlib.sha256(canonical_json(parts).encode("utf-8")).hexdigest()
    return ToolBindingGeneration(f"tbg_{digest[:32]}")


def core_binding_generation(
    key: ToolKey, *, executor_identity: str, input_schema: dict[str, Any], description: str
) -> ToolBindingGeneration:
    """Content-derived generation for an in-process core tool.

    Restart-stable on purpose: the executable binding is code in this process, so a restart does
    not replace it. Changing the offered schema or description does replace what the model was
    promised, and that produces a new generation.
    """
    return _generation(
        {
            "kind": "core",
            "key": key.canonical(),
            "executor_identity": executor_identity,
            "description": description,
            "input_schema": input_schema,
        }
    )


def mcp_binding_generation(
    key: ToolKey,
    *,
    executor_identity: str,
    connection_id: str,
    input_schema: dict[str, Any],
    description: str,
) -> ToolBindingGeneration:
    """Connection-scoped generation for one MCP tool.

    `connection_id` is minted afresh by `StdioMCPClient` on every successful handshake, so a
    respawned server never inherits the generation of the process it replaced.
    """
    return _generation(
        {
            "kind": "mcp",
            "key": key.canonical(),
            "executor_identity": executor_identity,
            "connection_id": connection_id,
            "description": description,
            "input_schema": input_schema,
        }
    )


@dataclass(frozen=True)
class ToolCatalogEntry:
    """One currently offered tool, in canonical terms plus its provider wire spelling."""

    key: ToolKey
    wire_name: str
    definition: ToolDefinition
    binding: ToolBinding
    grant: ToolGrantEvidence


class ToolPlanSource(Protocol):
    """Whatever can enumerate the currently offered, currently executable tools."""

    def catalog_version(self) -> int:
        """A version that changes exactly when the offered executable catalogue changes."""

    def policy_version(self) -> int:
        """A version that changes exactly when the permission/grant decision changes."""

    def entries(self) -> Sequence[ToolCatalogEntry]:
        """The offered tools, in deterministic order."""


def project_tool_plan(
    source: ToolPlanSource, *, security_revocation_epoch: int
) -> ToolPlanSnapshot:
    """Freeze the current offered catalogue into an immutable plan for one step."""
    entries = list(source.entries())
    catalog_version = source.catalog_version()
    policy_version = source.policy_version()
    return ToolPlanSnapshot(
        catalog_version=catalog_version,
        policy_version=policy_version,
        security_revocation_epoch=security_revocation_epoch,
        definitions=tuple(entry.definition for entry in entries),
        bindings=tuple(entry.binding for entry in entries),
        provider_wire_name_to_tool_key={entry.wire_name: entry.key for entry in entries},
        grant_evidence={entry.key.canonical(): entry.grant for entry in entries},
    )


def resolve_current_binding(
    source: ToolPlanSource,
    key: ToolKey,
    generation: ToolBindingGeneration | None = None,
) -> ToolCatalogEntry | None:
    """The live entry for one canonical key, or None when nothing addresses it any more.

    Passing `generation` asks the only question dispatch actually cares about: is the exact
    frozen binding still addressable? A same-named entry at a different generation is not an
    answer to that question, so it is not returned. Substituting it would be the silent
    rebinding this whole identity scheme exists to prevent.
    """
    for entry in source.entries():
        if entry.key != key:
            continue
        if generation is not None and entry.binding.binding_generation != generation:
            continue
        return entry
    return None


def _core_recovery_capability(name: str) -> ToolRecoveryCapability:
    """What the current core tools actually promise about repeating one call.

    Read-only core tools are declared `idempotent` because they have no externally relevant
    effect. Every mutating core tool is `never_automatic_repeat`: none of them accepts an
    idempotency key and none exposes an authoritative reconciliation lookup, so a second
    dispatch after uncertainty would be a second append, a second row or a second message.
    """
    if name in _CORE_SIDE_EFFECTING:
        return ToolRecoveryCapability(
            effect_class="side_effecting", repeat_semantics="never_automatic_repeat"
        )
    return ToolRecoveryCapability(effect_class="read_only", repeat_semantics="idempotent")


class CerebroToolCatalog:
    """Projects the live `CoreTools` + `MCPRegistry` exposure for one agent into canonical form.

    This is a read-only view. Building it starts no subprocess and changes no production
    routing; an MCP server that has never been contacted simply contributes no entries, which is
    the truthful answer to "what is executable right now".
    """

    def __init__(
        self,
        core_tools: Any,
        mcp_registry: Any | None,
        agent: Any,
        profile: dict[str, Any] | None = None,
    ) -> None:
        self.core_tools = core_tools
        self.mcp_registry = mcp_registry
        self.agent = agent
        self.profile = profile or {}
        self._trust_tier = core_tools.tier_of(agent, self.profile)
        self._enabled_globs = tuple(self.profile.get("tools_enabled", ["cerebro-core:*"]))

    # -- grant state -----------------------------------------------------------------

    def policy_version(self) -> int:
        """Changes when the tier or the enabled-tool globs change, and not otherwise."""
        return stable_version_of(
            {
                "trust_tier": self._trust_tier,
                "tools_enabled": sorted(self._enabled_globs),
                "agent_id": self.agent.id,
            }
        )

    def _grant(self, key: ToolKey, reason: str) -> ToolGrantEvidence:
        return ToolGrantEvidence(
            grant_id=f"{self.agent.id}:{self._trust_tier}:{key.canonical()}",
            policy_version=self.policy_version(),
            trust_tier=self._trust_tier,
            reason=reason,
        )

    # -- catalogue -------------------------------------------------------------------

    def _core_entries(self) -> list[ToolCatalogEntry]:
        entries: list[ToolCatalogEntry] = []
        policy_version = self.policy_version()
        catalog_version = self._catalog_version_of(self._raw_bindings())
        for spec in self.core_tools.specs_for(self.agent, self.profile):
            key = core_tool_key(spec.name)
            executor_identity = f"cerebro.core_tools/{spec.name}"
            definition = ToolDefinition(
                key=key,
                description=spec.description,
                input_schema=spec.parameters,
                provenance=Provenance(source_kind="core_tools", source_id=CORE_SOURCE_ID),
            )
            binding = ToolBinding(
                key=key,
                executor_identity=executor_identity,
                binding_generation=core_binding_generation(
                    key,
                    executor_identity=executor_identity,
                    input_schema=spec.parameters,
                    description=spec.description,
                ),
                catalog_version=catalog_version,
                policy_version=policy_version,
                recovery_capability=_core_recovery_capability(spec.name),
            )
            entries.append(
                ToolCatalogEntry(
                    key=key,
                    wire_name=spec.name,
                    definition=definition,
                    binding=binding,
                    grant=self._grant(key, f"trust tier {self._trust_tier}"),
                )
            )
        return entries

    def _mcp_entries(self) -> list[ToolCatalogEntry]:
        if self.mcp_registry is None:
            return []
        entries: list[ToolCatalogEntry] = []
        policy_version = self.policy_version()
        catalog_version = self._catalog_version_of(self._raw_bindings())
        for server_name, connection_id, spec in self._live_mcp_specs():
            wire_name = spec.name
            prefix = f"{server_name}__"
            raw_name = wire_name[len(prefix):] if wire_name.startswith(prefix) else wire_name
            key = mcp_tool_key(server_name, raw_name)
            executor_identity = f"mcp.stdio/{server_name}/{connection_id}/{raw_name}"
            definition = ToolDefinition(
                key=key,
                description=spec.description,
                input_schema=spec.parameters,
                provenance=Provenance(source_kind="mcp_server", source_id=server_name),
            )
            binding = ToolBinding(
                key=key,
                executor_identity=executor_identity,
                binding_generation=mcp_binding_generation(
                    key,
                    executor_identity=executor_identity,
                    connection_id=connection_id,
                    input_schema=spec.parameters,
                    description=spec.description,
                ),
                catalog_version=catalog_version,
                policy_version=policy_version,
                # An external MCP server declares nothing about repeat safety today, so the
                # Harness declares nothing on its behalf.
                recovery_capability=ToolRecoveryCapability(
                    effect_class="side_effecting",
                    repeat_semantics="never_automatic_repeat",
                ),
            )
            entries.append(
                ToolCatalogEntry(
                    key=key,
                    wire_name=wire_name,
                    definition=definition,
                    binding=binding,
                    grant=self._grant(key, f"tools_enabled match for {server_name}"),
                )
            )
        return entries

    def _live_mcp_specs(self) -> list[tuple[str, str, Any]]:
        """Offered MCP specs paired with the connection that currently answers for them."""
        offered = {spec.name for spec in self._filtered_mcp_specs()}
        found: list[tuple[str, str, Any]] = []
        for server_name in getattr(self.mcp_registry, "_servers", {}):
            client = self.mcp_registry.get_client(server_name)
            if client is None:
                continue
            connection_id = getattr(client, "connection_id", None)
            if not connection_id:
                # Never handshaken, or the process is gone. Nothing is addressable, so nothing
                # is frozen; a later snapshot can offer it once a connection exists.
                continue
            for spec in client.get_specs():
                if spec.name in offered:
                    found.append((server_name, connection_id, spec))
        return found

    def _filtered_mcp_specs(self) -> list[Any]:
        specs = self.mcp_registry.all_specs()
        allowed = []
        for spec in specs:
            normalized = spec.name.replace("__", ":")
            if any(
                fnmatch.fnmatch(spec.name, glob) or fnmatch.fnmatch(normalized, glob)
                for glob in self._enabled_globs
            ):
                allowed.append(spec)
        return allowed

    def _raw_bindings(self) -> list[dict[str, Any]]:
        """Identity material for the catalogue version, without recursing into entries()."""
        rows: list[dict[str, Any]] = []
        for spec in self.core_tools.specs_for(self.agent, self.profile):
            rows.append(
                {
                    "key": core_tool_key(spec.name).canonical(),
                    "description": spec.description,
                    "input_schema": spec.parameters,
                }
            )
        if self.mcp_registry is not None:
            for server_name, connection_id, spec in self._live_mcp_specs():
                prefix = f"{server_name}__"
                raw = spec.name[len(prefix):] if spec.name.startswith(prefix) else spec.name
                rows.append(
                    {
                        "key": mcp_tool_key(server_name, raw).canonical(),
                        "connection_id": connection_id,
                        "description": spec.description,
                        "input_schema": spec.parameters,
                    }
                )
        return sorted(rows, key=lambda row: row["key"])

    def _catalog_version_of(self, rows: list[dict[str, Any]]) -> int:
        return stable_version_of(rows)

    def catalog_version(self) -> int:
        """Changes exactly when an offered binding's identity material changes."""
        return self._catalog_version_of(self._raw_bindings())

    def entries(self) -> list[ToolCatalogEntry]:
        """Deterministically ordered canonical view of everything currently executable."""
        entries = self._core_entries() + self._mcp_entries()
        return sorted(entries, key=lambda entry: entry.key.canonical())
