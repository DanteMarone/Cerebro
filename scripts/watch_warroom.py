"""A file watcher for archived Cerebro channel transcripts.

Monitors an explicitly named Markdown file and outputs new incoming messages directed to
@antigravity or @everyone. The former default build-room transcript was retired after Slice 2.

Usage:
    python scripts/watch_warroom.py [--once] channel_path
"""

import re
import sys
import time
from pathlib import Path

HEADING = re.compile(r"^### @(\w+) → @(\w+) · (.+)$")


def parse_messages(file_path: Path):
    """Parse messages from a channel transcript markdown file."""
    if not file_path.exists():
        return []
    text = file_path.read_text(encoding="utf-8")
    messages = []
    current = None
    for line in text.splitlines():
        m = HEADING.match(line.strip())
        if m:
            if current:
                current["body"] = "\n".join(current["lines"]).strip()
                del current["lines"]
                messages.append(current)
            current = {
                "author": m.group(1),
                "recipient": m.group(2),
                "time": m.group(3),
                "lines": [],
            }
        elif current is not None:
            if line.strip() != "---":
                current["lines"].append(line)
    if current:
        current["body"] = "\n".join(current["lines"]).strip()
        del current["lines"]
        messages.append(current)
    return messages


def check_for_new_messages(channel_path: Path, last_count: int):
    """Check for new messages and return (new_count, list_of_new_messages)."""
    messages = parse_messages(channel_path)
    if len(messages) > last_count:
        new_msgs = messages[last_count:]
        return len(messages), new_msgs
    return len(messages), []


def main():
    once = "--once" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--once"]
    if not args:
        print("usage: watch_warroom.py [--once] channel_path", file=sys.stderr)
        raise SystemExit(2)
    channel_path = Path(args[0])

    messages = parse_messages(channel_path)
    last_count = len(messages)
    print(
        f"[Watcher] Monitoring {channel_path} ({last_count} existing messages)...",
        flush=True,
    )

    if once:
        return

    while True:
        time.sleep(2)
        count, new_msgs = check_for_new_messages(channel_path, last_count)
        if new_msgs:
            last_count = count
            for msg in new_msgs:
                target = msg["recipient"].lower()
                author = msg["author"].lower()
                if author != "antigravity":
                    print(
                        f"\n=== NEW MESSAGE: @{msg['author']} → @{msg['recipient']} "
                        f"({msg['time']}) ===",
                        flush=True,
                    )
                    print(msg["body"], flush=True)
                    if target in ("antigravity", "everyone"):
                        print(
                            f"\n>>> ACTION REQUIRED: Message addressed to @{target}!\n",
                            flush=True,
                        )


if __name__ == "__main__":
    main()
