from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dnd_dm_assistant.domain.campaign_state import (
    CampaignState,
    StateNotFoundError,
)
from dnd_dm_assistant.domain.state_ports import CampaignStateGateway

NotFoundError = StateNotFoundError


class CampaignService:
    """Thin use-case layer; persistence and transactions are supplied by a gateway."""

    def __init__(self, gateway: CampaignStateGateway) -> None:
        self._gateway = gateway

    def create(
        self,
        entity_type: str,
        data: dict[str, Any],
        *,
        campaign_id: str | None = None,
        request_id: str = "unknown",
    ) -> dict[str, Any]:
        return self._gateway.create(
            entity_type, data, campaign_id=campaign_id, request_id=request_id
        )

    def get(
        self, entity_type: str, entity_id: str, *, campaign_id: str | None = None
    ) -> dict[str, Any]:
        return self._gateway.get(entity_type, entity_id, campaign_id=campaign_id)

    def list(
        self,
        entity_type: str,
        *,
        campaign_id: str | None,
        limit: int = 100,
        offset: int = 0,
        open_only: bool = False,
        parent_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        return self._gateway.list(
            entity_type,
            campaign_id=campaign_id,
            limit=limit,
            offset=offset,
            open_only=open_only,
            parent_id=parent_id,
        )

    def update(
        self,
        entity_type: str,
        entity_id: str,
        data: dict[str, Any],
        *,
        campaign_id: str | None = None,
        expected_version: int,
        request_id: str = "unknown",
    ) -> dict[str, Any]:
        return self._gateway.update(
            entity_type,
            entity_id,
            data,
            campaign_id=campaign_id,
            expected_version=expected_version,
            request_id=request_id,
        )

    def delete(
        self,
        entity_type: str,
        entity_id: str,
        *,
        campaign_id: str | None = None,
        expected_version: int,
        request_id: str = "unknown",
    ) -> None:
        self._gateway.delete(
            entity_type,
            entity_id,
            campaign_id=campaign_id,
            expected_version=expected_version,
            request_id=request_id,
        )

    def state(self, campaign_id: str, *, limit: int = 100) -> CampaignState:
        return self._gateway.state(campaign_id, limit=limit)

    def export_backup(self, campaign_id: str) -> dict[str, Any]:
        exporter = getattr(self._gateway, "export_campaign_backup", None)
        if callable(exporter):
            return exporter(campaign_id)
        campaign = self.get("campaign", campaign_id)
        return {
            "schema_version": "1.0",
            "exported_at": datetime.now(UTC),
            "campaign": campaign,
            "characters": self.list("character", campaign_id=campaign_id, limit=200),
            "conditions": self.list("condition", campaign_id=campaign_id, limit=200),
            "npcs": self.list("npc", campaign_id=campaign_id, limit=200),
            "locations": self.list("location", campaign_id=campaign_id, limit=200),
            "connections": self.list("connection", campaign_id=campaign_id, limit=200),
            "quests": self.list("quest", campaign_id=campaign_id, limit=200),
            "clues": self.list("clue", campaign_id=campaign_id, limit=200),
            "events": self.list("event", campaign_id=campaign_id, limit=200),
            "combats": self.list("combat", campaign_id=campaign_id, limit=200),
            "combatants": self.list("combatant", campaign_id=campaign_id, limit=200),
            "world_items": self.list("world_item", campaign_id=campaign_id, limit=500),
            "monsters": self.list("monster", campaign_id=campaign_id, limit=500),
            "scenes": self.list("scene", campaign_id=campaign_id, limit=200),
            "scene_participants": self.list(
                "scene_participant", campaign_id=campaign_id, limit=500
            ),
        }

    def import_backup(
        self,
        backup: dict[str, Any],
        *,
        name: str | None = None,
        request_id: str = "unknown",
    ) -> dict[str, Any]:
        importer = getattr(self._gateway, "import_campaign_backup", None)
        if (
            str(backup.get("schema_version")) == "2.0"
            and backup.get("tables")
            and callable(importer)
        ):
            return importer(backup, name=name, request_id=request_id)
        source_campaign = dict(backup["campaign"])
        source_campaign["name"] = name or f"{source_campaign.get('name', '导入战役')}（导入）"
        source_location_id = source_campaign.pop("current_location_id", None)
        campaign = self.create(
            "campaign",
            self._clean_import_values(source_campaign),
            request_id=request_id,
        )
        campaign_id = str(campaign["id"])
        mappings: dict[str, dict[str, str]] = {
            "location": {},
            "character": {},
            "quest": {},
            "event": {},
            "combat": {},
            "npc": {},
            "monster": {},
            "scene": {},
        }

        def copy_rows(entity_type: str, rows: list[dict[str, Any]]) -> None:
            for source in rows:
                old_id = str(source.get("id", ""))
                values = self._clean_import_values(source)
                if entity_type == "location":
                    values["parent_location_id"] = mappings["location"].get(
                        str(source.get("parent_location_id", ""))
                    )
                if entity_type in {"npc", "event"}:
                    values["location_id"] = mappings["location"].get(
                        str(source.get("location_id", ""))
                    )
                if entity_type == "scene":
                    values["location_id"] = mappings["location"].get(
                        str(source.get("location_id", ""))
                    )
                if entity_type == "combat":
                    values["scene_id"] = mappings["scene"].get(
                        str(source.get("scene_id", ""))
                    )
                if entity_type == "clue":
                    values["quest_id"] = mappings["quest"].get(str(source.get("quest_id", "")))
                    values["source_event_id"] = mappings["event"].get(
                        str(source.get("source_event_id", ""))
                    )
                created = self.create(
                    entity_type,
                    values,
                    campaign_id=campaign_id,
                    request_id=request_id,
                )
                if entity_type in mappings and old_id:
                    mappings[entity_type][old_id] = str(created["id"])

        copy_rows(
            "location",
            sorted(
                list(backup.get("locations", [])),
                key=lambda row: (int(row.get("depth", 1)), str(row.get("id", ""))),
            ),
        )
        copy_rows("character", list(backup.get("characters", [])))
        copy_rows("npc", list(backup.get("npcs", [])))
        copy_rows("monster", list(backup.get("monsters", [])))
        copy_rows("quest", list(backup.get("quests", [])))
        copy_rows("event", list(backup.get("events", [])))
        copy_rows("clue", list(backup.get("clues", [])))
        copy_rows("scene", list(backup.get("scenes", [])))
        copy_rows("combat", list(backup.get("combats", [])))

        for source in backup.get("world_items", []):
            values = self._clean_import_values(source)
            values["location_id"] = mappings["location"].get(
                str(source.get("location_id", ""))
            )
            values["owner_character_id"] = mappings["character"].get(
                str(source.get("owner_character_id", ""))
            )
            self.create(
                "world_item", values, campaign_id=campaign_id, request_id=request_id
            )

        for source in backup.get("conditions", []):
            character_id = mappings["character"].get(str(source.get("character_id", "")))
            if character_id:
                values = self._clean_import_values(source)
                values["character_id"] = character_id
                self.create(
                    "condition", values, campaign_id=campaign_id, request_id=request_id
                )
        for source in backup.get("connections", []):
            from_id = mappings["location"].get(str(source.get("from_location_id", "")))
            to_id = mappings["location"].get(str(source.get("to_location_id", "")))
            if from_id and to_id:
                values = self._clean_import_values(source)
                values.update({"from_location_id": from_id, "to_location_id": to_id})
                self.create(
                    "connection", values, campaign_id=campaign_id, request_id=request_id
                )
        for source in backup.get("combatants", []):
            combat_id = mappings["combat"].get(str(source.get("combat_id", "")))
            if combat_id:
                values = self._clean_import_values(source)
                values["combat_id"] = combat_id
                source_type = str(source.get("entity_type", ""))
                if source_type in mappings and source.get("entity_id"):
                    values["entity_id"] = mappings[source_type].get(
                        str(source.get("entity_id", ""))
                    )
                self.create(
                    "combatant", values, campaign_id=campaign_id, request_id=request_id
                )
        for source in backup.get("scene_participants", []):
            scene_id = mappings["scene"].get(str(source.get("scene_id", "")))
            source_type = str(source.get("entity_type", ""))
            entity_id = mappings.get(source_type, {}).get(
                str(source.get("entity_id", ""))
            )
            if scene_id and entity_id:
                values = self._clean_import_values(source)
                values.update({"scene_id": scene_id, "entity_id": entity_id})
                self.create(
                    "scene_participant",
                    values,
                    campaign_id=campaign_id,
                    request_id=request_id,
                )

        new_location_id = mappings["location"].get(str(source_location_id or ""))
        if new_location_id:
            campaign = self.update(
                "campaign",
                campaign_id,
                {"current_location_id": new_location_id},
                expected_version=int(campaign["version"]),
                request_id=request_id,
            )
        return campaign

    @staticmethod
    def _clean_import_values(source: dict[str, Any]) -> dict[str, Any]:
        excluded = {"id", "campaign_id", "created_at", "updated_at", "version"}
        values = {key: value for key, value in source.items() if key not in excluded}
        for key in ("current_time", "occurred_at", "started_at", "ended_at", "discovered_at"):
            value = values.get(key)
            if isinstance(value, str) and value:
                values[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return values
