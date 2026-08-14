# Cerebro — what's next

Dante's requirements from 2026-08-14, sequenced. This is the working list; the design behind each
lives in [CEREBRO_V2_ARCHITECTURE.md](CEREBRO_V2_ARCHITECTURE.md).

## Sequencing, and why

Ordered by **how much each unblocks**, not by how it was listed. Two of his six are much smaller
than they sound and one is much larger.

| # | Requirement | Size | Where |
| :--- | :--- | :--- | :--- |
| 1 | Add agents to existing channels | **hours** — the API exists, only the UI is missing | Slice 3 |
| 2 | Create DMs, not just channels | **hours** — `kind: "dm"` already works, the dialog does not offer it | Slice 3 |
| 3 | Unread badges per channel | small — one column, one event, one UI element | Slice 3 |
| 4 | Resident agents (no CLI window) | in progress | Slice 3 A/B |
| 5 | Usage awareness and cost routing | **largest**, and the one that keeps the team alive | Slice 4 |
| 6 | Build out local agents | medium — needs §7 context to be real first | Slice 4 |
| 7 | Cheap cloud agents (DeepSeek, GLM, OpenRouter) | **hours** — one generalisation of an existing provider | slot in anywhere |

**Item 7 is not a big job.** `LMStudioProvider` already speaks the OpenAI protocol, which is also
what OpenRouter, DeepSeek and GLM speak. Generalising it costs a rename and a key lookup. It is
listed last because Dante ranked it last, but it should be done early precisely *because* it is
cheap and it takes pressure off item 5.

**Item 5 is the one to take seriously.** It is the difference between a team and a team that works
next week. Design in §13.2 — the honest part is that Cerebro **cannot** measure a `cli_agent`'s
subscription quota; it sees a subprocess, not a balance. So it is self-reporting plus observation,
with the UI showing which is which. A fuel gauge that is quietly wrong is worse than none.

**Items 1 and 2 are nearly done already** and should ship before anything else, because they are
the things Dante hits every time he uses the app.

## Immediate queue

1. **Slice 3 Part B** — the polling loop. Makes agents resident; deletes three hand-rolled watchers.
2. **Channel UX** — create a DM from the UI, add members to an existing channel, unread badges.
3. **`OpenAICompatibleProvider`** — item 7, an afternoon, unlocks cheap agents.
4. **Slice 4** — usage board and cost routing (§13.2), then local agents built out on top of a real
   context packet (§13.3, §7).

## Standing constraints

Carried from the architecture doc, listed here because they bind every item above:

- Cron stays off for `cli_agent` members until Dante has watched resident agents behave (§9.3).
- New agents default to `sandboxed` (§8.8).
- Dante is in every channel and cannot be removed; agents read only channels they belong to
  (§6.1, §6.2).
- Browser surfaces are verified in a browser. Almost every failure in this project has been silent.
