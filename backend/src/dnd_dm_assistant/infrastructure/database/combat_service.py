from __future__ import annotations

import re
import secrets
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import floor, hypot
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.api.schemas import (
    CombatActionCommand,
    CombatEffectCommand,
    CombatEffectEndCommand,
    CombatEffectSaveCommand,
    CombatFeatureActionCommand,
    CombatManeuverCommand,
    CombatResetCommand,
    CombatSettlementCommand,
    CombatSummonCommand,
    CombatSummonEndCommand,
    ConcentrationCheckCommand,
    DeathConfirmationCommand,
    DeathSaveCommand,
    MonsterAreaActionCommand,
    PlayerRollPromptBatchCommand,
    PlayerRollPromptCommand,
    PlayerRollResolutionCommand,
    TurnAdvanceCommand,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.combat import (
    resolve_damage,
    resolve_death_save,
    resolve_healing,
)
from dnd_dm_assistant.domain.exploration import (
    cover_between,
    grid_distance_ft,
    line_cells,
    line_of_sight,
    line_of_sight_3d,
)
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Campaign,
    Character,
    CharacterCompanion,
    CharacterCondition,
    Combat,
    CombatAction,
    Combatant,
    CombatEffect,
    CombatSettlement,
    CurrencyTransaction,
    DeathSave,
    MonsterInstance,
    OperationTransaction,
    SceneGrid,
    SceneObject,
    SceneParticipant,
    SceneToken,
    Wallet,
    WorldItem,
)


class CombatEngineService:
    _CONDITION_ALIASES = {
        "incapacitated": "incapacitated",
        "失能": "incapacitated",
        "unconscious": "unconscious",
        "昏迷": "unconscious",
        "stunned": "stunned",
        "震慑": "stunned",
        "paralyzed": "paralyzed",
        "麻痹": "paralyzed",
        "petrified": "petrified",
        "石化": "petrified",
        "blinded": "blinded",
        "目盲": "blinded",
        "deafened": "deafened",
        "耳聋": "deafened",
        "poisoned": "poisoned",
        "中毒": "poisoned",
        "frightened": "frightened",
        "恐慌": "frightened",
        "restrained": "restrained",
        "束缚": "restrained",
        "charmed": "charmed",
        "魅惑": "charmed",
        "invisible": "invisible",
        "隐形": "invisible",
        "prone": "prone",
        "倒地": "prone",
        "grappled": "grappled",
        "擒抱": "grappled",
        "raging": "raging",
        "rage": "raging",
        "狂暴": "raging",
    }
    _ACTION_BLOCKING_CONDITIONS = {
        "incapacitated",
        "unconscious",
        "stunned",
        "paralyzed",
        "petrified",
    }
    _MOVEMENT_BLOCKING_CONDITIONS = {
        "unconscious",
        "stunned",
        "paralyzed",
        "petrified",
        "grappled",
        "restrained",
    }
    _SAVE_AUTO_FAIL_STR_DEX_CONDITIONS = {
        "stunned",
        "paralyzed",
        "petrified",
        "unconscious",
    }
    _RUNTIME_STATE_CONDITIONS = {
        "dodge": "闪避",
        "hidden": "隐藏",
        "help": "受助",
        "ready": "准备",
        "disengage": "撤离",
        "feature_invisible": "隐形",
    }

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _state_int(value: object, default: int = 0) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return default
        return default

    @staticmethod
    def _effect_ends_round(
        started_round: int,
        duration_unit: str,
        duration_value: int | None,
    ) -> int | None:
        """Translate a combat effect's explicit clock to an initiative clock.

        Combat rounds are six seconds.  A duration expressed in minutes is
        therefore deterministic in combat (10 rounds per minute); leaving it
        as a database field without an ``ends_round`` made minute-long buffs
        live forever.  Narrative/concentration/until-save effects stay open
        until their dedicated lifecycle endpoint resolves them.
        """

        if duration_value is None:
            return None
        if duration_unit == "rounds":
            return started_round + int(duration_value)
        if duration_unit == "minutes":
            return started_round + int(duration_value) * 10
        return None

    @staticmethod
    def _ordered_combatants(session: Session, combat_id: str) -> list[Combatant]:
        return list(
            session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat_id, Combatant.is_active.is_(True))
                .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
            ).all()
        )

    @staticmethod
    def _is_summon(combatant: Combatant) -> bool:
        return (
            combatant.entity_type == "companion"
            and "summon_source" in combatant.snapshot_json
        )

    @staticmethod
    def _effect_summon_ids(effect: CombatEffect) -> list[str]:
        """Read both the original one-summon link and grouped lifecycle links."""
        details = dict(effect.details_json or {})
        ids: list[str] = []
        raw = details.get("ends_summon_combatant_id")
        if isinstance(raw, str) and raw:
            ids.append(raw)
        grouped = details.get("ends_summon_combatant_ids")
        if isinstance(grouped, list):
            ids.extend(item for item in grouped if isinstance(item, str) and item)
        return list(dict.fromkeys(ids))

    @classmethod
    def _effect_summon_id(cls, effect: CombatEffect) -> str | None:
        ids = cls._effect_summon_ids(effect)
        return ids[0] if ids else None

    @classmethod
    def _deactivate_summons(
        cls,
        session: Session,
        combat: Combat,
        summon_ids: list[str],
        *,
        now: datetime,
    ) -> list[Combatant]:
        unique_ids = list(dict.fromkeys(summon_ids))
        if not unique_ids:
            return []
        before_order = cls._ordered_combatants(session, combat.id)
        current = (
            before_order[combat.current_turn_index]
            if 0 <= combat.current_turn_index < len(before_order)
            else None
        )
        deactivated: list[Combatant] = []
        for summon_id in unique_ids:
            summon = session.get(Combatant, summon_id)
            if (
                summon is None
                or summon.combat_id != combat.id
                or not cls._is_summon(summon)
                or not summon.is_active
            ):
                continue
            summon.is_active = False
            summon.version += 1
            summon.updated_at = now
            deactivated.append(summon)
        if not deactivated:
            return []

        session.flush()
        after_order = cls._ordered_combatants(session, combat.id)
        after_index = {combatant.id: index for index, combatant in enumerate(after_order)}
        if current is not None and current.id in after_index:
            combat.current_turn_index = after_index[current.id]
        elif current is not None and after_order:
            current_position = before_order.index(current)
            successors = before_order[current_position + 1 :] + before_order[:current_position]
            successor = next(
                (candidate for candidate in successors if candidate.id in after_index),
                after_order[0],
            )
            combat.current_turn_index = after_index[successor.id]
        else:
            combat.current_turn_index = 0
        combat.version += 1
        combat.updated_at = now
        return deactivated

    @classmethod
    def _deactivate_summons_for_effects(
        cls,
        session: Session,
        combat: Combat,
        effects: list[CombatEffect],
        *,
        now: datetime,
    ) -> list[Combatant]:
        return cls._deactivate_summons(
            session,
            combat,
            [
                summon_id
                for effect in effects
                for summon_id in cls._effect_summon_ids(effect)
            ],
            now=now,
        )

    @classmethod
    def _effect_lifecycle_summon(
        cls,
        session: Session,
        combat_id: str,
        command: CombatEffectCommand,
    ) -> Combatant | None:
        summon_id = command.ends_summon_combatant_id
        if summon_id is None:
            return None
        summon = session.get(Combatant, summon_id)
        if summon is None or summon.combat_id != combat_id or not cls._is_summon(summon):
            raise StateNotFoundError("summon combatant not found in combat")
        if not summon.is_active:
            raise ValueError("summon is already ended")
        if summon.version != command.summon_version:
            raise VersionConflict(
                "combatant",
                summon.id,
                command.summon_version or 0,
                summon.version,
            )
        return summon

    def add_summon(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatSummonCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Add a real creature template to an existing combat initiative.

        Rule-plan compilation only describes a summon.  This operation is the
        explicit, auditable bridge from that description to a combatant.  It
        deliberately refuses an underspecified inline template instead of
        inventing HP, AC, or actions.
        """
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            existing_action = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing_action is not None:
                raw_ids = existing_action.result_json.get("combatant_ids")
                existing_ids = (
                    [item for item in raw_ids if isinstance(item, str)]
                    if isinstance(raw_ids, list)
                    else []
                )
                if not existing_ids:
                    existing_id = existing_action.result_json.get("combatant_id")
                    existing_ids = [existing_id] if isinstance(existing_id, str) else []
                existing_combatants = [
                    item
                    for item_id in existing_ids
                    if (item := session.get(Combatant, item_id)) is not None
                ]
                return {
                    "action": serialize(existing_action),
                    "combatant": (
                        serialize(existing_combatants[0])
                        if existing_combatants
                        else None
                    ),
                    "combatants": [serialize(item) for item in existing_combatants],
                    "already_applied": True,
                }
            if combat.status != "active":
                raise ValueError("只能向进行中的战斗加入召唤物")

            source = (
                session.get(Combatant, command.source_combatant_id)
                if command.source_combatant_id
                else None
            )
            if source is not None and (
                source.combat_id != combat_id or not source.is_active
            ):
                raise StateNotFoundError("召唤来源不在当前战斗中")
            if command.initiative_mode == "not_applicable":
                raise ValueError("initiative_mode=not_applicable 的召唤效果不能加入战斗")
            if command.initiative_mode == "shared_with_source" and source is None:
                raise ValueError("shared_with_source 召唤必须提供当前战斗中的来源单位")
            if command.controller == "player":
                if source is None or not self._is_player_controlled(source):
                    raise ValueError("玩家召唤必须由当前玩家控制的单位发起")
                owner_id = command.owner_character_id
                if owner_id is None:
                    raise ValueError("player summon owner is required")
                if self._combatant_owner(source) != owner_id:
                    raise ValueError("玩家不能替其他玩家控制召唤物")

            companion = None
            if command.companion_id is not None:
                companion = session.get(CharacterCompanion, command.companion_id)
                if companion is None or companion.campaign_id != campaign_id:
                    raise StateNotFoundError("companion not found in campaign")
                if not companion.active:
                    raise ValueError("该召唤物模板已停用")
                if (
                    command.controller == "player"
                    and companion.owner_character_id != command.owner_character_id
                ):
                    raise ValueError("玩家不能召唤其他角色的伙伴")
                if command.count == 1:
                    already = session.scalar(
                        select(Combatant).where(
                            Combatant.combat_id == combat_id,
                            Combatant.entity_type == "companion",
                            Combatant.entity_id == companion.id,
                            Combatant.is_active.is_(True),
                        )
                    )
                    if already is not None:
                        return {
                            "action": None,
                            "combatant": serialize(already),
                            "combatants": [serialize(already)],
                            "already_applied": True,
                        }

            if command.controller == "player":
                self._validate_action_economy(
                    session,
                    combat,
                    source,
                    actor_version=source.version if source is not None else None,
                    action_cost=command.action_cost,
                    consume=True,
                )
                if command.resource_key and command.resource_cost:
                    owner_id = command.owner_character_id
                    character = session.get(Character, owner_id) if owner_id else None
                    if character is None or character.campaign_id != campaign_id:
                        raise StateNotFoundError("召唤物主人角色不在当前战役")
                    resources = dict(character.resources or {})
                    resource = resources.get(command.resource_key)
                    current = int(resource.get("current") or 0) if isinstance(resource, dict) else 0
                    if current < command.resource_cost:
                        raise ValueError("对应法术位或资源不足")
                    resources[command.resource_key] = {
                        **(resource if isinstance(resource, dict) else {}),
                        "current": current - command.resource_cost,
                    }
                    character.resources = resources
                    character.version += 1
                    character.updated_at = datetime.now(UTC)

            template = dict(companion.template_json or {}) if companion else {}

            def value(name: str, default: Any = None) -> Any:
                explicit = getattr(command, name)
                if explicit is not None and explicit != {} and explicit != []:
                    return explicit
                if name in template and template[name] not in (None, "", {}, []):
                    return template[name]
                return default

            name = str(value("name", companion.name if companion else "") or "").strip()
            if not name:
                raise ValueError("召唤物缺少名称")
            max_hp_raw = value("max_hp", companion.max_hp if companion else None)
            hp_raw = value("hp", companion.hp if companion else max_hp_raw)
            ac_raw = value("armor_class", companion.armor_class if companion else None)
            speed_raw = value("speed_ft", companion.speed if companion else None)
            if max_hp_raw is None or ac_raw is None or speed_raw is None:
                raise ValueError("召唤物战斗模板必须明确 HP、AC 和速度")
            max_hp = int(max_hp_raw)
            hp = int(hp_raw)
            armor_class = int(ac_raw)
            speed_ft = int(speed_raw)
            if max_hp < 1 or hp < 0 or hp > max_hp:
                raise ValueError("召唤物 HP 数值无效")
            ability_scores_raw = value("ability_scores", {})
            ability_scores = (
                {str(key): int(raw) for key, raw in ability_scores_raw.items()}
                if isinstance(ability_scores_raw, dict)
                else {}
            )
            actions_raw = value("actions", [])
            actions = list(actions_raw) if isinstance(actions_raw, list) else []
            template_actions = template.get("actions")
            if (
                command.companion_id is not None
                and not actions
                and isinstance(template_actions, list)
            ):
                actions = list(template_actions)

            before_order = self._ordered_combatants(session, combat_id)
            current_id = (
                before_order[combat.current_turn_index].id
                if before_order and combat.current_turn_index < len(before_order)
                else None
            )
            occupied = {
                (int(raw["row"]), int(raw["col"]))
                for raw in (
                    fighter.snapshot_json.get("grid_position")
                    for fighter in before_order
                )
                if isinstance(raw, dict) and "row" in raw and "col" in raw
            }
            scene_id = combat.scene_id
            grid = (
                session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
                if scene_id
                else None
            )
            source_position = (
                source.snapshot_json.get("grid_position")
                if source is not None and isinstance(source.snapshot_json, dict)
                else None
            )
            candidates: list[tuple[int, int]] = []
            if grid is not None:
                candidates = [
                    (row, col)
                    for row in range(1, grid.height + 1)
                    for col in range(1, grid.width + 1)
                    if (row, col) not in occupied
                ]
                if isinstance(source_position, dict):
                    origin = (
                        int(source_position.get("row", 1)),
                        int(source_position.get("col", 1)),
                    )
                    candidates.sort(
                        key=lambda point: (
                            abs(point[0] - origin[0]) + abs(point[1] - origin[1]),
                            point,
                        )
                    )
                if command.position is not None:
                    requested_position = (
                        int(command.position["row"]),
                        int(command.position["col"]),
                    )
                    if not (
                        1 <= requested_position[0] <= grid.height
                        and 1 <= requested_position[1] <= grid.width
                    ):
                        raise ValueError("召唤位置超出当前战斗地图边界")
                    terrain_cells = {
                        (int(cell["row"]), int(cell["col"]))
                        for cell in (grid.layers_json.get("cells", []) or [])
                        if isinstance(cell, dict)
                        and isinstance(cell.get("row"), int)
                        and isinstance(cell.get("col"), int)
                        and (cell.get("kind") == "wall" or cell.get("blocks_sight") is True)
                    }
                    scene_objects = session.scalars(
                        select(SceneObject).where(SceneObject.scene_id == scene_id)
                    ).all()
                    object_cells = {
                        (row, col)
                        for item in scene_objects
                        if item.object_type == "wall"
                        or (item.object_type == "door" and item.state in {"active", "closed"})
                        for row in range(item.row, item.row + item.height_cells)
                        for col in range(item.col, item.col + item.width_cells)
                    }
                    if requested_position in occupied:
                        raise ValueError("召唤位置已被其他战斗单位占据")
                    if requested_position in terrain_cells or requested_position in object_cells:
                        raise ValueError("召唤位置被墙体或关闭的门阻挡")
                    candidates = [requested_position] + [
                        point for point in candidates if point != requested_position
                    ]
                    candidates[1:] = sorted(
                        candidates[1:],
                        key=lambda point: (
                            abs(point[0] - requested_position[0])
                            + abs(point[1] - requested_position[1]),
                            point,
                        ),
                    )
            elif command.position is not None:
                raise ValueError("选择召唤位置需要当前战斗地图网格")
            dexterity = int(ability_scores.get("dexterity", ability_scores.get("敏捷", 10)))
            disposition = command.disposition
            owner_id = command.owner_character_id
            summon_group_id = idempotency_key if command.count > 1 else None
            combatants: list[Combatant] = []
            initiative_rolls: list[int] = []
            for index in range(command.count):
                position: dict[str, int] | None = None
                if candidates:
                    row, col = candidates.pop(0)
                    position = {"row": row, "col": col}
                if command.initiative_mode == "independent":
                    rolled_modifier = int(floor((dexterity - 10) / 2))
                    rolled_initiative = int(secrets.randbelow(20) + 1)
                    initiative = rolled_initiative + rolled_modifier
                    initiative_rolls.append(rolled_initiative)
                else:
                    assert source is not None
                    initiative = source.initiative
                snapshot: dict[str, object] = {
                    "ability_scores": ability_scores,
                    "actions": actions,
                    "controller": command.controller,
                    "owner_character_id": owner_id,
                    "disposition": disposition,
                    "initiative_mode": command.initiative_mode,
                    "summon_source_combatant_id": command.source_combatant_id,
                    "summon_source": dict(command.template_json or {}),
                    # Enemy summons never opt into autonomous combat merely
                    # by existing.  A DM must explicitly choose a basic AI
                    # policy in the DM-owned summon command; player summons
                    # are always excluded from that boundary.
                    "enemy_ai_mode": (
                        command.enemy_ai_mode
                        if command.controller == "dm" and disposition == "enemy"
                        else "not_applicable"
                    ),
                    "summon_duration": {
                        "unit": command.duration_unit,
                        "value": command.duration_value,
                        "requires_concentration": command.requires_concentration,
                    },
                    "combat_start_state": {
                        "hp": hp,
                        "temporary_hp": 0,
                        "max_hp_reduction": 0,
                        "conditions": [],
                        "concentration": {},
                        "is_active": True,
                    },
                }
                if summon_group_id is not None:
                    snapshot["summon_group_id"] = summon_group_id
                    snapshot["summon_group_index"] = index + 1
                if position is not None:
                    snapshot["grid_position"] = position
                combatant = Combatant(
                    combat_id=combat_id,
                    entity_type="companion",
                    entity_id=companion.id if companion else None,
                    display_name=name if command.count == 1 else f"{name} {index + 1}",
                    initiative=initiative,
                    armor_class=armor_class,
                    hp=hp,
                    max_hp=max_hp,
                    speed_ft=speed_ft,
                    movement_remaining_ft=speed_ft,
                    snapshot_json=snapshot,
                    is_active=True,
                )
                session.add(combatant)
                combatants.append(combatant)
            session.flush()
            if not combatants:
                raise ValueError("至少需要建立一个召唤单位")
            # A summon spell may create several combatants.  One lifecycle
            # effect owns the whole group so ending its duration or breaking
            # concentration cannot leave orphan initiative cards behind.
            old_effects: list[CombatEffect] = []
            ended_summons: list[Combatant] = []
            lifecycle_effect: CombatEffect | None = None
            if command.requires_concentration:
                if source is None:
                    raise ValueError("专注召唤必须提供来源单位")
                old_effects = self._active_concentration_effects(session, combat_id, source.id)
                for old_effect in old_effects:
                    old_target = session.get(Combatant, old_effect.target_combatant_id)
                    if old_target is not None:
                        self._reverse_compiled_effect(session, old_target, old_effect)
                    old_effect.status = "ended"
                    old_effect.ended_at = datetime.now(UTC)
                    old_effect.end_reason = f"开始新专注召唤：{name}"
                    old_effect.version += 1
                ended_summons = self._deactivate_summons_for_effects(
                    session,
                    combat,
                    old_effects,
                    now=datetime.now(UTC),
                )
            if command.requires_concentration or command.duration_unit != "until_removed":
                lifecycle_target = source or combatants[0]
                ends_round = (
                    combat.round_number + int(command.duration_value or 0)
                    if command.duration_unit == "rounds"
                    else None
                )
                lifecycle_effect = CombatEffect(
                    campaign_id=campaign_id,
                    combat_id=combat_id,
                    target_combatant_id=lifecycle_target.id,
                    source_combatant_id=source.id if source is not None else None,
                    name=f"{name} 的召唤持续时间",
                    effect_type="aura",
                    details_json={
                        "rule_block": {
                            "kind": "summon_lifecycle",
                            # Concentration ends immediately when its source
                            # becomes unconscious, dies, or leaves the
                            # combat.  Keep these predicates explicit so the
                            # generic lifecycle evaluator can clean every
                            # member of a summon group in one transaction.
                            "end_triggers": (
                                [
                                    "source_unconscious",
                                    "source_dead",
                                    "source_inactive",
                                ]
                                if command.requires_concentration
                                else []
                            ),
                        },
                        "ends_summon_combatant_ids": [item.id for item in combatants],
                        "source_action": dict(command.template_json or {}),
                    },
                    started_round=combat.round_number,
                    duration_unit=command.duration_unit,
                    duration_value=command.duration_value,
                    ends_round=ends_round,
                    requires_concentration=command.requires_concentration,
                    status="active",
                )
                session.add(lifecycle_effect)
                session.flush()
                for combatant in combatants:
                    snapshot = dict(combatant.snapshot_json or {})
                    snapshot["summon_lifecycle_effect_id"] = lifecycle_effect.id
                    combatant.snapshot_json = snapshot
                if command.requires_concentration and source is not None:
                    source.concentration = {
                        "effect_id": lifecycle_effect.id,
                        "name": lifecycle_effect.name,
                        "started_round": combat.round_number,
                    }
                    source.version += 1
                    source.updated_at = datetime.now(UTC)
            after_order = self._ordered_combatants(session, combat_id)
            if current_id is not None:
                combat.current_turn_index = next(
                    index for index, item in enumerate(after_order) if item.id == current_id
                )
            else:
                combat.current_turn_index = 0
            combat.version += 1
            combat.updated_at = datetime.now(UTC)
            result = {
                "combatant_id": combatants[0].id,
                "combatant_ids": [item.id for item in combatants],
                "count": command.count,
                "initiative_roll": initiative_rolls[0] if len(initiative_rolls) == 1 else None,
                "initiative_rolls": initiative_rolls,
                "dexterity_modifier": (
                    int(floor((dexterity - 10) / 2))
                    if command.initiative_mode == "independent"
                    else None
                ),
                "initiative": combatants[0].initiative,
                "initiatives": [item.initiative for item in combatants],
                "initiative_mode": command.initiative_mode,
                "controller": command.controller,
                "owner_character_id": owner_id,
                "lifecycle_effect_id": (
                    lifecycle_effect.id if lifecycle_effect is not None else None
                ),
                "duration_unit": command.duration_unit,
                "duration_value": command.duration_value,
                "requires_concentration": command.requires_concentration,
                "replaced_concentration_effect_ids": [effect.id for effect in old_effects],
                "ended_summon_ids": [item.id for item in ended_summons],
            }
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=source.id if source is not None else None,
                action_type="summon",
                target_combatant_ids=[item.id for item in combatants],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation="召唤物已建立战斗模板并加入先攻顺序",
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"{name} 加入战斗（先攻 {combatants[0].initiative}）"
                    if command.count == 1
                    else f"{name} ×{command.count} 加入战斗"
                ),
                idempotency_key=idempotency_key,
                dm_override=command.controller == "dm",
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "combatant": serialize(combatants[0]),
                "combatants": [serialize(item) for item in combatants],
                "already_applied": False,
            }

    def end_summon(
        self,
        campaign_id: str,
        combat_id: str,
        summon_combatant_id: str,
        command: CombatSummonEndCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Explicitly remove one summoned combatant from the active turn order."""
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                ended_effect_ids = existing.result_json.get("ended_effect_ids", [])
                ended_effects = [
                    effect
                    for effect_id in (
                        ended_effect_ids if isinstance(ended_effect_ids, list) else []
                    )
                    if isinstance(effect_id, str)
                    and (effect := session.get(CombatEffect, effect_id)) is not None
                ]
                summon = session.get(Combatant, summon_combatant_id)
                return {
                    "action": serialize(existing),
                    "combat": serialize(combat),
                    "summon": serialize(summon) if summon is not None else None,
                    "ended_effects": [serialize(effect) for effect in ended_effects],
                    "already_applied": True,
                }

            summon = session.get(Combatant, summon_combatant_id)
            if (
                summon is None
                or summon.combat_id != combat_id
                or not self._is_summon(summon)
            ):
                raise StateNotFoundError("summon combatant not found in combat")
            if not summon.is_active:
                raise ValueError("summon is already ended")
            if summon.version != command.summon_version:
                raise VersionConflict(
                    "combatant",
                    summon.id,
                    command.summon_version,
                    summon.version,
                )

            linked_effects = [
                effect
                for effect in session.scalars(
                    select(CombatEffect).where(
                        CombatEffect.combat_id == combat_id,
                        CombatEffect.status == "active",
                    )
                ).all()
                if summon.id in self._effect_summon_ids(effect)
            ]
            before = {
                "combat": serialize(combat),
                "summon": serialize(summon),
                "linked_effects": [serialize(effect) for effect in linked_effects],
            }
            now = datetime.now(UTC)
            touched_combatants: dict[str, Combatant] = {}
            for effect in linked_effects:
                effect.status = "ended"
                effect.ended_at = now
                effect.end_reason = command.reason
                effect.version += 1
                target = session.get(Combatant, effect.target_combatant_id)
                if target is not None:
                    self._reverse_compiled_effect(session, target, effect)
                    touched_combatants[target.id] = target
                if effect.source_combatant_id is not None:
                    source = session.get(Combatant, effect.source_combatant_id)
                    if source is not None:
                        if source.concentration.get("effect_id") == effect.id:
                            source.concentration = {}
                        touched_combatants[source.id] = source
            for combatant in touched_combatants.values():
                if combatant.id != summon.id:
                    combatant.version += 1
                    combatant.updated_at = now

            deactivated = self._deactivate_summons(
                session,
                combat,
                [summon.id],
                now=now,
            )
            if not deactivated:
                raise ValueError("summon is already ended")
            active_order = self._ordered_combatants(session, combat_id)
            active = (
                active_order[combat.current_turn_index]
                if active_order and combat.current_turn_index < len(active_order)
                else None
            )
            result = {
                "combatant_id": summon.id,
                "ended_effect_ids": [effect.id for effect in linked_effects],
                "current_turn_index": combat.current_turn_index,
                "active_combatant_id": active.id if active is not None else None,
                "reason": command.reason,
            }
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_end_summon",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot=before,
                after_snapshot=result,
                reason=command.reason,
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            source_id = summon.snapshot_json.get("summon_source_combatant_id")
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=(source_id if isinstance(source_id, str) else None),
                transaction_id=transaction.id,
                action_type="end_summon",
                target_combatant_ids=[summon.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=command.reason,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{summon.display_name} 离开战斗",
                idempotency_key=idempotency_key,
                dm_override=command.actor == "dm",
                override_reason=command.reason if command.actor == "dm" else None,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "combat": serialize(combat),
                "summon": serialize(summon),
                "ended_effects": [serialize(effect) for effect in linked_effects],
                "already_applied": False,
            }

    @staticmethod
    def _combatant_owner(combatant: Combatant) -> str | None:
        if combatant.entity_type == "character":
            return combatant.entity_id
        raw = combatant.snapshot_json.get("owner_character_id")
        return str(raw) if raw else None

    @classmethod
    def _is_player_controlled(cls, combatant: Combatant) -> bool:
        if combatant.entity_type == "character":
            return True
        return (
            combatant.entity_type == "companion"
            and combatant.snapshot_json.get("controller") == "player"
            and cls._combatant_owner(combatant) is not None
        )

    @staticmethod
    def _scope(
        session: Session,
        campaign_id: str,
        combat_id: str,
        command: CombatActionCommand,
    ) -> tuple[Combat, Combatant, Combatant | None]:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        combat = session.get(Combat, combat_id)
        if combat is None or combat.campaign_id != campaign_id:
            raise StateNotFoundError("combat not found in campaign")
        target = session.get(Combatant, command.target_combatant_id)
        if target is None or target.combat_id != combat_id:
            raise StateNotFoundError("target combatant not found in combat")
        actor = None
        if command.actor_combatant_id is not None:
            actor = session.get(Combatant, command.actor_combatant_id)
            if actor is None or actor.combat_id != combat_id:
                raise StateNotFoundError("actor combatant not found in combat")
        return combat, target, actor

    @staticmethod
    def _action_window_metadata(
        action_cost: str | None,
        *,
        legendary_cost: int | None = None,
        legendary_pool_max: int | None = None,
        reaction_trigger: str | None = None,
        reaction_event: str | None = None,
    ) -> dict[str, object] | None:
        """Return the authoritative audit context for an off-turn action.

        The request already carries these fields, but the request is not what
        the DM/player combat log presents after a player roll resolves. Keep a
        small, stable copy in the result so a confirmed action remains
        self-explanatory even when its original prompt is no longer visible.
        """

        cost = (action_cost or "").strip()
        if cost not in {"reaction", "legendary_action", "lair_action"}:
            return None
        metadata: dict[str, object] = {"action_cost": cost}
        if cost == "reaction":
            event = (reaction_event or "").strip()
            if event:
                metadata["reaction_event"] = event
            trigger = (reaction_trigger or "").strip()
            if trigger:
                metadata["reaction_trigger"] = trigger
        elif cost == "legendary_action":
            if legendary_cost is not None:
                metadata["legendary_cost"] = legendary_cost
            if legendary_pool_max is not None:
                metadata["legendary_pool_max"] = legendary_pool_max
        return metadata

    @classmethod
    def _action_window_summary(
        cls,
        action_cost: str | None,
        *,
        legendary_cost: int | None = None,
        legendary_pool_max: int | None = None,
        reaction_trigger: str | None = None,
        reaction_event: str | None = None,
    ) -> str | None:
        metadata = cls._action_window_metadata(
            action_cost,
            legendary_cost=legendary_cost,
            legendary_pool_max=legendary_pool_max,
            reaction_trigger=reaction_trigger,
            reaction_event=reaction_event,
        )
        if metadata is None:
            return None
        cost = str(metadata["action_cost"])
        if cost == "reaction":
            event = metadata.get("reaction_event")
            event_label = {
                "leaves_reach": "离开近战威胁范围",
                "enters_reach": "进入近战威胁范围",
                "takes_damage": "受到伤害",
                "casts_spell": "施法",
                "turn_end": "回合结束",
            }.get(str(event), event)
            event_text = f"；结构化事件：{event_label}" if event_label else ""
            return (
                f"反应触发：{metadata.get('reaction_trigger', 'DM已确认的实际事件')}"
                f"{event_text}"
            )
        if cost == "legendary_action":
            cost_label = metadata.get("legendary_cost")
            pool_label = metadata.get("legendary_pool_max")
            return (
                f"传奇动作窗口（消耗 {cost_label} 点；动作池 {pool_label}）"
                if cost_label is not None and pool_label is not None
                else "传奇动作窗口"
            )
        return "巢穴动作窗口（本轮先攻20）"

    @staticmethod
    def _structured_advanced_action_names(
        combatant: Combatant,
        action_cost: str,
    ) -> list[str]:
        """Return names from explicitly structured advanced monster actions.

        A prose mention of a legendary or lair action is not enough to open a
        durable window.  The compendium/import pipeline records structured
        actions in the combatant snapshot, so use that same source that the
        action console and confirmation path already consume.
        """

        raw_actions = dict(combatant.snapshot_json or {}).get("actions")
        if not isinstance(raw_actions, list):
            return []
        label = "传奇动作" if action_cost == "legendary_action" else "巢穴动作"
        names: list[str] = []
        for index, raw in enumerate(raw_actions):
            if not isinstance(raw, dict):
                continue
            if str(raw.get("action_type") or "").strip() != action_cost:
                continue
            name = str(raw.get("name") or "").strip()
            names.append(name or f"未命名{label} {index + 1}")
        return names

    @staticmethod
    def _structured_reaction_actions(
        combatant: Combatant,
        reaction_event: str,
    ) -> list[dict[str, str]]:
        """Return explicitly structured reactions for one event boundary."""

        raw_actions = dict(combatant.snapshot_json or {}).get("actions")
        if not isinstance(raw_actions, list):
            return []
        result: list[dict[str, str]] = []
        for raw in raw_actions:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("action_type") or "").strip() != "reaction":
                continue
            if str(raw.get("reaction_event") or "").strip() != reaction_event:
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            action = {"name": name}
            trigger = str(raw.get("reaction_trigger") or "").strip()
            if trigger:
                action["trigger"] = trigger
            result.append(action)
        return result

    @classmethod
    def _validate_reaction_window(
        cls,
        session: Session,
        *,
        combat: Combat,
        actor: Combatant | None,
        target: Combatant,
        command: CombatActionCommand,
    ) -> CombatAction | None:
        """Validate and return the eligible window consumed by a reaction.

        A structured reaction window is an authoritative event boundary, not
        merely a UI hint.  Once the DM supplies its id, the confirmation must
        use the same reactor, event, and trigger target that opened the
        window.  The window is marked resolved by ``confirm`` after the
        damage action is flushed, so a second request cannot spend the same
        reaction twice.
        """

        window_id = (command.reaction_window_id or "").strip()
        if not window_id:
            return None
        if command.action_cost != "reaction":
            raise ValueError("reaction_window_id is only valid for a reaction")
        if actor is None:
            raise ValueError("a reaction window requires an actor")
        window = session.get(CombatAction, window_id)
        if (
            window is None
            or window.combat_id != combat.id
            or window.action_type != "eligible_action_window"
            or window.status != "confirmed"
        ):
            raise ValueError("reaction window not found or no longer eligible")
        metadata = (window.result_json or {}).get("action_window")
        if not isinstance(metadata, dict) or metadata.get("status") != "eligible":
            raise ValueError("reaction window is already resolved")
        if window.actor_combatant_id != actor.id:
            raise ValueError("reaction window belongs to another reactor")
        event = str(metadata.get("reaction_event") or "").strip()
        if not event or event != (command.reaction_event or "").strip():
            raise ValueError("reaction event does not match the eligible window")
        action_name = (command.action_name or "").strip()
        eligible_names = metadata.get("eligible_action_names")
        if (
            action_name
            and isinstance(eligible_names, list)
            and action_name not in {str(name).strip() for name in eligible_names}
        ):
            raise ValueError("action is not one of the actions opened by this reaction window")
        allowed_target_ids = {
            str(item)
            for item in (window.target_combatant_ids or [])
            if isinstance(item, str)
        }
        for key in ("trigger_combatant_id", "moving_combatant_id", "damaged_combatant_id"):
            value = metadata.get(key)
            if isinstance(value, str):
                allowed_target_ids.add(value)
        if target.id not in allowed_target_ids:
            raise ValueError("reaction target does not match the event that opened the window")
        return window

    @classmethod
    def _persist_eligible_enters_reach_reaction_windows(
        cls,
        session: Session,
        *,
        combat: Combat,
        moving_combatant: Combatant,
        from_position: tuple[int, int],
        to_position: tuple[int, int],
        movement_key: str,
        transaction: OperationTransaction | None = None,
    ) -> None:
        """Open explicit monster reaction windows when a unit enters reach.

        Movement is written by three different callers (player movement, AI
        movement, and forced movement).  Keep the temporal rule here so all
        callers use the same before/after snapshot and idempotency semantics.
        This only records an eligible window; the existing advanced-action
        confirmation path still owns the DM's trigger confirmation, target,
        rolls, and reaction consumption.
        """

        if from_position == to_position or moving_combatant.hp <= 0:
            return

        grid = (
            session.scalar(select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id))
            if combat.scene_id
            else None
        )
        cell_size = grid.cell_size_ft if grid is not None else 5

        def faction(item: Combatant) -> str:
            disposition = (item.snapshot_json or {}).get("disposition")
            if disposition in {"ally", "enemy"}:
                return str(disposition)
            return "ally" if item.entity_type in {"character", "companion"} else "enemy"

        for reactor in cls._ordered_combatants(session, combat.id):
            if (
                reactor.id == moving_combatant.id
                or reactor.entity_type != "monster"
                or reactor.hp <= 0
                or not reactor.reaction_available
                or faction(reactor) == faction(moving_combatant)
            ):
                continue
            raw_position = (reactor.snapshot_json or {}).get("grid_position")
            if not isinstance(raw_position, dict):
                continue
            try:
                reactor_position = (
                    int(raw_position["row"]),
                    int(raw_position["col"]),
                )
            except (KeyError, TypeError, ValueError):
                continue

            raw_actions = (reactor.snapshot_json or {}).get("actions")
            if not isinstance(raw_actions, list):
                continue
            eligible: list[tuple[dict[str, Any], int]] = []
            for raw in raw_actions:
                if not isinstance(raw, dict):
                    continue
                if str(raw.get("action_type") or "").strip() != "reaction":
                    continue
                if str(raw.get("reaction_event") or "").strip() != "enters_reach":
                    continue
                if raw.get("area_shape") or raw.get("affects_multiple_targets"):
                    continue
                if raw.get("ranged") is True or (
                    str(raw.get("attack_type") or "").lower() == "ranged"
                ):
                    continue
                name = str(raw.get("name") or "").strip()
                if not name:
                    continue
                raw_range = raw.get("reach_ft", raw.get("range_ft", 5))
                if isinstance(raw_range, bool):
                    continue
                try:
                    reach_ft = int(raw_range)
                except (TypeError, ValueError):
                    continue
                if reach_ft <= 0:
                    continue
                if (
                    grid_distance_ft(
                        from_position,
                        reactor_position,
                        cell_size_ft=cell_size,
                    ) > reach_ft
                    and grid_distance_ft(
                        to_position,
                        reactor_position,
                        cell_size_ft=cell_size,
                    ) <= reach_ft
                ):
                    eligible.append((raw, reach_ft))
            if not eligible:
                continue

            # A pending window already reserves this unit's one reaction.  Do
            # not create a second prompt when the mover crosses another cell
            # before the DM resolves the first one.
            open_window = False
            for existing in session.scalars(
                select(CombatAction).where(
                    CombatAction.combat_id == combat.id,
                    CombatAction.actor_combatant_id == reactor.id,
                    CombatAction.action_type == "eligible_action_window",
                    CombatAction.status == "confirmed",
                )
            ).all():
                window = (existing.result_json or {}).get("action_window")
                if (
                    isinstance(window, dict)
                    and window.get("status") == "eligible"
                    and window.get("action_cost") == "reaction"
                    and window.get("reaction_event") == "enters_reach"
                ):
                    open_window = True
                    break
            if open_window:
                continue

            key_material = f"{combat.id}:{movement_key}:{reactor.id}:enters_reach"
            idempotency_key = f"rw:enters_reach:{sha256(key_material.encode()).hexdigest()}"
            if session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat.id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            ) is not None:
                continue

            reaction_actions = [raw for raw, _ in eligible]
            reaction_metadata: dict[str, object] = {
                "action_cost": "reaction",
                "status": "eligible",
                "window_key": f"enters_reach:{movement_key}:{reactor.id}",
                "trigger": "enters_reach",
                "reaction_event": "enters_reach",
                "eligible_action_names": [
                    str(raw.get("name") or "") for raw in reaction_actions
                ],
                "reaction_ranges_ft": {
                    str(raw.get("name") or ""): reach_ft
                    for raw, reach_ft in eligible
                },
                "trigger_combatant_id": moving_combatant.id,
                "trigger_combatant_name": moving_combatant.display_name,
                "from_position": {
                    "row": from_position[0],
                    "col": from_position[1],
                },
                "to_position": {
                    "row": to_position[0],
                    "col": to_position[1],
                },
            }
            reaction_triggers = {
                str(raw.get("name") or ""): str(raw.get("reaction_trigger") or "")
                for raw in reaction_actions
                if str(raw.get("reaction_trigger") or "").strip()
            }
            if reaction_triggers:
                reaction_metadata["reaction_triggers"] = reaction_triggers
                reaction_metadata["trigger"] = next(iter(reaction_triggers.values()))
            else:
                reaction_metadata["trigger"] = "进入近战威胁范围"
            session.add(
                CombatAction(
                    campaign_id=combat.campaign_id,
                    combat_id=combat.id,
                    actor_combatant_id=reactor.id,
                    transaction_id=transaction.id if transaction is not None else None,
                    action_type="eligible_action_window",
                    target_combatant_ids=[moving_combatant.id],
                    request_json={
                        "source_action_type": "move",
                        "reaction_event": "enters_reach",
                        "moving_combatant_id": moving_combatant.id,
                        "from_position": reaction_metadata["from_position"],
                        "to_position": reaction_metadata["to_position"],
                    },
                    result_json={"action_window": reaction_metadata},
                    explanation=(
                        "仅记录明确结构化进入威胁范围反应的可触发时机；不会自动"
                        "掷骰、消耗反应或执行动作。"
                    ),
                    round_number=combat.round_number,
                    turn_index=combat.current_turn_index,
                    summary=(
                        f"{reactor.display_name}：进入近战威胁范围反应窗口已开放"
                        f"（{moving_combatant.display_name} 进入；等待 DM 确认）"
                    ),
                    idempotency_key=idempotency_key,
                    status="confirmed",
                )
            )

    @staticmethod
    def _is_structured_spell_action(
        combatant: Combatant,
        action_name: str | None,
    ) -> bool:
        """Require an explicit spell-shaped action before opening spell reactions."""

        name = (action_name or "").strip()
        if not name:
            return False
        raw_actions = dict(combatant.snapshot_json or {}).get("actions")
        if not isinstance(raw_actions, list):
            return False
        for raw in raw_actions:
            if not isinstance(raw, dict) or str(raw.get("name") or "").strip() != name:
                continue
            action_type = str(raw.get("action_type") or "").strip().lower()
            if action_type == "spellcasting" or raw.get("is_spell") is True:
                return True
            resource_key = str(raw.get("resource_key") or "").strip().lower()
            if resource_key.startswith("spell_slots_"):
                return True
            if isinstance(raw.get("spell_level"), int) and raw["spell_level"] >= 0:
                return True
        return False

    @classmethod
    def _persist_eligible_advanced_action_windows(
        cls,
        session: Session,
        *,
        combat: Combat,
        transaction: OperationTransaction,
        previous_active: Combatant | None,
        active: Combatant | None,
        ordered: list[Combatant],
    ) -> None:
        """Persist the temporal boundary for DM-confirmed advanced actions.

        These are audit events, not action executions: each row records when a
        structured legendary/lair action became eligible, while the existing
        CombatAction confirmation flow still owns target selection, rolls and
        resource consumption.
        """

        if active is None:
            return
        previous_active_id = previous_active.id if previous_active is not None else None
        previous_active_name = (
            previous_active.display_name if previous_active is not None else "上一行动单位"
        )
        active_index = next(
            (index for index, row in enumerate(ordered) if row.id == active.id),
            None,
        )
        previous_initiative = (
            ordered[active_index - 1].initiative
            if active_index is not None and active_index > 0
            else None
        )
        lair_window = active.initiative <= 20 and (
            previous_initiative is None or previous_initiative > 20
        )
        window_key = f"{combat.round_number}:{combat.current_turn_index}"

        for actor in ordered:
            if actor.entity_type != "monster" or actor.hp <= 0:
                continue
            state = dict(actor.snapshot_json or {})
            reaction_actions = cls._structured_reaction_actions(actor, "turn_end")
            if (
                reaction_actions
                and actor.reaction_available
                and previous_active_id is not None
                and actor.id != previous_active_id
            ):
                idempotency_key = (
                    f"rw:{combat.id}:{actor.id}:{combat.round_number}:"
                    f"{combat.current_turn_index}:turn_end"
                )
                existing = session.scalar(
                    select(CombatAction).where(
                        CombatAction.combat_id == combat.id,
                        CombatAction.idempotency_key == idempotency_key,
                    )
                )
                if existing is None:
                    reaction_metadata: dict[str, object] = {
                        "action_cost": "reaction",
                        "status": "eligible",
                        "window_key": window_key,
                        "trigger": "other_turn_end",
                        "reaction_event": "turn_end",
                        "eligible_action_names": [
                            action["name"] for action in reaction_actions
                        ],
                        "active_combatant_id": active.id,
                        "trigger_combatant_id": previous_active_id,
                        "trigger_combatant_name": previous_active_name,
                    }
                    reaction_triggers = {
                        action["name"]: action["trigger"]
                        for action in reaction_actions
                        if action.get("trigger")
                    }
                    if reaction_triggers:
                        reaction_metadata["reaction_triggers"] = reaction_triggers
                    session.add(
                        CombatAction(
                            campaign_id=combat.campaign_id,
                            combat_id=combat.id,
                            actor_combatant_id=actor.id,
                            transaction_id=transaction.id,
                            action_type="eligible_action_window",
                            target_combatant_ids=[],
                            request_json={
                                "source_action_type": "advance_turn",
                                "reaction_event": "turn_end",
                                "previous_active_combatant_id": previous_active_id,
                                "active_combatant_id": active.id,
                            },
                            result_json={"action_window": reaction_metadata},
                            explanation=(
                                "仅记录结构化回合结束反应的可触发时机；不会自动掷骰、"
                                "消耗反应或执行动作。"
                            ),
                            round_number=combat.round_number,
                            turn_index=combat.current_turn_index,
                            summary=(
                                f"{actor.display_name}：回合结束反应窗口已开放"
                                f"（{previous_active_name} 回合结束后；等待 DM 确认）"
                            ),
                            idempotency_key=idempotency_key,
                            status="confirmed",
                        )
                    )
            for action_cost in ("legendary_action", "lair_action"):
                action_names = cls._structured_advanced_action_names(actor, action_cost)
                if not action_names:
                    continue
                if action_cost == "legendary_action":
                    if (
                        previous_active_id is None
                        or actor.id == previous_active_id
                        or actor.id == active.id
                    ):
                        continue
                    trigger = "other_turn_end"
                else:
                    if (
                        not lair_window
                        or cls._state_int(state.get("lair_action_round"))
                        == combat.round_number
                    ):
                        continue
                    trigger = "initiative_20"

                idempotency_key = (
                    f"aw:{combat.id}:{actor.id}:{combat.round_number}:"
                    f"{combat.current_turn_index}:{action_cost}"
                )
                existing = session.scalar(
                    select(CombatAction).where(
                        CombatAction.combat_id == combat.id,
                        CombatAction.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    continue

                metadata: dict[str, object] = {
                    "action_cost": action_cost,
                    "status": "eligible",
                    "window_key": window_key,
                    "trigger": trigger,
                    "eligible_action_names": action_names,
                    "active_combatant_id": active.id,
                }
                if action_cost == "legendary_action":
                    metadata["trigger_combatant_id"] = previous_active_id
                    metadata["trigger_combatant_name"] = previous_active_name
                    pool_max = cls._state_int(state.get("legendary_actions_max"))
                    raw_actions = state.get("actions")
                    inferred_pools = {
                        raw["legendary_pool_max"]
                        for raw in raw_actions
                        if isinstance(raw, dict)
                        and isinstance(raw.get("legendary_pool_max"), int)
                        and not isinstance(raw.get("legendary_pool_max"), bool)
                        and raw["legendary_pool_max"] > 0
                    } if isinstance(raw_actions, list) else set()
                    if pool_max <= 0 and len(inferred_pools) == 1:
                        pool_max = inferred_pools.pop()
                    remaining = cls._state_int(
                        state.get("legendary_actions_remaining"),
                        pool_max,
                    )
                    if remaining <= 0:
                        continue
                    if pool_max > 0:
                        metadata["legendary_pool_max"] = pool_max
                    metadata["legendary_actions_remaining"] = remaining
                    summary = (
                        f"{actor.display_name}：传奇动作窗口已开放"
                        f"（{previous_active_name} 回合结束后；等待 DM 确认）"
                    )
                else:
                    metadata["initiative"] = active.initiative
                    metadata["eligible_round"] = combat.round_number
                    summary = (
                        f"{actor.display_name}：巢穴动作窗口已开放"
                        f"（第 {combat.round_number} 轮先攻20；等待 DM 确认）"
                    )

                session.add(
                    CombatAction(
                        campaign_id=combat.campaign_id,
                        combat_id=combat.id,
                        actor_combatant_id=actor.id,
                        transaction_id=transaction.id,
                        action_type="eligible_action_window",
                        target_combatant_ids=[],
                        request_json={
                            "source_action_type": "advance_turn",
                            "previous_active_combatant_id": (
                                previous_active.id if previous_active is not None else None
                            ),
                            "active_combatant_id": active.id,
                        },
                        result_json={"action_window": metadata},
                        explanation=(
                            "仅记录本次可触发时机；不会自动掷攻击或伤害骰，"
                            "也不会自动执行动作。"
                        ),
                        round_number=combat.round_number,
                        turn_index=combat.current_turn_index,
                        summary=summary,
                        idempotency_key=idempotency_key,
                        status="confirmed",
                    )
                )

    @classmethod
    def _persist_eligible_damage_reaction_windows(
        cls,
        session: Session,
        *,
        combat: Combat,
        transaction: OperationTransaction,
        damage_action: CombatAction,
        damaged_targets: list[tuple[Combatant, int]],
    ) -> None:
        """Open explicit ``takes_damage`` reaction windows after one damage event.

        The damage action is already authoritative when this helper runs: all
        typed segments have been resolved, HP/lifecycle changes have been
        written, and the action has been flushed.  Consequently one compound
        event creates at most one window per damaged monster, rather than one
        window per damage segment.  This records eligibility only; the normal
        DM confirmation path still owns target selection, rolls, execution and
        reaction consumption.
        """

        if not damaged_targets:
            return
        trigger_id = damage_action.actor_combatant_id
        trigger = session.get(Combatant, trigger_id) if trigger_id else None
        trigger_name = trigger.display_name if trigger is not None else "未指定来源"
        for target, adjusted_damage in damaged_targets:
            if (
                target.entity_type != "monster"
                or target.hp <= 0
                or not target.reaction_available
            ):
                continue
            reaction_actions = cls._structured_reaction_actions(
                target,
                "takes_damage",
            )
            if not reaction_actions:
                continue
            idempotency_key = (
                f"rw:{combat.id}:damage:{damage_action.id}:{target.id}:takes_damage"
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat.id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                continue
            reaction_metadata: dict[str, object] = {
                "action_cost": "reaction",
                "status": "eligible",
                "window_key": f"damage:{damage_action.id}:{target.id}",
                "trigger": "takes_damage",
                "reaction_event": "takes_damage",
                "eligible_action_names": [
                    action["name"] for action in reaction_actions
                ],
                "trigger_action_id": damage_action.id,
                "trigger_action_type": damage_action.action_type,
                "trigger_combatant_id": trigger_id,
                "trigger_combatant_name": trigger_name,
                "damaged_combatant_id": target.id,
                "damaged_combatant_name": target.display_name,
                "adjusted_damage": adjusted_damage,
            }
            reaction_triggers = {
                action["name"]: action["trigger"]
                for action in reaction_actions
                if action.get("trigger")
            }
            if reaction_triggers:
                reaction_metadata["reaction_triggers"] = reaction_triggers
            session.add(
                CombatAction(
                    campaign_id=combat.campaign_id,
                    combat_id=combat.id,
                    actor_combatant_id=target.id,
                    transaction_id=transaction.id,
                    action_type="eligible_action_window",
                    target_combatant_ids=[],
                    request_json={
                        "source_action_type": damage_action.action_type,
                        "damage_action_id": damage_action.id,
                        "reaction_event": "takes_damage",
                        "trigger_combatant_id": trigger_id,
                        "damaged_combatant_id": target.id,
                    },
                    result_json={"action_window": reaction_metadata},
                    explanation=(
                        "仅记录结构化受伤反应的可触发时机；不会自动选择目标、"
                        "掷骰、消耗反应或执行动作。"
                    ),
                    round_number=combat.round_number,
                    turn_index=combat.current_turn_index,
                    summary=(
                        f"{target.display_name}：受到伤害反应窗口已开放"
                        f"（{trigger_name} 造成 {adjusted_damage} 点实际伤害；"
                        "等待 DM 确认）"
                    ),
                    idempotency_key=idempotency_key,
                    status="confirmed",
                    # SQLite's server-side current_timestamp has only second
                    # precision. Preserve the causal order in the audit
                    # stream when the reaction window is opened in the same
                    # transaction as its damage action.
                    created_at=damage_action.created_at + timedelta(seconds=1),
                )
            )
        session.flush()

    @classmethod
    def _persist_eligible_cast_spell_reaction_windows(
        cls,
        session: Session,
        *,
        combat: Combat,
        transaction: OperationTransaction | None,
        spell_action: CombatAction,
    ) -> None:
        """Open explicit ``casts_spell`` windows when a structured spell starts."""

        caster = (
            session.get(Combatant, spell_action.actor_combatant_id)
            if spell_action.actor_combatant_id
            else None
        )
        action_name = str(spell_action.request_json.get("action_name") or "").strip()
        if caster is None or not cls._is_structured_spell_action(caster, action_name):
            return
        monsters = session.scalars(
            select(Combatant).where(
                Combatant.combat_id == combat.id,
                Combatant.entity_type == "monster",
                Combatant.is_active.is_(True),
            )
        ).all()
        for monster in monsters:
            if monster.id == caster.id or monster.hp <= 0 or not monster.reaction_available:
                continue
            reaction_actions = cls._structured_reaction_actions(monster, "casts_spell")
            if not reaction_actions:
                continue
            idempotency_key = (
                f"rw:{combat.id}:spell:{spell_action.id}:{monster.id}:casts_spell"
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat.id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                continue
            reaction_metadata: dict[str, object] = {
                "action_cost": "reaction",
                "status": "eligible",
                "window_key": f"spell:{spell_action.id}:{monster.id}",
                "trigger": "casts_spell",
                "reaction_event": "casts_spell",
                "eligible_action_names": [
                    action["name"] for action in reaction_actions
                ],
                "trigger_action_id": spell_action.id,
                "trigger_action_type": spell_action.action_type,
                "trigger_action_name": action_name,
                "trigger_combatant_id": caster.id,
                "trigger_combatant_name": caster.display_name,
            }
            reaction_triggers = {
                action["name"]: action["trigger"]
                for action in reaction_actions
                if action.get("trigger")
            }
            if reaction_triggers:
                reaction_metadata["reaction_triggers"] = reaction_triggers
            session.add(
                CombatAction(
                    campaign_id=combat.campaign_id,
                    combat_id=combat.id,
                    actor_combatant_id=monster.id,
                    transaction_id=transaction.id if transaction is not None else None,
                    action_type="eligible_action_window",
                    target_combatant_ids=[],
                    request_json={
                        "source_action_type": spell_action.action_type,
                        "spell_action_id": spell_action.id,
                        "spell_action_name": action_name,
                        "reaction_event": "casts_spell",
                        "trigger_combatant_id": caster.id,
                    },
                    result_json={"action_window": reaction_metadata},
                    explanation=(
                        "仅记录结构化施法反应的可触发时机；不会自动选择目标、"
                        "掷骰、消耗反应或执行动作。"
                    ),
                    round_number=combat.round_number,
                    turn_index=combat.current_turn_index,
                    summary=(
                        f"{monster.display_name}：施法反应窗口已开放"
                        f"（{caster.display_name} 开始施放「{action_name}」；等待 DM 确认）"
                    ),
                    idempotency_key=idempotency_key,
                    status="confirmed",
                )
            )
        session.flush()

    @classmethod
    def _validate_action_economy(
        cls,
        session: Session,
        combat: Combat,
        actor: Combatant | None,
        *,
        actor_version: int | None,
        action_cost: str,
        consume: bool,
        legendary_cost: int | None = None,
        legendary_pool_max: int | None = None,
        reaction_trigger: str | None = None,
        action_name: str | None = None,
        reaction_event: str | None = None,
    ) -> bool:
        if action_cost == "none":
            return False
        if actor is None or actor_version is None:
            raise ValueError("an actor and actor version are required to spend an action")
        if actor.version != actor_version:
            raise VersionConflict(
                "combatant",
                actor.id,
                actor_version,
                actor.version,
            )
        cls._validate_can_act(actor)
        ordered = session.scalars(
            select(Combatant)
            .where(
                Combatant.combat_id == combat.id,
                Combatant.is_active.is_(True),
            )
            .order_by(
                Combatant.initiative.desc(),
                Combatant.created_at,
                Combatant.id,
            )
        ).all()
        active = ordered[combat.current_turn_index] if ordered else None
        if action_cost in {"action", "bonus_action"} and (
            active is None or active.id != actor.id
        ):
            raise ValueError("only the active combatant can spend actions")
        if action_cost == "reaction" and not (reaction_trigger or "").strip():
            raise ValueError("a reaction requires an explicit trigger confirmed by the DM")
        if action_cost == "reaction" and action_name:
            raw_actions = (actor.snapshot_json or {}).get("actions", [])
            if isinstance(raw_actions, list):
                structured = next(
                    (
                        raw
                        for raw in raw_actions
                        if isinstance(raw, dict)
                        and str(raw.get("name") or "").strip() == action_name.strip()
                        and str(raw.get("reaction_event") or "").strip()
                    ),
                    None,
                )
                if structured is not None:
                    expected_event = str(structured["reaction_event"]).strip()
                    supplied_event = (reaction_event or "").strip()
                    if not supplied_event:
                        raise ValueError(
                            f"reaction action {action_name!r} requires its structured "
                            "reaction_event"
                        )
                    if supplied_event != expected_event:
                        raise ValueError(
                            f"reaction_event {supplied_event!r} does not match "
                            f"{action_name!r} ({expected_event!r})"
                        )
        if action_cost == "legendary_action":
            if actor.entity_type != "monster":
                raise ValueError("only monsters can spend legendary actions")
            if active is None or active.id == actor.id:
                raise ValueError(
                    "legendary actions are only available after another creature's turn"
                )
            cost = int(legendary_cost or 0)
            pool_max = int(legendary_pool_max or 0)
            if cost < 1 or pool_max < cost:
                raise ValueError("legendary action cost and pool maximum must be explicit")
            state = dict(actor.snapshot_json or {})
            stored_max = cls._state_int(state.get("legendary_actions_max"), pool_max)
            if stored_max != pool_max:
                raise ValueError("legendary action pool does not match the monster stat block")
            remaining = cls._state_int(
                state.get("legendary_actions_remaining"), pool_max
            )
            window_key = f"{combat.round_number}:{combat.current_turn_index}"
            if state.get("legendary_action_window_used") == window_key:
                raise ValueError("this monster already used a legendary action in this window")
            if remaining < cost:
                raise ValueError("not enough legendary actions remain")
            if consume:
                actor.snapshot_json = {
                    **state,
                    "legendary_actions_max": pool_max,
                    "legendary_actions_remaining": remaining - cost,
                    "legendary_action_window_used": window_key,
                }
                actor.version += 1
                actor.updated_at = datetime.now(UTC)
            return consume
        if action_cost == "lair_action":
            if actor.entity_type != "monster":
                raise ValueError("only monsters can own lair actions")
            if active is None:
                raise ValueError("lair actions require an active initiative window")
            active_index = ordered.index(active)
            previous_initiative = (
                ordered[active_index - 1].initiative if active_index > 0 else None
            )
            crossed_initiative_twenty = active.initiative <= 20 and (
                previous_initiative is None or previous_initiative > 20
            )
            if not crossed_initiative_twenty:
                raise ValueError("lair actions are only available at the initiative 20 window")
            state = dict(actor.snapshot_json or {})
            if cls._state_int(state.get("lair_action_round")) == combat.round_number:
                raise ValueError("this monster already used a lair action this round")
            if consume:
                actor.snapshot_json = {
                    **state,
                    "lair_action_round": combat.round_number,
                }
                actor.version += 1
                actor.updated_at = datetime.now(UTC)
            return consume
        field = {
            "action": "action_available",
            "bonus_action": "bonus_action_available",
            "reaction": "reaction_available",
        }.get(action_cost)
        if field is None:
            raise ValueError("unsupported action cost")
        if not bool(getattr(actor, field)):
            if action_cost == "action":
                snapshot = dict(actor.snapshot_json or {})
                attack_budget = cls._state_int(snapshot.get("attack_roll_budget"), 0)
                if attack_budget > 0:
                    if consume:
                        snapshot["attack_roll_budget"] = attack_budget - 1
                        actor.snapshot_json = snapshot
                        actor.version += 1
                        actor.updated_at = datetime.now(UTC)
                    return consume
                extra_budget = cls._state_int(snapshot.get("extra_action_budget"), 0)
                if extra_budget > 0:
                    if consume:
                        snapshot["extra_action_budget"] = extra_budget - 1
                        actor.snapshot_json = snapshot
                        actor.version += 1
                        actor.updated_at = datetime.now(UTC)
                    return consume
            raise ValueError(f"{action_cost} has already been spent this turn")
        if consume:
            setattr(actor, field, False)
            actor.version += 1
            actor.updated_at = datetime.now(UTC)
        return consume

    @staticmethod
    def _recharge_state(actor: Combatant) -> dict[str, bool] | None:
        raw = (actor.snapshot_json or {}).get("recharge_available")
        if not isinstance(raw, dict):
            return None
        return {
            str(key): value
            for key, value in raw.items()
            if isinstance(key, str) and isinstance(value, bool)
        }

    @classmethod
    def _validate_recharge(
        cls,
        actor: Combatant | None,
        *,
        recharge_key: str | None,
        consume: bool,
    ) -> bool:
        """Validate and optionally consume a structured recharge action.

        An absent recharge map represents the monster's initial state: a
        recharge action is available on its first turn. Once a map exists,
        missing or false keys are unavailable until the DM rolls recharge and
        writes the result back through the combat UI. This prevents the old
        failure mode where a parsed breath weapon silently refreshed forever.
        """

        key = (recharge_key or "").strip()
        if not key:
            return False
        if actor is None:
            raise ValueError("recharge actions require an actor")
        state = cls._recharge_state(actor)
        if state is not None and state.get(key) is not True:
            raise ValueError(f"recharge action {key!r} is not available")
        if not consume:
            return False
        next_state = dict(state or {})
        next_state[key] = False
        actor.snapshot_json = {
            **dict(actor.snapshot_json or {}),
            "recharge_available": next_state,
        }
        # Action economy already increments the actor version for ordinary
        # actions. A reaction/none action still needs a version bump for this
        # snapshot-only state transition.
        return True

    @classmethod
    def _process_monster_turn_start(
        cls,
        monster: Combatant,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Apply only fully structured recharge rolls and turn-start traits."""

        snapshot = dict(monster.snapshot_json or {})
        actions = snapshot.get("actions")
        recharge_state = snapshot.get("recharge_available")
        recharge_rolls: list[dict[str, object]] = []
        if isinstance(actions, list) and isinstance(recharge_state, dict):
            next_recharge = {
                str(key): value
                for key, value in recharge_state.items()
                if isinstance(key, str) and isinstance(value, bool)
            }
            for raw_action in actions:
                if not isinstance(raw_action, dict):
                    continue
                name = str(raw_action.get("name") or "").strip()
                recharge = raw_action.get("recharge")
                if not name or not isinstance(recharge, dict) or next_recharge.get(name) is True:
                    continue
                minimum = recharge.get("minimum")
                maximum = recharge.get("maximum", minimum)
                if (
                    not isinstance(minimum, int)
                    or not isinstance(maximum, int)
                    or minimum < 1
                    or maximum > 6
                    or minimum > maximum
                ):
                    continue
                roll = secrets.randbelow(6) + 1
                available = minimum <= roll <= maximum
                next_recharge[name] = available
                recharge_rolls.append(
                    {
                        "action_name": name,
                        "roll": roll,
                        "minimum": minimum,
                        "maximum": maximum,
                        "available": available,
                    }
                )
            snapshot["recharge_available"] = next_recharge

        trait_results: list[dict[str, object]] = []
        traits = snapshot.get("turn_start_traits")
        if isinstance(traits, list):
            resources_raw = snapshot.get("resources")
            resources = dict(resources_raw) if isinstance(resources_raw, dict) else {}
            for raw_trait in traits:
                if not isinstance(raw_trait, dict):
                    continue
                name = str(raw_trait.get("name") or "").strip()
                kind = str(raw_trait.get("kind") or "").strip()
                if not name or kind not in {"heal", "condition", "resource"}:
                    continue
                disabled = raw_trait.get("disabled_by_conditions", [])
                disabled_conditions = {
                    cls._canonical_condition(value)
                    for value in disabled
                } if isinstance(disabled, list) else set()
                if cls._condition_set(monster) & disabled_conditions:
                    trait_results.append(
                        {"name": name, "kind": kind, "applied": False, "reason": "disabled"}
                    )
                    continue
                trigger = str(raw_trait.get("trigger") or "always")
                if trigger == "hp_below_half" and monster.hp * 2 >= monster.max_hp:
                    continue
                if trigger not in {"always", "hp_below_half"}:
                    continue
                if kind == "heal":
                    amount = raw_trait.get("amount")
                    if not isinstance(amount, int) or amount < 1:
                        continue
                    before_hp = monster.hp
                    monster.hp = min(
                        max(0, monster.max_hp - monster.max_hp_reduction),
                        monster.hp + amount,
                    )
                    trait_results.append(
                        {
                            "name": name,
                            "kind": kind,
                            "applied": monster.hp != before_hp,
                            "hp_before": before_hp,
                            "hp_after": monster.hp,
                        }
                    )
                elif kind == "condition":
                    condition = str(raw_trait.get("condition") or "").strip()
                    if not condition:
                        continue
                    if cls._condition_is_immune(monster, condition):
                        trait_results.append(
                            {
                                "name": name,
                                "kind": kind,
                                "applied": False,
                                "reason": "condition_immune",
                                "condition": condition,
                            }
                        )
                        continue
                    if not cls._has_condition(monster, condition):
                        cls._apply_condition_restrictions(
                            monster,
                            condition,
                            {},
                        )
                    applied = cls._add_condition(monster, condition)
                    trait_results.append(
                        {
                            "name": name,
                            "kind": kind,
                            "applied": applied,
                            "condition": condition,
                        }
                    )
                else:
                    resource_key = str(raw_trait.get("resource_key") or "").strip()
                    restore_to = raw_trait.get("restore_to")
                    if not resource_key or not isinstance(restore_to, int) or restore_to < 0:
                        continue
                    before_resource = resources.get(resource_key)
                    resources[resource_key] = restore_to
                    trait_results.append(
                        {
                            "name": name,
                            "kind": kind,
                            "applied": before_resource != restore_to,
                            "resource_key": resource_key,
                            "before": before_resource,
                            "after": restore_to,
                        }
                    )
            if resources:
                snapshot["resources"] = resources
        monster.snapshot_json = snapshot
        return recharge_rolls, trait_results

    @classmethod
    def _validate_monster_sequence(
        cls,
        session: Session,
        combat_id: str,
        actor: Combatant | None,
        command: CombatActionCommand | PlayerRollPromptCommand,
    ) -> None:
        sequence_id = command.sequence_id
        if sequence_id is None:
            return
        if actor is None or actor.entity_type != "monster":
            raise ValueError("structured monster sequences require a monster actor")
        assert command.sequence_step is not None
        assert command.sequence_size is not None
        rows = list(
            session.scalars(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.actor_combatant_id == actor.id,
                )
            ).all()
        )
        sequence_rows = [
            row
            for row in rows
            if row.request_json.get("sequence_id") == sequence_id
        ]
        if any(
            cls._state_int(row.request_json.get("sequence_size"), -1)
            != command.sequence_size
            for row in sequence_rows
        ):
            raise ValueError("monster sequence size does not match its earlier steps")
        if any(
            cls._state_int(row.request_json.get("sequence_step"), -1)
            == command.sequence_step
            for row in sequence_rows
        ):
            raise ValueError("monster sequence step was already recorded with another request")
        completed_steps = {
            cls._state_int(row.request_json.get("sequence_step"), -1)
            for row in sequence_rows
            if row.status == "confirmed"
        }
        if command.sequence_step > 0 and command.sequence_step - 1 not in completed_steps:
            pending_step = command.sequence_step - 1
            if any(
                cls._state_int(row.request_json.get("sequence_step"), -1) == pending_step
                and row.status == "previewed"
                for row in sequence_rows
            ):
                raise ValueError(
                    "monster sequence is paused until the previous player roll is confirmed"
                )
            raise ValueError("monster sequence steps must be recorded in order")

    @classmethod
    def _validate_active_actor(
        cls,
        session: Session,
        combat: Combat,
        actor: Combatant,
        *,
        actor_version: int,
    ) -> None:
        if actor.version != actor_version:
            raise VersionConflict(
                "combatant",
                actor.id,
                actor_version,
                actor.version,
            )
        ordered = CombatEngineService._ordered_combatants(session, combat.id)
        active = ordered[combat.current_turn_index] if ordered else None
        if active is None or active.id != actor.id:
            raise ValueError("only the active combatant can use a maneuver")
        if not actor.is_active:
            raise ValueError("inactive combatants cannot use maneuvers")
        cls._validate_can_act(actor)

    @staticmethod
    def _condition_name(value: object) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            raw = value.get("name", value.get("condition_name"))
            return str(raw).strip() if raw is not None else ""
        return ""

    @classmethod
    def _canonical_condition(cls, value: object) -> str:
        name = cls._condition_name(value).strip().lower().replace("-", "_")
        return cls._CONDITION_ALIASES.get(name, name)

    @classmethod
    def _condition_set(cls, target: Combatant) -> set[str]:
        conditions = {
            canonical
            for value in list(target.conditions or [])
            if (canonical := cls._canonical_condition(value))
        }
        # These are condition consequences, not extra user-applied rows.  A
        # single source of truth here keeps action gates, attack contexts and
        # saving throws consistent without making the UI display duplicate
        # synthetic conditions.
        if "unconscious" in conditions:
            conditions.update({"incapacitated", "prone"})
        if conditions & {"stunned", "paralyzed", "petrified"}:
            conditions.add("incapacitated")
        return conditions

    @classmethod
    def _has_condition(cls, target: Combatant, condition: str) -> bool:
        return cls._canonical_condition(condition) in cls._condition_set(target)

    @classmethod
    def _condition_is_immune(cls, target: Combatant, condition: str) -> bool:
        """Return whether a target is explicitly immune to a condition."""

        canonical = cls._canonical_condition(condition)
        return bool(canonical) and canonical in {
            cls._canonical_condition(value)
            for value in list(target.condition_immunities or [])
        }

    @classmethod
    def _feature_rule_modifiers(
        cls,
        combatant: Combatant,
        *,
        stat: str,
        scope: str | None = None,
        ability: str | None = None,
    ) -> list[dict[str, object]]:
        """Return typed feature modifiers that apply to this combatant.

        Character creation freezes feature facts into ``rule_modifiers``.  The
        old combat paths retained those facts for audit but did not consume
        them, so a feature could look structured while having no rules impact.
        This helper is intentionally fail-closed: only explicit selectors and
        known condition predicates are applied; prose remains DM-owned.
        """

        raw = (combatant.snapshot_json or {}).get("rule_modifiers")
        if not isinstance(raw, dict):
            return []
        ability_aliases = {
            "力量": "strength",
            "敏捷": "dexterity",
            "体质": "constitution",
            "智力": "intelligence",
            "感知": "wisdom",
            "魅力": "charisma",
        }
        normalized_ability = str(ability or "").strip().lower()
        normalized_ability = ability_aliases.get(normalized_ability, normalized_ability)
        conditions = cls._condition_set(combatant)
        result: list[dict[str, object]] = []
        for value in raw.values():
            if not isinstance(value, dict):
                continue
            if str(value.get("stat") or "").strip() != stat:
                continue
            declared_scope = str(value.get("scope") or "all").strip()
            if scope is not None and declared_scope not in {"all", scope}:
                continue
            declared_ability = value.get("ability")
            if declared_ability is not None and normalized_ability:
                declared = str(declared_ability).strip().lower()
                declared = ability_aliases.get(declared, declared)
                if declared != normalized_ability:
                    continue
            applies_when = str(value.get("applies_when") or "").strip().lower()
            known_predicates = {
                "",
                "always",
                "not_incapacitated",
                "not incapacitated",
                "not_prone",
                "not prone",
                "wearing_armor",
                "wearing armor",
                "not_wearing_armor",
                "not wearing armor",
            }
            if applies_when not in known_predicates:
                # A typed modifier with an event predicate (for example
                # "next attack after a miss") is not a passive combat-start
                # modifier.  Keep it in the registry for a future event
                # consumer instead of granting it on every roll.
                continue
            if applies_when in {"not_incapacitated", "not incapacitated"} and (
                conditions & cls._ACTION_BLOCKING_CONDITIONS
            ):
                continue
            if applies_when in {"not_prone", "not prone"} and "prone" in conditions:
                continue
            if applies_when in {"not_wearing_armor", "not wearing armor"}:
                # The equipment snapshot is the only safe source for this
                # predicate.  Missing equipment data must not grant the
                # feature accidentally.
                equipment = (combatant.snapshot_json or {}).get("equipment")
                if not isinstance(equipment, list) or any(
                    isinstance(item, dict) and item.get("category") == "armor"
                    for item in equipment
                ):
                    continue
            if applies_when in {"wearing_armor", "wearing armor"}:
                equipment = (combatant.snapshot_json or {}).get("equipment")
                if not isinstance(equipment, list) or not any(
                    isinstance(item, dict) and item.get("category") == "armor"
                    for item in equipment
                ):
                    continue
            result.append(value)
        return result

    @classmethod
    def _feature_attack_roll_contexts(
        cls,
        actor: Combatant,
        target: Combatant,
    ) -> tuple[list[str], list[str]]:
        """Read typed class attack modifiers for the current attack."""

        advantage: list[str] = []
        disadvantage: list[str] = []
        for modifier in cls._feature_rule_modifiers(
            actor, stat="attack_roll", scope="outgoing"
        ):
            operation = str(modifier.get("operation") or "")
            source = str(modifier.get("source") or modifier.get("id") or "职业特性")
            if operation == "advantage":
                advantage.append(source)
            elif operation == "disadvantage":
                disadvantage.append(source)
        # Defensive features such as Elusive suppress an incoming advantage
        # only when their explicit predicate is satisfied.
        target_conditions = cls._condition_set(target)
        suppress_incoming = any(
            str(defense.get("kind") or "") == "suppress_attack_advantage"
            and not (
                str(defense.get("applies_when") or "").strip().lower()
                in {"not_incapacitated", "not incapacitated"}
                and target_conditions & cls._ACTION_BLOCKING_CONDITIONS
            )
            for defense in cls._feature_defenses(target)
        )
        if suppress_incoming:
            advantage.clear()
        return advantage, disadvantage

    @classmethod
    def _feature_defenses(cls, combatant: Combatant) -> list[dict[str, object]]:
        raw = (combatant.snapshot_json or {}).get("feature_runtime")
        if not isinstance(raw, dict):
            return []
        combat_start = raw.get("combat_start")
        defenses = combat_start.get("defenses") if isinstance(combat_start, dict) else None
        return [item for item in defenses or () if isinstance(item, dict)]

    @classmethod
    def _validate_can_act(cls, actor: Combatant) -> None:
        if not actor.is_active or actor.hp <= 0:
            raise ValueError("inactive or zero-HP combatants cannot take actions")
        blocked = sorted(cls._condition_set(actor) & cls._ACTION_BLOCKING_CONDITIONS)
        if blocked:
            raise ValueError(
                f"combatant cannot take actions while affected by {', '.join(blocked)}"
            )

    @classmethod
    def _condition_source_ids(
        cls,
        session: Session,
        combat_id: str,
        target: Combatant,
        condition: str,
    ) -> set[str]:
        """Return structured sources for a condition without guessing prose."""

        canonical = cls._canonical_condition(condition)
        source_ids: set[str] = set()
        effects = session.scalars(
            select(CombatEffect).where(
                CombatEffect.combat_id == combat_id,
                CombatEffect.target_combatant_id == target.id,
                CombatEffect.status == "active",
            )
        ).all()
        for effect in effects:
            state = cls._runtime_state(effect)
            if state and cls._canonical_condition(state.get("condition")) == canonical:
                if effect.source_combatant_id:
                    source_ids.add(effect.source_combatant_id)
                continue
            details = dict(effect.details_json or {})
            block = details.get("rule_block")
            if (
                isinstance(block, dict)
                and cls._canonical_condition(block.get("condition")) == canonical
            ):
                if effect.source_combatant_id:
                    source_ids.add(effect.source_combatant_id)
        return source_ids

    @classmethod
    def _validate_charmed_harm_targets(
        cls,
        session: Session,
        combat: Combat,
        actor: Combatant | None,
        target_ids: list[str],
        *,
        dm_override: bool = False,
    ) -> None:
        """Prevent structured harmful effects from targeting a charmer.

        The ordinary attack path used to enforce this rule, while damage,
        save prompts, area effects, conditions, and forced movement could use
        different paths.  Keep the rule at the shared service boundary and
        fail closed when the source of ``charmed`` is not structured: the
        engine must not guess who the charmer is.
        """

        if actor is None or dm_override or not cls._has_condition(actor, "charmed"):
            return
        source_ids = cls._condition_source_ids(session, combat.id, actor, "charmed")
        if not source_ids:
            raise ValueError("魅惑状态的来源未记录；该有害效果需要 DM 裁定")
        if source_ids.intersection(target_ids):
            raise ValueError("魅惑状态下不能对魅惑来源造成伤害、施加状态或强制移动")

    @staticmethod
    def _player_roll_is_harmful(command: object) -> bool:
        """Return whether a save prompt can damage or control its target."""

        def value(name: str, default: object = None) -> object:
            if isinstance(command, dict):
                return command.get(name, default)
            return getattr(command, name, default)

        damage = int(value("damage_on_success", 0) or 0) + int(
            value("damage_on_failure", 0) or 0
        )
        for field_name in ("damage_components_on_success", "damage_components_on_failure"):
            for component in value(field_name, []) or []:
                if isinstance(component, dict):
                    damage += int(component.get("amount", 0) or 0)
                else:
                    damage += int(getattr(component, "amount", 0) or 0)
        return bool(
            damage
            or value("conditions_on_success", [])
            or value("conditions_on_failure", [])
            or value("movement_on_success_ft") is not None
            or value("movement_on_failure_ft") is not None
        )

    @staticmethod
    def _combat_action_is_harmful(command: CombatActionCommand) -> bool:
        """Identify direct damage or structured hostile side effects."""

        return bool(
            command.action_type == "damage"
            or command.conditions_to_apply
            or command.forced_movement_distance_ft is not None
        )

    @classmethod
    def _frightened_source_visibility(
        cls,
        session: Session,
        combat: Combat,
        actor: Combatant,
    ) -> bool | None:
        """Resolve whether at least one structured fear source is visible.

        Frightened imposes attack disadvantage only while the fear source is
        visible.  Missing source, position, scene, or grid data is deliberately
        tri-state instead of being treated as visible; the caller can then
        leave the decision to the DM rather than inventing a penalty.
        """

        source_ids = cls._condition_source_ids(session, combat.id, actor, "frightened")
        if not source_ids or combat.scene_id is None:
            return None
        actor_point = cls._grid_point(actor)
        if actor_point is None:
            return None
        grid = session.scalar(
            select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id)
        )
        if grid is None:
            return None
        blockers, _ = cls._grid_obstacles(session, grid)
        visible = False
        for source_id in source_ids:
            source = session.get(Combatant, source_id)
            source_point = cls._grid_point(source) if source is not None else None
            if source_point is None:
                return None
            has_sight, _ = cls._grid_line_of_sight(
                session,
                grid,
                actor_point,
                source_point,
                blockers,
                start_height_ft=cls._explicit_grid_elevation_ft(actor),
                end_height_ft=(
                    cls._explicit_grid_elevation_ft(source)
                    if source is not None
                    else None
                ),
            )
            if has_sight:
                visible = True
        return visible

    @classmethod
    def _movement_is_blocked(cls, actor: Combatant) -> bool:
        return bool(cls._condition_set(actor) & cls._MOVEMENT_BLOCKING_CONDITIONS)

    @classmethod
    def _validate_frightened_movement(
        cls,
        session: Session,
        combat: Combat,
        actor: Combatant,
        from_position: tuple[int, int],
        to_position: tuple[int, int],
    ) -> None:
        """Reject movement that knowingly brings a frightened unit closer.

        This rule is shared by player movement and the AI movement writer.  A
        missing source, scene, or authoritative grid is intentionally a DM
        decision rather than permission to move: distance cannot safely be
        inferred from a free-form snapshot or a fallback grid size.
        """

        if not cls._has_condition(actor, "frightened"):
            return
        source_ids = cls._condition_source_ids(
            session, combat.id, actor, "frightened"
        )
        if not source_ids:
            raise ValueError("恐慌状态的来源未记录，移动方向需要 DM 裁定")
        if combat.scene_id is None:
            raise ValueError("恐慌状态缺少权威战斗场景，移动方向需要 DM 裁定")
        grid = session.scalar(
            select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id)
        )
        if grid is None:
            raise ValueError("恐慌状态缺少权威战斗网格，移动方向需要 DM 裁定")
        for source_id in source_ids:
            source = session.get(Combatant, source_id)
            source_position = cls._grid_point(source) if source is not None else None
            if source_position is None:
                raise ValueError("恐慌来源没有战斗位置，移动方向需要 DM 裁定")
            if grid_distance_ft(
                to_position, source_position, cell_size_ft=grid.cell_size_ft
            ) < grid_distance_ft(
                from_position, source_position, cell_size_ft=grid.cell_size_ft
            ):
                raise ValueError("恐慌状态下不能主动靠近恐慌来源")

    @classmethod
    def _refresh_new_turn_resources(cls, actor: Combatant) -> None:
        """Recompute a unit's turn budget after boundary effects settle.

        A turn-start condition can expire while ``advance_turn`` is processing
        the new active unit. The initial reset happens before that lifecycle
        pass, so a newly freed unit would otherwise retain a blocked action or
        zero movement for the whole turn.
        """

        movement_blocked = cls._movement_is_blocked(actor)
        actor.movement_remaining_ft = 0 if movement_blocked else actor.speed_ft
        can_act = not bool(cls._condition_set(actor) & cls._ACTION_BLOCKING_CONDITIONS)
        actor.action_available = can_act
        actor.bonus_action_available = can_act
        actor.reaction_available = can_act

    @classmethod
    def _add_condition(cls, target: Combatant, condition: str) -> bool:
        if cls._has_condition(target, condition):
            return False
        target.conditions = list(target.conditions or []) + [condition]
        return True

    @classmethod
    def _remove_condition(cls, target: Combatant, condition: str) -> bool:
        canonical = cls._canonical_condition(condition)
        current = list(target.conditions or [])
        filtered = [
            value for value in current if cls._canonical_condition(value) != canonical
        ]
        target.conditions = filtered
        return len(filtered) != len(current)

    @classmethod
    def sync_condition_state(
        cls,
        target: Combatant,
        previous_conditions: list[object] | tuple[object, ...],
    ) -> None:
        """Apply lifecycle restrictions after a direct condition-list edit.

        The DM quick editor and movement endpoint persist a complete condition
        list instead of creating a ``CombatEffect``. They still need the same
        typed restrictions as structured effects; otherwise the UI could
        display a condition without changing action economy or speed.
        """

        previous = {
            canonical
            for value in previous_conditions
            if (canonical := cls._canonical_condition(value))
        }
        current = cls._condition_set(target)
        added = current - previous
        for condition in added:
            cls._apply_condition_restrictions(target, condition, {})
        if added or current != previous:
            cls._restore_condition_restrictions(target)

    @classmethod
    def _apply_condition_restrictions(
        cls,
        target: Combatant,
        condition: str,
        before: dict[str, object],
    ) -> None:
        """Apply typed condition restrictions with a shared baseline.

        Multiple effects can own the same restriction (for example
        ``grappled`` plus ``restrained``).  A per-effect snapshot alone would
        restore the first effect's value while the second is still active.
        Keep one baseline on the combatant and restore it only after the last
        restricting condition ends.
        """

        canonical = cls._canonical_condition(condition)
        action_blocked = canonical in cls._ACTION_BLOCKING_CONDITIONS
        movement_blocked = canonical in cls._MOVEMENT_BLOCKING_CONDITIONS
        if not action_blocked and not movement_blocked:
            return
        snapshot = dict(target.snapshot_json or {})
        raw_baseline = snapshot.get("_condition_restriction_baseline")
        baseline = dict(raw_baseline) if isinstance(raw_baseline, dict) else {}
        if action_blocked:
            for field in (
                "action_available",
                "bonus_action_available",
                "reaction_available",
            ):
                before[field] = bool(getattr(target, field))
                baseline.setdefault(field, bool(getattr(target, field)))
                setattr(target, field, False)
        if movement_blocked:
            before["speed_ft"] = target.speed_ft
            before["movement_remaining_ft"] = target.movement_remaining_ft
            baseline.setdefault("speed_ft", target.speed_ft)
            baseline.setdefault("movement_remaining_ft", target.movement_remaining_ft)
            target.speed_ft = 0
            target.movement_remaining_ft = 0
        snapshot["_condition_restriction_baseline"] = baseline
        target.snapshot_json = snapshot

    @classmethod
    def _restore_condition_restrictions(
        cls,
        target: Combatant,
        applied_state: dict[str, object] | None = None,
    ) -> None:
        """Restore the shared baseline after one condition source ends."""

        conditions = cls._condition_set(target)
        raw_baseline = (target.snapshot_json or {}).get(
            "_condition_restriction_baseline"
        )
        baseline = dict(raw_baseline) if isinstance(raw_baseline, dict) else {}
        if conditions & cls._ACTION_BLOCKING_CONDITIONS:
            for field in (
                "action_available",
                "bonus_action_available",
                "reaction_available",
            ):
                setattr(target, field, False)
        else:
            for field in (
                "action_available",
                "bonus_action_available",
                "reaction_available",
            ):
                value = baseline.get(field)
                if isinstance(value, bool):
                    setattr(target, field, value)
        if conditions & cls._MOVEMENT_BLOCKING_CONDITIONS:
            target.speed_ft = 0
            target.movement_remaining_ft = 0
        else:
            speed_ft = baseline.get("speed_ft")
            movement_remaining_ft = baseline.get("movement_remaining_ft")
            if isinstance(speed_ft, int) and speed_ft >= 0:
                target.speed_ft = speed_ft
            if isinstance(movement_remaining_ft, int) and movement_remaining_ft >= 0:
                target.movement_remaining_ft = min(
                    movement_remaining_ft,
                    target.speed_ft,
                )
            elif isinstance(applied_state, dict):
                # Compatibility for effects created before the shared
                # baseline was introduced.
                fallback_speed = applied_state.get("speed_ft")
                fallback_movement = applied_state.get("movement_remaining_ft")
                if isinstance(fallback_speed, int) and fallback_speed >= 0:
                    target.speed_ft = fallback_speed
                if isinstance(fallback_movement, int) and fallback_movement >= 0:
                    target.movement_remaining_ft = min(
                        fallback_movement,
                        target.speed_ft,
                    )
        if not (
            conditions & cls._ACTION_BLOCKING_CONDITIONS
            or conditions & cls._MOVEMENT_BLOCKING_CONDITIONS
        ):
            snapshot = dict(target.snapshot_json or {})
            snapshot.pop("_condition_restriction_baseline", None)
            target.snapshot_json = snapshot

    @classmethod
    def _sync_zero_hp_lifecycle(
        cls,
        target: Combatant,
        *,
        before_hp: int,
    ) -> list[str]:
        """Keep the combatant's unconscious state tied to its HP.

        Death-save tracking already existed, but HP reaching zero was not
        reflected in the condition list.  That meant the existing action,
        movement, and attack-context rules could not see that the combatant
        was unconscious.  Summons are removed from combat instead and must not
        enter the death-save/unconscious lifecycle.
        """

        if cls._is_summon(target):
            return []
        changes: list[str] = []
        if target.hp == 0:
            if cls._add_condition(target, "昏迷"):
                cls._apply_condition_restrictions(target, "昏迷", {})
                changes.append("added:unconscious")
        elif before_hp == 0 and target.hp > 0:
            if cls._remove_condition(target, "unconscious"):
                cls._restore_condition_restrictions(target)
                changes.append("removed:unconscious")
        return changes

    @classmethod
    def _deactivate_zero_hp_non_character(
        cls,
        target: Combatant,
        *,
        now: datetime,
    ) -> bool:
        """Remove defeated non-character combatants from initiative.

        Characters at 0 HP stay in the initiative so the existing death-save
        lifecycle can prompt them.  Monsters and summons do not have that
        player death-save turn: once their HP reaches 0 they must stop being
        eligible for AI turns, targets, and movement immediately.
        """

        if (
            target.hp > 0
            or target.entity_type == "character"
            or not target.is_active
        ):
            return False
        target.is_active = False
        target.updated_at = now
        return True

    @staticmethod
    def _runtime_state(effect: CombatEffect) -> dict[str, object] | None:
        raw = dict(effect.details_json or {}).get("runtime_state")
        return dict(raw) if isinstance(raw, dict) else None

    @classmethod
    def _active_runtime_effects(
        cls,
        session: Session,
        combat_id: str,
        *,
        target_id: str | None = None,
        state_name: str | None = None,
    ) -> list[CombatEffect]:
        effects = list(
            session.scalars(
                select(CombatEffect).where(
                    CombatEffect.combat_id == combat_id,
                    CombatEffect.status == "active",
                )
            ).all()
        )
        return [
            effect
            for effect in effects
            if (target_id is None or effect.target_combatant_id == target_id)
            and (state := cls._runtime_state(effect)) is not None
            and (state_name is None or state.get("name") == state_name)
        ]

    @classmethod
    def _create_runtime_effect(
        cls,
        session: Session,
        combat: Combat,
        *,
        actor: Combatant,
        target: Combatant,
        state_name: str,
        expires: str,
        expires_combatant_id: str | None,
        details: dict[str, object] | None = None,
    ) -> CombatEffect:
        if cls._active_runtime_effects(
            session,
            combat.id,
            target_id=target.id,
            state_name=state_name,
        ):
            raise ValueError(f"combatant already has active {state_name} state")
        condition = cls._RUNTIME_STATE_CONDITIONS[state_name]
        condition_was_present = cls._has_condition(target, condition)
        applied_state: dict[str, object] = {}
        if not condition_was_present:
            cls._apply_condition_restrictions(target, condition, applied_state)
        cls._add_condition(target, condition)
        runtime_state: dict[str, object] = {
            "name": state_name,
            "condition": condition,
            "condition_was_present": condition_was_present,
            "expires": expires,
            "expires_combatant_id": expires_combatant_id,
            "created_round": combat.round_number,
            "created_turn_index": combat.current_turn_index,
            "applied_state": applied_state,
        }
        if details:
            runtime_state.update(details)
        effect = CombatEffect(
            campaign_id=combat.campaign_id,
            combat_id=combat.id,
            target_combatant_id=target.id,
            source_combatant_id=actor.id,
            name=f"{actor.display_name}：{condition}",
            effect_type="condition",
            details_json={"runtime_state": runtime_state},
            started_round=combat.round_number,
            duration_unit="until_removed",
            requires_concentration=False,
            status="active",
        )
        session.add(effect)
        session.flush()
        return effect

    @classmethod
    def _end_runtime_effect(
        cls,
        session: Session,
        effect: CombatEffect,
        *,
        reason: str,
        now: datetime,
    ) -> Combatant | None:
        if effect.status != "active":
            return None
        state = cls._runtime_state(effect)
        if state is None:
            return None
        target = session.get(Combatant, effect.target_combatant_id)
        condition = state.get("condition")
        if target is not None and isinstance(condition, str):
            # A condition is a set of active sources, not a single boolean.
            # Ending one effect must not erase a second spell, feature, or
            # monster action that still owns the same condition.
            condition_was_present = bool(state.get("condition_was_present"))
            if not condition_was_present and not cls._condition_owned_by_other_effect(
                session,
                effect,
                target,
                condition,
            ):
                cls._remove_condition(target, condition)
            applied = state.get("applied_state")
            cls._restore_condition_restrictions(
                target,
                applied if isinstance(applied, dict) else None,
            )
            target.updated_at = now
        effect.status = "ended"
        effect.ended_at = now
        effect.end_reason = reason
        effect.version += 1
        return target

    @classmethod
    def _condition_owned_by_other_effect(
        cls,
        session: Session,
        effect: CombatEffect | None,
        target: Combatant,
        condition: str,
    ) -> bool:
        """Return whether another active structured effect still owns a condition."""

        canonical = cls._canonical_condition(condition)
        active_effects = session.scalars(
            select(CombatEffect).where(
                CombatEffect.combat_id
                == (effect.combat_id if effect is not None else target.combat_id),
                CombatEffect.target_combatant_id == target.id,
                CombatEffect.status == "active",
                *(
                    (CombatEffect.id != effect.id,)
                    if effect is not None
                    else ()
                ),
            )
        ).all()
        for other in active_effects:
            state = cls._runtime_state(other)
            if state and cls._canonical_condition(state.get("condition")) == canonical:
                return True
            details = dict(other.details_json or {})
            block = details.get("rule_block")
            if (
                isinstance(block, dict)
                and str(block.get("kind") or "") == "condition"
                and str(block.get("operation") or "apply") != "remove"
                and cls._canonical_condition(block.get("condition")) == canonical
            ):
                return True
        return False

    @staticmethod
    def _effect_end_triggers(effect: CombatEffect) -> tuple[str, ...]:
        """Read explicit lifecycle predicates from either runtime shape.

        Older compiled effects put their rule block at ``details_json`` root;
        turn-boundary runtime effects put it under ``runtime_state``.  Keeping
        the lookup here lets both paths share one safe, fail-closed lifecycle
        evaluator instead of scattering condition-name heuristics through the
        turn advance code.
        """

        details = dict(effect.details_json or {})
        state = details.get("runtime_state")
        block = details.get("rule_block")
        candidates: list[object] = []
        for container in (state, block, details):
            if not isinstance(container, dict):
                continue
            for key in ("end_triggers", "ends_when"):
                raw = container.get(key)
                if isinstance(raw, list):
                    candidates.extend(raw)
                elif isinstance(raw, str):
                    candidates.append(raw)
        return tuple(
            dict.fromkeys(
                str(value).strip().lower().replace("-", "_")
                for value in candidates
                if isinstance(value, str) and value.strip()
            )
        )

    @classmethod
    def _lifecycle_end_reason(
        cls,
        session: Session,
        effect: CombatEffect,
        *,
        event_combatant_ids: set[str] | None = None,
        event_kinds: set[str] | None = None,
        event_only: bool = False,
    ) -> str | None:
        """Return the reason when an explicit condition end predicate is true.

        These predicates are deliberately narrow.  We do not infer that every
        condition ends when a creature is hurt, leaves an area, or changes
        targets; only a compiler/DM supplied predicate can trigger automatic
        cleanup.  That keeps narrative effects DM-owned while making common
        source/target death and concentration lifecycles real.
        """

        triggers = cls._effect_end_triggers(effect)
        if not triggers:
            return None
        event_ids = event_combatant_ids or set()
        kinds = event_kinds or set()
        source = (
            session.get(Combatant, effect.source_combatant_id)
            if effect.source_combatant_id
            else None
        )
        target = session.get(Combatant, effect.target_combatant_id)
        combat = session.get(Combat, effect.combat_id)
        for trigger in triggers:
            if trigger in {
                "target_takes_damage",
                "target_damaged",
                "on_target_damage",
            } and "damage" in kinds and target is not None and target.id in event_ids:
                return "状态目标受到伤害，满足显式结束条件"
            if trigger in {
                "source_takes_damage",
                "source_damaged",
                "on_source_damage",
            } and "damage" in kinds and source is not None and source.id in event_ids:
                return "状态来源受到伤害，满足显式结束条件"
            if trigger in {"target_moves", "target_moved", "on_target_move"}:
                if "movement" in kinds and target is not None and target.id in event_ids:
                    return "状态目标移动，满足显式结束条件"
            if trigger in {"source_moves", "source_moved", "on_source_move"}:
                if "movement" in kinds and source is not None and source.id in event_ids:
                    return "状态来源移动，满足显式结束条件"
            if trigger in {"target_out_of_reach", "grapple_target_out_of_reach"}:
                # Grapple is a relationship, not merely a condition string.
                # If forced movement separates the target from its grappler,
                # end it only when both positions and the authoritative grid
                # are available; missing geometry remains DM-owned.
                if (
                    "movement" not in kinds
                    or target is None
                    or target.id not in event_ids
                    or source is None
                    or combat is None
                    or combat.scene_id is None
                ):
                    continue
                source_point = cls._grid_point(source)
                target_point = cls._grid_point(target)
                grid = session.scalar(
                    select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id)
                )
                if source_point is None or target_point is None or grid is None:
                    continue
                distance_ft = grid_distance_ft(
                    source_point,
                    target_point,
                    cell_size_ft=grid.cell_size_ft,
                )
                details = dict(effect.details_json or {})
                block = details.get("rule_block")
                reach_ft = (
                    cls._state_int(block.get("reach_ft"), 5)
                    if isinstance(block, dict)
                    else 5
                )
                if distance_ft > max(5, reach_ft):
                    return f"擒抱目标被强制移动到 {distance_ft} 尺外"
            if event_only:
                continue
            if trigger in {"source_inactive", "source_dies", "source_dead"}:
                if source is None or not source.is_active or source.hp <= 0:
                    return f"状态来源满足 {trigger}"
            elif trigger == "source_unconscious":
                if source is None or cls._has_condition(source, "unconscious"):
                    return "状态来源陷入昏迷"
            elif trigger in {"target_inactive", "target_dies", "target_dead"}:
                if target is None or not target.is_active or target.hp <= 0:
                    return f"状态目标满足 {trigger}"
            elif trigger == "target_unconscious":
                if target is None or cls._has_condition(target, "unconscious"):
                    return "状态目标陷入昏迷"
            elif trigger in {"source_incapacitated", "grappler_incapacitated"}:
                if (
                    source is None
                    or not source.is_active
                    or source.hp <= 0
                    or cls._has_condition(source, "incapacitated")
                ):
                    return "擒抱来源失能、昏迷或离开战斗"
            elif trigger == "concentration_broken":
                if (
                    effect.source_combatant_id is None
                    or source is None
                    or source.concentration.get("effect_id") != effect.id
                ):
                    return "专注已中断"
        return None

    @classmethod
    def _end_predicated_effects(
        cls,
        session: Session,
        combat: Combat,
        *,
        now: datetime,
        event_combatant_ids: set[str] | None = None,
        event_kinds: set[str] | None = None,
        event_only: bool = False,
    ) -> tuple[list[CombatEffect], list[Combatant]]:
        """End only effects with an explicit satisfied lifecycle predicate."""

        ended: list[CombatEffect] = []
        changed_targets: dict[str, Combatant] = {}
        for effect in cls._active_runtime_effects(session, combat.id):
            reason = cls._lifecycle_end_reason(
                session,
                effect,
                event_combatant_ids=event_combatant_ids,
                event_kinds=event_kinds,
                event_only=event_only,
            )
            if reason is None:
                continue
            target = cls._end_runtime_effect(session, effect, reason=reason, now=now)
            if target is not None:
                changed_targets[target.id] = target
            ended.append(effect)
        for effect in session.scalars(
            select(CombatEffect).where(
                CombatEffect.combat_id == combat.id,
                CombatEffect.status == "active",
            )
        ).all():
            if effect in ended or not cls._effect_end_triggers(effect):
                continue
            reason = cls._lifecycle_end_reason(
                session,
                effect,
                event_combatant_ids=event_combatant_ids,
                event_kinds=event_kinds,
                event_only=event_only,
            )
            if reason is None:
                continue
            target = session.get(Combatant, effect.target_combatant_id)
            details = dict(effect.details_json or {})
            if target is not None and isinstance(details.get("rule_block"), dict):
                cls._reverse_compiled_effect(session, target, effect)
                changed_targets[target.id] = target
            effect.status = "ended"
            effect.ended_at = now
            effect.end_reason = reason
            effect.version += 1
            ended.append(effect)
        # Losing consciousness, dying, or leaving the combat ends every
        # concentration effect owned by that source, not only effects that
        # happened to declare a summon-specific predicate.  The event IDs
        # make this fail closed: an unrelated unconscious combatant cannot
        # clear another unit's concentration.
        lifecycle_event_ids = event_combatant_ids or set()
        if not event_only and lifecycle_event_ids:
            for effect in session.scalars(
                select(CombatEffect).where(
                    CombatEffect.combat_id == combat.id,
                    CombatEffect.status == "active",
                    CombatEffect.requires_concentration.is_(True),
                )
            ).all():
                if effect in ended or effect.source_combatant_id not in lifecycle_event_ids:
                    continue
                source = session.get(Combatant, effect.source_combatant_id)
                if (
                    source is not None
                    and source.is_active
                    and source.hp > 0
                    and not cls._has_condition(source, "incapacitated")
                ):
                    continue
                target = session.get(Combatant, effect.target_combatant_id)
                details = dict(effect.details_json or {})
                if target is not None and isinstance(details.get("rule_block"), dict):
                    cls._reverse_compiled_effect(session, target, effect)
                    changed_targets[target.id] = target
                effect.status = "ended"
                effect.ended_at = now
                effect.end_reason = "专注来源失能、失去意识或离开战斗"
                effect.version += 1
                ended.append(effect)
        # The Dodge benefit ends as soon as its owner becomes incapacitated.
        # Keep this tied to the same condition event used by direct DM edits
        # and structured save outcomes; merely displaying ``incapacitated``
        # must not leave an old Dodge runtime effect granting disadvantage.
        if not event_only and event_kinds and "condition" in event_kinds:
            for combatant_id in lifecycle_event_ids:
                subject = session.get(Combatant, combatant_id)
                if subject is None or not (
                    cls._condition_set(subject) & cls._ACTION_BLOCKING_CONDITIONS
                ):
                    continue
                for effect in cls._active_runtime_effects(
                    session,
                    combat.id,
                    target_id=subject.id,
                    state_name="dodge",
                ):
                    changed = cls._end_runtime_effect(
                        session,
                        effect,
                        reason="闪避因失能结束",
                        now=now,
                    )
                    if changed is not None:
                        changed_targets[changed.id] = changed
                    ended.append(effect)
        changed_sources: dict[str, Combatant] = {}
        for effect in ended:
            if not effect.source_combatant_id:
                continue
            source = session.get(Combatant, effect.source_combatant_id)
            if source is not None and source.concentration.get("effect_id") == effect.id:
                source.concentration = {}
                changed_sources[source.id] = source
        for target in changed_targets.values():
            target.version += 1
            target.updated_at = now
        for source in changed_sources.values():
            if source.id not in changed_targets:
                source.version += 1
            source.updated_at = now
        ended_summons = cls._deactivate_summons_for_effects(
            session,
            combat,
            ended,
            now=now,
        )
        return ended, ended_summons

    @classmethod
    def _end_lifecycles_after_condition_change(
        cls,
        session: Session,
        combat: Combat,
        *,
        target: Combatant,
        now: datetime,
    ) -> tuple[list[CombatEffect], list[Combatant]]:
        """End lifecycles immediately after a structured condition is added.

        Damage already evaluates this path in the same transaction.  A direct
        condition outcome (for example, a failed stun save) must do the same:
        an incapacitated concentrating creature loses concentration at once,
        and grapple relationships with an incapacitated source end at once.
        The generic predicate evaluator remains the single lifecycle authority.
        """

        if not cls._condition_set(target) & cls._ACTION_BLOCKING_CONDITIONS:
            return [], []
        return cls._end_predicated_effects(
            session,
            combat,
            now=now,
            event_combatant_ids={target.id},
            event_kinds={"condition"},
            event_only=False,
        )

    @classmethod
    def _reverse_compiled_effect(
        cls,
        session: Session,
        target: Combatant,
        effect: CombatEffect,
    ) -> dict[str, object]:
        """Reverse a structured effect without breaking co-existing sources."""

        details = dict(effect.details_json or {})
        block = details.get("rule_block")
        if isinstance(block, dict) and str(block.get("kind") or "") == "condition":
            condition = str(block.get("condition") or "").strip()
            condition_was_present = details.get("condition_was_present")
            applied = details.get("applied_state")
            prior_conditions = (
                applied.get("conditions")
                if isinstance(applied, dict)
                else None
            )
            if (
                condition
                and not (
                    bool(condition_was_present)
                    if isinstance(condition_was_present, bool)
                    else (
                        isinstance(prior_conditions, list)
                        and any(
                            cls._canonical_condition(value)
                            == cls._canonical_condition(condition)
                            for value in prior_conditions
                        )
                    )
                )
                and not cls._condition_owned_by_other_effect(session, effect, target, condition)
            ):
                cls._remove_condition(target, condition)
            # Some structured maneuvers use a condition block as the marker
            # for another reversible state (grapple sets speed to 0). Restore
            # that state from the same effect snapshot when the effect ends.
            cls._restore_condition_restrictions(
                target,
                applied if isinstance(applied, dict) else None,
            )
            return {}
        return cls._apply_rule_block_effect(
            target,
            details,
            remove=True,
            session=session,
            effect=effect,
        )

    @staticmethod
    def _rule_modifier_key(
        block: dict[str, object],
        details: dict[str, object] | None = None,
    ) -> str:
        """Build a source-specific key for a compiled rule modifier.

        The old key only used ``stat:scope:skill``.  That is useful for a
        character's static feature registry, but it is not enough for two
        simultaneous combat effects with the same shape: the second effect
        overwrote the first one and ending either effect restored both.  An
        effect-instance suffix keeps the existing lookup shape while making
        temporary combat modifiers independently reversible.
        """

        base = ":".join(
            str(value)
            for value in (
                block.get("stat") or "",
                block.get("scope") or "all",
                block.get("skill") or "",
            )
        )
        instance = (
            str((details or {}).get("_effect_instance_key") or "").strip()
        )
        if instance:
            return f"{base}:effect:{instance}"
        block_id = str(block.get("id") or "").strip()
        return f"{base}:block:{block_id}" if block_id else base

    @classmethod
    def _active_effects_for_rule_field(
        cls,
        session: Session,
        target: Combatant,
        *,
        kind: str,
        field: str,
    ) -> list[CombatEffect]:
        """Return compiled effects and history for one concrete field.

        Ended rows are retained only to recover the earliest baseline when a
        later stacked effect ends; the replay methods apply only rows whose
        status is still active.
        """

        effects = session.scalars(
            select(CombatEffect).where(
                CombatEffect.combat_id == target.combat_id,
                CombatEffect.target_combatant_id == target.id,
            )
        ).all()
        matched: list[CombatEffect] = []
        for effect in effects:
            details = dict(effect.details_json or {})
            block = details.get("rule_block")
            if not isinstance(block, dict) or str(block.get("kind") or "") != kind:
                continue
            if kind == "modifier" and str(block.get("stat") or "") != field:
                continue
            if kind == "defense":
                defense_field = {
                    "resistance": "damage_resistances",
                    "vulnerability": "damage_vulnerabilities",
                    "immunity": "damage_immunities",
                }.get(str(block.get("operation") or ""))
                if defense_field != field:
                    continue
            matched.append(effect)
        def order_key(row: CombatEffect) -> tuple[object, str, str]:
            raw_order = dict(row.details_json or {}).get("_effect_instance_order")
            order = (
                (0, int(raw_order))
                if isinstance(raw_order, int) and not isinstance(raw_order, bool)
                else (1, row.started_round)
            )
            return (
                order,
                row.created_at.isoformat() if row.created_at is not None else "",
                row.id,
            )

        return sorted(matched, key=order_key)

    @classmethod
    def _rebuild_numeric_rule_field(
        cls,
        session: Session,
        target: Combatant,
        effect: CombatEffect,
        *,
        field: str,
    ) -> bool:
        """Recompute a stacked AC/speed field after one effect ends.

        Replaying the remaining active effects from the earliest captured
        baseline handles both ``add`` and ``set`` effects, including ending
        the oldest effect while newer effects remain active.
        """

        effects = cls._active_effects_for_rule_field(
            session, target, kind="modifier", field=field
        )
        if not effects:
            return False
        first_details = dict(effects[0].details_json or {})
        first_applied = first_details.get("applied_state")
        baseline = (
            first_applied.get(field)
            if isinstance(first_applied, dict)
            else None
        )
        if not isinstance(baseline, int):
            return False
        value = baseline
        for row in effects:
            if row.id == effect.id or row.status != "active":
                continue
            details = dict(row.details_json or {})
            block = details.get("rule_block")
            if not isinstance(block, dict):
                continue
            row_applied = details.get("applied_state")
            if isinstance(row_applied, dict):
                row_applied = dict(row_applied)
                row_applied[field] = value
                details["applied_state"] = row_applied
                row.details_json = details
            raw_value = block.get("value")
            if not isinstance(raw_value, int):
                return False
            operation = str(block.get("operation") or "")
            if operation == "add":
                value = value + raw_value
            elif operation == "set":
                source = str(block.get("source") or "")
                value = max(value, raw_value) if "低于" in source else raw_value
            else:
                return False
        setattr(target, field, max(0, value) if field == "speed_ft" else value)
        if field == "speed_ft":
            target.movement_remaining_ft = min(
                target.movement_remaining_ft,
                target.speed_ft,
            )
        return True

    @classmethod
    def _rebuild_defense_rule_field(
        cls,
        session: Session,
        target: Combatant,
        effect: CombatEffect,
        *,
        field: str,
    ) -> bool:
        """Recompute one resistance/vulnerability/immunity field by source."""

        effects = cls._active_effects_for_rule_field(
            session, target, kind="defense", field=field
        )
        if not effects:
            return False
        first_details = dict(effects[0].details_json or {})
        first_applied = first_details.get("applied_state")
        baseline = (
            first_applied.get(field)
            if isinstance(first_applied, dict)
            else None
        )
        if not isinstance(baseline, list):
            return False
        values = {str(item) for item in baseline}
        for row in effects:
            if row.id == effect.id or row.status != "active":
                continue
            details = dict(row.details_json or {})
            block = details.get("rule_block")
            if not isinstance(block, dict):
                continue
            row_applied = details.get("applied_state")
            if isinstance(row_applied, dict):
                row_applied = dict(row_applied)
                row_applied[field] = sorted(values)
                details["applied_state"] = row_applied
                row.details_json = details
            raw_types = block.get("damage_types")
            if not isinstance(raw_types, list):
                return False
            values.update(str(item) for item in raw_types if str(item))
        setattr(target, field, sorted(values))
        return True

    @classmethod
    def _apply_structured_monster_effects(
        cls,
        session: Session,
        combat: Combat,
        *,
        actor: Combatant,
        target: Combatant,
        conditions: list[str],
        condition_duration: str | None,
        condition_duration_value: int | None = None,
        condition_save_dc: int | None = None,
        condition_save_ability: str | None = None,
        movement_distance_ft: int | None = None,
        movement_direction: str | None = None,
    ) -> dict[str, object]:
        """Apply effects whose outcome and complete lifecycle are structured.

        Turn-boundary conditions use the lightweight runtime state used by
        Dodge/Ready.  Round/minute, until-save, and until-removed conditions
        use a reversible rule block so expiry and explicit cleanup restore the
        exact pre-effect condition list instead of merely deleting a string.
        """

        result: dict[str, object] = {
            "conditions_applied": [],
            "conditions_immune": [],
            "effect_ids": [],
        }
        expires_map = {
            "actor_turn_start": ("turn_start", actor.id),
            "actor_turn_end": ("turn_end", actor.id),
            "target_turn_start": ("turn_start", target.id),
            "target_turn_end": ("turn_end", target.id),
        }
        supported_durations = {
            *expires_map,
            "rounds",
            "minutes",
            "until_save",
            "until_removed",
        }
        if conditions and condition_duration not in supported_durations:
            raise ValueError("monster condition duration is not safe to automate")
        if condition_duration in {"rounds", "minutes"} and condition_duration_value is None:
            raise ValueError("timed condition requires a duration value")
        if condition_duration == "until_save" and (
            condition_save_dc is None or not (condition_save_ability or "").strip()
        ):
            raise ValueError("until_save condition requires an explicit save DC and ability")
        expires, expires_combatant_id = expires_map.get(
            condition_duration or "", ("", None)
        )
        immune = {
            cls._canonical_condition(value)
            for value in list(target.condition_immunities or [])
        }
        for raw_condition in conditions:
            condition = str(raw_condition).strip()
            if not condition:
                continue
            if cls._canonical_condition(condition) in immune:
                cast_list = result["conditions_immune"]
                assert isinstance(cast_list, list)
                cast_list.append(condition)
                continue
            if expires:
                state_name = f"monster_condition:{condition}"
                condition_was_present = bool(
                    cls._has_condition(target, condition)
                    and not cls._condition_owned_by_other_effect(
                        session,
                        None,
                        target,
                        condition,
                    )
                )
                applied_state: dict[str, object] = {}
                if not condition_was_present:
                    cls._apply_condition_restrictions(target, condition, applied_state)
                cls._add_condition(target, condition)
                effect = CombatEffect(
                    campaign_id=combat.campaign_id,
                    combat_id=combat.id,
                    target_combatant_id=target.id,
                    source_combatant_id=actor.id,
                    name=f"{actor.display_name}：{condition}",
                    effect_type="condition",
                    details_json={
                        "runtime_state": {
                            "name": state_name,
                            "condition": condition,
                            "condition_was_present": condition_was_present,
                            "expires": expires,
                            "expires_combatant_id": expires_combatant_id,
                            "created_round": combat.round_number,
                            "created_turn_index": combat.current_turn_index,
                            "source": "structured_monster_action",
                            "applied_state": applied_state,
                        }
                    },
                    started_round=combat.round_number,
                    duration_unit="until_removed",
                    requires_concentration=False,
                    status="active",
                )
            else:
                before_conditions = list(target.conditions or [])
                condition_was_present = bool(
                    cls._has_condition(target, condition)
                    and not cls._condition_owned_by_other_effect(
                        session,
                        None,
                        target,
                        condition,
                    )
                )
                cls._add_condition(target, condition)
                applied_state: dict[str, object] = {"conditions": before_conditions}
                if not condition_was_present:
                    cls._apply_condition_restrictions(target, condition, applied_state)
                duration_unit = condition_duration or "until_removed"
                effect = CombatEffect(
                    campaign_id=combat.campaign_id,
                    combat_id=combat.id,
                    target_combatant_id=target.id,
                    source_combatant_id=actor.id,
                    name=f"{actor.display_name}：{condition}",
                    effect_type="condition",
                    details_json={
                        "rule_block": {
                            "kind": "condition",
                            "condition": condition,
                            "operation": "apply",
                        },
                        "applied_state": applied_state,
                        "condition_was_present": condition_was_present,
                        "source": "structured_monster_action",
                    },
                    started_round=combat.round_number,
                    duration_unit=duration_unit,
                    duration_value=condition_duration_value,
                    ends_round=cls._effect_ends_round(
                        combat.round_number,
                        duration_unit,
                        condition_duration_value,
                    ),
                    save_dc=condition_save_dc,
                    save_ability=condition_save_ability,
                    requires_concentration=False,
                    status="active",
                )
            session.add(effect)
            session.flush()
            applied = result["conditions_applied"]
            effect_ids = result["effect_ids"]
            assert isinstance(applied, list) and isinstance(effect_ids, list)
            applied.append(condition)
            effect_ids.append(effect.id)
        if result["conditions_applied"]:
            ended_effects, ended_summons = cls._end_lifecycles_after_condition_change(
                session,
                combat,
                target=target,
                now=datetime.now(UTC),
            )
            if ended_effects:
                result["ended_predicated_effect_ids"] = [
                    effect.id for effect in ended_effects
                ]
            if ended_summons:
                result["ended_predicated_summon_ids"] = [
                    summon.id for summon in ended_summons
                ]
        if movement_distance_ft is not None:
            if movement_direction not in {"away", "toward"}:
                raise ValueError("structured forced movement direction is required")
            if combat.scene_id is None or session.scalar(
                select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id)
            ) is None:
                raise ValueError("强制位移需要权威战斗网格，不能默认按5尺网格处理")
            result["movement"] = cls._move_away_on_grid(
                session,
                combat,
                target=target,
                source=actor,
                distance_ft=movement_distance_ft,
                direction=movement_direction,
            )
        return result

    @staticmethod
    def _grid_point(combatant: Combatant) -> tuple[int, int] | None:
        raw = (combatant.snapshot_json or {}).get("grid_position")
        if not isinstance(raw, dict):
            return None
        row = raw.get("row")
        col = raw.get("col")
        if not isinstance(row, int) or not isinstance(col, int):
            return None
        return row, col

    @staticmethod
    def _grid_size_cells(combatant: Combatant) -> int:
        """Read a combatant's authoritative square footprint without guessing.

        Combat snapshots may carry the persistent map value directly as
        ``size_cells`` or the compendium size label. Medium and smaller
        creatures occupy one square; larger labels use the standard 5e square
        footprint. Unknown values deliberately fall back to one square so
        legacy combats keep their existing geometry.
        """

        raw = combatant.snapshot_json or {}
        explicit_size = raw.get("size_cells")
        if isinstance(explicit_size, int) and not isinstance(explicit_size, bool):
            return max(1, min(4, explicit_size))
        size_label = str(raw.get("size") or "").strip().casefold()
        return {
            "tiny": 1,
            "微型": 1,
            "small": 1,
            "小型": 1,
            "medium": 1,
            "中型": 1,
            "large": 2,
            "大型": 2,
            "huge": 3,
            "巨型": 3,
            "gargantuan": 4,
            "超巨型": 4,
        }.get(size_label, 1)

    @classmethod
    def _grid_footprint(cls, combatant: Combatant) -> tuple[tuple[int, int], ...]:
        point = cls._grid_point(combatant)
        if point is None:
            return ()
        size_cells = cls._grid_size_cells(combatant)
        return tuple(
            (point[0] + row_offset, point[1] + col_offset)
            for row_offset in range(size_cells)
            for col_offset in range(size_cells)
        )

    @staticmethod
    def _grid_footprint_distance_ft(
        start: tuple[tuple[int, int], ...],
        end: tuple[tuple[int, int], ...],
        *,
        cell_size_ft: int,
    ) -> int:
        if not start or not end:
            raise ValueError("combatants need authoritative grid footprints")
        return min(
            grid_distance_ft(source, target, cell_size_ft=cell_size_ft)
            for source in start
            for target in end
        )

    @staticmethod
    def _sight_transparency(metadata: object, *, default: str) -> str:
        """Normalize explicit transparent/translucent/opaque object metadata."""

        if not isinstance(metadata, dict):
            return default
        if metadata.get("blocks_sight") is False:
            return "transparent"
        raw = metadata.get("sight_transparency")
        if not isinstance(raw, str):
            return default
        return {
            "transparent": "transparent",
            "clear": "transparent",
            "透明": "transparent",
            "translucent": "translucent",
            "semi_transparent": "translucent",
            "半透明": "translucent",
            "opaque": "opaque",
            "不透明": "opaque",
        }.get(raw.strip().casefold(), default)

    @staticmethod
    def _grid_obstacles(
        session: Session,
        grid: SceneGrid,
    ) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
        blockers: set[tuple[int, int]] = set()
        cover_cells: set[tuple[int, int]] = set()
        raw_cells = (grid.layers_json or {}).get("cells", [])
        if isinstance(raw_cells, list):
            for cell in raw_cells:
                if not isinstance(cell, dict):
                    continue
                row = cell.get("row")
                col = cell.get("col")
                if not isinstance(row, int) or not isinstance(col, int):
                    continue
                point = (row, col)
                cover_default = "translucent" if cell.get("kind") == "cover" else "transparent"
                behavior = CombatEngineService._sight_transparency(
                    cell,
                    default="opaque"
                    if cell.get("kind") == "wall" or cell.get("blocks_sight") is True
                    else cover_default,
                )
                if behavior == "translucent":
                    cover_cells.add(point)
                if behavior == "opaque":
                    blockers.add(point)
        objects = session.scalars(
            select(SceneObject).where(SceneObject.scene_id == grid.scene_id)
        ).all()
        for scene_object in objects:
            if scene_object.state in {"destroyed", "picked_up"}:
                continue
            cells = {
                (row, col)
                for row in range(
                    scene_object.row,
                    scene_object.row + scene_object.height_cells,
                )
                for col in range(
                    scene_object.col,
                    scene_object.col + scene_object.width_cells,
                )
            }
            metadata = dict(scene_object.metadata_json or {})
            if (
                scene_object.object_type == "cover"
                and scene_object.state == "active"
            ) or (
                scene_object.object_type == "furniture"
                and scene_object.state == "active"
                and metadata.get("provides_cover") is True
            ):
                if CombatEngineService._sight_transparency(
                    metadata,
                    default="translucent",
                ) != "transparent":
                    cover_cells.update(cells)
            if scene_object.object_type == "wall" or (
                scene_object.object_type == "door"
                and scene_object.state in {"active", "closed"}
            ):
                behavior = CombatEngineService._sight_transparency(
                    metadata,
                    default="opaque",
                )
                if behavior == "translucent":
                    cover_cells.update(cells)
                elif behavior == "opaque":
                    blockers.update(cells)
        return blockers, cover_cells

    @staticmethod
    def _explicit_obstacle_height_interval(
        metadata: object,
    ) -> tuple[int, int] | None:
        """Read a wall's measured vertical span without inventing its height."""

        if not isinstance(metadata, dict):
            return None

        def integer_value(*keys: str) -> int | None:
            for key in keys:
                value = metadata.get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    return value
            return None

        base_ft = integer_value(
            "base_elevation_ft",
            "bottom_elevation_ft",
            "floor_elevation_ft",
        )
        base_ft = 0 if base_ft is None else base_ft
        top_ft = integer_value("top_elevation_ft")
        if top_ft is not None:
            return (base_ft, top_ft) if top_ft > base_ft else None
        height_ft = integer_value("height_ft", "wall_height_ft")
        if height_ft is None or height_ft <= 0:
            return None
        return base_ft, base_ft + height_ft

    @classmethod
    def _grid_obstacle_height_profiles(
        cls,
        session: Session,
        grid: SceneGrid,
    ) -> tuple[dict[tuple[int, int], tuple[tuple[int, int], ...]], set[tuple[int, int]]]:
        """Return explicit wall spans and cells whose height remains unknown.

        A cell is marked unresolved when any sight-blocking source covering it
        lacks an explicit height. This lets callers use 3-D sight only when
        the complete ray is authoritative, while preserving the existing
        conservative 2-D behavior for legacy maps.
        """

        profiles: dict[tuple[int, int], list[tuple[int, int]]] = {}
        unresolved: set[tuple[int, int]] = set()

        def add_profile(cells: set[tuple[int, int]], metadata: object) -> None:
            interval = cls._explicit_obstacle_height_interval(metadata)
            for point in cells:
                if interval is None:
                    unresolved.add(point)
                else:
                    profiles.setdefault(point, []).append(interval)

        raw_cells = (grid.layers_json or {}).get("cells", [])
        if isinstance(raw_cells, list):
            for cell in raw_cells:
                if not isinstance(cell, dict):
                    continue
                behavior = cls._sight_transparency(
                    cell,
                    default="opaque"
                    if cell.get("kind") == "wall" or cell.get("blocks_sight") is True
                    else "transparent",
                )
                if behavior != "opaque":
                    continue
                row, col = cell.get("row"), cell.get("col")
                if isinstance(row, int) and isinstance(col, int):
                    add_profile({(row, col)}, cell)

        objects = session.scalars(
            select(SceneObject).where(SceneObject.scene_id == grid.scene_id)
        ).all()
        for scene_object in objects:
            if scene_object.state in {"destroyed", "picked_up"}:
                continue
            if not (
                scene_object.object_type == "wall"
                or (
                    scene_object.object_type == "door"
                    and scene_object.state in {"active", "closed"}
                )
            ):
                continue
            if cls._sight_transparency(scene_object.metadata_json, default="opaque") != "opaque":
                continue
            cells = {
                (row, col)
                for row in range(
                    scene_object.row,
                    scene_object.row + scene_object.height_cells,
                )
                for col in range(
                    scene_object.col,
                    scene_object.col + scene_object.width_cells,
                )
            }
            add_profile(cells, scene_object.metadata_json)

        return {
            point: tuple(intervals) for point, intervals in profiles.items()
        }, unresolved

    @classmethod
    def _grid_line_of_sight(
        cls,
        session: Session,
        grid: SceneGrid,
        start: tuple[int, int],
        end: tuple[int, int],
        blockers: set[tuple[int, int]],
        *,
        start_height_ft: int | None,
        end_height_ft: int | None,
    ) -> tuple[bool, str]:
        """Resolve sight and identify whether the result used 2-D or 3-D data."""

        two_d_result = line_of_sight(start, end, blockers)
        if start_height_ft is None or end_height_ft is None:
            return two_d_result, "2d"

        ray_blockers = set(line_cells(start, end)) & blockers
        profiles, unresolved = cls._grid_obstacle_height_profiles(session, grid)
        if any(point in unresolved or point not in profiles for point in ray_blockers):
            return two_d_result, "2d"
        return (
            line_of_sight_3d(
                start,
                end,
                blockers,
                profiles,
                start_height_ft=start_height_ft,
                end_height_ft=end_height_ft,
            ),
            "3d",
        )

    @classmethod
    def _grid_footprint_line_of_sight(
        cls,
        session: Session,
        grid: SceneGrid,
        start: tuple[tuple[int, int], ...],
        end: tuple[tuple[int, int], ...],
        blockers: set[tuple[int, int]],
        *,
        start_height_ft: int | None,
        end_height_ft: int | None,
    ) -> tuple[bool, str, tuple[tuple[int, int], tuple[int, int]] | None]:
        """Use any visible pair of occupied squares for large combatants."""

        modes: list[str] = []
        for source in start:
            for target in end:
                has_sight, mode = cls._grid_line_of_sight(
                    session,
                    grid,
                    source,
                    target,
                    blockers,
                    start_height_ft=start_height_ft,
                    end_height_ft=end_height_ft,
                )
                modes.append(mode)
                if has_sight:
                    return has_sight, mode, (source, target)
        return False, ("3d" if modes and all(mode == "3d" for mode in modes) else "2d"), None

    @classmethod
    def _attack_geometry(
        cls,
        session: Session,
        combat: Combat,
        command: CombatActionCommand,
        actor: Combatant,
        target: Combatant,
    ) -> dict[str, object] | None:
        """Resolve authoritative range, sight, and cover when a combat grid exists."""

        actor_point = cls._grid_point(actor)
        target_point = cls._grid_point(target)
        actor_footprint = cls._grid_footprint(actor)
        target_footprint = cls._grid_footprint(target)
        if (
            combat.scene_id is None
            or actor_point is None
            or target_point is None
            or not actor_footprint
            or not target_footprint
        ):
            return None
        grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id))
        if grid is None:
            return None
        blockers, cover_cells = cls._grid_obstacles(session, grid)
        horizontal_distance_ft = cls._grid_footprint_distance_ft(
            actor_footprint,
            target_footprint,
            cell_size_ft=grid.cell_size_ft,
        )
        actor_elevation_ft = cls._explicit_grid_elevation_ft(actor)
        target_elevation_ft = cls._explicit_grid_elevation_ft(target)
        vertical_distance_ft = (
            abs(actor_elevation_ft - target_elevation_ft)
            if actor_elevation_ft is not None and target_elevation_ft is not None
            else None
        )
        # On an authoritative 3-D grid, 5e's cube-style distance uses the
        # greatest axis distance. Missing altitude deliberately keeps the
        # established 2-D behavior instead of inventing a height.
        distance_ft = max(horizontal_distance_ft, vertical_distance_ft or 0)
        if command.attack_range_ft is not None and distance_ft > command.attack_range_ft:
            raise ValueError(
                f"target is {distance_ft} ft away, beyond the explicit "
                f"{command.attack_range_ft} ft attack range"
            )
        has_sight, line_of_sight_mode, sight_pair = cls._grid_footprint_line_of_sight(
            session,
            grid,
            actor_footprint,
            target_footprint,
            blockers,
            start_height_ft=actor_elevation_ft,
            end_height_ft=target_elevation_ft,
        )
        # A 3-D ray that passes above an explicitly measured wall is not
        # total cover merely because the legacy 2-D cell ray intersects it.
        # Keep ordinary cover cells in the calculation, while retaining the
        # conservative 2-D blocker result whenever height data is incomplete.
        cover_start, cover_end = sight_pair or (actor_point, target_point)
        cover = cover_between(
            cover_start,
            cover_end,
            cover_cells,
            blockers if line_of_sight_mode == "2d" else set(),
        )
        if (not has_sight or cover == "total") and not command.dm_override:
            raise ValueError(
                "target has total cover or no line of sight; an explicit DM override is required"
            )
        cover_bonus = 0 if command.ignore_cover else (2 if cover == "half" else 0)
        effective_armor_class = target.armor_class + cover_bonus
        if (
            command.attack_roll_total is not None
            and command.amount > 0
            and command.attack_roll_total < effective_armor_class
            and not command.dm_override
        ):
            raise ValueError(
                f"attack total {command.attack_roll_total} does not reach effective AC "
                f"{effective_armor_class}"
            )
        return {
            "distance_ft": distance_ft,
            "horizontal_distance_ft": horizontal_distance_ft,
            "vertical_distance_ft": vertical_distance_ft,
            "distance_mode": "3d" if vertical_distance_ft is not None else "2d",
            "line_of_sight": has_sight,
            "line_of_sight_mode": line_of_sight_mode,
            "line_of_sight_pair": {
                "from": {"row": cover_start[0], "col": cover_start[1]},
                "to": {"row": cover_end[0], "col": cover_end[1]},
            },
            "attacker_footprint_size_cells": cls._grid_size_cells(actor),
            "target_footprint_size_cells": cls._grid_size_cells(target),
            "cover": cover,
            "cover_bonus": cover_bonus,
            "base_armor_class": target.armor_class,
            "effective_armor_class": effective_armor_class,
        }

    @staticmethod
    def _point_in_monster_area(
        *,
        shape: str,
        origin: tuple[int, int],
        anchor: tuple[int, int],
        point: tuple[int, int],
        size_ft: int,
        width_ft: int | None,
        cell_size_ft: int,
        origin_height_ft: int = 0,
        anchor_height_ft: int = 0,
        point_height_ft: int = 0,
        height_ft: int | None = None,
    ) -> bool:
        if shape == "cube":
            if size_ft % cell_size_ft != 0:
                raise ValueError("cube size must align to the authoritative grid cell size")
            side_cells = size_ft // cell_size_ft
            horizontal = (
                anchor[0] <= point[0] < anchor[0] + side_cells
                and anchor[1] <= point[1] < anchor[1] + side_cells
            )
            vertical = anchor_height_ft <= point_height_ft < anchor_height_ft + size_ft
            return horizontal and vertical
        if shape == "sphere":
            # The anchor is the sphere's centre. Include elevation when a
            # combatant supplies it; missing elevation is the ground plane.
            row_ft = (point[0] - anchor[0]) * cell_size_ft
            col_ft = (point[1] - anchor[1]) * cell_size_ft
            vertical_ft = point_height_ft - anchor_height_ft
            return (row_ft**2 + col_ft**2 + vertical_ft**2) ** 0.5 <= size_ft
        if shape == "cylinder":
            row_ft = (point[0] - anchor[0]) * cell_size_ft
            col_ft = (point[1] - anchor[1]) * cell_size_ft
            vertical = anchor_height_ft <= point_height_ft < anchor_height_ft + (height_ft or 0)
            return hypot(row_ft, col_ft) <= size_ft and vertical
        direction_row = anchor[0] - origin[0]
        direction_col = anchor[1] - origin[1]
        direction_length = hypot(direction_row, direction_col)
        if direction_length == 0:
            raise ValueError("cone and line areas require an anchor away from the actor")
        unit_row = direction_row / direction_length
        unit_col = direction_col / direction_length
        target_row = (point[0] - origin[0]) * cell_size_ft
        target_col = (point[1] - origin[1]) * cell_size_ft
        forward_ft = target_row * unit_row + target_col * unit_col
        if forward_ft < 0 or forward_ft > size_ft:
            return False
        perpendicular_ft = abs(target_row * unit_col - target_col * unit_row)
        if shape == "line":
            assert width_ft is not None
            vertical_ft = abs(point_height_ft - origin_height_ft)
            return perpendicular_ft <= width_ft / 2 and vertical_ft <= width_ft / 2
        if shape == "cone":
            # A 5e cone is represented as a 90-degree wedge on the square grid.
            vertical_ft = abs(point_height_ft - origin_height_ft)
            return perpendicular_ft <= forward_ft and vertical_ft <= forward_ft
        raise ValueError("unsupported monster area shape")

    @classmethod
    def _footprint_in_monster_area(
        cls,
        *,
        shape: str,
        origin: tuple[int, int],
        anchor: tuple[int, int],
        footprint: tuple[tuple[int, int], ...],
        size_ft: int,
        width_ft: int | None,
        cell_size_ft: int,
        origin_height_ft: int = 0,
        anchor_height_ft: int = 0,
        point_height_ft: int = 0,
        height_ft: int | None = None,
    ) -> bool:
        """Treat an area as affecting a creature when any occupied square intersects it."""

        return any(
            cls._point_in_monster_area(
                shape=shape,
                origin=origin,
                anchor=anchor,
                point=point,
                size_ft=size_ft,
                width_ft=width_ft,
                cell_size_ft=cell_size_ft,
                origin_height_ft=origin_height_ft,
                anchor_height_ft=anchor_height_ft,
                point_height_ft=point_height_ft,
                height_ft=height_ft,
            )
            for point in footprint
        )

    @classmethod
    def _monster_area_targets(
        cls,
        session: Session,
        combat: Combat,
        actor: Combatant,
        command: MonsterAreaActionCommand,
    ) -> tuple[SceneGrid, list[Combatant], dict[str, dict[str, object]]]:
        if combat.scene_id is None:
            raise ValueError("monster area actions require an authoritative combat scene")
        grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id))
        if grid is None:
            raise ValueError("monster area actions require an authoritative combat grid")
        origin = cls._grid_point(actor)
        origin_footprint = cls._grid_footprint(actor)
        if origin is None or not origin_footprint:
            raise ValueError("monster area actor has no authoritative grid position")
        anchor = (command.anchor_row, command.anchor_col)
        origin_height_ft = cls._grid_elevation_ft(actor)
        if command.requires_explicit_elevation and cls._explicit_grid_elevation_ft(actor) is None:
            raise ValueError("高级三维区域需要记录施法者的 grid_position.elevation_ft")
        if not (1 <= anchor[0] <= grid.height and 1 <= anchor[1] <= grid.width):
            raise ValueError("area anchor is outside the combat grid")
        if command.shape == "cube":
            if command.size_ft % grid.cell_size_ft != 0:
                raise ValueError("cube size must align to the authoritative grid cell size")
            side_cells = command.size_ft // grid.cell_size_ft
            if (
                anchor[0] + side_cells - 1 > grid.height
                or anchor[1] + side_cells - 1 > grid.width
            ):
                raise ValueError("cube area extends outside the combat grid")
        blockers, _ = cls._grid_obstacles(session, grid)
        affected: list[Combatant] = []
        geometry: dict[str, dict[str, object]] = {}
        for candidate in cls._ordered_combatants(session, combat.id):
            if candidate.id == actor.id and not command.include_actor:
                continue
            point = cls._grid_point(candidate)
            if (
                command.requires_explicit_elevation
                and cls._explicit_grid_elevation_ft(candidate) is None
            ):
                raise ValueError(
                    f"高级三维区域目标 {candidate.display_name} 缺少 grid_position.elevation_ft"
                )
            point_height_ft = cls._grid_elevation_ft(candidate)
            candidate_footprint = cls._grid_footprint(candidate)
            if point is None or not candidate_footprint or not cls._footprint_in_monster_area(
                shape=command.shape,
                origin=origin,
                anchor=anchor,
                footprint=candidate_footprint,
                size_ft=command.size_ft,
                width_ft=command.width_ft,
                cell_size_ft=grid.cell_size_ft,
                origin_height_ft=origin_height_ft,
                anchor_height_ft=command.anchor_height_ft,
                point_height_ft=point_height_ft,
                height_ft=command.height_ft,
            ):
                continue
            has_sight, line_of_sight_mode, sight_pair = cls._grid_footprint_line_of_sight(
                session,
                grid,
                origin_footprint,
                candidate_footprint,
                blockers,
                start_height_ft=cls._explicit_grid_elevation_ft(actor),
                end_height_ft=cls._explicit_grid_elevation_ft(candidate),
            )
            if command.requires_line_of_sight and not has_sight:
                continue
            affected.append(candidate)
            geometry[candidate.id] = {
                "grid_position": {"row": point[0], "col": point[1]},
                "elevation_ft": point_height_ft,
                "vertical_distance_ft": abs(point_height_ft - command.anchor_height_ft),
                "distance_ft": cls._grid_footprint_distance_ft(
                    origin_footprint,
                    candidate_footprint,
                    cell_size_ft=grid.cell_size_ft,
                ),
                "line_of_sight": has_sight,
                "line_of_sight_mode": line_of_sight_mode,
                "line_of_sight_pair": (
                    {
                        "from": {"row": sight_pair[0][0], "col": sight_pair[0][1]},
                        "to": {"row": sight_pair[1][0], "col": sight_pair[1][1]},
                    }
                    if sight_pair is not None
                    else None
                ),
            }
        requested_ids = {target.target_combatant_id for target in command.targets}
        affected_ids = {target.id for target in affected}
        if requested_ids != affected_ids:
            missing = sorted(affected_ids - requested_ids)
            extra = sorted(requested_ids - affected_ids)
            raise ValueError(
                "area target list does not match authoritative geometry; "
                f"missing={missing}, outside_or_blocked={extra}"
            )
        return grid, affected, geometry

    @classmethod
    def _validate_player_roll_area_target(
        cls,
        session: Session,
        combat: Combat,
        actor: Combatant,
        target: Combatant,
        command: Any,
    ) -> dict[str, object]:
        """Validate one paused save target against the authoritative 3-D area.

        Player-roll prompts are created before the d20 is known, so they cannot
        use ``MonsterAreaActionCommand`` directly.  This preflight shares the
        same geometry primitive and rejects a 2-D-only target before a prompt
        reaches the player.  The later prompt resolution still applies each
        typed damage segment through the normal damage endpoint.
        """

        if command.area_shape is None:
            return {}
        if combat.scene_id is None:
            raise ValueError("area player-roll prompts require an authoritative combat scene")
        grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id))
        if grid is None:
            raise ValueError("area player-roll prompts require an authoritative combat grid")
        origin = cls._grid_point(actor)
        point = cls._grid_point(target)
        origin_footprint = cls._grid_footprint(actor)
        target_footprint = cls._grid_footprint(target)
        if origin is None or point is None or not origin_footprint or not target_footprint:
            raise ValueError("area target and actor both need authoritative grid positions")
        if command.requires_explicit_elevation and (
            cls._explicit_grid_elevation_ft(actor) is None
            or cls._explicit_grid_elevation_ft(target) is None
        ):
            raise ValueError(
                "高级三维区域需要施法者和目标都记录 grid_position.elevation_ft"
            )
        assert command.area_size_ft is not None
        assert command.area_anchor_row is not None
        assert command.area_anchor_col is not None
        anchor = (command.area_anchor_row, command.area_anchor_col)
        if not (1 <= anchor[0] <= grid.height and 1 <= anchor[1] <= grid.width):
            raise ValueError("area anchor is outside the combat grid")
        blockers, _ = cls._grid_obstacles(session, grid)
        if target.id == actor.id and not command.area_include_actor:
            raise ValueError("area prompt excludes its actor")
        if not cls._footprint_in_monster_area(
            shape=command.area_shape,
            origin=origin,
            anchor=anchor,
            footprint=target_footprint,
            size_ft=command.area_size_ft,
            width_ft=command.area_width_ft,
            cell_size_ft=grid.cell_size_ft,
            origin_height_ft=cls._grid_elevation_ft(actor),
            anchor_height_ft=command.area_anchor_height_ft,
            point_height_ft=cls._grid_elevation_ft(target),
            height_ft=command.area_height_ft,
        ):
            raise ValueError("player roll target is outside the authoritative 3-D area")
        has_sight, line_of_sight_mode, sight_pair = cls._grid_footprint_line_of_sight(
            session,
            grid,
            origin_footprint,
            target_footprint,
            blockers,
            start_height_ft=cls._explicit_grid_elevation_ft(actor),
            end_height_ft=cls._explicit_grid_elevation_ft(target),
        )
        if not has_sight:
            raise ValueError("player roll target is behind total cover or outside line of sight")
        return {
            "grid_position": {"row": point[0], "col": point[1]},
            "elevation_ft": cls._grid_elevation_ft(target),
            "vertical_distance_ft": abs(
                cls._grid_elevation_ft(target) - command.area_anchor_height_ft
            ),
            "distance_ft": cls._grid_footprint_distance_ft(
                origin_footprint,
                target_footprint,
                cell_size_ft=grid.cell_size_ft,
            ),
            "line_of_sight": has_sight,
            "line_of_sight_mode": line_of_sight_mode,
            "line_of_sight_pair": (
                {
                    "from": {"row": sight_pair[0][0], "col": sight_pair[0][1]},
                    "to": {"row": sight_pair[1][0], "col": sight_pair[1][1]},
                }
                if sight_pair is not None
                else None
            ),
        }

    @staticmethod
    def _grid_elevation_ft(combatant: Combatant) -> int:
        """Read an explicit vertical coordinate without inventing altitude."""

        raw = (combatant.snapshot_json or {}).get("grid_position")
        if not isinstance(raw, dict):
            return 0
        for key in ("elevation_ft", "height_ft", "z"):
            value = raw.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return 0

    @staticmethod
    def _explicit_grid_elevation_ft(combatant: Combatant) -> int | None:
        """Return saved elevation while preserving the difference from missing data."""

        raw = (combatant.snapshot_json or {}).get("grid_position")
        if not isinstance(raw, dict):
            return None
        for key in ("elevation_ft", "height_ft", "z"):
            value = raw.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return None

    @classmethod
    def _attack_contexts(
        cls,
        session: Session,
        combat: Combat,
        command: CombatActionCommand,
        actor: Combatant | None,
        target: Combatant,
    ) -> tuple[list[str], CombatEffect | None]:
        if not command.is_attack:
            return [], None
        if actor is None or command.actor_version is None:
            raise ValueError("an attack requires an actor and actor version")
        if actor.version != command.actor_version:
            raise VersionConflict(
                "combatant", actor.id, command.actor_version, actor.version
            )
        cls._validate_can_act(actor)
        cls._validate_charmed_harm_targets(
            session,
            combat,
            actor,
            [target.id],
            dm_override=command.dm_override,
        )
        contexts: list[str] = []
        adjudication_contexts: list[str] = []
        advantage_sources: list[str] = []
        disadvantage_sources: list[str] = []
        feature_advantage, feature_disadvantage = cls._feature_attack_roll_contexts(
            actor, target
        )
        if feature_advantage:
            contexts.append("feature_attack_roll_advantage")
            advantage_sources.extend(
                f"feature:{source}" for source in feature_advantage
            )
        if feature_disadvantage:
            contexts.append("feature_attack_roll_disadvantage")
            disadvantage_sources.extend(
                f"feature:{source}" for source in feature_disadvantage
            )
        geometry = cls._attack_geometry(session, combat, command, actor, target)
        if geometry is not None:
            contexts.append(f"distance_ft:{geometry['distance_ft']}")
            if geometry["distance_mode"] == "3d":
                contexts.append(f"horizontal_distance_ft:{geometry['horizontal_distance_ft']}")
                contexts.append(f"vertical_distance_ft:{geometry['vertical_distance_ft']}")
                contexts.append("distance_mode:3d")
            contexts.append(f"line_of_sight:{str(geometry['line_of_sight']).lower()}")
            contexts.append(f"line_of_sight_mode:{geometry['line_of_sight_mode']}")
            contexts.append(
                "attacker_footprint_size_cells:"
                f"{geometry['attacker_footprint_size_cells']}"
            )
            contexts.append(
                "target_footprint_size_cells:"
                f"{geometry['target_footprint_size_cells']}"
            )
            sight_pair = geometry.get("line_of_sight_pair")
            if isinstance(sight_pair, dict):
                sight_from = sight_pair.get("from")
                sight_to = sight_pair.get("to")
                if isinstance(sight_from, dict) and isinstance(sight_to, dict):
                    contexts.append(
                        "line_of_sight_pair:"
                        f"{sight_from.get('row')},{sight_from.get('col')}"
                        f"->{sight_to.get('row')},{sight_to.get('col')}"
                    )
            contexts.append(f"cover:{geometry['cover']}")
            contexts.append(f"effective_ac:{geometry['effective_armor_class']}")
            if geometry["cover"] == "half" and command.attack_roll_total is None:
                adjudication_contexts.append("target_half_cover_requires_attack_total")
        # Paralyzed and unconscious targets turn a hit from within 5 feet into
        # a critical hit.  The core DM action API receives the final damage
        # total rather than individual damage dice, so this marker is kept in
        # the authoritative result for audit/death-save handling; it must not
        # silently multiply a DM-supplied final damage number.
        if (
            geometry is not None
            and int(geometry["distance_ft"]) <= 5
            and (
                cls._has_condition(target, "paralyzed")
                or cls._has_condition(target, "unconscious")
            )
        ):
            contexts.append("automatic_critical:target_within_5ft")
        if cls._has_condition(actor, "prone"):
            contexts.append("attacker_prone")
            adjudication_contexts.append("attacker_prone")
            disadvantage_sources.append("attacker_prone")
        for condition, context in (
            ("blinded", "attacker_blinded"),
            ("poisoned", "attacker_poisoned"),
            ("restrained", "attacker_restrained"),
            ("invisible", "attacker_invisible"),
            ("frightened", "attacker_frightened_source_visibility"),
        ):
            if cls._has_condition(actor, condition):
                if condition == "frightened":
                    source_visible = cls._frightened_source_visibility(
                        session, combat, actor
                    )
                    if source_visible is True:
                        contexts.append("attacker_frightened_source_visible")
                        disadvantage_sources.append("attacker_frightened_source_visible")
                    elif source_visible is False:
                        contexts.append("attacker_frightened_source_not_visible")
                    else:
                        contexts.append(context)
                        adjudication_contexts.append(context)
                else:
                    contexts.append(context)
                    if condition in {"blinded", "poisoned", "restrained"}:
                        disadvantage_sources.append(context)
                    elif condition == "invisible":
                        advantage_sources.append(context)
        if cls._has_condition(target, "prone"):
            if geometry is not None:
                if int(geometry["distance_ft"]) <= 5:
                    contexts.append("target_prone_within_5ft")
                    advantage_sources.append("target_prone_within_5ft")
                else:
                    contexts.append("target_prone_beyond_5ft")
                    disadvantage_sources.append("target_prone_beyond_5ft")
            else:
                contexts.append("target_prone_distance_requires_dm_ruling")
                adjudication_contexts.append("target_prone_distance_requires_dm_ruling")
        for condition, context in (
            ("blinded", "target_blinded"),
            ("restrained", "target_restrained"),
            ("stunned", "target_stunned"),
            ("petrified", "target_petrified"),
            ("invisible", "target_invisible"),
            ("paralyzed", "target_paralyzed_auto_critical_within_5ft"),
            ("unconscious", "target_unconscious_auto_critical_within_5ft"),
        ):
            if cls._has_condition(target, condition):
                contexts.append(context)
                adjudication_contexts.append(context)
                if condition in {
                    "blinded",
                    "restrained",
                    "stunned",
                    "paralyzed",
                    "petrified",
                    "unconscious",
                }:
                    advantage_sources.append(context)
                elif condition == "invisible":
                    disadvantage_sources.append(context)
        if cls._active_runtime_effects(
            session, combat.id, target_id=actor.id, state_name="hidden"
        ):
            contexts.append("attacker_hidden_visibility_requires_dm_ruling")
            adjudication_contexts.append("attacker_hidden_visibility_requires_dm_ruling")
        if (
            not (cls._condition_set(target) & cls._ACTION_BLOCKING_CONDITIONS)
            and not cls._movement_is_blocked(target)
            and target.speed_ft > 0
            and cls._active_runtime_effects(
                session, combat.id, target_id=target.id, state_name="dodge"
            )
        ):
            # D&D Dodge imposes disadvantage only while the defender can see
            # the attacker.  A missing geometry result remains a DM ruling;
            # authoritative geometry must not be replaced by a guess.
            if geometry is None:
                contexts.append("target_dodging")
                adjudication_contexts.append("target_dodging")
                disadvantage_sources.append("target_dodging")
            elif geometry["line_of_sight"]:
                contexts.append("target_dodging")
                disadvantage_sources.append("target_dodging")
            else:
                contexts.append("target_dodge_no_effect_attacker_not_visible")
        help_effect: CombatEffect | None = None
        if command.help_effect_id is not None:
            help_effect = session.get(CombatEffect, command.help_effect_id)
            if (
                help_effect is None
                or help_effect.combat_id != combat.id
                or help_effect.target_combatant_id != actor.id
                or help_effect.status != "active"
                or (state := cls._runtime_state(help_effect)) is None
                or state.get("name") != "help"
            ):
                raise ValueError("Help effect is not active for this attacker")
            if help_effect.version != command.help_effect_version:
                raise VersionConflict(
                    "combat_effect",
                    help_effect.id,
                    command.help_effect_version or 0,
                    help_effect.version,
                )
            contexts.append("help_available")
            adjudication_contexts.append("help_available")
            advantage_sources.append("help_available")
        if advantage_sources or disadvantage_sources:
            expected_roll_mode = (
                "normal"
                if advantage_sources and disadvantage_sources
                else "advantage"
                if advantage_sources
                else "disadvantage"
            )
            if advantage_sources and disadvantage_sources:
                contexts.append("attack_roll_rule:normal_due_to_cancellation")
            elif advantage_sources:
                contexts.append("attack_roll_rule:advantage")
            else:
                contexts.append("attack_roll_rule:disadvantage")
            contexts.append(
                "attack_roll_advantage_sources:" + ",".join(advantage_sources)
                if advantage_sources
                else "attack_roll_advantage_sources:none"
            )
            contexts.append(
                "attack_roll_disadvantage_sources:" + ",".join(disadvantage_sources)
                if disadvantage_sources
                else "attack_roll_disadvantage_sources:none"
            )
            if (
                command.attack_roll_mode is not None
                and command.attack_roll_mode != expected_roll_mode
                and not command.dm_override
            ):
                raise ValueError(
                    "attack_roll_mode conflicts with the structured condition matrix; "
                    f"expected {expected_roll_mode}, got {command.attack_roll_mode}; "
                    "use a DM override only when another explicit source changes the result"
                )
        if adjudication_contexts and not command.dm_override and (
            command.attack_roll_mode is None
            or not (command.attack_adjudication_note or "").strip()
        ):
            raise ValueError(
                "attack context requires explicit attack_roll_mode and "
                "attack_adjudication_note; the engine will not guess advantage, "
                "distance, or visibility"
            )
        return contexts, help_effect

    @classmethod
    def _damage_defenses(
        cls,
        target: Combatant,
        command: object,
        damage_types: list[str],
        *,
        damage_tags: list[str] | None = None,
        dm_override: bool | None = None,
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], list[str], list[str]]:
        """Resolve typed and explicitly tagged conditional defenses.

        Conditional monster defenses are stored as data, never inferred from
        prose.  A matching source tag (for example ``nonmagical``) is required;
        otherwise the engine pauses unless the DM explicitly overrides it.
        """

        resistance = list(target.damage_resistances or [])
        vulnerability = list(target.damage_vulnerabilities or [])
        immunity = list(target.damage_immunities or [])
        if cls._has_condition(target, "petrified"):
            # Petrification grants resistance to all damage and immunity to
            # poison.  Expand the finite damage type set because the domain
            # resolver intentionally treats unknown strings as literal types.
            resistance.extend(
                [
                    "acid",
                    "bludgeoning",
                    "cold",
                    "fire",
                    "force",
                    "lightning",
                    "necrotic",
                    "piercing",
                    "poison",
                    "psychic",
                    "radiant",
                    "slashing",
                    "thunder",
                ]
            )
            immunity.append("poison")
        tags = {
            str(value).strip().lower()
            for value in (
                damage_tags
                if damage_tags is not None
                else getattr(command, "damage_tags", [])
            )
            if str(value).strip()
        }
        effective_dm_override = (
            bool(getattr(command, "dm_override", False))
            if dm_override is None
            else dm_override
        )
        normalized_damage_types = {str(value).strip().lower() for value in damage_types}
        applied: list[str] = []
        unresolved: list[str] = []
        raw_conditionals = target.snapshot_json.get("conditional_damage_defenses")
        conditionals = raw_conditionals if isinstance(raw_conditionals, list) else []
        for index, raw_defense in enumerate(conditionals):
            if not isinstance(raw_defense, dict):
                continue
            condition = str(raw_defense.get("condition") or "").strip()
            operation = str(raw_defense.get("operation") or "").strip()
            raw_types = raw_defense.get("damage_types")
            types = (
                [str(value).strip() for value in raw_types if str(value).strip()]
                if isinstance(raw_types, list)
                else []
            )
            if (
                not condition
                or operation not in {"resistance", "vulnerability", "immunity"}
                or not types
            ):
                continue
            if not any(value.lower() in normalized_damage_types for value in types):
                continue
            defense_label = str(raw_defense.get("id") or f"conditional_defense_{index + 1}")
            automatic_feature_condition = (
                condition.lower() in {"raging", "rage"}
                and cls._has_condition(target, "raging")
            )
            if condition.lower() not in tags and not automatic_feature_condition:
                # A typed segment may explicitly identify one source class
                # while the target carries several mutually exclusive
                # conditional defenses for the same damage type.  Once a
                # source tag is present, unrelated conditions are not an
                # unresolved rule; they simply do not apply to this segment.
                if tags:
                    continue
                unresolved.append(f"{defense_label}:{condition}")
                continue
            destination = {
                "resistance": resistance,
                "vulnerability": vulnerability,
                "immunity": immunity,
            }[operation]
            destination.extend(types)
            applied.append(f"{defense_label}:{operation}:{','.join(types)}")
        if unresolved and not effective_dm_override:
            raise ValueError(
                "目标有条件性伤害防御，必须提交 damage_tags 或 DM override："
                + "、".join(unresolved)
            )
        return tuple(resistance), tuple(vulnerability), tuple(immunity), applied, unresolved

    @classmethod
    def _resolve(
        cls,
        command: CombatActionCommand,
        target: Combatant,
    ) -> dict[str, Any]:
        before = {
            "hp": target.hp,
            "max_hp": target.max_hp,
            "max_hp_reduction": target.max_hp_reduction,
            "temporary_hp": target.temporary_hp,
            "version": target.version,
        }
        concentration_check_dc: int | None = None
        if command.action_type == "damage":
            applied_defenses: list[str] = []
            unresolved_defenses: list[str] = []
            if command.damage_components:
                component_results: list[dict[str, Any]] = []
                current_hp = target.hp
                current_temporary_hp = target.temporary_hp
                applied_component_defenses: list[str] = []
                unresolved_component_defenses: list[str] = []
                for component in command.damage_components:
                    (
                        component_resistances,
                        component_vulnerabilities,
                        component_immunities,
                        component_applied_defenses,
                        component_unresolved_defenses,
                    ) = cls._damage_defenses(
                        target,
                        command,
                        [component.damage_type],
                        damage_tags=component.damage_tags or command.damage_tags,
                    )
                    component_resolution = resolve_damage(
                        amount=component.amount,
                        current_hp=current_hp,
                        temporary_hp=current_temporary_hp,
                        damage_type=component.damage_type,
                        resistances=component_resistances,
                        vulnerabilities=component_vulnerabilities,
                        immunities=component_immunities,
                    )
                    current_hp = component_resolution.remaining_hp
                    current_temporary_hp = component_resolution.remaining_temporary_hp
                    component_result = asdict(component_resolution)
                    component_tags = list(component.damage_tags or command.damage_tags)
                    if component_tags:
                        component_result["damage_tags"] = component_tags
                    component_result["conditional_defenses_applied"] = (
                        component_applied_defenses
                    )
                    component_result["conditional_defenses_unresolved"] = (
                        component_unresolved_defenses
                    )
                    component_results.append(component_result)
                    applied_component_defenses.extend(component_applied_defenses)
                    unresolved_component_defenses.extend(component_unresolved_defenses)
                adjusted_damage = sum(item["adjusted_damage"] for item in component_results)
                modifiers = {item["modifier"] for item in component_results}
                result = {
                    "original_damage": sum(item["original_damage"] for item in component_results),
                    "adjusted_damage": adjusted_damage,
                    "damage_type": "mixed",
                    "modifier": next(iter(modifiers)) if len(modifiers) == 1 else "mixed",
                    "temporary_hp_lost": sum(
                        item["temporary_hp_lost"] for item in component_results
                    ),
                    "hp_lost": sum(item["hp_lost"] for item in component_results),
                    "remaining_temporary_hp": current_temporary_hp,
                    "remaining_hp": current_hp,
                    "unapplied_damage": sum(
                        item["unapplied_damage"] for item in component_results
                    ),
                    "explanation": "；".join(
                        item["explanation"] for item in component_results
                    ),
                    "damage_components": component_results,
                }
                if applied_component_defenses:
                    result["conditional_defenses_applied"] = list(
                        dict.fromkeys(applied_component_defenses)
                    )
                if unresolved_component_defenses:
                    result["conditional_defenses_unresolved"] = list(
                        dict.fromkeys(unresolved_component_defenses)
                    )
                if adjusted_damage > 0 and target.concentration:
                    concentration_check_dc = max(10, adjusted_damage // 2)
                after = {
                    **before,
                    "hp": current_hp,
                    "temporary_hp": current_temporary_hp,
                }
            else:
                (
                    resistances,
                    vulnerabilities,
                    immunities,
                    applied_defenses,
                    unresolved_defenses,
                ) = cls._damage_defenses(
                    target,
                    command,
                    [command.damage_type or ""],
                )
                damage_resolution = resolve_damage(
                    amount=command.amount,
                    current_hp=target.hp,
                    temporary_hp=target.temporary_hp,
                    damage_type=command.damage_type or "",
                    resistances=resistances,
                    vulnerabilities=vulnerabilities,
                    immunities=immunities,
                )
                result = asdict(damage_resolution)
                after = {
                    **before,
                    "hp": damage_resolution.remaining_hp,
                    "temporary_hp": damage_resolution.remaining_temporary_hp,
                }
                if damage_resolution.adjusted_damage > 0 and target.concentration:
                    concentration_check_dc = max(
                        10,
                        damage_resolution.adjusted_damage // 2,
                    )
            if applied_defenses:
                result["conditional_defenses_applied"] = applied_defenses
            if unresolved_defenses:
                result["conditional_defenses_unresolved"] = unresolved_defenses
        else:
            healing_resolution = resolve_healing(
                amount=command.amount,
                current_hp=target.hp,
                max_hp=target.max_hp,
                max_hp_reduction=target.max_hp_reduction,
            )
            result = asdict(healing_resolution)
            after = {**before, "hp": healing_resolution.remaining_hp}
        after["version"] = target.version + 1
        return {
            "before": before,
            "after": after,
            "result": result,
            "concentration_check_dc": concentration_check_dc,
        }

    @staticmethod
    def _death_save(session: Session, target: Combatant) -> DeathSave:
        death_save = session.scalar(
            select(DeathSave).where(DeathSave.combatant_id == target.id)
        )
        if death_save is None:
            death_save = DeathSave(combatant_id=target.id)
            session.add(death_save)
            session.flush()
        return death_save

    @staticmethod
    def _end_condition(session: Session, combat: Combat) -> dict[str, Any]:
        hostiles = [
            row
            for row in session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat.id)
                .order_by(Combatant.initiative.desc(), Combatant.id)
            )
            if row.entity_type == "monster"
            or row.snapshot_json.get("disposition") == "enemy"
        ]
        defeated = [
            row
            for row in hostiles
            if row.hp <= 0 or not row.is_active
        ]
        remaining = [row for row in hostiles if row not in defeated]
        can_end = bool(hostiles) and not remaining and combat.status == "active"
        return {
            "can_end": can_end,
            "suggested_resolution_type": "victory" if can_end else None,
            "reason": (
                "all_hostile_monsters_defeated"
                if can_end
                else "hostile_monsters_remain"
                if remaining
                else "no_hostile_monsters"
            ),
            "hostile_count": len(hostiles),
            "defeated_count": len(defeated),
            "remaining_hostiles": [
                {
                    "combatant_id": row.id,
                    "display_name": row.display_name,
                    "hp": row.hp,
                }
                for row in remaining
            ],
            "requires_dm_confirmation": can_end,
        }

    def get_end_condition(
        self,
        campaign_id: str,
        combat_id: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            return self._end_condition(session, combat)

    @staticmethod
    def _player_roll_scope(
        session: Session,
        campaign_id: str,
        combat_id: str,
        action_id: str,
    ) -> tuple[Combat, CombatAction, Combatant, Combatant]:
        combat = session.get(Combat, combat_id)
        if combat is None or combat.campaign_id != campaign_id:
            raise StateNotFoundError("combat not found in campaign")
        action = session.get(CombatAction, action_id)
        if (
            action is None
            or action.combat_id != combat_id
            or action.campaign_id != campaign_id
            or action.action_type != "player_roll_prompt"
        ):
            raise StateNotFoundError("player roll prompt not found in combat")
        actor = (
            session.get(Combatant, action.actor_combatant_id)
            if action.actor_combatant_id is not None
            else None
        )
        target_id = (
            action.target_combatant_ids[0]
            if action.target_combatant_ids
            else None
        )
        target = (
            session.get(Combatant, target_id)
            if isinstance(target_id, str)
            else None
        )
        if (
            actor is None
            or actor.combat_id != combat_id
            or target is None
            or target.combat_id != combat_id
        ):
            raise StateNotFoundError("prompt actor or target is no longer in combat")
        return combat, action, actor, target

    def create_player_roll_prompt(
        self,
        campaign_id: str,
        combat_id: str,
        command: PlayerRollPromptCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                existing_actor = (
                    session.get(Combatant, existing.actor_combatant_id)
                    if existing.actor_combatant_id
                    else None
                )
                existing_effect_target = (
                    session.get(
                        Combatant,
                        existing.request_json.get("effect_target_combatant_id"),
                    )
                    if existing.request_json.get("effect_target_combatant_id")
                    else None
                )
                return {
                    "action": serialize(existing),
                    "actor": serialize(existing_actor) if existing_actor is not None else None,
                    "effect_target": (
                        serialize(existing_effect_target)
                        if existing_effect_target is not None
                        else None
                    ),
                }
            actor = session.get(Combatant, command.actor_combatant_id)
            target = session.get(Combatant, command.target_combatant_id)
            if actor is None or actor.combat_id != combat_id:
                raise StateNotFoundError("actor combatant not found in combat")
            if target is None or target.combat_id != combat_id:
                raise StateNotFoundError("target combatant not found in combat")
            effect_target = target
            if command.effect_target_combatant_id is not None:
                effect_target = session.get(Combatant, command.effect_target_combatant_id)
                if effect_target is None or effect_target.combat_id != combat_id:
                    raise StateNotFoundError("effect target combatant not found in combat")
            if self._player_roll_is_harmful(command):
                self._validate_charmed_harm_targets(
                    session,
                    combat,
                    actor,
                    list(dict.fromkeys([target.id, effect_target.id])),
                    dm_override=command.dm_override,
                )
            # Geometry is an authoritative request-shape check, not a turn
            # mutation. Run it before optimistic-version gates so a stale
            # retry still receives the actionable area error instead of an
            # unrelated 409 from an earlier prompt.
            area_geometry = self._validate_player_roll_area_target(
                session,
                combat,
                actor,
                target,
                command,
            )
            if actor.version != command.actor_version:
                raise VersionConflict(
                    "combatant",
                    actor.id,
                    command.actor_version,
                    actor.version,
                )
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if (
                command.effect_target_version is not None
                and effect_target.version != command.effect_target_version
            ):
                raise VersionConflict(
                    "combatant",
                    effect_target.id,
                    command.effect_target_version,
                    effect_target.version,
                )
            self._validate_monster_sequence(session, combat_id, actor, command)
            economy_consumed = self._validate_action_economy(
                session,
                combat,
                actor,
                actor_version=command.actor_version,
                action_cost=command.action_cost,
                consume=True,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                action_name=command.action_name,
                reaction_event=command.reaction_event,
            )
            recharge_consumed = self._validate_recharge(
                actor,
                recharge_key=command.recharge_key,
                consume=command.recharge_consume,
            )
            if recharge_consumed and not economy_consumed:
                assert actor is not None
                actor.version += 1
                actor.updated_at = datetime.now(UTC)
            request_json = command.model_dump(mode="json")
            if area_geometry:
                request_json["area_geometry"] = area_geometry
            request_json["actor_name"] = actor.display_name
            request_json["target_name"] = target.display_name
            request_json["effect_target_name"] = effect_target.display_name
            action_window = self._action_window_metadata(
                command.action_cost,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                reaction_event=command.reaction_event,
            )
            window_summary = self._action_window_summary(
                command.action_cost,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                reaction_event=command.reaction_event,
            )
            label = {
                "armor_class": "AC 防御",
                "saving_throw": f"{command.ability or ''}豁免",
                "ability_check": f"{command.ability or ''}属性检定",
                "skill_check": f"{command.skill or ''}技能检定",
            }[command.resolution_type]
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=actor.id,
                action_type="player_roll_prompt",
                target_combatant_ids=[target.id],
                request_json=request_json,
                result_json={
                    "phase": "awaiting_player_roll",
                    "roll_owner": "player",
                    **({"action_window": action_window} if action_window is not None else {}),
                },
                explanation=command.description,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"{actor.display_name} 对 {target.display_name} 使用"
                    f"「{command.action_name}」；等待玩家进行 {label}"
                    f"（{command.roll_formula}，DC {command.dc}）"
                    + (f"；{window_summary}" if window_summary else "")
                ),
                idempotency_key=idempotency_key,
                status="previewed",
            )
            session.add(action)
            session.flush()
            self._persist_eligible_cast_spell_reaction_windows(
                session,
                combat=combat,
                transaction=None,
                spell_action=action,
            )
            return {
                "action": serialize(action),
                "actor": serialize(actor),
                "target": serialize(target),
                "effect_target": serialize(effect_target),
            }

    @staticmethod
    def _batch_player_roll_prompt_key(idempotency_key: str, index: int) -> str:
        """Give every child prompt a stable, collision-resistant request key."""

        digest = sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"player-roll-batch:{digest}:{index}"

    def create_player_roll_prompt_batch(
        self,
        campaign_id: str,
        combat_id: str,
        command: PlayerRollPromptBatchCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Atomically queue all player saves for one multi-target action.

        A multi-target saving throw must not create the first prompt or spend
        an action if a later target turns out to be stale or outside the
        authoritative 3-D area.  The complete batch is therefore preflighted
        against a single session snapshot, then one action resource is spent
        and all prompt rows are inserted under the same transaction.
        """

        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")

        prompt_template = command.model_dump(mode="json", exclude={"targets"})
        prompts = [
            PlayerRollPromptCommand(
                **prompt_template,
                target_combatant_id=target.target_combatant_id,
                target_version=target.target_version,
                effect_target_combatant_id=target.effect_target_combatant_id,
                effect_target_version=target.effect_target_version,
            )
            for target in command.targets
        ]

        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")

            existing_transaction = session.scalar(
                select(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign_id,
                    OperationTransaction.idempotency_key == idempotency_key,
                )
            )
            if existing_transaction is not None:
                if (
                    existing_transaction.operation_type
                    != "combat_player_roll_prompt_batch"
                    or existing_transaction.after_snapshot.get("combat_id") != combat_id
                ):
                    raise ValueError("idempotency key was already used by a different operation")
                action_ids = existing_transaction.after_snapshot.get("action_ids")
                target_ids = existing_transaction.after_snapshot.get("target_ids")
                actor_id = existing_transaction.after_snapshot.get("actor_combatant_id")
                if (
                    not isinstance(action_ids, list)
                    or not isinstance(target_ids, list)
                    or not isinstance(actor_id, str)
                ):
                    raise ValueError("batch player-roll transaction is incomplete")
                actions: list[CombatAction] = []
                for action_id in action_ids:
                    if not isinstance(action_id, str):
                        raise ValueError("batch player-roll transaction is incomplete")
                    action = session.get(CombatAction, action_id)
                    if (
                        action is None
                        or action.combat_id != combat_id
                        or action.transaction_id != existing_transaction.id
                    ):
                        raise ValueError("batch player-roll transaction is incomplete")
                    actions.append(action)
                actor = session.get(Combatant, actor_id)
                if actor is None or actor.combat_id != combat_id:
                    raise StateNotFoundError("prompt actor is no longer in combat")
                targets: list[Combatant] = []
                for target_id in target_ids:
                    if not isinstance(target_id, str):
                        raise ValueError("batch player-roll transaction is incomplete")
                    target = session.get(Combatant, target_id)
                    if target is None or target.combat_id != combat_id:
                        raise StateNotFoundError("prompt target is no longer in combat")
                    targets.append(target)
                return {
                    "actions": [serialize(action) for action in actions],
                    "actor": serialize(actor),
                    "targets": [serialize(target) for target in targets],
                    "transaction": serialize(existing_transaction),
                    "already_applied": True,
                }

            actor = session.get(Combatant, command.actor_combatant_id)
            if actor is None or actor.combat_id != combat_id:
                raise StateNotFoundError("actor combatant not found in combat")

            prepared: list[
                tuple[PlayerRollPromptCommand, Combatant, Combatant, dict[str, object]]
            ] = []
            for prompt in prompts:
                target = session.get(Combatant, prompt.target_combatant_id)
                if target is None or target.combat_id != combat_id:
                    raise StateNotFoundError("target combatant not found in combat")
                effect_target = target
                if prompt.effect_target_combatant_id is not None:
                    effect_target = session.get(Combatant, prompt.effect_target_combatant_id)
                    if effect_target is None or effect_target.combat_id != combat_id:
                        raise StateNotFoundError("effect target combatant not found in combat")
                # Match the single-prompt endpoint's order: geometry errors
                # take precedence over stale versions, and every target is
                # checked before any resource can be consumed.
                area_geometry = self._validate_player_roll_area_target(
                    session,
                    combat,
                    actor,
                    target,
                    prompt,
                )
                prepared.append((prompt, target, effect_target, area_geometry))

            if any(self._player_roll_is_harmful(prompt) for prompt in prompts):
                self._validate_charmed_harm_targets(
                    session,
                    combat,
                    actor,
                    list(
                        dict.fromkeys(
                            target_id
                            for _, target, effect_target, _ in prepared
                            for target_id in (target.id, effect_target.id)
                        )
                    ),
                    dm_override=command.dm_override,
                )

            if actor.version != command.actor_version:
                raise VersionConflict(
                    "combatant",
                    actor.id,
                    command.actor_version,
                    actor.version,
                )
            for prompt, target, effect_target, _ in prepared:
                if target.version != prompt.target_version:
                    raise VersionConflict(
                        "combatant",
                        target.id,
                        prompt.target_version,
                        target.version,
                    )
                if (
                    prompt.effect_target_version is not None
                    and effect_target.version != prompt.effect_target_version
                ):
                    raise VersionConflict(
                        "combatant",
                        effect_target.id,
                        prompt.effect_target_version,
                        effect_target.version,
                    )

            self._validate_monster_sequence(session, combat_id, actor, prompts[0])
            self._validate_action_economy(
                session,
                combat,
                actor,
                actor_version=command.actor_version,
                action_cost=command.action_cost,
                consume=False,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                action_name=command.action_name,
                reaction_event=command.reaction_event,
            )
            self._validate_recharge(
                actor,
                recharge_key=command.recharge_key,
                consume=False,
            )

            now = datetime.now(UTC)
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_player_roll_prompt_batch",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={
                    "actor": serialize(actor),
                    "targets": [serialize(target) for _, target, _, _ in prepared],
                },
                after_snapshot={},
                reason=f"{actor.display_name} queued {len(prepared)} player saving throws",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()

            economy_consumed = self._validate_action_economy(
                session,
                combat,
                actor,
                actor_version=command.actor_version,
                action_cost=command.action_cost,
                consume=True,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                action_name=command.action_name,
                reaction_event=command.reaction_event,
            )
            recharge_consumed = self._validate_recharge(
                actor,
                recharge_key=command.recharge_key,
                consume=command.recharge_consume,
            )
            if recharge_consumed and not economy_consumed:
                actor.version += 1
                actor.updated_at = now

            label = f"{command.ability or ''}豁免"
            action_window = self._action_window_metadata(
                command.action_cost,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                reaction_event=command.reaction_event,
            )
            window_summary = self._action_window_summary(
                command.action_cost,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                reaction_event=command.reaction_event,
            )
            actions: list[CombatAction] = []
            for index, (prompt, target, effect_target, area_geometry) in enumerate(prepared):
                request_json = prompt.model_dump(mode="json")
                if area_geometry:
                    request_json["area_geometry"] = area_geometry
                request_json.update(
                    {
                        "actor_name": actor.display_name,
                        "target_name": target.display_name,
                        "effect_target_name": effect_target.display_name,
                        "batch_idempotency_key": idempotency_key,
                        "batch_index": index,
                        "batch_size": len(prepared),
                    }
                )
                actions.append(
                    CombatAction(
                        campaign_id=campaign_id,
                        combat_id=combat_id,
                        actor_combatant_id=actor.id,
                        transaction_id=transaction.id,
                        action_type="player_roll_prompt",
                        target_combatant_ids=[target.id],
                        request_json=request_json,
                        result_json={
                            "phase": "awaiting_player_roll",
                            "roll_owner": "player",
                            "batch_index": index,
                            "batch_size": len(prepared),
                            **(
                                {"action_window": action_window}
                                if action_window is not None
                                else {}
                            ),
                        },
                        explanation=prompt.description,
                        round_number=combat.round_number,
                        turn_index=combat.current_turn_index,
                        summary=(
                            f"{actor.display_name} 对 {target.display_name} 使用"
                            f"「{prompt.action_name}」；等待玩家进行 {label}"
                            f"（{prompt.roll_formula}，DC {prompt.dc}）"
                            + (f"；{window_summary}" if window_summary else "")
                        ),
                        idempotency_key=self._batch_player_roll_prompt_key(
                            idempotency_key,
                            index,
                        ),
                        status="previewed",
                    )
                )
            session.add_all(actions)
            session.flush()
            if actions:
                self._persist_eligible_cast_spell_reaction_windows(
                    session,
                    combat=combat,
                    transaction=transaction,
                    spell_action=actions[0],
                )
            transaction.after_snapshot = {
                "combat_id": combat_id,
                "actor_combatant_id": actor.id,
                "target_ids": [target.id for _, target, _, _ in prepared],
                "action_ids": [action.id for action in actions],
                "action_economy_consumed": economy_consumed,
                "recharge_consumed": recharge_consumed,
            }
            return {
                "actions": [serialize(action) for action in actions],
                "actor": serialize(actor),
                "targets": [serialize(target) for _, target, _, _ in prepared],
                "transaction": serialize(transaction),
                "already_applied": False,
            }

    @classmethod
    def _resolve_save_defenses(
        cls,
        target: Combatant,
        *,
        dc: int,
        ability: str | None,
        roll_total: int,
        roll_totals: list[int],
        damage_on_success: int,
        damage_on_failure: int,
        is_magical: bool,
        use_legendary_resistance: bool,
        use_feature_reroll: bool,
        consume: bool,
    ) -> dict[str, object]:
        snapshot = dict(target.snapshot_json or {})
        raw_defenses = snapshot.get("advanced_defenses")
        defenses = dict(raw_defenses) if isinstance(raw_defenses, dict) else {}
        applied: list[str] = []
        rolls = list(roll_totals) if roll_totals else [roll_total]
        normalized_ability = str(ability or "").strip().lower()
        condition_set = cls._condition_set(target)
        condition_save_disadvantage = (
            normalized_ability in {"dexterity", "敏捷"}
            and "restrained" in condition_set
        )
        magic_resistance = bool(
            defenses.get("magic_resistance") or snapshot.get("magic_resistance")
        )
        feature_modifiers = cls._feature_rule_modifiers(
            target,
            stat="saving_throw",
            ability=ability,
        )
        feature_advantage = [
            str(item.get("source") or "职业豁免优势")
            for item in feature_modifiers
            if item.get("operation") == "advantage"
        ]
        feature_disadvantage = [
            str(item.get("source") or "职业豁免劣势")
            for item in feature_modifiers
            if item.get("operation") == "disadvantage"
        ]
        feature_reroll_consumed: dict[str, object] | None = None
        if use_feature_reroll:
            if magic_resistance and is_magical:
                raise ValueError("魔法抗性与职业特性重掷不能在同一次豁免中叠加")
            raw_rerolls = snapshot.get("feature_saving_throw_rerolls")
            rerolls = list(raw_rerolls) if isinstance(raw_rerolls, list) else []
            available_index = next(
                (
                    index
                    for index, item in enumerate(rerolls)
                    if isinstance(item, dict) and item.get("available") is True
                ),
                None,
            )
            if available_index is None:
                raise ValueError("目标没有可用的职业特性豁免重掷")
            if len(rolls) < 2:
                raise ValueError("职业特性重掷需要提交第一次与重掷后的两个总值")
            effective_roll = max(rolls)
            feature_reroll_consumed = {
                "resource": "feature_saving_throw_reroll",
                "before": len(rerolls),
                "after": len(rerolls) - 1,
            }
            if consume:
                rerolls[available_index] = {
                    **rerolls[available_index],
                    "available": False,
                }
                snapshot["feature_saving_throw_rerolls"] = rerolls
                target.snapshot_json = snapshot
            applied.append("feature_saving_throw_reroll")
        elif (
            (magic_resistance and is_magical)
            or feature_advantage
            or feature_disadvantage
            or condition_save_disadvantage
        ):
            if len(rolls) < 2:
                raise ValueError(
                    "structured saving-throw advantage/disadvantage requires two reported "
                    "save totals; the server will not invent the second roll"
                )
            has_advantage = (magic_resistance and is_magical) or bool(feature_advantage)
            has_disadvantage = bool(feature_disadvantage) or condition_save_disadvantage
            if has_advantage and has_disadvantage:
                effective_roll = rolls[0]
                applied.append("saving_throw_advantage_disadvantage_cancelled")
            elif has_advantage:
                effective_roll = max(rolls)
                if magic_resistance and is_magical:
                    applied.append("magic_resistance")
                applied.extend(f"feature:{source}" for source in feature_advantage)
            else:
                effective_roll = min(rolls)
                applied.extend(f"feature:{source}" for source in feature_disadvantage)
                if condition_save_disadvantage:
                    applied.append("restrained_disadvantage_dexterity_save")
            if condition_save_disadvantage and (
                "restrained_disadvantage_dexterity_save" not in applied
            ):
                applied.append("restrained_disadvantage_dexterity_save")
        else:
            effective_roll = roll_total
        auto_fail = (
            bool(condition_set & cls._SAVE_AUTO_FAIL_STR_DEX_CONDITIONS)
            and normalized_ability in {"strength", "dexterity", "力量", "敏捷"}
        )
        if auto_fail:
            effective_roll = -100_000
            applied.append("condition_auto_fail_strength_dex_save")
        succeeded = effective_roll >= dc and not auto_fail
        resource_consumed: dict[str, object] | None = None
        if use_legendary_resistance:
            if succeeded:
                raise ValueError("legendary resistance can only replace a failed saving throw")
            raw_legendary = defenses.get("legendary_resistance")
            if not isinstance(raw_legendary, dict):
                raise ValueError("target has no structured legendary resistance resource")
            remaining = cls._state_int(raw_legendary.get("remaining"))
            maximum = cls._state_int(raw_legendary.get("maximum"), remaining)
            if remaining < 1:
                raise ValueError("no legendary resistance uses remain")
            succeeded = True
            applied.append("legendary_resistance")
            resource_consumed = {
                "resource": "legendary_resistance",
                "before": remaining,
                "after": remaining - 1,
            }
            if consume:
                defenses["legendary_resistance"] = {
                    **raw_legendary,
                    "remaining": remaining - 1,
                    "maximum": maximum,
                }
                snapshot["advanced_defenses"] = defenses
                target.snapshot_json = snapshot
        damage = damage_on_success if succeeded else damage_on_failure
        evasion = bool(defenses.get("evasion") or snapshot.get("evasion"))
        if evasion and normalized_ability == "dexterity" and (
            damage_on_success > 0 or damage_on_failure > 0
        ):
            damage = 0 if succeeded else damage_on_failure // 2
            applied.append("evasion")
        elif isinstance((reflex := defenses.get("reflex_defense")), dict):
            reflex_ability = str(reflex.get("ability") or "dexterity").lower()
            success_multiplier = reflex.get("success_multiplier")
            failure_multiplier = reflex.get("failure_multiplier")
            if (
                normalized_ability == reflex_ability
                and isinstance(success_multiplier, (int, float))
                and isinstance(failure_multiplier, (int, float))
                and 0 <= success_multiplier <= 1
                and 0 <= failure_multiplier <= 1
            ):
                multiplier = success_multiplier if succeeded else failure_multiplier
                base_damage = damage_on_success if succeeded else damage_on_failure
                damage = floor(base_damage * multiplier)
                applied.append("reflex_defense")
        return {
            "success": succeeded,
            "effective_roll_total": effective_roll,
            "reported_roll_totals": rolls,
            "damage": damage,
            "applied_defenses": applied,
            "defense_resource_consumed": resource_consumed,
            "feature_reroll_consumed": feature_reroll_consumed,
        }

    @classmethod
    def _resolve_player_roll(
        cls,
        action: CombatAction,
        target: Combatant,
        command: PlayerRollResolutionCommand,
        *,
        consume_defenses: bool = False,
    ) -> dict[str, Any]:
        request = action.request_json
        dc = int(str(request["dc"]))
        defense = cls._resolve_save_defenses(
            target,
            dc=dc,
            ability=(str(request.get("ability")) if request.get("ability") else None),
            roll_total=command.roll_total,
            roll_totals=command.roll_totals,
            damage_on_success=cls._state_int(request.get("damage_on_success")),
            damage_on_failure=cls._state_int(request.get("damage_on_failure")),
            is_magical=bool(request.get("is_magical")),
            use_legendary_resistance=command.use_legendary_resistance,
            use_feature_reroll=command.use_feature_reroll,
            consume=consume_defenses,
        )
        success = bool(defense["success"])
        damage = cls._state_int(defense["damage"])
        component_key = (
            "damage_components_on_success"
            if success
            else "damage_components_on_failure"
        )
        raw_components = request.get(component_key)
        if isinstance(raw_components, list) and raw_components:
            damage_components = [
                {
                    "amount": cls._state_int(item.get("amount")),
                    "damage_type": str(item.get("damage_type") or "").strip(),
                    "damage_tags": [
                        str(tag).strip()
                        for tag in item.get("damage_tags", [])
                        if str(tag).strip()
                    ]
                    if isinstance(item.get("damage_tags"), list)
                    else [],
                }
                for item in raw_components
                if isinstance(item, dict)
                and cls._state_int(item.get("amount")) >= 0
                and str(item.get("damage_type") or "").strip()
            ]
        else:
            raw_damage = cls._state_int(
                request.get("damage_on_success" if success else "damage_on_failure")
            )
            damage_components = [
                {
                    "amount": raw_damage,
                    "damage_type": str(request.get("damage_type") or "").strip(),
                    "damage_tags": [
                        str(tag).strip()
                        for tag in request.get("damage_tags", [])
                        if str(tag).strip()
                    ]
                    if isinstance(request.get("damage_tags"), list)
                    else [],
                }
            ] if raw_damage > 0 else []
        for component in damage_components:
            if not component.get("damage_tags"):
                component.pop("damage_tags", None)

        # Save defenses such as Evasion and a structured reflex profile modify
        # the save outcome before the follow-up damage transaction.  Apply that
        # multiplier to every typed segment, then let the normal damage
        # endpoint apply resistance/vulnerability/immunity independently to
        # each segment.  This prevents a fire + piercing save from collapsing
        # back into one untyped number.
        applied_defenses = set(str(value) for value in defense["applied_defenses"])
        if "evasion" in applied_defenses:
            damage_components = [
                {
                    **component,
                    "amount": (
                        0
                        if success
                        else int(component["amount"]) // 2
                    ),
                }
                for component in damage_components
            ]
        elif "reflex_defense" in applied_defenses:
            raw_defenses = dict(target.snapshot_json or {}).get("advanced_defenses")
            reflex = (
                dict(raw_defenses).get("reflex_defense")
                if isinstance(raw_defenses, dict)
                else None
            )
            if isinstance(reflex, dict):
                multiplier_key = "success_multiplier" if success else "failure_multiplier"
                multiplier = reflex.get(multiplier_key)
                if isinstance(multiplier, (int, float)) and 0 <= multiplier <= 1:
                    damage_components = [
                        {
                            **component,
                            "amount": floor(int(component["amount"]) * multiplier),
                        }
                        for component in damage_components
                    ]
        damage = sum(int(component["amount"]) for component in damage_components)
        damage_components = [
            component for component in damage_components if component["amount"] > 0
        ]
        damage_type = (
            damage_components[0]["damage_type"]
            if len(damage_components) == 1
            else "mixed"
            if len(damage_components) > 1
            else request.get("damage_type")
        )
        result: dict[str, Any] = {
            "phase": "resolved",
            "roll_owner": "player",
            "roll_total": defense["effective_roll_total"],
            "reported_roll_totals": defense["reported_roll_totals"],
            "dc": dc,
            "success": success,
            "outcome": "success" if success else "failure",
            "damage": damage,
            "damage_type": damage_type,
            "damage_components": damage_components,
            "dm_note": command.dm_note,
            "applied_defenses": defense["applied_defenses"],
            "defense_resource_consumed": defense["defense_resource_consumed"],
            "feature_reroll_consumed": defense["feature_reroll_consumed"],
        }
        result["follow_up_damage"] = (
            {
                "action_type": "damage",
                "actor_combatant_id": action.actor_combatant_id,
                "action_cost": "none",
                "action_name": request["action_name"],
                "resolution_note": (
                    f"{target.display_name} 的玩家骰总值 {defense['effective_roll_total']}"
                    f" 对抗 DC {dc}，{'成功' if success else '失败'}；"
                    f"结算 {damage} 点{request.get('damage_type') or ''}伤害"
                ),
                "target_combatant_id": target.id,
                "target_version": target.version,
                "amount": damage,
                "damage_type": damage_type,
                "damage_components": damage_components,
                "damage_tags": request.get("damage_tags", []),
            }
            if damage > 0
            else None
        )
        return result

    def preview_player_roll(
        self,
        campaign_id: str,
        combat_id: str,
        action_id: str,
        command: PlayerRollResolutionCommand,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            combat, action, actor, target = self._player_roll_scope(
                session, campaign_id, combat_id, action_id
            )
            if action.version != command.action_version:
                raise VersionConflict(
                    "combat_action",
                    action.id,
                    command.action_version,
                    action.version,
                )
            if action.status != "previewed":
                raise ValueError("player roll prompt has already been resolved")
            request = dict(action.request_json or {})
            effect_target = target
            raw_effect_target_id = request.get("effect_target_combatant_id")
            if isinstance(raw_effect_target_id, str) and raw_effect_target_id != target.id:
                effect_target = session.get(Combatant, raw_effect_target_id)
                if effect_target is None or effect_target.combat_id != combat.id:
                    raise StateNotFoundError("effect target combatant not found in combat")
            if self._player_roll_is_harmful(action.request_json):
                self._validate_charmed_harm_targets(
                    session,
                    combat,
                    actor,
                    list(dict.fromkeys([target.id, effect_target.id])),
                    dm_override=bool(request.get("dm_override")),
                )
            return {
                "action": serialize(action),
                "actor": serialize(actor),
                "target": serialize(target),
                "resolution": self._resolve_player_roll(action, target, command),
            }

    def confirm_player_roll(
        self,
        campaign_id: str,
        combat_id: str,
        action_id: str,
        command: PlayerRollResolutionCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            combat, action, actor, target = self._player_roll_scope(
                session, campaign_id, combat_id, action_id
            )
            if action.status == "confirmed":
                return {
                    "action": serialize(action),
                    "actor": serialize(actor),
                    "target": serialize(target),
                    "effect_target": serialize(target),
                    "resolution": action.result_json,
                }
            if action.version != command.action_version:
                raise VersionConflict(
                    "combat_action",
                    action.id,
                    command.action_version,
                    action.version,
                )
            request = dict(action.request_json or {})
            effect_target = target
            raw_effect_target_id = request.get("effect_target_combatant_id")
            if isinstance(raw_effect_target_id, str) and raw_effect_target_id != target.id:
                effect_target = session.get(Combatant, raw_effect_target_id)
                if effect_target is None or effect_target.combat_id != combat.id:
                    raise StateNotFoundError("effect target combatant not found in combat")
            if self._player_roll_is_harmful(request):
                self._validate_charmed_harm_targets(
                    session,
                    combat,
                    actor,
                    list(dict.fromkeys([target.id, effect_target.id])),
                    dm_override=bool(request.get("dm_override")),
                )
            resolution = self._resolve_player_roll(
                action,
                target,
                command,
                consume_defenses=True,
            )
            request_action_cost = (
                str(request.get("action_cost"))
                if request.get("action_cost") is not None
                else None
            )
            request_legendary_cost = (
                request.get("legendary_cost")
                if isinstance(request.get("legendary_cost"), int)
                else None
            )
            request_legendary_pool_max = (
                request.get("legendary_pool_max")
                if isinstance(request.get("legendary_pool_max"), int)
                else None
            )
            request_reaction_trigger = (
                str(request.get("reaction_trigger"))
                if request.get("reaction_trigger") is not None
                else None
            )
            request_reaction_event = (
                str(request.get("reaction_event"))
                if request.get("reaction_event") is not None
                else None
            )
            action_window = self._action_window_metadata(
                request_action_cost,
                legendary_cost=request_legendary_cost,
                legendary_pool_max=request_legendary_pool_max,
                reaction_trigger=request_reaction_trigger,
                reaction_event=request_reaction_event,
            )
            window_summary = self._action_window_summary(
                request_action_cost,
                legendary_cost=request_legendary_cost,
                legendary_pool_max=request_legendary_pool_max,
                reaction_trigger=request_reaction_trigger,
                reaction_event=request_reaction_event,
            )
            succeeded = bool(resolution["success"])
            target_state_changed = (
                resolution.get("defense_resource_consumed") is not None
                or resolution.get("feature_reroll_consumed") is not None
            )
            raw_conditions = request.get(
                "conditions_on_success" if succeeded else "conditions_on_failure",
                [],
            )
            conditions = [
                str(value).strip()
                for value in raw_conditions
                if isinstance(value, str) and value.strip()
            ] if isinstance(raw_conditions, list) else []
            movement_raw = request.get(
                "movement_on_success_ft" if succeeded else "movement_on_failure_ft"
            )
            movement_distance = int(movement_raw) if isinstance(movement_raw, int) else None
            structured_effects: dict[str, object] = {}
            if conditions or movement_distance is not None:
                structured_effects = self._apply_structured_monster_effects(
                    session,
                    combat,
                    actor=actor,
                    target=effect_target,
                    conditions=conditions,
                    condition_duration=(
                        str(request["condition_duration"])
                        if request.get("condition_duration") is not None
                        else None
                    ),
                    condition_duration_value=(
                        self._state_int(request.get("condition_duration_value"))
                        if request.get("condition_duration_value") is not None
                        else None
                    ),
                    condition_save_dc=(
                        self._state_int(request.get("condition_save_dc"))
                        if request.get("condition_save_dc") is not None
                        else None
                    ),
                    condition_save_ability=(
                        str(request["condition_save_ability"])
                        if request.get("condition_save_ability") is not None
                        else None
                    ),
                    movement_distance_ft=movement_distance,
                    movement_direction=(
                        str(request["movement_direction"])
                        if request.get("movement_direction") is not None
                        else None
                    ),
                )
                if effect_target.id != target.id:
                    effect_target.version += 1
                    effect_target.updated_at = datetime.now(UTC)
                else:
                    target_state_changed = True
            if target_state_changed:
                target.version += 1
                target.updated_at = datetime.now(UTC)
            if structured_effects:
                resolution["structured_effects"] = structured_effects
                movement = structured_effects.get("movement")
                if (
                    isinstance(movement, dict)
                    and self._state_int(movement.get("moved_ft")) > 0
                ):
                    ended_effects, ended_summons = self._end_predicated_effects(
                        session,
                        combat,
                        now=datetime.now(UTC),
                        event_combatant_ids={effect_target.id},
                        event_kinds={"movement"},
                        event_only=True,
                    )
                    if ended_effects:
                        resolution["ended_predicated_effect_ids"] = [
                            effect.id for effect in ended_effects
                        ]
                    if ended_summons:
                        resolution["ended_predicated_summon_ids"] = [
                            summon.id for summon in ended_summons
                        ]
                follow_up = resolution.get("follow_up_damage")
                if isinstance(follow_up, dict) and effect_target.id == target.id:
                    follow_up["target_version"] = target.version
            elif target_state_changed:
                follow_up = resolution.get("follow_up_damage")
                if isinstance(follow_up, dict):
                    follow_up["target_version"] = target.version
            action.result_json = {
                **resolution,
                "confirmation_idempotency_key": idempotency_key,
                **({"action_window": action_window} if action_window is not None else {}),
            }
            action.status = "confirmed"
            action.version += 1
            action.updated_at = datetime.now(UTC)
            action.summary = (
                f"{actor.display_name} 对 {target.display_name} 使用"
                f"「{action.request_json['action_name']}」；"
                f"{target.display_name} 掷骰 {resolution['roll_total']} 对抗"
                f" DC {action.request_json['dc']}，"
                f"{'成功' if resolution['success'] else '失败'}"
                + (f"；{window_summary}" if window_summary else "")
            )
            effect_ids = structured_effects.get("effect_ids", [])
            if isinstance(effect_ids, list):
                for effect_id in effect_ids:
                    effect = session.get(CombatEffect, effect_id)
                    if effect is not None and effect.source_action_id is None:
                        effect.source_action_id = action.id
            return {
                "action": serialize(action),
                "actor": serialize(actor),
                "target": serialize(target),
                "effect_target": serialize(effect_target),
                "resolution": action.result_json,
            }

    def preview(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatActionCommand,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            combat, target, actor = self._scope(
                session, campaign_id, combat_id, command
            )
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            self._validate_reaction_window(
                session,
                combat=combat,
                actor=actor,
                target=target,
                command=command,
            )
            self._validate_monster_sequence(session, combat_id, actor, command)
            self._validate_action_economy(
                session,
                combat,
                actor,
                actor_version=command.actor_version,
                action_cost=command.action_cost,
                consume=False,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                action_name=command.action_name,
                reaction_event=command.reaction_event,
            )
            self._validate_recharge(
                actor,
                recharge_key=command.recharge_key,
                consume=command.recharge_consume,
            )
            attack_contexts, _ = self._attack_contexts(
                session, combat, command, actor, target
            )
            automatic_critical = "automatic_critical:target_within_5ft" in attack_contexts
            if actor is not None and self._combat_action_is_harmful(command):
                self._validate_charmed_harm_targets(
                    session,
                    combat,
                    actor,
                    [target.id],
                    dm_override=command.dm_override,
                )
            if actor is not None and command.area_shape is not None:
                self._validate_player_roll_area_target(
                    session,
                    combat,
                    actor,
                    target,
                    command,
                )
            if command.action_type == "heal" and target.hp == 0:
                death_save = session.scalar(
                    select(DeathSave).where(DeathSave.combatant_id == target.id)
                )
                if (
                    death_save is not None
                    and death_save.dead
                    and not command.dm_override
                ):
                    raise ValueError(
                        "ordinary healing cannot restore a dead combatant; "
                        "use a DM override for a resurrection effect"
                    )
            resolved = self._resolve(command, target)
            if attack_contexts:
                resolved["attack_contexts"] = attack_contexts
            if command.is_attack:
                resolved["automatic_critical"] = automatic_critical
                resolved["critical_hit"] = command.critical_hit or automatic_critical
            return resolved

    def preflight_action_batch(
        self,
        campaign_id: str,
        combat_id: str,
        commands: list[tuple[CombatActionCommand, str]],
    ) -> None:
        """Validate a player multi-target action before any row is mutated.

        Player spell/weapon projections can contain several independently
        resisted damage segments.  The legacy endpoint confirmed those
        segments one at a time, so an invalid later segment could leave the
        first segment committed.  This preflight walks the complete command
        list against one read-only snapshot, including optimistic versions,
        action economy, sequence gates, and conditional damage defenses.

        The actual confirmations still use the normal authoritative endpoint;
        this method is deliberately a validation barrier, not a second
        resolver.  Every failure that can be caused by the submitted batch is
        therefore raised before the first write.
        """

        with Session(self.engine) as session:
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            if combat.status != "active":
                raise ValueError("only an active combat can confirm actions")

            simulated_versions: dict[str, int] = {}
            for command, idempotency_key in commands:
                if not idempotency_key.strip():
                    raise ValueError("idempotency key is required")
                existing = session.scalar(
                    select(CombatAction).where(
                        CombatAction.combat_id == combat_id,
                        CombatAction.idempotency_key == idempotency_key,
                    )
                )
                if existing is not None:
                    continue
                current_target = session.get(Combatant, command.target_combatant_id)
                if current_target is None or current_target.combat_id != combat_id:
                    raise StateNotFoundError("target combatant not found in combat")
                expected_target_version = simulated_versions.get(
                    current_target.id,
                    current_target.version,
                )
                if command.target_version != expected_target_version:
                    raise VersionConflict(
                        "combatant",
                        current_target.id,
                        command.target_version,
                        expected_target_version,
                    )
                actor = (
                    session.get(Combatant, command.actor_combatant_id)
                    if command.actor_combatant_id is not None
                    else None
                )
                if actor is not None:
                    expected_actor_version = simulated_versions.get(actor.id, actor.version)
                    if command.actor_version != expected_actor_version:
                        raise VersionConflict(
                            "combatant",
                            actor.id,
                            command.actor_version or 0,
                        expected_actor_version,
                    )
                self._validate_reaction_window(
                    session,
                    combat=combat,
                    actor=actor,
                    target=current_target,
                    command=command,
                )
                if actor is not None and self._combat_action_is_harmful(command):
                    self._validate_charmed_harm_targets(
                        session,
                        combat,
                        actor,
                        [current_target.id],
                        dm_override=command.dm_override,
                    )
                self._validate_monster_sequence(session, combat_id, actor, command)
                self._validate_action_economy(
                    session,
                    combat,
                    actor,
                    actor_version=command.actor_version,
                    action_cost=command.action_cost,
                    consume=False,
                    legendary_cost=command.legendary_cost,
                    legendary_pool_max=command.legendary_pool_max,
                    reaction_trigger=command.reaction_trigger,
                    action_name=command.action_name,
                    reaction_event=command.reaction_event,
                )
                if actor is not None and command.area_shape is not None:
                    # The normal confirmation path performs this same
                    # authoritative 3-D geometry check immediately before
                    # writing.  The batch barrier must perform it for every
                    # target as well, otherwise a valid first target could be
                    # committed before a later target is rejected.
                    self._validate_player_roll_area_target(
                        session,
                        combat,
                        actor,
                        current_target,
                        command,
                    )
                if command.action_type == "heal" and current_target.hp == 0:
                    death_save = session.scalar(
                        select(DeathSave).where(
                            DeathSave.combatant_id == current_target.id
                        )
                    )
                    if death_save is not None and death_save.dead and not command.dm_override:
                        raise ValueError(
                            "ordinary healing cannot restore a dead combatant; "
                            "use a DM override for a resurrection effect"
                        )
                # _resolve is pure with respect to the ORM row.  It is the
                # same typed damage/defense gate used by confirm(), so mixed
                # damage, immunity, resistance, vulnerability and unresolved
                # conditional defenses are all checked before writes.
                self._resolve(command, current_target)
                if actor is not None and command.action_cost != "none":
                    simulated_versions[actor.id] = expected_actor_version + 1
                simulated_versions[current_target.id] = (
                    simulated_versions.get(current_target.id, expected_target_version) + 1
                )

    def confirm_action_batch(
        self,
        campaign_id: str,
        combat_id: str,
        commands: list[tuple[CombatActionCommand, str]],
    ) -> list[dict[str, Any]]:
        """Confirm a preflighted batch through the ordinary combat resolver."""

        self.preflight_action_batch(campaign_id, combat_id, commands)
        return [
            self.confirm(
                campaign_id,
                combat_id,
                command,
                idempotency_key=idempotency_key,
            )
            for command, idempotency_key in commands
        ]

    def confirm(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatActionCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            combat, target, actor = self._scope(
                session,
                campaign_id,
                combat_id,
                command,
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                existing_target_id = (
                    existing.target_combatant_ids[0]
                    if existing.target_combatant_ids
                    else None
                )
                existing_target = (
                    session.get(Combatant, existing_target_id)
                    if isinstance(existing_target_id, str)
                    else None
                )
                return {
                    "action": serialize(existing),
                    "actor": serialize(actor) if actor is not None else None,
                    "target": serialize(existing_target) if existing_target is not None else None,
                    "end_condition": self._end_condition(session, combat),
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            reaction_window = self._validate_reaction_window(
                session,
                combat=combat,
                actor=actor,
                target=target,
                command=command,
            )
            self._validate_monster_sequence(session, combat_id, actor, command)
            attack_contexts, help_effect = self._attack_contexts(
                session, combat, command, actor, target
            )
            automatic_critical = "automatic_critical:target_within_5ft" in attack_contexts
            effective_critical_hit = command.critical_hit or automatic_critical
            if actor is not None and self._combat_action_is_harmful(command):
                self._validate_charmed_harm_targets(
                    session,
                    combat,
                    actor,
                    [target.id],
                    dm_override=command.dm_override,
                )
            if actor is not None and command.area_shape is not None:
                self._validate_player_roll_area_target(
                    session,
                    combat,
                    actor,
                    target,
                    command,
                )
            economy_consumed = self._validate_action_economy(
                session,
                combat,
                actor,
                actor_version=command.actor_version,
                action_cost=command.action_cost,
                consume=True,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                action_name=command.action_name,
                reaction_event=command.reaction_event,
            )
            recharge_consumed = self._validate_recharge(
                actor,
                recharge_key=command.recharge_key,
                consume=command.recharge_consume,
            )
            if recharge_consumed and not economy_consumed:
                assert actor is not None
                actor.version += 1
                actor.updated_at = datetime.now(UTC)
            if command.action_type == "heal" and target.hp == 0:
                current_death_save = session.scalar(
                    select(DeathSave).where(DeathSave.combatant_id == target.id)
                )
                if (
                    current_death_save is not None
                    and current_death_save.dead
                    and not command.dm_override
                ):
                    raise ValueError(
                        "ordinary healing cannot restore a dead combatant; "
                        "use a DM override for a resurrection effect"
                    )
            resolved = self._resolve(command, target)
            before = serialize(target)
            after = resolved["after"]
            target.hp = int(after["hp"])
            target.temporary_hp = int(after["temporary_hp"])
            target.version += 1
            now = datetime.now(UTC)
            target.updated_at = now
            condition_changes = self._sync_zero_hp_lifecycle(
                target,
                before_hp=int(resolved["before"]["hp"]),
            )
            structured_effects: dict[str, object] = {}
            if actor is not None and (
                command.conditions_to_apply
                or command.forced_movement_distance_ft is not None
            ):
                structured_effects = self._apply_structured_monster_effects(
                    session,
                    combat,
                    actor=actor,
                    target=target,
                    conditions=command.conditions_to_apply,
                    condition_duration=command.condition_duration,
                    condition_duration_value=command.condition_duration_value,
                    condition_save_dc=command.condition_save_dc,
                    condition_save_ability=command.condition_save_ability,
                    movement_distance_ft=command.forced_movement_distance_ft,
                    movement_direction=command.forced_movement_direction,
                )
            extra_attack_budget = 0
            if command.is_attack and command.action_cost == "action" and actor is not None:
                runtime = actor.snapshot_json.get("feature_runtime")
                combat_start = runtime.get("combat_start") if isinstance(runtime, dict) else None
                attack_count = (
                    int(combat_start.get("attack_action_count") or 1)
                    if isinstance(combat_start, dict)
                    else 1
                )
                if attack_count > 1:
                    snapshot = dict(actor.snapshot_json or {})
                    extra_attack_budget = attack_count - 1
                    snapshot["attack_roll_budget"] = extra_attack_budget
                    actor.snapshot_json = snapshot
            consumed_attack_effects: list[CombatEffect] = []
            if command.is_attack and actor is not None:
                actor_hidden = self._active_runtime_effects(
                    session,
                    combat.id,
                    target_id=actor.id,
                    state_name="hidden",
                )
                for state_effect in [*actor_hidden, help_effect]:
                    if state_effect is None or state_effect in consumed_attack_effects:
                        continue
                    ended_target = self._end_runtime_effect(
                        session,
                        state_effect,
                        reason="state consumed by confirmed attack",
                        now=now,
                    )
                    if ended_target is not None:
                        consumed_attack_effects.append(state_effect)
                if (
                    consumed_attack_effects
                    and command.action_cost == "none"
                    and actor.id != target.id
                ):
                    actor.version += 1
                    actor.updated_at = now
            death_save_result: dict[str, Any] | None = None
            death_save: DeathSave | None = None
            summon_ended = False
            combatant_deactivated = False
            if command.action_type == "damage" and target.hp == 0:
                if self._is_summon(target):
                    deactivated = self._deactivate_summons(
                        session,
                        combat,
                        [target.id],
                        now=now,
                    )
                    summon_ended = bool(deactivated)
                else:
                    combatant_deactivated = self._deactivate_zero_hp_non_character(
                        target,
                        now=now,
                    )
                    # Keep a death-save record for every non-summon zero-HP
                    # target, even when a non-character is immediately removed
                    # from initiative.  The record is not an invitation for an
                    # NPC turn; it preserves the authoritative result shape for
                    # generic combat clients and lets audit/history explain how
                    # zero-HP damage was resolved.
                    death_save = self._death_save(session, target)
                    was_at_zero = int(resolved["before"]["hp"]) == 0
                    massive_damage = (
                        int(resolved["result"]["unapplied_damage"]) >= target.max_hp
                        and target.max_hp > 0
                    )
                    if massive_damage:
                        death_save.failures = 3
                        death_save.successes = 0
                        death_save.stable = False
                        death_save.dead = True
                        death_save.pending_death_confirmation = False
                        death_save.version += 1
                        death_save_result = {
                            "failures_added": 3,
                            "massive_damage": True,
                            "dead": True,
                            "explanation": "剩余伤害达到最大生命值，角色立即死亡",
                        }
                    elif was_at_zero and int(resolved["result"]["adjusted_damage"]) > 0:
                        failures_added = 2 if effective_critical_hit else 1
                        death_save.failures = min(
                            3, death_save.failures + failures_added
                        )
                        death_save.successes = 0
                        death_save.stable = False
                        death_save.dead = death_save.failures >= 3
                        death_save.pending_death_confirmation = False
                        death_save.version += 1
                        death_save_result = {
                            "failures_added": failures_added,
                            "massive_damage": False,
                            "dead": death_save.dead,
                            "explanation": (
                                f"0 HP 时受到{'暴击' if effective_critical_hit else ''}伤害，"
                                f"累计 {failures_added} 次死亡豁免失败"
                            ),
                        }
            elif command.action_type == "heal" and int(resolved["result"].get("hp_gained", 0)) > 0:
                existing_death_save = session.scalar(
                    select(DeathSave).where(DeathSave.combatant_id == target.id)
                )
                if existing_death_save is not None:
                    existing_death_save.successes = 0
                    existing_death_save.failures = 0
                    existing_death_save.stable = False
                    existing_death_save.dead = False
                    existing_death_save.pending_death_confirmation = False
                    existing_death_save.last_roll = None
                    existing_death_save.version += 1
            damaged_combatant_ids = {
                target.id
            } if (
                command.action_type == "damage"
                and int(resolved["result"].get("adjusted_damage", 0)) > 0
            ) else set()
            moved_combatant_ids = {
                target.id
            } if (
                isinstance(structured_effects.get("movement"), dict)
                and self._state_int(
                    structured_effects["movement"].get("moved_ft")
                ) > 0
            ) else set()
            lifecycle_event_ids = damaged_combatant_ids | moved_combatant_ids
            lifecycle_event_kinds: set[str] = set()
            if damaged_combatant_ids:
                lifecycle_event_kinds.add("damage")
            if moved_combatant_ids:
                lifecycle_event_kinds.add("movement")
            ended_predicated_effects, ended_predicated_summons = (
                self._end_predicated_effects(
                    session,
                    combat,
                    now=now,
                    event_combatant_ids=lifecycle_event_ids,
                    event_kinds=lifecycle_event_kinds,
                    # A zero-HP transition also changes the source lifecycle
                    # (unconscious/dead/inactive).  Evaluate those explicit
                    # predicates in the same transaction so concentration
                    # summons do not linger until the next turn or check.
                    event_only=not (
                        command.action_type == "damage" and target.hp <= 0
                    ),
                )
            )
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type=f"combat_{command.action_type}",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"combatant": before},
                after_snapshot={
                    "combatant_id": target.id,
                    "hp": target.hp,
                    "temporary_hp": target.temporary_hp,
                },
                reason=command.override_reason
                if command.dm_override
                else f"{command.action_type} confirmed in combat",
                source="combat",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            result = dict(resolved["result"])
            action_window = self._action_window_metadata(
                command.action_cost,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                reaction_event=command.reaction_event,
            )
            if action_window is not None:
                result["action_window"] = action_window
            if structured_effects:
                result["structured_effects"] = structured_effects
            if extra_attack_budget:
                result["attack_roll_budget"] = extra_attack_budget
            if attack_contexts:
                result["attack_contexts"] = attack_contexts
                result["attack_roll_mode"] = command.attack_roll_mode
                result["attack_adjudication_note"] = command.attack_adjudication_note
            if command.is_attack:
                result["automatic_critical"] = automatic_critical
                result["critical_hit"] = effective_critical_hit
            if consumed_attack_effects:
                result["consumed_effect_ids"] = [
                    effect.id for effect in consumed_attack_effects
                ]
            if summon_ended:
                result["summon_ended"] = True
                result["summon_end_reason"] = "生命值降至0"
            if combatant_deactivated:
                result["combatant_deactivated"] = True
                result["deactivation_reason"] = "非角色单位生命值降至0，已离开先攻轨道"
            if condition_changes:
                result["condition_changes"] = condition_changes
            if ended_predicated_effects:
                result["ended_predicated_effect_ids"] = [
                    effect.id for effect in ended_predicated_effects
                ]
            if ended_predicated_summons:
                result["ended_predicated_summon_ids"] = [
                    summon.id for summon in ended_predicated_summons
                ]
            if death_save_result is not None:
                result["death_save"] = death_save_result
            if resolved["concentration_check_dc"] is not None:
                result["concentration_check_dc"] = resolved["concentration_check_dc"]
            if recharge_consumed:
                result["recharge_consumed"] = command.recharge_key
            if command.action_type == "damage" and actor is not None:
                action_result = command.resolution_note or (
                    f"造成 {result['adjusted_damage']} 点"
                    f"{command.damage_type or ''}伤害"
                )
                if command.damage_components:
                    reported_damage = int(result.get("original_damage", 0))
                    adjusted_damage = int(result.get("adjusted_damage", 0))
                    if reported_damage != adjusted_damage:
                        action_result += (
                            f"；实际扣除 {adjusted_damage} 点"
                            f"（原始报告 {reported_damage} 点）"
                        )
                if summon_ended:
                    action_result += "；召唤物生命归零，已离开战斗"
                if combatant_deactivated:
                    action_result += "；单位生命归零，已离开先攻轨道"
                window_summary = self._action_window_summary(
                    command.action_cost,
                    legendary_cost=command.legendary_cost,
                    legendary_pool_max=command.legendary_pool_max,
                    reaction_trigger=command.reaction_trigger,
                    reaction_event=command.reaction_event,
                )
                if window_summary:
                    action_result += f"；{window_summary}"
                action_summary = (
                    f"{actor.display_name} 对 {target.display_name} 使用"
                    f"「{command.action_name or '攻击'}」；{action_result}"
                )
            elif command.action_type == "damage":
                action_summary = (
                    f"{target.display_name} 受到 {result['adjusted_damage']} 点"
                    f"{command.damage_type or ''}伤害"
                )
                if command.damage_components:
                    reported_damage = int(result.get("original_damage", 0))
                    adjusted_damage = int(result.get("adjusted_damage", 0))
                    if reported_damage != adjusted_damage:
                        action_summary += (
                            f"；实际扣除 {adjusted_damage} 点"
                            f"（原始报告 {reported_damage} 点）"
                        )
                if summon_ended:
                    action_summary += "；召唤物生命归零，已离开战斗"
                window_summary = self._action_window_summary(
                    command.action_cost,
                    legendary_cost=command.legendary_cost,
                    legendary_pool_max=command.legendary_pool_max,
                    reaction_trigger=command.reaction_trigger,
                    reaction_event=command.reaction_event,
                )
                if window_summary:
                    action_summary += f"；{window_summary}"
            else:
                action_summary = (
                    f"{target.display_name} 恢复 {result['hp_gained']} 点生命"
                )
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=actor.id if actor is not None else None,
                transaction_id=transaction.id,
                action_type=command.action_type,
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=result.get("explanation"),
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=action_summary,
                idempotency_key=idempotency_key,
                dm_override=command.dm_override,
                override_reason=command.override_reason,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            if reaction_window is not None:
                window_result = dict(reaction_window.result_json or {})
                window_metadata = dict(window_result.get("action_window") or {})
                window_metadata.update(
                    {
                        "status": "resolved",
                        "resolved_action_id": action.id,
                        "resolved_target_combatant_id": target.id,
                    }
                )
                reaction_window.result_json = {
                    **window_result,
                    "action_window": window_metadata,
                }
                reaction_window.version += 1
                reaction_window.updated_at = now
            movement = structured_effects.get("movement")
            if isinstance(movement, dict) and int(movement.get("moved_ft") or 0) > 0:
                self._persist_eligible_enters_reach_reaction_windows(
                    session,
                    combat=combat,
                    moving_combatant=target,
                    from_position=(
                        int(movement["from"]["row"]),
                        int(movement["from"]["col"]),
                    ),
                    to_position=(
                        int(movement["to"]["row"]),
                        int(movement["to"]["col"]),
                    ),
                    movement_key=idempotency_key,
                    transaction=transaction,
                )
            session.flush()
            if (
                command.action_type == "damage"
                and int(result.get("adjusted_damage", 0)) > 0
            ):
                self._persist_eligible_damage_reaction_windows(
                    session,
                    combat=combat,
                    transaction=transaction,
                    damage_action=action,
                    damaged_targets=[
                        (target, int(result["adjusted_damage"]))
                    ],
                )
            self._persist_eligible_cast_spell_reaction_windows(
                session,
                combat=combat,
                transaction=transaction,
                spell_action=action,
            )
            concentration_prompts: list[dict[str, object]] = []
            raw_concentration_dc = result.get("concentration_check_dc")
            if (
                command.action_type == "damage"
                and isinstance(raw_concentration_dc, int)
                and bool(target.concentration)
                and target.hp > 0
                and target.is_active
                and not self._has_condition(target, "unconscious")
            ):
                concentration_prompts = self._persist_concentration_prompts(
                    session,
                    combat,
                    action,
                    [(target.id, raw_concentration_dc)],
                )
            effect_ids = structured_effects.get("effect_ids", [])
            if isinstance(effect_ids, list):
                for effect_id in effect_ids:
                    effect = session.get(CombatEffect, effect_id)
                    if effect is not None and effect.source_action_id is None:
                        effect.source_action_id = action.id
            return {
                "action": serialize(action),
                "actor": serialize(actor) if actor is not None else None,
                "target": serialize(target),
                "death_save": (
                    serialize(death_save)
                    if death_save is not None
                    else None
                ),
                "concentration_prompts": concentration_prompts,
                "end_condition": self._end_condition(session, combat),
            }

    def confirm_feature_action(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatFeatureActionCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Apply a class feature whose registry has an executable contract.

        Class advancement records are intentionally not executable by name.
        Combat receives a frozen ``feature_runtime`` registry when the unit is
        created; this endpoint resolves only an entry from that registry and
        records the resource/effect transition as one combat action.
        """

        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                actor = (
                    session.get(Combatant, existing.actor_combatant_id)
                    if existing.actor_combatant_id
                    else None
                )
                return {
                    "action": serialize(existing),
                    "actor": serialize(actor) if actor is not None else None,
                    "already_applied": True,
                }
            actor = session.get(Combatant, command.actor_combatant_id)
            if actor is None or actor.combat_id != combat_id or not actor.is_active:
                raise StateNotFoundError("feature action actor not found in combat")
            if actor.version != command.actor_version:
                raise VersionConflict(
                    "combatant", actor.id, command.actor_version, actor.version
                )
            ordered = self._ordered_combatants(session, combat_id)
            active = (
                ordered[combat.current_turn_index]
                if 0 <= combat.current_turn_index < len(ordered)
                else None
            )
            if active is None or active.id != actor.id:
                raise ValueError("职业特性只能在该单位的当前回合使用")
            self._validate_can_act(actor)
            registry = actor.snapshot_json.get("feature_runtime")
            registry_data = dict(registry) if isinstance(registry, dict) else {}
            raw_actions = registry_data.get("actions")
            action = (
                dict(raw_actions.get(command.feature_id))
                if isinstance(raw_actions, dict)
                and isinstance(raw_actions.get(command.feature_id), dict)
                else None
            )
            if action is None or action.get("kind") != "feature_action":
                raise ValueError("该职业特性没有可执行的运行时积木")
            action_cost = str(action.get("action_cost") or "none")
            if action_cost not in {"action", "bonus_action", "reaction", "none"}:
                raise ValueError("职业特性的动作经济类型无效")
            if action_cost == "reaction":
                raise ValueError("该职业特性需要 DM 明确实现反应触发条件")
            target = actor
            if command.target_combatant_id is not None:
                target = session.get(Combatant, command.target_combatant_id)
                if target is None or target.combat_id != combat_id or not target.is_active:
                    raise StateNotFoundError("feature action target not found in combat")
                if command.target_version != target.version:
                    raise VersionConflict(
                        "combatant", target.id, command.target_version or 0, target.version
                    )
            if action.get("target") == "self" and target.id != actor.id:
                raise ValueError("该职业特性只能以自身为目标")
            if action_cost == "none" and actor.version != command.actor_version:
                raise VersionConflict(
                    "combatant", actor.id, command.actor_version, actor.version
                )
            if action_cost != "none":
                self._validate_action_economy(
                    session,
                    combat,
                    actor,
                    actor_version=command.actor_version,
                    action_cost=action_cost,
                    consume=True,
                )

            character = (
                session.get(Character, actor.entity_id)
                if actor.entity_type == "character" and actor.entity_id
                else None
            )
            resource_key = str(action.get("resource_key") or "").strip()
            resource_cost = int(action.get("resource_cost") or 0)
            if action.get("resource_cost_mode") == "amount":
                if command.healing_total is None or command.healing_total < 1:
                    raise ValueError("该职业特性需要填写本次实际消耗的资源数量")
                resource_cost = command.healing_total
            resource_before: int | None = None
            resource_after: int | None = None
            if resource_key and resource_cost:
                if character is None:
                    raise ValueError("职业特性资源只能由角色单位消耗")
                resources = dict(character.resources or {})
                raw_resource = resources.get(resource_key)
                resource = dict(raw_resource) if isinstance(raw_resource, dict) else {}
                resource_before = self._state_int(resource.get("current"))
                if resource_before < resource_cost:
                    raise ValueError(f"职业特性资源不足：{resource_key}")
                resource_after = resource_before - resource_cost
                resource["current"] = resource_after
                resources[resource_key] = resource
                character.resources = resources
                character.version += 1
                character.updated_at = datetime.now(UTC)

            before = serialize(target)
            result: dict[str, Any] = {
                "feature_id": command.feature_id,
                "feature_name": action.get("name"),
                "action_cost": action_cost,
                "resource_key": resource_key or None,
                "resource_cost": resource_cost,
                "resource_before": resource_before,
                "resource_after": resource_after,
            }
            effects = action.get("effects")
            effect_list = effects if isinstance(effects, list) else []
            for effect in effect_list:
                if not isinstance(effect, dict):
                    continue
                kind = str(effect.get("kind") or "")
                if kind == "activate_condition":
                    condition = str(effect.get("condition") or "").strip()
                    if not condition:
                        continue
                    if self._condition_is_immune(target, condition):
                        raise ValueError(
                            f"目标免疫状态「{condition}」，职业特性未写入"
                        )
                    if not self._has_condition(target, condition):
                        self._apply_condition_restrictions(
                            target,
                            condition,
                            {},
                        )
                        if self._add_condition(target, condition):
                            result.setdefault("conditions_added", []).append(condition)
                elif kind == "activate_timed_condition":
                    condition = str(effect.get("condition") or "").strip()
                    expires = str(effect.get("expires") or "turn_start")
                    if condition != "隐形" or expires not in {"turn_start", "turn_end"}:
                        raise ValueError(
                            "当前职业特性只允许结构化的隐形持续到下一回合边界"
                        )
                    if self._condition_is_immune(target, condition):
                        raise ValueError(
                            f"目标免疫状态「{condition}」，职业特性未写入"
                        )
                    state_name = "feature_invisible"
                    runtime_effect = self._create_runtime_effect(
                        session,
                        combat,
                        actor=actor,
                        target=target,
                        state_name=state_name,
                        expires=expires,
                        expires_combatant_id=target.id,
                        details={"source": "compiled_feature_action"},
                    )
                    result.setdefault("conditions_added", []).append(condition)
                    result["effect_id"] = runtime_effect.id
                elif kind == "grant_action_budget":
                    amount = self._state_int(effect.get("amount"), 0)
                    if amount < 1:
                        continue
                    snapshot = dict(actor.snapshot_json or {})
                    previous = self._state_int(snapshot.get("extra_action_budget"), 0)
                    snapshot["extra_action_budget"] = previous + amount
                    actor.snapshot_json = snapshot
                    result["extra_action_budget"] = previous + amount
                elif kind == "grant_saving_throw_reroll":
                    snapshot = dict(actor.snapshot_json or {})
                    pending = snapshot.get("feature_saving_throw_rerolls")
                    rerolls = list(pending) if isinstance(pending, list) else []
                    rerolls.append(
                        {
                            "feature_id": command.feature_id,
                            "source": action.get("name"),
                            "scope": effect.get("scope") or "self",
                            "available": True,
                        }
                    )
                    snapshot["feature_saving_throw_rerolls"] = rerolls
                    actor.snapshot_json = snapshot
                    result["saving_throw_reroll_granted"] = True
                elif kind == "grant_roll_die":
                    die_key = str(effect.get("die_key") or "").strip()
                    if not die_key:
                        raise ValueError("职业特性的骰子效果缺少 die_key")
                    registry_resources = registry_data.get("resources")
                    die_value = None
                    if isinstance(registry_resources, dict):
                        raw_die = registry_resources.get(die_key)
                        if isinstance(raw_die, dict):
                            die_value = raw_die.get("value") or raw_die.get("label")
                    snapshot = dict(actor.snapshot_json or {})
                    feature_dice = dict(
                        snapshot.get("feature_dice")
                        if isinstance(snapshot.get("feature_dice"), dict)
                        else {}
                    )
                    feature_dice[die_key] = {
                        "source": action.get("name"),
                        "value": die_value,
                        "target_combatant_id": target.id,
                        "available": True,
                    }
                    snapshot["feature_dice"] = feature_dice
                    actor.snapshot_json = snapshot
                    result["roll_die_granted"] = {"die_key": die_key, "value": die_value}
                elif kind == "requires_dm_choice":
                    raise ValueError(str(effect.get("reason") or "该职业特性需要 DM 选择分支"))

            if action.get("resolution_kind") == "healing":
                total = command.healing_total
                if total is None:
                    raise ValueError("该职业特性需要填写治疗骰最终总值")
                formula = str(action.get("healing") or action.get("healing_formula") or "")
                match = re.search(r"1d(\d+)\s*\+\s*(\d+)", formula, re.IGNORECASE)
                if match and not command.dm_override:
                    minimum = 1 + int(match.group(2))
                    maximum = int(match.group(1)) + int(match.group(2))
                    if not minimum <= total <= maximum:
                        raise ValueError(f"治疗骰结果应在 {minimum}–{maximum} 之间")
                healing = resolve_healing(
                    amount=total,
                    current_hp=target.hp,
                    max_hp=target.max_hp,
                    max_hp_reduction=target.max_hp_reduction,
                )
                target.hp = healing.remaining_hp
                result["healing"] = {
                    "formula": formula,
                    "reported_total": total,
                    **asdict(healing),
                }
            elif action.get("resolution_kind") == "temporary_healing":
                total = command.healing_total
                if total is None or total < 1:
                    raise ValueError("该职业特性需要填写本次临时生命骰最终总值")
                before_temporary = target.temporary_hp
                target.temporary_hp = max(target.temporary_hp, total)
                result["temporary_healing"] = {
                    "reported_total": total,
                    "temporary_hp_before": before_temporary,
                    "temporary_hp_after": target.temporary_hp,
                    "replaced": total > before_temporary,
                }

            # A feature with no action cost (Action Surge) still changes the
            # combat snapshot and therefore needs a new CAS version.
            target.version += 1
            target.updated_at = datetime.now(UTC)
            if target.id != actor.id:
                actor.version += 1
                actor.updated_at = datetime.now(UTC)
            actor_snapshot = dict(actor.snapshot_json or {})
            if character is not None:
                actor_snapshot["resources"] = dict(character.resources or {})
            actor.snapshot_json = actor_snapshot
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_feature_action",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"actor": before},
                after_snapshot={"actor": serialize(target), "result": result},
                reason=command.override_reason or "compiled class feature confirmed",
                source="combat",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            summary = (
                f"{actor.display_name} 使用职业特性"
                f"「{action.get('name') or command.feature_id}」"
            )
            if isinstance(result.get("healing"), dict):
                summary += f"；恢复 {result['healing'].get('hp_gained', 0)} 点生命"
            if result.get("conditions_added"):
                summary += "；获得 " + "、".join(result["conditions_added"])
            if result.get("extra_action_budget"):
                summary += f"；额外动作预算 +{result['extra_action_budget']}"
            combat_action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=actor.id,
                transaction_id=transaction.id,
                action_type="feature_action",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=summary,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=summary,
                idempotency_key=idempotency_key,
                dm_override=command.dm_override,
                override_reason=command.override_reason,
                status="confirmed",
            )
            session.add(combat_action)
            session.flush()
            return {
                "action": serialize(combat_action),
                "actor": serialize(actor),
                "target": serialize(target),
                "result": result,
                "already_applied": False,
            }

    def confirm_monster_area_action(
        self,
        campaign_id: str,
        combat_id: str,
        command: MonsterAreaActionCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Atomically resolve one structured monster AoE against every grid target."""

        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                targets = [
                    target
                    for target_id in existing.target_combatant_ids
                    if (target := session.get(Combatant, target_id)) is not None
                ]
                actor = (
                    session.get(Combatant, existing.actor_combatant_id)
                    if existing.actor_combatant_id
                    else None
                )
                return {
                    "action": serialize(existing),
                    "actor": serialize(actor) if actor is not None else None,
                    "targets": [serialize(target) for target in targets],
                    "already_applied": True,
                }
            actor = session.get(Combatant, command.actor_combatant_id)
            if actor is None or actor.combat_id != combat.id or actor.entity_type != "monster":
                raise StateNotFoundError("monster area actor not found in combat")
            _, affected, geometry = self._monster_area_targets(
                session,
                combat,
                actor,
                command,
            )
            if (
                command.damage_total > 0
                or command.conditions_on_success
                or command.conditions_on_failure
            ):
                self._validate_charmed_harm_targets(
                    session,
                    combat,
                    actor,
                    [target.id for target in affected],
                    dm_override=command.dm_override,
                )
            target_commands = {
                target.target_combatant_id: target for target in command.targets
            }
            for target in affected:
                target_command = target_commands[target.id]
                if target.version != target_command.target_version:
                    raise VersionConflict(
                        "combatant",
                        target.id,
                        target_command.target_version,
                        target.version,
                    )
            before_actor = serialize(actor)
            before_targets = {target.id: serialize(target) for target in affected}
            economy_consumed = self._validate_action_economy(
                session,
                combat,
                actor,
                actor_version=command.actor_version,
                action_cost=command.action_cost,
                consume=True,
                legendary_cost=command.legendary_cost,
                legendary_pool_max=command.legendary_pool_max,
                reaction_trigger=command.reaction_trigger,
                action_name=command.action_name,
                reaction_event=command.reaction_event,
            )
            recharge_consumed = self._validate_recharge(
                actor,
                recharge_key=command.recharge_key,
                consume=command.recharge_consume,
            )
            if recharge_consumed and not economy_consumed:
                actor.version += 1
                actor.updated_at = datetime.now(UTC)
            now = datetime.now(UTC)
            target_results: list[dict[str, object]] = []
            effect_ids: list[str] = []
            summon_ids_to_end: list[str] = []
            deactivated_non_character_ids: list[str] = []
            damage_on_success = (
                command.damage_total // 2 if command.half_damage_on_save else 0
            )
            explicit_damage_components = bool(command.damage_components)
            damage_components = [
                {
                    "amount": component.amount,
                    "damage_type": component.damage_type,
                    "damage_tags": list(component.damage_tags),
                }
                for component in command.damage_components
            ] or [
                {
                    "amount": command.damage_total,
                    "damage_type": command.damage_type,
                    "damage_tags": list(command.damage_tags),
                }
            ]
            for target in affected:
                target_command = target_commands[target.id]
                defense = self._resolve_save_defenses(
                    target,
                    dc=command.save_dc,
                    ability=command.save_ability,
                    roll_total=target_command.roll_total,
                    roll_totals=target_command.roll_totals,
                    damage_on_success=damage_on_success,
                    damage_on_failure=command.damage_total,
                        is_magical=command.is_magical,
                        use_legendary_resistance=target_command.use_legendary_resistance,
                        use_feature_reroll=False,
                        consume=True,
                )
                succeeded = bool(defense["success"])
                component_results: list[dict[str, object]] = []
                applied_conditional_defenses: list[str] = []
                unresolved_conditional_defenses: list[str] = []
                current_hp = target.hp
                current_temporary_hp = target.temporary_hp
                for component in damage_components:
                    (
                        resistances,
                        vulnerabilities,
                        immunities,
                        component_applied_defenses,
                        component_unresolved_defenses,
                    ) = self._damage_defenses(
                        target,
                        command,
                        [str(component["damage_type"])],
                        damage_tags=(
                            list(component.get("damage_tags") or [])
                            or command.damage_tags
                        ),
                    )
                    component_amount = int(component["amount"])
                    # Apply the save result to every independently resisted
                    # segment.  This matters for fire + piercing effects:
                    # resistance/immune/vulnerability is never allowed to
                    # leak from one segment into another.
                    if not explicit_damage_components:
                        component_amount = self._state_int(defense["damage"])
                    elif defense["success"]:
                        component_amount = (
                            component_amount // 2
                            if command.half_damage_on_save
                            else 0
                        )
                    if explicit_damage_components:
                        # _resolve_save_defenses calculates Evasion and other
                        # reflex profiles for the aggregate damage as well as
                        # recording the applied defense.  Re-apply that same
                        # multiplier to every typed segment here; otherwise a
                        # fire + force area would bypass Evasion merely because
                        # the spell was represented as mixed damage.
                        applied_save_defenses = {
                            str(value) for value in defense["applied_defenses"]
                        }
                        if "evasion" in applied_save_defenses:
                            component_amount = (
                                0 if defense["success"] else component_amount // 2
                            )
                        elif "reflex_defense" in applied_save_defenses:
                            raw_defenses = dict(target.snapshot_json or {}).get(
                                "advanced_defenses"
                            )
                            reflex = (
                                dict(raw_defenses).get("reflex_defense")
                                if isinstance(raw_defenses, dict)
                                else None
                            )
                            if isinstance(reflex, dict):
                                multiplier_key = (
                                    "success_multiplier"
                                    if defense["success"]
                                    else "failure_multiplier"
                                )
                                multiplier = reflex.get(multiplier_key)
                                if isinstance(multiplier, (int, float)) and 0 <= multiplier <= 1:
                                    component_amount = floor(component_amount * multiplier)
                    component_resolution = resolve_damage(
                        amount=component_amount,
                        current_hp=current_hp,
                        temporary_hp=current_temporary_hp,
                        damage_type=str(component["damage_type"]),
                        resistances=resistances,
                        vulnerabilities=vulnerabilities,
                        immunities=immunities,
                    )
                    current_hp = component_resolution.remaining_hp
                    current_temporary_hp = component_resolution.remaining_temporary_hp
                    component_result = asdict(component_resolution)
                    component_result["damage_tags"] = list(component.get("damage_tags") or [])
                    component_result["conditional_defenses_applied"] = (
                        component_applied_defenses
                    )
                    component_result["conditional_defenses_unresolved"] = (
                        component_unresolved_defenses
                    )
                    component_results.append(component_result)
                    applied_conditional_defenses.extend(component_applied_defenses)
                    unresolved_conditional_defenses.extend(component_unresolved_defenses)
                modifiers = {str(item["modifier"]) for item in component_results}
                damage_result: dict[str, object] = {
                    "original_damage": sum(
                        int(item["original_damage"]) for item in component_results
                    ),
                    "adjusted_damage": sum(
                        int(item["adjusted_damage"]) for item in component_results
                    ),
                    "damage_type": "mixed" if len(damage_components) > 1 else command.damage_type,
                    "modifier": next(iter(modifiers)) if len(modifiers) == 1 else "mixed",
                    "temporary_hp_lost": sum(
                        int(item["temporary_hp_lost"]) for item in component_results
                    ),
                    "hp_lost": sum(int(item["hp_lost"]) for item in component_results),
                    "remaining_temporary_hp": current_temporary_hp,
                    "remaining_hp": current_hp,
                    "unapplied_damage": sum(
                        int(item["unapplied_damage"]) for item in component_results
                    ),
                    "explanation": "；".join(
                        str(item["explanation"]) for item in component_results
                    ),
                    "damage_components": component_results,
                }
                if damage_result["adjusted_damage"] > 0 and target.concentration:
                    damage_result["concentration_check_dc"] = max(
                        10,
                        int(damage_result["adjusted_damage"]) // 2,
                    )
                target.hp = current_hp
                target.temporary_hp = current_temporary_hp
                condition_changes = self._sync_zero_hp_lifecycle(
                    target,
                    before_hp=int(before_targets[target.id]["hp"]),
                )
                conditions = (
                    command.conditions_on_success
                    if succeeded
                    else command.conditions_on_failure
                )
                structured_effects: dict[str, object] = {}
                if conditions:
                    structured_effects = self._apply_structured_monster_effects(
                        session,
                        combat,
                        actor=actor,
                        target=target,
                        conditions=conditions,
                        condition_duration=command.condition_duration,
                        condition_duration_value=command.condition_duration_value,
                        condition_save_dc=command.condition_save_dc,
                        condition_save_ability=command.condition_save_ability,
                        movement_distance_ft=None,
                        movement_direction=None,
                    )
                    raw_effect_ids = structured_effects.get("effect_ids")
                    if isinstance(raw_effect_ids, list):
                        effect_ids.extend(
                            value for value in raw_effect_ids if isinstance(value, str)
                        )
                target.version += 1
                target.updated_at = now
                if target.hp == 0:
                    if self._is_summon(target):
                        summon_ids_to_end.append(target.id)
                    elif self._deactivate_zero_hp_non_character(target, now=now):
                        deactivated_non_character_ids.append(target.id)
                    else:
                        self._death_save(session, target)
                target_results.append(
                    {
                        "target_combatant_id": target.id,
                        "target_name": target.display_name,
                        "roll_total": defense["effective_roll_total"],
                        "reported_roll_totals": defense["reported_roll_totals"],
                        "success": succeeded,
                        "applied_defenses": defense["applied_defenses"],
                        "conditional_defenses_applied": applied_conditional_defenses,
                        "conditional_defenses_unresolved": unresolved_conditional_defenses,
                        "defense_resource_consumed": defense[
                            "defense_resource_consumed"
                        ],
                        "damage": damage_result,
                        "structured_effects": structured_effects,
                        "condition_changes": condition_changes,
                        "combatant_deactivated": target.id in deactivated_non_character_ids,
                        "geometry": geometry[target.id],
                    }
                )
            ended_summons = self._deactivate_summons(
                session,
                combat,
                summon_ids_to_end,
                now=now,
            )
            damaged_combatant_ids = {
                str(item["target_combatant_id"])
                for item in target_results
                if isinstance(item.get("damage"), dict)
                and self._state_int(item["damage"].get("adjusted_damage")) > 0
            }
            ended_predicated_effects, ended_predicated_summons = (
                self._end_predicated_effects(
                    session,
                    combat,
                    now=now,
                    event_combatant_ids=damaged_combatant_ids,
                    event_kinds={"damage"} if damaged_combatant_ids else set(),
                    event_only=True,
                )
            )
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_monster_area_action",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"actor": before_actor, "targets": before_targets},
                after_snapshot={
                    "actor": serialize(actor),
                    "targets": {target.id: serialize(target) for target in affected},
                    "ended_summon_ids": [target.id for target in ended_summons],
                    "ended_predicated_effect_ids": [
                        effect.id for effect in ended_predicated_effects
                    ],
                    "ended_predicated_summon_ids": [
                        summon.id for summon in ended_predicated_summons
                    ],
                },
                reason=command.dm_geometry_note,
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            action_result: dict[str, object] = {
                "shape": command.shape,
                "size_ft": command.size_ft,
                "width_ft": command.width_ft,
                "height_ft": command.height_ft,
                "anchor": {"row": command.anchor_row, "col": command.anchor_col},
                "anchor_height_ft": command.anchor_height_ft,
                "damage_components": damage_components,
                "target_results": target_results,
                "recharge_consumed": command.recharge_key if recharge_consumed else None,
                "ended_summon_ids": [target.id for target in ended_summons],
                "deactivated_non_character_ids": deactivated_non_character_ids,
                "ended_predicated_effect_ids": [
                    effect.id for effect in ended_predicated_effects
                ],
                "ended_predicated_summon_ids": [
                    summon.id for summon in ended_predicated_summons
                ],
            }
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=actor.id,
                transaction_id=transaction.id,
                action_type="monster_area_action",
                target_combatant_ids=[target.id for target in affected],
                request_json=command.model_dump(mode="json"),
                result_json=action_result,
                explanation=command.dm_geometry_note,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"{actor.display_name} 使用「{command.action_name}」，"
                    f"按 {command.shape} 区域结算 {len(affected)} 个目标"
                ),
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            damaged_targets_for_reactions: list[tuple[Combatant, int]] = []
            affected_by_id = {target.id: target for target in affected}
            for target_result in target_results:
                if not isinstance(target_result.get("damage"), dict):
                    continue
                adjusted_damage = self._state_int(
                    target_result["damage"].get("adjusted_damage")
                )
                damaged_target = affected_by_id.get(
                    str(target_result.get("target_combatant_id"))
                )
                if damaged_target is not None and adjusted_damage > 0:
                    damaged_targets_for_reactions.append(
                        (damaged_target, adjusted_damage)
                    )
            self._persist_eligible_damage_reaction_windows(
                session,
                combat=combat,
                transaction=transaction,
                damage_action=action,
                damaged_targets=damaged_targets_for_reactions,
            )
            self._persist_eligible_cast_spell_reaction_windows(
                session,
                combat=combat,
                transaction=transaction,
                spell_action=action,
            )
            concentration_prompts = self._persist_concentration_prompts(
                session,
                combat,
                action,
                [
                    (
                        str(item["target_combatant_id"]),
                        int(item["damage"]["concentration_check_dc"]),
                    )
                    for item in target_results
                    if isinstance(item.get("damage"), dict)
                    and isinstance(
                        item["damage"].get("concentration_check_dc"),
                        int,
                    )
                ],
            )
            for effect_id in effect_ids:
                effect = session.get(CombatEffect, effect_id)
                if effect is not None and effect.source_action_id is None:
                    effect.source_action_id = action.id
            return {
                "action": serialize(action),
                "actor": serialize(actor),
                "targets": [serialize(target) for target in affected],
                "ended_summons": [serialize(target) for target in ended_summons],
                "ended_predicated_effects": [
                    serialize(effect) for effect in ended_predicated_effects
                ],
                "ended_predicated_summons": [
                    serialize(summon) for summon in ended_predicated_summons
                ],
                "concentration_prompts": concentration_prompts,
                "already_applied": False,
            }

    def confirm_maneuver(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatManeuverCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Execute movement/control maneuvers without inventing contested rolls.

        Dash and standing up are deterministic. Grapple and shove deliberately
        require an explicit DM-adjudicated outcome because the combat snapshot
        does not always contain reach, size, proficiency, or save DC data.
        Once adjudicated, their state and grid consequences are authoritative.
        """

        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                actor = (
                    session.get(Combatant, existing.actor_combatant_id)
                    if existing.actor_combatant_id
                    else None
                )
                target_id = (
                    existing.target_combatant_ids[0]
                    if existing.target_combatant_ids
                    else None
                )
                target = session.get(Combatant, target_id) if target_id else None
                effect_id = existing.result_json.get("effect_id")
                existing_effect = (
                    session.get(CombatEffect, effect_id)
                    if isinstance(effect_id, str)
                    else None
                )
                return {
                    "action": serialize(existing),
                    "actor": serialize(actor) if actor is not None else None,
                    "target": serialize(target) if target is not None else None,
                    "effect": (
                        serialize(existing_effect) if existing_effect is not None else None
                    ),
                    "already_applied": True,
                }
            if combat.status != "active":
                raise ValueError("maneuvers require an active combat")
            actor = session.get(Combatant, command.actor_combatant_id)
            if actor is None or actor.combat_id != combat_id:
                raise StateNotFoundError("actor combatant not found in combat")
            target = (
                session.get(Combatant, command.target_combatant_id)
                if command.target_combatant_id is not None
                else None
            )
            if command.target_combatant_id is not None and (
                target is None or target.combat_id != combat_id
            ):
                raise StateNotFoundError("target combatant not found in combat")
            if target is not None and target.id == actor.id:
                raise ValueError(f"a combatant cannot use {command.action_type} on itself")
            ready_effect: CombatEffect | None = None
            if command.action_type == "ready" and command.ready_phase == "trigger":
                if not actor.is_active:
                    raise ValueError("inactive combatants cannot trigger Ready")
                if actor.version != command.actor_version:
                    raise VersionConflict(
                        "combatant",
                        actor.id,
                        command.actor_version,
                        actor.version,
                    )
                self._validate_can_act(actor)
                ready_effect = session.get(CombatEffect, command.ready_effect_id)
                if (
                    ready_effect is None
                    or ready_effect.combat_id != combat.id
                    or ready_effect.target_combatant_id != actor.id
                    or ready_effect.status != "active"
                    or (ready_state := self._runtime_state(ready_effect)) is None
                    or ready_state.get("name") != "ready"
                ):
                    raise ValueError("Ready effect is not active for this combatant")
                if ready_effect.version != command.ready_effect_version:
                    raise VersionConflict(
                        "combat_effect",
                        ready_effect.id,
                        command.ready_effect_version or 0,
                        ready_effect.version,
                    )
            else:
                self._validate_active_actor(
                    session,
                    combat,
                    actor,
                    actor_version=command.actor_version,
                )
            if target is not None and target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version or 0,
                    target.version,
                )
            if (
                command.action_type == "grapple"
                and command.outcome == "success"
                and target is not None
            ):
                immunity_names = {
                    str(value).strip().lower()
                    for value in list(target.condition_immunities or [])
                }
                if {"擒抱", "grappled"} & immunity_names:
                    raise ValueError("目标免疫擒抱；如有例外需由 DM 改判为失败或另行裁定")
                if self._has_condition(target, "擒抱"):
                    raise ValueError("目标已经处于擒抱状态")
            if (
                command.action_type == "shove"
                and command.shove_mode == "prone"
                and command.outcome == "success"
                and target is not None
            ):
                immunity_names = {
                    str(value).strip().lower()
                    for value in list(target.condition_immunities or [])
                }
                if {"倒地", "prone"} & immunity_names:
                    raise ValueError("目标免疫倒地；如有例外需由 DM 改判为失败或另行裁定")

            before_actor = serialize(actor)
            before_target = serialize(target) if target is not None else None
            before_item: dict[str, Any] | None = None
            after_item: dict[str, Any] | None = None
            before_object: dict[str, Any] | None = None
            after_object: dict[str, Any] | None = None
            used_item: WorldItem | None = None
            interacted_object: SceneObject | None = None
            effect: CombatEffect | None = None
            result: dict[str, object] = {
                "outcome": command.outcome or "success",
                "adjudication_note": command.adjudication_note,
            }
            if command.action_type == "ready" and command.ready_phase == "trigger":
                effect = ready_effect
                if command.outcome == "success":
                    self._validate_action_economy(
                        session,
                        combat,
                        actor,
                        actor_version=command.actor_version,
                        action_cost="reaction",
                        consume=True,
                        reaction_trigger=(
                            str(ready_state.get("trigger") or "Ready trigger confirmed by DM")
                            if isinstance(ready_state, dict)
                            else "Ready trigger confirmed by DM"
                        ),
                    )
                    if effect is not None:
                        self._end_runtime_effect(
                            session,
                            effect,
                            reason="DM confirmed the prepared trigger occurred",
                            now=datetime.now(UTC),
                        )
                    result.update(
                        {
                            "effect_id": effect.id if effect is not None else None,
                            "reaction_spent": True,
                            "prepared_response": (
                                ready_state.get("response")
                                if isinstance(ready_state, dict)
                                else None
                            ),
                        }
                    )
                else:
                    result.update(
                        {
                            "effect_id": effect.id if effect is not None else None,
                            "reaction_spent": False,
                            "state_remains_active": True,
                        }
                    )
            elif command.action_type == "dash":
                self._validate_action_economy(
                    session,
                    combat,
                    actor,
                    actor_version=command.actor_version,
                    action_cost="action",
                    consume=True,
                )
                gained = actor.speed_ft
                actor.movement_remaining_ft += gained
                result.update(
                    {
                        "movement_gained_ft": gained,
                        "movement_remaining_ft": actor.movement_remaining_ft,
                    }
                )
            elif command.action_type == "stand_up":
                if not self._has_condition(actor, "倒地"):
                    raise ValueError("combatant is not prone")
                movement_cost = (actor.speed_ft + 1) // 2
                if movement_cost <= 0 or actor.movement_remaining_ft < movement_cost:
                    raise ValueError("起身需要消耗速度的一半；当前移动额度不足，需 DM 裁定")
                self._remove_condition(actor, "倒地")
                actor.movement_remaining_ft -= movement_cost
                actor.version += 1
                actor.updated_at = datetime.now(UTC)
                result.update(
                    {
                        "movement_cost_ft": movement_cost,
                        "movement_remaining_ft": actor.movement_remaining_ft,
                        "condition_removed": "倒地",
                    }
                )
            elif command.action_type in {
                "dodge",
                "help",
                "ready",
                "search",
                "hide",
                "disengage",
                "use_item",
                "object_interaction",
            }:
                self._validate_action_economy(
                    session,
                    combat,
                    actor,
                    actor_version=command.actor_version,
                    action_cost="action",
                    consume=True,
                )
                if command.action_type == "dodge":
                    if actor.speed_ft <= 0 or self._movement_is_blocked(actor):
                        raise ValueError(
                            "Dodge provides no benefit while speed is 0 or movement is blocked"
                        )
                    effect = self._create_runtime_effect(
                        session,
                        combat,
                        actor=actor,
                        target=actor,
                        state_name="dodge",
                        expires="turn_start",
                        expires_combatant_id=actor.id,
                    )
                    result["effect_id"] = effect.id
                elif command.action_type == "help":
                    assert target is not None
                    effect = self._create_runtime_effect(
                        session,
                        combat,
                        actor=actor,
                        target=target,
                        state_name="help",
                        expires="turn_start",
                        expires_combatant_id=actor.id,
                        details={"trigger": command.help_trigger or ""},
                    )
                    target.version += 1
                    target.updated_at = datetime.now(UTC)
                    result.update(
                        {
                            "effect_id": effect.id,
                            "help_trigger": command.help_trigger,
                        }
                    )
                elif command.action_type == "ready":
                    effect = self._create_runtime_effect(
                        session,
                        combat,
                        actor=actor,
                        target=actor,
                        state_name="ready",
                        expires="turn_start",
                        expires_combatant_id=actor.id,
                        details={
                            "trigger": command.ready_trigger or "",
                            "response": command.ready_response or "",
                        },
                    )
                    result.update(
                        {
                            "effect_id": effect.id,
                            "ready_trigger": command.ready_trigger,
                            "ready_response": command.ready_response,
                            "reaction_required_when_triggered": True,
                        }
                    )
                elif command.action_type == "search":
                    assert target is not None
                    ended_hidden: list[CombatEffect] = []
                    if command.outcome == "success":
                        for hidden_effect in self._active_runtime_effects(
                            session,
                            combat.id,
                            target_id=target.id,
                            state_name="hidden",
                        ):
                            if self._end_runtime_effect(
                                session,
                                hidden_effect,
                                reason="DM confirmed Search revealed the hidden combatant",
                                now=datetime.now(UTC),
                            ) is not None:
                                ended_hidden.append(hidden_effect)
                        if ended_hidden:
                            target.version += 1
                            target.updated_at = datetime.now(UTC)
                    result.update(
                        {
                            "revealed": bool(ended_hidden),
                            "ended_effect_ids": [row.id for row in ended_hidden],
                        }
                    )
                elif command.action_type == "hide":
                    if command.outcome == "success":
                        effect = self._create_runtime_effect(
                            session,
                            combat,
                            actor=actor,
                            target=actor,
                            state_name="hidden",
                            expires="triggered",
                            expires_combatant_id=None,
                        )
                        result["effect_id"] = effect.id
                    result["hidden"] = command.outcome == "success"
                elif command.action_type == "disengage":
                    effect = self._create_runtime_effect(
                        session,
                        combat,
                        actor=actor,
                        target=actor,
                        state_name="disengage",
                        expires="turn_end",
                        expires_combatant_id=actor.id,
                    )
                    result["effect_id"] = effect.id
                elif command.action_type == "use_item":
                    used_item = session.get(WorldItem, command.item_id)
                    if (
                        used_item is None
                        or used_item.campaign_id != campaign_id
                        or used_item.owner_character_id != actor.entity_id
                    ):
                        raise StateNotFoundError("item not found in the actor's inventory")
                    if used_item.version != command.item_version:
                        raise VersionConflict(
                            "world_item",
                            used_item.id,
                            command.item_version or 0,
                            used_item.version,
                        )
                    before_item = serialize(used_item)
                    if used_item.quantity <= 1:
                        session.delete(used_item)
                        result.update(
                            {
                                "item_consumed": True,
                                "item_id": used_item.id,
                                "item_name": used_item.name,
                                "quantity_after": 0,
                            }
                        )
                    else:
                        used_item.quantity -= 1
                        used_item.version += 1
                        used_item.updated_at = datetime.now(UTC)
                        after_item = serialize(used_item)
                        result.update(
                            {
                                "item_consumed": True,
                                "item_id": used_item.id,
                                "item_name": used_item.name,
                                "quantity_after": used_item.quantity,
                            }
                        )
                else:
                    if combat.scene_id is None:
                        raise ValueError("object interaction requires a scene-backed combat")
                    interacted_object = session.get(SceneObject, command.object_id)
                    if (
                        interacted_object is None
                        or interacted_object.scene_id != combat.scene_id
                    ):
                        raise StateNotFoundError("scene object not found in combat scene")
                    if interacted_object.version != command.object_version:
                        raise VersionConflict(
                            "scene_object",
                            interacted_object.id,
                            command.object_version or 0,
                            interacted_object.version,
                        )
                    before_object = serialize(interacted_object)
                    if interacted_object.state == command.object_state:
                        raise ValueError("object is already in the requested state")
                    interacted_object.state = command.object_state or interacted_object.state
                    interacted_object.version += 1
                    interacted_object.updated_at = datetime.now(UTC)
                    after_object = serialize(interacted_object)
                    result.update(
                        {
                            "object_id": interacted_object.id,
                            "object_label": interacted_object.label,
                            "object_state_before": before_object["state"],
                            "object_state_after": interacted_object.state,
                        }
                    )
            else:
                self._validate_action_economy(
                    session,
                    combat,
                    actor,
                    actor_version=command.actor_version,
                    action_cost="action",
                    consume=True,
                )
                if command.outcome == "success" and target is not None:
                    if command.action_type == "grapple":
                        applied_state = {
                            "conditions": list(target.conditions or []),
                            "speed_ft": target.speed_ft,
                            "movement_remaining_ft": target.movement_remaining_ft,
                        }
                        self._apply_condition_restrictions(
                            target,
                            "grappled",
                            applied_state,
                        )
                        # Preserve the existing public Chinese label while
                        # _condition_set canonicalizes it to ``grappled``.
                        self._add_condition(target, "擒抱")
                        effect = CombatEffect(
                            campaign_id=campaign_id,
                            combat_id=combat_id,
                            target_combatant_id=target.id,
                            source_combatant_id=actor.id,
                            name=f"被 {actor.display_name} 擒抱",
                            effect_type="condition",
                            details_json={
                                "maneuver": "grapple",
                                "rule_block": {
                                    "kind": "condition",
                                    "condition": "擒抱",
                                    "end_triggers": [
                                        "source_incapacitated",
                                        "target_out_of_reach",
                                    ],
                                    "reach_ft": 5,
                                },
                                "applied_state": applied_state,
                                "dm_adjudication": command.adjudication_note,
                            },
                            started_round=combat.round_number,
                            duration_unit="until_removed",
                            requires_concentration=False,
                            status="active",
                        )
                        session.add(effect)
                        session.flush()
                        result.update(
                            {
                                "condition_applied": "擒抱",
                                "speed_ft": 0,
                                "effect_id": effect.id,
                            }
                        )
                    elif command.shove_mode == "prone":
                        if not self._has_condition(target, "倒地"):
                            target.conditions = list(target.conditions or []) + ["倒地"]
                        result["condition_applied"] = "倒地"
                    else:
                        result.update(
                            self._move_away_on_grid(
                                session,
                                combat,
                                target=target,
                                source=actor,
                                distance_ft=command.push_distance_ft or 0,
                                direction="away",
                            )
                        )
                    target.version += 1
                    target.updated_at = datetime.now(UTC)

            now = datetime.now(UTC)
            if (
                command.action_type == "shove"
                and isinstance(result.get("moved_ft"), int)
                and int(result["moved_ft"]) > 0
                and target is not None
            ):
                ended_predicated_effects, ended_predicated_summons = (
                    self._end_predicated_effects(
                        session,
                        combat,
                        now=now,
                        event_combatant_ids={target.id},
                        event_kinds={"movement"},
                        event_only=True,
                    )
                )
                if ended_predicated_effects:
                    result["ended_predicated_effect_ids"] = [
                        effect.id for effect in ended_predicated_effects
                    ]
                if ended_predicated_summons:
                    result["ended_predicated_summon_ids"] = [
                        summon.id for summon in ended_predicated_summons
                    ]
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type=f"combat_maneuver_{command.action_type}",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={
                    "actor": before_actor,
                    "target": before_target,
                    "item": before_item,
                    "object": before_object,
                },
                after_snapshot={
                    "actor": serialize(actor),
                    "target": serialize(target) if target is not None else None,
                    "item": after_item,
                    "object": after_object,
                    "result": result,
                },
                reason=(
                    command.adjudication_note
                    or f"{command.action_type} resolved by combat rules"
                ),
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            label = {
                "dash": "疾走",
                "stand_up": "起身",
                "grapple": "擒抱",
                "shove": "推撞",
                "dodge": "闪避",
                "help": "协助",
                "ready": "准备",
                "search": "搜索",
                "hide": "躲藏",
                "disengage": "撤离",
                "use_item": "使用物品",
                "object_interaction": "物件互动",
            }[command.action_type]
            outcome_label = "成功" if result["outcome"] == "success" else "失败"
            summary = f"{actor.display_name} 使用{label}"
            if target is not None:
                summary += f"对抗 {target.display_name}，{outcome_label}"
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=actor.id,
                transaction_id=transaction.id,
                action_type=command.action_type,
                target_combatant_ids=[target.id] if target is not None else [],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=command.adjudication_note,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=summary,
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            if effect is not None and effect.source_action_id is None:
                effect.source_action_id = action.id
            return {
                "action": serialize(action),
                "actor": serialize(actor),
                "target": serialize(target) if target is not None else None,
                "effect": serialize(effect) if effect is not None else None,
                "item": (
                    serialize(used_item)
                    if used_item is not None and after_item is not None
                    else None
                ),
                "object": serialize(interacted_object) if interacted_object is not None else None,
                "already_applied": False,
            }

    @classmethod
    def _move_away_on_grid(
        cls,
        session: Session,
        combat: Combat,
        *,
        target: Combatant,
        source: Combatant,
        distance_ft: int,
        direction: str = "away",
    ) -> dict[str, object]:
        raw_target = target.snapshot_json.get("grid_position")
        raw_source = source.snapshot_json.get("grid_position")
        if not isinstance(raw_target, dict):
            raise ValueError("强制位移目标尚未设置战斗地图位置，需 DM 裁定")
        if not isinstance(raw_source, dict):
            raise ValueError("强制位移来源尚未设置战斗地图位置，需 DM 裁定")
        target_point = (int(raw_target.get("row", 0)), int(raw_target.get("col", 0)))
        source_point = (int(raw_source.get("row", 0)), int(raw_source.get("col", 0)))
        delta_row = target_point[0] - source_point[0]
        delta_col = target_point[1] - source_point[1]
        if direction in {"toward", "pull"}:
            delta_row, delta_col = -delta_row, -delta_col
        step_row = 0 if delta_row == 0 else (1 if delta_row > 0 else -1)
        step_col = 0 if delta_col == 0 else (1 if delta_col > 0 else -1)
        if step_row == 0 and step_col == 0:
            raise ValueError("强制位移无法确定方向，需 DM 裁定")
        grid = (
            session.scalar(select(SceneGrid).where(SceneGrid.scene_id == combat.scene_id))
            if combat.scene_id
            else None
        )
        blocked: set[tuple[int, int]] = set()
        if combat.scene_id:
            for obj in session.scalars(
                select(SceneObject).where(SceneObject.scene_id == combat.scene_id)
            ).all():
                if obj.object_type == "wall" or (
                    obj.object_type == "door" and obj.state in {"active", "closed"}
                ):
                    blocked.update(
                        {
                            (row, col)
                            for row in range(obj.row, obj.row + obj.height_cells)
                            for col in range(obj.col, obj.col + obj.width_cells)
                        }
                    )
        occupied = {
            (int(pos["row"]), int(pos["col"]))
            for item in cls._ordered_combatants(session, combat.id)
            if item.id != target.id
            for pos in [item.snapshot_json.get("grid_position")]
            if isinstance(pos, dict) and "row" in pos and "col" in pos
        }
        cell_size = grid.cell_size_ft if grid is not None else 5
        if distance_ft % cell_size != 0:
            raise ValueError(
                f"强制位移距离必须与当前 {cell_size} 尺网格对齐，需 DM 裁定"
            )
        steps = distance_ft // cell_size
        current = target_point
        moved_steps = 0
        for _ in range(steps):
            candidate = (current[0] + step_row, current[1] + step_col)
            if grid is not None and not (
                1 <= candidate[0] <= grid.height and 1 <= candidate[1] <= grid.width
            ):
                break
            if candidate in blocked or candidate in occupied:
                break
            current = candidate
            moved_steps += 1
        moved_ft = moved_steps * cell_size
        snapshot = dict(target.snapshot_json)
        position = dict(raw_target)
        position.update({"row": current[0], "col": current[1]})
        snapshot["grid_position"] = position
        target.snapshot_json = snapshot
        return {
            "moved_ft": moved_ft,
            "requested_ft": distance_ft,
            "direction": direction,
            "blocked": moved_ft < distance_ft,
            "from": {"row": target_point[0], "col": target_point[1]},
            "to": {"row": current[0], "col": current[1]},
        }

    def apply_forced_movement(
        self,
        campaign_id: str,
        combat_id: str,
        *,
        target_combatant_id: str,
        source_combatant_id: str | None,
        distance_ft: int,
        direction: str,
        target_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Move a target along the combat grid without teleporting through blockers."""

        if distance_ft < 0:
            raise ValueError("forced movement distance cannot be negative")
        with Session(self.engine) as session, session.begin():
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                target = session.get(Combatant, target_combatant_id)
                return {
                    "action": serialize(existing),
                    "target": serialize(target) if target is not None else None,
                    "moved_ft": existing.result_json.get("moved_ft", 0),
                }
            target = session.get(Combatant, target_combatant_id)
            if target is None or target.combat_id != combat_id:
                raise StateNotFoundError("target combatant not found in combat")
            if target.version != target_version:
                raise VersionConflict("combatant", target.id, target_version, target.version)
            source = (
                session.get(Combatant, source_combatant_id)
                if source_combatant_id
                else None
            )
            if source is None or source.combat_id != combat_id:
                raise StateNotFoundError("source combatant not found in combat")
            before_target = serialize(target)
            result = self._move_away_on_grid(
                session,
                combat,
                target=target,
                source=source,
                distance_ft=distance_ft,
                direction=direction,
            )
            target.version += 1
            target.updated_at = datetime.now(UTC)
            now = datetime.now(UTC)
            ended_predicated_effects, ended_predicated_summons = (
                self._end_predicated_effects(
                    session,
                    combat,
                    now=now,
                    event_combatant_ids={target.id},
                    event_kinds={"movement"} if result["moved_ft"] > 0 else set(),
                    event_only=True,
                )
            )
            if ended_predicated_effects:
                result["ended_predicated_effect_ids"] = [
                    effect.id for effect in ended_predicated_effects
                ]
            if ended_predicated_summons:
                result["ended_predicated_summon_ids"] = [
                    summon.id for summon in ended_predicated_summons
                ]
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_forced_movement",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"target": before_target, "from": result["from"]},
                after_snapshot={"target": serialize(target), "result": result},
                reason="按规则积木执行强制位移",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=source.id if source is not None else None,
                transaction_id=transaction.id,
                action_type="forced_movement",
                target_combatant_ids=[target.id],
                request_json={
                    "distance_ft": distance_ft,
                    "direction": direction,
                    "source_combatant_id": source_combatant_id,
                },
                result_json=result,
                explanation="强制位移遇到地图边界、障碍物或其他单位时停止",
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{target.display_name} 被强制移动 {result['moved_ft']} 尺",
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            if result["moved_ft"] > 0:
                self._persist_eligible_enters_reach_reaction_windows(
                    session,
                    combat=combat,
                    moving_combatant=target,
                    from_position=(
                        int(result["from"]["row"]),
                        int(result["from"]["col"]),
                    ),
                    to_position=(
                        int(result["to"]["row"]),
                        int(result["to"]["col"]),
                    ),
                    movement_key=idempotency_key,
                    transaction=transaction,
                )
            session.flush()
            return {"action": serialize(action), "target": serialize(target), **result}

    def get_death_save(
        self,
        campaign_id: str,
        combat_id: str,
        combatant_id: str,
    ) -> dict[str, Any]:
        command = CombatActionCommand(
            action_type="heal",
            target_combatant_id=combatant_id,
            target_version=1,
            amount=0,
        )
        with Session(self.engine) as session:
            _, target, _ = self._scope(session, campaign_id, combat_id, command)
            death_save = session.scalar(
                select(DeathSave).where(DeathSave.combatant_id == target.id)
            )
            if death_save is None:
                if target.hp != 0:
                    raise ValueError("death saves are only available at 0 HP")
                return {
                    "combatant_id": target.id,
                    "successes": 0,
                    "failures": 0,
                    "stable": False,
                    "dead": False,
                    "pending_death_confirmation": False,
                    "last_roll": None,
                    "version": 1,
                }
            return serialize(death_save)

    def confirm_death_save(
        self,
        campaign_id: str,
        combat_id: str,
        combatant_id: str,
        command: DeathSaveCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope_command = CombatActionCommand(
            action_type="heal",
            target_combatant_id=combatant_id,
            target_version=command.target_version,
            amount=0,
        )
        with Session(self.engine) as session, session.begin():
            combat, target, _ = self._scope(
                session,
                campaign_id,
                combat_id,
                scope_command,
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                death_save = self._death_save(session, target)
                return {
                    "action": serialize(existing),
                    "target": serialize(target),
                    "death_save": serialize(death_save),
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if target.hp != 0:
                raise ValueError("death saves are only available at 0 HP")
            death_save = self._death_save(session, target)
            if (
                death_save.dead
                or death_save.stable
                or death_save.pending_death_confirmation
            ):
                raise ValueError("death save track cannot advance in its current state")
            resolution = resolve_death_save(
                roll=command.roll,
                successes=death_save.successes,
                failures=death_save.failures,
            )
            before_target = serialize(target)
            before_death_save = serialize(death_save)
            death_save.successes = resolution.successes
            death_save.failures = resolution.failures
            death_save.stable = resolution.stable
            death_save.dead = resolution.dead
            death_save.pending_death_confirmation = (
                resolution.pending_death_confirmation
            )
            death_save.last_roll = command.roll
            death_save.version += 1
            if resolution.hp_restored:
                target.hp = resolution.hp_restored
            condition_changes = self._sync_zero_hp_lifecycle(
                target,
                before_hp=int(before_target["hp"]),
            )
            target.version += 1
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_death_save",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={
                    "combatant": before_target,
                    "death_save": before_death_save,
                },
                after_snapshot={
                    "combatant_id": target.id,
                    "hp": target.hp,
                    "successes": death_save.successes,
                    "failures": death_save.failures,
                    "stable": death_save.stable,
                    "pending_death_confirmation": (
                        death_save.pending_death_confirmation
                    ),
                },
                reason="DM confirmed death save roll",
                source="combat",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            result = asdict(resolution)
            if condition_changes:
                result["condition_changes"] = condition_changes
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                transaction_id=transaction.id,
                action_type="death_save",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=resolution.explanation,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{target.display_name}：{resolution.explanation}",
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "target": serialize(target),
                "death_save": serialize(death_save),
            }

    def confirm_death(
        self,
        campaign_id: str,
        combat_id: str,
        combatant_id: str,
        command: DeathConfirmationCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope_command = CombatActionCommand(
            action_type="heal",
            target_combatant_id=combatant_id,
            target_version=command.target_version,
            amount=0,
        )
        with Session(self.engine) as session, session.begin():
            combat, target, _ = self._scope(
                session,
                campaign_id,
                combat_id,
                scope_command,
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            death_save = self._death_save(session, target)
            if existing is not None:
                return {
                    "action": serialize(existing),
                    "target": serialize(target),
                    "death_save": serialize(death_save),
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if not death_save.pending_death_confirmation:
                raise ValueError("death is not awaiting confirmation")
            before = serialize(death_save)
            death_save.dead = True
            death_save.pending_death_confirmation = False
            death_save.version += 1
            target.version += 1
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_confirm_death",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"death_save": before},
                after_snapshot={
                    "combatant_id": target.id,
                    "dead": True,
                },
                reason=command.reason,
                source="combat",
                confirmed_at=datetime.now(UTC),
            )
            session.add(transaction)
            session.flush()
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                transaction_id=transaction.id,
                action_type="confirm_death",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json={"dead": True, "reason": command.reason},
                explanation=command.reason,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{target.display_name} 已由 DM 确认死亡",
                idempotency_key=idempotency_key,
                dm_override=True,
                override_reason=command.reason,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "target": serialize(target),
                "death_save": serialize(death_save),
            }

    def advance_turn(
        self,
        campaign_id: str,
        combat_id: str,
        command: TurnAdvanceCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                active_id = existing.result_json.get("active_combatant_id")
                active = (
                    session.get(Combatant, active_id)
                    if isinstance(active_id, str)
                    else None
                )
                return {
                    "action": serialize(existing),
                    "combat": serialize(combat),
                    "active_combatant": (
                        serialize(active) if active is not None else None
                    ),
                    "expiration_prompts": existing.result_json.get(
                        "expiration_prompts",
                        [],
                    ),
                    "effect_ticks": existing.result_json.get("effect_ticks", []),
                    "effect_prompts": existing.result_json.get("effect_prompts", []),
                    "status_prompts": existing.result_json.get("status_prompts", []),
                    "ended_runtime_effects": existing.result_json.get(
                        "ended_runtime_effects", []
                    ),
                    "predicated_effects": existing.result_json.get(
                        "predicated_effects", []
                    ),
                    "predicated_summons": existing.result_json.get(
                        "predicated_summons", []
                    ),
                    "expired_rule_effects": existing.result_json.get(
                        "expired_rule_effects", []
                    ),
                    "recharge_rolls": existing.result_json.get("recharge_rolls", []),
                    "trait_results": existing.result_json.get("trait_results", []),
                }
            if combat.version != command.combat_version:
                raise VersionConflict(
                    "combat",
                    combat.id,
                    command.combat_version,
                    combat.version,
                )
            if combat.status in {"completed", "cancelled"}:
                raise ValueError("completed combat cannot advance turns")
            unresolved_player_roll = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.action_type == "player_roll_prompt",
                    CombatAction.status == "previewed",
                )
            )
            if unresolved_player_roll is not None:
                raise ValueError(
                    "当前仍有玩家掷骰请求未结算，不能结束怪物回合"
                )
            unresolved_effect_save = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.action_type == "effect_save_prompt",
                    CombatAction.status == "previewed",
                )
            )
            if unresolved_effect_save is not None:
                request = dict(unresolved_effect_save.request_json or {})
                raise ValueError(
                    "当前仍有回合末重复豁免请求未结算，不能继续推进战斗："
                    f"{request.get('summary') or unresolved_effect_save.summary}"
                )
            unresolved_concentration = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.action_type == "concentration_check_prompt",
                    CombatAction.status == "previewed",
                )
            )
            if unresolved_concentration is not None:
                request = dict(unresolved_concentration.request_json or {})
                raise ValueError(
                    "当前仍有专注豁免请求未结算，不能继续推进战斗："
                    f"{request.get('summary') or unresolved_concentration.summary}"
                )
            raw_ordered = session.scalars(
                select(Combatant)
                .where(
                    Combatant.combat_id == combat_id,
                    Combatant.is_active.is_(True),
                )
                .order_by(
                    Combatant.initiative.desc(),
                    Combatant.created_at,
                    Combatant.id,
                )
            ).all()
            if not raw_ordered:
                raise ValueError("combat has no active combatants")
            before = serialize(combat)
            previous_round = combat.round_number
            previous_raw_index = (
                combat.current_turn_index
                if 0 <= combat.current_turn_index < len(raw_ordered)
                else 0
            )
            previous_active = raw_ordered[previous_raw_index]
            now = datetime.now(UTC)
            for row in raw_ordered:
                if row.hp <= 0 and row.entity_type != "character":
                    if row.is_active:
                        row.is_active = False
                        row.version += 1
                        row.updated_at = now
            ordered = [row for row in raw_ordered if row.is_active]
            if not ordered:
                raise ValueError("combat has no active combatants")
            next_round = combat.round_number
            active: Combatant | None = None
            wrapped = False
            for offset in range(1, len(raw_ordered) + 1):
                candidate = raw_ordered[(previous_raw_index + offset) % len(raw_ordered)]
                if not candidate.is_active:
                    continue
                active = candidate
                wrapped = previous_raw_index + offset >= len(raw_ordered)
                break
            if active is None:
                raise ValueError("combat has no next active combatant")
            next_index = ordered.index(active)
            if wrapped:
                next_round += 1
            combat.current_turn_index = next_index
            combat.round_number = next_round
            combat.version += 1
            self._refresh_new_turn_resources(active)
            active_snapshot = dict(active.snapshot_json or {})
            # Action Surge grants a budget for this turn only.  The budget is
            # consumed by the normal action-economy gate and must never leak
            # into the next initiative turn.
            active_snapshot.pop("extra_action_budget", None)
            active_snapshot.pop("attack_roll_budget", None)
            active.snapshot_json = active_snapshot
            recharge_rolls: list[dict[str, object]] = []
            trait_results: list[dict[str, object]] = []
            if active.entity_type == "monster":
                snapshot = dict(active.snapshot_json or {})
                actions = snapshot.get("actions")
                legendary_pools = {
                    int(item["legendary_pool_max"])
                    for item in actions
                    if isinstance(actions, list)
                    and isinstance(item, dict)
                    and isinstance(item.get("legendary_pool_max"), int)
                    and int(item["legendary_pool_max"]) > 0
                } if isinstance(actions, list) else set()
                if len(legendary_pools) == 1:
                    pool_max = legendary_pools.pop()
                    snapshot["legendary_actions_max"] = pool_max
                    snapshot["legendary_actions_remaining"] = pool_max
                    snapshot.pop("legendary_action_window_used", None)
                    active.snapshot_json = snapshot
                recharge_rolls, trait_results = self._process_monster_turn_start(active)
            active.version += 1
            active.updated_at = now
            combat.updated_at = now
            effect_ticks: list[dict[str, object]] = []
            effect_prompts: list[dict[str, object]] = []
            status_prompts: list[dict[str, object]] = []
            ended_runtime_effects: list[CombatEffect] = []
            changed_runtime_targets: dict[str, Combatant] = {}
            for effect in self._active_runtime_effects(session, combat.id):
                state = self._runtime_state(effect)
                if state is None:
                    continue
                expires = state.get("expires")
                expires_combatant_id = state.get("expires_combatant_id")
                due = (
                    expires == "turn_end"
                    and previous_active is not None
                    and expires_combatant_id == previous_active.id
                ) or (
                    expires == "turn_start"
                    and expires_combatant_id == active.id
                )
                if not due:
                    continue
                changed = self._end_runtime_effect(
                    session,
                    effect,
                    reason=f"runtime state ended at {str(expires).replace('_', ' ')}",
                    now=now,
                )
                if changed is not None:
                    changed_runtime_targets[changed.id] = changed
                    ended_runtime_effects.append(effect)
            for changed in changed_runtime_targets.values():
                if changed.id != active.id:
                    changed.version += 1
                    changed.updated_at = now
            predicated_effects, predicated_summons = self._end_predicated_effects(
                session,
                combat,
                now=now,
            )
            due_effects = session.scalars(
                select(CombatEffect).where(
                    CombatEffect.combat_id == combat_id,
                    CombatEffect.status == "active",
                    CombatEffect.trigger_timing.is_not(None),
                )
            ).all()
            for effect in due_effects:
                timing = effect.trigger_timing
                due = (
                    timing == "turn_end"
                    and previous_active is not None
                    and effect.target_combatant_id == previous_active.id
                ) or (
                    timing == "turn_start"
                    and effect.target_combatant_id == active.id
                ) or (
                    timing == "round_end"
                    and next_round > previous_round
                ) or (
                    timing == "round_start"
                    and next_round > previous_round
                )
                if not due:
                    continue
                tick = self._tick_rule_effect(session, combat, effect, now=now)
                if tick is None:
                    continue
                if tick.get("requires_save") or tick.get("requires_dm_review"):
                    effect_prompts.append(tick)
                else:
                    effect_ticks.append(tick)
            existing_prompt_ids = {
                str(prompt.get("effect_id"))
                for prompt in effect_prompts
                if prompt.get("effect_id") is not None
            }
            if previous_active is not None:
                save_effects = session.scalars(
                    select(CombatEffect).where(
                        CombatEffect.combat_id == combat.id,
                        CombatEffect.target_combatant_id == previous_active.id,
                        CombatEffect.status == "active",
                        CombatEffect.duration_unit == "until_save",
                        CombatEffect.save_dc.is_not(None),
                        CombatEffect.save_ability.is_not(None),
                    )
                ).all()
                for effect in save_effects:
                    if effect.id in existing_prompt_ids:
                        continue
                    effect_prompts.append(
                        {
                            "effect_id": effect.id,
                            "target_combatant_id": previous_active.id,
                            "requires_save": True,
                            "save_dc": effect.save_dc,
                            "save_ability": effect.save_ability,
                            "timing": "turn_end",
                            "summary": (
                                f"{previous_active.display_name} 回合结束时需要进行 "
                                f"{effect.save_ability} 豁免（DC {effect.save_dc}）；"
                                "等待 DM/玩家提交结果"
                            ),
                        }
                    )
            if active.hp == 0 and not self._is_summon(active):
                death_save = session.scalar(
                    select(DeathSave).where(DeathSave.combatant_id == active.id)
                )
                if death_save is None or (
                    not death_save.dead
                    and not death_save.stable
                    and not death_save.pending_death_confirmation
                ):
                    status_prompts.append(
                        {
                            "type": "death_save_required",
                            "combatant_id": active.id,
                            "summary": f"{active.display_name} 需要进行死亡豁免",
                        }
                    )
            expiring_effects = session.scalars(
                select(CombatEffect)
                .where(
                    CombatEffect.combat_id == combat_id,
                    CombatEffect.status == "active",
                    CombatEffect.ends_round.is_not(None),
                    CombatEffect.ends_round <= combat.round_number,
                )
                .order_by(CombatEffect.ends_round, CombatEffect.created_at, CombatEffect.id)
            ).all()
            summon_effects: list[CombatEffect] = []
            expired_rule_effects: list[CombatEffect] = []
            expired_targets: dict[str, Combatant] = {}
            for effect in expiring_effects:
                effect_target = session.get(Combatant, effect.target_combatant_id)
                details = dict(effect.details_json or {})
                is_summon_effect = self._effect_summon_id(effect) is not None
                has_compiled_rule = isinstance(details.get("rule_block"), dict)
                if is_summon_effect:
                    summon_effects.append(effect)
                # Compiler-produced effects are authoritative: their reverse
                # operation is safe to execute at expiry.  Free-form DM
                # effects still remain prompts because the engine cannot infer
                # what a prose-only effect changed.
                if has_compiled_rule and effect_target is not None:
                    self._reverse_compiled_effect(session, effect_target, effect)
                    expired_targets[effect_target.id] = effect_target
                    expired_rule_effects.append(effect)
                if is_summon_effect or has_compiled_rule:
                    effect.status = "ended"
                    effect.ended_at = now
                    effect.end_reason = (
                        "召唤持续时间结束" if is_summon_effect else "结构化效果持续时间结束"
                    )
                    effect.version += 1
                    source = (
                        session.get(Combatant, effect.source_combatant_id)
                        if effect.source_combatant_id else None
                    )
                    if source is not None and source.concentration.get("effect_id") == effect.id:
                        source.concentration = {}
                        source.version += 1
                        source.updated_at = now
            for effect_target in expired_targets.values():
                effect_target.version += 1
                effect_target.updated_at = now
            ended_summons = self._deactivate_summons_for_effects(
                session,
                combat,
                summon_effects,
                now=now,
            )
            # A turn-start effect may have removed a condition that blocked
            # the active unit. Recompute the fresh turn budget after every
            # lifecycle path (runtime, predicated, and round expiry).
            self._refresh_new_turn_resources(active)
            expiration_prompts = [
                serialize(effect)
                for effect in expiring_effects
                if effect.status == "active"
            ]
            active_order = self._ordered_combatants(session, combat_id)
            turn_active = (
                active_order[combat.current_turn_index]
                if active_order and combat.current_turn_index < len(active_order)
                else None
            )
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_advance_turn",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"combat": before},
                after_snapshot={
                    "combat_id": combat.id,
                    "round_number": combat.round_number,
                    "current_turn_index": combat.current_turn_index,
                    "active_combatant_id": turn_active.id if turn_active else None,
                    "ended_summon_ids": [summon.id for summon in ended_summons],
                    "expired_rule_effect_ids": [effect.id for effect in expired_rule_effects],
                    "effect_ticks": effect_ticks,
                    "effect_prompts": effect_prompts,
                    "status_prompts": status_prompts,
                    "ended_runtime_effect_ids": [
                        effect.id for effect in ended_runtime_effects
                    ],
                    "predicated_effect_ids": [effect.id for effect in predicated_effects],
                    "recharge_rolls": recharge_rolls,
                    "trait_results": trait_results,
                },
                reason="DM advanced combat turn",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            self._persist_eligible_advanced_action_windows(
                session,
                combat=combat,
                transaction=transaction,
                previous_active=previous_active,
                active=turn_active,
                ordered=active_order,
            )
            persisted_effect_prompts: list[dict[str, object]] = []
            for prompt in effect_prompts:
                if (
                    prompt.get("requires_save") is not True
                    or not isinstance(prompt.get("effect_id"), str)
                    or not isinstance(prompt.get("target_combatant_id"), str)
                ):
                    continue
                effect_id = str(prompt["effect_id"])
                target_id = str(prompt["target_combatant_id"])
                idempotency = (
                    f"effect-save-prompt:{effect_id}:{combat.round_number}:{target_id}"
                )
                pending = CombatAction(
                    campaign_id=campaign_id,
                    combat_id=combat_id,
                    actor_combatant_id=target_id,
                    transaction_id=transaction.id,
                    action_type="effect_save_prompt",
                    target_combatant_ids=[target_id],
                    request_json={
                        "effect_id": effect_id,
                        "target_combatant_id": target_id,
                        "save_dc": prompt.get("save_dc"),
                        "save_ability": prompt.get("save_ability"),
                        "timing": prompt.get("timing", "turn_end"),
                        "summary": prompt.get("summary"),
                    },
                    result_json={},
                    explanation="回合末重复豁免待 DM/玩家提交",
                    round_number=combat.round_number,
                    turn_index=combat.current_turn_index,
                    summary=str(prompt.get("summary") or "等待回合末重复豁免"),
                    idempotency_key=idempotency,
                    status="previewed",
                )
                session.add(pending)
                session.flush()
                prompt["pending_action_id"] = pending.id
                persisted_effect_prompts.append(dict(prompt))
            result: dict[str, Any] = {
                "active_combatant_id": turn_active.id if turn_active else None,
                "round_number": combat.round_number,
                "turn_index": combat.current_turn_index,
                "expiration_prompts": expiration_prompts,
                "effect_ticks": effect_ticks,
                "effect_prompts": persisted_effect_prompts,
                "status_prompts": status_prompts,
                "ended_runtime_effects": [
                    serialize(effect) for effect in ended_runtime_effects
                ],
                "ended_summon_ids": [summon.id for summon in ended_summons],
                "expired_rule_effects": [serialize(effect) for effect in expired_rule_effects],
                "recharge_rolls": recharge_rolls,
                "trait_results": trait_results,
            }
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=turn_active.id if turn_active else None,
                transaction_id=transaction.id,
                action_type="advance_turn",
                target_combatant_ids=[turn_active.id] if turn_active else [],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation="恢复新回合角色的动作、附赠动作、反应与移动",
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"第 {combat.round_number} 轮：轮到 {turn_active.display_name}"
                    if turn_active is not None
                    else f"第 {combat.round_number} 轮：当前没有活动战斗单位"
                ),
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "combat": serialize(combat),
                "active_combatant": serialize(turn_active) if turn_active else None,
                "expiration_prompts": expiration_prompts,
                "effect_ticks": effect_ticks,
                "effect_prompts": effect_prompts,
                "status_prompts": status_prompts,
                "ended_runtime_effects": [
                    serialize(effect) for effect in ended_runtime_effects
                ],
                "predicated_effects": [serialize(effect) for effect in predicated_effects],
                "predicated_summons": [serialize(summon) for summon in predicated_summons],
                "ended_summons": [serialize(summon) for summon in ended_summons],
                "expired_rule_effects": [
                    serialize(effect) for effect in expired_rule_effects
                ],
                "recharge_rolls": recharge_rolls,
                "trait_results": trait_results,
            }

    def reset_combat(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatResetCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            if combat.version != command.combat_version:
                raise VersionConflict(
                    "combat",
                    combat.id,
                    command.combat_version,
                    combat.version,
                )
            if combat.status not in {"active", "ended"}:
                raise ValueError("only an active or ended combat can be reset")

            combatants = session.scalars(
                select(Combatant)
                .where(Combatant.combat_id == combat_id)
                .order_by(
                    Combatant.initiative.desc(),
                    Combatant.created_at,
                    Combatant.id,
                )
            ).all()
            if not combatants:
                raise ValueError("combat has no combatants")

            before = {
                "combat": serialize(combat),
                "combatants": [serialize(fighter) for fighter in combatants],
            }
            # A reset returns the initiative track to its starting fixture.
            # Summoned units are created during the combat and therefore must
            # not survive the reset as inactive/position-less stale targets.
            # Keeping them in the track is especially dangerous for AI area
            # actions: target selection can choose the stale unit, while the
            # authoritative map has no position with which to resolve it.
            summon_ids = [
                fighter.id
                for fighter in combatants
                if fighter.entity_type == "companion"
                or self._is_summon(fighter)
                or (
                    isinstance(fighter.snapshot_json, dict)
                    and bool(fighter.snapshot_json.get("summon_source_combatant_id"))
                )
            ]
            if summon_ids:
                session.execute(delete(SceneToken).where(SceneToken.entity_id.in_(summon_ids)))
                session.execute(delete(Combatant).where(Combatant.id.in_(summon_ids)))
                combatants = [fighter for fighter in combatants if fighter.id not in summon_ids]
            combatant_ids = [fighter.id for fighter in combatants]
            session.execute(
                delete(DeathSave).where(DeathSave.combatant_id.in_(combatant_ids))
            )
            session.execute(
                delete(CombatEffect).where(CombatEffect.combat_id == combat_id)
            )
            session.execute(
                delete(CombatAction).where(CombatAction.combat_id == combat_id)
            )

            now = datetime.now(UTC)
            for fighter in combatants:
                snapshot = dict(fighter.snapshot_json or {})
                baseline_raw = snapshot.get("combat_start_state")
                baseline = (
                    baseline_raw
                    if isinstance(baseline_raw, dict)
                    else {}
                )
                fighter.hp = max(
                    0,
                    min(
                        fighter.max_hp,
                        int(baseline.get("hp", fighter.max_hp)),
                    ),
                )
                fighter.temporary_hp = max(
                    0,
                    int(baseline.get("temporary_hp", 0)),
                )
                fighter.max_hp_reduction = max(
                    0,
                    min(
                        fighter.max_hp,
                        int(baseline.get("max_hp_reduction", 0)),
                    ),
                )
                if fighter.hp + fighter.max_hp_reduction > fighter.max_hp:
                    fighter.hp = fighter.max_hp - fighter.max_hp_reduction
                conditions = baseline.get("conditions", [])
                concentration = baseline.get("concentration", {})
                fighter.conditions = list(conditions) if isinstance(conditions, list) else []
                fighter.concentration = (
                    dict(concentration)
                    if isinstance(concentration, dict)
                    else {}
                )
                fighter.movement_remaining_ft = fighter.speed_ft
                fighter.action_available = True
                fighter.bonus_action_available = True
                fighter.reaction_available = True
                snapshot.pop("extra_action_budget", None)
                snapshot.pop("attack_roll_budget", None)
                fighter.is_active = bool(baseline.get("is_active", True))
                starting_snapshot = baseline.get("snapshot_json")
                starting_position = (
                    starting_snapshot.get("grid_position")
                    if isinstance(starting_snapshot, dict)
                    else None
                )
                if (
                    isinstance(starting_position, dict)
                    and isinstance(starting_position.get("row"), int)
                    and isinstance(starting_position.get("col"), int)
                ):
                    snapshot["grid_position"] = {
                        key: value
                        for key, value in starting_position.items()
                        if key in {"row", "col", "elevation_ft", "height_ft", "z"}
                    }
                else:
                    snapshot.pop("grid_position", None)
                fighter.snapshot_json = snapshot
                fighter.version += 1
                fighter.updated_at = now

            combat.status = "active"
            combat.round_number = 1
            combat.current_turn_index = 0
            combat.ended_at = None
            combat.version += 1
            combat.updated_at = now
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_reset",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot=before,
                after_snapshot={
                    "combat_id": combat.id,
                    "round_number": 1,
                    "current_turn_index": 0,
                    "combatant_ids": combatant_ids,
                },
                reason="DM reset active combat to its starting state",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            return {
                "combat": serialize(combat),
                "combatants": [serialize(fighter) for fighter in combatants],
                "cleared_log": True,
            }

    @staticmethod
    def _effect_scope(
        session: Session,
        campaign_id: str,
        combat_id: str,
        command: CombatEffectCommand,
    ) -> tuple[Combat, Combatant, Combatant | None]:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        combat = session.get(Combat, combat_id)
        if combat is None or combat.campaign_id != campaign_id:
            raise StateNotFoundError("combat not found in campaign")
        target = session.get(Combatant, command.target_combatant_id)
        if target is None or target.combat_id != combat_id:
            raise StateNotFoundError("target combatant not found in combat")
        source = None
        if command.source_combatant_id is not None:
            source = session.get(Combatant, command.source_combatant_id)
            if source is None or source.combat_id != combat_id:
                raise StateNotFoundError("source combatant not found in combat")
        return combat, target, source

    @staticmethod
    def _active_concentration_effects(
        session: Session,
        combat_id: str,
        source_id: str | None,
    ) -> list[CombatEffect]:
        if source_id is None:
            return []
        return list(
            session.scalars(
                select(CombatEffect)
                .where(
                    CombatEffect.combat_id == combat_id,
                    CombatEffect.source_combatant_id == source_id,
                    CombatEffect.requires_concentration.is_(True),
                    CombatEffect.status == "active",
                )
                .order_by(CombatEffect.created_at, CombatEffect.id)
            ).all()
        )

    @staticmethod
    def _persist_concentration_prompts(
        session: Session,
        combat: Combat,
        damage_action: CombatAction,
        prompts: list[tuple[str, int]],
    ) -> list[dict[str, object]]:
        """Persist concentration checks created by one damage event.

        A damage action is committed before the DM/player can provide the
        Constitution save. Keeping the request as another ``CombatAction``
        makes it survive reloads and gives ``advance_turn`` one authoritative
        pause gate. Area damage may create one prompt per concentrating target,
        so this accepts a list rather than a single DC.
        """

        persisted: list[dict[str, object]] = []
        for target_id, dc in prompts:
            prompt_key = f"concentration-prompt:{damage_action.id}:{target_id}"
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat.id,
                    CombatAction.idempotency_key == prompt_key,
                )
            )
            if existing is not None:
                if existing.status == "previewed":
                    persisted.append(
                        {
                            "pending_action_id": existing.id,
                            "damage_action_id": damage_action.id,
                            "target_combatant_id": target_id,
                            "dc": dc,
                        }
                    )
                continue
            target = session.get(Combatant, target_id)
            if target is None:
                continue
            summary = (
                f"{target.display_name} 受到伤害后需要进行体质豁免"
                f"（DC {dc}）以维持专注"
            )
            prompt = CombatAction(
                campaign_id=combat.campaign_id,
                combat_id=combat.id,
                actor_combatant_id=target.id,
                transaction_id=damage_action.transaction_id,
                action_type="concentration_check_prompt",
                target_combatant_ids=[target.id],
                request_json={
                    "damage_action_id": damage_action.id,
                    "combatant_id": target.id,
                    "target_combatant_id": target.id,
                    "dc": dc,
                    "ability": "constitution",
                    "summary": summary,
                },
                result_json={},
                explanation="伤害已确认；等待 DM/玩家提交专注体质豁免",
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=summary,
                idempotency_key=prompt_key,
                status="previewed",
            )
            session.add(prompt)
            session.flush()
            persisted.append(
                {
                    "pending_action_id": prompt.id,
                    "damage_action_id": damage_action.id,
                    "target_combatant_id": target.id,
                    "dc": dc,
                    "summary": summary,
                }
            )
        if persisted:
            result_json = dict(damage_action.result_json or {})
            result_json["concentration_prompts"] = persisted
            if len(persisted) == 1:
                result_json["concentration_prompt"] = persisted[0]
            damage_action.result_json = result_json
            damage_action.version += 1
            damage_action.updated_at = datetime.now(UTC)
        return persisted

    @staticmethod
    def _apply_rule_block_effect(
        target: Combatant,
        details: dict[str, object],
        *,
        remove: bool = False,
        session: Session | None = None,
        effect: CombatEffect | None = None,
    ) -> dict[str, object]:
        """Apply or reverse a compiler-produced combat block.

        DM-created effects without ``rule_block`` remain untouched.  This keeps
        the existing free-form effect API compatible while making compiled
        spell effects authoritative once accepted.
        """

        raw_block = details.get("rule_block")
        block = raw_block if isinstance(raw_block, dict) else None
        if block is None:
            return {}
        applied = details.get("applied_state")
        if remove:
            kind = str(block.get("kind") or "")
            if kind == "modifier":
                stat = str(block.get("stat") or "")
                operation = str(block.get("operation") or "")
                if stat in {"armor_class", "speed_ft"} and operation in {"add", "set"}:
                    # Rebuild from the earliest captured baseline instead of
                    # restoring this effect's stale "before" value.  That
                    # keeps a second active buff/debuff in place.
                    if (
                        session is not None
                        and effect is not None
                        and CombatEngineService._rebuild_numeric_rule_field(
                            session,
                            target,
                            effect,
                            field=stat,
                        )
                    ):
                        return {}
                elif isinstance(applied, dict):
                    raw_key = applied.get("rule_modifier_key")
                    modifier_key = (
                        str(raw_key)
                        if isinstance(raw_key, str) and raw_key
                        else CombatEngineService._rule_modifier_key(block, details)
                    )
                    snapshot = dict(target.snapshot_json or {})
                    raw_modifiers = snapshot.get("rule_modifiers")
                    modifiers = (
                        dict(raw_modifiers) if isinstance(raw_modifiers, dict) else {}
                    )
                    if modifier_key in modifiers:
                        modifiers.pop(modifier_key, None)
                        if modifiers:
                            snapshot["rule_modifiers"] = modifiers
                        else:
                            snapshot.pop("rule_modifiers", None)
                        target.snapshot_json = snapshot
                        return {}
            elif kind == "defense":
                operation = str(block.get("operation") or "")
                field = {
                    "resistance": "damage_resistances",
                    "vulnerability": "damage_vulnerabilities",
                    "immunity": "damage_immunities",
                }.get(operation)
                if (
                    field
                    and session is not None
                    and effect is not None
                    and CombatEngineService._rebuild_defense_rule_field(
                        session,
                        target,
                        effect,
                        field=field,
                    )
                ):
                    return {}
            transformation_before = details.get("transformation_before")
            if isinstance(transformation_before, dict):
                for field in ("armor_class", "hp", "max_hp", "speed_ft"):
                    value = transformation_before.get(field)
                    if isinstance(value, int):
                        setattr(target, field, value)
                previous_snapshot = transformation_before.get("snapshot_json")
                if isinstance(previous_snapshot, dict):
                    target.snapshot_json = dict(previous_snapshot)
            if isinstance(applied, dict):
                for key, value in applied.items():
                    if key == "conditions" and isinstance(value, list):
                        target.conditions = list(value)
                    elif key == "damage_resistances" and isinstance(value, list):
                        target.damage_resistances = list(value)
                    elif key == "damage_vulnerabilities" and isinstance(value, list):
                        target.damage_vulnerabilities = list(value)
                    elif key == "damage_immunities" and isinstance(value, list):
                        target.damage_immunities = list(value)
                    elif key == "armor_class" and isinstance(value, int):
                        target.armor_class = value
                    elif key == "speed_ft" and isinstance(value, int):
                        target.speed_ft = value
                        target.movement_remaining_ft = min(
                            target.movement_remaining_ft,
                            target.speed_ft,
                        )
                    elif key in {
                        "action_available",
                        "bonus_action_available",
                        "reaction_available",
                    } and isinstance(value, bool):
                        setattr(target, key, value)
                    elif key == "rule_modifiers" and isinstance(value, dict):
                        snapshot = dict(target.snapshot_json or {})
                        if value:
                            snapshot["rule_modifiers"] = dict(value)
                        else:
                            snapshot.pop("rule_modifiers", None)
                        target.snapshot_json = snapshot
            return {}

        kind = str(block.get("kind") or "")
        before: dict[str, object] = {}
        if kind == "transformation":
            form = details.get("transformation_form")
            if not isinstance(form, dict):
                return {}
            before = {
                "armor_class": target.armor_class,
                "hp": target.hp,
                "max_hp": target.max_hp,
                "speed_ft": target.speed_ft,
                "snapshot_json": dict(target.snapshot_json),
            }
            armor_class = form.get("armor_class")
            max_hp = form.get("max_hp")
            hp = form.get("hp")
            speed_ft = form.get("speed_ft")
            if isinstance(armor_class, int) and 0 <= armor_class <= 99:
                target.armor_class = armor_class
            if isinstance(max_hp, int) and max_hp >= 0:
                target.max_hp = max_hp
            if isinstance(hp, int) and hp >= 0:
                target.hp = min(hp, target.max_hp)
            if isinstance(speed_ft, int) and speed_ft >= 0:
                target.speed_ft = speed_ft
                target.movement_remaining_ft = min(target.movement_remaining_ft, speed_ft)
            snapshot = dict(target.snapshot_json or {})
            for key in ("actions", "ability_scores", "size", "movement_modes"):
                value = form.get(key)
                if isinstance(value, (list, dict, str, int, float, bool)):
                    snapshot[key] = value
            snapshot["active_transformation"] = {
                "form_ref": form.get("form_ref") or block.get("form_ref"),
                "mode": block.get("mode"),
            }
            target.snapshot_json = snapshot
            details["transformation_before"] = before
        elif kind == "condition":
            condition = str(block.get("condition") or "").strip()
            if condition:
                before["conditions"] = list(target.conditions or [])
                if condition.startswith("移除："):
                    values = [
                        value.strip()
                        for value in condition.removeprefix("移除：").split("/")
                    ]
                    for value in values:
                        CombatEngineService._remove_condition(target, value)
                elif not CombatEngineService._has_condition(target, condition):
                    CombatEngineService._apply_condition_restrictions(target, condition, before)
                    CombatEngineService._add_condition(target, condition)
        elif kind == "modifier":
            stat = str(block.get("stat") or "")
            operation = str(block.get("operation") or "")
            value = block.get("value")
            if stat == "armor_class" and isinstance(value, int):
                before["armor_class"] = target.armor_class
                source = str(block.get("source") or "")
                target.armor_class = (
                    max(target.armor_class, value)
                    if operation == "set" and "低于" in source
                    else value
                    if operation == "set"
                    else target.armor_class + value
                )
            elif stat == "speed_ft" and isinstance(value, int):
                before["speed_ft"] = target.speed_ft
                before["movement_remaining_ft"] = target.movement_remaining_ft
                target.speed_ft = value if operation == "set" else max(0, target.speed_ft + value)
                target.movement_remaining_ft = min(target.movement_remaining_ft, target.speed_ft)
            elif stat in {"action", "bonus_action", "reaction"} and operation == "grant":
                field = f"{stat}_available"
                before[field] = bool(getattr(target, field))
                setattr(target, field, True)
            else:
                raw_modifiers = target.snapshot_json.get("rule_modifiers")
                modifiers = dict(raw_modifiers) if isinstance(raw_modifiers, dict) else {}
                key = CombatEngineService._rule_modifier_key(block, details)
                before["rule_modifiers"] = dict(modifiers)
                before["rule_modifier_key"] = key
                modifiers[key] = {
                    "operation": operation,
                    "value": value,
                    "expression": block.get("expression"),
                    "source": block.get("source"),
                }
                snapshot = dict(target.snapshot_json)
                snapshot["rule_modifiers"] = modifiers
                target.snapshot_json = snapshot
        elif kind == "defense":
            operation = str(block.get("operation") or "")
            types = [str(value) for value in block.get("damage_types", []) if str(value)]
            field_name = {
                "resistance": "damage_resistances",
                "vulnerability": "damage_vulnerabilities",
                "immunity": "damage_immunities",
            }.get(operation)
            if field_name and types:
                current = list(getattr(target, field_name) or [])
                before[field_name] = current
                setattr(target, field_name, sorted(set(current).union(types)))
        return before

    @staticmethod
    def _roll_rule_expression(expression: object) -> int | None:
        raw = str(expression or "").replace(" ", "")
        match = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", raw, re.IGNORECASE)
        if not match:
            if raw.isdigit():
                return int(raw)
            return None
        count = int(match.group(1) or "1")
        sides = int(match.group(2))
        modifier = int(match.group(3) or "0")
        return sum(secrets.randbelow(sides) + 1 for _ in range(count)) + modifier

    @classmethod
    def _reapply_rule_state_effect(
        cls,
        target: Combatant,
        details: dict[str, object],
    ) -> dict[str, object] | None:
        """Reconcile a repeating state without stacking it on every tick."""

        raw_block = details.get("rule_block")
        block = raw_block if isinstance(raw_block, dict) else None
        if block is None:
            return None
        kind = str(block.get("kind") or "")
        if kind not in {"condition", "modifier", "defense"}:
            return None

        changed = False
        result: dict[str, object] = {
            "rule_block_kind": kind,
            "reapplied": False,
            "status": "active",
        }
        if kind == "condition":
            condition = str(block.get("condition") or "").strip()
            if not condition:
                return {**result, "status": "invalid"}
            operation = str(block.get("operation") or "apply")
            if operation == "remove":
                changed = cls._remove_condition(target, condition)
                if changed:
                    cls._restore_condition_restrictions(target)
                result["status"] = "removed" if changed else "already_absent"
            elif cls._condition_is_immune(target, condition):
                # The initial effect path rejects immune conditions. Repeat
                # ticks must use the same gate; otherwise gaining immunity
                # between turns would be undone by the next reapplication.
                result["status"] = "immune"
            elif not cls._has_condition(target, condition):
                cls._apply_condition_restrictions(target, condition, {})
                changed = cls._add_condition(target, condition)
                result["reapplied"] = changed
            result["condition"] = condition
        elif kind == "defense":
            operation = str(block.get("operation") or "")
            field_name = {
                "resistance": "damage_resistances",
                "vulnerability": "damage_vulnerabilities",
                "immunity": "damage_immunities",
            }.get(operation)
            types = [str(value) for value in block.get("damage_types", []) if str(value)]
            if field_name is None or not types:
                return {**result, "status": "invalid"}
            current = {str(value) for value in getattr(target, field_name) or []}
            if any(value not in current for value in types):
                cls._apply_rule_block_effect(target, details)
                changed = True
                result["reapplied"] = True
            result["defense"] = operation
            result["damage_types"] = types
        else:
            stat = str(block.get("stat") or "")
            operation = str(block.get("operation") or "")
            value = block.get("value")
            applied = details.get("applied_state")
            baseline = applied if isinstance(applied, dict) else {}
            if stat in {"armor_class", "speed_ft"} and isinstance(value, int):
                field_name = "armor_class" if stat == "armor_class" else "speed_ft"
                current = int(getattr(target, field_name))
                before = baseline.get(field_name)
                source = str(block.get("source") or "")
                expected = (
                    max(int(before), value)
                    if operation == "set" and "低于" in source and isinstance(before, int)
                    else value
                    if operation == "set"
                    else int(before) + value
                    if operation == "add" and isinstance(before, int)
                    else None
                )
                if expected is None:
                    return {**result, "status": "requires_dm_review", "stat": stat}
                if current == expected:
                    pass
                elif isinstance(before, int) and current == before:
                    cls._apply_rule_block_effect(target, details)
                    changed = True
                    result["reapplied"] = True
                else:
                    result["status"] = "requires_dm_review"
                    result["current"] = current
                    result["expected"] = expected
                result["stat"] = stat
            elif stat in {"action", "bonus_action", "reaction"} and operation == "grant":
                field_name = f"{stat}_available"
                if not bool(getattr(target, field_name)):
                    cls._apply_rule_block_effect(target, details)
                    changed = True
                    result["reapplied"] = True
                result["stat"] = stat
            else:
                raw_modifiers = target.snapshot_json.get("rule_modifiers")
                modifiers = raw_modifiers if isinstance(raw_modifiers, dict) else {}
                modifier_key = cls._rule_modifier_key(block, details)
                if modifier_key not in modifiers:
                    cls._apply_rule_block_effect(target, details)
                    changed = True
                    result["reapplied"] = True
                result["stat"] = stat

        result["changed"] = changed
        return result

    def _tick_rule_effect(
        self,
        session: Session,
        combat: Combat,
        effect: CombatEffect,
        *,
        now: datetime,
    ) -> dict[str, object] | None:
        """Resolve one explicit recurring rule at a turn boundary."""

        target = session.get(Combatant, effect.target_combatant_id)
        if target is None or not target.is_active or target.hp <= 0:
            return None
        details = dict(effect.details_json or {})
        repeat = details.get("repeat")
        repeat_count = (
            repeat.get("count")
            if isinstance(repeat, dict)
            and isinstance(repeat.get("count"), int)
            and not isinstance(repeat.get("count"), bool)
            else None
        )
        if isinstance(repeat, dict) and repeat.get("count") is not None:
            if repeat_count is None or repeat_count < 1:
                return {
                    "effect_id": effect.id,
                    "target_combatant_id": target.id,
                    "requires_dm_review": True,
                    "summary": f"{effect.name} 的重复次数无效，本次未自动结算",
                }
            completed = details.get("_repeat_ticks_completed", 0)
            if not isinstance(completed, int) or isinstance(completed, bool):
                return {
                    "effect_id": effect.id,
                    "target_combatant_id": target.id,
                    "requires_dm_review": True,
                    "summary": f"{effect.name} 的重复次数记录无效，本次未自动结算",
                }
            if completed >= repeat_count:
                effect.status = "ended"
                effect.ended_at = now
                effect.end_reason = "重复次数已用尽"
                effect.version += 1
                return None
        before = serialize(target)
        state_result = self._reapply_rule_state_effect(target, details)
        if state_result is not None:
            changed = bool(state_result.pop("changed", False))
            state_result["expression"] = None
            if changed:
                target.version += 1
                target.updated_at = now
            transaction = OperationTransaction(
                campaign_id=combat.campaign_id,
                operation_type="combat_effect_tick",
                idempotency_key=f"effect-tick:{effect.id}:{combat.round_number}:{combat.current_turn_index}",
                status="applied",
                before_snapshot={"combatant": before, "effect_id": effect.id},
                after_snapshot={"combatant": serialize(target), "result": state_result},
                reason=f"{effect.name} 按回合维持状态",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            action = CombatAction(
                campaign_id=combat.campaign_id,
                combat_id=combat.id,
                actor_combatant_id=effect.source_combatant_id,
                transaction_id=transaction.id,
                action_type="effect_tick",
                target_combatant_ids=[target.id],
                request_json={"effect_id": effect.id, "trigger_timing": effect.trigger_timing},
                result_json=state_result,
                explanation=f"{effect.name} 自动维持状态",
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"{target.display_name} 重新获得 {state_result.get('condition')} 状态"
                    if state_result.get("reapplied") and state_result.get("condition")
                    else f"{target.display_name} 维持 {effect.name}"
                ),
                idempotency_key=f"effect-tick:{effect.id}:{combat.round_number}:{combat.current_turn_index}",
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "effect_id": effect.id,
                "target_combatant_id": target.id,
                "result": state_result,
            }
        raw_components = details.get("damage_components")
        damage_components = (
            [item for item in raw_components if isinstance(item, dict)]
            if isinstance(raw_components, list)
            else []
        )
        is_component_damage = bool(damage_components)
        expression = details.get("damage_expression") or details.get("healing_expression")
        amount = self._roll_rule_expression(expression)
        if is_component_damage and not all(
            self._roll_rule_expression(item.get("expression", item.get("amount"))) is not None
            and str(item.get("damage_type") or "").strip()
            for item in damage_components
        ):
            # A recurring mixed effect must describe every segment explicitly;
            # silently collapsing a missing segment into the legacy scalar
            # would change resistance/immunity semantics.  Surface the
            # malformed effect as a DM review prompt instead of dropping the
            # tick from the turn result.
            return {
                "effect_id": effect.id,
                "target_combatant_id": target.id,
                "requires_dm_review": True,
                "summary": (
                    f"{effect.name} 的持续复合伤害缺少明确表达式或伤害类型，"
                    "本次未自动结算"
                ),
            }
        if amount is None and not is_component_damage:
            if effect.save_dc is not None and effect.save_ability:
                return {
                    "effect_id": effect.id,
                    "target_combatant_id": target.id,
                    "requires_save": True,
                    "save_dc": effect.save_dc,
                    "save_ability": effect.save_ability,
                    "summary": (
                        f"{target.display_name} 需要进行 {effect.save_ability}"
                        f" 豁免（DC {effect.save_dc}）"
                    ),
                }
            return {
                "effect_id": effect.id,
                "target_combatant_id": target.id,
                "requires_dm_review": True,
                "summary": f"{effect.name} 缺少可解析的持续效果表达式，本次未自动结算",
            }

        result: dict[str, object]
        death_save: DeathSave | None = None
        if details.get("damage_expression") or is_component_damage:
            component_results: list[dict[str, object]] = []
            current_hp = target.hp
            current_temporary_hp = target.temporary_hp
            applied_conditional_defenses: list[str] = []
            unresolved_conditional_defenses: list[str] = []
            components = damage_components or [
                {
                    "expression": expression,
                    "damage_type": str(details.get("damage_type") or ""),
                }
            ]
            for component in components:
                component_expression = component.get("expression", component.get("amount"))
                component_amount = self._roll_rule_expression(component_expression)
                if component_amount is None:
                    return None
                component_type = str(component.get("damage_type") or "").strip()
                component_tags = [
                    str(tag).strip()
                    for tag in component.get("damage_tags", details.get("damage_tags", []))
                    if str(tag).strip()
                ] if isinstance(
                    component.get("damage_tags", details.get("damage_tags", [])), list
                ) else []
                (
                    resistances,
                    vulnerabilities,
                    immunities,
                    component_applied_defenses,
                    component_unresolved_defenses,
                ) = self._damage_defenses(
                    target,
                    details,
                    [component_type],
                    damage_tags=component_tags,
                    dm_override=bool(details.get("dm_override")),
                )
                resolution = resolve_damage(
                    amount=component_amount,
                    current_hp=current_hp,
                    temporary_hp=current_temporary_hp,
                    damage_type=component_type,
                    resistances=resistances,
                    vulnerabilities=vulnerabilities,
                    immunities=immunities,
                )
                current_hp = resolution.remaining_hp
                current_temporary_hp = resolution.remaining_temporary_hp
                component_results.append(
                    {
                        **asdict(resolution),
                        "expression": component_expression,
                        "damage_type": component_type,
                        "damage_tags": component_tags,
                        "conditional_defenses_applied": component_applied_defenses,
                        "conditional_defenses_unresolved": component_unresolved_defenses,
                    }
                )
                applied_conditional_defenses.extend(component_applied_defenses)
                unresolved_conditional_defenses.extend(component_unresolved_defenses)
            modifiers = {str(item["modifier"]) for item in component_results}
            result = {
                "original_damage": sum(int(item["original_damage"]) for item in component_results),
                "adjusted_damage": sum(int(item["adjusted_damage"]) for item in component_results),
                "damage_type": (
                    component_results[0]["damage_type"]
                    if len(component_results) == 1
                    else "mixed"
                ),
                "modifier": next(iter(modifiers)) if len(modifiers) == 1 else "mixed",
                "temporary_hp_lost": sum(
                    int(item["temporary_hp_lost"]) for item in component_results
                ),
                "hp_lost": sum(int(item["hp_lost"]) for item in component_results),
                "remaining_temporary_hp": current_temporary_hp,
                "remaining_hp": current_hp,
                "unapplied_damage": sum(
                    int(item["unapplied_damage"]) for item in component_results
                ),
                "explanation": "；".join(str(item["explanation"]) for item in component_results),
                "damage_components": component_results,
                "expression": expression if not is_component_damage else None,
            }
            if applied_conditional_defenses:
                result["conditional_defenses_applied"] = list(
                    dict.fromkeys(applied_conditional_defenses)
                )
            if unresolved_conditional_defenses:
                result["conditional_defenses_unresolved"] = list(
                    dict.fromkeys(unresolved_conditional_defenses)
                )
            if result["adjusted_damage"] > 0 and target.concentration:
                result["concentration_check_dc"] = max(
                    10,
                    int(result["adjusted_damage"]) // 2,
                )
            target.hp = current_hp
            target.temporary_hp = current_temporary_hp
        else:
            healing_resolution = resolve_healing(
                amount=amount,
                current_hp=target.hp,
                max_hp=target.max_hp,
                max_hp_reduction=target.max_hp_reduction,
            )
            target.hp = healing_resolution.remaining_hp
            result = {**asdict(healing_resolution), "expression": expression}
        if repeat_count is not None:
            completed = int(details.get("_repeat_ticks_completed", 0)) + 1
            details["_repeat_ticks_completed"] = completed
            effect.details_json = details
            result["repeat_count"] = repeat_count
            result["repeat_ticks_completed"] = completed
            if completed >= repeat_count:
                effect.status = "ended"
                effect.ended_at = now
                effect.end_reason = "重复次数已用尽"
                effect.version += 1
                result["repeat_completed"] = True
        condition_changes = self._sync_zero_hp_lifecycle(
            target,
            before_hp=int(before["hp"]),
        )
        target.version += 1
        target.updated_at = now
        if (details.get("damage_expression") or is_component_damage) and target.hp == 0:
            if self._is_summon(target):
                self._deactivate_summons(session, combat, [target.id], now=now)
            else:
                death_save = self._death_save(session, target)
        if condition_changes:
            result["condition_changes"] = condition_changes
        if death_save is not None:
            result["death_save"] = serialize(death_save)
        transaction = OperationTransaction(
            campaign_id=combat.campaign_id,
            operation_type="combat_effect_tick",
            idempotency_key=f"effect-tick:{effect.id}:{combat.round_number}:{combat.current_turn_index}",
            status="applied",
            before_snapshot={"combatant": before, "effect_id": effect.id},
            after_snapshot={"combatant": serialize(target), "result": result},
            reason=f"{effect.name} 按回合自动结算",
            source="combat",
            confirmed_at=now,
        )
        session.add(transaction)
        session.flush()
        action = CombatAction(
            campaign_id=combat.campaign_id,
            combat_id=combat.id,
            actor_combatant_id=effect.source_combatant_id,
            transaction_id=transaction.id,
            action_type="effect_tick",
            target_combatant_ids=[target.id],
            request_json={"effect_id": effect.id, "trigger_timing": effect.trigger_timing},
            result_json=result,
            explanation=f"{effect.name} 自动结算 {expression}",
            round_number=combat.round_number,
            turn_index=combat.current_turn_index,
            summary=(
                f"{target.display_name} 受到 {result.get('adjusted_damage', 0)} 点持续伤害"
                if details.get("damage_expression") or is_component_damage
                else f"{target.display_name} 恢复 {result.get('hp_gained', 0)} 点持续治疗"
            ),
            idempotency_key=f"effect-tick:{effect.id}:{combat.round_number}:{combat.current_turn_index}",
            status="confirmed",
        )
        session.add(action)
        session.flush()
        if (
            (details.get("damage_expression") or is_component_damage)
            and int(result.get("adjusted_damage", 0)) > 0
        ):
            self._persist_eligible_damage_reaction_windows(
                session,
                combat=combat,
                transaction=transaction,
                damage_action=action,
                damaged_targets=[
                    (target, int(result["adjusted_damage"]))
                ],
            )
        return {"effect_id": effect.id, "target_combatant_id": target.id, "result": result}

    def preview_effect(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatEffectCommand,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            combat, target, source = self._effect_scope(
                session,
                campaign_id,
                combat_id,
                command,
            )
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if (
                source is not None
                and source.id != target.id
                and source.version != command.source_version
            ):
                raise VersionConflict(
                    "combatant",
                    source.id,
                    command.source_version or 0,
                    source.version,
                )
            lifecycle_summon = self._effect_lifecycle_summon(
                session,
                combat_id,
                command,
            )
            old_effects = (
                self._active_concentration_effects(session, combat_id, source.id)
                if command.requires_concentration and source is not None
                else []
            )
            ends_round = self._effect_ends_round(
                combat.round_number,
                command.duration_unit,
                command.duration_value,
            )
            return {
                "effect": {
                    **command.model_dump(mode="json"),
                    "started_round": combat.round_number,
                    "ends_round": ends_round,
                    "status": "active",
                },
                "effects_to_end": [serialize(effect) for effect in old_effects],
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
                "lifecycle_summon": (
                    serialize(lifecycle_summon)
                    if lifecycle_summon is not None
                    else None
                ),
            }

    def confirm_effect(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatEffectCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            combat, target, source = self._effect_scope(
                session,
                campaign_id,
                combat_id,
                command,
            )
            existing_action = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing_action is not None:
                effect_id = existing_action.result_json.get("effect_id")
                effect = (
                    session.get(CombatEffect, effect_id)
                    if isinstance(effect_id, str)
                    else None
                )
                if effect is None:
                    raise ValueError("confirmed effect record is missing")
                ended_ids_raw = existing_action.result_json.get(
                    "ended_effect_ids",
                    [],
                )
                ended_ids = (
                    ended_ids_raw if isinstance(ended_ids_raw, list) else []
                )
                ended_effects = [
                    row
                    for effect_id_value in ended_ids
                    if isinstance(effect_id_value, str)
                    and (row := session.get(CombatEffect, effect_id_value)) is not None
                ]
                ended_summon_ids_raw = existing_action.result_json.get(
                    "ended_summon_ids",
                    [],
                )
                ended_summons = [
                    summon_row
                    for summon_id in (
                        ended_summon_ids_raw
                        if isinstance(ended_summon_ids_raw, list)
                        else []
                    )
                    if isinstance(summon_id, str)
                    and (summon_row := session.get(Combatant, summon_id)) is not None
                ]
                return {
                    "action": serialize(existing_action),
                    "effect": serialize(effect),
                    "ended_effects": [serialize(row) for row in ended_effects],
                    "ended_summons": [serialize(row) for row in ended_summons],
                    "target": serialize(target),
                    "source": serialize(source) if source is not None else None,
                }
            lifecycle_summon = self._effect_lifecycle_summon(
                session,
                combat_id,
                command,
            )
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if (
                source is not None
                and source.id != target.id
                and source.version != command.source_version
            ):
                raise VersionConflict(
                    "combatant",
                    source.id,
                    command.source_version or 0,
                    source.version,
                )
            details_json = dict(command.details_json)
            raw_rule_block = details_json.get("rule_block")
            if (
                isinstance(raw_rule_block, dict)
                and str(raw_rule_block.get("kind") or "") == "condition"
                and str(raw_rule_block.get("operation") or "apply") != "remove"
            ):
                condition = str(raw_rule_block.get("condition") or "").strip()
                if condition and self._condition_is_immune(target, condition):
                    raise ValueError(
                        f"目标免疫状态「{condition}」，结构化效果未写入"
                    )
            now = datetime.now(UTC)
            old_effects = (
                self._active_concentration_effects(session, combat_id, source.id)
                if command.requires_concentration and source is not None
                else []
            )
            before = {
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
                "effects_to_end": [serialize(row) for row in old_effects],
            }
            for old_effect in old_effects:
                old_target = session.get(Combatant, old_effect.target_combatant_id)
                if old_target is not None:
                    self._reverse_compiled_effect(session, old_target, old_effect)
                old_effect.status = "ended"
                old_effect.ended_at = now
                old_effect.end_reason = f"开始新专注：{command.name}"
                old_effect.version += 1
            ended_summons = self._deactivate_summons_for_effects(
                session,
                combat,
                old_effects,
                now=now,
            )
            if lifecycle_summon is not None and not lifecycle_summon.is_active:
                raise ValueError("summon lifecycle effect cannot replace its ended effect")
            ends_round = self._effect_ends_round(
                combat.round_number,
                command.duration_unit,
                command.duration_value,
            )
            if (
                isinstance(raw_rule_block, dict)
                and str(raw_rule_block.get("kind") or "") == "condition"
                and str(raw_rule_block.get("operation") or "apply") != "remove"
            ):
                condition = str(raw_rule_block.get("condition") or "").strip()
                details_json["condition_was_present"] = bool(
                    condition
                    and self._has_condition(target, condition)
                    and not self._condition_owned_by_other_effect(
                        session,
                        None,
                        target,
                        condition,
                    )
                )
            if lifecycle_summon is not None:
                details_json["ends_summon_combatant_id"] = lifecycle_summon.id
            # Keep simultaneous same-shaped rule modifiers source-specific.
            # This is internal metadata and does not change the public rule
            # block contract.
            details_json.setdefault("_effect_instance_key", idempotency_key)
            prior_effects = session.scalars(
                select(CombatEffect).where(
                    CombatEffect.combat_id == combat_id,
                    CombatEffect.target_combatant_id == target.id,
                )
            ).all()
            prior_orders = [
                int(order)
                for prior_effect in prior_effects
                for order in [
                    dict(prior_effect.details_json or {}).get(
                        "_effect_instance_order"
                    )
                ]
                if isinstance(order, int) and not isinstance(order, bool)
            ]
            details_json["_effect_instance_order"] = (
                max(prior_orders, default=0) + 1
            )
            condition_added = False
            if (
                isinstance(raw_rule_block, dict)
                and str(raw_rule_block.get("kind") or "") == "condition"
                and str(raw_rule_block.get("operation") or "apply") != "remove"
            ):
                condition = str(raw_rule_block.get("condition") or "").strip()
                condition_added = bool(condition) and not self._has_condition(
                    target,
                    condition,
                )
            applied_state = self._apply_rule_block_effect(target, details_json)
            if applied_state:
                details_json["applied_state"] = applied_state
            condition_ended_effects: list[CombatEffect] = []
            condition_ended_summons: list[Combatant] = []
            if condition_added:
                (
                    condition_ended_effects,
                    condition_ended_summons,
                ) = self._end_lifecycles_after_condition_change(
                    session,
                    combat,
                    target=target,
                    now=now,
                )
            lifecycle_ended_effects = list(
                dict.fromkeys([*old_effects, *condition_ended_effects])
            )
            lifecycle_ended_summons = list(
                dict.fromkeys([*ended_summons, *condition_ended_summons])
            )
            effect = CombatEffect(
                campaign_id=campaign_id,
                combat_id=combat_id,
                target_combatant_id=target.id,
                source_combatant_id=source.id if source is not None else None,
                name=command.name,
                effect_type=command.effect_type,
                details_json=details_json,
                started_round=combat.round_number,
                duration_unit=command.duration_unit,
                duration_value=command.duration_value,
                ends_round=ends_round,
                requires_concentration=command.requires_concentration,
                save_dc=command.save_dc,
                save_ability=command.save_ability,
                trigger_timing=command.trigger_timing,
                status="active",
            )
            session.add(effect)
            session.flush()
            if command.requires_concentration and source is not None:
                source.concentration = {
                    "effect_id": effect.id,
                    "name": effect.name,
                    "started_round": combat.round_number,
                }
                if source.id != target.id:
                    source.version += 1
                    source.updated_at = now
            target.version += 1
            target.updated_at = now
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_add_effect",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot=before,
                after_snapshot={
                    "effect": serialize(effect),
                    "ended_effect_ids": [row.id for row in lifecycle_ended_effects],
                    "ended_summon_ids": [row.id for row in lifecycle_ended_summons],
                },
                reason=f"DM confirmed effect: {command.name}",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            result = {
                "effect_id": effect.id,
                "ended_effect_ids": [row.id for row in lifecycle_ended_effects],
                "ended_summon_ids": [row.id for row in lifecycle_ended_summons],
                "requires_concentration": command.requires_concentration,
            }
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=source.id if source is not None else None,
                transaction_id=transaction.id,
                action_type="add_effect",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=(
                    f"结束 {len(lifecycle_ended_effects)} 个生命周期效果"
                    if lifecycle_ended_effects
                    else "建立结构化战斗效果"
                ),
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{target.display_name} 获得效果：{command.name}",
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "effect": serialize(effect),
                "ended_effects": [serialize(row) for row in lifecycle_ended_effects],
                "ended_summons": [serialize(row) for row in lifecycle_ended_summons],
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
            }

    def list_effects(
        self,
        campaign_id: str,
        combat_id: str,
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            rows = session.scalars(
                select(CombatEffect)
                .where(CombatEffect.combat_id == combat_id)
                .order_by(CombatEffect.created_at, CombatEffect.id)
            ).all()
            return tuple(serialize(row) for row in rows)

    def confirm_concentration_check(
        self,
        campaign_id: str,
        combat_id: str,
        command: ConcentrationCheckCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            target = session.get(Combatant, command.combatant_id)
            if target is None or target.combat_id != combat_id:
                raise StateNotFoundError("combatant not found in combat")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                ended_ids_raw = existing.result_json.get("ended_effect_ids", [])
                ended_ids = (
                    ended_ids_raw if isinstance(ended_ids_raw, list) else []
                )
                existing_ended = [
                    row
                    for effect_id in ended_ids
                    if isinstance(effect_id, str)
                    and (row := session.get(CombatEffect, effect_id)) is not None
                ]
                ended_summon_ids_raw = existing.result_json.get(
                    "ended_summon_ids",
                    [],
                )
                existing_ended_summons = [
                    summon_row
                    for summon_id in (
                        ended_summon_ids_raw
                        if isinstance(ended_summon_ids_raw, list)
                        else []
                    )
                    if isinstance(summon_id, str)
                    and (summon_row := session.get(Combatant, summon_id)) is not None
                ]
                return {
                    "action": serialize(existing),
                    "target": serialize(target),
                    "dc": existing.result_json.get("dc"),
                    "roll_total": existing.result_json.get("roll_total"),
                    "success": existing.result_json.get("success"),
                    "ended_effects": [serialize(row) for row in existing_ended],
                    "ended_summons": [
                        serialize(row) for row in existing_ended_summons
                    ],
                }
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            damage_action = session.get(CombatAction, command.damage_action_id)
            if damage_action is None or damage_action.combat_id != combat_id:
                raise StateNotFoundError("damage action not found in combat")
            if (
                damage_action.action_type not in {"damage", "monster_area_action", "effect_tick"}
                or target.id not in damage_action.target_combatant_ids
            ):
                raise ValueError("action does not require this target's concentration check")
            pending_prompt = next(
                (
                    row
                    for row in session.scalars(
                        select(CombatAction).where(
                            CombatAction.combat_id == combat_id,
                            CombatAction.action_type == "concentration_check_prompt",
                            CombatAction.status == "previewed",
                        )
                    ).all()
                    if row.request_json.get("damage_action_id") == damage_action.id
                    and row.request_json.get("target_combatant_id") == target.id
                ),
                None,
            )
            if pending_prompt is None:
                raise ValueError("该伤害事件没有待处理的专注豁免请求")
            raw_dc = damage_action.result_json.get("concentration_check_dc")
            if raw_dc is None and damage_action.action_type == "monster_area_action":
                raw_target_results = damage_action.result_json.get("target_results")
                if isinstance(raw_target_results, list):
                    matching_result = next(
                        (
                            item
                            for item in raw_target_results
                            if isinstance(item, dict)
                            and item.get("target_combatant_id") == target.id
                        ),
                        None,
                    )
                    matching_damage = (
                        matching_result.get("damage")
                        if isinstance(matching_result, dict)
                        else None
                    )
                    if isinstance(matching_damage, dict):
                        raw_dc = matching_damage.get("concentration_check_dc")
            if not isinstance(raw_dc, int) or raw_dc <= 0:
                raise ValueError("damage action has no concentration check")
            success = command.roll_total >= raw_dc
            active_effects = self._active_concentration_effects(
                session,
                combat_id,
                target.id,
            )
            before = {
                "target": serialize(target),
                "effects": [serialize(row) for row in active_effects],
            }
            ended: list[CombatEffect] = []
            now = datetime.now(UTC)
            if not success:
                for effect in active_effects:
                    self._reverse_compiled_effect(session, target, effect)
                    effect.status = "ended"
                    effect.ended_at = now
                    effect.end_reason = (
                        f"专注检定失败：{command.roll_total} < DC {raw_dc}"
                    )
                    effect.version += 1
                    ended.append(effect)
                target.concentration = {}
                target.version += 1
                target.updated_at = now
            ended_summons = self._deactivate_summons_for_effects(
                session,
                combat,
                ended,
                now=now,
            )
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_concentration_check",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot=before,
                after_snapshot={
                    "combatant_id": target.id,
                    "dc": raw_dc,
                    "roll_total": command.roll_total,
                    "success": success,
                    "ended_effect_ids": [row.id for row in ended],
                    "ended_summon_ids": [row.id for row in ended_summons],
                },
                reason="DM confirmed concentration check",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            result = {
                "dc": raw_dc,
                "roll_total": command.roll_total,
                "success": success,
                "ended_effect_ids": [row.id for row in ended],
                "ended_summon_ids": [row.id for row in ended_summons],
                "damage_action_id": damage_action.id,
            }
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=target.id,
                transaction_id=transaction.id,
                action_type="concentration_check",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json=result,
                explanation=(
                    f"{command.roll_total} 对抗 DC {raw_dc}："
                    f"{'成功，维持专注' if success else '失败，结束专注'}"
                ),
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"{target.display_name} 专注检定"
                    f"{'成功' if success else '失败'}"
                ),
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            pending_prompt.status = "confirmed"
            pending_prompt.result_json = {
                "resolution_action_id": action.id,
                "roll_total": command.roll_total,
                "dc": raw_dc,
                "success": success,
            }
            pending_prompt.version += 1
            pending_prompt.updated_at = now
            return {
                "action": serialize(action),
                "target": serialize(target),
                "dc": raw_dc,
                "roll_total": command.roll_total,
                "success": success,
                "ended_effects": [serialize(row) for row in ended],
                "ended_summons": [serialize(row) for row in ended_summons],
            }

    def end_effect(
        self,
        campaign_id: str,
        combat_id: str,
        effect_id: str,
        command: CombatEffectEndCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            effect = session.get(CombatEffect, effect_id)
            if effect is None or effect.combat_id != combat_id:
                raise StateNotFoundError("effect not found in combat")
            target = session.get(Combatant, effect.target_combatant_id)
            if target is None:
                raise StateNotFoundError("effect target is missing")
            source = (
                session.get(Combatant, effect.source_combatant_id)
                if effect.source_combatant_id is not None
                else None
            )
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                ended_summon_ids_raw = existing.result_json.get(
                    "ended_summon_ids",
                    [],
                )
                ended_summons = [
                    row
                    for summon_id in (
                        ended_summon_ids_raw
                        if isinstance(ended_summon_ids_raw, list)
                        else []
                    )
                    if isinstance(summon_id, str)
                    and (row := session.get(Combatant, summon_id)) is not None
                ]
                return {
                    "action": serialize(existing),
                    "effect": serialize(effect),
                    "target": serialize(target),
                    "source": serialize(source) if source is not None else None,
                    "ended_summons": [serialize(row) for row in ended_summons],
                    "combat": serialize(combat),
                }
            if effect.status != "active":
                raise ValueError("effect is already ended")
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant",
                    target.id,
                    command.target_version,
                    target.version,
                )
            if (
                source is not None
                and source.id != target.id
                and source.version != command.source_version
            ):
                raise VersionConflict(
                    "combatant",
                    source.id,
                    command.source_version or 0,
                    source.version,
                )
            before = {
                "effect": serialize(effect),
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
            }
            now = datetime.now(UTC)
            if self._runtime_state(effect) is not None:
                self._end_runtime_effect(
                    session,
                    effect,
                    reason=command.reason,
                    now=now,
                )
            else:
                self._reverse_compiled_effect(session, target, effect)
                effect.status = "ended"
                effect.ended_at = now
                effect.end_reason = command.reason
                effect.version += 1
            target.version += 1
            target.updated_at = now
            if source is not None:
                concentration_id = source.concentration.get("effect_id")
                if concentration_id == effect.id:
                    source.concentration = {}
                if source.id != target.id:
                    source.version += 1
                    source.updated_at = now
            ended_summons = self._deactivate_summons_for_effects(
                session,
                combat,
                [effect],
                now=now,
            )
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_end_effect",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot=before,
                after_snapshot={
                    "effect_id": effect.id,
                    "status": effect.status,
                    "end_reason": effect.end_reason,
                    "ended_summon_ids": [row.id for row in ended_summons],
                },
                reason=command.reason,
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=source.id if source is not None else None,
                transaction_id=transaction.id,
                action_type="end_effect",
                target_combatant_ids=[target.id],
                request_json=command.model_dump(mode="json"),
                result_json={
                    "effect_id": effect.id,
                    "effect_name": effect.name,
                    "reason": command.reason,
                    "ended_summon_ids": [row.id for row in ended_summons],
                },
                explanation=command.reason,
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=f"{target.display_name} 的效果结束：{effect.name}",
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            return {
                "action": serialize(action),
                "effect": serialize(effect),
                "target": serialize(target),
                "source": serialize(source) if source is not None else None,
                "ended_summons": [serialize(row) for row in ended_summons],
                "combat": serialize(combat),
            }

    def confirm_effect_save(
        self,
        campaign_id: str,
        combat_id: str,
        effect_id: str,
        command: CombatEffectSaveCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Resolve a condition's explicit repeat-save lifecycle.

        ``until_save`` effects used to surface a prompt at the turn boundary
        but had no authoritative endpoint to consume it.  A successful save
        now reverses the compiled rule block and ends linked summon effects;
        a failed save records the result while leaving the effect active.
        """

        if not idempotency_key.strip():
            raise ValueError("idempotency key is required")
        with Session(self.engine) as session, session.begin():
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            effect = session.get(CombatEffect, effect_id)
            if effect is None or effect.combat_id != combat_id:
                raise StateNotFoundError("effect not found in combat")
            target = session.get(Combatant, command.target_combatant_id)
            if target is None or target.combat_id != combat_id:
                raise StateNotFoundError("effect target not found in combat")
            if effect.target_combatant_id != target.id:
                raise ValueError("effect save target does not match effect target")
            existing = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return {
                    "action": serialize(existing),
                    "effect": serialize(effect),
                    "target": serialize(target),
                    "success": bool(existing.result_json.get("success")),
                    "already_applied": True,
                }
            if effect.status != "active":
                raise ValueError("effect is already ended")
            if effect.duration_unit != "until_save":
                raise ValueError("only until_save effects accept a repeat save")
            if effect.save_dc is None or not effect.save_ability:
                raise ValueError("effect has no structured save DC and ability")
            if target.version != command.target_version:
                raise VersionConflict(
                    "combatant", target.id, command.target_version, target.version
                )
            pending_prompt = session.scalar(
                select(CombatAction).where(
                    CombatAction.combat_id == combat_id,
                    CombatAction.action_type == "effect_save_prompt",
                    CombatAction.status == "previewed",
                    CombatAction.request_json["effect_id"].as_string() == effect.id,
                )
            )
            success = command.roll_total >= effect.save_dc
            now = datetime.now(UTC)
            ended_summons: list[Combatant] = []
            if success:
                self._reverse_compiled_effect(session, target, effect)
                effect.status = "ended"
                effect.ended_at = now
                effect.end_reason = (
                    f"重复豁免成功：{command.roll_total} >= DC {effect.save_dc}"
                )
                effect.version += 1
                target.version += 1
                target.updated_at = now
                source = (
                    session.get(Combatant, effect.source_combatant_id)
                    if effect.source_combatant_id else None
                )
                if source is not None and source.concentration.get("effect_id") == effect.id:
                    source.concentration = {}
                    source.version += 1
                    source.updated_at = now
                ended_summons = self._deactivate_summons_for_effects(
                    session, combat, [effect], now=now
                )
            result = {
                "effect_id": effect.id,
                "target_combatant_id": target.id,
                "roll_total": command.roll_total,
                "save_dc": effect.save_dc,
                "save_ability": effect.save_ability,
                "success": success,
                "ended_summon_ids": [row.id for row in ended_summons],
                "dm_note": command.dm_note,
            }
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_effect_save",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={"effect_id": effect.id, "target": serialize(target)},
                after_snapshot={"result": result, "effect": serialize(effect)},
                reason="DM confirmed repeat save",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            action = CombatAction(
                campaign_id=campaign_id,
                combat_id=combat_id,
                actor_combatant_id=target.id,
                transaction_id=transaction.id,
                action_type="effect_save",
                target_combatant_ids=[target.id],
                request_json={**command.model_dump(mode="json"), "effect_id": effect.id},
                result_json=result,
                explanation=(
                    f"{target.display_name} 进行 {effect.save_ability} 豁免"
                    f" {command.roll_total} 对抗 DC {effect.save_dc}："
                    f"{'成功，效果结束' if success else '失败，效果继续'}"
                ),
                round_number=combat.round_number,
                turn_index=combat.current_turn_index,
                summary=(
                    f"{target.display_name} 的 {effect.name} 重复豁免"
                    f"{'成功' if success else '失败'}"
                ),
                idempotency_key=idempotency_key,
                status="confirmed",
            )
            session.add(action)
            session.flush()
            if pending_prompt is not None:
                pending_prompt.status = "confirmed"
                pending_prompt.result_json = {
                    "effect_id": effect.id,
                    "resolution_action_id": action.id,
                    "success": success,
                    "roll_total": command.roll_total,
                }
                pending_prompt.version += 1
                pending_prompt.updated_at = now
            return {
                "action": serialize(action),
                "effect": serialize(effect),
                "target": serialize(target),
                "success": success,
                "ended_summons": [serialize(row) for row in ended_summons],
                "already_applied": False,
            }

    @staticmethod
    def _condition_names(values: list[object]) -> list[str]:
        names: list[str] = []
        for value in values:
            if isinstance(value, str):
                name = value.strip()
            elif isinstance(value, dict):
                raw_name = value.get("name", value.get("condition_name"))
                name = raw_name.strip() if isinstance(raw_name, str) else ""
            else:
                name = ""
            if name and name not in names:
                names.append(name)
        return names

    @staticmethod
    def _settlement_plan(
        session: Session,
        campaign_id: str,
        combat_id: str,
        command: CombatSettlementCommand,
    ) -> tuple[
        Combat,
        dict[str, Character],
        list[dict[str, Any]],
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        combat = session.get(Combat, combat_id)
        if combat is None or combat.campaign_id != campaign_id:
            raise StateNotFoundError("combat not found in campaign")
        if combat.version != command.combat_version:
            raise VersionConflict(
                "combat",
                combat.id,
                command.combat_version,
                combat.version,
            )
        if combat.status != "ended":
            raise ValueError("combat must be ended before settlement")
        xp_by_character = {
            award.character_id: award.xp for award in command.xp_awards
        }
        writeback_by_character = {
            writeback.character_id: writeback for writeback in command.writebacks
        }
        currency_by_character = {
            award.character_id: award.copper
            for award in command.currency_awards
        }
        loot_by_character: dict[str, list[Any]] = {}
        for award in command.loot_awards:
            loot_by_character.setdefault(award.character_id, []).append(award)
        character_ids = (
            set(xp_by_character)
            | set(writeback_by_character)
            | set(currency_by_character)
            | set(loot_by_character)
        )
        characters: dict[str, Character] = {}
        changes: list[dict[str, Any]] = []
        currency_changes: list[dict[str, Any]] = []
        loot_changes: list[dict[str, Any]] = []
        for character_id in sorted(character_ids):
            character = session.get(Character, character_id)
            if character is None or character.campaign_id != campaign_id:
                raise StateNotFoundError("settlement character not found in campaign")
            characters[character_id] = character
            before = {
                "hp": character.hp,
                "experience": character.experience,
                "version": character.version,
            }
            after = dict(before)
            after["experience"] = character.experience + xp_by_character.get(
                character_id,
                0,
            )
            condition_names: list[str] = []
            writeback = writeback_by_character.get(character_id)
            if writeback is not None:
                combatant = session.get(Combatant, writeback.combatant_id)
                if (
                    combatant is None
                    or combatant.combat_id != combat_id
                    or combatant.entity_type != "character"
                    or combatant.entity_id != character_id
                ):
                    raise ValueError(
                        "writeback combatant must reference the selected character"
                    )
                if writeback.write_hp:
                    after["hp"] = min(character.max_hp, combatant.hp)
                if writeback.write_conditions:
                    condition_names = CombatEngineService._condition_names(
                        combatant.conditions
                    )
            after["version"] = character.version + 1
            changes.append(
                {
                    "character_id": character_id,
                    "name": character.name,
                    "before": before,
                    "after": after,
                    "conditions_to_add": condition_names,
                    "xp_award": xp_by_character.get(character_id, 0),
                }
            )
            copper = currency_by_character.get(character_id, 0)
            if copper:
                wallet = session.scalar(
                    select(Wallet).where(
                        Wallet.campaign_id == campaign_id,
                        Wallet.character_id == character_id,
                    )
                )
                currency_changes.append(
                    {
                        "character_id": character_id,
                        "name": character.name,
                        "wallet_id": wallet.id if wallet is not None else None,
                        "wallet_will_be_created": wallet is None,
                        "before_copper": wallet.copper if wallet is not None else 0,
                        "award_copper": copper,
                        "after_copper": (
                            wallet.copper if wallet is not None else 0
                        )
                        + copper,
                    }
                )
            for award in loot_by_character.get(character_id, []):
                loot_changes.append(
                    {
                        "character_id": character_id,
                        "character_name": character.name,
                        **award.model_dump(mode="json"),
                    }
                )
        return (
            combat,
            characters,
            changes,
            currency_changes,
            loot_changes,
        )

    def preview_settlement(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatSettlementCommand,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            existing = session.scalar(
                select(CombatSettlement).where(
                    CombatSettlement.combat_id == combat_id
                )
            )
            if existing is not None:
                raise ValueError("combat is already settled")
            (
                combat,
                _,
                changes,
                currency_changes,
                loot_changes,
            ) = self._settlement_plan(
                session,
                campaign_id,
                combat_id,
                command,
            )
            scene_changes = self._scene_entity_changes(session, combat, command)
            return {
                "combat": serialize(combat),
                "resolution_type": command.resolution_type,
                "character_changes": changes,
                "currency_changes": currency_changes,
                "loot_changes": loot_changes,
                "scene_entity_changes": scene_changes,
                "total_xp": sum(award.xp for award in command.xp_awards),
                "total_copper": sum(
                    award.copper for award in command.currency_awards
                ),
                "notes": command.notes,
            }

    @staticmethod
    def _scene_entity_changes(
        session: Session,
        combat: Combat,
        command: CombatSettlementCommand,
    ) -> list[dict[str, Any]]:
        if combat.scene_id is None:
            return []
        changes: list[dict[str, Any]] = []
        combatants = session.scalars(
            select(Combatant).where(
                Combatant.combat_id == combat.id,
                Combatant.entity_type.in_(("npc", "monster")),
                Combatant.entity_id.is_not(None),
            )
        ).all()
        for combatant in combatants:
            entity: NPC | MonsterInstance | None
            if combatant.entity_type == "npc":
                entity = session.get(NPC, combatant.entity_id)
            else:
                entity = session.get(MonsterInstance, combatant.entity_id)
            if entity is None or entity.campaign_id != combat.campaign_id:
                continue
            participant = session.scalar(
                select(SceneParticipant).where(
                    SceneParticipant.scene_id == combat.scene_id,
                    SceneParticipant.entity_type == combatant.entity_type,
                    SceneParticipant.entity_id == combatant.entity_id,
                )
            )
            after_role = (
                "defeated"
                if command.resolution_type == "victory"
                and combatant.entity_type == "monster"
                and combatant.hp <= 0
                else participant.role if participant is not None else None
            )
            if entity.hp == combatant.hp and (
                participant is None or participant.role == after_role
            ):
                continue
            changes.append(
                {
                    "entity_type": combatant.entity_type,
                    "entity_id": entity.id,
                    "name": entity.name,
                    "participant_id": participant.id if participant is not None else None,
                    "before": {
                        "hp": entity.hp,
                        "version": entity.version,
                        "role": participant.role if participant is not None else None,
                    },
                    "after": {
                        "hp": min(entity.max_hp, combatant.hp),
                        "version": entity.version + 1,
                        "role": after_role,
                    },
                }
            )
        return changes

    def confirm_settlement(
        self,
        campaign_id: str,
        combat_id: str,
        command: CombatSettlementCommand,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(CombatSettlement).where(
                    CombatSettlement.campaign_id == campaign_id,
                    CombatSettlement.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                character_ids_raw = existing.result_json.get("character_ids", [])
                character_ids = (
                    character_ids_raw
                    if isinstance(character_ids_raw, list)
                    else []
                )
                existing_characters: list[Character] = []
                for character_id in character_ids:
                    if isinstance(character_id, str):
                        character = session.get(Character, character_id)
                        if character is not None:
                            existing_characters.append(character)
                wallet_ids_raw = existing.result_json.get("wallet_ids", [])
                wallet_ids = (
                    wallet_ids_raw if isinstance(wallet_ids_raw, list) else []
                )
                existing_wallets: list[Wallet] = []
                for wallet_id in wallet_ids:
                    if isinstance(wallet_id, str):
                        wallet = session.get(Wallet, wallet_id)
                        if wallet is not None:
                            existing_wallets.append(wallet)
                item_ids_raw = existing.result_json.get("loot_item_ids", [])
                item_ids = item_ids_raw if isinstance(item_ids_raw, list) else []
                existing_items: list[WorldItem] = []
                for item_id in item_ids:
                    if isinstance(item_id, str):
                        item = session.get(WorldItem, item_id)
                        if item is not None:
                            existing_items.append(item)
                combat = session.get(Combat, combat_id)
                return {
                    "settlement": serialize(existing),
                    "combat": serialize(combat) if combat is not None else None,
                    "characters": [serialize(row) for row in existing_characters],
                    "conditions": [],
                    "wallets": [serialize(row) for row in existing_wallets],
                    "loot_items": [serialize(row) for row in existing_items],
                }
            other_settlement = session.scalar(
                select(CombatSettlement).where(
                    CombatSettlement.combat_id == combat_id
                )
            )
            if other_settlement is not None:
                raise ValueError("combat is already settled")
            (
                combat,
                characters,
                changes,
                currency_changes,
                loot_changes,
            ) = self._settlement_plan(
                session,
                campaign_id,
                combat_id,
                command,
            )
            combat_before = serialize(combat)
            scene_changes = self._scene_entity_changes(session, combat, command)
            now = datetime.now(UTC)
            created_conditions: list[CharacterCondition] = []
            updated_wallets: list[Wallet] = []
            created_items: list[WorldItem] = []
            for change in changes:
                character = characters[str(change["character_id"])]
                after = change["after"]
                character.hp = int(after["hp"])
                character.experience = int(after["experience"])
                character.version += 1
                character.updated_at = now
                for condition_name in change["conditions_to_add"]:
                    duplicate = session.scalar(
                        select(CharacterCondition).where(
                            CharacterCondition.character_id == character.id,
                            CharacterCondition.condition_name == condition_name,
                        )
                    )
                    if duplicate is None:
                        condition = CharacterCondition(
                            character_id=character.id,
                            condition_name=condition_name,
                            source=f"战斗结算：{combat.name}",
                            duration="持续，直至规则或DM移除",
                            notes=command.notes,
                            details={
                                "combat_id": combat.id,
                                "settlement_resolution": command.resolution_type,
                            },
                        )
                        session.add(condition)
                        created_conditions.append(condition)
            for currency_change in currency_changes:
                character_id = str(currency_change["character_id"])
                wallet = session.scalar(
                    select(Wallet).where(
                        Wallet.campaign_id == campaign_id,
                        Wallet.character_id == character_id,
                    )
                )
                if wallet is None:
                    wallet = Wallet(
                        campaign_id=campaign_id,
                        character_id=character_id,
                        name="角色钱包",
                        copper=0,
                    )
                    session.add(wallet)
                    session.flush()
                award_copper = int(currency_change["award_copper"])
                wallet.copper += award_copper
                wallet.version += 1
                wallet.updated_at = now
                updated_wallets.append(wallet)
                session.add(
                    CurrencyTransaction(
                        campaign_id=campaign_id,
                        wallet_id=wallet.id,
                        amount_copper=award_copper,
                        kind="adjustment",
                        idempotency_key=(
                            f"combat-settlement:{combat.id}:{character_id}"
                        ),
                        metadata_json={
                            "source": "combat_settlement",
                            "combat_id": combat.id,
                            "resolution_type": command.resolution_type,
                        },
                    )
                )
            for loot_change in loot_changes:
                item = WorldItem(
                    campaign_id=campaign_id,
                    owner_character_id=str(loot_change["character_id"]),
                    name=str(loot_change["name"]),
                    description=loot_change["description"],
                    category=str(loot_change["category"]),
                    quantity=int(loot_change["quantity"]),
                    unit_weight_lb=float(loot_change["unit_weight_lb"]),
                    price_cp=int(loot_change["price_cp"]),
                    source_record_id=loot_change["source_record_id"],
                    source_label=str(loot_change["source_label"]),
                    metadata_json={
                        **dict(loot_change["metadata_json"]),
                        "source": "combat_settlement",
                        "combat_id": combat.id,
                        "resolution_type": command.resolution_type,
                    },
                )
                session.add(item)
                created_items.append(item)
            session.flush()
            combat.xp_awarded = bool(command.xp_awards)
            combat.base_xp = sum(award.xp for award in command.xp_awards)
            combat.version += 1
            combat.updated_at = now
            for scene_change in scene_changes:
                if scene_change["entity_type"] == "npc":
                    scene_entity: NPC | MonsterInstance | None = session.get(
                        NPC, scene_change["entity_id"]
                    )
                else:
                    scene_entity = session.get(
                        MonsterInstance, scene_change["entity_id"]
                    )
                if scene_entity is None:
                    continue
                scene_entity.hp = int(scene_change["after"]["hp"])
                scene_entity.version += 1
                scene_entity.updated_at = now
                participant_id = scene_change["participant_id"]
                participant = (
                    session.get(SceneParticipant, participant_id)
                    if participant_id is not None
                    else None
                )
                after_role = scene_change["after"]["role"]
                if participant is not None and after_role != participant.role:
                    participant.role = str(after_role)
                    participant.version += 1
                    participant.updated_at = now
            transaction = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="combat_settlement",
                idempotency_key=idempotency_key,
                status="applied",
                before_snapshot={
                    "combat": combat_before,
                    "character_changes": changes,
                    "currency_changes": currency_changes,
                    "loot_changes": loot_changes,
                    "scene_entity_changes": scene_changes,
                },
                after_snapshot={
                    "combat_id": combat.id,
                    "resolution_type": command.resolution_type,
                    "character_ids": list(characters),
                    "wallet_ids": [wallet.id for wallet in updated_wallets],
                    "loot_item_ids": [item.id for item in created_items],
                    "scene_entity_changes": scene_changes,
                },
                reason=command.notes or f"combat settlement: {command.resolution_type}",
                source="combat",
                confirmed_at=now,
            )
            session.add(transaction)
            session.flush()
            settlement = CombatSettlement(
                campaign_id=campaign_id,
                combat_id=combat_id,
                transaction_id=transaction.id,
                status="confirmed",
                resolution_type=command.resolution_type,
                xp_allocations=[
                    award.model_dump(mode="json") for award in command.xp_awards
                ],
                writebacks=[
                    writeback.model_dump(mode="json")
                    for writeback in command.writebacks
                ],
                result_json={
                    "character_ids": list(characters),
                    "condition_ids": [condition.id for condition in created_conditions],
                    "total_xp": sum(award.xp for award in command.xp_awards),
                    "total_copper": sum(
                        award.copper for award in command.currency_awards
                    ),
                    "currency_changes": currency_changes,
                    "wallet_ids": [wallet.id for wallet in updated_wallets],
                    "loot_changes": loot_changes,
                    "loot_item_ids": [item.id for item in created_items],
                    "scene_entity_changes": scene_changes,
                },
                idempotency_key=idempotency_key,
                notes=command.notes,
                confirmed_at=now,
            )
            session.add(settlement)
            session.flush()
            return {
                "settlement": serialize(settlement),
                "combat": serialize(combat),
                "characters": [
                    serialize(characters[character_id])
                    for character_id in sorted(characters)
                ],
                "conditions": [
                    serialize(condition) for condition in created_conditions
                ],
                "wallets": [serialize(wallet) for wallet in updated_wallets],
                "loot_items": [serialize(item) for item in created_items],
            }

    def list_actions(
        self,
        campaign_id: str,
        combat_id: str,
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            combat = session.get(Combat, combat_id)
            if combat is None or combat.campaign_id != campaign_id:
                raise StateNotFoundError("combat not found in campaign")
            rows = session.scalars(
                select(CombatAction)
                .where(CombatAction.combat_id == combat_id)
                .order_by(CombatAction.created_at, CombatAction.id)
            ).all()
            return tuple(serialize(row) for row in rows)
