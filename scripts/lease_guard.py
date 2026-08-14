"""Refuse a commit that touches files the committer does not hold a lease on.

**This is a workflow guard, not a security boundary.** `git commit --no-verify` bypasses it, the
committing identity comes from local configuration, and anything with write access to the repo can
edit or delete this file. It stops honest mistakes. It stops nothing else, and it should never be
cited as though it did.

The claim being made for it is narrow and specific: on 2026-08-14 the Cerebro team had three lease
violations -- a scope overrun, a commit with no lease declared at all, and a test file added outside
a declared set. Two were mine, made while I was enforcing §8.7 on everybody else. All three were
found afterwards by review rather than at the moment of the mistake. This turns all three into a
refused commit with a message naming the file.

Design notes:

- **It asks the server; it does not reconstruct the rules.** `GET /api/leases/check` owns the
  matching semantics. A guard with its own copy of "does this lease cover this path" drifts the
  moment either side changes and then reports confidently using the wrong rules.
- **Renames and deletes are checked at both ends.** The staged diff is taken with `--no-renames`, so
  `git mv a b` arrives as a delete of `a` and an add of `b` and requires holding both. Holding only
  the destination is not holding the change.
- **It fails closed.** Unreachable server, unknown identity, malformed response: refuse. A guard
  that fails open is decoration, and the moment it is most likely to be unreachable is during the
  kind of messy session where it matters most.

Usage (normally invoked from .githooks/pre-commit):

    python scripts/lease_guard.py

Identity resolution, in order: --agent, $CEREBRO_AGENT, `git config cerebro.agent`.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cerebro.auth import TokenStore  # noqa: E402
from cerebro.config import settings  # noqa: E402

DEFAULT_BASE_URL = os.environ.get("CEREBRO_BASE_URL", "http://127.0.0.1:8765")

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_CANNOT_VERIFY = 2


class CannotVerify(Exception):
    """We could not establish whether the commit is allowed. Treated as a refusal."""


def staged_paths() -> list[str]:
    """Repo-relative paths in the staged diff, with renames split into delete + add."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--no-renames"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CannotVerify(f"could not read the staged diff: {result.stderr.strip()}")
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def resolve_agent(explicit: str | None) -> str:
    if explicit:
        return explicit
    if os.environ.get("CEREBRO_AGENT"):
        return os.environ["CEREBRO_AGENT"]
    result = subprocess.run(
        ["git", "config", "cerebro.agent"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise CannotVerify(
        "no committing identity. Set one with:\n"
        "    git config cerebro.agent <your-agent-id>\n"
        "or export CEREBRO_AGENT=<your-agent-id>."
    )


def token_for(agent_id: str) -> str:
    tokens = TokenStore(settings.data_dir / ".secrets.env")._read()
    if agent_id not in tokens:
        raise CannotVerify(
            f"no API token for {agent_id!r}. Mint one with scripts/agent_token.py, or correct "
            "`git config cerebro.agent`."
        )
    return tokens[agent_id]


def check(paths: list[str], token: str, base_url: str) -> dict:
    query = urllib.parse.urlencode([("path", p) for p in paths])
    req = urllib.request.Request(f"{base_url}/api/leases/check?{query}")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise CannotVerify(f"the lease API refused the check ({exc.code}). Is the token valid?")
    except Exception as exc:  # noqa: BLE001 - any failure here is a refusal, see module docstring
        raise CannotVerify(
            f"could not reach the lease API at {base_url} ({exc}). Start Cerebro, or bypass "
            "deliberately with --no-verify and say so in the channel."
        )


def report(payload: dict) -> int:
    unheld = [r for r in payload.get("results", []) if not r.get("held")]
    if not unheld:
        overrides = [r for r in payload["results"] if r.get("by_owner_override")]
        if overrides:
            print(
                f"lease-guard: allowed as repo owner ({payload['principal']}) for "
                f"{len(overrides)} path(s) with no explicit lease."
            )
        return EXIT_OK

    print("", file=sys.stderr)
    print("lease-guard: BLOCKED -- staged files you do not hold a lease on:",
          file=sys.stderr)
    print("", file=sys.stderr)
    for entry in unheld:
        if entry.get("held_by"):
            print(
                f"  {entry['path']}\n"
                f"      held by @{entry['held_by']} as {entry['conflicting_resource']}",
                file=sys.stderr,
            )
        else:
            print(f"  {entry['path']}\n      no lease declared", file=sys.stderr)
    print("", file=sys.stderr)
    print(
        f"Declare a lease as @{payload['principal']} covering these paths, then commit again.\n"
        "This is an advisory guard: --no-verify bypasses it. If you do that, say so in the "
        "channel rather than letting it pass silently.",
        file=sys.stderr,
    )
    return EXIT_BLOCKED


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", help="committing agent id (overrides env and git config)")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--paths", nargs="*", help="check these paths instead of the staged diff (for testing)"
    )
    args = parser.parse_args()

    try:
        paths = args.paths if args.paths is not None else staged_paths()
        if not paths:
            return EXIT_OK
        agent = resolve_agent(args.agent)
        payload = check(paths, token_for(agent), args.base_url)
    except CannotVerify as exc:
        print("", file=sys.stderr)
        print(f"lease-guard: CANNOT VERIFY -- refusing the commit.\n\n  {exc}", file=sys.stderr)
        print("", file=sys.stderr)
        return EXIT_CANNOT_VERIFY

    return report(payload)


if __name__ == "__main__":
    raise SystemExit(main())
