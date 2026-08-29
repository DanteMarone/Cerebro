"""Provider error taxonomy and semantic recovery disposition.

Two separate questions, deliberately not collapsed into one flag:

1. *May the transport retry?* That is `InferenceError.transport_retryable`, and it is the
   provider's opinion about its own wire.
2. *May Cerebro repeat the semantic work?* That is `SemanticRecoveryDisposition`, and it is the
   harness's decision, made with knowledge of what has already escaped.

A 429 is retryable transport and says nothing about whether a tool call that may already have
run can be issued again. Collapsing the two is how a retry becomes a duplicate side effect.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

__all__ = [
    "InferenceError",
    "InferenceErrorKind",
    "ProviderRecoveryAction",
    "SemanticRecoveryDisposition",
    "classify_recovery",
    "provider_action_for",
]

InferenceErrorKind = Literal[
    "transient_transport",
    "rate_limited",
    "quota_or_billing",
    "authentication",
    "permission_denied",
    "invalid_request",
    "request_too_large",
    "context_exhausted",
    "provider_overloaded",
    "provider_internal",
    "cancelled",
    "policy_denied",
    "unsupported",
    "fatal_internal",
]

SemanticRecoveryDisposition = Literal[
    "same_attempt_transport_retry",
    "fresh_attempt_from_current_checkpoint",
    "compact_then_fresh_attempt",
    "refresh_auth_then_fresh_attempt",
    "reconcile_or_suspend",
    "not_replay_safe",
]

ProviderRecoveryAction = Literal[
    "retry_same_attempt",
    "start_fresh_attempt",
    "compact_then_fresh_attempt",
    "refresh_auth_then_fresh_attempt",
    "suspend",
    "fail",
]


class InferenceError(BaseModel):
    """A provider failure, classified in Cerebro's terms.

    `transport_retryable` is recorded because the adapter knows it, not because the harness may
    act on it alone.
    """

    model_config = {"frozen": True}

    kind: InferenceErrorKind
    provider_code: str | None = None
    provider_message: str | None = None
    request_id: str | None = None
    retry_after: float | None = None
    transport_retryable: bool = False
    provider_retry_hint: str | None = None


# The kind -> disposition table for an attempt that left nothing uncertain behind it.
_BASE_DISPOSITION: dict[str, SemanticRecoveryDisposition] = {
    "transient_transport": "fresh_attempt_from_current_checkpoint",
    "rate_limited": "fresh_attempt_from_current_checkpoint",
    "provider_overloaded": "fresh_attempt_from_current_checkpoint",
    "provider_internal": "fresh_attempt_from_current_checkpoint",
    "authentication": "refresh_auth_then_fresh_attempt",
    "context_exhausted": "compact_then_fresh_attempt",
    "request_too_large": "compact_then_fresh_attempt",
    "quota_or_billing": "not_replay_safe",
    "permission_denied": "not_replay_safe",
    "policy_denied": "not_replay_safe",
    "invalid_request": "not_replay_safe",
    "unsupported": "not_replay_safe",
    "fatal_internal": "not_replay_safe",
    "cancelled": "not_replay_safe",
}


def classify_recovery(
    error: InferenceError,
    *,
    dispatch_may_have_escaped: bool = False,
    has_unresolved_effect: bool = False,
    stream_already_started: bool = False,
) -> SemanticRecoveryDisposition:
    """Decide whether the semantic work may be repeated after `error`.

    `transport_retryable` never by itself produces a fresh semantic attempt, and a fresh attempt
    is never implied by transport retryability: the two come from different arguments here on
    purpose.

    An unresolved effect that may already have escaped outranks every error kind. Nothing about
    a 500 makes it safe to re-run a mutation whose outcome is unknown.
    """
    if has_unresolved_effect:
        return "reconcile_or_suspend"

    base = _BASE_DISPOSITION.get(error.kind, "not_replay_safe")

    if base == "not_replay_safe":
        return base

    # Transport retry is only on the table while the attempt is still the same attempt: nothing
    # has escaped, and no partial finalized output exists to be replayed twice.
    if (
        error.transport_retryable
        and not dispatch_may_have_escaped
        and not stream_already_started
    ):
        return "same_attempt_transport_retry"

    return base


def provider_action_for(disposition: SemanticRecoveryDisposition) -> ProviderRecoveryAction:
    """Turn a disposition into the concrete Phase 1 provider action.

    AR-11: Phase 1 has no generic provider-side reconciliation, so `reconcile_or_suspend`
    degenerates to a durable suspend rather than to a guess. `compact_then_fresh_attempt` stays
    representable even though compaction itself is not implemented in Phase 1; an adapter that
    reaches it must suspend rather than silently drop history.
    """
    if disposition == "same_attempt_transport_retry":
        return "retry_same_attempt"
    if disposition == "fresh_attempt_from_current_checkpoint":
        return "start_fresh_attempt"
    if disposition == "compact_then_fresh_attempt":
        return "compact_then_fresh_attempt"
    if disposition == "refresh_auth_then_fresh_attempt":
        return "refresh_auth_then_fresh_attempt"
    if disposition == "reconcile_or_suspend":
        return "suspend"
    return "fail"
