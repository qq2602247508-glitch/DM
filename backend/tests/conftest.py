from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    path = tmp_path / "test.db"
    return Settings(
        environment="test",
        database_url=f"sqlite:///{path}",
        frontend_origin="http://127.0.0.1:5173",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def campaign_client(tmp_path: Path, monkeypatch: Any) -> Iterator[TestClient]:
    """A migrated database fixture for campaign-state integration tests."""
    database_url = f"sqlite:///{tmp_path / 'campaign.db'}"
    monkeypatch.setenv("DND_DM_DATABASE_URL", database_url)
    command.upgrade(Config("backend/alembic.ini"), "head")
    settings = Settings(environment="test", database_url=database_url)
    with TestClient(create_app(settings)) as test_client:
        test_client.database_url = database_url  # type: ignore[attr-defined]
        yield test_client
