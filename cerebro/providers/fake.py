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
from cerebro.providers.openai_compatible import to_chat_messages
from cerebro.providers.validate import validate_chat_turns


class FakeProvider:
    """Replays scripted Delta objects and records incoming invocation calls."""

    def __init__(
        self,
        deltas: list[Delta] | None = None,
        delay_s: float = 0.0,
        name: str = "fake",
        self_id: str = "jarvis",
    ) -> None:
        self.name = name
        self.self_id = self_id
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
        """Record invocation and yield configured deltas.

        Validates the conversation first. A fake that accepts more than a real model does is not a
        test double, it is a way of not testing: three of Cerebro's first six silent failures were
        green here and dead against qwen3.6-27b. Validation runs on the mapped outbound shape —
        the same turns a real provider would put on the wire — so what passes here is what a model
        could actually have understood.
        """
        validate_chat_turns(to_chat_messages(list(messages), self.self_id))

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
