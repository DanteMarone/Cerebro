"""Issue and revoke agent bearer tokens (architecture §6.3).

Named agent_token rather than token because a script called token.py sits at sys.path[0]
when run directly and shadows the standard library token module, which tokenize imports --
so importing anything that touches dataclasses fails with a circular import.

    python scripts/agent_token.py issue claude
    python scripts/agent_token.py revoke claude
    python scripts/agent_token.py list

The token is printed once, on issue. It is stored in data/.secrets.env and never shown again by
`list`, which reports only which agents hold one -- if it is lost, issue a new one, which replaces
the old.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebro.auth import TokenStore  # noqa: E402
from cerebro.config import settings  # noqa: E402

USAGE = "usage: python scripts/agent_token.py [issue <agent> | revoke <agent> | list]"


def main(argv: list[str]) -> int:
    if not argv:
        print(USAGE)
        return 2

    store = TokenStore(settings.data_dir / ".secrets.env")
    command, *rest = argv

    if command == "list":
        agents = store.agents()
        print("\n".join(agents) if agents else "no agent tokens issued")
        return 0

    if command in ("issue", "revoke"):
        if not rest:
            print(USAGE)
            return 2
        agent = rest[0]
        if command == "issue":
            token = store.issue(agent)
            print(f"token for {agent} (shown once, stored in {store.path}):\n\n{token}\n")
            print("Send it as:  Authorization: Bearer <token>")
            return 0
        removed = store.revoke(agent)
        print(f"revoked {agent}" if removed else f"{agent} had no token")
        return 0 if removed else 1

    print(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
