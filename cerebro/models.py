"""Data models for Cerebro v2.

Pydantic models mirroring the SQLite schema rows, plus the Delta union.
Types only — no behavior.
"""

from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field


# --- Database Entity Models ---

class Team(BaseModel):
    id: str
    slug: str
    name: str
    description: str | None = None
    workspace_path: str | None = None
    created_at: str | None = None


class Agent(BaseModel):
    id: str
    name: str
    display_name: str | None = None
    avatar: str | None = None
    role: str | None = None
    provider: str = "lmstudio"
    model: str | None = None
    params_json: str | None = None
    api_key_ref: str | None = None
    home_path: str | None = None
    enabled: int = 1
    delegation_enabled: int = 0
    created_at: str | None = None


class AgentTeam(BaseModel):
    agent_id: str
    team_id: str


class Channel(BaseModel):
    id: str
    team_id: str | None = None
    kind: str = "channel"  # 'channel' | 'dm' | 'war_room'
    name: str
    topic: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    archived_at: str | None = None
    summary: str | None = None
    summary_upto_msg: int | None = None


class ChannelMember(BaseModel):
    channel_id: str
    member_id: str
    member_kind: str = "agent"  # 'user' | 'agent'
    listen_mode: str = "active"  # 'active' | 'mention_only' | 'muted'
    joined_at: str | None = None


class Message(BaseModel):
    id: int | None = None
    channel_id: str
    author_id: str
    author_kind: str = "agent"  # 'user' | 'agent' | 'system'
    kind: str = "chat"          # 'chat' | 'system' | 'tool' | 'event' | 'error'
    body: str
    quote_msg_id: int | None = None
    turn_id: str | None = None
    depth: int = 0
    created_at: str | None = None
    meta_json: str | None = None


class ToolCall(BaseModel):
    id: str
    message_id: int | None = None
    agent_id: str
    server: str
    tool: str
    args_json: str | None = None
    result_json: str | None = None
    status: str = "pending"
    error: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: int | None = None


class Task(BaseModel):
    id: str
    title: str
    body: str | None = None
    owner_agent_id: str | None = None
    channel_id: str | None = None
    team_id: str | None = None
    status: str = "open"  # 'open' | 'in_progress' | 'blocked' | 'done' | 'cancelled'
    artifacts_json: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    due_at: str | None = None


class CronJob(BaseModel):
    id: str
    agent_id: str
    cron_expr: str
    timezone: str = "UTC"
    target_channel_id: str | None = None
    prompt: str
    enabled: int = 1
    last_run_at: str | None = None
    next_run_at: str | None = None


class AuditEvent(BaseModel):
    id: int | None = None
    ts: str
    actor_id: str
    actor_kind: str
    action: str
    target: str | None = None
    detail_json: str | None = None
    revert_ref: str | None = None
    reverted_at: str | None = None


class BudgetUsage(BaseModel):
    scope: str
    scope_id: str
    period: str
    window_start: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    delegations: int = 0


# --- Provider Stream Delta Union (§9) ---

class TextDelta(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolCallDelta(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    id: str
    name: str
    args_fragment: str


class ReasoningDelta(BaseModel):
    """Chain-of-thought emitted by a reasoning model.

    Kept distinct from TextDelta because it is shown live and then discarded -- it never becomes
    the message body. gpt-oss-20b, which Dante runs locally, streams this before any content, so
    dropping it means the UI shows a long silence and then an answer.
    """

    type: Literal["reasoning"] = "reasoning"
    text: str


class Usage(BaseModel):
    type: Literal["usage"] = "usage"
    input: int
    output: int


class Done(BaseModel):
    type: Literal["done"] = "done"
    reason: str


Delta = Annotated[
    Union[TextDelta, ReasoningDelta, ToolCallDelta, Usage, Done],
    Field(discriminator="type"),
]


# --- Leases (§8.7) ---

class Lease(BaseModel):
    resource: str
    holder_id: str
    holder_kind: str = "agent"  # 'agent' | 'user'
    channel_id: str | None = None
    reason: str = ""
    acquired_at: str
    expires_at: str


class LeaseConflictError(Exception):
    """Raised when an attempt to acquire or mutate a lease conflicts with another holder."""

    def __init__(self, resource: str, holder_id: str, expires_at: str, reason: str = ""):
        self.resource = resource
        self.holder_id = holder_id
        self.expires_at = expires_at
        self.reason = reason
        super().__init__(
            f"Resource '{resource}' is currently held by '{holder_id}' until {expires_at} "
            f"(reason: '{reason}')"
        )
