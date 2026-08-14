"""FakeProvider implementation for test scripting and verification."""

import asyncio
from typing import Any, AsyncIterator

from cerebro.models import (
    Delta,
    Done,
    Message,
    TextDelta,
    ToolCallDelta,
    Usage,
)
from cerebro.providers.base import Params, ToolSpec


class FakeProvider:
    """Replays scripted Delta objects and records incoming invocation calls."""

    def __init__(
        self,
        deltas: list[Delta] | None = None,
        delay_s: float = 0.0,
        name: str = "fake",
    ) -> None:
        self.name = name
        self.deltas: list[Delta] = list(deltas) if deltas is not None else []
        self.delay_s = delay_s
        self.calls: list[dict[str, Any]] = []

    def set_deltas(self, deltas: list[Delta]) -> None:
        """Replace scripted deltas for subsequent stream calls."""
        self.deltas = list(deltas)

    def add_text(self, text: str) -> None:
        """Helper to append a TextDelta."""
        self.deltas.append(TextDelta(text=text))

    def add_tool_call(self, id: str, name: str, args_fragment: str) -> None:
        """Helper to append a ToolCallDelta."""
        self.deltas.append(ToolCallDelta(id=id, name=name, args_fragment=args_fragment))

    def add_usage(self, input_tokens: int, output_tokens: int) -> None:
        """Helper to append a Usage delta."""
        self.deltas.append(Usage(input=input_tokens, output=output_tokens))

    def add_done(self, reason: str = "stop") -> None:
        """Helper to append a Done delta."""
        self.deltas.append(Done(reason=reason))

    def clear_calls(self) -> None:
        """Clear recorded invocation history."""
        self.calls.clear()

    @property
    def last_call(self) -> dict[str, Any] | None:
        return self.calls[-1] if self.calls else None

    @property
    def last_messages(self) -> list[Message] | None:
        return self.calls[-1]["messages"] if self.calls else None

    @property
    def last_tools(self) -> list[ToolSpec] | None:
        return self.calls[-1]["tools"] if self.calls else None

    @property
    def last_params(self) -> Params | None:
        return self.calls[-1]["params"] if self.calls else None

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        params: Params,
    ) -> AsyncIterator[Delta]:
        """Record invocation and yield configured deltas."""
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "params": params,
            }
        )

        for delta in self.deltas:
            if self.delay_s > 0:
                await asyncio.sleep(self.delay_s)
            yield delta
