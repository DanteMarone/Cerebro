# Harness v1 Phase 1B review handoff

Issue: #217 — `Review: adversarial audit of Harness v1 Phase 1B durable store`

Status: **complete**

Verdict: **MERGEABLE AFTER FIXES**

## Exact reviewed inputs

- implementation: `implement/harness-v1-phase1b-durable-store@abd1d702741adb795f13024ba2e9f4bf38310ecb`
- base: `main@41100fca9a08e7c9209a4ad87d1fae8c1940beaf`
- clarified contract: `design/harness-v1-contract-clarifications@05fb8fa09c47598bbeed16c9be279f5dfe2a648b`
- failure audit: `research/harness-v1-failure-audit@ee7a8a37fc03d2538ee3ecc5007a48a79d8a4af4`
- seam inventory: `research/harness-v1-seam-inventory@3870a64baeb81e6d32b1ddd13bf0022db30961a0`

Root `AGENTS.md` and issue #217 were read before the implementation audit.

## Deliverables

Only the issue-required review documents were added under `docs/research/harness-v1-phase1b-review/`:

- `REVIEW.md`
- `FINDINGS.md`
- `TEST_GAPS.md`
- `HANDOFF.md`

No production code or tests were modified. No PR was opened or merged.

## Accepted findings

Six `MUST_FIX` findings were accepted; no `BLOCKER` was found:

1. **P1B-01** — abandoned-attempt supersession does not derive protected possibly-escaped calls from durable ToolExecution truth and does not require durable abandonment.
2. **P1B-02** — TurnRecoveryDriver is not failure-isolated; one malformed/missing reference or stale recovery CAS can abort later candidates.
3. **P1B-03** — `(agent_turn_id, attempt_generation)` makes attempt generation turn-global and blocks generation 1 on a later StepSnapshot.
4. **P1B-04** — snapshot/attempt/tool admission and dispatch lack terminal/current-projection gates, allowing post-terminal effect admission and step projection rewind; terminal finalization fields also need SQL immutability distinct from attention updates.
5. **P1B-05** — ToolExecution can bind to a ToolCallItem owned by another AgentTurn.
6. **P1B-06** — recovery/history/attention queries can filter on duplicated SQL state before canonical payload validation and silently hide divergence.

Each finding in `FINDINGS.md` contains the exact file/symbol, concrete failure sequence, violated invariant, smallest repair, deterministic regression test, and merge disposition.

## Covered checks

The review found the following implementation areas sound within Phase 1B scope:

- `run_in_writer()` transaction discipline and rollback;
- explicit AgentTurn/attempt/tool/history CAS;
- event/projection writes occurring in the same transaction;
- aggregate ToolExecution attention recomputation, including terminal indeterminate resolution;
- database-authoritative causal wake uniqueness and intentional recurrence encoding;
- minimal immutable StepSnapshot identity seam;
- additive migration/product-table separation;
- no RuntimeService/AgentRuntime/provider/tool-execution/finalization/native-provider/external-agent/multi-worker scope creep.

The aggregate multi-call attention and post-terminal reconciliation paths are still missing deterministic regression tests even though the implementation logic appears correct.

## Test assessment

The implementation handoff reports:

- focused suite: `149 passed`;
- `flake8 .`: clean;
- full suite: `610 passed, 3 skipped`;
- `git diff --check`: clean.

Those results were treated as evidence, not proof. The review inspected `tests/test_harness_store.py` and identified the missing adversarial sequences in `TEST_GAPS.md`.

The review branch itself is documentation-only, so lint/tests were not rerun; root `AGENTS.md` explicitly permits skipping them for documentation-only changes.

## Incremental review commit chain

- `8f80ee57dff973902215259969006b640f34303a` — start Phase 1B durable-store review
- `4b3f8c61b3e7bc6ecf8d2044f9da1190497404d0` — record Phase 1B review findings
- `a93e3a9f0b74fe160fdab232288133f36f782cf3` — document Phase 1B adversarial test gaps
- this handoff-finalization commit follows

A commit cannot contain its own SHA. The exact final review branch SHA is therefore recorded in the completion comment on issue #217.

## Repair-review boundary

A repair pass should stay inside Phase 1B schema/store/recovery semantics and the corresponding deterministic tests. None of these findings requires implementing the executable Phase 1C StepSnapshot/tool plan, provider/tool reducer execution, product finalization cutover, native providers, external-agent recovery, or multi-worker fencing.
