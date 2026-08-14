"""Typed asynchronous persistence helpers for Cerebro v2 over db.py."""

from datetime import datetime, timedelta, timezone
import json
from typing import Any
from cerebro import db
from cerebro.models import Lease, LeaseConflictError

VALID_MESSAGE_KINDS = {"chat", "system", "tool", "event", "error"}


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
                    k: v
                    for k, v in pj.items()
                    if k not in ("tools_enabled", "system_prompt")
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
    try:
        metadata = json.loads(d.get("meta_json") or "{}")
    except (TypeError, ValueError):
        metadata = {}
    source = metadata.get("source") if isinstance(metadata, dict) else None
    if (
        isinstance(metadata, dict)
        and metadata.get("imported")
        and isinstance(source, dict)
        and source.get("author")
    ):
        d["display_author_id"] = source["author"]
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
    pj = (
        dict(agent.get("params", {}))
        if isinstance(agent.get("params"), dict)
        else {}
    )
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
    kind: str | None = None,
) -> dict[str, Any]:
    """Create a new channel and guarantee Dante is an owner member."""
    actual_kind = kind if kind is not None else channel_type
    sql = """
    INSERT OR IGNORE INTO channels (id, team_id, kind, name, topic, created_by, created_at)
    VALUES (?, ?, ?, ?, ?, ?, datetime('now'));
    """
    await _execute_write(
        sql, (channel_id, team_id, actual_kind, name, topic, created_by)
    )
    # Enforce §6.1 invariant: Dante is always a member of every channel
    await add_channel_member(
        channel_id=channel_id,
        member_id="dante",
        member_kind="user",
        listen_mode="active",
    )
    ch = await get_channel(channel_id)
    return ch or {
        "id": channel_id,
        "team_id": team_id,
        "kind": actual_kind,
        "type": actual_kind,
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


async def remove_channel_member(channel_id: str, member_id: str) -> None:
    """Remove a member from a channel. Enforces §6.1: Dante cannot be removed."""
    if member_id.lower() == "dante":
        raise ValueError("Cannot remove owner 'dante' from channel (§6.1 invariant)")
    sql = "DELETE FROM channel_members WHERE channel_id = ? AND member_id = ?;"
    await _execute_write(sql, (channel_id, member_id))


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


async def update_read_cursor(
    channel_id: str,
    member_id: str,
    message_id: int,
) -> None:
    """Update a member's last read message pointer in a channel (§6)."""
    sql = """
    UPDATE channel_members
    SET last_read_message_id = MAX(COALESCE(last_read_message_id, 0), ?)
    WHERE channel_id = ? AND member_id = ?;
    """
    await _execute_write(sql, (message_id, channel_id, member_id))


async def get_unread_count(channel_id: str, member_id: str) -> int:
    """Return the count of messages in channel_id with id > member's last_read_message_id."""
    sql = """
    SELECT COUNT(*) as count
    FROM messages
    WHERE channel_id = ?
      AND id > (
          SELECT COALESCE(last_read_message_id, 0)
          FROM channel_members
          WHERE channel_id = ? AND member_id = ?
      );
    """
    row = await db.fetch_one(sql, (channel_id, channel_id, member_id))
    return int(row["count"]) if row and row.get("count") is not None else 0


async def append_message(
    channel_id: str,
    author_id: str,
    content: str,
    author_kind: str = "user",
    msg_type: str = "chat",
    turn_id: str | None = None,
    quote_msg_id: int | None = None,
    parent_id: int | None = None,
    depth: int = 0,
    meta_json: str | None = None,
    created_at: str | None = None,
) -> int:
    """Append a message to a channel and return its generated ID."""
    qid = quote_msg_id if quote_msg_id is not None else parent_id
    kind = msg_type if msg_type in VALID_MESSAGE_KINDS else "chat"
    sql = """
    INSERT INTO messages (
        channel_id, author_id, author_kind, kind, body, quote_msg_id,
        turn_id, depth, created_at, meta_json
    ) VALUES (
        ?, ?, ?, ?, ?, ?,
        ?, ?, COALESCE(?, datetime('now')), ?
    );
    """
    row_id = await _execute_write(
        sql,
        (
            channel_id,
            author_id,
            author_kind,
            kind,
            content,
            qid,
            turn_id,
            depth,
            created_at,
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
    """List messages in a channel.

    When after_id is provided, returns messages > after_id in ascending order.
    When after_id is None, returns the most recent `limit` messages in ascending order.
    """
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
        SELECT * FROM (
            SELECT * FROM messages
            WHERE channel_id = ?
            ORDER BY id DESC
            LIMIT ?
        ) ORDER BY id ASC;
        """
        rows = await db.fetch_all(sql, (channel_id, limit))
    return [_normalize_message_row(r) for r in rows if r]


# --- Leases (§8.7) ---

async def acquire_lease(
    resource: str,
    holder_id: str,
    holder_kind: str = "agent",
    ttl_s: int = 600,
    reason: str = "",
    channel_id: str | None = None,
    is_owner: bool = False,
) -> Lease:
    """Atomically acquire or re-acquire a lease inside a single writer transaction."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    expires_at = (now_dt + timedelta(seconds=ttl_s)).isoformat()

    async def _tx(conn: Any) -> Lease:
        cur = await conn.execute("SELECT * FROM leases WHERE resource = ?;", (resource,))
        existing = await cur.fetchone()
        if existing:
            if existing["expires_at"] > now:
                if existing["holder_id"] != holder_id and not is_owner:
                    raise LeaseConflictError(
                        resource=resource,
                        holder_id=existing["holder_id"],
                        expires_at=existing["expires_at"],
                        reason=existing["reason"] or "",
                    )
            await conn.execute(
                """
                UPDATE leases
                SET holder_id = ?, holder_kind = ?, channel_id = ?, reason = ?,
                    acquired_at = ?, expires_at = ?
                WHERE resource = ?;
                """,
                (holder_id, holder_kind, channel_id, reason, now, expires_at, resource),
            )
        else:
            await conn.execute(
                """
                INSERT INTO leases (
                    resource, holder_id, holder_kind, channel_id, reason, acquired_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (resource, holder_id, holder_kind, channel_id, reason, now, expires_at),
            )
        return Lease(
            resource=resource,
            holder_id=holder_id,
            holder_kind=holder_kind,
            channel_id=channel_id,
            reason=reason,
            acquired_at=now,
            expires_at=expires_at,
        )

    return await db.run_in_writer(_tx)


async def release_lease(resource: str, holder_id: str, is_owner: bool = False) -> bool:
    """Atomically release a lease inside a single writer transaction. Only holder or owner may release."""
    now = datetime.now(timezone.utc).isoformat()

    async def _tx(conn: Any) -> bool:
        cur = await conn.execute("SELECT * FROM leases WHERE resource = ?;", (resource,))
        existing = await cur.fetchone()
        if not existing:
            return False
        if existing["expires_at"] > now and existing["holder_id"] != holder_id and not is_owner:
            raise LeaseConflictError(
                resource=resource,
                holder_id=existing["holder_id"],
                expires_at=existing["expires_at"],
                reason=existing["reason"] or "",
            )
        cur_del = await conn.execute("DELETE FROM leases WHERE resource = ?;", (resource,))
        return cur_del.rowcount > 0

    return await db.run_in_writer(_tx)


async def renew_lease(
    resource: str,
    holder_id: str,
    ttl_s: int = 600,
    is_owner: bool = False,
) -> Lease:
    """Atomically extend the expiration time of an active lease in a single writer transaction."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    expires_at = (now_dt + timedelta(seconds=ttl_s)).isoformat()

    async def _tx(conn: Any) -> Lease:
        cur = await conn.execute("SELECT * FROM leases WHERE resource = ?;", (resource,))
        existing = await cur.fetchone()
        if not existing or existing["expires_at"] <= now:
            raise LeaseConflictError(
                resource=resource,
                holder_id=existing["holder_id"] if existing else "none",
                expires_at=existing["expires_at"] if existing else now,
                reason="Lease does not exist or has expired",
            )
        if existing["holder_id"] != holder_id and not is_owner:
            raise LeaseConflictError(
                resource=resource,
                holder_id=existing["holder_id"],
                expires_at=existing["expires_at"],
                reason=existing["reason"] or "",
            )
        await conn.execute(
            "UPDATE leases SET expires_at = ? WHERE resource = ?;",
            (expires_at, resource),
        )
        return Lease(
            resource=existing["resource"],
            holder_id=existing["holder_id"],
            holder_kind=existing["holder_kind"],
            channel_id=existing["channel_id"],
            reason=existing["reason"] or "",
            acquired_at=existing["acquired_at"],
            expires_at=expires_at,
        )

    return await db.run_in_writer(_tx)


async def list_leases(include_expired: bool = False, hub: Any = None) -> list[Lease]:
    """List all active leases, or all including expired if requested. Performs lazy sweep."""
    if not include_expired:
        await sweep_expired_leases(hub=hub)
    now = datetime.now(timezone.utc).isoformat()
    if include_expired:
        rows = await db.fetch_all("SELECT * FROM leases ORDER BY acquired_at ASC;")
    else:
        sql = "SELECT * FROM leases WHERE expires_at > ? ORDER BY acquired_at ASC;"
        rows = await db.fetch_all(sql, (now,))
    return [Lease(**r) for r in rows if r]


async def get_lease(resource: str, include_expired: bool = False) -> Lease | None:
    """Retrieve an active lease on a specific resource."""
    now = datetime.now(timezone.utc).isoformat()
    row = await db.fetch_one("SELECT * FROM leases WHERE resource = ?;", (resource,))
    if not row:
        return None
    if not include_expired and row["expires_at"] <= now:
        return None
    return Lease(**row)


async def sweep_expired_leases(hub: Any = None) -> list[str]:
    """Atomically delete all expired leases from the database and publish lease.expired events."""
    now = datetime.now(timezone.utc).isoformat()

    async def _tx(conn: Any) -> list[dict[str, Any]]:
        cur = await conn.execute(
            "SELECT resource, holder_id, channel_id FROM leases WHERE expires_at <= ?;",
            (now,),
        )
        rows = await cur.fetchall()
        if not rows:
            return []
        expired_list = [dict(r) for r in rows]
        await conn.execute("DELETE FROM leases WHERE expires_at <= ?;", (now,))
        return expired_list

    expired_entries = await db.run_in_writer(_tx)
    if not expired_entries:
        return []

    resources = [e["resource"] for e in expired_entries]
    if hub is not None:
        for entry in expired_entries:
            try:
                await hub.publish(
                    "lease.expired",
                    {
                        "resource": entry["resource"],
                        "holder_id": entry["holder_id"],
                        "channel_id": entry.get("channel_id"),
                        "expired_at": now,
                    },
                )
            except Exception:
                pass
    return resources
