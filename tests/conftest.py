from pathlib import Path
from typing import AsyncIterator
import pytest

from cerebro import db
from cerebro.config import Settings


@pytest.fixture
def tmp_settings(tmp_path: Path) -> Settings:
    """Provide Settings configured to a temporary data directory."""
    return Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "test_cerebro.db",
        workspace_path=tmp_path / "workspace",
        agents_path=tmp_path / "agents",
        vault_path=tmp_path / "vault",
        claude_memory_path=tmp_path / "claude_memory_nonexistent",
    )


@pytest.fixture
async def test_db(tmp_settings: Settings) -> AsyncIterator[Settings]:
    """Provide an initialized and migrated database in a temporary directory."""
    from cerebro.api.app import app
    from cerebro.auth import TokenStore

    tmp_settings.ensure_dirs()
    await db.connect(db_path=tmp_settings.db_path)
    await db.migrate()
    app.state.token_store = TokenStore(tmp_settings.data_dir / ".secrets.env")
    try:
        yield tmp_settings
    finally:
        await db.close()
