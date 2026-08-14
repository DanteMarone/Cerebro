"""Import the temporary Markdown war room into a durable Cerebro v2 channel."""

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from cerebro import db, store


HEADING = re.compile(r"^### @(\w+) → @(\w+) · (.+)$")
WARROOM_CHANNEL_ID = "warroom"
WARROOM_TEAM_ID = "cerebro-core"
WARROOM_MEMBERS = ("claude", "antigravity", "codex")
IMPORT_AUTHOR_ID = "transcript-importer"

CLI_AGENT_SEEDS = {
    "claude": {
        "display_name": "Claude",
        "avatar": "C",
        "role": "Architect",
        "model": "claude-code",
        "params": {"backend": "claude"},
    },
    "antigravity": {
        "display_name": "Antigravity",
        "avatar": "A",
        "role": "Executor",
        "model": "gemini-antigravity",
        "params": {"backend": "agy"},
    },
    "codex": {
        "display_name": "Codex",
        "avatar": "X",
        "role": "Reviewer and implementer",
        "model": "codex",
        "params": {"backend": "codex"},
    },
}


@dataclass(frozen=True)
class TranscriptMessage:
    """One parsed message from the append-only Markdown transcript."""

    ordinal: int
    author: str
    recipient: str
    timestamp: str
    body: str


@dataclass(frozen=True)
class ImportResult:
    """Counts and channel identity returned by an import pass."""

    channel_id: str
    parsed: int
    inserted: int
    already_present: int
    corrected_attribution: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable result."""
        return asdict(self)


def parse_transcript(text: str) -> list[TranscriptMessage]:
    """Parse message blocks while ignoring protocol examples inside fenced code."""
    parsed: list[TranscriptMessage] = []
    author = recipient = timestamp = None
    body: list[str] = []
    in_fence = False

    def finish() -> None:
        if author is None or recipient is None or timestamp is None:
            return
        parsed.append(
            TranscriptMessage(
                ordinal=len(parsed) + 1,
                author=author,
                recipient=recipient,
                timestamp=timestamp,
                body="\n".join(body).strip(),
            )
        )

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else HEADING.match(line.strip())
        if match:
            finish()
            author, recipient, timestamp = match.groups()
            body = []
        elif author is not None and line.strip() != "---":
            body.append(line)

    finish()
    return parsed


def read_transcript(path: Path) -> list[TranscriptMessage]:
    """Read and parse one UTF-8 transcript file."""
    return parse_transcript(path.read_text(encoding="utf-8", errors="replace"))


async def _execute_write(sql: str, params: tuple[Any, ...] = ()) -> Any:
    future = await db.enqueue_write(sql, params)
    return await future


async def _ensure_team_and_agents() -> None:
    await _execute_write(
        """
        INSERT OR IGNORE INTO teams (id, slug, name, description, created_at)
        VALUES (?, ?, ?, ?, datetime('now'));
        """,
        (
            WARROOM_TEAM_ID,
            WARROOM_TEAM_ID,
            "Cerebro Core",
            "The team building Cerebro itself.",
        ),
    )

    for agent_id, seed in CLI_AGENT_SEEDS.items():
        if await store.get_agent(agent_id) is None:
            await store.upsert_agent(
                {
                    "id": agent_id,
                    "name": agent_id,
                    "display_name": seed["display_name"],
                    "avatar": seed["avatar"],
                    "role": seed["role"],
                    "provider": "cli_agent",
                    "model": seed["model"],
                    "params": seed["params"],
                    "enabled": True,
                    "delegation_enabled": False,
                }
            )
        await _execute_write(
            """
            INSERT OR IGNORE INTO agent_teams (agent_id, team_id)
            VALUES (?, ?);
            """,
            (agent_id, WARROOM_TEAM_ID),
        )


def _source_identity(message: TranscriptMessage) -> tuple[str, str]:
    canonical = "\n".join(
        (
            message.author,
            message.recipient,
            message.timestamp,
            message.body,
        )
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    turn_id = f"import:warroom:{message.ordinal}:{digest[:16]}"
    return turn_id, digest


async def import_warroom(
    transcript_path: Path,
    channel_id: str = WARROOM_CHANNEL_ID,
) -> ImportResult:
    """Import a transcript snapshot into one owner-visible, idempotent channel."""
    messages = read_transcript(transcript_path)
    source_date = datetime.fromtimestamp(transcript_path.stat().st_mtime).date().isoformat()

    await _ensure_team_and_agents()
    await store.create_channel(
        channel_id=channel_id,
        name="warroom",
        channel_type="war_room",
        team_id=WARROOM_TEAM_ID,
        topic="Cerebro project buildout and coordination",
        created_by="dante",
    )
    for agent_id in WARROOM_MEMBERS:
        await store.add_channel_member(channel_id, agent_id, member_kind="agent")

    inserted = 0
    corrected_attribution = 0
    for message in messages:
        turn_id, digest = _source_identity(message)
        existing = await db.fetch_one(
            "SELECT id, author_id FROM messages WHERE channel_id = ? AND turn_id = ?;",
            (channel_id, turn_id),
        )
        metadata = {
            "recipient": message.recipient,
            "imported": True,
            "source": {
                "path": transcript_path.as_posix(),
                "ordinal": message.ordinal,
                "author": message.author,
                "timestamp": message.timestamp,
                "sha256": digest,
            },
        }
        metadata_json = json.dumps(metadata, sort_keys=True)
        if existing is not None:
            if existing["author_id"] != IMPORT_AUTHOR_ID:
                await _execute_write(
                    """
                    UPDATE messages
                    SET author_id = ?, author_kind = 'system', meta_json = ?
                    WHERE id = ? AND channel_id = ? AND turn_id = ?;
                    """,
                    (
                        IMPORT_AUTHOR_ID,
                        metadata_json,
                        existing["id"],
                        channel_id,
                        turn_id,
                    ),
                )
                corrected_attribution += 1
            continue
        await store.append_message(
            channel_id=channel_id,
            author_id=IMPORT_AUTHOR_ID,
            author_kind="system",
            content=message.body,
            msg_type="chat",
            turn_id=turn_id,
            meta_json=metadata_json,
            created_at=f"{source_date} {message.timestamp}:00",
        )
        inserted += 1

    return ImportResult(
        channel_id=channel_id,
        parsed=len(messages),
        inserted=inserted,
        already_present=len(messages) - inserted,
        corrected_attribution=corrected_attribution,
    )
