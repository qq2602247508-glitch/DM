from __future__ import annotations

import secrets
from datetime import UTC, datetime
from math import floor
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.world import GeneratedLocationNode
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.encounter_service import (
    EncounterAdjustmentService,
)
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    AuditLog,
    Campaign,
    Character,
    Combat,
    Combatant,
    Location,
    MonsterInstance,
    Scene,
    SceneGrid,
    SceneObject,
    SceneParticipant,
    WorldItem,
)


class WorldService:
    def __init__(self, engine: Engine, *, actor: str = "dm") -> None:
        self.engine = engine
        self.actor = actor

    def list_items(
        self,
        campaign_id: str,
        *,
        location_id: str | None = None,
        owner_character_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            query = select(WorldItem).where(WorldItem.campaign_id == campaign_id)
            if location_id is not None:
                query = query.where(WorldItem.location_id == location_id)
            if owner_character_id is not None:
                query = query.where(WorldItem.owner_character_id == owner_character_id)
            query = query.order_by(WorldItem.created_at, WorldItem.id).limit(500)
            return tuple(serialize(item) for item in session.scalars(query))

    def create_item(
        self, campaign_id: str, data: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            self._validate_item_scope(session, campaign_id, data)
            item = WorldItem(campaign_id=campaign_id, **data)
            session.add(item)
            session.flush()
            self._audit(
                session,
                campaign_id,
                "create",
                "world_item",
                item.id,
                None,
                item,
                request_id,
            )
            return serialize(item)

    def delete_item(
        self,
        campaign_id: str,
        item_id: str,
        *,
        expected_version: int,
        request_id: str,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            item = self._item(session, campaign_id, item_id)
            self._version(item, expected_version, "world_item")
            before = serialize(item)
            result = session.execute(
                delete(WorldItem).where(
                    WorldItem.id == item_id, WorldItem.version == expected_version
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                raise VersionConflict("world_item", item_id, expected_version, int(item.version))
            self._audit(
                session, campaign_id, "delete", "world_item", item_id, before, None, request_id
            )

    def pickup_item(
        self,
        campaign_id: str,
        item_id: str,
        *,
        character_id: str,
        quantity: int,
        expected_version: int,
        request_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with Session(self.engine) as session, session.begin():
            item = self._item(session, campaign_id, item_id)
            character = self._character(session, campaign_id, character_id)
            self._version(item, expected_version, "world_item")
            if item.location_id is None:
                raise ValueError("item is not available at a location")
            if quantity < 1 or quantity > item.quantity:
                raise ValueError("pickup quantity is out of range")
            before = serialize(item)
            if quantity == item.quantity:
                item.location_id = None
                item.owner_character_id = character_id
                item.version += 1
                item.updated_at = datetime.now(UTC)
                moved = item
            else:
                item.quantity -= quantity
                item.version += 1
                item.updated_at = datetime.now(UTC)
                moved = WorldItem(
                    campaign_id=campaign_id,
                    name=item.name,
                    description=item.description,
                    category=item.category,
                    quantity=quantity,
                    unit_weight_lb=item.unit_weight_lb,
                    price_cp=item.price_cp,
                    source_record_id=item.source_record_id,
                    source_label=item.source_label,
                    owner_character_id=character_id,
                    is_equipped=False,
                    is_hidden=False,
                    metadata_json=item.metadata_json,
                )
                session.add(moved)
            session.flush()
            self._audit(
                session,
                campaign_id,
                "pickup",
                "world_item",
                moved.id,
                before,
                moved,
                request_id,
            )
            return serialize(moved), self._inventory_summary(session, campaign_id, character)

    def inventory(self, campaign_id: str, character_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            character = self._character(session, campaign_id, character_id)
            return self._inventory_summary(session, campaign_id, character)

    def list_monsters(self, campaign_id: str) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            rows = session.scalars(
                select(MonsterInstance)
                .where(MonsterInstance.campaign_id == campaign_id)
                .order_by(MonsterInstance.created_at, MonsterInstance.id)
                .limit(500)
            )
            return tuple(serialize(row) for row in rows)

    def create_monster(
        self, campaign_id: str, data: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            monster = MonsterInstance(campaign_id=campaign_id, **data)
            session.add(monster)
            session.flush()
            self._audit(
                session, campaign_id, "create", "monster", monster.id, None, monster, request_id
            )
            return serialize(monster)

    def list_scenes(self, campaign_id: str) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            scenes = session.scalars(
                select(Scene)
                .where(Scene.campaign_id == campaign_id)
                .order_by(Scene.created_at, Scene.id)
                .limit(200)
            )
            return tuple(serialize(scene) for scene in scenes)

    def create_scene(
        self, campaign_id: str, data: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            location_id = data.get("location_id")
            if location_id is not None:
                self._location(session, campaign_id, str(location_id))
            scene = Scene(campaign_id=campaign_id, **data)
            session.add(scene)
            session.flush()
            self._audit(session, campaign_id, "create", "scene", scene.id, None, scene, request_id)
            return serialize(scene)

    def list_participants(
        self, campaign_id: str, scene_id: str
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            self._scene(session, campaign_id, scene_id)
            participants = session.scalars(
                select(SceneParticipant)
                .where(SceneParticipant.scene_id == scene_id)
                .order_by(SceneParticipant.created_at, SceneParticipant.id)
            )
            return tuple(
                {
                    **serialize(participant),
                    "entity": self._participant_entity(
                        session, campaign_id, participant.entity_type, participant.entity_id
                    ),
                }
                for participant in participants
            )

    def add_participant(
        self, campaign_id: str, scene_id: str, data: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._scene(session, campaign_id, scene_id)
            entity = self._participant_entity(
                session, campaign_id, str(data["entity_type"]), str(data["entity_id"])
            )
            participant = SceneParticipant(scene_id=scene_id, **data)
            session.add(participant)
            session.flush()
            self._audit(
                session,
                campaign_id,
                "add_participant",
                "scene",
                scene_id,
                None,
                participant,
                request_id,
            )
            return {**serialize(participant), "entity": entity}

    def remove_participant(
        self,
        campaign_id: str,
        scene_id: str,
        participant_id: str,
        *,
        expected_version: int,
        request_id: str,
    ) -> None:
        with Session(self.engine) as session, session.begin():
            self._scene(session, campaign_id, scene_id)
            participant = session.get(SceneParticipant, participant_id)
            if participant is None or participant.scene_id != scene_id:
                raise StateNotFoundError("scene participant not found")
            self._version(participant, expected_version, "scene_participant")
            before = serialize(participant)
            session.delete(participant)
            self._audit(
                session,
                campaign_id,
                "remove_participant",
                "scene",
                scene_id,
                before,
                None,
                request_id,
            )

    def start_combat(
        self, campaign_id: str, scene_id: str, *, name: str | None, request_id: str
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            scene = self._scene(session, campaign_id, scene_id)
            participants = tuple(
                session.scalars(
                    select(SceneParticipant)
                    .where(
                        SceneParticipant.scene_id == scene_id,
                        SceneParticipant.role != "defeated",
                    )
                    .order_by(SceneParticipant.created_at, SceneParticipant.id)
                )
            )
            if not participants:
                raise ValueError("scene has no participants")
            combat = Combat(
                campaign_id=campaign_id,
                scene_id=scene.id,
                name=name or f"{scene.name}战斗",
                status="active",
            )
            session.add(combat)
            session.flush()
            grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
            blocked: set[tuple[int, int]] = set()
            if grid is not None:
                objects = session.scalars(
                    select(SceneObject).where(SceneObject.scene_id == scene_id)
                ).all()
                for scene_object in objects:
                    blocks_movement = (
                        scene_object.object_type in {"wall", "cover", "furniture"}
                        or (
                            scene_object.object_type == "door"
                            and scene_object.state in {"active", "closed"}
                        )
                    )
                    if not blocks_movement:
                        continue
                    for row in range(
                        scene_object.row,
                        scene_object.row + scene_object.height_cells,
                    ):
                        for col in range(
                            scene_object.col,
                            scene_object.col + scene_object.width_cells,
                        ):
                            blocked.add((row, col))
            occupied: set[tuple[int, int]] = set()
            ally_spawn_index = 0
            enemy_spawn_index = 0

            def spawn_position(entity_type: str) -> dict[str, int] | None:
                nonlocal ally_spawn_index, enemy_spawn_index
                if grid is None:
                    return None
                if entity_type == "monster":
                    origin = (
                        min(grid.height, 2),
                        max(1, grid.width - 2 - enemy_spawn_index),
                    )
                    enemy_spawn_index += 1
                else:
                    origin = (
                        max(1, grid.height - 1),
                        min(grid.width, 2 + ally_spawn_index),
                    )
                    ally_spawn_index += 1
                candidates = [
                    (row, col)
                    for row in range(1, grid.height + 1)
                    for col in range(1, grid.width + 1)
                    if (row, col) not in blocked and (row, col) not in occupied
                ]
                if not candidates:
                    return None
                row, col = min(
                    candidates,
                    key=lambda point: (
                        abs(point[0] - origin[0]) + abs(point[1] - origin[1]),
                        point[0],
                        point[1],
                    ),
                )
                occupied.add((row, col))
                return {"row": row, "col": col}

            rolls: list[dict[str, Any]] = []
            for participant in participants:
                entity = self._entity_model(
                    session, campaign_id, participant.entity_type, participant.entity_id
                )
                abilities = entity.ability_scores or {}
                dexterity = int(
                    abilities.get("dexterity", abilities.get("dex", abilities.get("敏捷", 10)))
                )
                modifier = floor((dexterity - 10) / 2)
                die = secrets.randbelow(20) + 1
                total = die + modifier
                position = spawn_position(participant.entity_type)
                snapshot = {
                    "speed_ft": int(getattr(entity, "speed", 30)),
                    "ability_scores": dict(entity.ability_scores or {}),
                    "actions": list(getattr(entity, "actions", []) or []),
                    "combat_start_state": {
                        "hp": int(getattr(entity, "hp", 1)),
                        "temporary_hp": 0,
                        "max_hp_reduction": 0,
                        "conditions": [],
                        "concentration": {},
                        "is_active": True,
                    },
                }
                if position is not None:
                    snapshot["grid_position"] = position
                combatant = Combatant(
                    combat_id=combat.id,
                    entity_type=participant.entity_type,
                    entity_id=participant.entity_id,
                    display_name=entity.name,
                    initiative=total,
                    armor_class=int(getattr(entity, "armor_class", 10)),
                    hp=int(getattr(entity, "hp", 1)),
                    max_hp=int(getattr(entity, "max_hp", 1)),
                    speed_ft=int(getattr(entity, "speed", 30)),
                    movement_remaining_ft=int(getattr(entity, "speed", 30)),
                    damage_resistances=list(
                        getattr(entity, "damage_resistances", []) or []
                    ),
                    damage_vulnerabilities=list(
                        getattr(entity, "damage_vulnerabilities", []) or []
                    ),
                    damage_immunities=list(
                        getattr(entity, "damage_immunities", []) or []
                    ),
                    condition_immunities=list(
                        getattr(entity, "condition_immunities", []) or []
                    ),
                    conditions=[],
                    snapshot_json=snapshot,
                    is_active=True,
                )
                session.add(combatant)
                rolls.append(
                    {
                        "entity_type": participant.entity_type,
                        "entity_id": participant.entity_id,
                        "name": entity.name,
                        "die": die,
                        "dexterity_modifier": modifier,
                        "total": total,
                    }
                )
            session.flush()
            EncounterAdjustmentService(self.engine).consume_for_combat(
                session,
                campaign_id=campaign_id,
                scene_id=scene_id,
                combat=combat,
            )
            session.flush()
            self._audit(
                session,
                campaign_id,
                "start_scene_combat",
                "combat",
                combat.id,
                None,
                combat,
                request_id,
            )
            return {"combat": serialize(combat), "initiative_rolls": rolls}

    def confirm_location_tree(
        self,
        campaign_id: str,
        root: GeneratedLocationNode,
        *,
        maximum_depth: int,
        request_id: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            created_locations: list[dict[str, Any]] = []
            created_items: list[dict[str, Any]] = []

            def create_node(
                node: GeneratedLocationNode, depth: int, parent_id: str | None
            ) -> None:
                if depth > maximum_depth:
                    raise ValueError("location tree exceeds confirmed maximum depth")
                location = Location(
                    campaign_id=campaign_id,
                    parent_location_id=parent_id,
                    depth=depth,
                    name=node.name,
                    description=node.description,
                    interactive_objects=list(node.interactive_objects),
                    secrets=node.secrets,
                    discovered=node.discovered,
                    notes=self._suggestion_notes(node),
                )
                session.add(location)
                session.flush()
                created_locations.append(serialize(location))
                for generated in node.items:
                    item = WorldItem(
                        campaign_id=campaign_id,
                        location_id=location.id,
                        name=generated.name,
                        description=generated.description,
                        category=generated.category,
                        quantity=generated.quantity,
                        unit_weight_lb=generated.unit_weight_lb,
                        price_cp=generated.price_cp,
                        source_label="ai_generated",
                        is_hidden=generated.hidden,
                        metadata_json={"interactive_note": generated.interactive_note},
                    )
                    session.add(item)
                    session.flush()
                    created_items.append(serialize(item))
                for child in node.children:
                    create_node(child, depth + 1, location.id)

            create_node(root, 1, None)
            self._audit(
                session,
                campaign_id,
                "confirm_location_generation",
                "location_tree",
                created_locations[0]["id"],
                None,
                {"locations": created_locations, "items": created_items},
                request_id,
            )
            return {"locations": created_locations, "items": created_items}

    @staticmethod
    def _suggestion_notes(node: GeneratedLocationNode) -> str | None:
        parts: list[str] = []
        if node.suggested_npcs:
            parts.append(f"建议 NPC：{'、'.join(node.suggested_npcs)}")
        if node.suggested_monsters:
            parts.append(f"建议怪物：{'、'.join(node.suggested_monsters)}")
        return "\n".join(parts) or None

    def _inventory_summary(
        self, session: Session, campaign_id: str, character: Character
    ) -> dict[str, Any]:
        items = tuple(
            session.scalars(
                select(WorldItem)
                .where(
                    WorldItem.campaign_id == campaign_id,
                    WorldItem.owner_character_id == character.id,
                )
                .order_by(WorldItem.created_at, WorldItem.id)
            )
        )
        total_weight = round(
            sum(float(item.unit_weight_lb) * int(item.quantity) for item in items), 3
        )
        strength = int(
            (character.ability_scores or {}).get(
                "strength", (character.ability_scores or {}).get("str", 10)
            )
        )
        campaign = self._campaign(session, campaign_id)
        mode = campaign.encumbrance_mode
        maximum = None if mode == "none" else strength * 15
        state = "ignored" if mode == "none" else "normal"
        if mode == "variant":
            if total_weight > strength * 10:
                state = "heavily_encumbered"
            elif total_weight > strength * 5:
                state = "encumbered"
        elif maximum is not None and total_weight > maximum:
            state = "over_capacity"
        return {
            "character_id": character.id,
            "strength": strength,
            "encumbrance_mode": mode,
            "total_weight_lb": total_weight,
            "maximum_weight_lb": maximum,
            "state": state,
            "items": [serialize(item) for item in items],
        }

    def _validate_item_scope(
        self, session: Session, campaign_id: str, data: dict[str, Any]
    ) -> None:
        location_id = data.get("location_id")
        owner_id = data.get("owner_character_id")
        if location_id and owner_id:
            raise ValueError("item cannot have both location and owner")
        if location_id:
            self._location(session, campaign_id, str(location_id))
        if owner_id:
            self._character(session, campaign_id, str(owner_id))

    @staticmethod
    def _version(entity: Any, expected: int, entity_type: str) -> None:
        actual = int(entity.version)
        if actual != expected:
            raise VersionConflict(entity_type, str(entity.id), expected, actual)

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _location(session: Session, campaign_id: str, location_id: str) -> Location:
        location = session.get(Location, location_id)
        if location is None or location.campaign_id != campaign_id:
            raise StateNotFoundError("location not found")
        return location

    @staticmethod
    def _character(session: Session, campaign_id: str, character_id: str) -> Character:
        character = session.get(Character, character_id)
        if character is None or character.campaign_id != campaign_id:
            raise StateNotFoundError("character not found")
        return character

    @staticmethod
    def _item(session: Session, campaign_id: str, item_id: str) -> WorldItem:
        item = session.get(WorldItem, item_id)
        if item is None or item.campaign_id != campaign_id:
            raise StateNotFoundError("world item not found")
        return item

    @staticmethod
    def _scene(session: Session, campaign_id: str, scene_id: str) -> Scene:
        scene = session.get(Scene, scene_id)
        if scene is None or scene.campaign_id != campaign_id:
            raise StateNotFoundError("scene not found")
        return scene

    def _participant_entity(
        self, session: Session, campaign_id: str, entity_type: str, entity_id: str
    ) -> dict[str, Any]:
        return serialize(self._entity_model(session, campaign_id, entity_type, entity_id))

    @staticmethod
    def _entity_model(
        session: Session, campaign_id: str, entity_type: str, entity_id: str
    ) -> Character | NPC | MonsterInstance:
        entity: Character | NPC | MonsterInstance | None
        if entity_type == "character":
            entity = session.get(Character, entity_id)
        elif entity_type == "npc":
            entity = session.get(NPC, entity_id)
        elif entity_type == "monster":
            entity = session.get(MonsterInstance, entity_id)
        else:
            raise ValueError("unsupported scene participant type")
        if entity is None or entity.campaign_id != campaign_id:
            raise StateNotFoundError(f"{entity_type} not found")
        return entity

    def _audit(
        self,
        session: Session,
        campaign_id: str,
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
                before_json=(
                    serialize(before) if hasattr(before, "__table__") else before
                ),
                after_json=serialize(after) if hasattr(after, "__table__") else after,
                request_id=request_id,
            )
        )
