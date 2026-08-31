"""Adapter implementations and the dialect registry.

Lookup is by dialect, not by provider name. "OpenAI-compatible" is a wire family that several
vendors speak; the adapter is chosen by the wire it has to produce, which is the only thing it
actually knows how to do.

An unregistered dialect raises. Falling back to the OpenAI-compatible adapter because it is the
one that exists would send a Gemini or Anthropic request in the wrong shape and blame the model
for the answer.
"""

from __future__ import annotations

from typing import Any, Callable

from cerebro.harness.adapters.cli_external import CliExternalAgentAdapter
from cerebro.harness.adapters.openai_compatible import OpenAICompatibleAdapter
from cerebro.harness.adapters.openai_dialect import DIALECT_ID as OPENAI_CHAT_DIALECT
from cerebro.harness.exceptions import UnknownDialect

__all__ = [
    "ADAPTER_FACTORIES",
    "CliExternalAgentAdapter",
    "OPENAI_CHAT_DIALECT",
    "OpenAICompatibleAdapter",
    "adapter_factory_for_dialect",
    "supported_dialects",
]

ADAPTER_FACTORIES: dict[str, Callable[..., Any]] = {
    OPENAI_CHAT_DIALECT: OpenAICompatibleAdapter,
}


def supported_dialects() -> list[str]:
    return sorted(ADAPTER_FACTORIES)


def adapter_factory_for_dialect(dialect_id: str) -> Callable[..., Any]:
    """Return the adapter factory for a dialect, or refuse explicitly."""
    try:
        return ADAPTER_FACTORIES[dialect_id]
    except KeyError:
        raise UnknownDialect(
            f"no ProviderAdapter is registered for dialect {dialect_id!r}; "
            f"supported: {supported_dialects()}"
        ) from None
