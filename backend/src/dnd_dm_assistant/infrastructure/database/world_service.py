from __future__ import annotations

import secrets
from datetime import UTC, datetime
from math import floor
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.equipment_rules import equipment_profile
from dnd_dm_assistant.domain.feature_runtime import (
    apply_initiative_start_resource_recovery,
    compile_feature_runtime_registry,
    feature_runtime_action_projections,
    resolve_feature_speed,
    resolve_unarmored_defense_ac,
)
from dnd_dm_assistant.domain.item_spec import materialize_item_effects
from dnd_dm_assistant.domain.world import GeneratedLocationNode
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.encounter_service import (
    EncounterAdjustmentService,
)
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Attunement,
    AuditLog,
    Campaign,
    Character,
    Combat,
    Combatant,
    EquipmentInstance,
    Location,
    MonsterInstance,
    Scene,
    SceneGrid,
    SceneObject,
    SceneParticipant,
    SceneToken,
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
            # SQLite's server-side CURRENT_TIMESTAMP has only second precision;
            # explicit microsecond timestamps keep creation order deterministic
            # when several outline Scenes are created in one second.
            scene = Scene(campaign_id=campaign_id, created_at=datetime.now(UTC), **data)
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
            grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
            existing_token = session.scalar(
                select(SceneToken).where(
                    SceneToken.scene_id == scene_id,
                    SceneToken.entity_type == participant.entity_type,
                    SceneToken.entity_id == participant.entity_id,
                )
            )
            if grid is not None and existing_token is None:
                occupied = {
                    (token.row, token.col)
                    for token in session.scalars(
                        select(SceneToken).where(SceneToken.scene_id == scene_id)
                    )
                }
                raw_cells = grid.layers_json.get("cells", [])
                cells = raw_cells if isinstance(raw_cells, list) else []
                blocked = {
                    (int(cell["row"]), int(cell["col"]))
                    for cell in cells
                    if isinstance(cell, dict)
                    and cell.get("kind") in {"wall", "door"}
                    and isinstance(cell.get("row"), int)
                    and isinstance(cell.get("col"), int)
                }
                position = next(
                    (
                        (row, col)
                        for row in range(2, max(3, grid.height))
                        for col in range(2, max(3, grid.width))
                        if (row, col) not in occupied and (row, col) not in blocked
                    ),
                    (1, 1),
                )
                session.add(
                    SceneToken(
                        scene_id=scene_id,
                        entity_type=participant.entity_type,
                        entity_id=participant.entity_id,
                        label=str(entity.get("name") or participant.entity_type),
                        row=position[0],
                        col=position[1],
                        visible=participant.visible,
                        metadata_json={"generated_from": "scene_participant"},
                    )
                )
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
            token = session.scalar(
                select(SceneToken).where(
                    SceneToken.scene_id == scene_id,
                    SceneToken.entity_type == participant.entity_type,
                    SceneToken.entity_id == participant.entity_id,
                    SceneToken.metadata_json["generated_from"].as_string()
                    == "scene_participant",
                )
            )
            if token is not None:
                session.delete(token)
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
                initiative_dice = [secrets.randbelow(20) + 1]
                initiative_advantage_sources: list[str] = []
                initiative_disadvantage_sources: list[str] = []
                effective_armor_class = int(getattr(entity, "armor_class", 10))
                effective_speed_ft = int(getattr(entity, "speed", 30))
                position = spawn_position(participant.entity_type)
                snapshot = {
                    "speed_ft": effective_speed_ft,
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
                # Advancement grants are persisted on the character sheet, but
                # the combat engine reads the immutable combatant snapshot.  A
                # feature that was merely displayed on the sheet therefore
                # had no runtime effect after entering combat.  Copy only
                # numeric/advantage profiles that were explicitly compiled by
                # the advancement compiler; prose-only grants remain DM-only.
                if isinstance(entity, Character):
                    feature_grants = [
                        item for item in (entity.features or [])
                        if isinstance(item, dict)
                    ]
                    scaling_values = {
                        str(item.get("scaling_key")): item.get("value")
                        for item in feature_grants
                        if item.get("kind") == "class_scaling"
                        and isinstance(item.get("scaling_key"), str)
                    }
                    rule_modifiers: dict[str, dict[str, Any]] = {}
                    for grant in feature_grants:
                        runtime = grant.get("runtime")
                        if not isinstance(runtime, dict):
                            continue
                        raw_modifiers = runtime.get("modifiers")
                        if not isinstance(raw_modifiers, list):
                            continue
                        for raw_modifier in raw_modifiers:
                            if not isinstance(raw_modifier, dict):
                                continue
                            stat = str(raw_modifier.get("stat") or "").strip()
                            operation = str(raw_modifier.get("operation") or "").strip()
                            scope = str(raw_modifier.get("scope") or "all").strip()
                            if not stat or not operation:
                                continue
                            modifier = dict(raw_modifier)
                            scaling_key = modifier.get("scaling_key")
                            if "value" not in modifier and isinstance(scaling_key, str):
                                candidate = scaling_values.get(scaling_key)
                                if isinstance(candidate, int):
                                    modifier["value"] = candidate
                                elif (
                                    isinstance(candidate, str)
                                    and candidate.strip().lstrip("+-").isdigit()
                                ):
                                    modifier["value"] = int(candidate.strip())
                            if "value" not in modifier and operation in {"add", "grant"}:
                                # A numeric modifier without a resolved value
                                # is not safe to apply automatically.
                                continue
                            skill = str(modifier.get("skill") or "")
                            rule_modifiers[f"{stat}:{scope}:{skill}"] = modifier
                    if rule_modifiers:
                        snapshot["rule_modifiers"] = rule_modifiers
                    feature_registry = compile_feature_runtime_registry(
                        feature_grants,
                        resources=(entity.resources or {})
                        if isinstance(entity.resources, dict)
                        else {},
                        scalings={
                            key: {"value": value}
                            for key, value in scaling_values.items()
                        },
                        class_levels=(entity.class_levels or {})
                        if isinstance(entity.class_levels, dict)
                        else {},
                        total_level=entity.level,
                    )
                    snapshot["feature_runtime"] = feature_registry
                    current_resources = dict(entity.resources or {})
                    resolved_resources, recovery_events = (
                        apply_initiative_start_resource_recovery(
                            current_resources,
                            feature_registry,
                        )
                    )
                    if recovery_events:
                        entity.resources = resolved_resources
                        snapshot["resources"] = resolved_resources
                        snapshot["initiative_start_resource_recovery"] = recovery_events
                        for resource_key, resource_value in resolved_resources.items():
                            registry_resource = feature_registry.get("resources", {}).get(
                                resource_key
                            )
                            if isinstance(registry_resource, dict):
                                registry_resource["current"] = resource_value.get("current")
                    else:
                        snapshot["resources"] = current_resources
                    runtime_actions = feature_runtime_action_projections(feature_registry)
                    if runtime_actions:
                        snapshot["actions"] = [
                            *list(snapshot.get("actions") or []),
                            *runtime_actions,
                        ]
                    snapshot["attack_action_count"] = int(
                        feature_registry.get("combat_start", {}).get(
                            "attack_action_count", 1
                        )
                    )
                    jump_modifiers = [
                        item
                        for item in feature_registry.get("combat_start", {}).get(
                            "modifiers", []
                        )
                        if isinstance(item, dict)
                        and item.get("stat") == "jump_ability"
                        and item.get("operation") == "set"
                    ]
                    if jump_modifiers:
                        ability = str(jump_modifiers[-1].get("value_source") or "strength")
                        raw_score = (entity.ability_scores or {}).get(ability)
                        if isinstance(raw_score, int):
                            snapshot["jump_ability"] = ability
                            snapshot["jump_distance_ft"] = max(0, raw_score)
                    conditional_defenses = [
                        {
                            "id": item.get("id"),
                            "condition": item.get("applies_when"),
                            "operation": item.get("operation"),
                            "damage_types": item.get("damage_types", []),
                        }
                        for item in feature_registry.get("combat_start", {}).get("defenses", [])
                        if isinstance(item, dict)
                        and item.get("applies_when")
                        and item.get("operation")
                    ]
                    if conditional_defenses:
                        snapshot["conditional_damage_defenses"] = conditional_defenses
                    advanced_defenses = dict(
                        snapshot.get("advanced_defenses")
                        if isinstance(snapshot.get("advanced_defenses"), dict)
                        else {}
                    )
                    for defense in feature_registry.get("combat_start", {}).get(
                        "defenses", []
                    ):
                        if not isinstance(defense, dict):
                            continue
                        if defense.get("kind") == "evasion":
                            advanced_defenses["evasion"] = True
                    if advanced_defenses:
                        snapshot["advanced_defenses"] = advanced_defenses
                    snapshot["feature_grants"] = feature_grants
                    equipment_rows = session.scalars(
                        select(EquipmentInstance).where(
                            EquipmentInstance.character_id == entity.id,
                            EquipmentInstance.campaign_id == campaign_id,
                        )
                    ).all()
                    equipped_profiles = [
                        equipment_profile(
                            row.name,
                            row.category,
                            dict(row.metadata_json or {}),
                            row.armor_class,
                        )
                        for row in equipment_rows
                        if row.equipped
                    ]
                    snapshot["equipment"] = equipped_profiles
                    active_attunement_ids = {
                        str(item.equipment_instance_id)
                        for item in session.scalars(
                            select(Attunement).where(
                                Attunement.character_id == entity.id,
                                Attunement.status == "active",
                            )
                        )
                    }
                    snapshot["item_effects"] = materialize_item_effects(
                        [
                            {
                                "id": row.id,
                                "equipped": bool(row.equipped),
                                "item_spec": (row.metadata_json or {}).get("item_spec"),
                            }
                            for row in equipment_rows
                        ],
                        active_attunement_ids,
                    )
                    armor_profiles = [
                        profile
                        for profile in equipped_profiles
                        if profile.get("kind") == "armor"
                    ]
                    wearing_armor = bool(armor_profiles)
                    armor_types = {
                        str(profile.get("armor_type") or "")
                        for profile in armor_profiles
                    }
                    wearing_heavy_armor: bool | None = (
                        True
                        if "heavy" in armor_types
                        else False
                        if armor_profiles and armor_types.issubset({"light", "medium"})
                        else None
                        if wearing_armor
                        else False
                    )
                    effective_armor_class, armor_resolution = resolve_unarmored_defense_ac(
                        effective_armor_class,
                        dict(entity.ability_scores or {}),
                        feature_registry,
                        equipment_state_authoritative=bool(equipment_rows),
                        wearing_armor=wearing_armor,
                        wielding_shield=any(
                            profile.get("kind") == "shield" for profile in equipped_profiles
                        ),
                    )
                    if armor_resolution is not None:
                        snapshot["armor_class_resolution"] = armor_resolution
                    effective_speed_ft, speed_resolution = resolve_feature_speed(
                        effective_speed_ft,
                        feature_registry,
                        equipment_state_authoritative=bool(equipment_rows),
                        wearing_armor=wearing_armor,
                        wielding_shield=any(
                            profile.get("kind") == "shield"
                            for profile in equipped_profiles
                        ),
                        wearing_heavy_armor=wearing_heavy_armor,
                    )
                    if speed_resolution is not None:
                        snapshot["speed_resolution"] = speed_resolution
                        snapshot["speed_ft"] = effective_speed_ft
                    combat_start = feature_registry.get("combat_start")
                    raw_initiative_modifiers = (
                        combat_start.get("modifiers")
                        if isinstance(combat_start, dict)
                        else []
                    )
                    for raw_modifier in raw_initiative_modifiers or []:
                        if not isinstance(raw_modifier, dict):
                            continue
                        if raw_modifier.get("stat") != "initiative":
                            continue
                        if raw_modifier.get("scope", "self") != "self":
                            continue
                        source_name = str(
                            raw_modifier.get("feature_name")
                            or raw_modifier.get("source_feature")
                            or raw_modifier.get("id")
                            or "结构化职业特性"
                        )
                        operation = raw_modifier.get("operation")
                        if operation == "advantage":
                            initiative_advantage_sources.append(source_name)
                        elif operation == "disadvantage":
                            initiative_disadvantage_sources.append(source_name)
                        elif operation == "add":
                            raw_value = raw_modifier.get("value")
                            if raw_modifier.get("value_source") == "wisdom_modifier":
                                wisdom = int(
                                    (entity.ability_scores or {}).get(
                                        "wisdom",
                                        (entity.ability_scores or {}).get("感知", 10),
                                    )
                                )
                                raw_value = floor((wisdom - 10) / 2)
                            if isinstance(raw_value, int) and not isinstance(raw_value, bool):
                                modifier += raw_value
                                initiative_advantage_sources.append(
                                    f"{source_name} (+{raw_value} initiative)"
                                )

                # Multiple advantages do not stack.  If a future feature
                # supplies both advantage and disadvantage, they cancel and
                # the normal single roll is retained instead of inventing a
                # preference between the two rules.
                initiative_mode = "normal"
                if initiative_advantage_sources and not initiative_disadvantage_sources:
                    initiative_dice.append(secrets.randbelow(20) + 1)
                    initiative_mode = "advantage"
                elif initiative_disadvantage_sources and not initiative_advantage_sources:
                    initiative_dice.append(secrets.randbelow(20) + 1)
                    initiative_mode = "disadvantage"
                die = (
                    max(initiative_dice)
                    if initiative_mode == "advantage"
                    else min(initiative_dice)
                    if initiative_mode == "disadvantage"
                    else initiative_dice[0]
                )
                total = die + modifier
                snapshot["initiative_roll"] = {
                    "mode": initiative_mode,
                    "dice": initiative_dice,
                    "selected_die": die,
                    "advantage_sources": initiative_advantage_sources,
                    "disadvantage_sources": initiative_disadvantage_sources,
                }
                if position is not None:
                    snapshot["grid_position"] = position
                combatant = Combatant(
                    combat_id=combat.id,
                    entity_type=participant.entity_type,
                    entity_id=participant.entity_id,
                    display_name=entity.name,
                    initiative=total,
                    armor_class=effective_armor_class,
                    hp=int(getattr(entity, "hp", 1)),
                    max_hp=int(getattr(entity, "max_hp", 1)),
                    speed_ft=effective_speed_ft,
                    movement_remaining_ft=effective_speed_ft,
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
                        "dice": initiative_dice,
                        "mode": initiative_mode,
                        "advantage_sources": initiative_advantage_sources,
                        "disadvantage_sources": initiative_disadvantage_sources,
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
