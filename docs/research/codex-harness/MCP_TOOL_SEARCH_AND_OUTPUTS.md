# Codex MCP, Tool Search, and Output-Budget Semantics

**Status:** Confirmed map of MCP tool naming/exposure, deferred tool search, collision policy, execution binding, and model-visible output truncation.

**Pinned upstream:** `openai/codex@0b45b171ca7141fd7723f16adb59cd8e7c1a74c3`

No Codex implementation code is copied into Cerebro by this document. Findings are currently **conceptual inspiration only**.

## Main conclusion

Codex treats a large external tool catalog as a **context-planning problem** rather than simply serializing every connected MCP schema into every model request.

The important layers are:

- MCP connection/binding owns the available external tools for the current request snapshot;
- each MCP tool becomes a canonical namespaced runtime tool;
- model-visible exposure can be direct, deferred/searchable, Code Mode-only, or hidden;
- collisions never silently let an external tool replace an existing trusted/core tool;
- deferred tools are discovered through a compact searchable index, then returned as loadable schemas;
- full runtime/log output and model-visible output have intentionally different budgets.

For Cerebro, the useful design is not the exact Codex naming or BM25 implementation. It is the structural rule: **connect broadly, expose narrowly, bind exactly, preserve full results outside context, and let the model discover schemas only when needed.**

## 1. MCP tools have canonical runtime identity separate from display/hook aliases

`McpHandler` is constructed from a `codex_mcp::ToolInfo` and uses `ToolInfo::canonical_tool_name()` as its executable `ToolName`.

The model-facing spec is a namespace tool. Its namespace is the tool's `callable_namespace`; the MCP function itself remains a child function inside that namespace.

Legacy/hook-facing names are separately flattened using a `mcp__` prefix plus `__` delimiter. This compatibility name is not the fundamental runtime identity.

Confirmed example from tests/search output:

```text
namespace: mcp__calendar
  create_event
  list_events
```

**Cerebro implication:** keep a structured canonical tool key such as:

```text
source_type = mcp
source_id = calendar
namespace = calendar
name = create_event
```

Generate provider-specific flattened names only at the adapter boundary when a model API requires them. Do not make a lossy flattened string the primary database/runtime identity.

Upstream:
- `codex-rs/core/src/tools/handlers/mcp.rs`
- `codex-rs/codex-mcp/*` `ToolInfo`

## 2. External tools cannot silently shadow trusted/core tools

`ToolRegistry` normalizes tool names and treats trusted and external registrations differently.

Trusted duplicate registration is a programming/configuration error.

External registration is fail-closed:

- default-namespace external `exec_command` and `shell_command` are explicitly rejected;
- if an external tool collides with an already registered canonical name, the existing tool remains registered;
- the duplicate external tool is skipped;
- the registry records the first collision for later diagnostics.

Special model tools such as tool search also reserve their model-visible namespace during finalization; conflicting ordinary namespace tools are removed and recorded as collisions.

**Cerebro implication:** define deterministic tool precedence and collision diagnostics. An MCP server, plugin or user-added tool must never be able to replace a built-in privileged tool merely by choosing the same name.

A sensible initial precedence is:

```text
Cerebro privileged/control tools
  > workspace-owned trusted tools
  > configured external MCP/plugin tools
```

with explicit namespacing preferred over precedence whenever possible.

Upstream:
- `codex-rs/core/src/tools/registry.rs`
- `codex-rs/core/src/tools/spec_plan.rs`

## 3. MCP model visibility is filtered before registration/exposure

The request-scoped MCP tool source does not indiscriminately expose every connected tool.

Confirmed filters/policies include:

- `tool_is_model_visible(...)` from MCP metadata;
- apps-enabled state;
- connector/app policy for Codex Apps tools;
- destructive/open-world annotations used by app policy;
- agent-plugin schema-size budgets;
- server-specific `omit_tools_from` exposure settings;
- Code Mode/direct-only namespace policy;
- whether tool search is enabled for the active model/turn.

Agent-plugin MCP tools are additionally bounded by per-tool and aggregate serialized spec budgets; tools that exceed those budgets can remain registered but hidden from the model.

**Cerebro implication:** MCP connection state and model exposure must be separate. `connected == true` should only mean the runtime can potentially call the server. The effective model tool set should be derived for each request from agent/workspace/model/provider policy.

Upstream:
- `codex-rs/core/src/mcp_tool_exposure.rs`
- `codex-rs/core/src/tools/spec_plan.rs`

## 4. Tool exposure is a multi-surface policy, not a boolean

For MCP tools, Codex computes effective exposure across three relevant surfaces:

- direct model exposure;
- deferred/tool-search exposure;
- Code Mode exposure.

The final `ToolExposure` can therefore be hidden, Code Mode-only, direct-model-only, direct, deferred-model-only, or deferred.

When tool search is enabled and deferred exposure is allowed, direct exposure is removed rather than duplicating the same large schema both directly and through search.

**Cerebro implication:** even if Harness v1 starts with only `hidden | direct | deferred`, design the policy representation so another execution surface can be added later without rewriting the catalog model.

Upstream:
- `codex-rs/core/src/tools/spec_plan.rs`
- `codex-rs/tools/src/tool_call.rs` / exposure types

## 5. Deferred tool search indexes lightweight semantic text, not full executable objects

`ToolSearchInfo` builds a searchable text representation from a tool's:

- namespace name/description;
- tool name and underscore-separated readable form;
- tool description;
- parameter/property names;
- schema descriptions recursively through nested items/variants.

The returned loadable tool spec has `defer_loading = true`; function output schemas are removed from the deferred search representation.

The search handler builds a BM25 English index over these textual documents. Search requires a non-empty query and bounded result count. Results are converted back to `LoadableToolSpec`s and coalesced, so multiple matching tools in one namespace can be returned under one namespace object.

**Cerebro implication:** the first implementation does not need embeddings. A compact lexical index over tool name, namespace, description and argument field descriptions is likely sufficient for Harness v1. The important API is:

```text
search_tools(query, limit)
  > lightweight ranked tool identities
  > load exact schemas into the current request/tool plan
```

The search index is a derived cache; the canonical tool catalog remains the source of truth.

Upstream:
- `codex-rs/tools/src/tool_search.rs`
- `codex-rs/core/src/tools/handlers/tool_search.rs`

## 6. Tool search is itself a model tool with reserved identity

During router finalization, Codex adds the tool-search executor only when there is at least one deferred searchable runtime.

If another registered tool already owns the tool-search name or a namespace that conflicts with its special model-visible wire identity, the conflicting tool is removed and the collision is recorded before the real search tool is installed.

The search call then returns a typed `ToolSearchOutput`, not arbitrary prose. The provider/model can load those returned deferred definitions for subsequent tool use.

**Cerebro implication:** `search_tools` should be a privileged Harness tool backed by the request-scoped catalog, not an ordinary MCP tool that can itself be shadowed by an external source.

Upstream:
- `codex-rs/core/src/tools/spec_plan.rs`
- `codex-rs/core/src/tools/handlers/tool_search.rs`
- `codex-rs/core/src/tools/context.rs`

## 7. The exact MCP binding is request-scoped

As mapped earlier in `TOOLS_AND_EXECUTION.md`, `build_tool_router(...)` receives the MCP binding captured for the current sampling step. MCP handlers are built/cached from that binding and the resulting registry/router is retained in the step context used for execution.

Before an MCP call executes, the session prepares the call against the server/tool from that request context. If preparation says the tool is no longer available to the model, execution returns a model-visible skipped/error result rather than silently dispatching a different current tool.

**Cerebro implication:** the tool schema the model saw and the executable tool binding should share a request/catalog version. If a server reconnects or changes schemas during inference, that change should affect a later request, not mutate the meaning of an already-issued tool call.

Upstream:
- `codex-rs/core/src/tools/spec_plan.rs`
- `codex-rs/core/src/tools/handlers/mcp.rs`
- `codex-rs/core/src/mcp_tool_call.rs`

## 8. MCP execution still passes through harness policy and lifecycle

An MCP call is not a direct pass-through from model to server.

Confirmed runtime stages include:

- parse/validate JSON arguments;
- verify the prepared tool remains available;
- construct typed invocation/lifecycle metadata;
- evaluate app/server approval policy;
- request approval/Guardian review where required;
- support cancellation;
- invoke the MCP server;
- emit lifecycle/telemetry;
- normalize the result to a harness `McpToolOutput`;
- apply model-visible truncation separately from logging.

**Cerebro implication:** MCP should be an interoperability transport behind Cerebro's `ToolRuntime`, not a bypass around Cerebro permissions, approvals, auditing, cancellation or output budgets.

Upstream:
- `codex-rs/core/src/mcp_tool_call.rs`
- `codex-rs/core/src/tools/handlers/mcp.rs`

## 9. MCP read-only annotations can influence concurrency

`McpHandler::supports_parallel_tool_calls()` allows parallel execution when either the tool/server metadata explicitly opts in or the MCP tool advertises `read_only_hint`.

This is still passed through the generic tool-runtime concurrency gate mapped in `TOOLS_AND_EXECUTION.md`.

**Cerebro implication:** MCP annotations are useful hints but should not be blindly trusted as authorization. They can inform default concurrency/safety policy, while Cerebro keeps final authority and can override metadata for known tools/servers.

Upstream:
- `codex-rs/core/src/tools/handlers/mcp.rs`

## 10. Model-facing tool output and durable/log output are separate products

This is one of the strongest confirmed patterns in the tool layer.

For MCP output:

- `log_output()` deliberately does **not** first apply the model-context budget;
- the response payload shown to the model gets timing metadata and a configured/model-derived truncation policy;
- Code Mode can retain the raw structured result;
- the persisted response envelope can carry a fallback token-limit override.

For shell/exec output:

- raw bytes and original-output metadata are retained in the runtime object;
- an upstream collection cap can separately record omitted bytes;
- logging/telemetry does not inherit the model output-token limit;
- model-visible response text uses the stricter of explicit command `max_output_tokens` and the model's truncation policy.

**Cerebro implication:** every tool result should conceptually have at least:

```text
raw_result / artifact reference
  durable audit + UI/download path

model_result
  bounded representation inserted into model context

summary metadata
  original size, truncation/omission facts, exit/status/timing
```

Do not throw away the only full copy merely because the model context needs truncation.

Upstream:
- `codex-rs/core/src/tools/context.rs`
- unified exec/process sources

## 11. Text truncation preserves both beginning and end

The shared output-truncation utility supports byte- or approximate-token budgets.

When ordinary text exceeds the model budget, formatted truncation reports the approximate original token count and total line count, then uses **middle truncation** rather than only keeping the prefix.

This is a sensible default for logs because useful setup/context often appears at the start while the actual exception/test summary appears at the end.

**Cerebro implication:** use head+tail/middle truncation for logs and command output by default. Record exact byte counts and, when feasible, make the full artifact addressable so an agent can explicitly read another slice if needed.

Upstream:
- `codex-rs/utils/output-truncation/src/lib.rs`
- shared string truncation utilities

## 12. Multimodal output budgets need type-aware handling

Function-call output truncation is not simply `string[..N]`.

Confirmed behavior:

- text consumes the configured byte/token budget and can be truncated;
- images are retained by this generic truncation path rather than counted as ordinary text bytes;
- audio consumes an estimated token/byte cost and can be omitted when the remaining budget is insufficient;
- encrypted content is preserved;
- omitted text/audio item counts receive explicit marker items.

MCP output also sanitizes original image-detail requests based on the selected model capability.

**Cerebro implication:** define content-part-aware tool results. A canonical tool output should be something like `text | image | audio | file/artifact | structured`, with provider/model adaptation deciding what can actually be inserted into the next inference.

Upstream:
- `codex-rs/utils/output-truncation/src/lib.rs`
- `codex-rs/core/src/tools/context.rs`
- `codex-rs/core/src/tools/handlers/mcp.rs`

## 13. Code Mode is an alternate tool execution surface, not a Harness v1 requirement

Codex Code Mode hosts a separate executable runtime/cell and lets code make nested calls through the same request-scoped `ToolCallRuntime`. Nested calls still use canonical tool names, cancellation, the router and normal result conversion. Code Mode has its own output truncation and cell lifecycle.

That architecture can reduce repeated model/tool round trips for programmatic workflows and can expose tools that are not directly model-visible. But it introduces a substantial new runtime, broker/cell lifecycle, nested-call semantics and security surface.

**Cerebro implication:** preserve the possibility of alternate execution surfaces in the tool catalog, but do **not** make Code Mode a Harness v1 prerequisite. Direct + deferred model tools cover the core architectural need first.

Upstream:
- `codex-rs/core/src/tools/code_mode/mod.rs`
- `codex-rs/code-mode/*`

## 14. Candidate Cerebro Harness v1 tool-catalog policy

A minimal design preserving the useful boundaries is:

```text
ToolCatalog
  ToolKey { source, namespace, name }
  runtime binding
  compact discovery metadata
  full input/output schemas
  safety/concurrency annotations
  source provenance

ToolPlanSnapshot
  catalog_version
  directly_exposed tools
  deferred/searchable tools
  hidden tools
  provider-shaped names/schemas

search_tools(query, limit)
  search only the snapshot's deferred set
  return exact loadable definitions

ToolCall
  canonical ToolKey + call_id + args
  execute against same ToolPlanSnapshot/catalog version

ToolResult
  terminal status
  bounded model representation
  durable raw/artifact representation
  truncation/original-size metadata
```

This is enough for large MCP catalogs without requiring Codex's complete Code Mode implementation.

## 15. Strong Harness v1 rules from this slice

1. **Never expose the entire connected tool universe by default.** Plan per request.
2. **Never let external tools shadow privileged built-ins.** Namespace and fail closed on collision.
3. **Make tool discovery derived from the same snapshot used for execution.**
4. **Treat MCP as a transport behind Cerebro policy.** Connection does not imply permission or model exposure.
5. **Preserve full outputs outside model context.** Model truncation is presentation, not data deletion.
6. **Use head+tail/middle truncation for log-like text and record omission metadata.**
7. **Keep tool result content typed.** Text, images, audio, files/artifacts and structured results have different budgeting/adaptation rules.
8. **Defer Code Mode until direct/deferred tools, permissions, recovery and persistence are stable.**

## Open questions for implementation design, not further Codex archaeology

- exact Cerebro tool namespace syntax and provider-safe flattening/escaping rules;
- whether deferred search is lexical-only or later hybrid lexical/vector;
- how schemas returned by `search_tools` become visible on providers without native deferred-tool primitives;
- full-result artifact storage and retention policy;
- per-tool/model default context budgets;
- whether tool outputs should support explicit pagination/slicing references;
- how much MCP annotation metadata Cerebro trusts versus overrides centrally.

These belong in `CODEX_TO_CEREBRO_GAP.md` and `CEREBRO_HARNESS_V1.md` rather than requiring more Codex source mining first.

## Provenance ledger additions

| Finding | Upstream source | Classification | Candidate Cerebro use |
| --- | --- | --- | --- |
| Canonical MCP namespace/tool identity | MCP handler/ToolInfo | conceptual inspiration only | Structured `ToolKey` |
| External collision fail-closed policy | `tools/registry.rs`, router finalization | conceptual inspiration only | Strong Harness v1 rule |
| Request/model/policy-derived MCP exposure | `mcp_tool_exposure.rs`, `spec_plan.rs` | conceptual inspiration only | Strong Harness v1 rule |
| Direct/deferred/code-mode exposure surfaces | `spec_plan.rs` | conceptual inspiration only | Start with direct/deferred, extensible model |
| Lexical deferred-tool search | `tools/tool_search.rs`, handler | conceptual inspiration only | Independent simple search implementation |
| Same request-scoped binding for discovery/execution | `spec_plan.rs`, MCP handler/call | conceptual inspiration only | Strong Harness v1 rule |
| MCP routed through approval/lifecycle/cancellation | `mcp_tool_call.rs` | conceptual inspiration only | MCP bridge contract |
| Full log/raw output separate from model result | `tools/context.rs` | conceptual inspiration only | Strong Harness v1 rule |
| Middle/head-tail truncation with omission metadata | output-truncation utility | conceptual inspiration only | Independently implement |
| Type-aware multimodal truncation | output-truncation utility | conceptual inspiration only | Canonical typed `ToolResult` |
| Code Mode nested runtime | `tools/code_mode/*` | conceptual inspiration only | Explicitly defer from Harness v1 |

No Codex implementation source has been copied or adapted into Cerebro.
