"""AR-12: opaque replay material stays out of generic logs, reprs and projections.

The rule is not "redact the sensitive ones". Generic code has no legitimate reason to read
adapter-owned bytes at all, so the payload is absent from every generic surface and the
sensitivity only changes how loudly that is said.
"""

import logging
import traceback

import pytest

from cerebro.harness import (
    InferenceAttemptId,
    InferenceItemId,
    ProviderOpaqueItem,
    ModelProfileId,
    ProviderConfigId,
    StepSnapshotId,
)
from cerebro.harness.adapters import OpenAICompatibleAdapter
from cerebro.harness.items import SENSITIVE_REPLAY_SENSITIVITIES
from cerebro.harness.serialization import dump_item, load_event, load_item, load_request
from tests.harness_fixtures import FakeTransport

SECRET = "eyJzaWduYXR1cmUiOiJ0b3Atc2VjcmV0LXNpZ25hdHVyZSJ9"


def _opaque(sensitivity: str = "signature_or_encrypted_reasoning") -> ProviderOpaqueItem:
    return ProviderOpaqueItem(
        item_id=InferenceItemId.generate(),
        origin="provider_attempt",
        producing_attempt_id=InferenceAttemptId.generate(),
        provider_id="future_provider",
        adapter_dialect="future.dialect",
        kind="thought_signature",
        exact_payload=SECRET,
        payload_encoding="base64",
        replay_requirement="required_for_correctness",
        retention_scope="conversation",
        sensitivity=sensitivity,  # type: ignore[arg-type]
    )


def test_repr_never_shows_the_payload():
    item = _opaque()
    assert SECRET not in repr(item)
    assert SECRET not in str(item)
    assert "redacted" in repr(item)


def test_repr_is_redacted_even_for_ordinary_material():
    """One mislabelled adapter should not be all that stands between a signature and a log."""
    assert SECRET not in repr(_opaque("ordinary"))


def test_the_log_projection_omits_the_payload_and_keeps_the_metadata():
    projection = _opaque().log_projection()
    assert projection["payload"] == "<redacted>"
    assert SECRET not in str(projection)
    assert projection["replay_requirement"] == "required_for_correctness"
    assert projection["retention_scope"] == "conversation"
    assert projection["sensitivity"] == "signature_or_encrypted_reasoning"
    assert projection["payload_bytes"] == len(SECRET)


def test_a_logged_item_does_not_leak_through_string_formatting(caplog):
    item = _opaque()
    with caplog.at_level(logging.INFO):
        logging.getLogger("cerebro.test").info("kept replay item %s", item)
    assert SECRET not in caplog.text


def test_sensitivity_classification_is_explicit():
    assert _opaque().is_sensitive
    assert not _opaque("ordinary").is_sensitive
    assert SENSITIVE_REPLAY_SENSITIVITIES == frozenset(
        {"hidden_reasoning", "signature_or_encrypted_reasoning", "secret_like"}
    )


def test_the_durable_form_still_carries_the_exact_payload():
    """Redaction is for projections. A redacted signature cannot continue a conversation."""
    assert dump_item(_opaque())["exact_payload"] == SECRET


def _invalid_opaque_payload():
    payload = dump_item(_opaque())
    payload["origin"] = "harness_local"
    payload["producing_attempt_id"] = None
    return payload


def _assert_validation_error_is_redacted(exc):
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    assert SECRET not in str(exc)
    assert SECRET not in repr(exc)
    assert SECRET not in formatted


def test_sensitive_payload_is_hidden_from_direct_union_and_nested_validation_errors(caplog):
    payload = _invalid_opaque_payload()
    request_payload = {
        "step_snapshot_id": str(StepSnapshotId.generate()),
        "provider_config_ref": str(ProviderConfigId.generate()),
        "model_profile_ref": str(ModelProfileId.generate()),
        "history": [payload],
    }
    event_payload = {
        "event_type": "output_item_completed",
        "attempt_id": str(InferenceAttemptId.generate()),
        "item": payload,
    }
    validations = [
        lambda: ProviderOpaqueItem(**payload),
        lambda: load_item(payload),
        lambda: load_request(request_payload),
        lambda: load_event(event_payload),
    ]

    with caplog.at_level(logging.ERROR):
        for validate in validations:
            with pytest.raises((ValueError, TypeError)) as excinfo:
                validate()
            _assert_validation_error_is_redacted(excinfo.value)
            logging.getLogger("cerebro.test").exception(
                "opaque validation failed", exc_info=excinfo.value
            )

    assert SECRET not in caplog.text


def test_the_current_adapter_declares_it_creates_no_sensitive_replay_material():
    """AR-12 gate: no sensitive replay data is created by this PR, so none is stored ungoverned."""
    adapter = OpenAICompatibleAdapter(FakeTransport([]))
    assert adapter.emits_sensitive_replay_material is False
