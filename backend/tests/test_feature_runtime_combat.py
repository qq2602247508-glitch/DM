from __future__ import annotations

from types import SimpleNamespace

import pytest

from dnd_dm_assistant.api.schemas import PlayerRollResolutionCommand
from dnd_dm_assistant.domain.feature_runtime import compile_feature_runtime_registry
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import CombatAction, Combatant
from dnd_dm_assistant.infrastructure.database.player_room_service import PlayerRoomService


def test_typed_feature_saving_throw_advantage_is_consumed_by_save_resolution() -> None:
    target = Combatant(
        id="danger-sense",
        entity_type="character",
        display_name="危险感知者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "rule_modifiers": {
                "saving_throw:self::danger": {
                    "stat": "saving_throw",
                    "scope": "self",
                    "ability": "dexterity",
                    "operation": "advantage",
                    "source": "危险感知",
                    "applies_when": "not_incapacitated",
                }
            }
        },
    )

    result = CombatEngineService._resolve_save_defenses(
        target,
        dc=15,
        ability="敏捷",
        roll_total=8,
        roll_totals=[8, 17],
        damage_on_success=0,
        damage_on_failure=10,
        is_magical=True,
        use_legendary_resistance=False,
        use_feature_reroll=False,
        consume=False,
    )

    assert result["effective_roll_total"] == 17
    assert result["success"] is True
    assert "feature:危险感知" in result["applied_defenses"]

    target.conditions = ["失能"]
    blocked = CombatEngineService._resolve_save_defenses(
        target,
        dc=15,
        ability="敏捷",
        roll_total=8,
        roll_totals=[8, 17],
        damage_on_success=0,
        damage_on_failure=0,
        is_magical=True,
        use_legendary_resistance=False,
        use_feature_reroll=False,
        consume=False,
    )
    assert blocked["effective_roll_total"] == 8
    assert "feature:危险感知" not in blocked["applied_defenses"]


def test_rage_strength_saving_throw_advantage_requires_active_raging_condition() -> None:
    raging_target = Combatant(
        id="raging-save",
        entity_type="character",
        display_name="狂暴者",
        hp=20,
        max_hp=20,
        conditions=["狂暴"],
        snapshot_json={
            "rule_modifiers": {
                "saving_throw:self::rage": {
                    "stat": "saving_throw",
                    "scope": "self",
                    "ability": "strength",
                    "operation": "advantage",
                    "source": "狂暴",
                    "applies_when": "raging",
                }
            }
        },
    )
    ended_target = Combatant(
        id="ended-rage-save",
        entity_type="character",
        display_name="狂暴结束者",
        hp=20,
        max_hp=20,
        snapshot_json=raging_target.snapshot_json,
    )

    active = CombatEngineService._resolve_save_defenses(
        raging_target,
        dc=15,
        ability="strength",
        roll_total=5,
        roll_totals=[5, 18],
        damage_on_success=0,
        damage_on_failure=0,
        is_magical=False,
        use_legendary_resistance=False,
        use_feature_reroll=False,
        consume=False,
    )
    ended = CombatEngineService._resolve_save_defenses(
        ended_target,
        dc=15,
        ability="strength",
        roll_total=5,
        roll_totals=[5, 18],
        damage_on_success=0,
        damage_on_failure=0,
        is_magical=False,
        use_legendary_resistance=False,
        use_feature_reroll=False,
        consume=False,
    )

    assert active["effective_roll_total"] == 18
    assert "feature:狂暴" in active["applied_defenses"]
    assert ended["effective_roll_total"] == 5
    assert ended["applied_defenses"] == []


def test_player_attack_context_applies_reckless_attack_to_both_sides() -> None:
    actor = Combatant(
        id="reckless-attacker",
        entity_type="character",
        display_name="鲁莽攻击者",
        hp=20,
        max_hp=20,
        conditions=["鲁莽攻击"],
    )
    target = Combatant(
        id="reckless-target",
        entity_type="monster",
        display_name="被鲁莽攻击者",
        hp=20,
        max_hp=20,
        conditions=["reckless_attack"],
    )

    mode, has_advantage, has_disadvantage, _ = PlayerRoomService._condition_attack_context(
        actor,
        target,
        distance_ft=5,
        action={
            "name": "巨斧武器攻击",
            "attack_ability": "strength",
            "is_weapon_attack": True,
        },
    )

    assert mode == "advantage"
    assert has_advantage is True
    assert has_disadvantage is False


def test_innate_sorcery_advantage_requires_active_state_and_sorcerer_spell() -> None:
    modifiers = {
        "attack_roll:outgoing:innate": {
            "stat": "attack_roll",
            "scope": "outgoing",
            "operation": "advantage",
            "source": "先天术法",
            "applies_when": "innate_sorcery_active_and_sorcerer_spell",
        },
        "spell_save_dc:outgoing:innate": {
            "stat": "spell_save_dc",
            "scope": "outgoing",
            "operation": "add",
            "value": 1,
            "source": "先天术法",
            "applies_when": "innate_sorcery_active",
        },
    }
    actor = Combatant(
        id="innate-sorcerer",
        entity_type="character",
        display_name="术士",
        hp=20,
        max_hp=20,
        conditions=["innate_sorcery"],
        snapshot_json={"rule_modifiers": modifiers},
    )
    target = Combatant(
        id="innate-target",
        entity_type="monster",
        display_name="目标",
        hp=20,
        max_hp=20,
    )

    spell_advantage, spell_disadvantage = CombatEngineService._feature_attack_roll_contexts(
        actor,
        target,
        is_spell_attack=True,
        is_sorcerer_spell=True,
    )
    assert spell_advantage == ["先天术法"]
    assert spell_disadvantage == []
    weapon_advantage, _ = CombatEngineService._feature_attack_roll_contexts(
        actor,
        target,
        is_spell_attack=False,
        is_sorcerer_spell=False,
    )
    assert weapon_advantage == []

    inactive = Combatant(
        id="inactive-innate-sorcerer",
        entity_type="character",
        display_name="未激活术士",
        hp=20,
        max_hp=20,
        snapshot_json={"rule_modifiers": modifiers},
    )
    inactive_advantage, _ = CombatEngineService._feature_attack_roll_contexts(
        inactive,
        target,
        is_spell_attack=True,
        is_sorcerer_spell=True,
    )
    assert inactive_advantage == []

    active_dc = CombatEngineService._feature_rule_modifiers(
        actor,
        stat="spell_save_dc",
        scope="outgoing",
    )
    inactive_dc = CombatEngineService._feature_rule_modifiers(
        inactive,
        stat="spell_save_dc",
        scope="outgoing",
    )
    assert [item["value"] for item in active_dc] == [1]
    assert inactive_dc == []
    assert PlayerRoomService._feature_additive_modifier(
        actor,
        "spell_save_dc",
        scope="outgoing",
    ) == 1
    assert PlayerRoomService._feature_additive_modifier(
        inactive,
        "spell_save_dc",
        scope="outgoing",
    ) == 0


def test_raging_strength_check_uses_reported_advantage_rolls() -> None:
    action = CombatAction(
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["raging-checker"],
        request_json={
            "resolution_type": "ability_check",
            "dc": 15,
            "ability": "strength",
            "action_name": "推开石门",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待力量属性检定",
        idempotency_key="raging-strength-check",
    )
    target = Combatant(
        id="raging-checker",
        entity_type="character",
        display_name="狂暴检定者",
        hp=20,
        max_hp=20,
        conditions=["raging"],
        snapshot_json={
            "rule_modifiers": {
                "ability_check:self:strength": {
                    "stat": "ability_check",
                    "scope": "self",
                    "ability": "strength",
                    "operation": "advantage",
                    "source": "狂暴",
                    "applies_when": "raging",
                }
            }
        },
    )

    resolved = CombatEngineService._resolve_player_roll(
        action,
        target,
        PlayerRollResolutionCommand(
            action_version=1,
            roll_total=5,
            roll_totals=[5, 18],
        ),
    )
    assert resolved["roll_total"] == 18
    assert resolved["success"] is True
    assert resolved["applied_defenses"] == ["feature:狂暴"]

    with pytest.raises(ValueError, match="two reported roll totals"):
        CombatEngineService._resolve_player_roll(
            action,
            target,
            PlayerRollResolutionCommand(action_version=1, roll_total=5),
        )


def test_reliable_talent_only_floors_a_proficient_noncombat_check() -> None:
    character = SimpleNamespace(
        features=["可靠才能"],
        skills={"运动": {"proficient": True}},
    )
    untrained = SimpleNamespace(
        features=["可靠才能"],
        skills={"运动": {"proficient": False}},
    )
    assert PlayerRoomService._reliable_talent_applies(character, "运动") is True
    assert PlayerRoomService._reliable_talent_applies(untrained, "运动") is False


def test_failed_save_opens_feature_reroll_window_before_damage() -> None:
    action = CombatAction(
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["reroll-target"],
        request_json={
            "resolution_type": "saving_throw",
            "dc": 15,
            "ability": "wisdom",
            "action_name": "恐惧波动",
            "damage_on_success": 0,
            "damage_on_failure": 12,
            "damage_type": "psychic",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待豁免",
        idempotency_key="feature-reroll-window",
    )
    target = Combatant(
        id="reroll-target",
        entity_type="character",
        display_name="可重掷者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "feature_saving_throw_rerolls": [
                {"feature_id": "indomitable", "source": "不屈", "available": True}
            ]
        },
    )
    first = CombatEngineService._resolve_player_roll(
        action,
        target,
        PlayerRollResolutionCommand(action_version=1, roll_total=5),
    )
    assert first["phase"] == "awaiting_feature_reroll"
    assert first["damage"] == 0
    assert first["feature_reroll_window"] == {
        "feature_id": "indomitable",
        "source": "不屈",
        "original_roll_total": 5,
        "dc": 15,
        "requires_second_roll": True,
    }
    assert target.hp == 20

    final = CombatEngineService._resolve_player_roll(
        action,
        target,
        PlayerRollResolutionCommand(
            action_version=1,
            roll_total=5,
            roll_totals=[5, 18],
            use_feature_reroll=True,
        ),
        consume_defenses=True,
    )
    assert final["phase"] == "resolved"
    assert final["success"] is True
    assert final["feature_reroll_consumed"]["resource"] == (
        "feature_saving_throw_reroll"
    )
    assert target.snapshot_json["feature_saving_throw_rerolls"][0]["available"] is False


def test_elusive_suppresses_condition_advantage_unless_incapacitated() -> None:
    actor = Combatant(
        id="elusive-attacker",
        entity_type="monster",
        display_name="攻击者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "rule_modifiers": {
                "attack_roll:outgoing:marked": {
                    "stat": "attack_roll",
                    "scope": "outgoing",
                    "operation": "advantage",
                    "source": "标记优势",
                }
            }
        },
    )
    target = Combatant(
        id="elusive-target",
        entity_type="character",
        display_name="飘忽不定者",
        hp=20,
        max_hp=20,
        conditions=["倒地"],
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "kind": "suppress_attack_advantage",
                            "applies_when": "not_incapacitated",
                        }
                    ]
                }
            }
        },
    )

    advantage, disadvantage = CombatEngineService._feature_attack_roll_contexts(
        actor, target
    )
    assert advantage == []
    assert disadvantage == []
    mode, has_advantage, has_disadvantage, _ = PlayerRoomService._condition_attack_context(
        actor,
        target,
        distance_ft=5,
    )
    assert mode == "normal"
    assert has_advantage is False
    assert has_disadvantage is False

    target.conditions = ["倒地", "震慑"]
    mode, has_advantage, has_disadvantage, _ = PlayerRoomService._condition_attack_context(
        actor,
        target,
        distance_ft=5,
    )
    assert mode == "advantage"
    assert has_advantage is True
    assert has_disadvantage is False


def test_player_attack_context_matches_dm_for_invisible_and_unconscious_targets() -> None:
    actor = Combatant(
        id="player-attack-context-actor",
        entity_type="character",
        display_name="玩家攻击者",
        hp=20,
        max_hp=20,
    )
    invisible_target = Combatant(
        id="player-attack-context-invisible",
        entity_type="monster",
        display_name="隐形目标",
        hp=20,
        max_hp=20,
        conditions=["隐形"],
    )
    mode, has_advantage, has_disadvantage, automatic_critical = (
        PlayerRoomService._condition_attack_context(
            actor,
            invisible_target,
            distance_ft=5,
        )
    )
    assert mode == "disadvantage"
    assert has_advantage is False
    assert has_disadvantage is True
    assert automatic_critical is False

    unconscious_target = Combatant(
        id="player-attack-context-unconscious",
        entity_type="monster",
        display_name="昏迷目标",
        hp=0,
        max_hp=20,
        conditions=["昏迷"],
    )
    mode, has_advantage, has_disadvantage, automatic_critical = (
        PlayerRoomService._condition_attack_context(
            actor,
            unconscious_target,
            distance_ft=5,
        )
    )
    assert mode == "advantage"
    assert has_advantage is True
    assert has_disadvantage is False
    assert automatic_critical is True


def test_event_predicate_feature_modifier_does_not_grant_passive_advantage() -> None:
    actor = Combatant(
        id="studied-attacks",
        entity_type="character",
        display_name="观察者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "rule_modifiers": {
                "attack_roll:outgoing::studied": {
                    "stat": "attack_roll",
                    "scope": "outgoing",
                    "operation": "advantage",
                    "source": "究明攻击",
                    "applies_when": "next_attack_against_same_target_after_miss",
                }
            }
        },
    )
    target = Combatant(
        id="target",
        entity_type="monster",
        display_name="目标",
        hp=20,
        max_hp=20,
    )

    advantage, disadvantage = CombatEngineService._feature_attack_roll_contexts(
        actor, target
    )

    assert advantage == []
    assert disadvantage == []


def test_compiled_evasion_contract_is_consumed_by_save_damage_resolution() -> None:
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "反射闪避",
                "kind": "class_feature",
                "class_name": "游荡者",
                "class_level": 7,
                "runtime": {},
            }
        ],
        class_levels={"游荡者": 7},
        total_level=7,
    )
    evasion = next(
        defense
        for defense in registry["combat_start"]["defenses"]
        if defense["kind"] == "evasion"
    )
    assert evasion["runtime_execution"]["consumer"] == (
        "saving_throw_damage_resolution"
    )

    target = Combatant(
        id="evasion-runtime",
        entity_type="character",
        display_name="反射闪避者",
        hp=30,
        max_hp=30,
        snapshot_json={
            "feature_runtime": registry,
            # Combat creation performs this deterministic projection from the
            # typed defense. Build the same snapshot boundary here so this
            # regression remains focused on the domain contract and consumer.
            "advanced_defenses": {"evasion": evasion["kind"] == "evasion"},
        },
    )

    succeeded = CombatEngineService._resolve_save_defenses(
        target,
        dc=15,
        ability="dexterity",
        roll_total=17,
        roll_totals=None,
        damage_on_success=10,
        damage_on_failure=20,
        is_magical=True,
        use_legendary_resistance=False,
        use_feature_reroll=False,
        consume=False,
    )
    failed = CombatEngineService._resolve_save_defenses(
        target,
        dc=15,
        ability="dexterity",
        roll_total=8,
        roll_totals=None,
        damage_on_success=10,
        damage_on_failure=21,
        is_magical=True,
        use_legendary_resistance=False,
        use_feature_reroll=False,
        consume=False,
    )

    assert succeeded["damage"] == 0
    assert failed["damage"] == 10
    assert succeeded["applied_defenses"] == ["evasion"]
    assert failed["applied_defenses"] == ["evasion"]


def test_evasion_requires_half_damage_save_and_non_incapacitated_state() -> None:
    def resolve(*, conditions: list[str], damage_on_success: int) -> dict[str, object]:
        target = Combatant(
            id="evasion-boundary",
            entity_type="character",
            display_name="反射闪避边界",
            hp=30,
            max_hp=30,
            conditions=conditions,
            snapshot_json={"advanced_defenses": {"evasion": True}},
        )
        return CombatEngineService._resolve_save_defenses(
            target,
            dc=15,
            ability="dexterity",
            roll_total=8,
            roll_totals=None,
            damage_on_success=damage_on_success,
            damage_on_failure=20,
            is_magical=True,
            use_legendary_resistance=False,
            use_feature_reroll=False,
            consume=False,
        )

    full_damage_save = resolve(conditions=[], damage_on_success=0)
    incapacitated = resolve(conditions=["震慑"], damage_on_success=10)

    assert full_damage_save["damage"] == 20
    assert full_damage_save["applied_defenses"] == []
    assert incapacitated["damage"] == 20
    assert "evasion" not in incapacitated["applied_defenses"]
    assert "condition_auto_fail_strength_dex_save" in incapacitated["applied_defenses"]
