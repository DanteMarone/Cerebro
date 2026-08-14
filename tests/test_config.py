from pathlib import Path
from cerebro.config import Settings, settings


def test_default_settings():
    """Verify all default configuration keys match the Slice 0 table."""
    assert settings.host == "127.0.0.1"
    assert settings.port == 8765
    assert settings.lmstudio_base_url == "http://127.0.0.1:1234"
    assert settings.lmstudio_concurrency == 2
    assert settings.gemini_concurrency == 4
    assert settings.moderator_model == ""
    assert settings.moderator_window == 12
    assert settings.max_auto_speakers == 2
    assert settings.history_window == 30
    assert settings.context_budget == 24000
    assert settings.max_depth == 8
    assert settings.max_agent_messages_per_turn == 12
    assert settings.max_turn_wallclock_s == 600
    assert settings.max_tool_iterations == 12
    assert settings.max_self_initiated_per_hour == 6
    assert settings.daily_usd_budget == 5.0
    assert settings.daily_delegations == 3
    assert settings.debug is False
    assert settings.vault_path == Path("D:/Obsidian/MyVault/Cerebro")
    assert settings.claude_memory_path == Path("D:/Obsidian/MyVault/Claude Memory")


def test_ensure_dirs_creates_data_and_journal_only(tmp_path: Path):
    """ensure_dirs must create data_dir and journal/, but NOT claude_memory_path."""
    custom_data = tmp_path / "data"
    custom_claude_mem = tmp_path / "claude_mem_forbidden"

    cfg = Settings(
        data_dir=custom_data,
        db_path=custom_data / "cerebro.db",
        claude_memory_path=custom_claude_mem,
    )

    assert not custom_data.exists()
    assert not custom_claude_mem.exists()

    cfg.ensure_dirs()

    assert custom_data.exists()
    assert (custom_data / "journal").exists()
    assert not custom_claude_mem.exists(), "MUST NOT create anything under claude_memory_path"
