"""What the team costs to run, and how much of it is left.

Two halves, and the seam between them is the whole point.

**Measured.** For providers Cerebro calls itself -- LM Studio, Gemini, anything OpenAI-compatible --
every turn already yields a `Usage` delta with real input/output token counts. Until now those were
published to the hub and dropped. Here they are accumulated into `budget_usage`, a table that has
existed since `001_init.sql` and had never been written to once.

**Self-reported.** For CLI-backed agents (`claude`, `codex`, `agy`) the number that actually governs
the day is not tokens, it is how much of a five-hour or weekly harness window remains. That lives
inside another vendor's process and Cerebro cannot see it. So the agent reports it, and we record
who said it and when.

The seam is deliberate and is never smoothed over. `source` is on every row of the board, and a
self-reported figure carries its age. Dante has read these numbers out loud to the team by hand
several times; the fix for that is a board that is honest about which half a number came from, not
one that presents an estimate with the same face as a measurement.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from cerebro import db

log = logging.getLogger(__name__)

#: A self-reported quota older than this is shown as stale rather than current. It is not deleted --
#: "Codex said 16% four hours ago" is still information, as long as nobody mistakes it for now.
STALE_AFTER = timedelta(minutes=90)

MEASURED = "measured"
SELF_REPORTED = "self-reported"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today(at: datetime | None = None) -> str:
    return (at or _now()).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class QuotaReport:
    """One agent's statement about its own remaining harness window."""

    agent_id: str
    window_name: str
    pct_remaining: float | None
    resets_at: str | None
    note: str | None
    reported_at: str
    reported_by: str

    @property
    def is_relayed(self) -> bool:
        """Somebody other than the agent itself made this claim."""
        return self.reported_by != self.agent_id

    @property
    def age(self) -> timedelta:
        try:
            when = datetime.fromisoformat(self.reported_at)
        except ValueError:
            return timedelta.max
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return _now() - when

    @property
    def is_stale(self) -> bool:
        return self.age > STALE_AFTER


async def record_turn_usage(
    agent_id: str,
    input_tokens: int,
    output_tokens: int,
    at: datetime | None = None,
) -> None:
    """Accumulate one turn's measured token usage for `agent_id`.

    Deliberately swallows its own failures. Accounting is not worth losing a turn over: if this
    raised into `AgentRuntime.run_turn`, a locked database would stop the team talking in order to
    protect a statistic. It logs loudly instead, which is the correct trade in this direction only.
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return

    window_start = _today(at)
    try:
        future = await db.enqueue_write(
            """
            INSERT INTO budget_usage
                (scope, scope_id, period, window_start, calls, input_tokens, output_tokens,
                 usd, delegations)
            VALUES ('agent', ?, 'day', ?, 1, ?, ?, NULL, 0)
            ON CONFLICT(scope, scope_id, period, window_start) DO UPDATE SET
                calls         = calls + 1,
                input_tokens  = input_tokens + excluded.input_tokens,
                output_tokens = output_tokens + excluded.output_tokens
            """,
            (agent_id, window_start, int(input_tokens), int(output_tokens)),
        )
        await future
    except Exception:  # noqa: BLE001 - see docstring
        log.exception("failed to record usage for %s; the turn is unaffected", agent_id)


async def report_quota(
    agent_id: str,
    window_name: str,
    pct_remaining: float | None,
    reported_by: str,
    resets_at: str | None = None,
    note: str | None = None,
    at: datetime | None = None,
) -> QuotaReport:
    """Record a statement about `agent_id`'s remaining window, made by `reported_by`.

    `reported_by` MUST come from the authenticated principal and never from a request body. An agent
    able to file a report as another agent could make a teammate look exhausted and take its work --
    the same attribution rule as §6.2, applied to a number instead of a sentence. The caller is
    responsible for deciding whether `reported_by` is allowed to speak for `agent_id`; see
    `routes_usage`.
    """
    if pct_remaining is not None:
        if not 0.0 <= float(pct_remaining) <= 100.0:
            raise ValueError(f"pct_remaining must be 0..100, got {pct_remaining!r}")
        pct_remaining = float(pct_remaining)

    reported_at = (at or _now()).isoformat()
    future = await db.enqueue_write(
        """
        INSERT INTO agent_quota
            (agent_id, window_name, pct_remaining, resets_at, note, reported_at, reported_by)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(agent_id, window_name) DO UPDATE SET
            pct_remaining = excluded.pct_remaining,
            resets_at     = excluded.resets_at,
            note          = excluded.note,
            reported_at   = excluded.reported_at,
            reported_by   = excluded.reported_by
        """,
        (agent_id, window_name, pct_remaining, resets_at, note, reported_at, reported_by),
    )
    await future
    return QuotaReport(
        agent_id, window_name, pct_remaining, resets_at, note, reported_at, reported_by
    )


async def quotas_for(agent_id: str) -> list[QuotaReport]:
    rows = await db.fetch_all(
        "SELECT * FROM agent_quota WHERE agent_id = ? ORDER BY window_name", (agent_id,)
    )
    return [_to_report(r) for r in rows]


def _to_report(row: dict[str, Any]) -> QuotaReport:
    return QuotaReport(
        agent_id=row["agent_id"],
        window_name=row["window_name"],
        pct_remaining=row["pct_remaining"],
        resets_at=row["resets_at"],
        note=row["note"],
        reported_at=row["reported_at"],
        reported_by=row["reported_by"],
    )


async def board(day: str | None = None) -> dict[str, Any]:
    """The whole team on one screen: what each agent has spent, and what it says it has left.

    Every entry names its `source`. An agent with no measured tokens and no self-report appears with
    both halves empty rather than being omitted -- "we do not know what this agent is costing" is a
    fact worth showing, and dropping the row would hide it.
    """
    window_start = day or _today()

    spend_rows = await db.fetch_all(
        """
        SELECT scope_id AS agent_id, calls, input_tokens, output_tokens
        FROM budget_usage
        WHERE scope = 'agent' AND period = 'day' AND window_start = ?
        """,
        (window_start,),
    )
    quota_rows = await db.fetch_all("SELECT * FROM agent_quota")

    agents: dict[str, dict[str, Any]] = {}

    for row in spend_rows:
        agents.setdefault(row["agent_id"], _blank(row["agent_id"]))["measured"] = {
            "source": MEASURED,
            "calls": row["calls"] or 0,
            "input_tokens": row["input_tokens"] or 0,
            "output_tokens": row["output_tokens"] or 0,
            "total_tokens": (row["input_tokens"] or 0) + (row["output_tokens"] or 0),
        }

    for row in quota_rows:
        report = _to_report(row)
        entry = agents.setdefault(report.agent_id, _blank(report.agent_id))
        entry["windows"].append(
            {
                "source": SELF_REPORTED,
                "window": report.window_name,
                "pct_remaining": report.pct_remaining,
                "resets_at": report.resets_at,
                "note": report.note,
                "reported_at": report.reported_at,
                "reported_by": report.reported_by,
                "relayed": report.is_relayed,
                "age_seconds": int(report.age.total_seconds())
                if report.age is not timedelta.max
                else None,
                "stale": report.is_stale,
            }
        )

    for entry in agents.values():
        entry["windows"].sort(key=lambda w: w["window"])

    return {
        "day": window_start,
        "stale_after_seconds": int(STALE_AFTER.total_seconds()),
        "agents": sorted(agents.values(), key=lambda a: a["agent_id"]),
    }


def _blank(agent_id: str) -> dict[str, Any]:
    return {"agent_id": agent_id, "measured": None, "windows": []}
