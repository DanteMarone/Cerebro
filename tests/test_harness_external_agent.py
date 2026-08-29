"""The `ExternalAgentAdapter` boundary.

No real CLI harness is invoked here. `claude`, `codex`, `agy` and `goose` cost money and need a
network; a test that spends either is not deterministic. The shim is exercised against a fake
provider and against `CliAgentProvider` driven by a stub subprocess, exactly as the existing CLI
provider tests do.
"""

import asyncio

import pytest

from cerebro.harness import (
    AgentTurnId,
    ExternalAgentAdapter,
    ExternalExecutionId,
    ExternalExecutionRequest,
    ExternalPromptTurn,
    ProviderAdapter,
)
from cerebro.harness.adapters import CliExternalAgentAdapter, OpenAICompatibleAdapter
from cerebro.harness.adapters.cli_external import prompt_turns_from_messages
from cerebro.harness.external_agent import (
    ExternalExecutionCompleted,
    ExternalReasoningDelta,
    ExternalTextDelta,
)
from cerebro.models import Done, Message, ReasoningDelta, TextDelta
from cerebro.providers.cli_agent import CliAgentProvider, render_prompt
from cerebro.providers.openai_compatible import ProviderError
from tests.harness_fixtures import FakeTransport


class StubCliProvider:
    """A `CliAgentProvider`-shaped stand-in. No subprocess, no network, no spend."""

    name = "cli_agent"
    backend = "claude"

    def __init__(self, deltas=None, raises: Exception | None = None) -> None:
        self.deltas = deltas or [TextDelta(text="done"), Done(reason="stop")]
        self.raises = raises
        self.seen: list[Message] = []

    async def stream(self, messages, tools, params):
        self.seen = list(messages)
        if self.raises is not None:
            raise self.raises
        for delta in self.deltas:
            yield delta


def _request(turns=None) -> ExternalExecutionRequest:
    return ExternalExecutionRequest(
        execution_id=ExternalExecutionId.generate(),
        agent_turn_id=AgentTurnId.generate(),
        agent_id="claude",
        prompt_turns=turns
        or [
            ExternalPromptTurn(author_id="dante", author_kind="user", body="ship it"),
            ExternalPromptTurn(author_id="claude", author_kind="agent", body="on it"),
        ],
    )


# -- structural separation -----------------------------------------------------------

def test_the_two_adapter_contracts_are_structurally_distinct():
    """An external harness is not a provider, and the type system says so."""
    provider = OpenAICompatibleAdapter(FakeTransport([]))
    external = CliExternalAgentAdapter(StubCliProvider())

    assert isinstance(provider, ProviderAdapter)
    assert not isinstance(provider, ExternalAgentAdapter)
    assert isinstance(external, ExternalAgentAdapter)
    assert not isinstance(external, ProviderAdapter)


def test_the_contracts_share_no_base_class():
    assert ProviderAdapter not in ExternalAgentAdapter.__mro__
    assert ExternalAgentAdapter not in ProviderAdapter.__mro__
    common = set(type(OpenAICompatibleAdapter(FakeTransport([]))).__mro__) & set(
        type(CliExternalAgentAdapter(StubCliProvider())).__mro__
    )
    assert common == {object}


def test_the_external_module_does_not_depend_on_provider_inference_semantics():
    """The boundary is only real if it does not import the thing it is separate from."""
    import ast

    import cerebro.harness.external_agent as module

    with open(module.__file__, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)

    forbidden = {"provider_adapter", "attempts", "items", "request", "events"}
    assert not any(name.split(".")[-1] in forbidden for name in imported), imported


# -- behaviour preservation ----------------------------------------------------------

async def test_the_shim_streams_the_provider_deltas_as_external_events():
    provider = StubCliProvider(
        [ReasoningDelta(text="thinking"), TextDelta(text="all done"), Done(reason="stop")]
    )
    adapter = CliExternalAgentAdapter(provider)
    request = _request()

    handle = await adapter.start_or_resume(request)
    events = [event async for event in adapter.stream_events(handle)]

    assert isinstance(events[0], ExternalReasoningDelta)
    assert isinstance(events[1], ExternalTextDelta)
    assert isinstance(events[2], ExternalExecutionCompleted)
    assert events[1].text == "all done"
    assert all(e.execution_id == request.execution_id for e in events)


async def test_the_shim_preserves_the_current_prompt_rendering():
    """Prompt rendering stays in `CliAgentProvider`; the shim hands it the same turns."""
    provider = StubCliProvider()
    adapter = CliExternalAgentAdapter(provider)
    rows = [
        Message(channel_id="c1", author_id="dante", author_kind="user", body="ship it"),
        Message(channel_id="c1", author_id="claude", author_kind="agent", body="on it"),
    ]
    request = _request(prompt_turns_from_messages(rows))

    handle = await adapter.start_or_resume(request)
    [event async for event in adapter.stream_events(handle)]

    assert render_prompt(provider.seen, "claude") == render_prompt(rows, "claude")


async def test_provider_failures_still_propagate_unchanged():
    provider = StubCliProvider(raises=ProviderError("agent 'claude' exited 1: boom"))
    adapter = CliExternalAgentAdapter(provider)
    handle = await adapter.start_or_resume(_request())

    with pytest.raises(ProviderError, match="exited 1"):
        [event async for event in adapter.stream_events(handle)]


def test_the_cli_adapter_claims_no_restart_recovery():
    adapter = CliExternalAgentAdapter(StubCliProvider())
    capability = adapter.recovery_capability
    assert capability.supports_reconnect is False
    assert capability.supports_orphan_reconciliation is False
    assert capability.supports_resume is False


async def test_orphan_reconciliation_answers_suspend_rather_than_guessing():
    adapter = CliExternalAgentAdapter(StubCliProvider())
    execution_id = ExternalExecutionId.generate()
    outcome = await adapter.reconcile_orphan(execution_id)
    assert outcome.supported is False
    assert outcome.disposition == "suspend"
    assert outcome.execution_id == execution_id


async def test_cancel_reaches_the_task_that_owns_the_child_process():
    """Cancellation is what kills the subprocess, so it has to reach the running task."""
    started = asyncio.Event()

    class HangingProvider(StubCliProvider):
        async def stream(self, messages, tools, params):
            started.set()
            await asyncio.sleep(60)
            yield Done(reason="stop")

    adapter = CliExternalAgentAdapter(HangingProvider())
    request = _request()
    handle = await adapter.start_or_resume(request)

    async def drive():
        async for _ in adapter.stream_events(handle):
            pass

    task = asyncio.create_task(drive())
    adapter.track(request.execution_id, task)
    await started.wait()
    await adapter.cancel(request.execution_id)

    with pytest.raises(asyncio.CancelledError):
        await task


def test_the_real_cli_provider_fits_the_boundary_without_being_changed():
    """`CliAgentProvider` is used as-is; the shim adds a boundary, not a rewrite."""
    provider = CliAgentProvider("claude", backend="claude", command=["echo"])
    adapter = CliExternalAgentAdapter(provider)
    assert isinstance(adapter, ExternalAgentAdapter)
    assert not isinstance(adapter, ProviderAdapter)
    assert adapter.adapter_id == "cli_agent:claude"
