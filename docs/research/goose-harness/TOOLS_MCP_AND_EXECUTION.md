# Goose tools, MCP and execution

Upstream: `aaif-goose/goose`

Pinned commit: `8ae4e4ba02836529790f47109b8785e8b42843a7`

Usage classification: **conceptual inspiration only**.

## MCP is the common tool protocol boundary

Confirmed source:

- `crates/goose/src/agents/mcp_client.rs`
- `crates/goose/src/agents/extension_manager.rs`
- `crates/goose/src/agents/extension.rs`
- `crates/goose/src/agents/platform_extensions/*`

Goose normalizes both external MCP servers and Goose-owned platform extensions behind `McpClientTrait`. The shared interface exposes:

- tool listing and invocation;
- server information/instructions;
- optional resources and resource reads;
- optional prompts;
- notifications/subscriptions;
- optional MOIM context;
- working-directory updates.

This means the model-facing tool registry does not need a separate execution path for “built-in” versus external tools. The protocol shape is shared, while trust, process lifecycle and local execution policy remain Goose-owned.

## Extension transports and lifecycle

Confirmed source: `crates/goose/src/agents/extension_manager.rs`.

`ExtensionManager` owns active extension clients, server metadata, platform context, the active provider, a cached flattened tool list and a monotonically increasing tool-cache version.

Supported extension forms in the pinned product include platform/built-in extensions, stdio child-process MCP servers and streamable HTTP MCP servers. The manager also contains OAuth/credential-store support and can resolve configured commands through Goose's search path, including npm-aware resolution.

For child-process MCP servers:

- Goose injects its resolved executable search path;
- the MCP process is launched with the session working directory when valid;
- long-lived subprocess lifecycle is owned by Goose;
- the CLI can place extensions inside a configured Docker container.

Resolved extension configuration can contain secrets substituted from the credential store. The resolved secret-bearing snapshot is retained in memory for change detection and is explicitly not serialized back to disk.

## Tool discovery, ownership and cache invalidation

Confirmed source:

- `crates/goose/src/agents/extension_manager.rs`
- `crates/goose/src/agents/mcp_client.rs`

Goose flattens extension tools into one model-facing registry and records tool ownership in metadata. Names are normally prefixed to avoid collisions; selected first-class platform extensions can expose unprefixed tools.

The manager contains recovery logic for common model-emitted name mangling such as:

- `functions.` / `functions:` prefixes;
- replacing Goose's `__` extension separator with `.`;
- emitting an owner prefix for an otherwise unprefixed tool.

Recovery occurs only when the mapping is unambiguous.

MCP `tools/list_changed` notifications invalidate the cached tool list and increment the cache version. Tool discovery is therefore dynamic rather than assumed fixed for the lifetime of an agent.

## MCP app/UI metadata trust boundary

Confirmed source: `crates/goose/src/agents/extension_manager.rs`.

Goose strips internal/trusted MCP-app metadata from untrusted tool results. When Goose itself resolves a tool-associated MCP UI resource, it inserts its own trusted attachment metadata describing the tool, extension, resource URI and optional resolved resource/error.

Architecturally this is important: protocol metadata from an extension is not automatically promoted into host-trusted UI metadata.

## Tool call execution context

Confirmed source:

- `crates/goose/src/agents/tool_execution.rs`
- `crates/goose/src/agents/mcp_client.rs`

`ToolCallContext` carries the Goose session id, optional working directory and optional tool-call request id. Tool execution can additionally emit best-effort notifications.

A tool call is not modeled as only a single future/result. Goose can multiplex:

- the terminal MCP `CallToolResult`;
- MCP server notifications;
- action-required/approval messages while the call is pending.

This allows a long-running tool to stream progress and pause for interaction without pretending the tool has completed.

## Approval as a stateful execution boundary

Confirmed source:

- `crates/goose/src/agents/tool_execution.rs`
- `crates/goose/src/tool_inspection.rs`
- `crates/goose/src/permission/permission_inspector.rs`
- `crates/goose/src/agents/tool_confirmation_router.rs`

Before dispatch, tool requests pass through inspection/permission policy. A request that needs approval produces a user-visible, agent-hidden action-required message and waits for a routed confirmation.

Confirmation outcomes can be one-shot or persistent:

- allow once;
- always allow, which updates persistent tool permission;
- deny once;
- always deny, which persists `NeverAllow`.

A denied call becomes a tool error/result that tells the model the user declined it rather than silently disappearing. This keeps the conversational state consistent with the execution boundary.

Some external-agent providers can own approval routing themselves. ACP providers advertise action-required permission routing through the provider abstraction rather than using the normal Goose tool-approval path.

## Permission modes

Confirmed source: `crates/goose/src/permission/permission_inspector.rs`.

Goose's permission behavior depends on `GooseMode`:

- **Auto**: baseline allows tools without approval.
- **Approve**: unknown tools require approval; read-only annotations do not automatically bypass it.
- **SmartApprove**: explicit user permissions still win; read-only annotated tools can be automatically allowed; otherwise Goose can use an LLM-based read-only classification before deciding whether approval is needed.
- **Chat**: the surrounding agent path treats tools as unavailable rather than granting execution.

Extension management is explicitly forced through approval in approval modes.

For SmartApprove, Goose avoids learning a broad name-wide “safe” decision from a single dynamic tool call. A detected non-read-only call can be cached as `AskBefore`, while an automatically recognized read-only call is not used to assert that all future calls to a multipurpose tool are safe.

## Tool inspection pipeline

Confirmed source:

- `crates/goose/src/agents/agent.rs`
- `crates/goose/src/tool_inspection.rs`
- `crates/goose/src/security/security_inspector.rs`
- `crates/goose/src/security/egress_inspector.rs`
- `crates/goose/src/permission/permission_inspector.rs`
- `crates/goose/src/tool_monitor.rs`

At agent construction, Goose installs an ordered inspection pipeline containing security, egress, adversary, permission and repetition inspectors.

Each inspector returns per-request actions (`Allow`, `Deny`, or `RequireApproval`) with reasons/confidence/finding ids. Results are combined conservatively: an `Allow` does not override another inspector's deny or approval requirement. If the permission inspector has no decision for a remaining request, the baseline falls back to requiring approval.

Inspector execution itself is isolated: an inspector error is logged and the manager continues running the remaining inspectors. This is worth distinguishing from the permission decision fallback; failure of one optional inspector does not crash tool execution policy as a whole.

## Security and egress inspection

Confirmed source:

- `crates/goose/src/security/security_inspector.rs`
- `crates/goose/src/security/egress_inspector.rs`

The security inspector is configuration-gated and analyzes tool calls for malicious/prompt-injection-like behavior. In the examined path, a malicious finding that should involve the user becomes an approval requirement with a security warning/finding id rather than an unconditional block.

The egress inspector recognizes common shell/network destinations and directionality, including URLs, git remotes, SSH/SCP/rsync, S3/GCS, Docker registries, package publishing and generic network commands. The purpose is policy visibility over outbound effects rather than assuming every shell command is equivalent.

The agent also installs an LLM-based adversary inspector when configured and a repetition inspector for repeated tool-call behavior.

## Built-in developer filesystem tools

Confirmed source: `crates/goose/src/agents/platform_extensions/developer/mod.rs`.

The first-class `developer` platform extension exposes a flat set of model-facing tools:

- `write` — create or overwrite a file, creating parent directories as needed;
- `edit` — exact unique find/replace editing;
- `shell` — execute a command in the active working directory;
- `tree` — directory tree with line counts, respecting `.gitignore`;
- `read_image` — local-file or HTTP(S) image input.

The tools carry MCP annotations for properties such as read-only/destructive/open-world/idempotent behavior. Those annotations feed permission policy, rather than being only UI descriptions.

File and shell tools resolve relative paths against the `ToolCallContext` working directory. The developer shell also receives the Goose session id through its environment.

## Shell behavior

Confirmed source: `crates/goose/src/agents/platform_extensions/developer/shell.rs`.

On Unix, Goose does not blindly use `$SHELL` for model-generated commands. Unless `GOOSE_SHELL` is set, it prefers `bash` when available and falls back to `sh`, because the model-facing tool contract expects common POSIX shell syntax. Windows defaults to `cmd` unless overridden.

Desktop-launched Goose can resolve the user's login-shell PATH in the background so the backend can find normal CLI tools even when Electron inherited a minimal environment. The result is cached and the first shell call waits for it if needed.

Inside Flatpak, shell execution can be wrapped with `flatpak-spawn --host` so commands run on the host rather than unintentionally inside the application sandbox.

Shell execution supports:

- an explicit/default timeout;
- cancellation;
- live output notifications;
- separate structured stdout/stderr;
- exit status and timeout state;
- bounded model-visible output;
- spilling oversized full output to a temporary file for later inspection.

The pinned implementation limits displayed command output to 2,000 lines / 50,000 bytes and retains overflow in a temporary file rather than dropping it permanently.

## Failure semantics

Confirmed source:

- `crates/goose/src/agents/tool_execution.rs`
- `crates/goose/src/agents/platform_extensions/developer/mod.rs`
- `crates/goose/src/agents/state_machine/ops_toolcalling.rs`
- `crates/goose/src/agents/state_machine/ops_unknown_tool.rs`

Malformed tool arguments, unknown developer tools and declined requests are returned as explicit tool errors/results. They re-enter the persisted conversation and therefore become model-visible evidence for the next inference step.

This is distinct from transport/process failures, which remain execution errors at the tool/MCP boundary. The state-machine path has an explicit unknown-tool operation so a model-emitted invalid tool name can be converted into recoverable conversation state rather than only surfacing as an outer runtime exception.

## Cancellation

Confirmed source:

- `crates/goose-agent/src/machine.rs`
- `crates/goose/src/agents/mcp_client.rs`
- `crates/goose/src/agents/tool_execution.rs`
- `crates/goose/src/agents/platform_extensions/developer/shell.rs`

The same `CancellationToken` concept reaches the control loop, MCP requests and local shell execution. The generic state machine forces a yield after applying a result if cancellation was observed, preventing the loop from immediately starting another autonomous step.

Cancellation is therefore represented as a runtime control signal, while already-produced durable effects can still be persisted.

## Cerebro implications

The strongest reusable pattern is to separate four concepts that are often collapsed into “tools”:

1. **discovery/registry** — what capabilities exist now and who owns them;
2. **policy/inspection** — whether a proposed call may run;
3. **execution** — transport/process/filesystem behavior;
4. **conversation state** — how progress, approval and final results are represented to users/models.

MCP is useful as the common capability/execution protocol, but it does not remove the need for Cerebro-owned trust, approval, egress, filesystem and process policy.

A second useful pattern is dynamic tool-set versioning and explicit ownership metadata. Cerebro's shared collaborative state will likely make this more important, because multiple agents/providers may see different tool subsets or observe tools changing while a session is live.

No Goose implementation code should be copied or adapted during this phase.
