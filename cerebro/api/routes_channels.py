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
async def get_channels():
    """List all available channels."""
    channels = await store.list_channels()
    return {"channels": channels}


@router.post("", status_code=201)
async def create_channel(req: CreateChannelRequest):
    """Create a new channel, unconditionally enrolling Dante (§6.1)."""
    channel_id = (req.id or _slugify(req.name)).strip()
    if not channel_id:
        raise HTTPException(status_code=400, detail="Invalid channel ID")

    existing = await store.get_channel(channel_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Channel '{channel_id}' already exists")

    await store.create_channel(
        channel_id=channel_id,
        name=req.name.strip(),
        team_id=req.team_id,
        kind=req.kind,
        topic=req.topic or "",
        created_by="dante",
    )

    # Add any requested initial members (Dante is already added by create_channel)
    for m_id in req.member_ids:
        if m_id and m_id != "dante":
            await store.add_channel_member(
                channel_id=channel_id,
                member_id=m_id,
                member_kind="agent",
                listen_mode="auto",
            )

    channel = await store.get_channel(channel_id)
    members = await store.get_channel_members(channel_id)
    return {"channel": channel, "members": members}


@router.get("/{channel_id}")
async def get_channel_by_id(channel_id: str):
    """Retrieve details for a single channel."""
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")
    members = await store.get_channel_members(channel_id)
    return {"channel": channel, "members": members}


@router.get("/{channel_id}/members")
async def get_channel_members_list(channel_id: str):
    """Retrieve roster of members for a channel."""
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")
    members = await store.get_channel_members(channel_id)
    return {"channel_id": channel_id, "members": members}


@router.post("/{channel_id}/members", status_code=201)
async def add_channel_member(channel_id: str, req: AddMemberRequest):
    """Add a member to a channel."""
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

    await store.add_channel_member(
        channel_id=channel_id,
        member_id=req.member_id,
        member_kind=req.member_kind,
        listen_mode=req.listen_mode,
    )
    members = await store.get_channel_members(channel_id)
    return {"ok": True, "members": members}


@router.delete("/{channel_id}/members/{member_id}")
async def remove_channel_member(channel_id: str, member_id: str):
    """Remove a member from a channel, refusing for Dante (§6.1)."""
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
):
    """Retrieve message history for a channel, optionally after a message ID."""
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")
    messages = await store.list_messages(channel_id, after_id=after, limit=limit)
    return {"messages": messages}


@router.post("/{channel_id}/messages")
async def post_channel_message(
    channel_id: str,
    req: CreateMessageRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
):
    """Append a new message to a channel and publish message.new event to hub."""
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")

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
