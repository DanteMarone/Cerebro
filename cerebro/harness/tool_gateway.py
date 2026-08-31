"""The concrete gateway from a frozen `ToolBinding` to Cerebro's current executors.

Standalone. Nothing in `RuntimeService`, `ChannelPoller` or `AgentRuntime` constructs this; it
exists so the Phase 1C effect primitive has a real executor to talk to in tests and internal
calls, and so Phase 1D has one place to review rather than a new integration to invent.

**Why an error string is not always a known failure.** `CompositeToolExecutor.execute` returns a
string for every outcome, and `StdioMCPClient.call_tool` catches every exception and returns
`"error: ..."` too. So one shape, `error: <text>`, covers a tool that refused, a tool that
crashed after writing to disk, and a transport that timed out with the request already delivered.
For a read-only binding those are all equivalent and the call resolves a known error. For a
side-effecting binding they are not, and claiming a known failure there would authorise a retry
that duplicates a real mutation. Those resolve as truthfully unknown.
"""

from __future__ import annotations

from typing import Any

from cerebro.harness.tool_runtime import (
    KnownInvocation,
    ToolInvocationRequest,
    UnknownInvocation,
)

__all__ = ["ERROR_PREFIX", "CerebroToolGateway"]

ERROR_PREFIX = "error: "


class CerebroToolGateway:
    """Invokes the exact snapshotted binding through the current composite executor."""

    def __init__(self, executor: Any, agent: Any, profile: dict[str, Any] | None = None) -> None:
        self.executor = executor
        self.agent = agent
        self.profile = profile or {}

    async def invoke(self, request: ToolInvocationRequest) -> Any:
        """Run one call and classify the outcome conservatively."""
        arguments = request.arguments if isinstance(request.arguments, dict) else {}
        if request.stable_operation_key is not None:
            policy = request.binding.recovery_capability.operation_key_policy
            arguments = dict(arguments)
            arguments[policy or "idempotency_key"] = request.stable_operation_key

        raw = await self.executor.execute(
            self.agent, request.wire_name, arguments, self.profile
        )
        text = raw if isinstance(raw, str) else str(raw)
        if not text.startswith(ERROR_PREFIX):
            return KnownInvocation(status="success", raw_output=text)

        detail = text[len(ERROR_PREFIX):]
        if request.binding.recovery_capability.effect_class == "read_only":
            return KnownInvocation(
                status="error", raw_output=text, error={"message": detail}
            )
        return UnknownInvocation(
            reason=(
                f"the current executor reports failures and transport loss identically, so "
                f"'{detail}' does not prove the side effect did not happen"
            ),
            raw_output=text,
        )
