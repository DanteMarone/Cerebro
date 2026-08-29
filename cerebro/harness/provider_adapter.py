"""The direct native `ProviderAdapter` boundary.

Everything provider-shaped lives below this line: auth, endpoint, wire schema, stream parsing,
native call binding, opaque replay capture and raw error mapping. Everything above it works in
canonical items and never branches on a provider name.

This protocol is for direct inference only. An external coding harness that owns its own
context, approvals and side effects is not a provider, and forcing it through these semantics to
reuse an interface would be claiming guarantees it cannot keep. That contract is
`ExternalAgentAdapter`, in its own module.
"""

from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cerebro.harness.errors import InferenceError
from cerebro.harness.events import InferenceEvent
from cerebro.harness.exceptions import ContinuationNotAdmissible
from cerebro.harness.ids import InferenceAttemptId
from cerebro.harness.model_profile import ModelProfile, ProviderConfig
from cerebro.harness.request import InferenceRequest

__all__ = [
    "AdapterCapabilities",
    "CancelToken",
    "PreparedProviderRequest",
    "ProviderAdapter",
    "assert_continuation_admissible",
]


class CancelToken:
    """A cooperative cancellation signal an adapter can poll or await.

    Deliberately not an `asyncio.Event` in the signature: cancellation is turn control state, and
    an adapter should be able to observe it without inheriting any particular loop plumbing.
    """

    def __init__(self) -> None:
        self._cancelled = False
        self.reason: str | None = None

    def cancel(self, reason: str | None = None) -> None:
        self._cancelled = True
        self.reason = reason

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def __bool__(self) -> bool:  # pragma: no cover - trivial
        return self._cancelled


class AdapterCapabilities(BaseModel):
    """What a dialect can express, before it is intersected with a `ModelProfile`."""

    model_config = {"frozen": True}

    dialect_id: str
    dialect_version: str
    supports_native_tool_calls: bool
    supported_tool_input_forms: list[str] = Field(default_factory=lambda: ["json"])
    supports_developer_role: bool = False
    supports_reasoning_summary: bool = False
    emits_opaque_replay_items: bool = False
    emits_sensitive_replay_material: bool = False
    supports_stateless_lossless_replay: bool = True


class PreparedProviderRequest(BaseModel):
    """A canonical request rendered into one dialect's wire form.

    Bound to the attempt that will dispatch it. An unbound prepared request could be sent twice
    under two identities, which is the one thing the attempt barrier exists to prevent.
    """

    model_config = {"frozen": True}

    attempt_id: InferenceAttemptId
    provider_id: str
    dialect_id: str
    dialect_version: str
    endpoint: str
    payload: dict[str, Any]
    request_semantic_hash: str
    # Provider wire tool name -> canonical ToolKey text, so a streamed call can be resolved back
    # to an executable identity without guessing from the name.
    wire_tool_names: dict[str, str] = Field(default_factory=dict)
    # Provider-native call id -> canonical CerebroCallId text for calls already in history.
    replayed_call_refs: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class ProviderAdapter(Protocol):
    """Direct native provider inference."""

    provider_id: str
    dialect_id: str
    dialect_version: str

    def resolve_capabilities(self, profile: ModelProfile) -> AdapterCapabilities:
        """What this dialect can express for this model."""
        ...

    def prepare(
        self,
        request: InferenceRequest,
        config: ProviderConfig,
        *,
        attempt_id: InferenceAttemptId,
    ) -> PreparedProviderRequest:
        """Render a canonical request into the dialect's wire form.

        Raises `UnsupportedDialectFeature` rather than dropping anything it cannot express.
        """
        ...

    def stream(
        self, prepared: PreparedProviderRequest, cancel_token: CancelToken
    ) -> AsyncIterator[InferenceEvent]:
        """Dispatch and yield canonical events. Called only after the dispatch barrier commits."""
        ...

    def classify_error(self, native_error: BaseException) -> InferenceError:
        """Map a native failure onto the canonical taxonomy."""
        ...

    async def close(self) -> None:
        ...


def assert_continuation_admissible(
    capabilities: AdapterCapabilities, profile: ModelProfile
) -> None:
    """AR-11 admission check, run before a provider/model pair is used.

    Phase 1 admits a combination only when every datum required for correct continuation can be
    represented losslessly in durable ordered items, refs and opaque replay material. If it
    cannot, generic harness code does not invent a replay strategy — the pair is refused here,
    where the refusal is cheap.
    """
    if profile.requires_opaque_replay and not capabilities.emits_opaque_replay_items:
        raise ContinuationNotAdmissible(
            f"model profile {profile.model_id!r} requires opaque replay material for "
            f"correctness, but dialect {capabilities.dialect_id!r} cannot emit or replay it"
        )
    if not profile.stateless_lossless_replay and not capabilities.emits_opaque_replay_items:
        raise ContinuationNotAdmissible(
            f"model profile {profile.model_id!r} is not stateless-lossless and dialect "
            f"{capabilities.dialect_id!r} carries no durable continuation state; the next "
            f"request could not be reconstructed after a restart"
        )
    if profile.tool_calling_mode == "native" and not capabilities.supports_native_tool_calls:
        raise ContinuationNotAdmissible(
            f"model profile {profile.model_id!r} declares native tool calling, which dialect "
            f"{capabilities.dialect_id!r} does not support"
        )
