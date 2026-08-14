"""Adapter between the runtime's `Persistence` protocol and the `store` module.

The store speaks dict rows and keyword arguments; the runtime speaks `Message` models. Rather
than bend either side, the seam is explicit and lives here.
"""

from pathlib import Path

from cerebro import db, store
from cerebro.config import settings
from cerebro.models import Agent, Message

DEFAULT_PROMPT = (
    "You are a Cerebro agent. Answer concisely and say plainly when you do not know something."
)


class StoreAdapter:
    """Implements the four methods `AgentRuntime` needs."""

    async def append_message(self, message: Message) -> Message:
        message_id = await store.append_message(
            channel_id=message.channel_id,
            author_id=message.author_id,
            content=message.body,
            author_kind=message.author_kind,
            msg_type=message.kind,
            turn_id=message.turn_id,
            quote_msg_id=message.quote_msg_id,
            depth=message.depth,
            meta_json=message.meta_json,
        )
        message.id = message_id
        row = await store.get_message(message_id)
        return Message(**_message_fields(row)) if row else message

    async def update_message_body(self, message_id: int, body: str) -> None:
        future = await db.enqueue_write(
            "UPDATE messages SET body = ? WHERE id = ?;", (body, message_id)
        )
        await future

    async def history(self, channel_id: str, limit: int) -> list[Message]:
        """The most recent `limit` messages, oldest first.

        Deliberately not `store.list_messages`, which returns the *first* rows in a channel --
        correct for pagination from the top, wrong for a context window.
        """
        rows = await db.fetch_all(
            "SELECT * FROM messages WHERE channel_id = ? ORDER BY id DESC LIMIT ?;",
            (channel_id, limit),
        )
        return [Message(**_message_fields(r)) for r in reversed(rows)]

    async def system_prompt(self, agent: Agent) -> str:
        home = Path(agent.home_path) if agent.home_path else settings.agents_path / agent.id
        prompt_file = home / "system_prompt.md"
        try:
            text = prompt_file.read_text(encoding="utf-8").strip()
        except OSError:
            return DEFAULT_PROMPT
        return text or DEFAULT_PROMPT


def _message_fields(row: dict) -> dict:
    """Keep only columns `Message` declares; the store adds a `content` alias."""
    allowed = set(Message.model_fields)
    return {k: v for k, v in row.items() if k in allowed}
