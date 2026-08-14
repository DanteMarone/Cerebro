"""Turn an agent's polling on or off (§6, Slice 3).

    python scripts/agent_wake.py status
    python scripts/agent_wake.py on codex
    python scripts/agent_wake.py off codex

Polling is opt-in and off by default. Switching four agents on at once would have every one of
them answer every message in every channel they belong to — a message storm and a token bill
before anyone has watched a single agent wake, answer and stop. Turn them on one at a time and
watch the first one.

Changes take effect on the next server restart, because the seeder reads these profiles at
startup.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cerebro.config import settings  # noqa: E402

USAGE = "usage: python scripts/agent_wake.py [status | on <agent> | off <agent>]"


def profiles() -> list[Path]:
    return sorted(settings.agents_path.glob("*/profile.json"))


def show() -> int:
    rows = []
    for path in profiles():
        data = json.loads(path.read_text(encoding="utf-8"))
        params = data.get("params") or {}
        rows.append((
            data.get("id", path.parent.name),
            "awake" if params.get("poll_enabled") else "asleep",
            str(params.get("poll_interval_s", "default")),
            data.get("provider", "?"),
            data.get("trust", "sandboxed"),
        ))
    if not rows:
        print("no agent profiles found")
        return 1
    print(f"{'agent':14s} {'polling':8s} {'interval':10s} {'provider':12s} trust")
    for row in rows:
        print(f"{row[0]:14s} {row[1]:8s} {row[2]:10s} {row[3]:12s} {row[4]}")
    return 0


def set_polling(agent_id: str, enabled: bool) -> int:
    path = settings.agents_path / agent_id / "profile.json"
    if not path.exists():
        print(f"no profile for '{agent_id}' at {path}")
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    params = data.setdefault("params", {})
    params["poll_enabled"] = enabled
    params.setdefault("poll_interval_s", 45)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"{agent_id} polling {'ENABLED' if enabled else 'disabled'} "
          f"(every {params['poll_interval_s']}s). Restart Cerebro to apply.")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        print(USAGE)
        return 2
    command, *rest = argv
    if command == "status":
        return show()
    if command in ("on", "off"):
        if not rest:
            print(USAGE)
            return 2
        return set_polling(rest[0], command == "on")
    print(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
