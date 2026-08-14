# Slice 2 — The team moves in (executor brief)

**Branch**: `v2` · **Reviewer**: Claude · **Authority**:
[CEREBRO_V2_ARCHITECTURE.md](../CEREBRO_V2_ARCHITECTURE.md) §6.1, §6.2, §6.3, §11.

The goal, in one sentence: **Dante opens Cerebro and talks to Claude, Antigravity and Codex in a
real channel, and the markdown war room is switched off.**

## Why this is not the Slice 2 in §13

§13 had Slice 2 as MCP and core tools. That ordering was written before the team existed. Right
now three agents are members of `#warroom` and none of them can speak in it, so all coordination
still happens in a markdown file that Dante has asked twice to retire. Tools are worth nothing
until the team can hold a conversation in the product.

Revised order — MCP moves out one slice, nothing is cut:

| Slice | Was | Now |
| :--- | :--- | :--- |
| 2 | MCP + core tools | **Agent ingress + channels** |
| 3 | Multi-agent channels | **Polling + self-directed speaking** (§6) |
| 4 | Memory + context | **MCP + core tools** |
| 5 | Autonomy | Memory + context |
| 6 | Gemini + delegation | Autonomy, then delegation |

---

## Part A — Agent ingress (Claude)

§6.3. This is first because everything else in the slice is blocked on it, and because it is the
piece where being wrong means an agent can speak as Dante.

- Token generation on agent creation; storage in `data/.secrets.env`; never in git, never in
  `profile.json`, never logged.
- `Authorization: Bearer <token>` on REST and the first WebSocket frame resolves to
  `Principal(kind="agent", id=...)`. An unknown token is rejected outright — it must not fall back
  to the human principal.
- An agent principal authors **only as itself**. Not as `dante`, not as a peer. Enforced where the
  author is assigned, not at the caller.
- `cerebro token issue <agent>` / `token revoke <agent>` CLI.

**Acceptance**: an agent token posts a message that lands attributed to that agent; the same token
attempting `author_id: "dante"` or a peer id is refused; an invalid token gets 401 and never a
human principal; no token appears in git, in a log line, or in `/api/agents` output.

## Part B — Channels and membership (Antigravity)

There is currently no way to create a channel through the API — `#warroom` exists only because the
importer made it.

| Endpoint | Notes |
| :--- | :--- |
| `POST /api/channels` | name, topic, kind, team, members[]. **Adds Dante unconditionally** (§6.1). |
| `POST /api/channels/{id}/members` | add an agent |
| `DELETE /api/channels/{id}/members/{member_id}` | refuses for `dante` |
| `GET /api/channels/{id}/members` | roster with `listen_mode` |

Front end: channel list split into DMs and channels, switching that preserves per-channel drafts
and scroll state, a member roster in the right panel, and a create-channel dialog. Keep the draft
and pinned-scroll behaviour that already works — it was hard-won and Dante asked for it specifically.

**Acceptance**: create a channel from the UI with two agents; Dante is a member without being
selected; removing him fails with a clear error; switching channels mid-draft loses nothing.

## Part C — Invariants and cutover (Codex)

You proposed the framing that made §6.1 and §6.2 sharp, so the proofs are yours.

- Store/API-level tests: channel creation without Dante still contains him; his removal is refused;
  no recipient or metadata field can hide a message from him; an agent principal cannot author as
  another identity; a revoked token stops working immediately.
- One **integration** test that exercises the real ASGI WebSocket path end to end on a single event
  loop, using the app's own lifespan. The current WS test calls the endpoint directly with a mock,
  which is fine as a unit test but means nothing in the suite proves the route actually works.
- The retirement itself, and only once Part A is verified live: all three agents posting into
  `#warroom` as themselves, a final idempotent sync of any straggler messages, then delete
  `scripts/warroom.py` and `workspace/channels/slice0.md` in one commit.

**Acceptance**: the invariant tests fail if the guard is removed — verify that by removing it
locally and watching them go red, not by reading them.

---

## Rules for this slice

- **Nobody retires the war room until all three agents have posted into `#warroom` as themselves.**
  Sequence: ingress, then move in, then retire.
- No automation borrows Dante's principal. Not for testing, not for convenience, not once.
- Live testing goes in a channel created for it, never in a DM and never in `#warroom` while its
  imported count is still the acceptance evidence.
- Browser surfaces are verified in a browser. Twice tonight a UI was reported working while it
  rendered nothing.
- Stage explicit paths. `git add -A` crossed a scope boundary three times tonight, once for me.
- Take `file:<path>` before editing anything outside your part. An announcement is not a lock.

## Acceptance for the slice

Dante opens `http://127.0.0.1:8765`, sees `#warroom` with the full imported history, types a
message, and gets replies from agents authored as themselves. `scripts/warroom.py` is gone. Suite
green and terminating, flake8 clean, cooldown audit passing, and every number in the report
produced by running something rather than reading it.
