"""WebSocket endpoint for Cerebro v2 live event streaming."""

import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from cerebro import store
from cerebro.auth import HUMAN, get_token_store, parse_bearer, principal_for
from cerebro.hub import Hub

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Handle bi-directional WebSocket connection with principal resolution."""
    # Resolve principal on connect from Authorization header and keep for socket lifetime (§6.3)
    headers = getattr(websocket, "headers", None) or {}
    auth_header = headers.get("authorization")
    if auth_header is not None:
        token = parse_bearer(auth_header)
        if not token:
            await websocket.close(code=4401, reason="malformed authorization")
            return
        token_store = getattr(websocket.app.state, "token_store", None) or get_token_store()
        try:
            principal = principal_for(token, token_store)
        except PermissionError:
            await websocket.close(code=4401, reason="unrecognised agent token")
            return
    else:
        principal = HUMAN

    await websocket.accept()
    hub: Hub | None = getattr(websocket.app.state, "hub", None)
    if hub is None:
        await websocket.close(code=1011, reason="Event hub not initialized")
        return

    sub = hub.subscribe("*")

    async def outbound_pump():
        """Fan events from the hub subscription to the WebSocket client."""
        try:
            async for event in sub:
                envelope = {
                    "type": event.type,
                    "payload": event.payload,
                    "seq": event.seq,
                    "ts": event.ts,
                }
                await websocket.send_text(json.dumps(envelope))
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.debug(f"Outbound WebSocket error: {exc}")

    async def inbound_pump():
        """Receive user/agent messages from WebSocket client and publish to hub."""
        try:
            while True:
                data_text = await websocket.receive_text()
                try:
                    data = json.loads(data_text)
                except Exception:
                    continue

                msg_type = data.get("type")
                payload = data.get("payload", {})

                if msg_type in ("message.send", "message.new"):
                    channel_id = payload.get("channel_id")
                    content = (payload.get("content") or "").strip()

                    if channel_id and content:
                        msg_id = await store.append_message(
                            channel_id=channel_id,
                            author_id=principal.id,
                            author_kind=principal.author_kind,
                            content=content,
                        )
                        message = await store.get_message(msg_id)
                        await hub.publish(
                            "message.new",
                            {"channel_id": channel_id, "message": message},
                        )
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception as exc:
            logger.debug(f"Inbound WebSocket error: {exc}")

    outbound_task = asyncio.create_task(outbound_pump())
    inbound_task = asyncio.create_task(inbound_pump())

    try:
        done, pending = await asyncio.wait(
            [outbound_task, inbound_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    finally:
        sub.close()
