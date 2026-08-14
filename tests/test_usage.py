"""Tests for the usage board (§13.2).

The load-bearing property here is not arithmetic, it is honesty about provenance. A board that adds
a measured token count to a self-reported percentage, or shows a four-hour-old figure as current, is
worse than no board -- it turns "I do not know" into a number, and a number gets acted on.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient, ASGITransport

from cerebro import db, usage
from cerebro.api.app import app
from cerebro.auth import TokenStore
from cerebro.config import Settings
from cerebro.hub import Hub


def _agent_headers(settings: Settings, agent_id: str) -> dict[str, str]:
    token = TokenStore(settings.data_dir / ".secrets.env").issue(agent_id)
    return {"Authorization": f"Bearer {token}"}


# -- measured half ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_measured_usage_accumulates_across_turns(test_db: Settings):
    """budget_usage has existed since 001_init.sql and was never written to. It is now."""
    await usage.record_turn_usage("jarvis", input_tokens=100, output_tokens=40)
    await usage.record_turn_usage("jarvis", input_tokens=30, output_tokens=10)

    rows = await db.fetch_all("SELECT * FROM budget_usage WHERE scope_id = 'jarvis'")
    assert len(rows) == 1, "one row per agent per day, accumulated"
    assert rows[0]["calls"] == 2
    assert rows[0]["input_tokens"] == 130
    assert rows[0]["output_tokens"] == 50


@pytest.mark.asyncio
async def test_a_turn_that_reported_no_tokens_is_not_recorded(test_db: Settings):
    await usage.record_turn_usage("jarvis", input_tokens=0, output_tokens=0)
    assert await db.fetch_all("SELECT * FROM budget_usage") == []


@pytest.mark.asyncio
async def test_a_failing_write_never_breaks_the_turn(test_db: Settings, monkeypatch):
    """Accounting must not be able to stop the team talking.

    If this raised into AgentRuntime.run_turn, a locked database would silence every agent in order
    to protect a statistic. Losing the number is the correct trade; losing the turn is not.
    """

    async def boom(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(db, "enqueue_write", boom)
    await usage.record_turn_usage("jarvis", input_tokens=10, output_tokens=5)


# -- self-reported half -----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_quota_report_records_who_said_it(test_db: Settings):
    report = await usage.report_quota("codex", "weekly", 16.0, reported_by="codex")
    assert report.reported_by == "codex"
    assert report.is_relayed is False


@pytest.mark.asyncio
async def test_a_relayed_report_is_marked_as_relayed(test_db: Settings):
    """Dante reading a percentage off a harness UI is real, and must not look self-reported."""
    report = await usage.report_quota("codex", "weekly", 16.0, reported_by="dante")
    assert report.is_relayed is True
    assert report.reported_by == "dante"


@pytest.mark.asyncio
async def test_a_report_replaces_the_previous_one_for_that_window(test_db: Settings):
    await usage.report_quota("codex", "weekly", 29.0, reported_by="codex")
    await usage.report_quota("codex", "weekly", 16.0, reported_by="codex")

    reports = await usage.quotas_for("codex")
    assert len(reports) == 1
    assert reports[0].pct_remaining == 16.0


@pytest.mark.asyncio
async def test_an_impossible_percentage_is_refused(test_db: Settings):
    with pytest.raises(ValueError, match="0..100"):
        await usage.report_quota("codex", "weekly", 140.0, reported_by="codex")


@pytest.mark.asyncio
async def test_an_old_report_is_marked_stale_rather_than_deleted(test_db: Settings):
    """'Codex said 16% four hours ago' is still information. Presenting it as current is the bug."""
    long_ago = datetime.now(timezone.utc) - (usage.STALE_AFTER + timedelta(minutes=5))
    await usage.report_quota("codex", "weekly", 16.0, reported_by="codex", at=long_ago)

    board = await usage.board()
    entry = next(a for a in board["agents"] if a["agent_id"] == "codex")
    assert entry["windows"][0]["stale"] is True
    assert entry["windows"][0]["pct_remaining"] == 16.0, "still shown, just not as current"


# -- the seam ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_board_keeps_measured_and_self_reported_apart(test_db: Settings):
    """The two halves are not commensurable and the board must never merge them."""
    await usage.record_turn_usage("jarvis", input_tokens=1200, output_tokens=300)
    await usage.report_quota("codex", "weekly", 16.0, reported_by="codex")

    board = await usage.board()
    jarvis = next(a for a in board["agents"] if a["agent_id"] == "jarvis")
    codex = next(a for a in board["agents"] if a["agent_id"] == "codex")

    assert jarvis["measured"]["source"] == usage.MEASURED
    assert jarvis["measured"]["total_tokens"] == 1500
    assert jarvis["windows"] == [], "a measured agent claims no harness window"

    assert codex["measured"] is None, "a CLI agent's tokens are not ours to see"
    assert codex["windows"][0]["source"] == usage.SELF_REPORTED


# -- the API ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_agent_cannot_report_quota_for_another_agent(test_db: Settings):
    """The attribution rule from §6.2, applied to a number instead of a sentence.

    An agent able to file as a teammate could make that teammate look exhausted and inherit its
    work. Dante ruled on impersonation once already; this is the same rule at a different door.
    """
    app.state.hub = Hub()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/usage/quota",
            json={"window": "weekly", "pct_remaining": 3.0, "agent_id": "codex"},
            headers=_agent_headers(test_db, "antigravity"),
        )

    assert res.status_code == 403
    assert "cannot report quota for codex" in res.json()["detail"]
    assert await db.fetch_all("SELECT * FROM agent_quota") == [], "nothing was written"


@pytest.mark.asyncio
async def test_an_agent_reporting_its_own_window_is_accepted(test_db: Settings):
    app.state.hub = Hub()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/api/usage/quota",
            json={"window": "5h", "pct_remaining": 62.0, "note": "plenty of headroom"},
            headers=_agent_headers(test_db, "antigravity"),
        )

    assert res.status_code == 200
    body = res.json()
    assert body["agent_id"] == "antigravity"
    assert body["reported_by"] == "antigravity"
    assert body["relayed"] is False


@pytest.mark.asyncio
async def test_dante_may_relay_a_quota_for_an_agent(test_db: Settings):
    """He has done this by hand in the channel several times; the product should accept it."""
    app.state.hub = Hub()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/")
        res = await client.post(
            "/api/usage/quota",
            json={"window": "weekly", "pct_remaining": 16.0, "agent_id": "codex"},
        )

    assert res.status_code == 200
    body = res.json()
    assert body["agent_id"] == "codex"
    assert body["reported_by"] == "dante"
    assert body["relayed"] is True


@pytest.mark.asyncio
async def test_the_board_is_visible_to_agents(test_db: Settings):
    """Dante's fourth requirement: agents can see each other's usage and route work accordingly."""
    await usage.report_quota("codex", "weekly", 16.0, reported_by="codex")
    app.state.hub = Hub()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/usage", headers=_agent_headers(test_db, "antigravity"))

    assert res.status_code == 200
    assert any(a["agent_id"] == "codex" for a in res.json()["agents"])


@pytest.mark.asyncio
async def test_the_board_refuses_anonymous_readers(test_db: Settings):
    """Absence of credentials is not an identity (§6.3)."""
    app.state.hub = Hub()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/usage", headers={"Authorization": "Bearer not-a-token"})

    assert res.status_code in (401, 403)
