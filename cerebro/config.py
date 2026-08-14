"""Cerebro v2 configuration."""

from dataclasses import dataclass
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _get_env(key: str, default: str) -> str:
    return os.environ.get(f"CEREBRO_{key.upper()}", default)


def _get_env_int(key: str, default: int) -> int:
    val = os.environ.get(f"CEREBRO_{key.upper()}")
    return int(val) if val is not None else default


def _get_env_float(key: str, default: float) -> float:
    val = os.environ.get(f"CEREBRO_{key.upper()}")
    return float(val) if val is not None else default


def _get_env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(f"CEREBRO_{key.upper()}")
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _get_env_path(key: str, default: Path) -> Path:
    val = os.environ.get(f"CEREBRO_{key.upper()}")
    return Path(val) if val is not None else default


@dataclass(frozen=True)
class Settings:
    host: str = _get_env("HOST", "127.0.0.1")
    port: int = _get_env_int("PORT", 8765)
    data_dir: Path = _get_env_path("DATA_DIR", REPO_ROOT / "data")
    db_path: Path = _get_env_path(
        "DB_PATH",
        _get_env_path("DATA_DIR", REPO_ROOT / "data") / "cerebro.db",
    )
    vault_path: Path = _get_env_path(
        "VAULT_PATH",
        Path("D:/Obsidian/MyVault/Cerebro"),
    )
    claude_memory_path: Path = _get_env_path(
        "CLAUDE_MEMORY_PATH",
        Path("D:/Obsidian/MyVault/Claude Memory"),
    )
    workspace_path: Path = _get_env_path("WORKSPACE_PATH", REPO_ROOT / "workspace")
    agents_path: Path = _get_env_path("AGENTS_PATH", REPO_ROOT / "agents")
    lmstudio_base_url: str = _get_env("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234")
    lmstudio_concurrency: int = _get_env_int("LMSTUDIO_CONCURRENCY", 2)
    gemini_concurrency: int = _get_env_int("GEMINI_CONCURRENCY", 4)
    moderator_model: str = _get_env("MODERATOR_MODEL", "")
    moderator_window: int = _get_env_int("MODERATOR_WINDOW", 12)
    max_auto_speakers: int = _get_env_int("MAX_AUTO_SPEAKERS", 2)
    history_window: int = _get_env_int("HISTORY_WINDOW", 30)
    context_budget: int = _get_env_int("CONTEXT_BUDGET", 24000)
    max_depth: int = _get_env_int("MAX_DEPTH", 8)
    max_agent_messages_per_turn: int = _get_env_int("MAX_AGENT_MESSAGES_PER_TURN", 12)
    max_turn_wallclock_s: int = _get_env_int("MAX_TURN_WALLCLOCK_S", 600)
    max_tool_iterations: int = _get_env_int("MAX_TOOL_ITERATIONS", 12)
    max_self_initiated_per_hour: int = _get_env_int("MAX_SELF_INITIATED_PER_HOUR", 6)
    daily_usd_budget: float = _get_env_float("DAILY_USD_BUDGET", 5.0)
    daily_delegations: int = _get_env_int("DAILY_DELEGATIONS", 3)
    debug: bool = _get_env_bool("DEBUG", False)

    def ensure_dirs(self) -> None:
        """
        Creates data_dir and its journal/ subdirectory.
        MUST NOT create anything under claude_memory_path.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "journal").mkdir(parents=True, exist_ok=True)


settings = Settings()
