"""The in-process core tools (§10.2), and the trust tiers that gate them (§8.8).

An agent that can only talk is a chatbot with colleagues. These are the first things a Cerebro
agent can actually *do*, and deliberately the smallest useful set: read and write its own notes,
and remember something across turns. A `cli_agent` is a fresh process every time it wakes, so
without these its memory of yesterday is whatever happens to still be in the channel.

**Trust is enforced here, not requested here.** §8.8 says a sandboxed agent must not be *offered*
`run_command` rather than be refused when it asks — a model that can see a capability in its
catalogue will eventually try it, and a refusal is a worse conversation than an absence. So the
catalogue is filtered per agent before the model ever sees it, and every path is additionally
confined at execution time. Dante's words: "The local agents have not proven themselves to not
totally fuck up my system."

Everything an agent writes lands inside its own home. There is no tool here that can touch
anything else, which is why this set is safe to give a 12B model today and why the dangerous ones
(`run_command`, `delegate_coding_task`, `publish_tool`) are not in this file at all.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from cerebro.models import Agent
from cerebro.providers.base import ToolSpec

MAX_NOTE_CHARS = 20_000
MAX_SCRATCHPAD_CHARS = 40_000

# §8.8. Tier -> the tools an agent at that tier may be offered.
TIER_TOOLS: dict[str, set[str]] = {
    "sandboxed": {"scratchpad_read", "scratchpad_append", "memory_write", "memory_list",
                  "memory_read"},
    "standard": {"scratchpad_read", "scratchpad_append", "memory_write", "memory_list",
                 "memory_read"},
    "full": {"scratchpad_read", "scratchpad_append", "memory_write", "memory_list",
             "memory_read"},
}
DEFAULT_TIER = "sandboxed"


class ToolError(Exception):
    """A refusal the agent should see and be able to reason about."""


@dataclass(frozen=True, slots=True)
class Tool:
    spec: ToolSpec
    run: Callable[[Agent, dict[str, Any]], str]


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
    """A note name that cannot escape the memory directory.

    Rejects rather than sanitises: silently rewriting `../../etc/passwd` into `etcpasswd` would
    hide an attempt worth seeing in the audit log.
    """
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


class CoreTools:
    """Builds the per-agent catalogue and executes calls against it."""

    def __init__(self, agents_root: Path) -> None:
        self.agents_root = Path(agents_root).resolve()
        self._tools = {t.spec.name: t for t in self._build()}

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
            # Belt and braces: the catalogue already excluded it, so reaching here means the model
            # invented a tool name or something upstream leaked one.
            return f"error: '{name}' is not available to {agent.id}."
        tool = self._tools.get(name)
        if tool is None:
            return f"error: no such tool '{name}'."
        try:
            return tool.run(agent, args)
        except ToolError as exc:
            return f"error: {exc}"
        except OSError as exc:
            return f"error: {exc}"

    # -- the tools ----------------------------------------------------------------

    def _build(self) -> list[Tool]:
        return [
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
            # Keep the recent end. A scratchpad is a working memory, not an archive; that is what
            # memory notes are for.
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
