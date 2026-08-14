"""Tests for SQLite schema migrations and database operations."""

import pytest
from cerebro import db
from cerebro.config import Settings


REQUIRED_TABLES = {
    "schema_version",
    "teams",
    "agents",
    "agent_teams",
    "channels",
    "channel_members",
    "messages",
    "tool_calls",
    "tasks",
    "cron_jobs",
    "audit_events",
    "budget_usage",
}

REQUIRED_INDEXES = {
    "idx_messages_channel_id_id",
    "idx_messages_turn_id",
    "idx_audit_events_ts",
    "idx_tasks_owner_status",
    "idx_cron_jobs_next_run",
}


@pytest.mark.asyncio
async def test_schema_introspect_tables_and_indexes(test_db: Settings):
    """Assert all tables and required indexes exist by introspecting sqlite_master."""
    # Check tables
    rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    )
    existing_tables = {r["name"] for r in rows}
    assert REQUIRED_TABLES.issubset(existing_tables), (
        f"Missing tables: {REQUIRED_TABLES - existing_tables}"
    )

    # Check indexes
    index_rows = await db.fetch_all(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%';"
    )
    existing_indexes = {r["name"] for r in index_rows}
    assert REQUIRED_INDEXES.issubset(existing_indexes), (
        f"Missing indexes: {REQUIRED_INDEXES - existing_indexes}"
    )


@pytest.mark.asyncio
async def test_migration_idempotent(test_db: Settings):
    """Assert running migrate() a second time is an idempotent no-op."""
    applied = await db.migrate()
    assert applied == [], "Second migration run should return empty list"


@pytest.mark.asyncio
async def test_single_writer_queue_and_reads(test_db: Settings):
    """Test enqueue_write, fetch_one, and fetch_all through the DB layer."""
    future = await db.enqueue_write(
        "INSERT INTO teams (id, slug, name, description, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'));",
        ("team_1", "cerebro-core", "Cerebro Core", "Core engineering team"),
    )
    await future

    team = await db.fetch_one("SELECT * FROM teams WHERE slug = ?;", ("cerebro-core",))
    assert team is not None
    assert team["id"] == "team_1"
    assert team["name"] == "Cerebro Core"

    teams = await db.fetch_all("SELECT * FROM teams ORDER BY id ASC;")
    assert len(teams) == 1
    assert teams[0]["slug"] == "cerebro-core"
