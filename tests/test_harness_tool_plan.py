"""Projection of the live CoreTools/MCP exposure into a frozen ToolPlanSnapshot (Phase 1C).

The binding-generation decision is the thing under test here: content-derived and
restart-stable for in-process CoreTools, connection-scoped for MCP subprocesses.
"""

from pathlib import Path

import pytest

from cerebro.harness import (
    CerebroToolCatalog,
    CerebroToolGateway,
    KnownInvocation,
    ToolInvocationRequest,
    UnknownInvocation,
    core_tool_key,
    mcp_tool_key,
    project_tool_plan,
    resolve_current_binding,
)
from cerebro.mcp import MCPServerConfig, StdioMCPClient
from cerebro.models import Agent
from cerebro.providers.base import ToolSpec
from cerebro.tools import CoreTools


def agent() -> Agent:
    return Agent(id="jarvis", name="Jarvis")


def core_tools(tmp_path: Path) -> CoreTools:
    return CoreTools(agents_root=tmp_path / "agents")


class FakeMCPClient:
    """A `StdioMCPClient` stand-in that exposes a connection identity and specs."""

    def __init__(self, name: str, specs: list[ToolSpec], connection_id: str | None) -> None:
        self.config = MCPServerConfig(name=name, command="python", args=["server.py"])
        self._specs = specs
        self.connection_id = connection_id

    def get_specs(self) -> list[ToolSpec]:
        return list(self._specs)


class FakeMCPRegistry:
    """Just enough registry surface for the catalogue projection."""

    def __init__(self, clients: dict[str, FakeMCPClient]) -> None:
        self._servers = {name: client.config for name, client in clients.items()}
        self._clients = clients

    def get_client(self, name: str) -> FakeMCPClient | None:
        return self._clients.get(name)

    def all_specs(self) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        for client in self._clients.values():
            specs.extend(client.get_specs())
        return specs


def test_core_tool_generations_are_content_derived_and_restart_stable(tmp_path: Path):
    """A restart does not replace in-process code, so it must not invalidate a snapshot."""
    profile = {"trust": "standard", "tools_enabled": ["*"]}
    first = CerebroToolCatalog(core_tools(tmp_path), None, agent(), profile)
    second = CerebroToolCatalog(core_tools(tmp_path), None, agent(), profile)

    generations = {
        entry.key.canonical(): str(entry.binding.binding_generation)
        for entry in first.entries()
    }
    reborn = {
        entry.key.canonical(): str(entry.binding.binding_generation)
        for entry in second.entries()
    }
    assert generations == reborn
    assert first.catalog_version() == second.catalog_version()
    assert core_tool_key("fs_read").canonical() in generations


def test_a_changed_core_tool_contract_changes_its_generation(tmp_path: Path):
    """Changing what the model was promised replaces the binding it was promised against."""
    profile = {"trust": "standard", "tools_enabled": ["*"]}
    tools = core_tools(tmp_path)
    catalog = CerebroToolCatalog(tools, None, agent(), profile)
    before = {
        entry.key: str(entry.binding.binding_generation) for entry in catalog.entries()
    }
    before_catalog_version = catalog.catalog_version()

    original = tools._tools["fs_read"]
    tools._tools["fs_read"] = type(original)(
        ToolSpec(
            name="fs_read",
            description=original.spec.description,
            parameters={"type": "object", "properties": {"path": {"type": "integer"}}},
        ),
        original.run,
    )
    after_catalog = CerebroToolCatalog(tools, None, agent(), profile)
    after = {
        entry.key: str(entry.binding.binding_generation) for entry in after_catalog.entries()
    }

    assert after[core_tool_key("fs_read")] != before[core_tool_key("fs_read")]
    assert after[core_tool_key("fs_list")] == before[core_tool_key("fs_list")]
    assert after_catalog.catalog_version() != before_catalog_version


def test_trust_tier_moves_the_grant_not_the_binding_identity(tmp_path: Path):
    """Revoking a tier must deny the frozen call, not pretend the executor changed."""
    tools = core_tools(tmp_path)
    standard = CerebroToolCatalog(
        tools, None, agent(), {"trust": "standard", "tools_enabled": ["*"]}
    )
    sandboxed = CerebroToolCatalog(
        tools, None, agent(), {"trust": "sandboxed", "tools_enabled": ["*"]}
    )
    shared = core_tool_key("memory_write")
    standard_entry = resolve_current_binding(standard, shared)
    sandboxed_entry = resolve_current_binding(sandboxed, shared)
    assert standard_entry is not None and sandboxed_entry is not None
    assert (
        standard_entry.binding.binding_generation
        == sandboxed_entry.binding.binding_generation
    )
    assert standard.policy_version() != sandboxed.policy_version()
    assert standard_entry.grant.trust_tier == "standard"
    assert sandboxed_entry.grant.trust_tier == "sandboxed"
    # A sandboxed agent is not offered the standard-only tools at all.
    assert resolve_current_binding(sandboxed, core_tool_key("fs_read")) is None


def test_core_recovery_capabilities_declare_mutation_honestly(tmp_path: Path):
    """No current core tool takes an idempotency key, so none may be repeated blindly."""
    catalog = CerebroToolCatalog(
        core_tools(tmp_path), None, agent(), {"trust": "standard", "tools_enabled": ["*"]}
    )
    by_name = {entry.key.name: entry.binding.recovery_capability for entry in catalog.entries()}
    assert by_name["post_message"].effect_class == "side_effecting"
    assert by_name["post_message"].repeat_semantics == "never_automatic_repeat"
    assert by_name["post_message"].allows_automatic_repeat_after_escape is False
    assert by_name["fs_read"].effect_class == "read_only"
    assert by_name["fs_read"].repeat_semantics == "idempotent"


def test_mcp_generation_is_scoped_to_the_answering_connection(tmp_path: Path):
    """A respawned server never inherits the generation of the process it replaced."""
    spec = ToolSpec(
        name="payments__charge",
        description="Charge a card",
        parameters={"type": "object", "properties": {"amount": {"type": "number"}}},
    )
    profile = {"trust": "standard", "tools_enabled": ["*"]}
    first = FakeMCPRegistry({"payments": FakeMCPClient("payments", [spec], "conn-1")})
    second = FakeMCPRegistry({"payments": FakeMCPClient("payments", [spec], "conn-2")})

    key = mcp_tool_key("payments", "charge")
    before = resolve_current_binding(
        CerebroToolCatalog(core_tools(tmp_path), first, agent(), profile), key
    )
    after = resolve_current_binding(
        CerebroToolCatalog(core_tools(tmp_path), second, agent(), profile), key
    )
    assert before is not None and after is not None
    assert before.binding.binding_generation != after.binding.binding_generation
    assert "conn-1" in before.binding.executor_identity
    assert "conn-2" in after.binding.executor_identity
    # And the exact-generation lookup refuses to substitute the replacement.
    catalog = CerebroToolCatalog(core_tools(tmp_path), second, agent(), profile)
    assert resolve_current_binding(catalog, key, before.binding.binding_generation) is None
    assert resolve_current_binding(catalog, key, after.binding.binding_generation) is not None


def test_an_unconnected_mcp_server_contributes_nothing_executable(tmp_path: Path):
    """Nothing addresses a server we have never handshaken, so nothing is frozen for it."""
    spec = ToolSpec(name="payments__charge", description="Charge", parameters={})
    registry = FakeMCPRegistry({"payments": FakeMCPClient("payments", [spec], None)})
    catalog = CerebroToolCatalog(
        core_tools(tmp_path), registry, agent(), {"trust": "standard", "tools_enabled": ["*"]}
    )
    assert resolve_current_binding(catalog, mcp_tool_key("payments", "charge")) is None
    plan = project_tool_plan(catalog, security_revocation_epoch=0)
    assert all(binding.key.source_type == "core" for binding in plan.bindings)


def test_enabled_globs_filter_the_mcp_exposure(tmp_path: Path):
    """A tool the profile does not enable is never offered and never frozen."""
    specs = [
        ToolSpec(name="payments__charge", description="Charge", parameters={}),
        ToolSpec(name="secrets__read", description="Read", parameters={}),
    ]
    registry = FakeMCPRegistry(
        {
            "payments": FakeMCPClient("payments", [specs[0]], "conn-1"),
            "secrets": FakeMCPClient("secrets", [specs[1]], "conn-1"),
        }
    )
    catalog = CerebroToolCatalog(
        core_tools(tmp_path),
        registry,
        agent(),
        {"trust": "standard", "tools_enabled": ["cerebro-core:*", "payments__*"]},
    )
    keys = {entry.key.canonical() for entry in catalog.entries()}
    assert mcp_tool_key("payments", "charge").canonical() in keys
    assert mcp_tool_key("secrets", "read").canonical() not in keys


def test_projected_plan_maps_wire_names_without_parsing_them(tmp_path: Path):
    """The frozen map is the only route from a wire name to identity."""
    spec = ToolSpec(name="payments__charge", description="Charge", parameters={})
    registry = FakeMCPRegistry({"payments": FakeMCPClient("payments", [spec], "conn-1")})
    catalog = CerebroToolCatalog(
        core_tools(tmp_path), registry, agent(), {"trust": "standard", "tools_enabled": ["*"]}
    )
    plan = project_tool_plan(catalog, security_revocation_epoch=3)
    assert plan.key_for_wire_name("payments__charge") == mcp_tool_key("payments", "charge")
    assert plan.key_for_wire_name("fs_read") == core_tool_key("fs_read")
    assert plan.key_for_wire_name("payments/charge") is None
    assert plan.security_revocation_epoch == 3
    assert plan.evidence_for(core_tool_key("fs_read")) is not None
    for binding in plan.bindings:
        assert plan.definition_for(binding.key) is not None


def test_stdio_client_mints_and_clears_its_connection_identity():
    """The identity exists only while a process is actually answering."""
    client = StdioMCPClient(MCPServerConfig(name="payments", command="python"))
    assert client.connection_id is None
    client._connection_id = "conn-1"
    assert client.connection_id is None  # no live process, so nothing is addressable


@pytest.mark.asyncio
async def test_gateway_will_not_call_an_error_string_a_known_failure(tmp_path: Path):
    """The current executor collapses refusal and transport loss into one string."""
    from tests.harness_phase1c import SIDE_EFFECTING, catalog_entry, mcp_key

    class Executor:
        def __init__(self, reply: str) -> None:
            self.reply = reply
            self.calls: list[tuple[str, dict]] = []

        async def execute(self, agent_obj, name, args, profile):
            self.calls.append((name, args))
            return self.reply

    side_effecting = catalog_entry(mcp_key(), generation="g1", capability=SIDE_EFFECTING)
    request = ToolInvocationRequest(
        call_id="ccall_x",
        agent_turn_id="atn_x",
        binding=side_effecting.binding,
        wire_name="payments__charge",
        arguments={"amount": 5},
    )

    executor = Executor("error: connection reset")
    outcome = await CerebroToolGateway(executor, agent()).invoke(request)
    assert isinstance(outcome, UnknownInvocation)
    assert "does not prove the side effect did not happen" in outcome.reason

    executor = Executor("charged")
    outcome = await CerebroToolGateway(executor, agent()).invoke(request)
    assert isinstance(outcome, KnownInvocation)
    assert outcome.status == "success"
    assert outcome.raw_output == "charged"


@pytest.mark.asyncio
async def test_gateway_calls_a_read_only_error_known_and_passes_the_operation_key(
    tmp_path: Path,
):
    """A read that failed has no effect to be uncertain about."""
    from tests.harness_phase1c import IDEMPOTENT, KEYED, catalog_entry, mcp_key

    class Executor:
        def __init__(self, reply: str) -> None:
            self.reply = reply
            self.calls: list[tuple[str, dict]] = []

        async def execute(self, agent_obj, name, args, profile):
            self.calls.append((name, args))
            return self.reply

    read_only = catalog_entry(mcp_key(), generation="g1", capability=IDEMPOTENT)
    executor = Executor("error: file not found")
    outcome = await CerebroToolGateway(executor, agent()).invoke(
        ToolInvocationRequest(
            call_id="ccall_x",
            agent_turn_id="atn_x",
            binding=read_only.binding,
            wire_name="payments__charge",
            arguments={},
        )
    )
    assert isinstance(outcome, KnownInvocation)
    assert outcome.status == "error"

    keyed = catalog_entry(mcp_key(), generation="g1", capability=KEYED)
    executor = Executor("charged")
    await CerebroToolGateway(executor, agent()).invoke(
        ToolInvocationRequest(
            call_id="ccall_x",
            agent_turn_id="atn_x",
            binding=keyed.binding,
            wire_name="payments__charge",
            arguments={"amount": 5},
            stable_operation_key="op-9",
        )
    )
    assert executor.calls[0][1] == {"amount": 5, "idempotency_key": "op-9"}
