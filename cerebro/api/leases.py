"""REST API routes for distributed mutex leases (§8.7)."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from cerebro import store
from cerebro.auth import Principal, get_current_principal
from cerebro.models import LeaseConflictError

router = APIRouter(prefix="/api/leases", tags=["leases"])


class AcquireLeaseRequest(BaseModel):
    resource: str = Field(..., min_length=1, max_length=255)
    ttl_s: int = Field(600, ge=1, le=86400)
    reason: str = Field("", max_length=1000)
    channel_id: Optional[str] = None


class ReleaseLeaseRequest(BaseModel):
    resource: str = Field(..., min_length=1, max_length=255)


class RenewLeaseRequest(BaseModel):
    resource: str = Field(..., min_length=1, max_length=255)
    ttl_s: int = Field(600, ge=1, le=86400)


@router.get("")
async def list_leases(
    request: Request,
    include_expired: bool = False,
    principal: Principal = Depends(get_current_principal),
):
    """List all active leases (or all including expired if requested)."""
    hub = getattr(request.app.state, "hub", None)
    leases = await store.list_leases(include_expired=include_expired, hub=hub)
    return {"leases": [lease.model_dump() for lease in leases]}


@router.post("/acquire")
async def acquire_lease(
    req: AcquireLeaseRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Atomically acquire or re-acquire a lease on a resource."""
    is_owner = (principal.id == "dante")
    try:
        lease = await store.acquire_lease(
            resource=req.resource,
            holder_id=principal.id,
            holder_kind=principal.kind,
            ttl_s=req.ttl_s,
            reason=req.reason,
            channel_id=req.channel_id,
            is_owner=is_owner,
        )
    except LeaseConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "lease_conflict",
                "resource": exc.resource,
                "holder_id": exc.holder_id,
                "expires_at": exc.expires_at,
                "reason": exc.reason,
                "message": str(exc),
            },
        )

    # Broadcast Hub event
    hub = getattr(request.app.state, "hub", None)
    if hub is not None:
        await hub.publish("lease.acquired", lease.model_dump())

    return {"lease": lease.model_dump()}


@router.post("/release")
async def release_lease(
    req: ReleaseLeaseRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Release a lease. Only the active holder or owner (Dante) may release."""
    is_owner = (principal.id == "dante")
    try:
        released = await store.release_lease(
            resource=req.resource,
            holder_id=principal.id,
            is_owner=is_owner,
        )
    except LeaseConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "lease_conflict",
                "resource": exc.resource,
                "holder_id": exc.holder_id,
                "expires_at": exc.expires_at,
                "reason": exc.reason,
                "message": str(exc),
            },
        )

    if released:
        hub = getattr(request.app.state, "hub", None)
        if hub is not None:
            await hub.publish(
                "lease.released",
                {"resource": req.resource, "holder_id": principal.id},
            )

    return {"released": released, "resource": req.resource}


@router.post("/renew")
async def renew_lease(
    req: RenewLeaseRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Extend the expiration time of an active lease."""
    is_owner = (principal.id == "dante")
    try:
        lease = await store.renew_lease(
            resource=req.resource,
            holder_id=principal.id,
            ttl_s=req.ttl_s,
            is_owner=is_owner,
        )
    except LeaseConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "lease_conflict",
                "resource": exc.resource,
                "holder_id": exc.holder_id,
                "expires_at": exc.expires_at,
                "reason": exc.reason,
                "message": str(exc),
            },
        )

    hub = getattr(request.app.state, "hub", None)
    if hub is not None:
        await hub.publish("lease.acquired", lease.model_dump())

    return {"lease": lease.model_dump()}


# -- path checking, for the commit guard -------------------------------------------
#
# The matching rules live here rather than in scripts/lease_guard.py deliberately. A guard that
# reimplements "does this lease cover this file" drifts from the server the moment either side
# changes, and then reports confidently using the wrong rules. The hook asks; this answers.


def _covers(resource: str, path: str) -> bool:
    """Does a lease on `resource` cover the repo-relative `path`?

    Only `file:` leases cover paths. `repo:Cerebro:HEAD` governs moving the branch, not the contents
    of a commit, and conflating the two would let one HEAD lease authorise editing anything.

    A directory lease covers everything beneath it, because the alternative is twenty declarations
    per slice and people quietly stop declaring.
    """
    if not resource.startswith("file:"):
        return False

    target = resource[len("file:"):].strip().replace("\\", "/").strip("/")
    candidate = path.strip().replace("\\", "/").strip("/")
    if not target:
        return False
    return candidate == target or candidate.startswith(target + "/")


@router.get("/check")
async def check_paths(
    request: Request,
    path: list[str] = Query(default=[], description="Repo-relative paths to check"),
    principal: Principal = Depends(get_current_principal),
):
    """Report whether the authenticated principal holds a lease covering each path.

    Identity comes from the bearer principal, never from a query parameter -- otherwise the guard
    could be told whose leases to consult, which is the same hole as claiming attribution.
    """
    leases = await store.list_leases(
        include_expired=False, hub=getattr(request.app.state, "hub", None)
    )
    is_owner = principal.id == "dante"

    results = []
    for candidate in path:
        covering = [lease for lease in leases if _covers(lease.resource, candidate)]
        mine = [lease for lease in covering if lease.holder_id == principal.id]
        others = [lease for lease in covering if lease.holder_id != principal.id]
        results.append(
            {
                "path": candidate,
                "held": bool(mine) or is_owner,
                "by_owner_override": bool(is_owner and not mine),
                "matched_resource": mine[0].resource if mine else None,
                "held_by": others[0].holder_id if others else None,
                "conflicting_resource": others[0].resource if others else None,
            }
        )

    return {
        "principal": principal.id,
        "is_owner": is_owner,
        "results": results,
        "all_held": all(r["held"] for r in results) if results else True,
    }
