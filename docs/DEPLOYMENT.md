# Deployment

**Landing is not shipping.** Python changes do not take effect until the service restarts. Static
assets (`app.js`, `style.css`) are served from disk and update on reload; nothing else does.

This distinction cost half a day: three fixes sat committed while the live service ran older code,
the app looked perfectly healthy, and the only symptom was already-fixed bugs reappearing. A human
found it by accident.

## Is the running service current?

```bash
python scripts/deploy.py --check
```

Exit `0` up to date, `1` stale or unknown, `2` refused.

`/api/health` reports it directly:

```json
{
  "status": "ok", "db": true, "schema_version": 4,
  "running_commit": "db77b55", "repo_commit": "4fe2c4e", "stale": true,
  "started_at": "2026-08-14T18:03:47+00:00"
}
```

`running_commit` is captured **once, at process start**, and never refreshed. That is deliberate:
reading git per request would report whatever `HEAD` says now, which is exactly the value that hides
the problem. A process can only honestly report the code it loaded.

A server that does not report `running_commit` at all predates this feature, so it is stale by
definition. `--check` treats that as stale rather than "fine" — an unanswerable question is not a
yes.

The web UI shows a full-width banner whenever `stale` is true.

## Deploying

```bash
python scripts/deploy.py
```

In order, and it stops at the first failure:

1. **Refuses a dirty tree.** What restarts must be what is committed, or the commit the server
   reports afterwards is a lie. `--allow-dirty` overrides, knowingly.
2. **Backs up** to `data/backups/cerebro_<timestamp>.db` using SQLite's `Connection.backup()`.
3. **Verifies the backup** — `PRAGMA integrity_check` plus a message-count match against the live
   database. A mismatch aborts *before* anything is restarted.
4. **Stops the service**, but only a process it has identified as Cerebro. Owning the port is not
   identity; the hand-rolled restart this replaces force-killed whatever was listening.
   Graceful `taskkill /PID /T` first, force only after 10s.
5. **Starts** `main.py` and waits for `/api/health`.
6. **Reports** before/after commit, schema version and staleness.

`--no-restart` does the backup and verification only.

## Backups

The database runs in **WAL mode**. Recent writes live in `data/cerebro.db-wal` until checkpointed,
and the WAL can hold far more than the main file — during the v2 build it reached 4 MB against a
520 KB main database.

**Copying `data/cerebro.db` alone can lose almost everything.** A copy taken mid-session restored to
0 messages while the live database held 363, and the restore reported success.

Copying `db`, `wal` and `shm` together while Cerebro runs is **also** unsafe — they are read one
after another while writes continue, so the snapshot can be torn.

Use one of these:

```bash
python scripts/deploy.py --no-restart      # backup + verify, service untouched
```

```bash
# If you have the sqlite3 CLI (it is NOT installed on this machine):
sqlite3 data/cerebro.db "VACUUM INTO '/your/backup/cerebro.db'"
```

Or stop Cerebro first, then copy all three files.

## Who deploys

Any CLI agent, using this script. Not Jarvis — it is an in-Cerebro agent and restarting the service
it lives in is not a sensible capability to hand it.

Nobody restarts by hand. Every step above exists because a previous restart was improvised.
