"""Typed asynchronous persistence helpers for Cerebro v2 over db.py."""

import json
from typing import Any
from cerebro import db


async def _execute_write(sql: str, params: tuple[Any, ...] = ()) -> Any:
    """Helper to enqueue a write and wait for its completion."""
    fut = await db.enqueue_write(sql, params)
    return await fut


def _normalize_agent_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    d = dict(row)
    if d.get("params_json"):
        try:
            pj = json.loads(d["params_json"])
            if isinstance(pj, dict):
                d["tools_enabled"] = pj.get("tools_enabled", [])
                d["system_prompt"] = pj.get("system_prompt", "")
                d["params"] = {
                    k: v for k, v in pj.items() if k not in ("tools_enabled", "system_prompt")
                }
            else:
                d["params"] = {}
                d["tools_enabled"] = []
                d["system_prompt"] = ""
        except Exception:
            d["params"] = {}
            d["tools_enabled"] = []
            d["system_prompt"] = ""
    else:
        d["params"] = {}
        d["tools_enabled"] = []
        d["system_prompt"] = ""
    return d


def _normalize_message_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    d = dict(row)
    # Ensure 'content' is accessible as alias to 'body'
    if "body" in d and "content" not in d:
        d["content"] = d["body"]
    if "content" in d and "body" not in d:
        d["body"] = d["content"]
    return d


async def get_agent(agent_id: str) -> dict[str, Any] | None:
    """Retrieve a single agent by ID."""
    row = await db.fetch_one("SELECT * FROM agents WHERE id = ?;", (agent_id,))
    return _normalize_agent_row(row)


async def list_agents() -> list[dict[str, Any]]:
    """List all agents ordered by name."""
    rows = await db.fetch_all("SELECT * FROM agents ORDER BY name ASC;")
    return [_normalize_agent_row(r) for r in rows if r]


async def upsert_agent(agent: dict[str, Any]) -> None:
    """Insert or update an agent definition in SQLite."""
    pj = dict(agent.get("params", {})) if isinstance(agent.get("params"), dict) else {}
    if "tools_enabled" in agent:
        pj["tools_enabled"] = agent["tools_enabled"]
    if "system_prompt" in agent:
        pj["system_prompt"] = agent["system_prompt"]
    params_json = json.dumps(pj)

    sql = """
    INSERT INTO agents (
        id, name, display_name, avatar, role,
        provider, model, params_json, api_key_ref, home_path,
        enabled, delegation_enabled, created_at
    ) VALUES (
        ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?,
        ?, ?, datetime('now')
    )
    ON CONFLICT(id) DO UPDATE SET
        name = excluded.name,
        display_name = excluded.display_name,
        avatar = excluded.avatar,
        role = excluded.role,
        provider = excluded.provider,
        model = excluded.model,
        params_json = excluded.params_json,
        api_key_ref = excluded.api_key_ref,
        home_path = excluded.home_path,
        enabled = excluded.enabled,
        delegation_enabled = excluded.delegation_enabled;
    """
    await _execute_write(
        sql,
        (
            agent["id"],
            agent.get("name", agent["id"]),
            agent.get("display_name", agent["id"].capitalize()),
            agent.get("avatar", "🤖"),
            agent.get("role", "Assistant"),
            agent.get("provider", "lmstudio"),
            agent.get("model", ""),
            params_json,
            agent.get("api_key_ref", ""),
            agent.get("home_path", ""),
            1 if agent.get("enabled", True) else 0,
            1 if agent.get("delegation_enabled") else 0,
        ),
    )


async def get_channel(channel_id: str) -> dict[str, Any] | None:
    """Retrieve a single channel by ID."""
    row = await db.fetch_one("SELECT * FROM channels WHERE id = ?;", (channel_id,))
    if row:
        d = dict(row)
        d["type"] = d.get("kind", "public")
        return d
    return None


async def list_channels() -> list[dict[str, Any]]:
    """List all channels ordered by name."""
    rows = await db.fetch_all("SELECT * FROM channels ORDER BY name ASC;")
    result = []
    for r in rows:
        d = dict(r)
        d["type"] = d.get("kind", "public")
        result.append(d)
    return result


async def create_channel(
    channel_id: str,
    name: str,
    channel_type: str = "public",
    team_id: str = "personal-assistant",
    topic: str = "",
    created_by: str = "dante",
) -> dict[str, Any]:
    """Create a new channel and return its details."""
    sql = """
    INSERT OR IGNORE INTO channels (id, team_id, kind, name, topic, created_by, created_at)
    VALUES (?, ?, ?, ?, ?, ?, datetime('now'));
    """
    await _execute_write(
        sql, (channel_id, team_id, channel_type, name, topic, created_by)
    )
    channel = await get_channel(channel_id)
    return channel or {
        "id": channel_id,
        "team_id": team_id,
        "kind": channel_type,
        "type": channel_type,
        "name": name,
        "topic": topic,
        "created_by": created_by,
    }


async def add_channel_member(
    channel_id: str,
    member_id: str,
    member_kind: str = "agent",
    listen_mode: str = "active",
) -> None:
    """Add an agent or human member to a channel."""
    sql = """
    INSERT OR IGNORE INTO channel_members (
        channel_id, member_id, member_kind, listen_mode, joined_at
    ) VALUES (?, ?, ?, ?, datetime('now'));
    """
    await _execute_write(sql, (channel_id, member_id, member_kind, listen_mode))


async def get_channel_members(channel_id: str) -> list[dict[str, Any]]:
    """Retrieve all members of a channel."""
    sql = """
    SELECT cm.*, a.display_name, a.avatar
    FROM channel_members cm
    LEFT JOIN agents a ON cm.member_id = a.id
    WHERE cm.channel_id = ?
    ORDER BY cm.joined_at ASC;
    """
    rows = await db.fetch_all(sql, (channel_id,))
    result = []
    for r in rows:
        d = dict(r)
        d["agent_id"] = d.get("member_id")
        result.append(d)
    return result


async def append_message(
    channel_id: str,
    author_id: str,
    content: str,
    author_kind: str = "user",
    msg_type: str = "text",
    turn_id: str | None = None,
    quote_msg_id: int | None = None,
    parent_id: int | None = None,
    depth: int = 0,
    meta_json: str | None = None,
) -> int:
    """Append a message to a channel and return its generated ID."""
    qid = quote_msg_id if quote_msg_id is not None else parent_id
    sql = """
    INSERT INTO messages (
        channel_id, author_id, author_kind, kind, body, quote_msg_id,
        turn_id, depth, created_at, meta_json
    ) VALUES (
        ?, ?, ?, ?, ?, ?,
        ?, ?, datetime('now'), ?
    );
    """
    row_id = await _execute_write(
        sql,
        (
            channel_id,
            author_id,
            author_kind,
            msg_type,
            content,
            qid,
            turn_id,
            depth,
            meta_json or "{}",
        ),
    )
    return row_id


async def get_message(message_id: int) -> dict[str, Any] | None:
    """Retrieve a single message by integer ID."""
    row = await db.fetch_one("SELECT * FROM messages WHERE id = ?;", (message_id,))
    return _normalize_message_row(row)


async def list_messages(
    channel_id: str, after_id: int | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    """List messages in a channel, optionally after a message ID."""
    if after_id is not None:
        sql = """
        SELECT * FROM messages
        WHERE channel_id = ? AND id > ?
        ORDER BY id ASC
        LIMIT ?;
        """
        rows = await db.fetch_all(sql, (channel_id, after_id, limit))
    else:
        sql = """
        SELECT * FROM messages
        WHERE channel_id = ?
        ORDER BY id ASC
        LIMIT ?;
        """
        rows = await db.fetch_all(sql, (channel_id, limit))
    return [_normalize_message_row(r) for r in rows if r]
