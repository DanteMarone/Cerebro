"""Provider Protocol and parameter models for Cerebro v2."""

from typing import Any, AsyncIterator, Protocol
from pydantic import BaseModel

from cerebro.models import Delta, Message


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class Params(BaseModel):
    temperature: float = 0.7
    max_tokens: int | None = None
    stop: list[str] | None = None


class Provider(Protocol):
    name: str

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec],
        params: Params,
    ) -> AsyncIterator[Delta]:
        ...
