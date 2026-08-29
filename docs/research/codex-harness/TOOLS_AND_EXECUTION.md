# Codex Tools and Execution Architecture

**Status:** Initial confirmed map; individual tool runtimes/sandbox backends still need deeper inspection.

**Pinned upstream:** `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

No Codex implementation code is copied into Cerebro by this document. Findings are currently **conceptual inspiration only**.

## Main conclusion

Codex's tool layer is not just `name + JSON schema + function`. It separates:

- the complete runtime registry;
- effective exposure policy;
- the exact model-visible tool surface for one sampling request;
- tool-call parsing/routing;
- concurrency policy;
- permission/sandbox resolution;
- pre/post hooks;
- lifecycle/telemetry;
- normalized model-visible terminal results.

That separation lets Codex expose a smaller or differently shaped tool set to different models/modes without losing the executable runtime catalog behind it.

## 1. Tool planning happens per sampling step

`build_tool_router(...)` in `codex-rs/core/src/tools/spec_plan.rs` builds a new finalized `ToolRouter` from the current:

- Session/TurnContext;
- ModelInfo and model-owned messages;
- environment snapshot;
- exact MCP binding;
- apps/plugin/tool-search policy;
- dynamic and extension tools;
- session source and feature flags.

Core sources, MCP sources, extension tools, dynamic tools and hosted provider tools are assembled before exposure/finalization.

The resulting router is stored in the request-scoped `StepContext`. `build_prompt(...)` advertises only `ToolRouter.model_visible_specs()` from that exact router.

**Cerebro implication:** tool availability should be planned for each inference from a canonical runtime catalog plus model/agent/environment policy. Do not expose a static global MCP catalog to every agent on every call.

Upstream:
- `codex-rs/core/src/tools/spec_plan.rs`
- `codex-rs/core/src/session/step_context.rs`
- `codex-rs/core/src/session/turn.rs`

## 2. Registry and model-visible exposure are different things

`ToolRegistry` stores executable runtimes and effective exposure. `ToolRouter` stores both that registry and a separately finalized list of model-visible specs.

This makes several behaviors possible:

- a registered tool can be hidden from the model;
- tools can be directly exposed, available only through Code Mode, or deferred behind tool search;
- namespace-level exposure can vary by server/config/model mode;
- collisions can be detected and resolved without blindly allowing an external tool to replace a core tool;
- reserved shell-like names from external tool sources are rejected;
- a model's actual ability to manage child agents can be calculated from whether all required child-management tools survived final exposure.

**Cerebro implication:** distinguish `ToolRuntime` from `ToolExposure`. An MCP tool being connected should not automatically mean every model can see or invoke it.

Upstream:
- `codex-rs/core/src/tools/registry.rs`
- `codex-rs/core/src/tools/router.rs`
- `codex-rs/core/src/tools/spec_plan.rs`

## 3. Tool exposure is model/provider/mode aware

Tool planning checks both provider capabilities and model metadata. Confirmed examples include:

- namespace-tool support;
- hosted versus standalone web search;
- model shell support;
- apply-patch support/mode;
- input modality requirements;
- Code Mode/direct/deferred exposure;
- multi-agent backend/version/depth;
- feature flags and session source;
- MCP server-level omit/exposure policy.

Some tools can therefore remain executable in the runtime but be represented differently or hidden for a particular model request.

**Cerebro implication:** the model capability profile proposed in `CONTEXT_AND_PROMPTS.md` should participate directly in tool planning.

Upstream:
- `codex-rs/core/src/tools/spec_plan.rs`
- `codex-rs/protocol/src/openai_models.rs`

## 4. ToolRouter binds advertised specs to executable runtimes

`ToolRouter` represents one finalized plan with:

- model-visible specs;
- executable registry;
- tool mode;
- Code Mode name mappings;
- namespace metadata;
- child-management capability.

Completed model output is converted into a typed `ToolCall` with a canonical `ToolName`, call ID and typed payload. Function, custom/freeform and client-executed tool-search calls are normalized here.

The invocation dispatched into the registry retains the same `StepContext` that advertised the tool.

**Cerebro implication:** provider adapters should normalize provider-specific tool-call wire formats into a Cerebro canonical `ToolCall`, then dispatch through a request-scoped router rather than calling MCP/providers directly.

Upstream:
- `codex-rs/core/src/tools/router.rs`

## 5. A tool runtime has lifecycle behavior beyond its handler

`CoreToolRuntime` extends the execution contract with optional behavior for:

- stable/immutable specs;
- readiness waiting;
- MCP-server ownership;
- payload-kind matching;
- telemetry tags;
- pre/post tool hook payloads;
- input rewriting by hooks;
- streamed argument-diff consumers;
- post-result observation.

This means hooks, telemetry and incremental UI behavior are part of the tool runtime abstraction rather than manually reimplemented by every caller.

**Cerebro implication:** a useful tool interface probably needs metadata/lifecycle hooks in addition to `execute(args)`. MCP remains the external interoperability layer, but Cerebro-native runtime wrappers can own policy and observability around MCP calls.

Upstream:
- `codex-rs/core/src/tools/registry.rs`

## 6. Tool calls have exactly one terminal model-visible outcome

The normal path is:

```text
model emits tool call
  > persist call item
  > dispatch against request-scoped router
  > success | ordinary failure | cancellation/abort
  > create terminal tool result with same call identity
  > persist result
  > next model sample sees result
```

Ordinary nonfatal handler failures are converted into tool outputs rather than crashing the turn. Parse/validation failures that the model can fix are also returned as model-visible feedback. Fatal internal failures remain fatal.

Cancellation aborts the underlying task when safe, emits a lifecycle notification, and returns an aborted result instead of dropping the call from history.

**Cerebro implication:** every accepted tool call should transition to one durable terminal state: `succeeded`, `failed`, `denied`, `aborted`, or equivalent. Provider/tool exceptions should not leave unresolved phantom calls in conversation state.

Upstream:
- `codex-rs/core/src/stream_events_utils.rs`
- `codex-rs/core/src/tools/parallel.rs`

## 7. Parallel tool calling is two separate capabilities

Codex tells the model that parallel tool calls are supported at the prompt/request level, but each actual runtime separately declares whether its calls may execute in parallel.

`ToolCallRuntime` uses a shared read/write gate:

- parallel-safe tools acquire shared/read admission;
- non-parallel-safe tools acquire exclusive/write admission.

For example, the current `exec_command` runtime explicitly supports parallel tool calls. Other tools can remain exclusive.

**Cerebro implication:** represent at least:

- model/provider can emit parallel calls;
- tool runtime is safe to execute concurrently;
- shared resource/lease constraints can further serialize calls.

Cerebro's existing database-backed leases can become an additional concurrency layer rather than replacing tool-level concurrency metadata.

Upstream:
- `codex-rs/core/src/tools/parallel.rs`
- `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs`

## 8. `apply_patch` is a verified editing primitive

The inspected `ApplyPatchHandler` confirms that `apply_patch` is not simply shelling out with arbitrary model text.

The runtime:

1. accepts a dedicated freeform patch payload;
2. parses the patch with the Codex apply-patch parser;
3. resolves the exact selected environment from the request's StepContext;
4. verifies the parsed patch against that environment's filesystem before execution;
5. computes affected paths and effective write permissions;
6. applies sandbox/turn-granted permissions;
7. executes only the verified patch;
8. tracks file changes/diffs and emits patch lifecycle/progress events;
9. feeds parse/correctness failures back to the model as recoverable tool feedback.

The runtime can also consume streamed patch argument deltas to emit preview/progress updates before the tool invocation is complete.

**Cerebro implication:** a constrained patch tool is a strong Harness v1 candidate. The first implementation should probably be independent rather than copied, but should preserve the same design properties: parse > validate against current files > authorize affected paths > execute > diff/audit > model-visible result.

Upstream:
- `codex-rs/core/src/tools/handlers/apply_patch.rs`
- `codex-rs/apply-patch/*`

## 9. Shell execution is a policy pipeline, not raw subprocess invocation

The inspected unified `exec_command` path confirms several stages before actual process execution:

- parse typed arguments and environment selection;
- resolve cwd relative to the selected environment;
- handle local versus remote/foreign path conventions;
- resolve the environment's shell and requested shell compatibility;
- resolve sandbox-permission intent and additional permissions;
- apply previously granted sticky turn/session permissions;
- enforce approval policy before requesting escalation;
- normalize/validate permission requests;
- intercept commands that are really `apply_patch` and route them through the patch-verification path;
- build a structured execution request with cwd, environment, network, tty, timeout, sandbox and permission state;
- execute through `UnifiedExecProcessManager`;
- return sandbox denials and ordinary execution failures in model-visible form.

Interactive process control is separated from one-shot execution; process IDs allow later input/control via companion tools.

**Cerebro implication:** do not implement Harness v1 shell as `subprocess.run(model_string, shell=True)`. A minimal useful shell runtime still needs environment resolution, timeout/cancellation, output limits, cwd, sandbox/policy checks and durable process identity.

Upstream:
- `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs`
- related unified-exec/process-manager and sandbox modules

## 10. Permissions are checked at execution time against the captured environment

Both `apply_patch` and `exec_command` resolve permissions against the environment captured in the request's StepContext. Permission profiles can combine base workspace policy with previously granted session/turn permissions and narrowly requested additional permissions.

This is distinct from model-facing prompt guidance about what the agent should do.

**Cerebro implication:** model instructions may explain permissions, but the runtime must be the authority. An agent should never be able to gain filesystem/network rights by producing different prose or tool arguments alone.

Upstream:
- `codex-rs/core/src/tools/handlers/apply_patch.rs`
- `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs`
- sandbox/permission modules referenced by those runtimes

## 11. Tool output has its own context-budget behavior

Tool outputs are not treated as unlimited transcript text. The model metadata includes a truncation policy, and tool outputs can carry fallback token-limit overrides. Shell output explicitly tracks original token/output size and omitted bytes.

This matters because a single `pytest`/build/log command can otherwise destroy the useful context budget.

**Cerebro implication:** every tool should have explicit model-visible output-budget/truncation policy separate from full audit/log storage. The model may get a bounded result while Cerebro keeps the complete artifact/log externally.

Upstream:
- `codex-rs/protocol/src/openai_models.rs`
- `codex-rs/core/src/tools/registry.rs`
- `codex-rs/core/src/tools/handlers/unified_exec/exec_command.rs`

## 12. Candidate minimal Cerebro Harness v1 tool stack

Based on this initial mining, the minimal stack should probably be smaller than Codex but preserve its structural boundaries:

```text
ToolCatalog
  canonical executable runtimes

ToolPlanner(request snapshot)
  model/provider capabilities
  agent allowlist
  environment/workspace
  task mode
  MCP availability
  > ToolRouter

ToolRouter
  exact model-visible schemas
  exact executable runtime bindings
  exposure/concurrency metadata

ToolRuntime
  validate args
  authorize
  execute/cancel
  truncate model-visible output
  emit audit/diff/lifecycle
  return one terminal ToolResult
```

Initial built-ins worth implementing before anything elaborate:

- filesystem read/search;
- `apply_patch`-style edit;
- structured shell/process execution;
- git status/diff (possibly via shell initially but with structured wrappers later);
- test execution;
- MCP bridge;
- Cerebro-native collaboration/task tools.

## Open questions still being mined

- exact registry dispatch order including pre/post hooks and rewritten tool inputs;
- sandbox orchestration and approval escalation internals;
- apply-patch grammar and whether any upstream code is worth adapting under Apache rather than independently implementing;
- process manager behavior for persistent/interactively controlled commands;
- output truncation algorithms and model-specific limits;
- MCP tool naming/collision/exposure rules;
- tool search/deferred exposure economics for large catalogs;
- Code Mode and whether it has any value for Cerebro v1;
- verification tools versus ordinary shell/test guidance;
- multi-agent tools and their task/context semantics.

## Provenance ledger additions

| Finding | Upstream source | Classification | Candidate Cerebro use |
| --- | --- | --- | --- |
| Runtime registry separate from model-visible tool plan | `core/src/tools/registry.rs`, `router.rs`, `spec_plan.rs` | conceptual inspiration only | Strong Harness v1 candidate |
| Per-request ToolRouter stored in StepContext | `core/src/session/step_context.rs`, `tools/*` | conceptual inspiration only | Strong Harness v1 candidate |
| Per-tool exposure modes | `core/src/tools/spec_plan.rs`, `registry.rs` | conceptual inspiration only | Agent/model tool policy |
| Per-tool parallel-safety gate | `core/src/tools/parallel.rs` | conceptual inspiration only | Tool concurrency metadata |
| Verified apply-patch pipeline | `core/src/tools/handlers/apply_patch.rs` | conceptual inspiration only | Independently implement first |
| Structured shell permission/sandbox pipeline | `core/src/tools/handlers/unified_exec/exec_command.rs` | conceptual inspiration only | Simplified independent implementation |
| Terminal model-visible result for failure/abort | `stream_events_utils.rs`, `tools/parallel.rs` | conceptual inspiration only | Strong Harness v1 candidate |
| Separate model-visible output budget from durable logs | model metadata + tool output runtimes | conceptual inspiration only | Strong Harness v1 candidate |

No Codex implementation source has been copied or adapted into Cerebro.
