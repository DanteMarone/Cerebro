"""Database layer for Cerebro v2.

SQLite with WAL mode via aiosqlite.
Single-writer queue consumer pattern to prevent write concurrency conflicts.
"""

import asyncio
from pathlib import Path
from typing import Any
import aiosqlite

from cerebro.config import settings

_db: aiosqlite.Connection | None = None
_write_queue: asyncio.Queue[tuple[str, tuple[Any, ...], asyncio.Future[Any]] | None] | None = None
_writer_task: asyncio.Task[None] | None = None


async def _writer_consumer() -> None:
    """Single consumer task processing all write queries sequentially."""
    if _write_queue is None or _db is None:
        return

    while True:
        item = await _write_queue.get()
        if item is None:
            _write_queue.task_done()
            break

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
    global _db, _write_queue, _writer_task
    if _db is not None:
        return _db

    path = Path(db_path) if db_path is not None else settings.db_path
    path.parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(path))
    _db.row_factory = aiosqlite.Row

    await _db.execute("PRAGMA journal_mode=WAL;")
    await _db.execute("PRAGMA foreign_keys=ON;")
    await _db.commit()

    _write_queue = asyncio.Queue()
    _writer_task = asyncio.create_task(_writer_consumer())

    return _db


async def close() -> None:
    """Stop writer queue and close database connection."""
    global _db, _write_queue, _writer_task
    if _write_queue is not None:
        await _write_queue.put(None)
        if _writer_task is not None:
            await _writer_task
        _write_queue = None
        _writer_task = None

    if _db is not None:
        await _db.close()
        _db = None


async def migrate(migrations_dir: Path | None = None) -> list[int]:
    """Apply unapplied migrations in alphabetical order. Idempotent."""
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
        await _db.executescript(content)
        await _db.execute(
            "INSERT OR REPLACE INTO schema_version (version, applied_at) "
            "VALUES (?, datetime('now'));",
            (version,),
        )
        await _db.commit()
        applied_now.append(version)

    return applied_now


async def fetch_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Read helper returning a single row as a dictionary, or None."""
    if _db is None:
        raise RuntimeError("Database is not connected. Call connect() first.")

    cursor = await _db.execute(sql, params)
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def fetch_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Read helper returning all matching rows as dictionaries."""
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
    if _write_queue is None:
        raise RuntimeError("Database is not connected or writer is not active.")

    loop = asyncio.get_running_loop()
    future: asyncio.Future[Any] = loop.create_future()
    await _write_queue.put((sql, params, future))
    return future
