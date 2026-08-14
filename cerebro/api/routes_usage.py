"""REST routes for the usage board (§13.2).

Reading is open to the whole team on purpose. Dante's fourth requirement was that agents can see
each other's usage, and it is what lets us self-organise: when Codex is at 16% of a weekly window,
the right move is for Antigravity to pick up the implementation, and that decision should not need
Dante to notice and say so.

Writing is narrow. An agent may file a report about itself and nothing else.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from cerebro import usage
from cerebro.auth import Principal, get_current_principal

router = APIRouter(prefix="/api/usage", tags=["usage"])


class QuotaReportRequest(BaseModel):
    """A statement about a remaining harness window.

    `agent_id` is optional and exists for the relay case only -- Dante reading a percentage off a
    harness UI for an agent that cannot see its own meter. An agent omits it. An agent that sends
    somebody else's id is refused rather than quietly rewritten, because silently correcting a
    request teaches the caller nothing and hides an attempt worth seeing.
    """

    window: str = Field(..., min_length=1, max_length=32)
    pct_remaining: Optional[float] = Field(None, ge=0, le=100)
    resets_at: Optional[str] = None
    note: Optional[str] = Field(None, max_length=500)
    agent_id: Optional[str] = None


@router.get("")
async def get_usage_board(
    day: Optional[str] = Query(None, description="YYYY-MM-DD, defaults to today (UTC)"),
    principal: Principal = Depends(get_current_principal),
):
    """The team's spend and remaining windows. Visible to every authenticated principal."""
    return await usage.board(day)


@router.post("/quota")
async def post_quota(
    body: QuotaReportRequest,
    principal: Principal = Depends(get_current_principal),
):
    """File a quota report.

    Authorisation is the whole substance of this route:

    - An agent may report only about itself. `reported_by` is taken from the bearer principal, so an
      agent cannot file as a teammate even if it sends one in the body.
    - Dante (§6.1) may relay for any agent, and the row records that he was the one who said it.
    """
    subject = body.agent_id or principal.id

    if principal.is_agent and subject != principal.id:
        raise HTTPException(
            status_code=403,
            detail=(
                f"{principal.id} cannot report quota for {subject}. An agent reports only its own "
                "window; attribution is assigned by the server, never claimed by the caller."
            ),
        )

    try:
        report = await usage.report_quota(
            agent_id=subject,
            window_name=body.window,
            pct_remaining=body.pct_remaining,
            reported_by=principal.id,
            resets_at=body.resets_at,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "agent_id": report.agent_id,
        "window": report.window_name,
        "pct_remaining": report.pct_remaining,
        "resets_at": report.resets_at,
        "note": report.note,
        "reported_at": report.reported_at,
        "reported_by": report.reported_by,
        "relayed": report.is_relayed,
    }
