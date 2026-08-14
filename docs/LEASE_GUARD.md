# Lease Commit Guard

**This is a workflow guard, not a security boundary.** `git commit --no-verify` bypasses it, the
committing identity comes from local configuration, and anyone with write access to the repo can
edit or delete it. It stops honest mistakes. It stops nothing else, and it must never be cited as
though it did.

That caveat is first because the alternative — describing it as "mutex enforcement" — would make it
worse than useless. A guard people believe is a lock is a guard people stop double-checking.

## What it is for

Leases (§8.7) coordinate who may edit what. On 2026-08-14 the team had three violations in a single
session:

| Violation | What happened |
|---|---|
| Scope overrun | A new production module committed outside the declared two-file lease |
| No lease at all | `9c4bd33` edited and committed two files with nothing declared |
| Untracked addition | A test file added outside a declared lease set |

Two of the three were the architect's, made while enforcing the protocol on everyone else. All three
were caught afterwards by review, not at the moment of the mistake. The guard turns each of them
into a refused commit naming the file.

## Setup

```bash
git config core.hooksPath .githooks
git config cerebro.agent <your-agent-id>
```

The agent id must have an API token (`scripts/agent_token.py`). Identity resolves in order:
`--agent`, `$CEREBRO_AGENT`, `git config cerebro.agent`.

## How it decides

The hook does **not** reconstruct the matching rules. It asks the server:

```
GET /api/leases/check?path=<repo-relative-path>&path=...
```

The endpoint takes the caller's identity from the bearer principal — never from a query parameter,
or the guard could be told whose leases to consult — and answers per path:

```json
{
  "principal": "claude",
  "is_owner": false,
  "all_held": false,
  "results": [
    {"path": "cerebro/usage.py", "held": true,  "matched_resource": "file:cerebro/usage.py"},
    {"path": "cerebro/db.py",    "held": false, "held_by": "antigravity",
     "conflicting_resource": "file:cerebro/db.py"}
  ]
}
```

Keeping the rules server-side is deliberate: a guard carrying its own copy of "does this lease cover
this path" drifts the moment either side changes, and then reports confidently using the wrong
rules.

### Coverage rules

- Only `file:` leases govern file contents. Holding `repo:Cerebro:HEAD` is permission to move the
  branch, not to edit anything in it.
- A directory lease covers everything beneath it. `file:cerebro/` satisfies `cerebro/usage.py`.
  Without this, a slice needs twenty declarations and people quietly stop declaring.
- A shared prefix is not coverage. `file:cerebro/us` does **not** satisfy `cerebro/usage.py`.
- Dante (repo owner) passes without an explicit lease, and the guard says so rather than staying
  silent about the override.

### Renames and deletes

The staged diff is read with `--no-renames`, so `git mv a b` arrives as a delete of `a` and an add
of `b`, and the commit requires holding **both**. Holding only the destination is not holding the
change. A delete requires holding the path being removed.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Every staged path is covered (or the caller is the repo owner) |
| 1 | Blocked — at least one staged path is not held |
| 2 | Cannot verify — refused |

**It fails closed.** Unreachable server, unknown identity, malformed response: the commit is
refused. A guard that fails open is decoration, and the moment it is most likely to be unreachable
is a messy session — exactly when the coordination it protects matters most.

To proceed anyway:

```bash
CEREBRO_LEASE_GUARD=off git commit ...   # or: git commit --no-verify
```

If you do that, say so in the channel. A silent bypass is the failure this exists to prevent,
wearing a different hat.

## Important: the database is the source of truth

The guard reads leases from the API, not from chat messages. A lease announced in `#warroom` and
never acquired through `/api/leases/acquire` does not exist as far as the guard is concerned — this
is intentional (`@codex`: *do not parse chat text for lease markers*), but it means declaring in
chat alone is no longer sufficient. Acquire through the API or the CLI:

```bash
python scripts/poll_channels.py --agent <id> --lease-acquire "file:path/to/file.py" --ttl 600 --reason "why"
```

## Verified behaviour

End-to-end against a live server (transcript under `workspace/evidence/lease-guard/`):

| Scenario | Result |
|---|---|
| Path the caller holds | exit 0 |
| Path nobody declared | exit 1, "no lease declared" |
| Path held by another agent | exit 1, names the holder and the resource |
| Mixed batch, one held one not | exit 1 — a partially-held commit is not a held commit |
| API unreachable | exit 2, CANNOT VERIFY |
| No committing identity | exit 2, CANNOT VERIFY |
