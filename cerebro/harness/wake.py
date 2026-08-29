"""`CausalWakeKey`: one semantic wake admits one durable turn.

The key exists so that a duplicate delivery converges on the turn it already created, while a
legitimate later occurrence still gets its own execution. Those are different situations, and a
uniqueness constraint that cannot tell them apart either double-executes or wedges the agent.

For a message-driven wake the trigger message is the occurrence identity. Everything else — an
explicit turn, a poll with no durable trigger message, any future recurring kind — must supply an
`occurrence_id` from the wake layer, because there is nothing else to distinguish "again" from
"the same one twice".
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, model_validator

__all__ = ["CAUSAL_WAKE_KEY_VERSION", "CausalWakeKey", "WakeKind"]

CAUSAL_WAKE_KEY_VERSION = 1

WakeKind = Literal["direct_message", "channel_poll", "explicit_turn"]

_MESSAGE_DRIVEN: frozenset[str] = frozenset({"direct_message", "channel_poll"})


class CausalWakeKey(BaseModel):
    """A versioned, deterministically serializable wake identity."""

    model_config = {"frozen": True}

    key_version: int = CAUSAL_WAKE_KEY_VERSION
    wake_kind: WakeKind
    target_agent_id: str
    channel_id: str
    trigger_message_id: int | None = None
    occurrence_id: str | None = None

    @model_validator(mode="after")
    def _occurrence_identity_present(self) -> "CausalWakeKey":
        if self.wake_kind in _MESSAGE_DRIVEN:
            if self.trigger_message_id is None and not self.occurrence_id:
                raise ValueError(
                    f"a {self.wake_kind} wake needs a trigger_message_id, or an explicit "
                    f"occurrence_id when the wake layer has no durable trigger message"
                )
            return self
        if not self.occurrence_id:
            raise ValueError(
                f"a {self.wake_kind} wake requires a durable occurrence_id; without one a "
                f"legitimate repeat is indistinguishable from a duplicate delivery"
            )
        return self

    def serialized(self) -> str:
        """The exact text the admission store's uniqueness constraint is built on."""
        occurrence: str | int
        if self.wake_kind in _MESSAGE_DRIVEN and self.trigger_message_id is not None:
            occurrence = self.trigger_message_id
        else:
            occurrence = self.occurrence_id or ""
        payload = {
            "v": self.key_version,
            "kind": self.wake_kind,
            "agent": self.target_agent_id,
            "channel": self.channel_id,
            "occurrence": occurrence,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def stable_hash(self) -> str:
        """A fixed-width form for indexing, derived only from `serialized()`."""
        return hashlib.sha256(self.serialized().encode("utf-8")).hexdigest()
