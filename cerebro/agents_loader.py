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
    """Bootstrap seed agent, team, and DM channels from disk."""
    # Always load and sync agent profiles from disk
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

    # Ensure DM channels exist between Dante and each agent
    agents = await store.list_agents()
    for agent in agents:
        agent_id = agent["id"]
        dm_channel_id = f"dm-dante-{agent_id}"
        channel = await store.get_channel(dm_channel_id)
        if not channel:
            display_name = agent.get("display_name") or agent.get("name") or agent_id
            await store.create_channel(
                channel_id=dm_channel_id,
                name=display_name,
                channel_type="dm",
                team_id="personal-assistant",
                topic=f"Direct Message with {display_name}",
                created_by="dante",
            )
            await store.add_channel_member(dm_channel_id, "dante", member_kind="user")
            await store.add_channel_member(dm_channel_id, agent_id, member_kind="agent")

    # Ensure warroom channel has sonnet and opus if warroom channel exists
    warroom = await store.get_channel("warroom")
    if warroom:
        await store.add_channel_member("warroom", "sonnet", member_kind="agent", listen_mode="active")
        await store.add_channel_member("warroom", "opus", member_kind="agent", listen_mode="active")

    # Link sonnet and opus to teams
    for agent_id in ("sonnet", "opus"):
        await _execute_write(
            """
            INSERT OR IGNORE INTO agent_teams (agent_id, team_id)
            VALUES (?, 'personal-assistant');
            """,
            (agent_id,),
        )
        await _execute_write(
            """
            INSERT OR IGNORE INTO agent_teams (agent_id, team_id)
            VALUES (?, 'cerebro-core');
            """,
            (agent_id,),
        )
