"""Agent directory scanner and seed data bootstrapper for Cerebro v2."""

import json
from pathlib import Path
from typing import Any
from cerebro import db, store

DEFAULT_AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"


async def _execute_write(sql: str, params: tuple[Any, ...] = ()) -> Any:
    fut = await db.enqueue_write(sql, params)
    return await fut


async def load_all_agents(agents_dir: Path = DEFAULT_AGENTS_DIR) -> list[dict]:
    """Scan the agents directory and upsert each agent into SQLite."""
    loaded = []
    if not agents_dir.exists():
        agents_dir.mkdir(parents=True, exist_ok=True)

    for agent_dir in agents_dir.iterdir():
        if not agent_dir.is_dir():
            continue
        profile_file = agent_dir / "profile.json"
        prompt_file = agent_dir / "system_prompt.md"

        if profile_file.exists():
            try:
                agent_data = json.loads(profile_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            if prompt_file.exists():
                agent_data["system_prompt"] = prompt_file.read_text(encoding="utf-8")
            else:
                agent_data.setdefault("system_prompt", "")

            await store.upsert_agent(agent_data)
            loaded.append(agent_data)

    return loaded


async def bootstrap_seed_data(agents_dir: Path = DEFAULT_AGENTS_DIR) -> None:
    """Bootstrap seed agent, team, and DM channel if the database is unpopulated."""
    existing_agents = await store.list_agents()
    if not existing_agents:
        # Load agents from disk
        await load_all_agents(agents_dir)

    # Ensure personal-assistant team exists
    await _execute_write(
        """
        INSERT OR IGNORE INTO teams (id, slug, name, created_at)
        VALUES ('personal-assistant', 'personal-assistant', 'Personal Assistant', datetime('now'));
        """
    )

    # Ensure Jarvis is linked to team
    await _execute_write(
        """
        INSERT OR IGNORE INTO agent_teams (agent_id, team_id)
        VALUES ('jarvis', 'personal-assistant');
        """
    )

    # Ensure DM channel between Dante and Jarvis exists
    dm_channel_id = "dm-dante-jarvis"
    channel = await store.get_channel(dm_channel_id)
    if not channel:
        await store.create_channel(
            channel_id=dm_channel_id,
            name="jarvis",
            channel_type="dm",
            team_id="personal-assistant",
            topic="Direct Message with Jarvis",
            created_by="dante",
        )
        await store.add_channel_member(dm_channel_id, "dante", member_kind="user")
        await store.add_channel_member(dm_channel_id, "jarvis", member_kind="agent")
