from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    Campaign,
    Character,
    CharacterCompanion,
    Combat,
    CombatAction,
    Combatant,
    CombatEffect,
    CombatReinforcement,
    CombatSettlement,
    DeathSave,
    OperationTransaction,
    PlayerActionRequest,
    Scene,
    SceneGrid,
    SceneObject,
    SceneParticipant,
    SceneToken,
)

SIMULATION_CAMPAIGN_NAME = "【系统】召唤物与法术战斗模拟"


class SimulationService:
    """Own the deterministic combat fixture used by the DM test workbench.

    The fixture is intentionally stored in the same campaign, scene, combat,
    combatant, character, and companion tables as a normal session.  The
    simulation page therefore exercises the same APIs as a real campaign; it
    does not maintain a second fake combat state.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _campaign(session: Session) -> Campaign:
        campaign = session.scalar(select(Campaign).where(Campaign.name == SIMULATION_CAMPAIGN_NAME))
        if campaign is None:
            raise StateNotFoundError("simulation campaign not prepared")
        return campaign

    @staticmethod
    def _rule_plan(blocks: list[dict[str, Any]], roots: list[str]) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "automation_ready": True,
            "blocks": blocks,
            "root_block_ids": roots,
        }

    @classmethod
    def _magic_missile_action(cls) -> dict[str, Any]:
        return {
            "name": "魔法飞弹",
            "description": (
                "自动命中一个可见目标；3 枚飞弹共造成 3d4+3 力场伤害。"
                "升环每高一环增加 1 枚飞弹（1d4+1）。"
            ),
            "damage": "3d4+3",
            "damage_type": "force",
            "range": "120尺",
            "spell_level": 1,
            "upcast_damage_dice": 1,
            "auto_hit": True,
            "cost": "动作",
            "resource_key": "spell_slots_1",
            "resource_cost": 1,
            "rule_plan": cls._rule_plan(
                [
                    {
                        "id": "target-magic-missile",
                        "kind": "target",
                        "mode": "single",
                        "disposition": "enemy",
                        "range_ft": 120,
                    },
                    {"id": "auto-hit-magic-missile", "kind": "auto_hit"},
                    {
                        "id": "damage-magic-missile",
                        "kind": "damage",
                        "expression": "3d4+3",
                        "damage_type": "force",
                    },
                ],
                ["target-magic-missile", "auto-hit-magic-missile", "damage-magic-missile"],
            ),
        }

    @staticmethod
    def _compound_damage_action() -> dict[str, Any]:
        return {
            "name": "元素裂解",
            "description": "远程法术攻击；命中造成 2d6 火焰和 1d6 力场伤害，逐段结算防御。",
            "damage": "2d6+1d6",
            "damage_type": "mixed",
            "damage_components": [
                {"expression": "2d6", "damage_type": "fire"},
                {"expression": "1d6", "damage_type": "force"},
            ],
            "range": "60尺",
            "spell_level": 2,
            "cost": "动作",
            "resource_key": "spell_slots_2",
            "resource_cost": 1,
            "rule_plan": SimulationService._rule_plan(
                [
                    {
                        "id": "target-elemental-split",
                        "kind": "target",
                        "mode": "single",
                        "disposition": "enemy",
                        "range_ft": 60,
                    },
                    {
                        "id": "damage-elemental-split-fire",
                        "kind": "damage",
                        "expression": "2d6",
                        "damage_type": "fire",
                    },
                    {
                        "id": "damage-elemental-split-force",
                        "kind": "damage",
                        "expression": "1d6",
                        "damage_type": "force",
                    },
                ],
                [
                    "target-elemental-split",
                    "damage-elemental-split-fire",
                    "damage-elemental-split-force",
                ],
            ),
        }

    @staticmethod
    def _combatant(
        combat: Combat,
        *,
        entity_type: str,
        entity_id: str | None,
        name: str,
        initiative: int,
        armor_class: int,
        hp: int,
        position: tuple[int, int],
        disposition: str,
        actions: list[dict[str, Any]],
        ability_scores: dict[str, int],
        resistances: list[str] | None = None,
        vulnerabilities: list[str] | None = None,
    ) -> Combatant:
        base_snapshot: dict[str, Any] = {
            "ability_scores": ability_scores,
            "actions": actions,
            "controller": "player" if entity_type == "character" else "dm",
            "disposition": disposition,
            "grid_position": {"row": position[0], "col": position[1]},
            "simulation_role": "player" if entity_type == "character" else "enemy",
        }
        snapshot = {
            **base_snapshot,
            "combat_start_state": {
                "hp": hp,
                "temporary_hp": 0,
                "conditions": [],
                "movement_remaining_ft": 30,
                "action_available": True,
                "bonus_action_available": True,
                "reaction_available": True,
                "is_active": True,
                "snapshot_json": base_snapshot,
            },
        }
        return Combatant(
            combat_id=combat.id,
            entity_type=entity_type,
            entity_id=entity_id,
            display_name=name,
            initiative=initiative,
            armor_class=armor_class,
            hp=hp,
            max_hp=hp,
            damage_resistances=resistances or [],
            damage_vulnerabilities=vulnerabilities or [],
            speed_ft=30,
            movement_remaining_ft=30,
            snapshot_json=snapshot,
        )

    @classmethod
    def _seed(cls, session: Session) -> tuple[Campaign, Scene, Combat]:
        now = datetime.now(UTC)
        campaign = Campaign(
            name=SIMULATION_CAMPAIGN_NAME,
            description=(
                "系统专用隔离战斗演练。这里的 Scene、Combat、Combatant、玩家房间和召唤模板"
                "都走正式战斗链；不会读取或修改普通跑团数据。"
            ),
            world_setting="测试地城：元素熔炉",
            current_time=now,
            status="active",
            allow_legacy=True,
            enabled_rule_extensions=["chase", "morale"],
        )
        session.add(campaign)
        session.flush()

        scene = Scene(
            campaign_id=campaign.id,
            name="模拟战斗：元素熔炉",
            description=(
                "一间带半掩体、墙壁和狭窄通道的训练场。测试目标：施法、豁免、范围、"
                "混合伤害、状态、召唤物先攻和敌方自动回合。"
            ),
            status="active",
        )
        session.add(scene)
        session.flush()
        cells = [
            {"row": 3, "col": 5, "kind": "cover", "label": "石柱", "blocks_sight": False},
            {"row": 4, "col": 5, "kind": "cover", "label": "石柱", "blocks_sight": False},
            {"row": 5, "col": 5, "kind": "cover", "label": "石柱", "blocks_sight": False},
            {"row": 2, "col": 8, "kind": "wall", "label": "熔炉墙", "blocks_sight": True},
            {"row": 3, "col": 8, "kind": "wall", "label": "熔炉墙", "blocks_sight": True},
            {"row": 4, "col": 8, "kind": "wall", "label": "熔炉墙", "blocks_sight": True},
        ]
        session.add(
            SceneGrid(
                scene_id=scene.id,
                width=12,
                height=8,
                cell_size_ft=5,
                mode="combat",
                public_description="元素熔炉训练地图；石柱提供半掩体，熔炉墙阻挡视线。",
                dm_description="用于验证范围、掩体、视线、召唤物和怪物 AI。",
                layers_json={
                    "theme": "elemental_forge",
                    "visual_theme": {"floor": "obsidian", "accent": "ember"},
                    "fog_of_war": True,
                    "cells": cells,
                },
            )
        )
        session.add_all(
            [
                SceneObject(
                    scene_id=scene.id,
                    object_type="cover",
                    label="中央石柱",
                    row=3,
                    col=5,
                    width_cells=1,
                    height_cells=3,
                    state="active",
                    visibility="public",
                    metadata_json={"cover": "half", "blocks_sight": False},
                ),
                SceneObject(
                    scene_id=scene.id,
                    object_type="wall",
                    label="熔炉墙",
                    row=2,
                    col=8,
                    width_cells=1,
                    height_cells=3,
                    state="active",
                    visibility="public",
                    metadata_json={"blocks_sight": True},
                ),
            ]
        )

        fire_bolt = {
            "name": "火焰箭",
            "description": "远程法术攻击；命中造成 1d10 火焰伤害。",
            "damage": "1d10",
            "damage_type": "fire",
            "range": "120尺",
            "cost": "动作",
            "rule_plan": cls._rule_plan(
                [
                    {"id": "target-fire-bolt", "kind": "target", "mode": "single", "range_ft": 120},
                    {
                        "id": "damage-fire-bolt",
                        "kind": "damage",
                        "expression": "1d10",
                        "damage_type": "fire",
                    },
                ],
                ["target-fire-bolt", "damage-fire-bolt"],
            ),
        }
        thunderwave = {
            "name": "雷鸣波",
            "description": "自身周围 15 尺立方；体质豁免，失败 2d8 雷鸣伤害并推离 10 尺。",
            "damage": "2d8",
            "damage_type": "thunder",
            "range": "自身；15尺立方",
            "spell_level": 1,
            "cost": "动作",
            "resource_key": "spell_slots_1",
            "resource_cost": 1,
            "rule_plan": cls._rule_plan(
                [
                    {
                        "id": "target-thunderwave",
                        "kind": "target",
                        "mode": "area",
                        "disposition": "enemy",
                        "range_ft": 0,
                        "shape": "cube",
                        "size_ft": 15,
                    },
                    {
                        "id": "damage-thunderwave",
                        "kind": "damage",
                        "expression": "2d8",
                        "damage_type": "thunder",
                    },
                    {"id": "save-thunderwave", "kind": "save", "ability": "constitution", "dc": 13},
                    {
                        "id": "move-thunderwave",
                        "kind": "move",
                        "movement_type": "forced",
                        "distance_ft": 10,
                        "direction": "away",
                    },
                ],
                [
                    "target-thunderwave",
                    "damage-thunderwave",
                    "save-thunderwave",
                    "move-thunderwave",
                ],
            ),
        }
        fireball = {
            "name": "火球术",
            "description": "150 尺内 20 尺球形区域；敏捷豁免，失败 8d6 火焰伤害，成功半伤。",
            "damage": "8d6",
            "damage_type": "fire",
            "half_damage_on_save": True,
            "range": "150尺；20尺球形",
            "range_ft": 150,
            "area_shape": "sphere",
            "area_size_ft": 20,
            "save_dc": 14,
            "save_ability": "dexterity",
            "affects_multiple_targets": True,
            "spell_level": 3,
            "upcast_damage_dice": 1,
            "cost": "动作",
            "resource_key": "spell_slots_3",
            "resource_cost": 1,
            "rule_plan": cls._rule_plan(
                [
                    {
                        "id": "target-fireball",
                        "kind": "target",
                        "mode": "area",
                        "disposition": "enemy",
                        "range_ft": 150,
                        "shape": "sphere",
                        "size_ft": 20,
                    },
                    {
                        "id": "damage-fireball",
                        "kind": "damage",
                        "expression": "8d6",
                        "damage_type": "fire",
                    },
                    {
                        "id": "save-fireball",
                        "kind": "save",
                        "ability": "dexterity",
                        "dc": 14,
                        "on_success": "half",
                    },
                ],
                ["target-fireball", "damage-fireball", "save-fireball"],
            ),
        }
        magic_missile = cls._magic_missile_action()
        compound_damage = cls._compound_damage_action()
        healing_word = {
            "name": "治疗之触",
            "description": "接触恢复 1d4+4 生命。",
            "healing": "1d4+4",
            "range": "接触",
            "spell_level": 1,
            "cost": "附赠动作",
            "resource_key": "spell_slots_1",
            "resource_cost": 1,
            "rule_plan": cls._rule_plan(
                [
                    {"id": "target-heal", "kind": "target", "mode": "single", "range_ft": 5},
                    {"id": "heal-touch", "kind": "heal", "expression": "1d4+4"},
                ],
                ["target-heal", "heal-touch"],
            ),
        }
        summon_elemental = {
            "name": "召唤小火元素",
            "description": "召唤一个独立先攻、由玩家控制的小火元素，持续 3 轮。",
            "range": "30尺",
            "spell_level": 2,
            "cost": "动作",
            "resource_key": "spell_slots_2",
            "resource_cost": 1,
            "concentration": True,
            "rule_plan": cls._rule_plan(
                [
                    {"id": "target-summon", "kind": "target", "mode": "point", "range_ft": 30},
                    {
                        "id": "summon-elemental",
                        "kind": "summon",
                        "creature_ref": "小火元素",
                        "template_ref": "simulation-fire-elemental",
                        "controller": "caster",
                        "initiative_mode": "independent",
                        "enters_combat": True,
                        "count": 1,
                    },
                    {
                        "id": "duration-summon",
                        "kind": "duration",
                        "unit": "round",
                        "value": 3,
                        "concentration": True,
                    },
                ],
                ["target-summon", "summon-elemental", "duration-summon"],
            ),
        }

        character = Character(
            campaign_id=campaign.id,
            name="模拟玩家·奥术师",
            race="人类",
            background="学者",
            class_name="法师",
            level=5,
            armor_class=14,
            speed=30,
            ability_scores={
                "strength": 8,
                "dexterity": 14,
                "constitution": 14,
                "intelligence": 18,
                "wisdom": 12,
                "charisma": 10,
            },
            hp=28,
            max_hp=28,
            actions=[fire_bolt],
            spells=[
                thunderwave,
                fireball,
                magic_missile,
                compound_damage,
                healing_word,
                summon_elemental,
            ],
            spellcasting={
                "ability": "intelligence",
                "mode": "slots",
                "save_dc": 14,
                "attack_bonus": 6,
            },
            resources={
                "spell_slots_1": {
                    "label": "1环法术位",
                    "current": 4,
                    "max": 4,
                    "recovery": "long_rest",
                },
                "spell_slots_2": {
                    "label": "2环法术位",
                    "current": 3,
                    "max": 3,
                    "recovery": "long_rest",
                },
                "spell_slots_3": {
                    "label": "3环法术位",
                    "current": 2,
                    "max": 2,
                    "recovery": "long_rest",
                },
            },
            class_levels={"法师": 5},
            features=["奥术回响（模拟规则入口）", "法术书", "战术移动"],
            notes="系统模拟角色；用于验证法术范围、豁免、伤害、升环和召唤。",
        )
        session.add(character)
        session.flush()

        companion_action = {
            "name": "灼热爪击",
            "description": "近战攻击；命中造成 1d6+2 火焰伤害。",
            "damage": "1d6+2",
            "damage_type": "fire",
            "range": "5尺",
            "cost": "动作",
            "rule_plan": cls._rule_plan(
                [
                    {"id": "target-claw", "kind": "target", "mode": "single", "range_ft": 5},
                    {
                        "id": "damage-claw",
                        "kind": "damage",
                        "expression": "1d6+2",
                        "damage_type": "fire",
                    },
                ],
                ["target-claw", "damage-claw"],
            ),
        }
        companion = CharacterCompanion(
            campaign_id=campaign.id,
            owner_character_id=character.id,
            name="小火元素（模拟模板）",
            companion_type="summon",
            source_record_id="simulation-fire-elemental",
            template_json={
                "ability_scores": {
                    "strength": 10,
                    "dexterity": 14,
                    "constitution": 12,
                    "intelligence": 6,
                    "wisdom": 10,
                    "charisma": 8,
                },
                "actions": [companion_action],
                "initiative_mode": "independent",
                "controller": "player",
                "disposition": "ally",
            },
            hp=18,
            max_hp=18,
            armor_class=13,
            speed=30,
            notes="用于测试玩家召唤物创建新 Combatant、独立先攻、独立回合和结束召唤。",
        )
        session.add(companion)
        session.flush()

        combat = Combat(
            campaign_id=campaign.id,
            scene_id=scene.id,
            name="模拟战斗：熔炉门厅",
            status="active",
            round_number=1,
            current_turn_index=0,
            difficulty="moderate",
            base_xp=450,
            difficulty_adjustments=[
                {"source": "simulation", "note": "固定演练遭遇，不计入真实战役经验。"}
            ],
        )
        session.add(combat)
        session.flush()

        enemy_bolt = {
            "name": "熔火射线",
            "description": "远程法术攻击；命中造成 2d6 火焰伤害。",
            "damage": "2d6",
            "damage_type": "fire",
            "range": "60尺",
            "attack_bonus": 5,
            "cost": "动作",
        }
        enemy_burst = {
            "name": "熔炉爆裂",
            "description": "15尺锥形；敏捷豁免 DC 13，失败 2d6 火焰伤害。",
            "damage": "2d6",
            "damage_type": "fire",
            "range": "15尺锥形",
            "save_dc": 13,
            "save_ability": "dexterity",
            "cost": "动作",
        }
        golem_strike = {
            "name": "熔岩重击",
            "description": "近战攻击；命中造成 1d10+3 钝击伤害。",
            "damage": "1d10+3",
            "damage_type": "bludgeoning",
            "range": "5尺",
            "attack_bonus": 5,
            "cost": "动作",
        }
        player_combatant = cls._combatant(
            combat,
            entity_type="character",
            entity_id=character.id,
            name=character.name,
            initiative=20,
            armor_class=character.armor_class,
            hp=character.hp,
            position=(6, 2),
            disposition="ally",
            actions=[
                fire_bolt,
                thunderwave,
                fireball,
                magic_missile,
                compound_damage,
                healing_word,
                summon_elemental,
            ],
            ability_scores=character.ability_scores,
        )
        mage = cls._combatant(
            combat,
            entity_type="monster",
            entity_id=None,
            name="熔火术士·AI",
            initiative=16,
            armor_class=13,
            hp=30,
            position=(5, 4),
            disposition="enemy",
            actions=[enemy_bolt, enemy_burst],
            ability_scores={
                "strength": 8,
                "dexterity": 14,
                "constitution": 12,
                "intelligence": 16,
                "wisdom": 10,
                "charisma": 12,
            },
            resistances=["fire"],
        )
        golem = cls._combatant(
            combat,
            entity_type="monster",
            entity_id=None,
            name="熔炉守卫·AI",
            initiative=11,
            armor_class=16,
            hp=38,
            position=(7, 4),
            disposition="enemy",
            actions=[golem_strike],
            ability_scores={
                "strength": 18,
                "dexterity": 8,
                "constitution": 16,
                "intelligence": 4,
                "wisdom": 10,
                "charisma": 5,
            },
            resistances=["fire", "poison"],
            vulnerabilities=[],
        )
        for fighter in (player_combatant, mage, golem):
            session.add(fighter)
        session.flush()

        session.add_all(
            [
                SceneParticipant(
                    scene_id=scene.id,
                    entity_type="character",
                    entity_id=character.id,
                    role="present",
                ),
                SceneToken(
                    scene_id=scene.id,
                    entity_type="character",
                    entity_id=character.id,
                    label=character.name,
                    row=6,
                    col=2,
                ),
                SceneToken(
                    scene_id=scene.id,
                    entity_type="monster",
                    entity_id=mage.id,
                    label=mage.display_name,
                    row=5,
                    col=7,
                ),
                SceneToken(
                    scene_id=scene.id,
                    entity_type="monster",
                    entity_id=golem.id,
                    label=golem.display_name,
                    row=7,
                    col=7,
                ),
            ]
        )
        session.flush()
        return campaign, scene, combat

    @staticmethod
    def _reset_combat(session: Session, campaign: Campaign, combat: Combat) -> None:
        fighter_ids = [
            row.id
            for row in session.scalars(
                select(Combatant).where(Combatant.combat_id == combat.id)
            ).all()
        ]
        session.execute(delete(CombatEffect).where(CombatEffect.combat_id == combat.id))
        session.execute(delete(CombatAction).where(CombatAction.combat_id == combat.id))
        session.execute(
            delete(CombatReinforcement).where(CombatReinforcement.combat_id == combat.id)
        )
        session.execute(delete(CombatSettlement).where(CombatSettlement.combat_id == combat.id))
        if fighter_ids:
            session.execute(delete(DeathSave).where(DeathSave.combatant_id.in_(fighter_ids)))
        session.execute(
            delete(PlayerActionRequest).where(PlayerActionRequest.campaign_id == campaign.id)
        )
        session.execute(
            delete(OperationTransaction).where(
                OperationTransaction.campaign_id == campaign.id,
                OperationTransaction.source == "combat",
            )
        )
        fighters = session.scalars(select(Combatant).where(Combatant.combat_id == combat.id)).all()
        dynamic_ids = [
            fighter.id
            for fighter in fighters
            if fighter.entity_type == "companion"
            or (
                isinstance(fighter.snapshot_json, dict)
                and fighter.snapshot_json.get("summon_source_combatant_id")
            )
        ]
        if dynamic_ids:
            session.execute(delete(SceneToken).where(SceneToken.entity_id.in_(dynamic_ids)))
            session.execute(delete(Combatant).where(Combatant.id.in_(dynamic_ids)))
        fighters = [fighter for fighter in fighters if fighter.id not in dynamic_ids]
        for fighter in fighters:
            baseline = dict(fighter.snapshot_json or {}).get("combat_start_state")
            if not isinstance(baseline, dict):
                continue
            fighter.hp = int(baseline.get("hp", fighter.max_hp))
            fighter.temporary_hp = int(baseline.get("temporary_hp", 0))
            fighter.conditions = list(baseline.get("conditions", []))
            fighter.concentration = {}
            fighter.movement_remaining_ft = int(
                baseline.get("movement_remaining_ft", fighter.speed_ft)
            )
            fighter.action_available = bool(baseline.get("action_available", True))
            fighter.bonus_action_available = bool(baseline.get("bonus_action_available", True))
            fighter.reaction_available = bool(baseline.get("reaction_available", True))
            fighter.is_active = bool(baseline.get("is_active", True))
            base_snapshot = baseline.get("snapshot_json")
            if isinstance(base_snapshot, dict):
                fighter.snapshot_json = {
                    **base_snapshot,
                    "combat_start_state": baseline,
                }
            fighter.version += 1
            fighter.updated_at = datetime.now(UTC)
        character = session.scalar(
            select(Character).where(
                Character.campaign_id == campaign.id,
                Character.name == "模拟玩家·奥术师",
            )
        )
        if character is not None:
            resources = {
                key: dict(value) if isinstance(value, dict) else value
                for key, value in (character.resources or {}).items()
            }
            for key in ("spell_slots_1", "spell_slots_2", "spell_slots_3"):
                resource = resources.get(key)
                if isinstance(resource, dict) and "max" in resource:
                    resource["current"] = resource["max"]
            character.resources = resources
            character.updated_at = datetime.now(UTC)
        combat.status = "active"
        combat.round_number = 1
        combat.current_turn_index = 0
        combat.xp_awarded = False
        combat.ended_at = None
        combat.version += 1
        combat.updated_at = datetime.now(UTC)

    @classmethod
    def _repair_known_fixture_regressions(
        cls,
        session: Session,
        campaign: Campaign,
    ) -> None:
        """Repair old persisted simulation rows after fixture rule-shape fixes.

        The simulation is intentionally persistent so the DM can share its
        player link.  Updating the seed alone would leave an already-created
        database with the old force-damage Fire Bolt and point-only area plans.
        Keep this migration narrow and idempotent rather than deleting the
        user's current test combat.
        """

        def repair_action(raw: object) -> object:
            if not isinstance(raw, dict):
                return raw
            action = deepcopy(raw)
            name = str(action.get("name") or "")
            if name == "火焰箭":
                action["description"] = "远程法术攻击；命中造成 1d10 火焰伤害。"
                action["damage_type"] = "fire"
                plan = action.get("rule_plan")
                if isinstance(plan, dict):
                    repaired_plan = deepcopy(plan)
                    blocks = []
                    for block in repaired_plan.get("blocks", []):
                        if not isinstance(block, dict):
                            blocks.append(block)
                            continue
                        next_block = deepcopy(block)
                        if next_block.get("kind") == "damage":
                            next_block["damage_type"] = "fire"
                        blocks.append(next_block)
                    repaired_plan["blocks"] = blocks
                    action["rule_plan"] = repaired_plan
            elif name == "雷鸣波":
                # Some already-created simulation rows were persisted before the
                # area-target migration.  They can contain a self/single target
                # block (or an orphaned area_effect block), which makes the
                # player UI show a target dropdown instead of the 15-foot cube.
                # Normalize this fixture to the same executable plan as the seed;
                # do not rely on prose parsing to recover a rule that is known
                # exactly.
                action["description"] = (
                    "自身周围 15 尺立方；体质豁免，失败 2d8 雷鸣伤害并推离 10 尺。"
                )
                action["damage"] = "2d8"
                action["damage_type"] = "thunder"
                action["range"] = "自身；15尺立方"
                plan = action.get("rule_plan")
                if isinstance(plan, dict):
                    repaired_plan = deepcopy(plan)
                    blocks = [
                        deepcopy(block)
                        for block in repaired_plan.get("blocks", [])
                        if isinstance(block, dict) and block.get("kind") != "area_effect"
                    ]
                    canonical_by_kind: dict[str, dict[str, Any]] = {
                        "target": {
                            "id": "target-thunderwave",
                            "kind": "target",
                            "mode": "area",
                            "disposition": "enemy",
                            "range_ft": 0,
                            "shape": "cube",
                            "size_ft": 15,
                        },
                        "damage": {
                            "id": "damage-thunderwave",
                            "kind": "damage",
                            "expression": "2d8",
                            "damage_type": "thunder",
                        },
                        "save": {
                            "id": "save-thunderwave",
                            "kind": "save",
                            "ability": "constitution",
                            "dc": 13,
                        },
                        "move": {
                            "id": "move-thunderwave",
                            "kind": "move",
                            "movement_type": "forced",
                            "distance_ft": 10,
                            "direction": "away",
                        },
                    }
                    seen_kinds: set[str] = set()
                    normalized_blocks: list[dict[str, Any]] = []
                    for block in blocks:
                        kind = str(block.get("kind") or "")
                        canonical = canonical_by_kind.get(kind)
                        if canonical is None or kind in seen_kinds:
                            if kind not in seen_kinds:
                                normalized_blocks.append(block)
                            continue
                        normalized = deepcopy(block)
                        normalized.update(canonical)
                        normalized_blocks.append(normalized)
                        seen_kinds.add(kind)
                    for kind, canonical in canonical_by_kind.items():
                        if kind not in seen_kinds:
                            normalized_blocks.append(deepcopy(canonical))
                    repaired_plan["blocks"] = normalized_blocks
                    repaired_plan["root_block_ids"] = [
                        str(block["id"])
                        for block in normalized_blocks
                        if str(block.get("id") or "")
                    ]
                    action["rule_plan"] = repaired_plan
            elif name == "火球术":
                # Older persisted fixture rows carried the prose "成功半伤"
                # but omitted the executable save outcome.  Keep both the
                # legacy field and the save block authoritative on every
                # prepare/reset, so a successful save cannot resolve to 0.
                action["half_damage_on_save"] = True
                # The DM combat console intentionally uses the action's
                # top-level executable fields for its branch selection.  Some
                # older persisted fixtures only retained these facts inside
                # rule_plan, which made Fireball render as a normal attack
                # despite having an area/save plan.  Keep the fixture's
                # canonical rules duplicated at the transport boundary so
                # old and newly seeded simulations behave identically.
                action["range"] = "150尺；20尺球形"
                action["range_ft"] = 150
                action["area_shape"] = "sphere"
                action["area_size_ft"] = 20
                action["save_dc"] = 14
                action["save_ability"] = "dexterity"
                action["affects_multiple_targets"] = True
                plan = action.get("rule_plan")
                if isinstance(plan, dict):
                    plan_blocks = plan.get("blocks")
                    if isinstance(plan_blocks, list):
                        plan["blocks"] = [
                            {
                                **block,
                                "on_success": "half",
                            }
                            if isinstance(block, dict) and block.get("kind") == "save"
                            else block
                            for block in plan_blocks
                        ]
                    area = next(
                        (block for block in plan.get("blocks", [])
                         if isinstance(block, dict) and block.get("kind") == "area_effect"),
                        None,
                    )
                    if isinstance(area, dict):
                        repaired_plan = deepcopy(plan)
                        repaired_blocks: list[object] = []
                        area_ids = {
                            str(child_id)
                            for child_id in area.get("effect_block_ids", [])
                            if isinstance(child_id, str)
                        }
                        for block in repaired_plan.get("blocks", []):
                            if not isinstance(block, dict):
                                repaired_blocks.append(block)
                                continue
                            if block.get("kind") == "area_effect":
                                continue
                            next_block = deepcopy(block)
                            if next_block.get("kind") == "target":
                                next_block["mode"] = "area"
                                next_block["disposition"] = "enemy"
                                next_block["shape"] = area.get("shape")
                                next_block["size_ft"] = area.get("size_ft")
                                if area.get("width_ft") is not None:
                                    next_block["width_ft"] = area.get("width_ft")
                            if (
                                name == "雷鸣波"
                                and next_block.get("kind") == "move"
                                and next_block.get("direction") in {"away", "push"}
                                and next_block.get("movement_type") in (None, "")
                            ):
                                # Older persisted simulation rows were seeded with the
                                # shorthand move block.  The combat executor only runs
                                # explicitly forced movement, so repair the fixture at
                                # the same boundary where the legacy area shape is fixed.
                                next_block["movement_type"] = "forced"
                            repaired_blocks.append(next_block)
                        repaired_plan["blocks"] = repaired_blocks
                        roots = [
                            str(root_id)
                            for root_id in repaired_plan.get("root_block_ids", [])
                            if str(root_id) not in area_ids
                        ]
                        repaired_plan["root_block_ids"] = roots
                        action["rule_plan"] = repaired_plan
            return action

        character = session.scalar(
            select(Character).where(
                Character.campaign_id == campaign.id,
                Character.name == "模拟玩家·奥术师",
            )
        )
        if character is not None:
            character.actions = [repair_action(item) for item in character.actions or []]
            character.spells = [repair_action(item) for item in character.spells or []]
            if not any(
                isinstance(item, dict) and item.get("name") == "魔法飞弹"
                for item in character.spells
            ):
                character.spells = [*character.spells, cls._magic_missile_action()]
            if not any(
                isinstance(item, dict) and item.get("name") == "元素裂解"
                for item in character.spells
            ):
                character.spells = [*character.spells, cls._compound_damage_action()]
        combat = session.scalar(
            select(Combat).where(
                Combat.campaign_id == campaign.id,
                Combat.name == "模拟战斗：熔炉门厅",
            )
        )
        if combat is None:
            return
        # A previous DM advanced-action test could have overwritten the
        # persisted mage snapshot with only its legendary/lair/reaction
        # actions.  Keep those actions, but restore the two ordinary actions
        # that make the fixture a runnable AI encounter.  Without this repair
        # the frontend correctly filters advanced actions out of the normal
        # monster turn, falls back to "未结构化动作", and can wait forever at
        # a zero-range targeting plan after the monster moves.
        mage_core_actions: tuple[dict[str, Any], ...] = (
            {
                "name": "熔火射线",
                "description": "远程法术攻击；命中造成 2d6 火焰伤害。",
                "damage": "2d6",
                "damage_type": "fire",
                "range": "60尺",
                "attack_bonus": 5,
                "cost": "动作",
            },
            {
                "name": "熔炉爆裂",
                "description": "15尺锥形；敏捷豁免 DC 13，失败 2d6 火焰伤害。",
                "damage": "2d6",
                "damage_type": "fire",
                "range": "15尺锥形",
                "range_ft": 15,
                "area_shape": "cone",
                "area_size_ft": 15,
                "affects_multiple_targets": True,
                "save_dc": 13,
                "save_ability": "dexterity",
                "cost": "动作",
            },
        )
        for fighter in session.scalars(
            select(Combatant).where(Combatant.combat_id == combat.id)
        ).all():
            snapshot = deepcopy(fighter.snapshot_json or {})
            snapshot["actions"] = [repair_action(item) for item in snapshot.get("actions", [])]
            if fighter.display_name == "熔火术士·AI":
                existing_names = {
                    str(item.get("name") or "")
                    for item in snapshot["actions"]
                    if isinstance(item, dict)
                }
                snapshot["actions"] = [
                    *[
                        deepcopy(action)
                        for action in mage_core_actions
                        if action["name"] not in existing_names
                    ],
                    *snapshot["actions"],
                ]
            if fighter.entity_type == "character" and not any(
                isinstance(item, dict) and item.get("name") == "魔法飞弹"
                for item in snapshot["actions"]
            ):
                snapshot["actions"].append(cls._magic_missile_action())
            if fighter.entity_type == "character" and not any(
                isinstance(item, dict) and item.get("name") == "元素裂解"
                for item in snapshot["actions"]
            ):
                snapshot["actions"].append(cls._compound_damage_action())
            fixture_positions = {
                "模拟玩家·奥术师": {"row": 6, "col": 2},
                "熔火术士·AI": {"row": 5, "col": 4},
                "熔炉守卫·AI": {"row": 7, "col": 4},
            }
            if fighter.display_name in fixture_positions:
                snapshot["grid_position"] = fixture_positions[fighter.display_name]
            baseline = snapshot.get("combat_start_state")
            if isinstance(baseline, dict):
                baseline_snapshot = baseline.get("snapshot_json")
                if not isinstance(baseline_snapshot, dict):
                    baseline_snapshot = {}
                position = snapshot.get("grid_position")
                if not isinstance(position, dict):
                    position = baseline_snapshot.get("grid_position")
                if isinstance(position, dict):
                    snapshot["grid_position"] = {
                        "row": int(position["row"]),
                        "col": int(position["col"]),
                    }
                    baseline_snapshot["grid_position"] = dict(snapshot["grid_position"])
                baseline["snapshot_json"] = {
                    **deepcopy(baseline_snapshot),
                    "actions": deepcopy(snapshot["actions"]),
                }
                snapshot["combat_start_state"] = baseline
            fighter.snapshot_json = snapshot

    @staticmethod
    def _state(session: Session, campaign: Campaign) -> dict[str, Any]:
        scene = session.scalar(
            select(Scene).where(
                Scene.campaign_id == campaign.id, Scene.name == "模拟战斗：元素熔炉"
            )
        )
        combat = session.scalar(
            select(Combat).where(
                Combat.campaign_id == campaign.id, Combat.name == "模拟战斗：熔炉门厅"
            )
        )
        character = session.scalar(
            select(Character).where(
                Character.campaign_id == campaign.id, Character.name == "模拟玩家·奥术师"
            )
        )
        companion = session.scalar(
            select(CharacterCompanion).where(
                CharacterCompanion.campaign_id == campaign.id,
                CharacterCompanion.name == "小火元素（模拟模板）",
            )
        )
        if scene is None or combat is None or character is None or companion is None:
            raise StateNotFoundError("simulation fixture is incomplete")
        combatants = session.scalars(
            select(Combatant)
            .where(Combatant.combat_id == combat.id, Combatant.is_active.is_(True))
            .order_by(Combatant.initiative.desc(), Combatant.created_at, Combatant.id)
        ).all()
        grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene.id))
        return {
            "scenario": {
                "title": "元素熔炉：召唤与范围战斗演练",
                "objective": (
                    "用同一套正式战斗框架验证火球术、雷鸣波、治疗、敌方 AI、"
                    "豁免、混合伤害和召唤物先攻。"
                ),
                "checkpoints": [
                    "玩家端选择雷鸣波或火球术，查看范围、伤害和豁免提示",
                    "玩家端施放召唤小火元素，确认创建新的 Combatant 并进入先攻",
                    "DM 开启怪物全自动，观察敌方移动、动作和需要玩家骰点时的暂停",
                    "DM 重置模拟战斗，确认状态、资源、HP、先攻和日志回到初始值",
                ],
            },
            "campaign": serialize(campaign),
            "scene": serialize(scene),
            "grid": serialize(grid) if grid is not None else None,
            "combat": serialize(combat),
            "combatants": [serialize(row) for row in combatants],
            "character": serialize(character),
            "companion": serialize(companion),
        }

    def current(self) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._state(session, self._campaign(session))

    def prepare(self, *, reset: bool = False) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            campaign = session.scalar(
                select(Campaign).where(Campaign.name == SIMULATION_CAMPAIGN_NAME)
            )
            if campaign is None:
                campaign, _, _ = self._seed(session)
            else:
                self._repair_known_fixture_regressions(session, campaign)
            if campaign is not None and reset:
                combat = session.scalar(
                    select(Combat).where(
                        Combat.campaign_id == campaign.id,
                        Combat.name == "模拟战斗：熔炉门厅",
                    )
                )
                if combat is None:
                    raise StateNotFoundError("simulation combat not found")
                self._reset_combat(session, campaign, combat)
            return self._state(session, campaign)
