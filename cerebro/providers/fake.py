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

# -- what a real chat template quietly refuses ------------------------------------
#
# Three of Cerebro's first six silent failures lived in the gap between what this fake accepted
# and what a real model understood: a packet with four consecutive system turns (accepted here,
# produced nothing from qwen3.6-27b, and Jarvis went mute in production); a tool round with an
# empty assistant turn and the result in a system message (accepted here, forbidden by the API);
# and a mapper that was never committed (never exercised here at all).
#
# None of them raised anything. A model handed a malformed conversation does not complain -- it
# returns something empty, and the failure surfaces as "the product is broken" long after the
# change that caused it. So the rules a template enforces silently are enforced loudly here.
#
# This lives in the fake rather than in its own module because today it is only the fake's
# concern. Enforcing it at the real provider boundary is a separate question with its own
# contract, and it is not answered by quietly reusing this.


class InvalidConversation(ValueError):
    """The message sequence is one a real chat template would mishandle rather than reject."""


def validate_chat_turns(turns: list[dict[str, Any]]) -> None:
    """Raise if `turns` is a shape a real provider would not reliably understand.

    Deliberately about *shape*, not content. It says nothing about whether a conversation is
    sensible, only whether it is well formed enough that a model's silence would be the model's
    fault rather than ours.
    """
    if not turns:
        raise InvalidConversation("no messages: a request with an empty conversation is a bug")

    previous_role: str | None = None
    for index, turn in enumerate(turns):
        role = turn.get("role")
        if role not in ("system", "user", "assistant", "tool"):
            raise InvalidConversation(f"turn {index}: unknown role {role!r}")

        if role == "system" and previous_role == "system":
            raise InvalidConversation(
                f"turn {index}: two system turns in a row. Chat templates are not obliged to "
                "handle consecutive system messages and several silently produce nothing. Merge "
                "them into one."
            )

        if role == "tool" and not turn.get("tool_call_id"):
            raise InvalidConversation(
                f"turn {index}: a tool result with no tool_call_id. The model cannot match it to "
                "the call it made."
            )

        if role == "assistant":
            content = turn.get("content")
            has_text = bool((content or "").strip()) if isinstance(content, str) else False
            if not has_text and not turn.get("tool_calls"):
                raise InvalidConversation(
                    f"turn {index}: an empty assistant turn carrying no tool_calls. It says "
                    "nothing, and an empty assistant message is exactly what convinces a model it "
                    "has already answered."
                )

        previous_role = role

    _check_tool_replies_follow_their_calls(turns)


def _check_tool_replies_follow_their_calls(turns: list[dict[str, Any]]) -> None:
    """Every tool result must answer a call the assistant actually made."""
    announced: set[str] = set()
    for index, turn in enumerate(turns):
        if turn.get("role") == "assistant":
            for call in turn.get("tool_calls") or []:
                if call.get("id"):
                    announced.add(call["id"])
        elif turn.get("role") == "tool":
            call_id = turn.get("tool_call_id")
            if call_id not in announced:
                raise InvalidConversation(
                    f"turn {index}: tool result for {call_id!r}, which no preceding assistant turn "
                    "requested. The call and its answer have come apart."
                )
