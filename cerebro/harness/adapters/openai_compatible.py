"""The OpenAI-compatible / LM Studio `ProviderAdapter`.

This is the compatibility edge for the path Cerebro runs today. It reuses
`OpenAICompatibleProvider` purely as transport — one HTTP client, one SSE parser, one set of
error strings — and does all of the canonical work itself: it builds the wire payload from
ordered `InferenceItem`s rather than from collaboration `Message` rows, and it turns the stream
back into canonical events with finalized items.

Two properties are worth stating plainly because the rest of the design leans on them:

- a provider-native `tool_call_id` becomes a `ProviderCallRef`. It never becomes a
  `CerebroCallId`. Cerebro mints its own call identity, and the two travel together;
- this dialect emits no `ProviderOpaqueItem` at all, and therefore no `hidden_reasoning`,
  `signature_or_encrypted_reasoning` or `secret_like` replay material (AR-12). Chat completions
  requires nothing to be echoed back except the tool call ids, which are ordinary
  `ProviderCallRef`s. Streamed `reasoning`/`reasoning_content` is a summary; it is never replay
  state and is never persisted as opaque material by this adapter.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from cerebro.harness.adapters.openai_dialect import (
    DIALECT_ID,
    DIALECT_VERSION,
    OpenAIDialectOptions,
    to_wire_messages,
    to_wire_tools,
    tool_key_for_wire_name,
    wire_name_for_tool_key,
)
from cerebro.harness.content import Provenance, TextPart
from cerebro.harness.errors import InferenceError
from cerebro.harness.events import (
    AssistantTextDelta,
    InferenceCompleted,
    InferenceEvent,
    InferenceStarted,
    OutputItemCompleted,
    OutputItemStarted,
    ProviderMetadata,
    ReasoningSummaryDelta,
    ToolCallInputDelta,
    UsageUpdate,
)
from cerebro.harness.exceptions import UnsupportedDialectFeature
from cerebro.harness.ids import CerebroCallId, InferenceAttemptId, InferenceItemId
from cerebro.harness.items import MessageItem, ReasoningSummaryItem, ToolCallItem
from cerebro.harness.model_profile import ModelProfile, ProviderConfig
from cerebro.harness.provider_adapter import (
    AdapterCapabilities,
    CancelToken,
    PreparedProviderRequest,
)
from cerebro.harness.provider_ref import ProviderCallRef
from cerebro.harness.request import InferenceRequest, request_semantic_hash
from cerebro.harness.tooling import JsonToolInput, TextToolInput
from cerebro.models import Done, ReasoningDelta, TextDelta, ToolCallDelta, Usage
from cerebro.providers.openai_compatible import ProviderError, ProviderUnavailable

__all__ = ["OpenAICompatibleAdapter"]

# finish_reason -> canonical completion status. `tool_calls` wins over `stop` whenever calls were
# finalized, because a server that reports `stop` alongside tool calls has not ended the turn.
_FINISH_REASONS: dict[str, str] = {
    "stop": "end_turn",
    "tool_calls": "tool_calls_pending",
    "function_call": "tool_calls_pending",
    "length": "max_output_reached",
    "content_filter": "content_filtered_or_refused",
}

_STATUS_KINDS: dict[int, str] = {
    400: "invalid_request",
    401: "authentication",
    402: "quota_or_billing",
    403: "permission_denied",
    404: "unsupported",
    408: "transient_transport",
    409: "invalid_request",
    413: "request_too_large",
    422: "invalid_request",
    429: "rate_limited",
    500: "provider_internal",
    502: "provider_overloaded",
    503: "provider_overloaded",
    504: "provider_overloaded",
}

_RETRYABLE_KINDS = frozenset(
    {"transient_transport", "rate_limited", "provider_overloaded", "provider_internal"}
)


class OpenAICompatibleAdapter:
    """Canonical `ProviderAdapter` for OpenAI-compatible chat completions (incl. LM Studio)."""

    dialect_id: str = DIALECT_ID
    dialect_version: str = DIALECT_VERSION

    #: AR-12 declaration. Read by tests and by any future storage-policy gate.
    emits_sensitive_replay_material: bool = False

    def __init__(
        self,
        transport: Any,
        *,
        provider_id: str | None = None,
        options: OpenAIDialectOptions | None = None,
    ) -> None:
        """`transport` is an `OpenAICompatibleProvider` (or anything with `stream_payload`)."""
        self._transport = transport
        self.provider_id = provider_id or getattr(transport, "name", "openai_compatible")
        self.options = options or OpenAIDialectOptions()

    # -- capabilities ---------------------------------------------------------------

    def resolve_capabilities(self, profile: ModelProfile) -> AdapterCapabilities:
        return AdapterCapabilities(
            dialect_id=self.dialect_id,
            dialect_version=self.dialect_version,
            supports_native_tool_calls=True,
            supported_tool_input_forms=["json", "text"],
            supports_developer_role=self.options.supports_developer_role,
            supports_reasoning_summary=profile.reasoning_summary_support != "none",
            emits_opaque_replay_items=False,
            emits_sensitive_replay_material=self.emits_sensitive_replay_material,
            supports_stateless_lossless_replay=True,
        )

    # -- prepare --------------------------------------------------------------------

    def prepare(
        self,
        request: InferenceRequest,
        config: ProviderConfig,
        *,
        attempt_id: InferenceAttemptId,
    ) -> PreparedProviderRequest:
        """Render a canonical request into a chat-completions payload.

        `attempt_id` is keyword-only and required: the attempt identity exists before dispatch,
        and a prepared request that is not bound to one could be sent twice under two identities.
        """
        if config.dialect_id != self.dialect_id:
            raise UnsupportedDialectFeature(
                f"provider config declares dialect {config.dialect_id!r}; this adapter speaks "
                f"{self.dialect_id!r}"
            )

        model = request.provider_options.get("model")
        if not model:
            raise UnsupportedDialectFeature(
                "chat completions requires an explicit model; provider_options['model'] is unset"
            )

        messages = to_wire_messages(
            request.instructions, request.history, options=self.options
        )

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": request.output_policy.temperature,
        }
        if request.output_policy.max_output_tokens:
            payload["max_tokens"] = request.output_policy.max_output_tokens
        if request.output_policy.stop:
            payload["stop"] = request.output_policy.stop

        wire_tool_names: dict[str, str] = {}
        if request.tools:
            payload["tools"] = to_wire_tools(request.tools)
            for tool in request.tools:
                wire_tool_names[wire_name_for_tool_key(tool.key)] = tool.key.canonical()
            if request.tool_policy.choice != "auto":
                payload["tool_choice"] = request.tool_policy.choice

        if request.tool_policy.allow_parallel_calls:
            # Phase 1 executes client tools sequentially. Advertising parallel calls would invite
            # a batch the runtime is not allowed to run in parallel.
            raise UnsupportedDialectFeature(
                "parallel client tool calls are not supported in Phase 1"
            )

        for key, value in request.provider_options.items():
            if key == "model":
                continue
            payload[key] = value

        replayed = {
            str(item.provider_ref.native_call_id): str(item.call_id)
            for item in request.history
            if item.item_type == "tool_call"
            and item.provider_ref is not None
            and item.provider_ref.native_call_id
        }

        return PreparedProviderRequest(
            attempt_id=attempt_id,
            provider_id=self.provider_id,
            dialect_id=self.dialect_id,
            dialect_version=self.dialect_version,
            endpoint=config.endpoint,
            payload=payload,
            request_semantic_hash=request_semantic_hash(request),
            wire_tool_names=wire_tool_names,
            replayed_call_refs=replayed,
        )

    # -- stream ---------------------------------------------------------------------

    async def stream(
        self,
        prepared: PreparedProviderRequest,
        cancel_token: CancelToken | None = None,
        *,
        emit_reasoning_summary: bool = False,
    ) -> AsyncIterator[InferenceEvent]:
        """Dispatch and translate the stream into canonical events.

        Deltas are published as they arrive and accumulated separately. Nothing becomes an item
        until the stream ends, because a delta is progress and only a finalized item is
        authority.
        """
        attempt_id = prepared.attempt_id
        yield InferenceStarted(attempt_id=attempt_id)

        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        calls: dict[str, dict[str, str]] = {}
        call_order: list[str] = []
        finish_reason = "stop"
        started_text = False

        async for delta in self._transport.stream_payload(prepared.payload):
            if cancel_token is not None and cancel_token.cancelled:
                break

            if isinstance(delta, TextDelta):
                if not started_text:
                    started_text = True
                    yield OutputItemStarted(
                        attempt_id=attempt_id, item_index=0, item_type="message"
                    )
                text_parts.append(delta.text)
                yield AssistantTextDelta(attempt_id=attempt_id, text=delta.text)

            elif isinstance(delta, ReasoningDelta):
                reasoning_parts.append(delta.text)
                yield ReasoningSummaryDelta(
                    attempt_id=attempt_id, summary_fragment=delta.text
                )

            elif isinstance(delta, ToolCallDelta):
                slot = calls.get(delta.id)
                if slot is None:
                    slot = {"name": delta.name or "", "args": ""}
                    calls[delta.id] = slot
                    call_order.append(delta.id)
                if delta.name:
                    slot["name"] = delta.name
                slot["args"] += delta.args_fragment
                yield ToolCallInputDelta(
                    attempt_id=attempt_id,
                    call_index=call_order.index(delta.id),
                    provider_native_call_id=delta.id,
                    tool_wire_name=slot["name"] or None,
                    arguments_fragment=delta.args_fragment,
                )

            elif isinstance(delta, Usage):
                yield UsageUpdate(
                    attempt_id=attempt_id,
                    input_tokens=delta.input,
                    output_tokens=delta.output,
                )

            elif isinstance(delta, Done):
                finish_reason = delta.reason

        text = "".join(text_parts)
        if text:
            yield OutputItemCompleted(
                attempt_id=attempt_id,
                item=MessageItem(
                    item_id=InferenceItemId.generate(),
                    origin="provider_attempt",
                    producing_attempt_id=attempt_id,
                    role="assistant",
                    content=[TextPart(text=text)],
                    provenance=Provenance(
                        source_kind="provider_attempt", source_id=self.provider_id
                    ),
                ),
            )

        if reasoning_parts and emit_reasoning_summary:
            yield OutputItemCompleted(
                attempt_id=attempt_id,
                item=ReasoningSummaryItem(
                    item_id=InferenceItemId.generate(),
                    origin="provider_attempt",
                    producing_attempt_id=attempt_id,
                    content=[TextPart(text="".join(reasoning_parts))],
                    provenance=Provenance(
                        source_kind="provider_reasoning_summary", source_id=self.provider_id
                    ),
                ),
            )

        for native_id in call_order:
            slot = calls[native_id]
            yield OutputItemCompleted(
                attempt_id=attempt_id,
                item=self._finalize_call(prepared, attempt_id, native_id, slot),
            )

        if calls and finish_reason not in ("tool_calls", "function_call"):
            # A server that finalized tool calls has not ended the turn, whatever it called the
            # finish reason. Trusting `stop` here would drop the calls on the floor.
            finish_reason = "tool_calls"

        yield ProviderMetadata(
            attempt_id=attempt_id, metadata={"finish_reason": finish_reason}
        )
        yield InferenceCompleted(
            attempt_id=attempt_id,
            status=_FINISH_REASONS.get(finish_reason, "incomplete"),  # type: ignore[arg-type]
        )

    def _finalize_call(
        self,
        prepared: PreparedProviderRequest,
        attempt_id: InferenceAttemptId,
        native_id: str,
        slot: dict[str, str],
    ) -> ToolCallItem:
        """Turn accumulated fragments into one finalized canonical call.

        The provider's id goes into a `ProviderCallRef`; Cerebro mints a fresh `CerebroCallId`.
        `replay_required` is true because chat completions rejects a tool result whose
        `tool_call_id` it did not issue, so losing that ref after the tool ran is unrecoverable.
        """
        raw = slot["args"] or "{}"
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            # Kept verbatim rather than repaired. A weak local model emitting malformed JSON is
            # expected, and the truthful canonical record of that is the text it actually sent.
            tool_input: Any = TextToolInput(text=raw)
        else:
            tool_input = JsonToolInput(value=parsed)

        return ToolCallItem(
            item_id=InferenceItemId.generate(),
            origin="provider_attempt",
            producing_attempt_id=attempt_id,
            call_id=CerebroCallId.generate(),
            tool_key=tool_key_for_wire_name(slot["name"], prepared.wire_tool_names),
            input=tool_input,
            provider_ref=ProviderCallRef(
                provider_id=self.provider_id,
                native_call_id=native_id,
                replay_required=True,
            ),
        )

    # -- errors ---------------------------------------------------------------------

    def classify_error(self, native_error: BaseException) -> InferenceError:
        """Map a transport failure onto the canonical taxonomy.

        `transport_retryable` is set from the wire's own opinion and nothing more. Whether the
        semantic work may be repeated is `classify_recovery`'s decision, made with knowledge of
        what may already have escaped.
        """
        if isinstance(native_error, ProviderUnavailable):
            return InferenceError(
                kind="transient_transport",
                provider_message=str(native_error),
                transport_retryable=True,
            )
        if isinstance(native_error, ProviderError):
            status = getattr(native_error, "status_code", None)
            # No status means the stream died mid-flight (read timeout, truncated body):
            # transport trouble, not a decision the server made.
            kind = (
                _STATUS_KINDS.get(status, "provider_internal")
                if status is not None
                else "transient_transport"
            )
            return InferenceError(
                kind=kind,  # type: ignore[arg-type]
                provider_code=str(status) if status is not None else None,
                provider_message=str(native_error),
                transport_retryable=kind in _RETRYABLE_KINDS,
            )
        if isinstance(
            native_error, (httpx.ConnectError, httpx.ReadTimeout, httpx.TimeoutException)
        ):
            return InferenceError(
                kind="transient_transport",
                provider_message=str(native_error),
                transport_retryable=True,
            )
        if isinstance(native_error, httpx.HTTPStatusError):
            status = native_error.response.status_code
            kind = _STATUS_KINDS.get(status, "provider_internal")
            return InferenceError(
                kind=kind,  # type: ignore[arg-type]
                provider_code=str(status),
                provider_message=str(native_error),
                transport_retryable=kind in _RETRYABLE_KINDS,
            )
        return InferenceError(
            kind="fatal_internal",
            provider_message=repr(native_error),
            transport_retryable=False,
        )

    async def close(self) -> None:
        closer = getattr(self._transport, "aclose", None)
        if closer is not None:
            await closer()
