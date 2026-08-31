"""Immutable executable StepSnapshot and frozen ToolPlanSnapshot contracts (Phase 1C)."""

import json

import pytest

from cerebro import db
from cerebro.config import Settings
from cerebro.harness import (
    ModelProfileId,
    ProviderConfigId,
    StepSnapshot,
    StepSnapshotId,
    ToolGrantEvidence,
    ToolKey,
    project_tool_plan,
)
from cerebro.harness.exceptions import (
    HarnessStateError,
    StaleHarnessWrite,
    UnsupportedFormatVersion,
)
from cerebro.harness.serialization import (
    canonical_json,
    dump_step_snapshot,
    load_step_snapshot,
)
from cerebro.harness.store import HarnessStore, StepSnapshotIdentity
from tests.harness_phase1c import (
    NOW,
    FakeToolCatalog,
    build_snapshot,
    catalog_entry,
    mcp_key,
    running_turn,
    snapshotted_turn,
)


def catalog() -> FakeToolCatalog:
    return FakeToolCatalog([catalog_entry(mcp_key(), generation="g1")])


@pytest.mark.asyncio
async def test_executable_snapshot_round_trips_after_close_and_reopen(test_db: Settings):
    """The whole executable definition survives a restart, byte for byte."""
    store = HarnessStore()
    turn, snapshot, _ = await snapshotted_turn(store, catalog(), occurrence="snap-round-trip")
    await db.close()
    await db.connect(test_db.db_path)

    reopened = await store.get_step_snapshot(snapshot.snapshot_id)
    assert reopened == snapshot
    assert reopened.tool_plan.plan_hash() == snapshot.tool_plan.plan_hash()
    assert reopened.tool_plan.binding_for(mcp_key()) is not None
    assert reopened.tool_plan.key_for_wire_name("payments__charge") == mcp_key()
    reloaded_turn = await store.get_turn(turn.id)
    assert reloaded_turn.active_step_snapshot_id == snapshot.snapshot_id


@pytest.mark.asyncio
async def test_snapshot_cannot_be_rebuilt_from_newer_current_configuration(test_db: Settings):
    """A later provider, model, tool or policy version never substitutes into an old step."""
    store = HarnessStore()
    live = catalog()
    _, snapshot, _ = await snapshotted_turn(store, live, occurrence="snap-no-substitute")

    live.replace(mcp_key(), catalog_entry(mcp_key(), generation="g2"))
    live.revoke_grant(POLICY_AFTER := 99)
    await store.advance_security_revocation_epoch(at=NOW)

    reopened = await store.get_step_snapshot(snapshot.snapshot_id)
    assert reopened.tool_plan.policy_version != POLICY_AFTER
    assert str(reopened.tool_plan.bindings[0].binding_generation) == "tbg_g1"
    assert reopened.security_revocation_epoch == 0
    assert await store.security_revocation_epoch() == 1
    # The live projection genuinely moved on; the snapshot did not follow it.
    current = project_tool_plan(live, security_revocation_epoch=1)
    assert current.plan_hash() != reopened.tool_plan.plan_hash()


@pytest.mark.asyncio
async def test_snapshot_columns_cannot_disagree_with_the_immutable_envelope(test_db: Settings):
    """A hand-edited queryable column is two answers to one question, so it fails closed."""
    store = HarnessStore()
    _, snapshot, _ = await snapshotted_turn(store, catalog(), occurrence="snap-column-drift")

    async def _tx(conn):
        await conn.execute(
            "UPDATE step_snapshots SET provider_id='someone_else' WHERE snapshot_id=?",
            (str(snapshot.snapshot_id),),
        )

    with pytest.raises(Exception) as excinfo:
        await db.run_in_writer(_tx)
    assert "immutable" in str(excinfo.value)


@pytest.mark.asyncio
async def test_snapshot_envelope_drift_fails_closed(test_db: Settings):
    """Inserting a snapshot whose envelope disagrees with its columns is unreadable."""
    store = HarnessStore()
    turn = await running_turn(store, occurrence="snap-envelope-drift")
    snapshot = build_snapshot(
        turn,
        catalog(),
        security_revocation_epoch=0,
        history_version=0,
        replay_version=0,
    )
    columns = snapshot.queryable_columns()
    columns["token_budget"] = 1
    names = ",".join(columns)
    placeholders = ",".join("?" for _ in columns)

    async def _tx(conn):
        await conn.execute(
            f"INSERT INTO step_snapshots (snapshot_id,format_version,agent_turn_id,step_index,"
            f"turn_version_at_creation,storage_envelope_json,created_at,{names}) "
            f"VALUES (?,?,?,?,?,?,?,{placeholders})",
            (
                str(snapshot.snapshot_id),
                snapshot.format_version,
                str(turn.id),
                0,
                turn.state_version,
                canonical_json(dump_step_snapshot(snapshot)),
                NOW,
                *columns.values(),
            ),
        )

    await db.run_in_writer(_tx)
    with pytest.raises(HarnessStateError, match="token_budget disagrees"):
        await store.get_step_snapshot(snapshot.snapshot_id)


@pytest.mark.asyncio
async def test_unknown_snapshot_and_tool_plan_versions_fail_closed(test_db: Settings):
    """An unrecognised snapshot or nested plan version is refused, never parsed optimistically."""
    store = HarnessStore()
    turn = await running_turn(store, occurrence="snap-unknown-version")
    snapshot = build_snapshot(
        turn, catalog(), security_revocation_epoch=0, history_version=0, replay_version=0
    )
    payload = dump_step_snapshot(snapshot)

    future = dict(payload, format_version=99)
    with pytest.raises(UnsupportedFormatVersion, match="StepSnapshot format_version 99"):
        load_step_snapshot(future)

    plan = dict(payload["tool_plan"], format_version=42)
    with pytest.raises(UnsupportedFormatVersion, match="ToolPlanSnapshot format_version 42"):
        load_step_snapshot(dict(payload, tool_plan=plan))

    # An identity-only Phase 1B snapshot is not an executable one and can never pretend to be.
    identity = StepSnapshotIdentity(
        snapshot_id=StepSnapshotId.generate(),
        agent_turn_id=turn.id,
        step_index=0,
        turn_version_at_creation=turn.state_version,
        created_at=NOW,
    )
    await store.commit_snapshot_identity(identity, expected_turn_version=turn.state_version)
    with pytest.raises(UnsupportedFormatVersion, match="StepSnapshot format_version 1"):
        await store.get_step_snapshot(identity.snapshot_id)


@pytest.mark.asyncio
async def test_snapshot_never_freezes_credential_material(test_db: Settings):
    """A snapshot outlives every credential rotation, so it may only hold references."""
    store = HarnessStore()
    turn = await running_turn(store, occurrence="snap-secret")
    with pytest.raises(ValueError, match="must not carry credential material"):
        build_snapshot(
            turn,
            catalog(),
            security_revocation_epoch=0,
            history_version=0,
            replay_version=0,
            provider_semantic_options={"api_key": "sk-live-1234"},
        )
    ok = build_snapshot(
        turn, catalog(), security_revocation_epoch=0, history_version=0, replay_version=0
    )
    assert "credential_reference" not in json.dumps(dump_step_snapshot(ok))
    assert str(ok.provider_config_id).startswith("pcfg_")


@pytest.mark.asyncio
async def test_snapshot_must_freeze_the_current_revocation_epoch(test_db: Settings):
    """A snapshot frozen against a stale epoch would be born already unenforceable."""
    store = HarnessStore()
    turn = await running_turn(store, occurrence="snap-stale-epoch")
    await store.advance_security_revocation_epoch(at=NOW)
    snapshot = build_snapshot(
        turn, catalog(), security_revocation_epoch=0, history_version=0, replay_version=0
    )
    with pytest.raises(HarnessStateError, match="current security revocation epoch"):
        await store.commit_step_snapshot(snapshot, expected_turn_version=turn.state_version)


@pytest.mark.asyncio
async def test_snapshot_commit_is_compare_and_set_on_the_turn(test_db: Settings):
    """A snapshot committed against a stale turn version is refused, not merged."""
    store = HarnessStore()
    turn = await running_turn(store, occurrence="snap-cas")
    snapshot = build_snapshot(
        turn, catalog(), security_revocation_epoch=0, history_version=0, replay_version=0
    )
    await store.commit_step_snapshot(snapshot, expected_turn_version=turn.state_version)
    second = build_snapshot(
        turn,
        catalog(),
        security_revocation_epoch=0,
        history_version=0,
        replay_version=0,
        step_index=1,
    )
    with pytest.raises(StaleHarnessWrite):
        await store.commit_step_snapshot(second, expected_turn_version=turn.state_version)


def test_tool_plan_refuses_an_unbound_definition_or_unmapped_wire_name():
    """A plan is executable identity, not a menu; every offered tool must be runnable."""
    entry = catalog_entry(mcp_key(), generation="g1")
    plan = project_tool_plan(FakeToolCatalog([entry]), security_revocation_epoch=0)
    with pytest.raises(ValueError, match="exactly one executable ToolBinding"):
        plan.model_copy(update={"bindings": ()}).model_validate(
            dict(plan.model_dump(mode="python"), bindings=())
        )
    with pytest.raises(ValueError, match="wire-name map must cover"):
        type(plan).model_validate(
            dict(plan.model_dump(mode="python"), provider_wire_name_to_tool_key={})
        )


def test_tool_plan_refuses_grant_evidence_at_the_wrong_policy_version():
    """Evidence frozen at a different policy version is not evidence for this step."""
    entry = catalog_entry(mcp_key(), generation="g1")
    plan = project_tool_plan(FakeToolCatalog([entry]), security_revocation_epoch=0)
    bad = dict(plan.model_dump(mode="python"))
    bad["grant_evidence"] = {
        mcp_key().canonical(): ToolGrantEvidence(
            grant_id="grant", policy_version=999, trust_tier="standard"
        )
    }
    with pytest.raises(ValueError, match="freezes policy_version"):
        type(plan).model_validate(bad)


def test_snapshot_and_plan_must_agree_on_policy_and_revocation():
    """Two disagreeing copies of the same fact are worse than one, so this is rejected."""
    plan = project_tool_plan(
        FakeToolCatalog([catalog_entry(mcp_key(), generation="g1")]),
        security_revocation_epoch=0,
    )
    base = {
        "snapshot_id": StepSnapshotId.generate(),
        "agent_turn_id": "atn_" + "a" * 8,
        "step_index": 0,
        "turn_version_at_creation": 0,
        "provider_config_id": ProviderConfigId.generate(),
        "provider_id": "lmstudio",
        "adapter_dialect": "openai_chat_completions",
        "adapter_dialect_version": "1",
        "model_profile_id": ModelProfileId.generate(),
        "model_profile_version": 1,
        "inference_history_version": 0,
        "provider_replay_version": 0,
        "context_projection_version": 1,
        "token_budget": 100,
        "tool_plan": plan,
        "permission_policy_version": plan.policy_version + 1,
        "security_revocation_epoch": 0,
        "workspace_ref": "w",
        "cwd": "c",
        "environment_ref": "e",
        "environment_version": 1,
        "completion_policy_version": 1,
        "created_at": NOW,
    }
    with pytest.raises(ValueError, match="permission_policy_version"):
        StepSnapshot(**base)
    base["permission_policy_version"] = plan.policy_version
    base["security_revocation_epoch"] = 5
    with pytest.raises(ValueError, match="security_revocation_epoch"):
        StepSnapshot(**base)


def test_tool_key_identity_is_not_the_provider_wire_name():
    """Two dialects may spell one binding differently; only the key is identity."""
    key = ToolKey(source_type="mcp", source_id="payments", namespace="payments", name="charge")
    plan = project_tool_plan(
        FakeToolCatalog(
            [catalog_entry(key, generation="g1", wire_name="payments__charge")]
        ),
        security_revocation_epoch=0,
    )
    assert plan.key_for_wire_name("payments__charge") == key
    assert plan.key_for_wire_name("payments:charge") is None
    assert plan.key_for_wire_name("charge") is None
