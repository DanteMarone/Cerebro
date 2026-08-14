"""Unit and concurrency tests for SQLite-backed lease management (§8.7)."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from cerebro import db, store
from cerebro.hub import Hub
from cerebro.models import LeaseConflictError


@pytest.fixture(autouse=True)
async def init_db(tmp_path: Path):
    """Initialize a fresh isolated database with all migrations for each test."""
    db_file = tmp_path / "test_leases.db"
    await db.connect(db_file)
    await db.migrate()
    yield db_file
    await db.close()


async def test_acquire_and_release_lease():
    """Basic acquisition and release of a lease."""
    lease = await store.acquire_lease(
        resource="file:cerebro/runtime.py",
        holder_id="antigravity",
        holder_kind="agent",
        ttl_s=300,
        reason="fixing turn loop",
        channel_id="warroom",
    )

    assert lease.resource == "file:cerebro/runtime.py"
    assert lease.holder_id == "antigravity"
    assert lease.reason == "fixing turn loop"
    assert lease.channel_id == "warroom"

    # Check store inspection
    active = await store.get_lease("file:cerebro/runtime.py")
    assert active is not None
    assert active.holder_id == "antigravity"

    # Release lease
    released = await store.release_lease("file:cerebro/runtime.py", holder_id="antigravity")
    assert released is True

    # Confirm cleared
    assert await store.get_lease("file:cerebro/runtime.py") is None


async def test_acquire_lease_conflict():
    """Attempting to acquire a lease held by another agent raises LeaseConflictError with metadata."""
    await store.acquire_lease(
        resource="repo:Cerebro:HEAD",
        holder_id="claude",
        holder_kind="agent",
        ttl_s=600,
        reason="merging v2 branch",
    )

    with pytest.raises(LeaseConflictError) as exc_info:
        await store.acquire_lease(
            resource="repo:Cerebro:HEAD",
            holder_id="codex",
            holder_kind="agent",
            ttl_s=600,
            reason="rebasing HEAD",
        )

    err = exc_info.value
    assert err.resource == "repo:Cerebro:HEAD"
    assert err.holder_id == "claude"
    assert err.reason == "merging v2 branch"
    assert "currently held by 'claude'" in str(err)


async def test_same_holder_reacquire_idempotence():
    """The same holder can re-acquire their own lease, updating the TTL and reason."""
    l1 = await store.acquire_lease(
        resource="port:8765",
        holder_id="jarvis",
        ttl_s=100,
        reason="starting server",
    )

    l2 = await store.acquire_lease(
        resource="port:8765",
        holder_id="jarvis",
        ttl_s=500,
        reason="restarting server on port",
    )

    assert l2.holder_id == "jarvis"
    assert l2.reason == "restarting server on port"
    assert l2.expires_at >= l1.expires_at


async def test_owner_override():
    """Dante (owner) can acquire a lease held by another agent, breaking the lock."""
    await store.acquire_lease(
        resource="db:cerebro:schema",
        holder_id="claude",
        ttl_s=600,
        reason="migrating tables",
    )

    # Dante takes over with is_owner=True
    override_lease = await store.acquire_lease(
        resource="db:cerebro:schema",
        holder_id="dante",
        holder_kind="user",
        ttl_s=300,
        reason="emergency schema reset",
        is_owner=True,
    )

    assert override_lease.holder_id == "dante"
    assert override_lease.holder_kind == "user"


async def test_release_by_non_holder_fails():
    """Only the holder or owner may release a lease."""
    await store.acquire_lease(
        resource="file:cerebro/api/app.py",
        holder_id="antigravity",
    )

    with pytest.raises(LeaseConflictError):
        await store.release_lease("file:cerebro/api/app.py", holder_id="codex")

    # Owner can release any lease
    released = await store.release_lease(
        "file:cerebro/api/app.py", holder_id="dante", is_owner=True
    )
    assert released is True


async def test_renew_lease_extends_ttl():
    """Renewing a lease extends expires_at."""
    l1 = await store.acquire_lease("port:9000", holder_id="antigravity", ttl_s=60)
    await asyncio.sleep(0.01)
    l2 = await store.renew_lease("port:9000", holder_id="antigravity", ttl_s=300)

    assert l2.holder_id == "antigravity"
    assert l2.expires_at > l1.expires_at

    # Non-holder cannot renew
    with pytest.raises(LeaseConflictError):
        await store.renew_lease("port:9000", holder_id="claude", ttl_s=300)


async def test_expired_lease_allows_reacquisition():
    """An expired lease is automatically reclaimed by another agent."""
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    # Insert expired lease manually
    sql = """
    INSERT INTO leases (resource, holder_id, holder_kind, channel_id, reason, acquired_at, expires_at)
    VALUES (?, ?, ?, ?, ?, ?, ?);
    """
    fut = await db.enqueue_write(
        sql, ("work:slice6", "claude", "agent", None, "old task", past, past)
    )
    await fut

    # Another agent acquires without conflict
    lease = await store.acquire_lease(
        "work:slice6", holder_id="codex", ttl_s=300, reason="fresh task"
    )
    assert lease.holder_id == "codex"
    assert lease.reason == "fresh task"


async def test_list_and_sweep_expired_leases():
    """list_leases excludes expired; sweep_expired_leases removes them."""
    now = datetime.now(timezone.utc)
    future = (now + timedelta(seconds=300)).isoformat()
    past = (now - timedelta(seconds=10)).isoformat()

    sql = """
    INSERT INTO leases (resource, holder_id, holder_kind, channel_id, reason, acquired_at, expires_at)
    VALUES (?, ?, ?, ?, ?, ?, ?);
    """
    fut1 = await db.enqueue_write(
        sql,
        ("res:active", "agent1", "agent", None, "active", now.isoformat(), future),
    )
    await fut1
    fut2 = await db.enqueue_write(
        sql,
        ("res:expired", "agent2", "agent", None, "dead", past, past),
    )
    await fut2

    active_leases = await store.list_leases(include_expired=False)
    assert len(active_leases) == 1
    assert active_leases[0].resource == "res:active"

    all_leases = await store.list_leases(include_expired=True)
    assert len(all_leases) == 1  # Lazy sweep already deleted the expired one

    # Sweep remaining
    swept = await store.sweep_expired_leases()
    assert swept == []


async def test_sweep_expired_leases_publishes_events():
    """Sweeping expired leases dispatches lease.expired event over Hub."""
    hub = Hub()
    sub = hub.subscribe("lease.expired")

    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    sql = """
    INSERT INTO leases (resource, holder_id, holder_kind, channel_id, reason, acquired_at, expires_at)
    VALUES (?, ?, ?, ?, ?, ?, ?);
    """
    fut = await db.enqueue_write(
        sql, ("res:sweeptest", "antigravity", "agent", "warroom", "test sweep", past, past)
    )
    await fut

    swept = await store.sweep_expired_leases(hub=hub)
    assert swept == ["res:sweeptest"]

    # Verify event on Hub
    event = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert event.type == "lease.expired"
    assert event.payload["resource"] == "res:sweeptest"
    assert event.payload["holder_id"] == "antigravity"
    sub.close()


async def test_production_race_for_lease():
    """Concurrency proof: Two callers race production store.acquire_lease() concurrently.

    Exactly one wins and acquires the lock; the second receives a typed LeaseConflictError.
    """
    results = []

    async def worker(agent_id: str):
        try:
            lease = await store.acquire_lease(
                resource="repo:Cerebro:HEAD",
                holder_id=agent_id,
                holder_kind="agent",
                ttl_s=300,
                reason=f"racing from {agent_id}",
            )
            results.append(("success", lease.holder_id))
        except LeaseConflictError as exc:
            results.append(("conflict", exc.holder_id, exc.resource))
        except Exception as exc:
            results.append(("error", str(exc)))

    await asyncio.gather(
        worker("agent_alpha"),
        worker("agent_beta"),
    )

    winner = next(r[1] for r in results if r[0] == "success")
    loser_conflict = next(r for r in results if r[0] == "conflict")
    assert loser_conflict[1] == winner
    assert loser_conflict[2] == "repo:Cerebro:HEAD"


async def test_two_independent_connections_race_for_lease(init_db: Path):
    """Concurrency proof: Two independent SQLite connections race for the same resource.

    Uses the exact production _acquire_lease_conn logic with BEGIN IMMEDIATE on both connections.
    Exactly one connection succeeds and commits; the second receives typed LeaseConflictError.
    """
    import aiosqlite

    db_path = str(init_db)
    results = []

    async def worker(agent_id: str):
        async with aiosqlite.connect(db_path, timeout=10.0) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode=WAL;")
            try:
                await conn.execute("BEGIN IMMEDIATE;")
                lease = await store._acquire_lease_conn(
                    conn=conn,
                    resource="repo:Cerebro:HEAD",
                    holder_id=agent_id,
                    holder_kind="agent",
                    ttl_s=300,
                    reason=f"racing from {agent_id}",
                )
                await conn.commit()
                results.append(("success", lease.holder_id))
            except LeaseConflictError as exc:
                await conn.rollback()
                results.append(("conflict", exc.holder_id, exc.resource))
            except Exception as exc:
                await conn.rollback()
                results.append(("error", str(exc)))

    await asyncio.gather(
        worker("conn_alpha"),
        worker("conn_beta"),
    )

    statuses = [r[0] for r in results]
    assert "success" in statuses, f"Expected one success, got: {results}"
    assert "conflict" in statuses, f"Expected one conflict, got: {results}"
    assert statuses.count("success") == 1
    assert statuses.count("conflict") == 1

    winner = next(r[1] for r in results if r[0] == "success")
    loser_conflict = next(r for r in results if r[0] == "conflict")
    assert loser_conflict[1] == winner
    assert loser_conflict[2] == "repo:Cerebro:HEAD"
