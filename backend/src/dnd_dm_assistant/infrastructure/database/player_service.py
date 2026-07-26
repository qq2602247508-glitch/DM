# ruff: noqa: E501, E701, E702

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    AuditLog,
    Campaign,
    Character,
    Combat,
    Combatant,
    Event,
    Handout,
    PlayerActionRequest,
    Scene,
    SceneGrid,
    SceneObject,
    SceneToken,
)


class PlayerService:
    """Separate read boundary for player-safe projections and request inboxes."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _character(session: Session, campaign_id: str, character_id: str) -> Character:
        character = session.get(Character, character_id)
        if character is None or character.campaign_id != campaign_id:
            raise StateNotFoundError("character not found")
        return character

    @staticmethod
    def _audit(
        session: Session,
        campaign_id: str,
        action: str,
        request: PlayerActionRequest,
        request_id: str,
    ) -> None:
        session.add(
            AuditLog(
                campaign_id=campaign_id,
                actor="player" if action == "player_request" else "dm",
                action=action,
                entity_type="player_action_request",
                entity_id=request.id,
                before_json=None,
                after_json=serialize(request),
                request_id=request_id,
            )
        )

    def player_view(self, campaign_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            campaign = self._campaign(session, campaign_id)
            scene = session.scalars(
                select(Scene)
                .where(Scene.campaign_id == campaign_id, Scene.status == "active")
                .order_by(Scene.created_at.desc())
            ).first()
            result: dict[str, Any] = {
                "campaign": {
                    "id": campaign.id,
                    "name": campaign.name,
                    "current_time": campaign.current_time,
                },
                "scene": None,
                "initiative": [],
                "handouts": [],
                "shared_log": [],
            }
            if scene:
                grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene.id))
                tokens = session.scalars(
                    select(SceneToken)
                    .where(SceneToken.scene_id == scene.id, SceneToken.visible.is_(True))
                    .order_by(SceneToken.id)
                ).all()
                objects = session.scalars(
                    select(SceneObject)
                    .where(SceneObject.scene_id == scene.id, SceneObject.visibility == "public")
                    .order_by(SceneObject.id)
                ).all()
                result["scene"] = {
                    "id": scene.id,
                    "name": scene.name,
                    "description": scene.description,
                    "grid": None
                    if grid is None
                    else {
                        "width": grid.width,
                        "height": grid.height,
                        "cell_size_ft": grid.cell_size_ft,
                        "mode": grid.mode,
                        "public_description": grid.public_description,
                    },
                    "tokens": [
                        {
                            "id": t.id,
                            "label": t.label,
                            "row": t.row,
                            "col": t.col,
                            "size_cells": t.size_cells,
                            "elevation_ft": t.elevation_ft,
                        }
                        for t in tokens
                    ],
                    "objects": [
                        {
                            "id": o.id,
                            "object_type": o.object_type,
                            "label": o.label,
                            "row": o.row,
                            "col": o.col,
                            "width_cells": o.width_cells,
                            "height_cells": o.height_cells,
                            "state": o.state,
                        }
                        for o in objects
                    ],
                }
            combat = session.scalars(
                select(Combat)
                .where(Combat.campaign_id == campaign_id, Combat.status == "active")
                .order_by(Combat.created_at.desc())
            ).first()
            if combat:
                combatants = session.scalars(
                    select(Combatant)
                    .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
                    .order_by(Combatant.initiative.desc(), Combatant.id)
                ).all()
                result["initiative"] = [
                    {
                        "id": c.id,
                        "name": c.display_name,
                        "initiative": c.initiative,
                        "hp": c.hp,
                        "max_hp": c.max_hp,
                        "conditions": c.conditions,
                    }
                    for c in combatants
                ]
            handouts = session.scalars(
                select(Handout)
                .where(Handout.campaign_id == campaign_id, Handout.published.is_(True))
                .order_by(Handout.sort_order, Handout.id)
            ).all()
            result["handouts"] = [
                {"id": h.id, "title": h.title, "body": h.body, "sort_order": h.sort_order}
                for h in handouts
            ]
            events = session.scalars(
                select(Event)
                .where(
                    Event.campaign_id == campaign_id, Event.visibility.in_(("players", "public"))
                )
                .order_by(Event.occurred_at.desc())
                .limit(100)
            ).all()
            result["shared_log"] = [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "title": e.title,
                    "description": e.description,
                    "occurred_at": e.occurred_at,
                }
                for e in events
            ]
            return result

    def character_view(self, campaign_id: str, character_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            character = self._character(session, campaign_id, character_id)
            # Explicit allowlist: notably excludes notes and every DM-only relation.
            return {
                key: getattr(character, key)
                for key in (
                    "id",
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
                    "version",
                )
            }

    def submit_action(
        self, campaign_id: str, data: dict[str, Any], request_id: str
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            existing = session.scalar(
                select(PlayerActionRequest).where(
                    PlayerActionRequest.campaign_id == campaign_id,
                    PlayerActionRequest.idempotency_key == data["idempotency_key"],
                )
            )
            if existing:
                return serialize(existing)
            character = self._character(session, campaign_id, data["character_id"])
            if character.version != data["character_version"]:
                raise VersionConflict(
                    "character", character.id, data["character_version"], character.version
                )
            item = PlayerActionRequest(campaign_id=campaign_id, **data)
            session.add(item)
            session.flush()
            self._audit(session, campaign_id, "player_request", item, request_id)
            return serialize(item)

    def list_requests(self, campaign_id: str, status: str | None = None) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            query = select(PlayerActionRequest).where(
                PlayerActionRequest.campaign_id == campaign_id
            )
            if status:
                query = query.where(PlayerActionRequest.status == status)
            return [
                serialize(item)
                for item in session.scalars(
                    query.order_by(PlayerActionRequest.created_at.desc())
                ).all()
            ]

    def resolve_action(
        self,
        campaign_id: str,
        request_id_value: str,
        expected_version: int,
        status: str,
        dm_note: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            item = session.get(PlayerActionRequest, request_id_value)
            if item is None or item.campaign_id != campaign_id:
                raise StateNotFoundError("player action request not found")
            if item.version != expected_version:
                raise VersionConflict(
                    "player_action_request", item.id, expected_version, item.version
                )
            if item.status != "pending":
                return serialize(item)  # confirmation is idempotent
            item.status, item.dm_note, item.resolved_at, item.version, item.updated_at = (
                status,
                dm_note,
                datetime.now(UTC),
                item.version + 1,
                datetime.now(UTC),
            )
            session.flush()
            self._audit(session, campaign_id, f"player_request_{status}", item, request_id)
            return serialize(item)

    def list_handouts(self, campaign_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            return [
                serialize(x)
                for x in session.scalars(
                    select(Handout)
                    .where(Handout.campaign_id == campaign_id)
                    .order_by(Handout.sort_order, Handout.id)
                ).all()
            ]

    def create_handout(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            item = Handout(campaign_id=campaign_id, **data)
            session.add(item)
            session.flush()
            return serialize(item)

    def update_handout(
        self, campaign_id: str, handout_id: str, data: dict[str, Any], version: int
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            item = session.get(Handout, handout_id)
            if item is None or item.campaign_id != campaign_id:
                raise StateNotFoundError("handout not found")
            if item.version != version:
                raise VersionConflict("handout", handout_id, version, item.version)
            for key, value in data.items():
                setattr(item, key, value)
            item.version += 1
            item.updated_at = datetime.now(UTC)
            session.flush()
            return serialize(item)
