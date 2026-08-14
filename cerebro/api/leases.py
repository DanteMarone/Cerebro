"""REST API routes for distributed mutex leases (§8.7)."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
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
