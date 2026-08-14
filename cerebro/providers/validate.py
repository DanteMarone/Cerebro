"""What a real chat template quietly refuses, stated explicitly.

Three of the six silent failures in Cerebro's first day lived in the gap between what
`FakeProvider` accepted and what a real model understood:

- a context packet with four consecutive system turns — the fake accepted it, qwen3.6-27b produced
  nothing at all, and Jarvis went mute in production while every test stayed green;
- a tool round with an empty assistant turn and the result in a system message — the fake accepted
  it, the API forbids it;
- a commit whose mapper was never committed — the fake never exercised the real one.

None of those raised an error anywhere. A model given a malformed conversation does not complain;
it returns something empty or wrong, and the failure surfaces as "the product is broken" long
after the change that caused it.

So the rules a template enforces silently are enforced loudly here instead, and the fake uses them.
The intent is that a test which passes has exercised a conversation a real model could have
understood — nothing weaker.
"""

from typing import Any


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
