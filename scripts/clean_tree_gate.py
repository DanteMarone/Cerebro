"""Run the test suite against a pristine checkout of HEAD, not the working tree.

Why this exists. Commit `447d795` claimed a fixed tool-round shape and the suite was green — but
the refactor it depended on was sitting uncommitted in the working tree. On a clean checkout the
old, invalid mapping was still what shipped. Codex caught it by reading `HEAD:` directly; nobody
else could have, because every one of us was testing our desk rather than the repository.

That is the same shape as the rest of the day's failures: a signal that says healthy while the
artifact is broken. Here the artifact is the commit itself.

    python scripts/clean_tree_gate.py            # gate HEAD
    python scripts/clean_tree_gate.py 447d795    # gate any commit

Uses `git worktree`, so the checkout is real and the working tree is never touched.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PYTHON = REPO / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():  # non-Windows layout
    PYTHON = REPO / ".venv" / "bin" / "python"


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def dirty_paths() -> list[str]:
    out = run(["git", "status", "--porcelain"], REPO).stdout.splitlines()
    return [line[3:] for line in out if line and not line.startswith("??")]


def main(argv: list[str]) -> int:
    ref = argv[0] if argv else "HEAD"
    interpreter = str(PYTHON) if PYTHON.exists() else sys.executable

    dirty = dirty_paths()
    if dirty:
        print(f"working tree has {len(dirty)} tracked modification(s) not in {ref}:")
        for path in dirty[:10]:
            print(f"  {path}")
        print("  (this is exactly what the gate exists to see past)\n")

    workdir = Path(tempfile.mkdtemp(prefix="cerebro-gate-"))
    checkout = workdir / "tree"
    added = run(["git", "worktree", "add", "--detach", str(checkout), ref], REPO)
    if added.returncode != 0:
        print("could not create worktree:\n" + added.stderr)
        return 2

    try:
        print(f"gating {ref} at {checkout}\n")
        lint = run([interpreter, "-m", "flake8", "."], checkout)
        print(f"flake8: {'clean' if lint.returncode == 0 else 'FAILED'}")
        if lint.returncode != 0:
            print(lint.stdout[-2000:])

        tests = subprocess.run(
            [interpreter, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=checkout,
            capture_output=True,
            text=True,
            env={"PYTHONPATH": str(checkout), "PATH": ""} | _base_env(),
        )
        tail = [ln for ln in tests.stdout.splitlines() if ln.strip()][-3:]
        print("pytest: " + (" / ".join(tail) if tail else "no output"))

        ok = lint.returncode == 0 and tests.returncode == 0
        print("\n" + ("GATE PASSED — the commit stands on its own." if ok else
                      "GATE FAILED — the commit does not work without your working tree."))
        return 0 if ok else 1
    finally:
        run(["git", "worktree", "remove", "--force", str(checkout)], REPO)
        shutil.rmtree(workdir, ignore_errors=True)


def _base_env() -> dict:
    import os

    return {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
