"""Tests for importing the temporary Markdown war room into Cerebro v2."""

import json

import pytest

from cerebro import db, store
from cerebro.config import Settings
from cerebro.transcript_import import import_warroom, parse_transcript


SAMPLE = """# #slice0 — war room

```text
### @example → @everyone · 00:00
This is documentation, not a message.
```

---
### @dante → @everyone · 00:01
Hello team.

---
### @codex → @claude · 00:02

> Hello team.

Ready to work.
"""


def test_parse_transcript_ignores_fenced_protocol_example():
    """Only real transcript blocks become messages."""
    messages = parse_transcript(SAMPLE)

    assert len(messages) == 2
    assert messages[0].author == "dante"
    assert messages[0].recipient == "everyone"
    assert messages[1].body == "> Hello team.\n\nReady to work."


@pytest.mark.asyncio
async def test_import_warroom_is_idempotent_and_preserves_source(
    tmp_path,
    test_db: Settings,
):
    """The importer preserves the transcript and does not duplicate it on rerun."""
    transcript = tmp_path / "slice0.md"
    transcript.write_text(SAMPLE, encoding="utf-8")

    first = await import_warroom(transcript)
    second = await import_warroom(transcript)

    assert first.parsed == 2
    assert first.inserted == 2
    assert first.corrected_attribution == 0
    assert second.inserted == 0
    assert second.already_present == 2
    assert second.corrected_attribution == 0

    channel = await store.get_channel("warroom")
    assert channel is not None
    assert channel["kind"] == "war_room"
    members = await store.get_channel_members("warroom")
    assert {member["member_id"] for member in members} == {
        "dante",
        "claude",
        "antigravity",
        "codex",
    }

    rows = await db.fetch_all(
        "SELECT * FROM messages WHERE channel_id = ? ORDER BY id ASC;",
        ("warroom",),
    )
    assert [row["author_id"] for row in rows] == [
        "transcript-importer",
        "transcript-importer",
    ]
    assert {row["author_kind"] for row in rows} == {"system"}
    assert [row["body"] for row in rows] == [
        "Hello team.",
        "> Hello team.\n\nReady to work.",
    ]
    metadata = [json.loads(row["meta_json"]) for row in rows]
    assert [item["source"]["author"] for item in metadata] == ["dante", "codex"]
    assert [item["recipient"] for item in metadata] == ["everyone", "claude"]
    assert [item["source"]["timestamp"] for item in metadata] == ["00:01", "00:02"]
    assert rows[0]["created_at"].endswith("00:01:00")

    normalized = await store.list_messages("warroom")
    assert [message["display_author_id"] for message in normalized] == [
        "dante",
        "codex",
    ]
