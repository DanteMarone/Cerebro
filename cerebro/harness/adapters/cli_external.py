"""`ExternalAgentAdapter` compatibility shim for the current `CliAgentProvider`.

The shim exists to put the boundary in place, not to change what running `claude -p` does today.
It delegates to `CliAgentProvider` unchanged, which keeps prompt rendering, cwd, timeout,
output-file handling and the cancellation kill in exactly one place. Duplicating any of that here
would mean two subtly different ways of running the same subprocess.

What it deliberately does not do:

- claim reconnect, resume or orphan reconciliation. `recovery_capability` says no to all three,
  and `reconcile_orphan` answers "suspend" rather than guessing what a lost subprocess did;
- route CLI execution through `ProviderAdapter`. An external harness has no canonical inference
  attempt and no provider replay state, and pretending otherwise would let generic recovery code
  make promises about somebody else's process.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from cerebro.harness.external_agent import (
    ExternalAgentEvent,
    ExternalExecutionCompleted,
    ExternalExecutionRequest,
    ExternalPromptTurn,
    ExternalReasoningDelta,
    ExternalRecoveryCapability,
    ExternalTextDelta,
    OrphanReconciliation,
)
from cerebro.harness.ids import ExternalExecutionId
from cerebro.models import Done, Message, ReasoningDelta, TextDelta
from cerebro.providers.base import Params

__all__ = ["CliExternalAgentAdapter", "ExternalExecutionHandle", "prompt_turns_from_messages"]

_CLI_RECOVERY = ExternalRecoveryCapability(
    supports_reconnect=False,
    supports_orphan_reconciliation=False,
    supports_resume=False,
    notes=(
        "A `claude -p` / `codex exec` / `agy` / `goose run` child is bound to this process. If "
        "Cerebro dies, the execution is lost and whatever it already did to the workspace "
        "stands. Phase 1 does not claim to reconnect or reconcile it."
    ),
)


def prompt_turns_from_messages(
    messages: list[Message],
) -> list[ExternalPromptTurn]:
    """Project collaboration rows into the external prompt shape.

    Compatibility direction only. Nothing in the Harness reads `Message`; this exists so a caller
    that still holds rows can reach the boundary.
    """
    return [
        ExternalPromptTurn(
            author_id=msg.author_id, author_kind=msg.author_kind, body=msg.body
        )
        for msg in messages
    ]


class ExternalExecutionHandle:
    """A started external execution, with the task that owns its child process."""

    def __init__(self, execution_id: ExternalExecutionId, request: ExternalExecutionRequest):
        self.execution_id = execution_id
        self.request = request
        self.cancelled = False


class CliExternalAgentAdapter:
    """Runs the existing `CliAgentProvider` behind the external-agent boundary."""

    def __init__(self, provider, *, adapter_id: str | None = None) -> None:
        self._provider = provider
        self.adapter_id = adapter_id or f"cli_agent:{getattr(provider, 'backend', 'unknown')}"
        self.recovery_capability: ExternalRecoveryCapability = _CLI_RECOVERY
        self._live: dict[str, asyncio.Task] = {}

    async def start_or_resume(
        self, request: ExternalExecutionRequest
    ) -> ExternalExecutionHandle:
        """Begin one execution. There is no resume; a repeat start is a fresh subprocess."""
        return ExternalExecutionHandle(request.execution_id, request)

    async def stream_events(
        self, handle: ExternalExecutionHandle
    ) -> AsyncIterator[ExternalAgentEvent]:
        """Yield events from the child process.

        `ProviderError` and `ProviderUnavailable` propagate unchanged. Current behaviour turns
        them into a channel-visible failure, and swallowing them into an event here would quietly
        change what a broken CLI agent looks like.
        """
        request = handle.request
        rows = [
            Message(
                channel_id="external",
                author_id=turn.author_id,
                author_kind=turn.author_kind,
                body=turn.body,
            )
            for turn in request.prompt_turns
        ]
        stream = self._provider.stream(rows, [], Params())
        try:
            async for delta in stream:
                if isinstance(delta, ReasoningDelta):
                    yield ExternalReasoningDelta(
                        execution_id=request.execution_id, text=delta.text
                    )
                elif isinstance(delta, TextDelta):
                    yield ExternalTextDelta(
                        execution_id=request.execution_id, text=delta.text
                    )
                elif isinstance(delta, Done):
                    yield ExternalExecutionCompleted(
                        execution_id=request.execution_id, reason=delta.reason
                    )
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

    async def cancel(self, execution_id: ExternalExecutionId) -> None:
        """Cancel the running task, which is what kills the child.

        The kill itself stays in `CliAgentProvider`: it already handles `CancelledError` by
        terminating the subprocess, and a coding agent left running unattended is precisely what
        that code exists to prevent.
        """
        task = self._live.pop(str(execution_id), None)
        if task is not None and not task.done():
            task.cancel()

    def track(self, execution_id: ExternalExecutionId, task: asyncio.Task) -> None:
        """Register the task driving one execution so `cancel` can reach it."""
        self._live[str(execution_id)] = task

    async def reconcile_orphan(
        self, execution_id: ExternalExecutionId
    ) -> OrphanReconciliation:
        """Say honestly that Phase 1 cannot reconcile a lost external execution."""
        return OrphanReconciliation(
            execution_id=execution_id,
            supported=False,
            disposition="suspend",
            reason=(
                "external CLI harness executions are not restart-recoverable in Phase 1; the "
                "turn must be suspended for a human rather than silently re-run"
            ),
        )
