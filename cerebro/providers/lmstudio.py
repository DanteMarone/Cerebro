"""LM Studio provider — OpenAI-compatible streaming over the local server.

LM Studio 0.4 serves an OpenAI-shaped API on http://127.0.0.1:1234/v1 and batches concurrent
requests to the same model, so the concurrency limit in config.py is a VRAM guard rather than a
protocol one.

Two things here are less obvious than they look.

**Who said what.** The provider is constructed for one agent and told its own id. In a channel
with several agents, only that agent's own past messages may be presented as `assistant`;
everything else -- Dante and every peer -- is a `user` turn prefixed with the speaker's name.
Presenting a peer's message as `assistant` makes the model believe it already said things it never
said, and it will contradict itself or continue the other agent's sentence.

**Streamed tool calls arrive in fragments.** OpenAI-shaped streams emit tool calls as indexed
pieces: the id and function name usually land in the first fragment, the JSON arguments dribble in
across many. We forward fragments as they come and remember the id/name per index so later
fragments stay attributable; the runtime is responsible for concatenating and parsing.
"""

import json
from typing import Any, AsyncIterator

import httpx

from cerebro.models import Delta, Done, Message, TextDelta, ToolCallDelta, Usage
from cerebro.providers.base import Params, ToolSpec

DEFAULT_BASE_URL = "http://127.0.0.1:1234"
EMBEDDING_HINTS = ("embed", "embedding")


class ProviderError(RuntimeError):
    """A provider call failed in a way the agent should see and can reason about."""


class ProviderUnavailable(ProviderError):
    """The backend is not reachable. Distinct because the UI shows it differently."""


def _role_for(message: Message, self_id: str) -> str:
    if message.author_kind == "system":
        return "system"
    if message.author_kind == "agent" and message.author_id == self_id:
        return "assistant"
    return "user"


def to_chat_messages(messages: list[Message], self_id: str) -> list[dict[str, Any]]:
    """Map Cerebro message rows onto OpenAI chat turns.

    Consecutive turns are not merged: local models cope fine, and merging would lose the speaker
    attribution that multi-agent channels depend on.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = _role_for(msg, self_id)
        body = msg.body
        if role == "user" and msg.author_kind == "agent":
            body = f"{msg.author_id}: {body}"
        out.append({"role": role, "content": body})
    return out


def _tools_payload(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in tools
    ]


class LMStudioProvider:
    """Streams completions from a local LM Studio server for one agent."""

    name = "lmstudio"

    def __init__(
        self,
        self_id: str,
        model: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 300.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.self_id = self_id
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._model = model or None
        self._client = client
        self._owns_client = client is None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    # -- model resolution ---------------------------------------------------------

    async def list_models(self) -> list[str]:
        client = await self._http()
        try:
            resp = await client.get(f"{self.base_url}/v1/models")
        except httpx.ConnectError as exc:
            raise ProviderUnavailable(
                f"LM Studio is not reachable at {self.base_url} — is the server running?"
            ) from exc
        resp.raise_for_status()
        return [m["id"] for m in resp.json().get("data", [])]

    async def resolve_model(self) -> str:
        """An agent with no model configured uses whatever LM Studio has loaded."""
        if self._model:
            return self._model
        available = [
            m for m in await self.list_models()
            if not any(h in m.lower() for h in EMBEDDING_HINTS)
        ]
        if not available:
            raise ProviderUnavailable(
                "LM Studio has no chat model loaded — only embedding models are available."
            )
        self._model = available[0]
        return self._model

    # -- streaming ----------------------------------------------------------------

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        params: Params,
    ) -> AsyncIterator[Delta]:
        model = await self.resolve_model()
        payload: dict[str, Any] = {
            "model": model,
            "messages": to_chat_messages(messages, self.self_id),
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": params.temperature,
        }
        if params.max_tokens:
            payload["max_tokens"] = params.max_tokens
        if params.stop:
            payload["stop"] = params.stop
        if tools:
            payload["tools"] = _tools_payload(tools)

        client = await self._http()
        seen_tools: dict[int, tuple[str, str]] = {}
        finish_reason = "stop"

        try:
            async with client.stream(
                "POST", f"{self.base_url}/v1/chat/completions", json=payload
            ) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "replace")[:500]
                    raise ProviderError(f"LM Studio returned {resp.status_code}: {detail}")

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        # A malformed frame is not worth killing a turn over.
                        continue

                    if usage := chunk.get("usage"):
                        yield Usage(
                            input=usage.get("prompt_tokens", 0),
                            output=usage.get("completion_tokens", 0),
                        )

                    for choice in chunk.get("choices", []):
                        if reason := choice.get("finish_reason"):
                            finish_reason = reason
                        delta = choice.get("delta") or {}

                        if text := delta.get("content"):
                            yield TextDelta(text=text)

                        for frag in delta.get("tool_calls") or []:
                            index = frag.get("index", 0)
                            fn = frag.get("function") or {}
                            call_id, name = seen_tools.get(index, ("", ""))
                            call_id = frag.get("id") or call_id
                            name = fn.get("name") or name
                            seen_tools[index] = (call_id, name)
                            yield ToolCallDelta(
                                id=call_id or f"call_{index}",
                                name=name,
                                args_fragment=fn.get("arguments") or "",
                            )
        except httpx.ConnectError as exc:
            raise ProviderUnavailable(
                f"LM Studio is not reachable at {self.base_url} — is the server running?"
            ) from exc
        except httpx.ReadTimeout as exc:
            raise ProviderError(
                f"LM Studio stopped responding after {self.timeout_s:.0f}s."
            ) from exc

        yield Done(reason=finish_reason)
