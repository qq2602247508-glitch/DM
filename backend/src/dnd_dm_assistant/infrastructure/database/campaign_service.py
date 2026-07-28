from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, TypeVar

from sqlalchemy import delete as sa_delete
from sqlalchemy import update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import (
    CampaignState,
    StateNotFoundError,
    VersionConflict,
)
from dnd_dm_assistant.infrastructure.database.campaign_repository import (
    SqlAlchemyCampaignStateRepository,
)
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    AuditLog,
    Campaign,
    Character,
    CharacterCondition,
    Clue,
    Combat,
    CombatAction,
    Combatant,
    Event,
    Location,
    LocationConnection,
    MonsterInstance,
    Quest,
    Scene,
    SceneParticipant,
    WorldItem,
)

ModelT = TypeVar("ModelT")


ENTITY_MODELS: dict[str, type[Any]] = {
    "campaign": Campaign,
    "character": Character,
    "condition": CharacterCondition,
    "npc": NPC,
    "location": Location,
    "connection": LocationConnection,
    "quest": Quest,
    "clue": Clue,
    "event": Event,
    "combat": Combat,
    "combatant": Combatant,
    "world_item": WorldItem,
    "monster": MonsterInstance,
    "scene": Scene,
    "scene_participant": SceneParticipant,
}

NotFoundError = StateNotFoundError

ENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "campaign": (
        "name",
        "description",
        "world_setting",
        "current_time",
        "current_location_id",
        "status",
        "ruleset",
        "primary_rules_year",
        "allow_legacy",
        "encumbrance_mode",
    ),
    "character": (
        "name",
        "race",
        "background",
        "class_name",
        "level",
        "experience",
        "armor_class",
        "speed",
        "ability_scores",
        "hp",
        "max_hp",
        "max_hp_reduction",
        "ability_score_reductions",
        "death_saves",
        "inventory",
        "equipment",
        "proficiencies",
        "skills",
        "features",
        "actions",
        "resources",
        "spells",
        "spellcasting",
        "class_levels",
        "subclass_choices",
        "notes",
    ),
    "npc": (
        "name",
        "description",
        "alignment",
        "attitude",
        "personality",
        "goal",
        "fear",
        "armor_class",
        "hp",
        "max_hp",
        "speed",
        "ability_scores",
        "challenge_rating",
        "actions",
        "equipment",
        "relationship",
        "secrets",
        "known_information",
        "location_id",
        "status",
    ),
    "location": (
        "name",
        "parent_location_id",
        "depth",
        "description",
        "interactive_objects",
        "secrets",
        "discovered",
        "notes",
    ),
    "quest": (
        "name",
        "description",
        "quest_type",
        "giver",
        "reward",
        "xp_reward",
        "xp_awarded",
        "status",
        "notes",
    ),
    "clue": (
        "name",
        "description",
        "player_text",
        "dm_truth",
        "verified",
        "discovered",
        "discovered_at",
        "source_event_id",
        "quest_id",
    ),
    "event": (
        "event_type",
        "title",
        "description",
        "occurred_at",
        "location_id",
        "visibility",
        "metadata_json",
    ),
    "combat": (
        "scene_id",
        "name",
        "status",
        "round_number",
        "current_turn_index",
        "difficulty",
        "base_xp",
        "difficulty_adjustments",
        "xp_awarded",
        "started_at",
        "ended_at",
    ),
    "combatant": (
        "combat_id",
        "entity_type",
        "entity_id",
        "display_name",
        "initiative",
        "armor_class",
        "hp",
        "max_hp",
        "temporary_hp",
        "max_hp_reduction",
        "damage_resistances",
        "damage_vulnerabilities",
        "damage_immunities",
        "condition_immunities",
        "conditions",
        "concentration",
        "speed_ft",
        "movement_remaining_ft",
        "action_available",
        "bonus_action_available",
        "reaction_available",
        "snapshot_json",
        "is_active",
    ),
    "condition": ("character_id", "condition_name", "source", "duration", "notes", "details"),
    "connection": ("from_location_id", "to_location_id", "label", "travel_time", "bidirectional"),
    "world_item": (
        "name",
        "description",
        "category",
        "quantity",
        "unit_weight_lb",
        "price_cp",
        "source_record_id",
        "source_label",
        "location_id",
        "owner_character_id",
        "is_equipped",
        "is_hidden",
        "metadata_json",
    ),
    "monster": (
        "name",
        "source_record_id",
        "source_name",
        "armor_class",
        "hp",
        "max_hp",
        "speed",
        "ability_scores",
        "challenge_rating",
        "actions",
        "notes",
    ),
    "scene": ("location_id", "name", "description", "status", "notes"),
    "scene_participant": (
        "scene_id",
        "entity_type",
        "entity_id",
        "role",
        "visible",
        "notes",
    ),
}


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def serialize(entity: Any) -> dict[str, Any]:
    fields = ["id", "created_at", "updated_at", "version"]
    fields += [column.name for column in entity.__table__.columns if column.name not in fields]
    return {
        field: _json_value(getattr(entity, field)) for field in fields if hasattr(entity, field)
    }


class SqlAlchemyCampaignStateGateway:
    """Transactional application boundary for all structured campaign state."""

    def __init__(self, engine: Engine, *, actor: str = "dm") -> None:
        self.engine = engine
        self.actor = actor

    def _audit(
        self,
        session: Session,
        *,
        campaign_id: str | None,
        action: str,
        entity_type: str,
        entity_id: str | None,
        before: Any,
        after: Any,
        request_id: str,
    ) -> None:
        session.add(
            AuditLog(
                campaign_id=campaign_id,
                actor=self.actor,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                before_json=None
                if before is None
                else serialize(before)
                if hasattr(before, "__table__")
                else before,
                after_json=None
                if after is None
                else serialize(after)
                if hasattr(after, "__table__")
                else after,
                request_id=request_id,
            )
        )

    def _resolve_campaign_id(self, session: Session, entity_type: str, entity: Any) -> str | None:
        return SqlAlchemyCampaignStateRepository(session).campaign_id_for(entity_type, entity)

    def create(
        self,
        entity_type: str,
        data: dict[str, Any],
        *,
        campaign_id: str | None = None,
        request_id: str = "unknown",
    ) -> Any:
        model = ENTITY_MODELS[entity_type]
        with Session(self.engine) as session, session.begin():
            if campaign_id is not None and entity_type == "campaign":
                raise ValueError("campaign_id is not accepted when creating a campaign")
            if entity_type != "campaign":
                self._ensure_campaign(session, campaign_id or "")
                data = self._with_parent(entity_type, data, campaign_id or "")
                self._ensure_related_scope(session, entity_type, data, campaign_id or "")
            values = {field: data[field] for field in ENTITY_FIELDS[entity_type] if field in data}
            if entity_type in {
                "character",
                "npc",
                "location",
                "quest",
                "clue",
                "event",
                "combat",
                "world_item",
                "monster",
                "scene",
            }:
                values["campaign_id"] = campaign_id
            if entity_type == "campaign" and data.get("current_location_id"):
                raise NotFoundError("current location must be assigned after campaign creation")
            entity = model(**values)
            session.add(entity)
            session.flush()
            self._audit(
                session,
                campaign_id=self._resolve_campaign_id(session, entity_type, entity),
                action="create",
                entity_type=entity_type,
                entity_id=entity.id,
                before=None,
                after=entity,
                request_id=request_id,
            )
            session.flush()
            return serialize(entity)

    def get(self, entity_type: str, entity_id: str, *, campaign_id: str | None = None) -> Any:
        with Session(self.engine) as session:
            entity = SqlAlchemyCampaignStateRepository(session).get(
                entity_type, entity_id, campaign_id
            )
            if entity is None:
                raise NotFoundError(f"{entity_type} not found")
            return serialize(entity)

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
        with Session(self.engine) as session:
            rows = SqlAlchemyCampaignStateRepository(session).list(
                entity_type,
                campaign_id,
                limit=limit,
                offset=offset,
                open_only=open_only,
                parent_id=parent_id,
            )
            return tuple(serialize(item) for item in rows)

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
        model = ENTITY_MODELS[entity_type]
        with Session(self.engine) as session, session.begin():
            entity = SqlAlchemyCampaignStateRepository(session).get(
                entity_type, entity_id, campaign_id
            )
            if entity is None:
                raise NotFoundError(f"{entity_type} not found")
            actual = int(entity.version)
            if actual != expected_version:
                raise VersionConflict(entity_type, entity_id, expected_version, actual)
            before = serialize(entity)
            values = {field: data[field] for field in ENTITY_FIELDS[entity_type] if field in data}
            if entity_type != "campaign":
                self._ensure_related_scope(
                    session,
                    entity_type,
                    values,
                    campaign_id or self._resolve_campaign_id(session, entity_type, entity) or "",
                )
            elif values.get("current_location_id"):
                location = session.get(Location, values["current_location_id"])
                if location is None or location.campaign_id != entity_id:
                    raise NotFoundError("location not found in campaign")
            values["version"] = expected_version + 1
            values["updated_at"] = datetime.now(UTC)
            result = session.execute(
                update(model)
                .where(model.id == entity_id, model.version == expected_version)
                .values(**values)
            )
            if getattr(result, "rowcount", None) != 1:
                raise VersionConflict(entity_type, entity_id, expected_version, actual)
            session.refresh(entity)
            if entity_type == "combatant":
                before_snapshot = before.get("snapshot_json")
                after_snapshot = entity.snapshot_json
                before_position = (
                    before_snapshot.get("grid_position")
                    if isinstance(before_snapshot, dict)
                    else None
                )
                after_position = (
                    after_snapshot.get("grid_position")
                    if isinstance(after_snapshot, dict)
                    else None
                )
                if (
                    isinstance(before_position, dict)
                    and isinstance(after_position, dict)
                    and before_position != after_position
                ):
                    combat = session.get(Combat, entity.combat_id)
                    if combat is not None:
                        spent_ft = max(
                            0,
                            int(before.get("movement_remaining_ft", 0))
                            - int(entity.movement_remaining_ft),
                        )
                        session.add(
                            CombatAction(
                                campaign_id=combat.campaign_id,
                                combat_id=combat.id,
                                actor_combatant_id=entity.id,
                                action_type="move",
                                target_combatant_ids=[entity.id],
                                request_json={
                                    "action_name": "移动",
                                    "from_position": before_position,
                                    "to_position": after_position,
                                    "movement_spent_ft": spent_ft,
                                },
                                result_json={
                                    "from_position": before_position,
                                    "to_position": after_position,
                                    "movement_remaining_ft": entity.movement_remaining_ft,
                                },
                                explanation="战斗地图移动已公开同步",
                                round_number=combat.round_number,
                                turn_index=combat.current_turn_index,
                                summary=(
                                    f"{entity.display_name} 从"
                                    f"（{before_position.get('row')},{before_position.get('col')}）"
                                    f"移动到（{after_position.get('row')},{after_position.get('col')}）"
                                    f"；消耗 {spent_ft} 尺移动力"
                                ),
                                idempotency_key=(
                                    f"combatant-move:{entity.id}:{expected_version}"
                                ),
                                status="confirmed",
                            )
                        )
            self._audit(
                session,
                campaign_id=self._resolve_campaign_id(session, entity_type, entity),
                action="update",
                entity_type=entity_type,
                entity_id=entity_id,
                before=before,
                after=entity,
                request_id=request_id,
            )
            session.flush()
            return serialize(entity)

    def delete(
        self,
        entity_type: str,
        entity_id: str,
        *,
        campaign_id: str | None = None,
        expected_version: int,
        request_id: str = "unknown",
    ) -> None:
        model = ENTITY_MODELS[entity_type]
        with Session(self.engine) as session, session.begin():
            entity = SqlAlchemyCampaignStateRepository(session).get(
                entity_type, entity_id, campaign_id
            )
            if entity is None:
                raise NotFoundError(f"{entity_type} not found")
            if int(entity.version) != expected_version:
                raise VersionConflict(entity_type, entity_id, expected_version, int(entity.version))
            before = serialize(entity)
            audit_campaign = self._resolve_campaign_id(session, entity_type, entity)
            # Campaign deletion retains a tombstone audit record via SET NULL FK.
            if entity_type == "campaign":
                audit_campaign = None
            result = session.execute(
                sa_delete(model).where(model.id == entity_id, model.version == expected_version)
            )
            if getattr(result, "rowcount", None) != 1:
                raise VersionConflict(entity_type, entity_id, expected_version, int(entity.version))
            self._audit(
                session,
                campaign_id=audit_campaign,
                action="delete",
                entity_type=entity_type,
                entity_id=entity_id,
                before=before,
                after=None,
                request_id=request_id,
            )

    def state(self, campaign_id: str, *, limit: int = 100) -> CampaignState:
        campaign = self.get("campaign", campaign_id)
        now = datetime.now(UTC)
        return CampaignState(
            campaign=campaign,
            characters=self.list("character", campaign_id=campaign_id, limit=limit),
            npcs=self.list("npc", campaign_id=campaign_id, limit=limit),
            locations=self.list("location", campaign_id=campaign_id, limit=limit),
            quests=self.list("quest", campaign_id=campaign_id, limit=limit, open_only=True),
            open_clues=self.list("clue", campaign_id=campaign_id, limit=limit, open_only=True),
            active_combats=self.list(
                "combat", campaign_id=campaign_id, limit=limit, open_only=True
            ),
            as_of=now,
        )

    def _ensure_campaign(self, session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise NotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _with_parent(entity_type: str, data: dict[str, Any], campaign_id: str) -> dict[str, Any]:
        values = dict(data)
        if entity_type in {
            "character",
            "npc",
            "location",
            "quest",
            "clue",
            "event",
            "combat",
            "world_item",
            "monster",
            "scene",
        }:
            values["campaign_id"] = campaign_id
        return values

    def _ensure_related_scope(
        self, session: Session, entity_type: str, data: dict[str, Any], campaign_id: str
    ) -> None:
        if entity_type in {"npc", "event"} and data.get("location_id"):
            location = session.get(Location, data["location_id"])
            if location is None or location.campaign_id != campaign_id:
                raise NotFoundError("location not found in campaign")
        if entity_type == "location" and data.get("parent_location_id"):
            parent = session.get(Location, data["parent_location_id"])
            if parent is None or parent.campaign_id != campaign_id:
                raise NotFoundError("parent location not found in campaign")
            expected_depth = int(parent.depth) + 1
            if int(data.get("depth", expected_depth)) != expected_depth:
                raise ValueError("location depth must be parent depth + 1")
        if entity_type == "clue" and data.get("quest_id"):
            quest = session.get(Quest, data["quest_id"])
            if quest is None or quest.campaign_id != campaign_id:
                raise NotFoundError("quest not found in campaign")
        if entity_type == "condition" and data.get("character_id"):
            character = session.get(Character, data["character_id"])
            if character is None or character.campaign_id != campaign_id:
                raise NotFoundError("character not found in campaign")
        if entity_type == "combatant" and data.get("combat_id"):
            combat = session.get(Combat, data["combat_id"])
            if combat is None or combat.campaign_id != campaign_id:
                raise NotFoundError("combat not found in campaign")
        if entity_type == "combat" and data.get("scene_id"):
            scene = session.get(Scene, data["scene_id"])
            if scene is None or scene.campaign_id != campaign_id:
                raise NotFoundError("scene not found in campaign")
        if entity_type == "connection":
            for key in ("from_location_id", "to_location_id"):
                if key not in data:
                    continue
                location = session.get(Location, data[key])
                if location is None or location.campaign_id != campaign_id:
                    raise NotFoundError("location not found in campaign")
        if entity_type == "world_item":
            location_id = data.get("location_id")
            owner_id = data.get("owner_character_id")
            if location_id and owner_id:
                raise ValueError("item cannot have both location and owner")
            if location_id:
                location = session.get(Location, location_id)
                if location is None or location.campaign_id != campaign_id:
                    raise NotFoundError("location not found in campaign")
            if owner_id:
                character = session.get(Character, owner_id)
                if character is None or character.campaign_id != campaign_id:
                    raise NotFoundError("character not found in campaign")
        if entity_type == "scene" and data.get("location_id"):
            location = session.get(Location, data["location_id"])
            if location is None or location.campaign_id != campaign_id:
                raise NotFoundError("location not found in campaign")
        if entity_type == "scene_participant":
            scene = session.get(Scene, data.get("scene_id"))
            if scene is None or scene.campaign_id != campaign_id:
                raise NotFoundError("scene not found in campaign")
            participant_type = str(data.get("entity_type", ""))
            participant_id = str(data.get("entity_id", ""))
            if participant_type == "character":
                entity_campaign_id = getattr(
                    session.get(Character, participant_id), "campaign_id", None
                )
            elif participant_type == "npc":
                entity_campaign_id = getattr(
                    session.get(NPC, participant_id), "campaign_id", None
                )
            elif participant_type == "monster":
                entity_campaign_id = getattr(
                    session.get(MonsterInstance, participant_id), "campaign_id", None
                )
            else:
                entity_campaign_id = None
            if entity_campaign_id != campaign_id:
                label = participant_type or "participant"
                raise NotFoundError(f"{label} not found in campaign")
