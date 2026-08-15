"""REST API routes for channels and channel message history."""

import re
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from cerebro import store
from cerebro.auth import Principal, get_current_principal

router = APIRouter(prefix="/api/channels", tags=["channels"])


class CreateChannelRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    id: Optional[str] = None
    topic: Optional[str] = ""
    kind: str = "topic"
    team_id: str = "personal-assistant"
    member_ids: list[str] = []


class AddMemberRequest(BaseModel):
    member_id: str
    member_kind: str = "agent"
    listen_mode: str = "auto"


class UpdateMemberRequest(BaseModel):
    listen_mode: str = Field(..., pattern="^(active|mention_only|muted)$")


class CreateMessageRequest(BaseModel):
    content: str
    author_id: str = "dante"
    type: str = "text"
    turn_id: Optional[str] = None
    parent_id: Optional[int] = None


def _slugify(text: str) -> str:
    """Convert name to safe channel ID."""
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip().lower()).strip("-")
    return slug or "channel"


@router.get("")
async def get_channels(principal: Principal = Depends(get_current_principal)):
    """List all available channels for the principal.

    - Human (Dante): sees all channels (§6.1).
    - Agent: sees only channels it is enrolled in as a member.
    - Includes unread_count per channel for the caller (§6).
    - Unauthenticated: refused with 401.
    """
    channels = await store.list_channels()
    if principal.is_agent:
        visible = []
        for ch in channels:
            members = await store.get_channel_members(ch["id"])
            if any(m["member_id"] == principal.id for m in members):
                ch_copy = dict(ch)
                ch_copy["unread_count"] = await store.get_unread_count(ch["id"], principal.id)
                visible.append(ch_copy)
        return {"channels": visible}

    result = []
    for ch in channels:
        ch_copy = dict(ch)
        ch_copy["unread_count"] = await store.get_unread_count(ch["id"], principal.id)
        result.append(ch_copy)
    return {"channels": result}


@router.post("", status_code=201)
async def create_channel(
    req: CreateChannelRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Create a channel (§6.4).

    Agents may create channels. The guard this replaces refused them entirely, which defended
    against agents opening rooms that exclude Dante -- something §6.1 already makes impossible,
    since he is added unconditionally and cannot be removed. It cost a capability specified since
    the first draft and bought nothing.

    What an agent may not do is create a room it is not itself in: that would let it arrange a
    conversation between Dante and a third party while standing outside it.
    """
    members = list(req.member_ids)
    if principal.is_agent and principal.id not in members:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Agent '{principal.id}' must include itself in 'member_ids' when creating "
                "a channel (§6.4)."
            ),
        )

    channel_id = (req.id or _slugify(req.name)).strip()
    if not channel_id:
        raise HTTPException(status_code=400, detail="Invalid channel ID")

    existing = await store.get_channel(channel_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Channel '{channel_id}' already exists")

    if principal.is_agent:
        created_by = principal.id
    else:
        created_by = "dante"

    await store.create_channel(
        channel_id=channel_id,
        name=req.name.strip(),
        team_id=req.team_id,
        kind=req.kind,
        topic=req.topic or "",
        created_by=created_by,
    )

    # Add initial agent members (Dante is already added as owner by create_channel)
    for m_id in members:
        if m_id and m_id != "dante":
            await store.add_channel_member(
                channel_id=channel_id,
                member_id=m_id,
                member_kind="agent",
                listen_mode="auto",
            )

    channel = await store.get_channel(channel_id)
    roster = await store.get_channel_members(channel_id)

    # Without this the sidebar only ever populates on mount, so a channel created while the page
    # is open -- by Dante in another tab, or by an agent under §6.4 -- stays invisible until F5.
    hub: Any = getattr(request.app.state, "hub", None)
    if hub is not None:
        await hub.publish("channel.new", {"channel": channel, "members": roster})

    return {"channel": channel, "members": roster}


@router.get("/{channel_id}")
async def get_channel_by_id(
    channel_id: str,
    principal: Principal = Depends(get_current_principal),
):
    """Retrieve details for a single channel.

    - Dante: sees all channels.
    - Agent: sees only channels it belongs to (403 otherwise).
    - Unauthenticated: refused with 401.
    """
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")
    members = await store.get_channel_members(channel_id)
    if principal.is_agent and not any(
        m["member_id"] == principal.id for m in members
    ):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{principal.id}' is not a member of channel '{channel_id}'",
        )
    return {"channel": channel, "members": members}


@router.get("/{channel_id}/members")
async def get_channel_members_list(
    channel_id: str,
    principal: Principal = Depends(get_current_principal),
):
    """Retrieve roster of members for a channel.

    - Dante: sees all channel rosters.
    - Agent: sees only rosters for channels it belongs to (403 otherwise).
    - Unauthenticated: refused with 401.
    """
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")
    members = await store.get_channel_members(channel_id)
    if principal.is_agent and not any(
        m["member_id"] == principal.id for m in members
    ):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{principal.id}' is not a member of channel '{channel_id}'",
        )
    return {"channel_id": channel_id, "members": members}


@router.post("/{channel_id}/members", status_code=201)
async def add_channel_member(
    channel_id: str,
    req: AddMemberRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Add a member (§6.4).

    An agent may invite peers into a channel it is already in — that is the point of an agent
    recruiting the expertise it needs. It may not add members to rooms it is not part of, and
    removal stays human-only.
    """
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    if principal.is_agent:
        roster = await store.get_channel_members(channel_id)
        if not any(m["member_id"] == principal.id for m in roster):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Agent '{principal.id}' is not a member of '{channel_id}' and cannot "
                    "invite others into it (§6.4)."
                ),
            )

    await store.add_channel_member(
        channel_id=channel_id,
        member_id=req.member_id,
        member_kind=req.member_kind,
        listen_mode=req.listen_mode,
    )
    members = await store.get_channel_members(channel_id)

    hub: Any = getattr(request.app.state, "hub", None)
    if hub is not None:
        await hub.publish("channel.update", {"channel": channel, "members": members})

    return {"ok": True, "members": members}


@router.patch("/{channel_id}/members/{member_id}")
async def update_channel_member(
    channel_id: str,
    member_id: str,
    req: UpdateMemberRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Mute or unmute a member ("kick" without losing history), refusing for Dante (§6.1).

    Muting stops the member from being offered a turn (service.py's `_responder` and the poller's
    `_channels_for` both skip muted rows) while leaving it in the roster: the room's history and
    the member's own context stay intact, so unmuting brings it right back in rather than requiring
    a fresh invite.
    """
    if principal.is_agent:
        raise HTTPException(status_code=403, detail="Agent member administration not permitted")

    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    try:
        await store.set_member_listen_mode(channel_id, member_id, req.listen_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    members = await store.get_channel_members(channel_id)

    hub: Any = getattr(request.app.state, "hub", None)
    if hub is not None:
        await hub.publish("channel.update", {"channel": channel, "members": members})

    return {"ok": True, "members": members}


@router.delete("/{channel_id}/members/{member_id}")
async def remove_channel_member(
    channel_id: str,
    member_id: str,
    principal: Principal = Depends(get_current_principal),
):
    """Remove a member from a channel, refusing for Dante (§6.1)."""
    if principal.is_agent:
        raise HTTPException(status_code=403, detail="Agent member administration not permitted")

    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    try:
        await store.remove_channel_member(channel_id, member_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    members = await store.get_channel_members(channel_id)
    return {"ok": True, "members": members}


@router.get("/{channel_id}/messages")
async def get_channel_messages(
    channel_id: str,
    after: Optional[int] = Query(
        None, description="Return messages with ID greater than this value"
    ),
    limit: int = Query(50, ge=1, le=200),
    principal: Principal = Depends(get_current_principal),
):
    """Retrieve message history for a channel, optionally after a message ID.

    - Dante: sees all channel histories.
    - Agent: sees only messages in channels it belongs to (403 otherwise).
    - Unauthenticated: refused with 401.
    """
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    if principal.is_agent:
        members = await store.get_channel_members(channel_id)
        if not any(m["member_id"] == principal.id for m in members):
            raise HTTPException(
                status_code=403,
                detail=f"Agent '{principal.id}' is not a member of channel '{channel_id}'",
            )

    messages = await store.list_messages(channel_id, after_id=after, limit=limit)
    return {"messages": messages}


@router.post("/{channel_id}/messages")
async def post_channel_message(
    channel_id: str,
    req: CreateMessageRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Append a new message to a channel and publish message.new event to hub.

    Enforces §6.3 channel membership: an agent may post only into channels it belongs to.
    """
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    # Enforce agent channel membership (§6.3)
    if principal.is_agent:
        members = await store.get_channel_members(channel_id)
        if not any(m["member_id"] == principal.id for m in members):
            raise HTTPException(
                status_code=403,
                detail=f"Agent '{principal.id}' is not a member of channel '{channel_id}'",
            )

    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    msg_id = await store.append_message(
        channel_id=channel_id,
        author_id=principal.id,
        author_kind=principal.author_kind,
        content=content,
        msg_type=req.type,
        turn_id=req.turn_id,
        parent_id=req.parent_id,
    )
    message = await store.get_message(msg_id)

    # Publish event to Hub if available
    hub: Any = getattr(request.app.state, "hub", None)
    if hub is not None:
        await hub.publish("message.new", {"channel_id": channel_id, "message": message})

    return message


class UpdateReadCursorRequest(BaseModel):
    message_id: int = Field(..., ge=0)


@router.patch("/{channel_id}/read")
async def update_channel_read_cursor(
    channel_id: str,
    req: UpdateReadCursorRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Advance the caller's read cursor for a channel (§6)."""
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    members = await store.get_channel_members(channel_id)
    if principal.is_agent and not any(m["member_id"] == principal.id for m in members):
        raise HTTPException(
            status_code=403,
            detail=f"Agent '{principal.id}' is not a member of channel '{channel_id}'",
        )

    await store.update_read_cursor(channel_id, principal.id, req.message_id)

    hub: Any = getattr(request.app.state, "hub", None)
    if hub is not None:
        await hub.publish("channel.read", {
            "channel_id": channel_id,
            "member_id": principal.id,
            "message_id": req.message_id,
        })

    return {
        "ok": True,
        "channel_id": channel_id,
        "member_id": principal.id,
        "last_read_message_id": req.message_id,
    }
