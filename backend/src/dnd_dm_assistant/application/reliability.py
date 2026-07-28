from __future__ import annotations

# ruff: noqa: E501
import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from dnd_dm_assistant.config import Settings


class ReliabilityError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ReliabilityService:
    """Local-only SQLite snapshots, safety mode and support diagnostics."""

    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    @property
    def _database_path(self) -> Path:
        prefix = "sqlite:///"
        if not self._settings.database_url.startswith(prefix):
            raise ReliabilityError("SQLite backups require a local sqlite:/// database URL")
        raw = self._settings.database_url.removeprefix(prefix)
        if raw == ":memory:":
            raise ReliabilityError("in-memory databases do not have durable recovery points")
        return Path(raw).expanduser().resolve()

    def _available(self) -> bool:
        with self._engine.connect() as connection:
            return (
                connection.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='system_settings'"
                    )
                ).scalar()
                is not None
            )

    def is_read_only(self) -> bool:
        if not self._available():
            return self._settings.read_only_safe_mode
        with self._engine.connect() as connection:
            value = connection.execute(
                text("SELECT value_json FROM system_settings WHERE key='read_only_safe_mode'")
            ).scalar()
        return (
            self._settings.read_only_safe_mode or bool(json.loads(value))
            if value
            else self._settings.read_only_safe_mode
        )

    def set_read_only(self, enabled: bool, reason: str, request_id: str) -> dict[str, Any]:
        if enabled and not reason.strip():
            raise ReliabilityError("a reason is required to enable read-only safe mode")
        if not self._available():
            raise ReliabilityError("database has not been migrated for reliability settings")
        value = json.dumps(bool(enabled))
        with self._engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO system_settings (key, value_json, reason, updated_at)
                VALUES ('read_only_safe_mode', :value, :reason, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET value_json=:value, reason=:reason, updated_at=CURRENT_TIMESTAMP
            """),
                {"value": value, "reason": reason.strip() or "DM disabled safe mode"},
            )
            connection.execute(
                text("""
                INSERT INTO audit_log (id, campaign_id, actor, action, entity_type, entity_id, before_json, after_json, request_id)
                VALUES (:id, NULL, 'dm', 'safe_mode_change', 'system_setting', 'read_only_safe_mode', NULL, :after, :request_id)
            """),
                {
                    "id": secrets.token_hex(16),
                    "after": json.dumps({"enabled": enabled, "reason": reason.strip()}),
                    "request_id": request_id,
                },
            )
        return {"enabled": enabled, "reason": reason.strip() or None}

    def create_backup(self, label: str, request_id: str, kind: str = "manual") -> dict[str, Any]:
        source = self._database_path
        if not source.exists():
            raise ReliabilityError("SQLite database does not exist yet")
        directory = self._settings.backup_directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        created = _now()
        point_id = secrets.token_hex(16)
        target = directory / f"{created[:10]}-{point_id}.sqlite3"
        # sqlite backup API yields a transactionally consistent copy even while WAL is active.
        with (
            sqlite3.connect(source) as source_connection,
            sqlite3.connect(target) as target_connection,
        ):
            source_connection.backup(target_connection)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        payload = {
            "id": point_id,
            "label": label.strip() or "未命名恢复点",
            "kind": kind,
            "path": target.name,
            "sha256": digest,
            "size_bytes": target.stat().st_size,
            "created_at": created,
        }
        with self._engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO recovery_points (id, label, kind, file_name, sha256, size_bytes, created_at, created_by_request_id)
                VALUES (:id, :label, :kind, :path, :sha256, :size_bytes, :created_at, :request_id)
            """),
                {**payload, "request_id": request_id},
            )
            connection.execute(
                text("""
                INSERT INTO audit_log (id, campaign_id, actor, action, entity_type, entity_id, before_json, after_json, request_id)
                VALUES (:id, NULL, 'system', 'backup_create', 'recovery_point', :point_id, NULL, :after, :request_id)
            """),
                {
                    "id": secrets.token_hex(16),
                    "point_id": point_id,
                    "after": json.dumps(payload),
                    "request_id": request_id,
                },
            )
        return payload

    def ensure_automatic_backup(
        self,
        request_id: str,
        *,
        minimum_interval: timedelta = timedelta(hours=24),
    ) -> dict[str, Any]:
        """Create at most one startup recovery point per interval.

        The check and snapshot are intentionally kept server-side so every
        launcher follows the same policy and a browser refresh cannot create a
        pile of backups. Existing recovery points are never removed here.
        """
        if minimum_interval.total_seconds() <= 0:
            raise ReliabilityError("automatic backup interval must be positive")
        if not self._available():
            raise ReliabilityError("database has not been migrated for recovery points")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT id, label, kind, file_name, sha256, size_bytes, created_at "
                        "FROM recovery_points WHERE kind='automatic_startup' "
                        "ORDER BY created_at DESC, id DESC LIMIT 1"
                    )
                )
                .mappings()
                .first()
            )
        if row is not None:
            raw_created = row["created_at"]
            created_at = (
                raw_created
                if isinstance(raw_created, datetime)
                else datetime.fromisoformat(str(raw_created).replace("Z", "+00:00"))
            )
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - created_at < minimum_interval:
                return {**dict(row), "created": False}
        point = self.create_backup(
            "每日启动自动恢复点",
            request_id,
            kind="automatic_startup",
        )
        return {**point, "created": True}

    def list_recovery_points(self) -> list[dict[str, Any]]:
        if not self._available():
            return []
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT id, label, kind, file_name, sha256, size_bytes, created_at FROM recovery_points ORDER BY created_at DESC, id DESC LIMIT 100"
                    )
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def preview_restore(self, point_id: str) -> dict[str, Any]:
        point = self._point(point_id)
        source = self._settings.backup_directory.resolve() / str(point["file_name"])
        if (
            not source.is_file()
            or hashlib.sha256(source.read_bytes()).hexdigest() != point["sha256"]
        ):
            raise ReliabilityError("recovery point is missing or its checksum no longer matches")
        with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as connection:
            campaigns = int(connection.execute("SELECT count(*) FROM campaigns").fetchone()[0])
            tables = int(
                connection.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
            )
        token = secrets.token_urlsafe(32)
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE recovery_points SET preview_token=:token, previewed_at=CURRENT_TIMESTAMP WHERE id=:id"
                ),
                {"token": token, "id": point_id},
            )
        return {
            "recovery_point_id": point_id,
            "label": point["label"],
            "campaigns": campaigns,
            "tables": tables,
            "confirm_token": token,
            "warning": "恢复会替换当前 SQLite 数据库；系统会先创建一个自动恢复点。",
        }

    def confirm_restore(
        self, point_id: str, token: str, confirmation: str, request_id: str
    ) -> dict[str, Any]:
        if confirmation != "RESTORE":
            raise ReliabilityError("confirmation must exactly equal RESTORE")
        point = self._point(point_id)
        if not secrets.compare_digest(str(point.get("preview_token") or ""), token):
            raise ReliabilityError("restore preview has expired or was not confirmed")
        automatic = self.create_backup(
            f"恢复 {point['label']} 前的自动备份", request_id, kind="pre_restore"
        )
        source = self._settings.backup_directory.resolve() / str(point["file_name"])
        destination = self._database_path
        # Copy into the live DB with SQLite's backup API. No filesystem replace means open
        # connections remain valid; disposing the engine forces later requests to reconnect.
        with (
            sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_connection,
            sqlite3.connect(destination) as destination_connection,
        ):
            source_connection.backup(destination_connection)
        self._engine.dispose()
        with self._engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE recovery_points SET restored_at=CURRENT_TIMESTAMP, preview_token=NULL WHERE id=:id"
                ),
                {"id": point_id},
            )
            connection.execute(
                text("""
                INSERT INTO audit_log (id, campaign_id, actor, action, entity_type, entity_id, before_json, after_json, request_id)
                VALUES (:id, NULL, 'dm', 'restore_confirmed', 'recovery_point', :point_id, :before, :after, :request_id)
            """),
                {
                    "id": secrets.token_hex(16),
                    "point_id": point_id,
                    "before": json.dumps({"automatic_backup_id": automatic["id"]}),
                    "after": json.dumps({"restored": True}),
                    "request_id": request_id,
                },
            )
        return {
            "restored": True,
            "recovery_point_id": point_id,
            "automatic_backup_id": automatic["id"],
        }

    def _point(self, point_id: str) -> dict[str, Any]:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text("SELECT * FROM recovery_points WHERE id=:id"), {"id": point_id}
                )
                .mappings()
                .first()
            )
        if row is None:
            raise ReliabilityError("recovery point was not found")
        return dict(row)

    def audit(self, campaign_id: str | None, limit: int, offset: int) -> dict[str, Any]:
        where = "campaign_id = :campaign_id" if campaign_id else "1 = 1"
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if campaign_id:
            params["campaign_id"] = campaign_id
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        f"SELECT id, campaign_id, actor, action, entity_type, entity_id, before_json, after_json, request_id, created_at FROM audit_log WHERE {where} ORDER BY created_at DESC, id DESC LIMIT :limit OFFSET :offset"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        return {"items": [dict(row) for row in rows], "limit": limit, "offset": offset}

    def list_house_rules(self, campaign_id: str) -> list[dict[str, Any]]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT * FROM house_rule_overrides WHERE campaign_id=:campaign_id ORDER BY created_at DESC, id DESC"
                    ),
                    {"campaign_id": campaign_id},
                )
                .mappings()
                .all()
            )
        return [dict(row) for row in rows]

    def save_house_rule(
        self, campaign_id: str, data: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        rule_key = str(data["rule_key"]).strip()
        reason = str(data["reason"]).strip()
        source = str(data["source"]).strip()
        if not rule_key or not reason or not source:
            raise ReliabilityError("house-rule overrides require a rule key, source, and reason")
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    text(
                        "SELECT id, core_value_json, override_value_json, reason, source, enabled FROM house_rule_overrides WHERE campaign_id=:campaign_id AND rule_key=:rule_key"
                    ),
                    {"campaign_id": campaign_id, "rule_key": rule_key},
                )
                .mappings()
                .first()
            )
            identifier = str(existing["id"]) if existing else secrets.token_hex(16)
            values = {
                "id": identifier,
                "campaign_id": campaign_id,
                "rule_key": rule_key,
                "core": json.dumps(data["core_value"]),
                "override": json.dumps(data["override_value"]),
                "reason": reason,
                "source": source,
                "enabled": bool(data.get("enabled", True)),
            }
            connection.execute(
                text("""
                INSERT INTO house_rule_overrides (id, campaign_id, rule_key, core_value_json, override_value_json, reason, source, enabled)
                VALUES (:id, :campaign_id, :rule_key, :core, :override, :reason, :source, :enabled)
                ON CONFLICT(campaign_id, rule_key) DO UPDATE SET core_value_json=:core, override_value_json=:override, reason=:reason, source=:source, enabled=:enabled, updated_at=CURRENT_TIMESTAMP, version=house_rule_overrides.version+1
            """),
                values,
            )
            after = {
                "rule_key": rule_key,
                "core_value": data["core_value"],
                "override_value": data["override_value"],
                "reason": reason,
                "source": source,
                "enabled": values["enabled"],
            }
            connection.execute(
                text("""INSERT INTO audit_log (id, campaign_id, actor, action, entity_type, entity_id, before_json, after_json, request_id)
                VALUES (:id, :campaign_id, 'dm', 'house_rule_override', 'house_rule_override', :entity_id, :before, :after, :request_id)"""),
                {
                    "id": secrets.token_hex(16),
                    "campaign_id": campaign_id,
                    "entity_id": identifier,
                    "before": json.dumps(dict(existing) if existing else None),
                    "after": json.dumps(after),
                    "request_id": request_id,
                },
            )
        return {"id": identifier, **after}

    def diagnostics(
        self, index: dict[str, Any] | None, models: dict[str, Any] | None
    ) -> dict[str, Any]:
        database: dict[str, Any]
        try:
            with self._engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                connection.execute(text("PRAGMA quick_check")).scalar()
            database = {"available": True, "reason": None, "migration_revision": revision}
        except Exception as exc:  # diagnostics must report instead of failing the entire page
            database = {"available": False, "reason": str(exc), "migration_revision": None}
        return {
            "database": database,
            "read_only_safe_mode": self.is_read_only(),
            "backups_directory": str(self._settings.backup_directory),
            "index": index,
            "models": models,
        }
