"""Cerebro Channel Poller CLI Tool.

Polls the Cerebro HTTP API (/api/channels) for new messages in channels where the
specified agent is an enrolled member. Uses positive bearer token authentication
from `.secrets.env` and maintains an atomic state cursor file.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cerebro.auth import TokenStore  # noqa: E402
from cerebro.config import settings  # noqa: E402


def get_state_file(data_dir: Path | None = None) -> Path:
    """Return path to the agent seen message state file."""
    base = Path(data_dir) if data_dir else settings.data_dir
    return base / ".agent_seen.json"


def load_state(state_file: Path | None = None) -> dict[str, int]:
    """Load the state dictionary mapping agent:channel -> last seen message ID."""
    path = state_file or get_state_file()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return {str(k): int(v) for k, v in data.items()}
        except (json.JSONDecodeError, OSError, ValueError):
            return {}
    return {}


def save_state(state: dict[str, int], state_file: Path | None = None) -> None:
    """Save the state dictionary atomically using a temporary file."""
    path = state_file or get_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def get_agent_token(
    agent_id: str,
    secrets_path: Path | None = None,
) -> str | None:
    """Read agent bearer token from secret environment file via TokenStore."""
    path = secrets_path or (settings.data_dir / ".secrets.env")
    store = TokenStore(path)
    return store.get(agent_id)


def fetch_channels(
    agent_id: str,
    base_url: str = "http://127.0.0.1:8765",
    token: str | None = None,
) -> list[dict]:
    """Fetch list of channels visible to this agent."""
    url = f"{base_url.rstrip('/')}/api/channels"
    tok = token or get_agent_token(agent_id)
    if not tok:
        print(f"[ERROR]: No token found for agent '{agent_id}'", file=sys.stderr)
        return []

    headers = {"Authorization": f"Bearer {tok}"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("channels", [])
    except urllib.error.HTTPError as e:
        print(f"[AUTH ERROR {e.code}] {agent_id}: {e.reason}", file=sys.stderr)
        return []
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        print(f"[NETWORK ERROR] fetch_channels({agent_id}): {e}", file=sys.stderr)
        return []


def fetch_channel_members(
    channel_id: str,
    agent_id: str,
    base_url: str = "http://127.0.0.1:8765",
    token: str | None = None,
) -> list[dict]:
    """Fetch channel member roster."""
    url = f"{base_url.rstrip('/')}/api/channels/{channel_id}/members"
    tok = token or get_agent_token(agent_id)
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("members", [])
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as e:
        print(f"[ERROR] fetch_channel_members({channel_id}): {e}", file=sys.stderr)
        return []


def fetch_messages(
    channel_id: str,
    after_id: int | None = None,
    agent_id: str = "antigravity",
    base_url: str = "http://127.0.0.1:8765",
    token: str | None = None,
) -> list[dict]:
    """Fetch messages for a channel with agent bearer token authorization."""
    url = f"{base_url.rstrip('/')}/api/channels/{channel_id}/messages"
    if after_id is not None:
        url += f"?after={after_id}"
    tok = token or get_agent_token(agent_id)
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("messages", [])
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as e:
        print(f"[ERROR] fetch_messages({channel_id}): {e}", file=sys.stderr)
        return []


def post_message(
    channel_id: str,
    content: str,
    agent_id: str = "antigravity",
    base_url: str = "http://127.0.0.1:8765",
    token: str | None = None,
) -> dict | None:
    """Post a message as an agent to a channel."""
    tok = token or get_agent_token(agent_id)
    if not tok:
        print(f"[ERROR]: No token available to post as '{agent_id}'", file=sys.stderr)
        return None

    url = f"{base_url.rstrip('/')}/api/channels/{channel_id}/messages"
    data = json.dumps({"content": content}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {tok}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ) as e:
        print(f"[ERROR] post_message({channel_id}): {e}", file=sys.stderr)
        return None


def poll_all_channels(
    agent_id: str = "antigravity",
    base_url: str = "http://127.0.0.1:8765",
    update_state: bool = True,
    state_file: Path | None = None,
) -> dict[str, list[dict]]:
    """Poll only channels where the agent is an enrolled member."""
    state = load_state(state_file)
    agent_key_prefix = f"{agent_id}:"
    channels = fetch_channels(agent_id=agent_id, base_url=base_url)
    unseen: dict[str, list[dict]] = {}

    for ch in channels:
        ch_id = ch["id"]
        # Verify agent membership before querying channel messages
        members = fetch_channel_members(ch_id, agent_id=agent_id, base_url=base_url)
        if not any(m.get("member_id") == agent_id for m in members):
            continue

        last_id = state.get(f"{agent_key_prefix}{ch_id}", 0)
        messages = fetch_messages(ch_id, after_id=last_id, agent_id=agent_id, base_url=base_url)
        if messages:
            unseen[ch_id] = messages
            if update_state:
                max_id = max(m["id"] for m in messages if "id" in m)
                state[f"{agent_key_prefix}{ch_id}"] = max(last_id, max_id)

    if update_state and unseen:
        save_state(state, state_file)
    return unseen


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll Cerebro channels for new messages.")
    parser.add_argument(
        "--agent", default="antigravity", help="Agent identifier to authenticate as."
    )
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8765", help="Cerebro API base URL."
    )
    parser.add_argument("--no-state", action="store_true", help="Do not persist read cursor state.")
    parser.add_argument("--post", help="Post a message to a channel specified by --channel.")
    parser.add_argument("--channel", default="warroom", help="Target channel for --post.")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.post:
        res = post_message(args.channel, args.post, agent_id=args.agent, base_url=args.base_url)
        if res:
            print(f"Posted to #{args.channel}: message ID {res.get('id')}")
        else:
            sys.exit(1)
        return

    print(f"Polling channels for agent '{args.agent}'...")
    results = poll_all_channels(
        agent_id=args.agent,
        base_url=args.base_url,
        update_state=not args.no_state,
    )
    if not results:
        print("No new messages.")
    else:
        for cid, msgs in results.items():
            print(f"\n--- Channel: #{cid} ({len(msgs)} new messages) ---")
            for m in msgs:
                print(f"[{m.get('created_at')}] @{m.get('author_id')}: {m.get('content')}")


if __name__ == "__main__":
    main()
