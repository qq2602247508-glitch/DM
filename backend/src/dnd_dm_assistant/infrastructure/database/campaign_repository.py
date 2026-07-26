from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    AuditLog,
    Campaign,
    Character,
    CharacterCondition,
    Clue,
    Combat,
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
    "audit": AuditLog,
}


class SqlAlchemyCampaignStateRepository:
    """Campaign-scoped SQLAlchemy reads; transaction ownership stays in the service."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def campaign_id_for(self, entity_type: str, entity: Any) -> str | None:
        if entity_type == "campaign":
            return entity.id
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
            return entity.campaign_id
        if entity_type == "condition":
            character = self.session.get(Character, entity.character_id)
            return None if character is None else character.campaign_id
        if entity_type == "connection":
            location = self.session.get(Location, entity.from_location_id)
            return None if location is None else location.campaign_id
        if entity_type == "combatant":
            combat = self.session.get(Combat, entity.combat_id)
            return None if combat is None else combat.campaign_id
        if entity_type == "scene_participant":
            scene = self.session.get(Scene, entity.scene_id)
            return None if scene is None else scene.campaign_id
        return None

    def get(self, entity_type: str, entity_id: str, campaign_id: str | None) -> Any | None:
        entity = self.session.get(ENTITY_MODELS[entity_type], entity_id)
        if entity is None:
            return None
        if campaign_id is not None and entity_type != "campaign":
            if self.campaign_id_for(entity_type, entity) != campaign_id:
                return None
        return entity

    def list(
        self,
        entity_type: str,
        campaign_id: str | None,
        *,
        limit: int,
        offset: int,
        open_only: bool,
        parent_id: str | None,
    ) -> tuple[Any, ...]:
        model = ENTITY_MODELS[entity_type]
        query = select(model)
        if entity_type == "campaign":
            pass
        elif entity_type in {
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
            query = query.where(model.campaign_id == campaign_id)
        elif entity_type == "condition":
            query = query.join(Character).where(Character.campaign_id == campaign_id)
            if parent_id is not None:
                query = query.where(model.character_id == parent_id)
        elif entity_type == "connection":
            query = query.join(Location, Location.id == model.from_location_id).where(
                Location.campaign_id == campaign_id
            )
            if parent_id is not None:
                query = query.where(model.from_location_id == parent_id)
        elif entity_type == "combatant":
            query = query.join(Combat).where(Combat.campaign_id == campaign_id)
            if parent_id is not None:
                query = query.where(model.combat_id == parent_id)
        elif entity_type == "scene_participant":
            query = query.join(Scene).where(Scene.campaign_id == campaign_id)
            if parent_id is not None:
                query = query.where(model.scene_id == parent_id)
        if open_only and entity_type == "clue":
            query = query.where(model.discovered.is_(False))
        if open_only and entity_type == "combat":
            query = query.where(model.status == "active")
        query = query.order_by(model.created_at.asc(), model.id.asc()).offset(offset).limit(limit)
        return tuple(self.session.scalars(query).all())

    def campaign(self, campaign_id: str) -> Campaign | None:
        return self.session.get(Campaign, campaign_id)
