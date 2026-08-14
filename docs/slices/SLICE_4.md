# Slice 4 — MCP tool layer (executor brief)

**Branch**: `v2` · **Lead**: Antigravity · **Reviewer**: Claude (Codex returns 2026-08-20) ·
**Authority**: [CEREBRO_V2_ARCHITECTURE.md](../CEREBRO_V2_ARCHITECTURE.md) D1, §8.8, §10.

The goal, in one sentence: **an agent can use a tool that Cerebro did not write.**

D1 has been the shape of this architecture since the first draft and is still a diagram. Everything
built since Slice 3 — leases, usage, completion ordering, isolation — hardened how the team
collaborates. None of it gave an agent a new capability. Until D1 lands, "Cerebro is an MCP client"
is a claim in a document.

## Scope

**In**: connecting to configured stdio MCP servers, aggregating their catalogues, exposing a
per-agent filtered view, calling their tools inside the existing tool loop, and surviving a server
that is broken or absent.

**Out, deliberately**: `publish_tool` (§10.3) and `delegate_coding_task` (D2). Both let an agent
introduce new executable code, and neither should land in the same slice as the machinery they'd
run on. They get their own slice with their own review.

---

## Part A — `MCPManager` (`cerebro/mcp/manager.py`)

Owns client sessions. One session per configured server, started lazily on first use and shared
across agents.

- Registry from `mcp_servers.json` as specified in §10.1.
- `list_tools(server)` after handshake, cached; `call_tool(server, tool, args)`.
- A server that fails to start is recorded as unavailable with its error, and **does not** raise
  into the turn. Its tools simply do not appear in any catalogue.
- A crashed server must be restartable without restarting Cerebro.

### The supply-chain constraint — read this before writing any config

Nearly every MCP example in the wild launches servers with `npx -y @scope/server` or
`uvx some-server`. **We do not do that.** Those commands download and execute code at launch, which
is precisely what Dante's dependency rules forbid: exact version pins, hash-locked lockfiles, a
7-day cooldown on new releases, and no install scripts.

Rules for this slice, non-negotiable:

- `command` must be an already-installed executable or an interpreter running a path inside this
  repo. No fetch-on-launch, no `-y`, no `@latest`.
- Anything third-party is installed as a normal pinned dependency, through the existing audited
  path, and only then referenced by `mcp_servers.json`.
- `scripts/audit_cooldown.py` must still pass afterwards.

If a server cannot be launched under these rules, it does not get added — raise it rather than
working around it.

## Part B — Catalogue, naming, and the collision that will bite

Tools reach the model through the provider's function-calling schema. **OpenAI-compatible function
names are restricted to `[A-Za-z0-9_-]`**, so the `server:tool` form used in §10.1's allowlist
syntax is *not* a legal function name — a `:` will be rejected by the endpoint or silently mangled
by a local one.

- Wire name: `server__tool` (double underscore), e.g. `filesystem__read_file`.
- Allowlist syntax in `profile.json` stays `server:tool` globs, matched **before** translation.
- The mapping is a pure function with its own tests, both directions, including a server or tool
  name containing an underscore.
- A collision after translation is a startup error, not a silent last-one-wins.

Get this wrong and the failure is a model that never successfully calls a tool, with no error
anywhere — the exact shape of the six silent failures this project has already had.

## Part C — Tier enforcement (§8.8), at two points

Dante's constraint, in his words: *"The local agents have not proven themselves to not totally fuck
up my system. So my main goal there was to narrow the local agent blast radius."*

1. **Catalogue construction** — an agent's tool list is `tier_allows ∩ profile.tools_enabled`.
   Never "send everything and filter at call time".
2. **Execution** — re-check on every call, from the agent's profile, ignoring anything the model
   said about itself.

Two points because a model can emit a tool name it was never shown. Filtering the menu is not the
same as locking the kitchen, and the check that matters is the one at the door.

Default for a new agent remains `["cerebro-core:*"]`.

### §8.8 is currently a stub, and this slice is when that stops being harmless

`TIER_TOOLS` in `cerebro/tools.py` today maps `sandboxed`, `standard` and `full` to the **same five
tools**. The tier mechanism exists, is wired in, and currently distinguishes nothing.

That is safe right now — everything is pinned to the sandboxed set, so the failure is in the
restrictive direction — but it means the enforcement has never actually been exercised, and the
documentation reads as though it has. The moment MCP adds tools worth withholding, an untested
filter becomes load-bearing.

So this slice must land with the tiers genuinely differentiated and a test that a `sandboxed` agent
is refused a tool a `full` agent is granted. Not a test that the filter function works — a test
that the agent is actually refused.

## Part D — Failure semantics

The tool loop's protocol shape is already correct and must stay correct: one assistant turn carrying
the calls, then one tool turn per call carrying its `tool_call_id`.

- A tool that errors returns a **tool result describing the error**. It is not a turn failure, and
  it is not an empty assistant turn. The model gets to react to it.
- A tool that hangs is cancelled at a per-call timeout and returns a tool result saying so.
- An unavailable server's tools are absent from the catalogue, so the model cannot call them at all.
- No path here may produce an empty assistant turn — `FakeProvider` will reject it, which is why the
  strict fake exists.

## Part E — Configuration and docs

`mcp_servers.json` at the repo root per §10.1, plus `docs/MCP.md` covering: how to add a server
under the supply-chain rules, the `server__tool` naming, how allowlists and tiers interact, and what
happens when a server is down.

---

## Acceptance criteria

Green tests are the floor, not the gate. Evidence must come from something running.

1. A real stdio MCP server (write a minimal one under `tools/system/` — do not pull a third-party
   server in to prove the plumbing) is connected, its tools listed, and one is **called end to end
   from an actual agent turn**, with the transcript preserved under `workspace/evidence/mcp/`.
2. An agent whose profile excludes that tool cannot see it *and* cannot call it — prove both,
   separately. The second is the one that matters.
3. Killing the server process mid-session produces an in-channel tool error, not a hung turn and
   not a crash; the next turn still works after restart.
4. Function-name translation round-trips, including underscore-containing names, and a deliberate
   collision fails at startup.
5. `scripts/audit_cooldown.py` PASS, `scripts/clean_tree_gate.py` PASS, full suite green, flake8
   clean, working tree empty.
6. `docs/MCP.md` and the README reconcile with actual behaviour.

## Review note

Codex is unavailable until 2026-08-20. I review this; I did not write it, so that review is real.
Anything landing before then that neither of us has genuinely read gets flagged `UNREVIEWED` in its
commit message rather than passing quietly on a green suite.

The most recent bug found in this repo (`db77b55`) was in a commit with a fully green suite, found
by reading a diff. Expect the same here.
