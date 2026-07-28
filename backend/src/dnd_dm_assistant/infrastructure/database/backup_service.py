from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.infrastructure.database.models import AuditLog, Base, Campaign

# Authentication secrets, transient LAN-room state, audit history and model telemetry are
# deliberately not copied into a new campaign. Everything else is authoritative campaign
# state and must survive a single-campaign round trip.
EXCLUDED_TABLES = frozenset(
    {
        "system_metadata",
        "audit_log",
        "model_runs",
        "player_rooms",
        "player_sessions",
    }
)

BACKUP_TABLE_NAMES = tuple(
    sorted(
        table_name
        for table_name in Base.metadata.tables
        if table_name not in EXCLUDED_TABLES and table_name != "campaigns"
    )
)

LEGACY_FIELDS = {
    "characters": "characters",
    "character_conditions": "conditions",
    "npcs": "npcs",
    "locations": "locations",
    "location_connections": "connections",
    "quests": "quests",
    "clues": "clues",
    "events": "events",
    "combats": "combats",
    "combatants": "combatants",
    "world_items": "world_items",
    "monster_instances": "monsters",
    "scenes": "scenes",
    "scene_participants": "scene_participants",
}

UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)


def _mapped_classes() -> dict[str, type[Any]]:
    return {
        mapper.class_.__table__.name: mapper.class_
        for mapper in Base.registry.mappers
        if mapper.local_table is not None
    }


def _canonical_payload(campaign: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> bytes:
    return json.dumps(
        {"campaign": campaign, "tables": tables},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _checksum(campaign: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> str:
    return hashlib.sha256(_canonical_payload(campaign, tables)).hexdigest()


def _serialize_row(entity: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for attribute in entity.__mapper__.column_attrs:
        value = getattr(entity, attribute.key)
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            value = value.isoformat()
        result[attribute.key] = value
    return result


def _remap_json(value: Any, id_map: dict[str, str]) -> Any:
    if isinstance(value, str):
        mapped = id_map.get(value)
        if mapped is not None:
            return mapped
        return UUID_PATTERN.sub(lambda match: id_map.get(match.group(0), match.group(0)), value)
    if isinstance(value, list):
        return [_remap_json(item, id_map) for item in value]
    if isinstance(value, dict):
        return {
            id_map.get(str(key), str(key)): _remap_json(item, id_map)
            for key, item in value.items()
        }
    return value


class CampaignBackupStore:
    """Versioned, atomic backup/restore for all authoritative campaign-scoped tables."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.models = _mapped_classes()

    def export(self, campaign_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            campaign_json = _serialize_row(campaign)
            tables = self._campaign_rows(session, campaign_id)

        counts = {name: len(rows) for name, rows in tables.items()}
        digest = _checksum(campaign_json, tables)
        result: dict[str, Any] = {
            "schema_version": "2.0",
            "exported_at": datetime.now(UTC),
            "campaign": campaign_json,
            "manifest": {
                "format": "dnd-dm-campaign-backup",
                "source_campaign_id": campaign_id,
                "table_names": list(BACKUP_TABLE_NAMES),
                "excluded_tables": sorted(EXCLUDED_TABLES),
                "record_count": sum(counts.values()),
                "sha256": digest,
            },
            "counts": counts,
            "tables": tables,
        }
        # Keep the original top-level collections so older clients can still inspect a
        # v2 export. The authoritative v2 copy is `tables`.
        for table_name, field_name in LEGACY_FIELDS.items():
            result[field_name] = tables[table_name]
        return result

    def import_backup(
        self,
        backup: dict[str, Any],
        *,
        name: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        tables = {
            str(table_name): [dict(row) for row in rows]
            for table_name, rows in dict(backup.get("tables") or {}).items()
        }
        self._validate_v2(backup, tables)
        source_campaign = dict(backup["campaign"])
        source_campaign_id = str(source_campaign.get("id") or "")
        new_campaign_id = str(uuid.uuid4())

        row_id_maps: dict[str, dict[str, str]] = {
            table_name: {
                str(row["id"]): str(uuid.uuid4())
                for row in rows
                if row.get("id") is not None
            }
            for table_name, rows in tables.items()
        }
        global_id_map = {source_campaign_id: new_campaign_id}
        for mapping in row_id_maps.values():
            global_id_map.update(mapping)

        with Session(self.engine) as session, session.begin():
            campaign_values = self._row_values(
                Campaign, source_campaign, global_id_map, row_id_maps
            )
            source_location_id = campaign_values.pop("current_location_id", None)
            campaign_values.update(
                {
                    "id": new_campaign_id,
                    "name": name
                    or f"{source_campaign.get('name', '导入战役')}（导入）",
                    "current_location_id": None,
                    "created_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "version": 1,
                }
            )
            campaign = Campaign(**campaign_values)
            session.add(campaign)
            session.flush()

            pending = [
                (table_name, source)
                for table_name in BACKUP_TABLE_NAMES
                for source in tables.get(table_name, [])
            ]
            while pending:
                deferred: list[tuple[str, dict[str, Any]]] = []
                inserted = 0
                for table_name, source in pending:
                    model = self.models[table_name]
                    values = self._row_values(model, source, global_id_map, row_id_maps)
                    values["id"] = row_id_maps[table_name][str(source["id"])]
                    if "campaign_id" in model.__table__.c:
                        values["campaign_id"] = new_campaign_id
                    if not self._foreign_keys_ready(session, model, values):
                        deferred.append((table_name, source))
                        continue
                    session.add(model(**values))
                    session.flush()
                    inserted += 1
                if deferred and inserted == 0:
                    labels = ", ".join(
                        f"{table_name}:{source.get('id')}" for table_name, source in deferred[:8]
                    )
                    raise ValueError(f"backup contains unresolved relationships: {labels}")
                pending = deferred

            if source_location_id:
                campaign.current_location_id = str(source_location_id)
                campaign.version += 1
                campaign.updated_at = datetime.now(UTC)
            session.add(
                AuditLog(
                    campaign_id=new_campaign_id,
                    actor="dm",
                    action="import_backup",
                    entity_type="campaign",
                    entity_id=new_campaign_id,
                    before_json=None,
                    after_json={
                        "schema_version": "2.0",
                        "source_campaign_id": source_campaign_id,
                        "record_count": sum(len(rows) for rows in tables.values()),
                    },
                    request_id=request_id,
                )
            )
            session.flush()
            return _serialize_row(campaign)

    def _campaign_rows(
        self, session: Session, campaign_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        selected: dict[str, list[Any]] = {}
        selected_ids: dict[str, set[str]] = {}

        # Directly scoped tables form the roots of the ownership graph.
        for table_name in BACKUP_TABLE_NAMES:
            model = self.models[table_name]
            if "campaign_id" not in model.__table__.c:
                continue
            rows = list(
                session.scalars(
                    select(model)
                    .where(model.__table__.c.campaign_id == campaign_id)
                    .order_by(model.__table__.c.created_at, model.__table__.c.id)
                ).all()
            )
            selected[table_name] = rows
            selected_ids[table_name] = {str(row.id) for row in rows}

        # Tables without campaign_id are owned through their foreign-key parents.
        remaining = {
            table_name
            for table_name in BACKUP_TABLE_NAMES
            if "campaign_id" not in self.models[table_name].__table__.c
        }
        while remaining:
            progress = False
            for table_name in tuple(sorted(remaining)):
                model = self.models[table_name]
                parent_tables = {
                    foreign_key.column.table.name for foreign_key in model.__table__.foreign_keys
                }
                if not parent_tables or not parent_tables.issubset(selected_ids):
                    continue
                rows = []
                for row in session.scalars(
                    select(model).order_by(
                        model.__table__.c.created_at, model.__table__.c.id
                    )
                ).all():
                    foreign_values = [
                        (
                            foreign_key.column.table.name,
                            getattr(row, foreign_key.parent.key),
                            foreign_key.parent.nullable,
                        )
                        for foreign_key in model.__table__.foreign_keys
                    ]
                    if foreign_values and all(
                        value is None
                        or str(value) in selected_ids.get(parent_table, set())
                        or nullable
                        for parent_table, value, nullable in foreign_values
                    ) and any(
                        value is not None
                        and str(value) in selected_ids.get(parent_table, set())
                        for parent_table, value, _nullable in foreign_values
                    ):
                        rows.append(row)
                selected[table_name] = rows
                selected_ids[table_name] = {str(row.id) for row in rows}
                remaining.remove(table_name)
                progress = True
            if not progress:
                raise RuntimeError(
                    "backup ownership graph is incomplete: " + ", ".join(sorted(remaining))
                )

        return {
            table_name: [_serialize_row(row) for row in selected.get(table_name, [])]
            for table_name in BACKUP_TABLE_NAMES
        }

    @staticmethod
    def _validate_v2(
        backup: dict[str, Any], tables: dict[str, list[dict[str, Any]]]
    ) -> None:
        if str(backup.get("schema_version")) != "2.0":
            raise ValueError("database backup importer requires schema version 2.0")
        unknown = set(tables) - set(BACKUP_TABLE_NAMES)
        if unknown:
            raise ValueError("backup contains unsupported tables: " + ", ".join(sorted(unknown)))
        counts = {str(key): int(value) for key, value in dict(backup.get("counts") or {}).items()}
        actual_counts = {name: len(rows) for name, rows in tables.items()}
        if counts != actual_counts:
            raise ValueError("backup record counts do not match the payload")
        manifest = dict(backup.get("manifest") or {})
        if manifest.get("format") != "dnd-dm-campaign-backup":
            raise ValueError("unsupported backup manifest")
        if set(manifest.get("table_names") or ()) != set(tables):
            raise ValueError("backup manifest table list does not match the payload")
        if str(manifest.get("source_campaign_id") or "") != str(
            dict(backup["campaign"]).get("id") or ""
        ):
            raise ValueError("backup manifest campaign does not match the payload")
        if int(manifest.get("record_count", -1)) != sum(actual_counts.values()):
            raise ValueError("backup manifest record count does not match the payload")
        expected = str(manifest.get("sha256") or "")
        actual = _checksum(dict(backup["campaign"]), tables)
        if expected != actual:
            raise ValueError("backup checksum does not match the payload")

    @staticmethod
    def _row_values(
        model: type[Any],
        source: dict[str, Any],
        global_id_map: dict[str, str],
        row_id_maps: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        foreign_keys = {
            model.__mapper__.get_property_by_column(foreign_key.parent).key: foreign_key
            for foreign_key in model.__table__.foreign_keys
        }
        for attribute in model.__mapper__.column_attrs:
            key = attribute.key
            column = attribute.columns[0]
            if key == "id" or key not in source:
                continue
            value = source[key]
            foreign_key = foreign_keys.get(key)
            if foreign_key is not None and value is not None:
                target_table = foreign_key.column.table.name
                if target_table == "campaigns":
                    value = global_id_map.get(str(value))
                else:
                    value = row_id_maps.get(target_table, {}).get(str(value))
                    if value is None and not column.nullable:
                        raise ValueError(
                            f"{model.__table__.name}.{key} references data outside the backup"
                        )
            else:
                value = _remap_json(value, global_id_map)
            if isinstance(column.type, DateTime) and isinstance(value, str):
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            values[key] = value
        return values

    @staticmethod
    def _foreign_keys_ready(session: Session, model: type[Any], values: dict[str, Any]) -> bool:
        models = _mapped_classes()
        for foreign_key in model.__table__.foreign_keys:
            attribute_key = model.__mapper__.get_property_by_column(foreign_key.parent).key
            value = values.get(attribute_key)
            if value is None:
                continue
            target_model = models[foreign_key.column.table.name]
            if session.get(target_model, value) is None:
                return False
        return True
