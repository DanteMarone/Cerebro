"""LM Studio provider — OpenAI-compatible streaming over the local server.

LM Studio 0.4 serves an OpenAI-shaped API on http://127.0.0.1:1234/v1 and batches concurrent
requests to the same model, so the concurrency limit in config.py is a VRAM guard rather than a
protocol one.
"""

from typing import Any
import httpx

from cerebro.providers.openai_compatible import (
    DEFAULT_BASE_URL,
    EMBEDDING_HINTS,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderUnavailable,
    to_chat_messages,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "EMBEDDING_HINTS",
    "LMStudioProvider",
    "OpenAICompatibleProvider",
    "ProviderError",
    "ProviderUnavailable",
    "to_chat_messages",
]


class LMStudioProvider(OpenAICompatibleProvider):
    """Streams completions from a local LM Studio server for one agent."""

    name: str = "lmstudio"

    def __init__(
        self,
        self_id: str,
        model: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 300.0,
        client: httpx.AsyncClient | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            self_id=self_id,
            model=model,
            base_url=base_url,
            name="lmstudio",
            timeout_s=timeout_s,
            client=client,
            **kwargs,
        )
