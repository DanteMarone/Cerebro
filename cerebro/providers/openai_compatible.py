"""OpenAI-compatible streaming provider for Cerebro v2.

Supports LM Studio, OpenRouter, DeepSeek, GLM, and any endpoint conforming to the
OpenAI chat completions streaming protocol.
"""

import json
from typing import Any, AsyncIterator

import httpx

from cerebro.models import (
    Delta,
    Done,
    Message,
    ReasoningDelta,
    TextDelta,
    ToolCallDelta,
    Usage,
)
from cerebro.providers.base import Params, ToolSpec

EMBEDDING_HINTS = ("embed", "embedding")
DEFAULT_BASE_URL = "http://127.0.0.1:1234"

PROVIDER_PRESETS: dict[str, str] = {
    "lmstudio": "http://127.0.0.1:1234",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "openai": "https://api.openai.com/v1",
}


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

    Tool rounds have a required shape: an assistant turn carrying `tool_calls`, then one `tool`
    turn per call carrying the matching `tool_call_id`. Codex refuted the first version of this,
    which emitted an empty assistant message and put the result in a system turn — a sequence no
    model is obliged to understand, and which the protocol forbids.

    The call and result travel in `meta_json` because the message table stores conversation, not
    protocol. That is a seam worth naming: the Provider protocol takes database rows, which cannot
    natively express a tool call. It was flagged in Slice 1 and deferred, and this is the bill.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        meta = _meta(msg)

        if msg.kind == "tool":
            # A tool result. Without the id the model cannot match it to what it asked for.
            out.append({
                "role": "tool",
                "tool_call_id": meta.get("tool_call_id", ""),
                "content": msg.body,
            })
            continue

        role = _role_for(msg, self_id)
        tool_calls = meta.get("tool_calls")

        if role == "assistant" and tool_calls:
            # content may legitimately be empty here: the turn *is* the tool call.
            out.append({
                "role": "assistant",
                "content": msg.body or None,
                "tool_calls": tool_calls,
            })
            continue

        if not (msg.body or "").strip() and role == "assistant":
            # An empty assistant turn with nothing attached says nothing and confuses templates.
            continue

        body = msg.body
        if role == "user" and msg.author_kind == "agent":
            body = f"{msg.author_id}: {body}"
        out.append({"role": role, "content": body})
    return out


def _meta(msg: Message) -> dict[str, Any]:
    if not msg.meta_json:
        return {}
    try:
        loaded = json.loads(msg.meta_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


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


class OpenAICompatibleProvider:
    """Streams completions from any OpenAI-compatible server for one agent."""

    name: str = "openai_compatible"

    def __init__(
        self,
        self_id: str,
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        name: str | None = None,
        timeout_s: float = 300.0,
        client: httpx.AsyncClient | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if name is not None:
            self.name = name
        self.self_id = self_id
        resolved_url = base_url or PROVIDER_PRESETS.get(self.name, "http://127.0.0.1:1234")
        self.base_url = resolved_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._model = model or None
        self._client = client
        self._owns_client = client is None
        self._custom_headers = dict(headers or {})

    def _get_headers(self) -> dict[str, str]:
        hdrs = dict(self._custom_headers)
        if self.api_key:
            hdrs["Authorization"] = f"Bearer {self.api_key}"
        if "openrouter.ai" in self.base_url:
            hdrs.setdefault("HTTP-Referer", "http://127.0.0.1:8765")
            hdrs.setdefault("X-Title", "Cerebro")
        return hdrs

    def _endpoint(self, path: str) -> str:
        clean_path = path.lstrip("/")
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/{clean_path}"
        return f"{self.base_url}/v1/{clean_path}"

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_s,
                headers=self._get_headers(),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    # -- model resolution ---------------------------------------------------------

    async def list_models(self) -> list[str]:
        client = await self._http()
        url = self._endpoint("models")
        try:
            resp = await client.get(url, headers=self._get_headers())
        except httpx.ConnectError as exc:
            raise ProviderUnavailable(
                f"{self.name} is not reachable at {self.base_url} — is the service online?"
            ) from exc
        resp.raise_for_status()
        return [m["id"] for m in resp.json().get("data", [])]

    async def resolve_model(self) -> str:
        """An agent with no model configured uses the first non-embedding model available."""
        if self._model:
            return self._model
        available = [
            m for m in await self.list_models()
            if not any(h in m.lower() for h in EMBEDDING_HINTS)
        ]
        if not available:
            raise ProviderUnavailable(
                f"{self.name} has no chat model available — only embedding models were found."
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
        url = self._endpoint("chat/completions")

        try:
            async with client.stream(
                "POST", url, json=payload, headers=self._get_headers()
            ) as resp:
                if resp.status_code >= 400:
                    detail = (await resp.aread()).decode("utf-8", "replace")[:500]
                    raise ProviderError(f"{self.name} returned {resp.status_code}: {detail}")

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
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

                        thought = delta.get("reasoning") or delta.get("reasoning_content")
                        if thought:
                            yield ReasoningDelta(text=thought)

                        if text := delta.get("content"):
                            yield TextDelta(text=text)

                        for frag in delta.get("tool_calls") or []:
                            index = frag.get("index", 0)
                            fn = frag.get("function") or {}
                            call_id, fname = seen_tools.get(index, ("", ""))
                            call_id = frag.get("id") or call_id
                            fname = fn.get("name") or fname
                            seen_tools[index] = (call_id, fname)
                            yield ToolCallDelta(
                                id=call_id or f"call_{index}",
                                name=fname,
                                args_fragment=fn.get("arguments") or "",
                            )
        except httpx.ConnectError as exc:
            raise ProviderUnavailable(
                f"{self.name} is not reachable at {self.base_url} — is the service online?"
            ) from exc
        except httpx.ReadTimeout as exc:
            raise ProviderError(
                f"{self.name} stopped responding after {self.timeout_s:.0f}s."
            ) from exc

        yield Done(reason=finish_reason)
