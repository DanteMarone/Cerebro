"""Database layer for Cerebro v2.

SQLite with WAL mode via aiosqlite.
Single-writer queue consumer pattern to prevent write concurrency conflicts.
"""

import asyncio
from pathlib import Path
from typing import Any
import aiosqlite

from cerebro.config import settings

_loop: asyncio.AbstractEventLoop | None = None
_path: Path | None = None
_db: aiosqlite.Connection | None = None
_write_queue: asyncio.Queue[tuple[str, tuple[Any, ...], asyncio.Future[Any]] | None] | None = None
_writer_task: asyncio.Task[None] | None = None


class WrongDatabase(RuntimeError):
    """connect() was asked for a different database than the one already open."""


class WrongEventLoop(RuntimeError):
    """The database was reached from an event loop other than the one it was connected on."""


def _check_loop() -> None:
    """Refuse cross-loop access instead of deadlocking.

    The write queue and its consumer task belong to whichever loop called `connect()`. A write
    enqueued from a second loop lands in a queue nobody is draining, so the caller awaits a future
    that can never resolve: no traceback, no timeout, just a process that stops. That is exactly
    how the Slice 1 WebSocket test hung the entire suite, and it would happen again in a cron
    worker or a background thread with nobody watching. Fail loudly at the boundary instead.
    """
    if _loop is None:
        return
    try:
        current = asyncio.get_running_loop()
    except RuntimeError:
        return
    if current is not _loop:
        raise WrongEventLoop(
            "cerebro.db was connected on a different event loop than the one calling it. "
            "The single-writer queue only drains on its own loop, so this call would hang. "
            "Run the database and its callers on one loop -- in tests, let the app lifespan own "
            "the connection rather than opening one in a fixture on another loop."
        )


async def _writer_consumer() -> None:
    """Single consumer task processing all write queries sequentially."""
    if _write_queue is None or _db is None:
        return

    while True:
        item = await _write_queue.get()
        if item is None:
            _write_queue.task_done()
            break

        if len(item) == 3 and item[0] == "tx":
            _, fn, future = item
            try:
                await _db.execute("BEGIN IMMEDIATE;")
                res = await fn(_db)
                await _db.commit()
                if not future.done():
                    future.set_result(res)
            except Exception as exc:
                try:
                    await _db.rollback()
                except Exception:
                    pass
                if not future.done():
                    future.set_exception(exc)
            finally:
                _write_queue.task_done()
        else:
            sql, params, future = item
            try:
                cursor = await _db.execute(sql, params)
                await _db.commit()
                if not future.done():
                    future.set_result(cursor.lastrowid)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)
            finally:
                _write_queue.task_done()


async def connect(db_path: Path | str | None = None) -> aiosqlite.Connection:
    """Connect to SQLite database and start writer queue."""
    global _db, _write_queue, _writer_task, _loop, _path

    path = Path(db_path) if db_path is not None else settings.db_path
    if _db is not None:
        # Silently returning the existing connection means a caller asking for a different
        # database gets the live one instead. That is how a test writes a channel named "test"
        # into Dante's real sidebar: the fixture asks for a temp path, gets production, and
        # nothing anywhere says so.
        if _path is not None and Path(path).resolve() != _path.resolve():
            raise WrongDatabase(
                f"already connected to {_path}, refusing to hand back that connection for "
                f"{path}. Close the existing connection first."
            )
        return _db
    path.parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(path))
    _db.row_factory = aiosqlite.Row

    await _db.execute("PRAGMA journal_mode=WAL;")
    await _db.execute("PRAGMA foreign_keys=ON;")
    await _db.commit()

    _loop = asyncio.get_running_loop()
    _path = path
    _write_queue = asyncio.Queue()
    _writer_task = asyncio.create_task(_writer_consumer())

    return _db


async def close() -> None:
    """Stop writer queue and close database connection."""
    global _db, _write_queue, _writer_task, _loop, _path
    if _write_queue is not None:
        await _write_queue.put(None)
        if _writer_task is not None:
            await _writer_task
        _write_queue = None
        _writer_task = None

    if _db is not None:
        await _db.close()
        _db = None
    _loop = None
    _path = None


async def migrate(migrations_dir: Path | None = None) -> list[int]:
    """Apply unapplied migrations in alphabetical order. Idempotent."""
    _check_loop()
    if _db is None:
        raise RuntimeError("Database is not connected. Call connect() first.")

    target_dir = migrations_dir or (Path(__file__).resolve().parent / "migrations")
    if not target_dir.exists():
        return []

    # Ensure schema_version table exists
    await _db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT
        );
        """
    )
    await _db.commit()

    # Get already applied versions
    cursor = await _db.execute("SELECT version FROM schema_version ORDER BY version ASC;")
    applied_rows = await cursor.fetchall()
    applied_versions = {row[0] for row in applied_rows}

    # Find migration files
    migration_files = sorted(target_dir.glob("*.sql"))
    applied_now: list[int] = []

    for sql_file in migration_files:
        prefix = sql_file.name.split("_")[0]
        if not prefix.isdigit():
            continue
        version = int(prefix)
        if version in applied_versions:
            continue

        content = sql_file.read_text(encoding="utf-8")
        raw_statements = [s.strip() for s in content.split(";") if s.strip()]

        await _db.execute("BEGIN IMMEDIATE;")
        try:
            for statement in raw_statements:
                await _db.execute(statement)
            await _db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, datetime('now'));",
                (version,),
            )
            await _db.commit()
        except Exception:
            await _db.execute("ROLLBACK;")
            raise
        applied_now.append(version)

    return applied_now


async def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Read helper returning a single row as a dictionary, or None."""
    _check_loop()
    if _db is None:
        raise RuntimeError("Database is not connected. Call connect() first.")

    cursor = await _db.execute(sql, params)
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Read helper returning all matching rows as dictionaries."""
    _check_loop()
    if _db is None:
        raise RuntimeError("Database is not connected. Call connect() first.")

    cursor = await _db.execute(sql, params)
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def enqueue_write(
    sql: str,
    params: tuple[Any, ...] = (),
) -> asyncio.Future[Any]:
    """Enqueue a write operation to the single-writer queue."""
    _check_loop()
    if _write_queue is None:
        raise RuntimeError("Database is not connected or writer is not active.")

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    await _write_queue.put((sql, params, future))
    return future


async def run_in_writer(fn: Any) -> Any:
    """Execute a callable atomically on the single-writer connection inside a transaction."""
    _check_loop()
    if _write_queue is None or _db is None:
        raise RuntimeError("Database is not connected or writer is not active.")

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    await _write_queue.put(("tx", fn, future))
    return await future
