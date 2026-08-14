# Slice 1 — Walking skeleton (executor brief)

**Branch**: `v2` · **Executor**: Gemini / Antigravity · **Reviewer**: Claude
**Authority**: [CEREBRO_V2_ARCHITECTURE.md](../CEREBRO_V2_ARCHITECTURE.md), §3, §5, §11.

The goal: Dante opens a browser, types a message to one agent, and watches tokens arrive from LM
Studio. The conversation survives a restart. Nothing else.

This is the first slice we build in parallel, so read §"Seam" below before you start.

---

## Who builds what

**Claude owns** — do not create or edit these:
`cerebro/providers/lmstudio.py`, `cerebro/runtime.py`, `cerebro/context.py`,
`cerebro/prompts/*`, `cerebro/hub.py`, `cerebro/turnguard.py`.

**You own**:

| File | Responsibility |
|---|---|
| `cerebro/api/ws.py` | The `/ws` WebSocket endpoint: accept, subscribe to the hub, fan events to the client, receive inbound user messages. |
| `cerebro/api/routes_channels.py` | `GET /api/channels`, `GET /api/channels/{id}/messages?after=`, `POST /api/channels/{id}/messages`. |
| `cerebro/api/routes_agents.py` | `GET /api/agents`, `GET /api/agents/{id}`. |
| `cerebro/store.py` | Typed persistence helpers over `db.py` — `create_channel`, `append_message`, `list_messages`, `load_agents`. All writes via `enqueue_write`. |
| `cerebro/agents_loader.py` | Read `agents/{id}/profile.json` + `system_prompt.md` into the `agents` table on startup; create the seed agent and its DM if the DB is empty. |
| `cerebro/web/**` | The entire front end. |
| `tests/**` for the above | Using `FakeProvider`; no test may need LM Studio or the network. |

---

## The seam

We are writing against each other's unfinished code, so the contract is the architecture document,
not whatever my half happens to do today.

**The hub is the only coupling.** You never call the runtime and never import a provider. You
publish one event when a user message arrives, and you render the events that come back:

```python
await hub.publish("message.new", {"channel_id": ..., "message": {...}})
```

The runtime subscribes, produces the reply, and publishes `message.delta` / `message.done`. If the
runtime is not running, posting a message must still persist it and render it — the UI simply gets
no reply. Build and demo in exactly that state.

**Event envelope** (§11), all over `/ws`: `{"type": ..., "payload": {...}, "seq": n}`.
Types you must handle this slice: `message.new`, `message.delta`, `message.done`, `agent.status`,
`error`. Ignore unknown types rather than throwing — later slices add more.

`message.delta` carries `{"message_id": int, "text": "<fragment>"}` and is append-only; the client
concatenates fragments in `seq` order. `message.done` carries the finished message row, which is
authoritative — replace whatever you accumulated with it.

**Reconnect**: track the highest `seq` seen; on reconnect call
`GET /api/channels/{id}/messages?after={last_message_id}` and replay. Lost deltas are not
recovered — that is by design.

If any of this is wrong, underspecified, or awkward to build against, **say so in `#slice0` and I
will change the document.** Do not adapt to my implementation.

---

## Front end

No npm, no bundler, no CDN. Vendor Preact + htm into `cerebro/web/vendor/` as literal files,
record exact versions and SRI hashes in `cerebro/web/vendor/VENDOR.md`.

This slice needs only: a left sidebar listing agents and channels, a centre message stream, and a
composer. Slack-shaped but plain — no threads, no right panel, no search. Streaming text must
render smoothly as it arrives, and the stream must stay pinned to the bottom unless the user has
scrolled up.

Dark and light both, driven by `prefers-color-scheme`. Messages show avatar, agent name, and
timestamp. Markdown rendering can wait for Slice 2; plain text with preserved whitespace is enough,
but escape it properly.

---

## Seed data

If the `agents` table is empty at startup, create one agent from `agents/jarvis/profile.json`:

```json
{
  "id": "jarvis", "name": "jarvis", "display_name": "Jarvis", "avatar": "J",
  "role": "Personal assistant", "provider": "lmstudio", "model": "",
  "params": {"temperature": 0.7, "max_tokens": 1024},
  "tools_enabled": ["cerebro-core:*"], "delegation_enabled": false, "enabled": true
}
```

An empty `model` means "whatever LM Studio has loaded" — resolve it at call time from
`GET /v1/models` and take the first entry. Write a short `system_prompt.md` beside it; it will be
replaced by the operating manual in Slice 4.

Also create the `personal-assistant` team and a DM channel between Dante and Jarvis, so the app
opens onto something rather than an empty state.

---

## Acceptance

Fresh venv on CPython 3.14, clean checkout:

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m flake8 .
PYTHONPATH=. .venv/Scripts/python -m pytest -q
.venv/Scripts/python scripts/audit_cooldown.py
PYTHONPATH=. .venv/Scripts/python main.py
```

- Browser at `http://127.0.0.1:8765` shows the sidebar, the DM, and an empty stream.
- Typing a message persists it, renders it immediately, and broadcasts `message.new` to every
  connected client.
- With the runtime present, tokens stream into the stream as they arrive.
- Killing and restarting the server preserves the conversation.
- Opening a second browser tab shows the same conversation, live.
- Cooldown audit still passes — if you add a dependency, it must clear the 7-day rule.

## Deliverable

Commits on `v2` prefixed `slice1:`. Docs updated in the same commit — this slice needs
`docs/websocket_protocol.md` describing the envelope and every event type you implemented, because
that document is what Slice 2 and 3 will build against.

Take `LEASE repo:Cerebro:HEAD` before any command that moves HEAD, and post it in `#slice0`.
