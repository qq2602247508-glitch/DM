from __future__ import annotations

# ruff: noqa: E501
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.config import Settings


def test_recovery_point_and_read_only_mode_are_local_and_explicit(tmp_path: Path) -> None:
    database = tmp_path / "campaign.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database}",
        backup_directory=tmp_path / "backups",
    )
    with TestClient(create_app(settings)) as client:
        engine = client.app.state.database_engine
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE campaigns (id TEXT PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json JSON NOT NULL, reason TEXT, updated_at DATETIME)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE recovery_points (id TEXT PRIMARY KEY, label TEXT, kind TEXT, file_name TEXT, sha256 TEXT, size_bytes INTEGER, created_at DATETIME, created_by_request_id TEXT, preview_token TEXT, previewed_at DATETIME, restored_at DATETIME)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE audit_log (id TEXT PRIMARY KEY, campaign_id TEXT, actor TEXT, action TEXT, entity_type TEXT, entity_id TEXT, before_json JSON, after_json JSON, request_id TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
                )
            )
        assert (
            client.post("/api/v1/system/recovery-points", json={"label": "before-risk"}).status_code
            == 200
        )
        point = client.get("/api/v1/system/recovery-points").json()["items"][0]
        preview = client.post(f"/api/v1/system/recovery-points/{point['id']}/preview-restore")
        assert preview.status_code == 200
        assert "confirm_token" in preview.json()

        automatic = client.post("/api/v1/system/recovery-points/ensure-automatic")
        repeated = client.post("/api/v1/system/recovery-points/ensure-automatic")
        assert automatic.status_code == 200
        assert automatic.json()["created"] is True
        assert repeated.status_code == 200
        assert repeated.json()["created"] is False
        assert repeated.json()["id"] == automatic.json()["id"]
        assert len(client.get("/api/v1/system/recovery-points").json()["items"]) == 2

        assert (
            client.post(
                "/api/v1/system/safe-mode", json={"enabled": True, "reason": "investigating"}
            ).status_code
            == 200
        )
        blocked = client.post("/api/v1/campaigns", json={"name": "must not write"})
        assert blocked.status_code == 423
        assert blocked.json()["code"] == "read_only_safe_mode"
        assert (
            client.post(
                "/api/v1/system/safe-mode", json={"enabled": False, "reason": "resolved"}
            ).status_code
            == 200
        )
