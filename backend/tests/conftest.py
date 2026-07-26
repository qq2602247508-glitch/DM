from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
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
