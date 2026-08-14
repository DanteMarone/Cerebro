"""REST API routes for channels and channel message history."""

from typing import Any, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from cerebro import store

router = APIRouter(prefix="/api/channels", tags=["channels"])


class CreateMessageRequest(BaseModel):
    content: str
    author_id: str = "dante"
    type: str = "text"
    turn_id: Optional[str] = None
    parent_id: Optional[int] = None


@router.get("")
async def get_channels():
    """List all available channels."""
    channels = await store.list_channels()
    return {"channels": channels}


@router.get("/{channel_id}")
async def get_channel_by_id(channel_id: str):
    """Retrieve details for a single channel."""
    channel = await store.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")
    members = await store.get_channel_members(channel_id)
    return {"channel": channel, "members": members}


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
        author_id=req.author_id,
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
