"""The in-process core tools (§10.2), and the trust tiers that gate them (§8.8).

An agent that can only talk is a chatbot with colleagues. These are the things a Cerebro
agent can actually *do*: read and write notes, remember across turns, inspect allowed workspace
files, coordinate channels, post messages, and manage tasks.

**Trust is enforced here, not requested here.** §8.8 says a sandboxed agent must not be *offered*
unauthorized capabilities rather than merely be refused when it asks — a model that can see a
capability in its catalogue will eventually try it. So the catalogue is filtered per agent tier
before the model ever sees it, and every path is additionally confined at execution time.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cerebro.models import Agent
from cerebro.providers.base import ToolSpec

MAX_NOTE_CHARS = 20_000
MAX_SCRATCHPAD_CHARS = 40_000
MAX_FS_READ_CHARS = 50_000

# §8.8. Tier -> the tools an agent at that tier may be offered.
TIER_TOOLS: dict[str, set[str]] = {
    "sandboxed": {
        "scratchpad_read", "scratchpad_append", "memory_write", "memory_list", "memory_read",
    },
    "standard": {
        "scratchpad_read", "scratchpad_append", "memory_write", "memory_list", "memory_read",
        "fs_read", "fs_list",
        "list_agents", "get_agent_profile",
        "create_channel", "post_message",
        "task_create", "task_list", "task_get", "task_update",
    },
    "full": {
        "scratchpad_read", "scratchpad_append", "memory_write", "memory_list", "memory_read",
        "fs_read", "fs_list",
        "list_agents", "get_agent_profile",
        "create_channel", "post_message",
        "task_create", "task_list", "task_get", "task_update",
    },
}
DEFAULT_TIER = "sandboxed"


class ToolError(Exception):
    """A refusal the agent should see and be able to reason about."""


@dataclass(frozen=True, slots=True)
class Tool:
    spec: ToolSpec
    run: Callable[[Agent, dict[str, Any]], Any]


def _home(agent: Agent, agents_root: Path) -> Path:
    root = agents_root.resolve()
    base = Path(agent.home_path) if agent.home_path else root / agent.id
    resolved = base.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ToolError(
            f"confinement violation: agent home '{base}' escapes agents root '{root}'"
        )
    return resolved


def _confined_path(parent_dir: Path, target_name: str | Path) -> Path:
    """Ensure the target path is strictly confined under parent_dir after symlink resolution."""
    parent = parent_dir.resolve()
    target = (parent / target_name).resolve()
    try:
        target.relative_to(parent)
    except ValueError:
        raise ToolError(
            f"confinement violation: '{target_name}' escapes allowed directory '{parent}'"
        )
    return target


def _safe_name(name: str) -> str:
    """A note name that cannot escape the memory directory."""
    cleaned = name.strip().replace(" ", "-")
    if (
        not cleaned
        or cleaned != Path(cleaned).name
        or cleaned.startswith(".")
        or "/" in cleaned
        or "\\" in cleaned
    ):
        raise ToolError(
            f"'{name}' is not a usable note name. Use a plain name with no path separators."
        )
    return cleaned if cleaned.endswith(".md") else f"{cleaned}.md"


def _resolve_safe_fs_path(
    agent: Agent,
    agents_root: Path,
    target_path_str: str,
) -> Path:
    """Resolve a target path string and ensure it is strictly confined within:
    1. The agent's own home directory, OR
    2. The project workspace root / agents_root.
    """
    agents_root = agents_root.resolve()
    home = _home(agent, agents_root).resolve()

    target = Path(target_path_str)
    if not target.is_absolute():
        candidates = [
            (agents_root / target).resolve(),
            (home / target).resolve(),
            (agents_root.parent / target).resolve(),
        ]
        resolved = candidates[0]
        for c in candidates:
            if c.exists():
                resolved = c
                break
    else:
        resolved = target.resolve()

    allowed_roots = [home, agents_root, agents_root.parent]
    is_confined = False
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            is_confined = True
            break
        except ValueError:
            pass

    if not is_confined:
        raise ToolError(
            f"confinement violation: '{target_path_str}' escapes allowed workspace '{agents_root}'"
        )
    return resolved


class CoreTools:
    """Builds the per-agent catalogue and executes calls against it."""

    def __init__(
        self,
        agents_root: Path,
        store: Any = None,
        hub: Any = None,
    ) -> None:
        self.agents_root = Path(agents_root).resolve()
        self._store = store
        self._hub = hub
        self._tools = {t.spec.name: t for t in self._build()}

    @property
    def store(self) -> Any:
        if self._store is not None:
            return self._store
        from cerebro import store
        return store

    # -- catalogue ----------------------------------------------------------------

    def tier_of(self, agent: Agent, profile: dict | None = None) -> str:
        """Absent or unrecognised trust defaults to sandboxed, so forgetting fails safe."""
        tier = (profile or {}).get("trust")
        return tier if tier in TIER_TOOLS else DEFAULT_TIER

    def specs_for(self, agent: Agent, profile: dict | None = None) -> list[ToolSpec]:
        allowed = TIER_TOOLS[self.tier_of(agent, profile)]
        return [t.spec for name, t in self._tools.items() if name in allowed]

    async def execute(
        self, agent: Agent, name: str, args: dict[str, Any], profile: dict | None = None
    ) -> str:
        allowed = TIER_TOOLS[self.tier_of(agent, profile)]
        if name not in allowed:
            return f"error: '{name}' is not available to {agent.id}."
        tool = self._tools.get(name)
        if tool is None:
            return f"error: no such tool '{name}'."
        try:
            res = tool.run(agent, args)
            if asyncio.iscoroutine(res):
                return await res
            return str(res)
        except ToolError as exc:
            return f"error: {exc}"
        except OSError as exc:
            return f"error: {exc}"
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"

    # -- the tools ----------------------------------------------------------------

    def _build(self) -> list[Tool]:
        return [
            # 1. Scratchpad
            Tool(
                ToolSpec(
                    name="scratchpad_read",
                    description="Read your own working notes. These are private to you and "
                                "survive between turns.",
                    parameters={"type": "object", "properties": {}},
                ),
                self._scratchpad_read,
            ),
            Tool(
                ToolSpec(
                    name="scratchpad_append",
                    description="Append a line to your working notes. Use this for what you are "
                                "doing, what you are waiting on, and what you learned.",
                    parameters={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                ),
                self._scratchpad_append,
            ),
            # 2. Memory notes
            Tool(
                ToolSpec(
                    name="memory_write",
                    description="Save a durable note that will still matter next week: a "
                                "decision and why, a constraint, how something actually behaves.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "body": {"type": "string"},
                        },
                        "required": ["name", "body"],
                    },
                ),
                self._memory_write,
            ),
            Tool(
                ToolSpec(
                    name="memory_list",
                    description="List the names of your memory notes, most recent first.",
                    parameters={"type": "object", "properties": {}},
                ),
                self._memory_list,
            ),
            Tool(
                ToolSpec(
                    name="memory_read",
                    description="Read one of your memory notes by name.",
                    parameters={
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                ),
                self._memory_read,
            ),
            # 3. Filesystem read/list (standard+)
            Tool(
                ToolSpec(
                    name="fs_read",
                    description="Read the text content of a file within allowed workspace.",
                    parameters={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                ),
                self._fs_read,
            ),
            Tool(
                ToolSpec(
                    name="fs_list",
                    description="List directory entries within allowed workspace.",
                    parameters={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                ),
                self._fs_list,
            ),
            # 4. Agent roster
            Tool(
                ToolSpec(
                    name="list_agents",
                    description="List all registered AI agents in Cerebro.",
                    parameters={"type": "object", "properties": {}},
                ),
                self._list_agents,
            ),
            Tool(
                ToolSpec(
                    name="get_agent_profile",
                    description="Retrieve the profile details of a specific agent.",
                    parameters={
                        "type": "object",
                        "properties": {"agent_id": {"type": "string"}},
                        "required": ["agent_id"],
                    },
                ),
                self._get_agent_profile,
            ),
            # 5. Channel and messaging
            Tool(
                ToolSpec(
                    name="create_channel",
                    description="Create a new topic channel, including Dante and specified participants.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "topic": {"type": "string"},
                            "participants": {"type": "array", "items": {"type": "string"}},
                            "initial_message": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                ),
                self._create_channel,
            ),
            Tool(
                ToolSpec(
                    name="post_message",
                    description="Post a chat message to a specific channel.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "channel": {"type": "string"},
                            "body": {"type": "string"},
                            "quote_msg_id": {"type": "integer"},
                        },
                        "required": ["channel", "body"],
                    },
                ),
                self._post_message,
            ),
            # 6. Tasks
            Tool(
                ToolSpec(
                    name="task_create",
                    description="Create a new durable task in Cerebro.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "description": {"type": "string"},
                            "assignee_id": {"type": "string"},
                            "due_at": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                ),
                self._task_create,
            ),
            Tool(
                ToolSpec(
                    name="task_list",
                    description="List existing tasks, optionally filtered by status.",
                    parameters={
                        "type": "object",
                        "properties": {"status": {"type": "string"}},
                    },
                ),
                self._task_list,
            ),
            Tool(
                ToolSpec(
                    name="task_get",
                    description="Get details of a specific task by ID.",
                    parameters={
                        "type": "object",
                        "properties": {"task_id": {"type": "string"}},
                        "required": ["task_id"],
                    },
                ),
                self._task_get,
            ),
            Tool(
                ToolSpec(
                    name="task_update",
                    description="Update the status or notes of an existing task.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string"},
                            "status": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                        "required": ["task_id"],
                    },
                ),
                self._task_update,
            ),
        ]

    # -- implementations ----------------------------------------------------------

    def _scratchpad_path(self, agent: Agent) -> Path:
        return _confined_path(_home(agent, self.agents_root), "scratchpad.md")

    def _memory_dir(self, agent: Agent) -> Path:
        return _confined_path(_home(agent, self.agents_root), "memory")

    def _scratchpad_read(self, agent: Agent, args: dict) -> str:
        try:
            path = self._scratchpad_path(agent)
            text = path.read_text(encoding="utf-8").strip()
        except ToolError as exc:
            return f"error: {exc}"
        except OSError:
            return "(your scratchpad is empty)"
        return text or "(your scratchpad is empty)"

    def _scratchpad_append(self, agent: Agent, args: dict) -> str:
        text = (args.get("text") or "").strip()
        if not text:
            raise ToolError("nothing to append")
        path = self._scratchpad_path(agent)
        path.parent.mkdir(parents=True, exist_ok=True)

        existing = ""
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            pass
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        updated = f"{existing.rstrip()}\n- [{stamp}] {text}\n".lstrip()
        if len(updated) > MAX_SCRATCHPAD_CHARS:
            updated = "…(older notes trimmed)\n" + updated[-MAX_SCRATCHPAD_CHARS:]
        path.write_text(updated, encoding="utf-8")
        return "noted"

    def _memory_write(self, agent: Agent, args: dict) -> str:
        name = _safe_name(str(args.get("name") or ""))
        body = (args.get("body") or "").strip()
        if not body:
            raise ToolError("a note needs a body")
        if len(body) > MAX_NOTE_CHARS:
            raise ToolError(f"note is too long ({len(body)} chars, limit {MAX_NOTE_CHARS})")

        directory = self._memory_dir(agent)
        directory.mkdir(parents=True, exist_ok=True)
        target = _confined_path(directory, name)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        front = f"---\nwritten: {stamp}\nby: {agent.id}\n---\n\n"
        target.write_text(front + body + "\n", encoding="utf-8")
        return f"saved as {name}"

    def _memory_list(self, agent: Agent, args: dict) -> str:
        directory = self._memory_dir(agent)
        try:
            if not directory.is_dir():
                return "(no memory notes yet)"
            valid_notes = []
            for p in directory.glob("*.md"):
                try:
                    p.resolve().relative_to(directory.resolve())
                    valid_notes.append(p)
                except ValueError:
                    continue
            valid_notes.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return "(no memory notes yet)"
        if not valid_notes:
            return "(no memory notes yet)"
        return json.dumps([n.name for n in valid_notes])

    def _memory_read(self, agent: Agent, args: dict) -> str:
        name = _safe_name(str(args.get("name") or ""))
        directory = self._memory_dir(agent)
        target = _confined_path(directory, name)
        try:
            return target.read_text(encoding="utf-8")
        except OSError:
            raise ToolError(f"no note called {name}") from None

    def _fs_read(self, agent: Agent, args: dict) -> str:
        path_str = str(args.get("path") or "").strip()
        if not path_str:
            raise ToolError("path is required")
        target = _resolve_safe_fs_path(agent, self.agents_root, path_str)
        if not target.is_file():
            raise ToolError(f"file not found: '{path_str}'")
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_FS_READ_CHARS:
            text = text[:MAX_FS_READ_CHARS] + f"\n…(truncated after {MAX_FS_READ_CHARS} chars)"
        return text

    def _fs_list(self, agent: Agent, args: dict) -> str:
        path_str = str(args.get("path") or ".").strip()
        target = _resolve_safe_fs_path(agent, self.agents_root, path_str)
        if not target.is_dir():
            raise ToolError(f"directory not found: '{path_str}'")
        entries = []
        for item in sorted(target.iterdir()):
            try:
                if item.name.startswith(".") and item.name != ".":
                    continue
                entries.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else 0,
                })
            except OSError:
                continue
        return json.dumps(entries)

    async def _list_agents(self, agent: Agent, args: dict) -> str:
        rows = await self.store.list_agents()
        sanitized = []
        for r in rows:
            sanitized.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "display_name": r.get("display_name"),
                "role": r.get("role"),
                "model": r.get("model"),
                "enabled": bool(r.get("enabled")),
            })
        return json.dumps(sanitized)

    async def _get_agent_profile(self, agent: Agent, args: dict) -> str:
        agent_id = str(args.get("agent_id") or "").strip()
        if not agent_id:
            raise ToolError("agent_id is required")
        row = await self.store.get_agent(agent_id)
        if not row:
            raise ToolError(f"agent not found: '{agent_id}'")
        return json.dumps({
            "id": row.get("id"),
            "name": row.get("name"),
            "display_name": row.get("display_name"),
            "role": row.get("role"),
            "model": row.get("model"),
            "provider": row.get("provider"),
            "enabled": bool(row.get("enabled")),
        })

    async def _create_channel(self, agent: Agent, args: dict) -> str:
        name = str(args.get("name") or "").strip().lstrip("#")
        if not name:
            raise ToolError("channel name is required")
        topic = str(args.get("topic") or "").strip()
        raw_participants = args.get("participants") or []
        if isinstance(raw_participants, str):
            raw_participants = [raw_participants]

        member_ids = list(set(["dante", agent.id] + [str(p).strip().lstrip("@") for p in raw_participants if p]))
        channel_id = name.lower().replace(" ", "-")
        created = await self.store.create_channel(
            channel_id=channel_id,
            name=name,
            topic=topic,
            kind="topic",
            created_by=agent.id,
        )
        for member_id in member_ids:
            if member_id != "dante":
                await self.store.add_channel_member(
                    channel_id=channel_id,
                    member_id=member_id,
                    member_kind="agent",
                    listen_mode="active",
                )
        initial_msg = str(args.get("initial_message") or "").strip()
        if initial_msg:
            await self.store.append_message(
                channel_id=created["id"],
                author_id=agent.id,
                content=initial_msg,
                author_kind="agent",
                msg_type="chat",
            )
        return f"created channel #{name} (id: {created['id']})"

    async def _post_message(self, agent: Agent, args: dict) -> str:
        channel_id = str(args.get("channel") or "").strip().lstrip("#")
        body = str(args.get("body") or "").strip()
        if not channel_id:
            raise ToolError("channel is required")
        if not body:
            raise ToolError("body is required")

        quote_msg_id = args.get("quote_msg_id")
        msg_id = await self.store.append_message(
            channel_id=channel_id,
            author_id=agent.id,
            content=body,
            author_kind="agent",
            msg_type="chat",
            quote_msg_id=int(quote_msg_id) if quote_msg_id is not None else None,
        )
        if self._hub is not None:
            await self._hub.publish(
                "message.new",
                {
                    "channel_id": channel_id,
                    "message": {
                        "id": msg_id,
                        "channel_id": channel_id,
                        "author_id": agent.id,
                        "author_kind": "agent",
                        "kind": "chat",
                        "body": body,
                        "quote_msg_id": int(quote_msg_id) if quote_msg_id is not None else None,
                    },
                },
            )
        return f"message posted (id: {msg_id})"

    async def _task_create(self, agent: Agent, args: dict) -> str:
        title = str(args.get("title") or "").strip()
        if not title:
            raise ToolError("task title is required")
        desc = str(args.get("description") or "").strip()
        assignee = args.get("assignee_id")
        task = await self.store.create_task(
            title=title,
            body=desc,
            owner_agent_id=str(assignee) if assignee else agent.id,
            status="pending",
            due_at=args.get("due_at"),
        )
        return f"task created (id: {task['id']})"

    async def _task_list(self, agent: Agent, args: dict) -> str:
        status = args.get("status")
        tasks = await self.store.list_tasks(status=status)
        return json.dumps(tasks)

    async def _task_get(self, agent: Agent, args: dict) -> str:
        task_id = str(args.get("task_id") or "").strip()
        if not task_id:
            raise ToolError("task_id is required")
        task = await self.store.get_task(task_id)
        if not task:
            raise ToolError(f"task not found: '{task_id}'")
        return json.dumps(task)

    async def _task_update(self, agent: Agent, args: dict) -> str:
        task_id = str(args.get("task_id") or "").strip()
        if not task_id:
            raise ToolError("task_id is required")
        status = args.get("status")
        notes = args.get("notes") or args.get("description")
        task = await self.store.update_task(task_id=task_id, status=status, body=notes)
        if not task:
            raise ToolError(f"task not found: '{task_id}'")
        return f"task {task_id} updated (status: {task.get('status')})"
