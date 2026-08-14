# Slice 0 — Skeleton (executor brief)

**Branch**: `v2` (already exists, already pushed)
**Executor**: Gemini / Antigravity (`agy`)
**Reviewer**: Claude — runs the acceptance commands and reads the diff before this lands
**Authority**: [CEREBRO_V2_ARCHITECTURE.md](../CEREBRO_V2_ARCHITECTURE.md). Where this brief and the
architecture document disagree, the architecture document wins. Do not redesign anything here.

---

## Already done (do not redo)

The `v2` branch already has the hard cutover applied:

- All PyQt5 modules deleted (`app.py`, `main.py`, `tab_*.py`, `dialogs.py`, `worker.py`, `tts.py`,
  `voice_input.py`, `fine_tuning.py`, `local_llm_helper.py`, `workflows.py`, `message_broker.py`,
  `tasks.py`, `tools.py`, `transcripts.py`, `metrics.py`, and 43 tests bound to them).
- `.gitignore` added.
- `requirements.in` / `requirements-dev.in` added.

Deliberately left in place as porting source for Slice 7 — **do not delete, do not modify**:
`tool_plugins/`, `automation_sequences.py`, `version.py`, the 12 surviving plugin tests, and the
root JSON config files (`agents.json`, `tasks.json`, `tools.json`, `automations.json`,
`workflows.json`) which are migration input.

---

## Build this

```
cerebro/
├── __init__.py
├── config.py
├── db.py
├── schema.sql
├── models.py
├── migrations/
│   ├── __init__.py
│   └── 001_init.sql
├── providers/
│   ├── __init__.py
│   ├── base.py
│   └── fake.py
└── api/
    ├── __init__.py
    └── app.py
main.py
setup.cfg
tests/conftest.py
tests/test_config.py
tests/test_db_migrations.py
tests/test_fake_provider.py
```

### `cerebro/config.py`

A frozen `Settings` dataclass loaded once at import, from environment with defaults. Env prefix
`CEREBRO_`. Every CONFIG value named in the architecture document belongs here — do not scatter
defaults through the codebase.

Required keys and defaults:

| Key | Default |
|---|---|
| `host` / `port` | `127.0.0.1` / `8765` |
| `data_dir` | `<repo>/data` |
| `db_path` | `<data_dir>/cerebro.db` |
| `vault_path` | `D:/Obsidian/MyVault/Cerebro` |
| `claude_memory_path` (read-only) | `D:/Obsidian/MyVault/Claude Memory` |
| `workspace_path` | `<repo>/workspace` |
| `agents_path` | `<repo>/agents` |
| `lmstudio_base_url` | `http://127.0.0.1:1234` |
| `lmstudio_concurrency` | `2` |
| `gemini_concurrency` | `4` |
| `moderator_model` | `""` (unset — Dante confirms later) |
| `moderator_window` | `12` |
| `max_auto_speakers` | `2` |
| `history_window` | `30` |
| `context_budget` | `24000` |
| `max_depth` | `8` |
| `max_agent_messages_per_turn` | `12` |
| `max_turn_wallclock_s` | `600` |
| `max_tool_iterations` | `12` |
| `max_self_initiated_per_hour` | `6` |
| `daily_usd_budget` | `5.0` |
| `daily_delegations` | `3` |
| `debug` | `False` |

`Settings.ensure_dirs()` creates `data_dir` and its `journal/` subdirectory. It MUST NOT create
anything under `claude_memory_path`.

### `cerebro/schema.sql` and `migrations/001_init.sql`

Transcribe §4 of the architecture document **exactly** — same tables, same columns, same names.
Add the four indexes it requires. `001_init.sql` is the schema plus a `schema_version` table.
If a column in §4 seems wrong to you, say so in your report; do not silently change it.

### `cerebro/db.py`

- `aiosqlite`, `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`.
- `async def connect()` / `async def close()`.
- `async def migrate()` — applies numbered files from `migrations/` in order, records each in
  `schema_version`, is idempotent, and runs each migration in a transaction.
- Read helpers `fetch_one` / `fetch_all`.

**Write path**: expose `async def enqueue_write(sql, params) -> Future` backed by a single
`asyncio.Queue` consumer task. Every write in Cerebro goes through it. Implement the queue and the
consumer; the callers come in later slices. Do not add a second write path "for convenience".

### `cerebro/models.py`

Pydantic models mirroring the schema rows plus the `Delta` union from §9: `TextDelta`,
`ToolCallDelta`, `Usage`, `Done`. Types only — no behaviour.

### `cerebro/providers/base.py`

The `Provider` Protocol exactly as written in §9, plus `ToolSpec` and `Params`. Nothing else.

### `cerebro/providers/fake.py`

`FakeProvider` replays a scripted list of `Delta` objects supplied at construction, with an
optional per-delta delay of 0. It records the `messages` and `tools` it was called with so tests
can assert on them. This is the backbone of every later test — make it pleasant to use.

### `cerebro/api/app.py` and `main.py`

- FastAPI app; on startup call `db.connect()` + `db.migrate()` + `settings.ensure_dirs()`.
- `GET /api/health` → `{"status": "ok", "db": true, "version": "<version.py>"}`.
- `GET /` → a minimal placeholder page (plain HTML string is fine; the real UI is Slice 1+).
- A `Principal` dependency returning a fixed local user object. It does nothing yet — it exists so
  auth is a one-file change later (D5). Every route takes it.
- `main.py` runs uvicorn against `settings.host`/`settings.port`.

### `setup.cfg`

`[flake8]` with `max-line-length = 100`, excluding `.venv`, `__pycache__`, `tool_plugins`.
`[tool:pytest]` with `asyncio_mode = auto` and `testpaths = tests`.

### Dependency locking

Generate both lockfiles:

```bash
pip-compile --generate-hashes --output-file=requirements.txt requirements.in
pip-compile --generate-hashes --output-file=requirements-dev.txt requirements-dev.in
```

Rules (non-negotiable — these are Dante's standing supply-chain directives):
- Exact pins with hashes. Never hand-edit the generated files.
- Every resolved release must be **at least 7 days old**. Verify this with
  `python scripts/audit_cooldown.py`, which checks every pin against the PyPI release date — do not
  assert it from memory. Where a resolved version is too young, pin the previous release in the
  `.in` file and recompile.
- **Target interpreter is CPython 3.14** — Dante's default `python`. Compile the lock against it
  (`--python-version 3.14`); a lock resolved against a different minor version installs a wheel set
  that will not import here.
- No package with an install script / arbitrary `setup.py` execution beyond what these well-known
  packages already do. If the resolver pulls in something unexpected, stop and report it.

---

## Do NOT build in this slice

These are Claude's and will conflict if you write them: `hub.py`, `runtime.py`, `moderator.py`,
`context.py`, `turnguard.py`, `journal.py`, `budgets.py`, `mcp/`, `prompts/`, `providers/lmstudio.py`,
`providers/gemini.py`, and the migration script for `agents.json`.

Also: no npm, no bundler, no `package.json`, no CDN links. No new top-level dependency that isn't
in `requirements.in` without asking first.

---

## Acceptance

All of these must pass, from a clean checkout of `v2`:

```bash
py -3.14 -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m flake8 .
PYTHONPATH=. .venv/Scripts/python -m pytest -q
.venv/Scripts/python scripts/audit_cooldown.py
PYTHONPATH=. .venv/Scripts/python main.py   # then: curl http://127.0.0.1:8765/api/health
```

Run these in a **freshly created venv**, not one that already has packages in it. The first
acceptance run of this slice reported green in an environment that still had a dependency left
over from the PyQt application; on a clean checkout two tests failed.

- `flake8` clean.
- `pytest` green, including the 12 retained plugin tests.
- `/api/health` returns `{"status":"ok","db":true,...}`.
- `data/cerebro.db` exists and contains every table and index from §4 — `test_db_migrations.py`
  must assert this by introspecting `sqlite_master`, not by trusting the SQL.
- Running `migrate()` twice is a no-op.
- No file under `D:/Obsidian/MyVault/Claude Memory` was created or modified.

## Deliverable

One commit on `v2` (or a short series), message prefix `slice0:`. Update `README.md`'s getting-started
section to the v2 commands in the same commit — a feature without current docs is not done. Report
back with: the flake8/pytest output, anything in §4 you thought was wrong, and any dependency that
tripped the 7-day rule.
