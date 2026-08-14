# Slice 3 — Resident agents (executor brief)

**Branch**: `v2` · **Lead**: Codex · **Architect**: Claude · **Authority**:
[CEREBRO_V2_ARCHITECTURE.md](../CEREBRO_V2_ARCHITECTURE.md) §6, §8.8, §9.3.

The goal, in one sentence: **Cerebro runs the agents.** No Claude Code window, no Antigravity chat,
no Codex session — Dante opens Cerebro, types, and the team answers because Cerebro invoked it.

## Why this and not MCP

§13 has MCP next. It moves again, for the same reason it moved last time: the thing Dante keeps
asking for is not more tools, it is a team that exists when he isn't holding it up.

Today "Claude is awake" means "a Claude Code window is open." That is why Antigravity went silent
until prodded, why Codex being asleep required promoting me mid-task, and why three agents are each
hand-rolling a channel watcher — three implementations of something that should be one, none of
which survive their session closing. Tools on top of that are tools on sand.

| Slice | Was | Now |
| :--- | :--- | :--- |
| 3 | Polling + speaking | **Resident agents** (`cli_agent` provider + internal polling) |
| 4 | MCP + core tools | MCP + core tools, with §8.8 tiers enforced in the tool layer |

---

## Part A — The `cli_agent` provider (Claude)

`cerebro/providers/cli_agent.py`, implementing the same `Provider` protocol as LM Studio. Mine
because it spawns processes, and because a mistake here is a hung turn or a runaway subprocess.

- One subprocess per turn: `claude -p` / `agy`, cwd and timeout from the profile.
- Context packet in on stdin; stdout streamed back as `TextDelta`. Stderr captured for the error
  path, never mixed into the reply.
- Non-zero exit, timeout, or a missing binary becomes an in-channel error message, never a crash
  and never a silent nothing.
- The process is killed on turn cancellation — the §8.6 kill switch must actually kill.
- Budgets (§8.5) apply per invocation. A resident agent woken on a timer is the first thing in this
  system that can spend money while nobody watches.

**Acceptance**: with no CLI session open anywhere, Dante posts in `#warroom`, Cerebro spawns the
agent, and the reply streams into the browser authored by that agent. Killing Cerebro mid-turn
leaves no orphaned process.

## Part B — Internal polling (Claude)

`cerebro/poller.py` and the §6 speaking rule, replacing every hand-rolled watcher.

- Each agent has `poll_interval_s` (default 45) and a per-channel `last_seen_message_id`.
- On a tick, an agent with unseen messages in a channel it belongs to takes **one** turn covering
  all of them — batching is what makes N agents affordable.
- `@mention` bypasses the interval and wakes the agent immediately.
- Deciding and speaking are the same call: the agent replies `PASS` to stay silent, and `PASS` is
  discarded rather than persisted.
- Turn caps (§8.4) bound everything; a poll-produced reply still carries `turn_id` and `depth`.

**Acceptance**: with all CLI sessions closed, a message sits in a channel and is answered within
one poll interval. Two agents told to always mention each other are frozen by the caps. An agent
with nothing to add produces no message and no row.

## Part C — Trust tiers enforced, not merely declared (Antigravity)

§8.8 exists in the documents and the profiles; nothing enforces it yet.

- `tools_for(agent)` filters by `profile.trust` and `tools_enabled`. A `sandboxed` agent must not
  receive `run_command`, `fs_write` outside its own roots, `delegate_coding_task` or `publish_tool`
  in its catalog at all — not offered and refused, but absent.
- Filesystem tools resolve and check paths against the agent's permitted roots, after
  normalisation. `..` must not escape.
- New agents default to `sandboxed` when the profile omits `trust`.
- UI: the trust tier and provider are visible on the agent card. Dante should be able to see at a
  glance which agents can touch his machine.

**Acceptance**: Jarvis cannot call `run_command` — it is not in its catalogue. A path traversal out
of its workspace is refused. A profile with no `trust` field behaves as `sandboxed`.

## Part D — Proofs (Codex)

- A sandboxed agent cannot reach the shell, cannot write outside its roots, and cannot escape by
  traversal, by symlink, or by an absolute path.
- A resident agent's messages are authored by that agent (§6.2) with no CLI session involved.
- Killing Cerebro mid-turn orphans nothing.
- Each mutation-proven: break the guard, watch the test go red, restore.

---

## Rules carried forward

- Cron stays **off** for `cli_agent` members until Dante has watched resident agents behave. Being
  woken on a timer with a full harness and no human in the room is the one genuinely irreversible
  thing in this design.
- Browser surfaces verified in a browser.
- Stage explicit paths; take a `file:` lease outside your part; an announcement is not a lock.
- Report what happened, including what failed.

## Acceptance for the slice

Dante closes every CLI window, posts in `#warroom`, and gets answers. `scripts/watch_*.py` are
deleted, because nothing needs them. Suite green and terminating, flake8 clean, cooldown passing,
and every number produced by running something.
