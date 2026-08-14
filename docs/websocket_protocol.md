# Cerebro v2 WebSocket Protocol

This document defines the WebSocket protocol implemented at the `/ws` endpoint in Cerebro v2 (Slice 1).

## 1. Connection & Endpoint

- **URI**: `/ws` (e.g. `ws://127.0.0.1:8765/ws` or `wss://<host>/ws`)
- **Protocol**: JSON text frames.
- **Connection Lifecycle**:
  - The client initiates connection to `/ws`.
  - The server accepts the WebSocket, subscribes to the internal process `Hub`, and streams all published events matching `*`.
  - On disconnection, the server cleanly unregisters the subscription.

---

## 2. Event Envelope

Every event transmitted from the server over `/ws` is serialized as a JSON object adhering to the process-monotonic envelope:

```json
{
  "type": "message.new",
  "payload": { ... },
  "seq": 42,
  "ts": 1723612800.123
}
```

### Fields
| Field | Type | Description |
| :--- | :--- | :--- |
| `type` | `string` | Event type identifier (e.g. `message.new`, `message.delta`). |
| `payload` | `object` | Type-specific event payload dictionary. |
| `seq` | `integer` | Process-monotonic integer sequence number assigned by the `Hub`. |
| `ts` | `float` | Unix epoch timestamp in seconds. |

---

## 3. Server Event Types

### `message.new`
Emitted when a complete new message is committed to a channel.

**Payload**:
```json
{
  "channel_id": "dm-dante-jarvis",
  "message": {
    "id": 1,
    "channel_id": "dm-dante-jarvis",
    "author_id": "dante",
    "content": "Hello Jarvis",
    "type": "text",
    "turn_id": null,
    "parent_id": null,
    "model": "",
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "created_at": "2026-08-14 00:00:00"
  }
}
```

### `message.delta`
Emitted during LLM streaming. Fragments arrive in sequential order and are concatenated by the client.

**Payload**:
```json
{
  "channel_id": "dm-dante-jarvis",
  "message_id": 2,
  "text": "Good evening, Dante."
}
```

### `message.done`
Emitted when an LLM turn is finalized. The payload contains the authoritative finished message row, replacing any accumulated delta buffer.

**Payload**:
```json
{
  "id": 2,
  "channel_id": "dm-dante-jarvis",
  "author_id": "jarvis",
  "content": "Good evening, Dante. How may I assist you?",
  "type": "text",
  "turn_id": "turn-123",
  "model": "gemma-4-26b",
  "prompt_tokens": 120,
  "completion_tokens": 15,
  "total_tokens": 135,
  "created_at": "2026-08-14 00:00:02"
}
```

### `agent.status`
Emitted when an agent state changes (e.g., `thinking`, `typing`, `idle`, `error`).

**Payload**:
```json
{
  "agent_id": "jarvis",
  "status": "thinking",
  "channel_id": "dm-dante-jarvis"
}
```

### `error`
Emitted when an unrecoverable turn or runtime error occurs.

**Payload**:
```json
{
  "channel_id": "dm-dante-jarvis",
  "message": "Model timeout from provider",
  "code": "PROVIDER_TIMEOUT"
}
```

---

## 4. Inbound Client Messages

Clients can dispatch messages over `/ws` using the `message.send` envelope:

```json
{
  "type": "message.send",
  "payload": {
    "channel_id": "dm-dante-jarvis",
    "content": "Hello Jarvis",
    "author_id": "dante"
  }
}
```

Alternatively, clients can post via `POST /api/channels/{channel_id}/messages`.

---

## 5. Reconnection & Gap Recovery

The client tracks the highest `id` of messages received in each channel. Upon WebSocket reconnection:
1. The client queries `GET /api/channels/{channel_id}/messages?after={last_message_id}` to retrieve any missed messages.
2. Lost streaming deltas during disconnection are not replayed; `message.done` / historical rows in SQLite provide the authoritative state.
