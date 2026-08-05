from __future__ import annotations

from types import SimpleNamespace

import pytest

from dnd_dm_assistant.api.schemas import PlayerRollPromptCommand, PlayerRollResolutionCommand
from dnd_dm_assistant.domain.feature_runtime import compile_feature_runtime_registry
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import CombatAction, Combatant, CombatEffect
from dnd_dm_assistant.infrastructure.database.player_room_service import PlayerRoomService


def _jack_of_all_trades_check_action(*, proficient: bool | None = None) -> CombatAction:
    request = {
        "resolution_type": "ability_check",
        "dc": 12,
        "ability": "dexterity",
        "action_name": "翻过矮墙",
    }
    if proficient is not None:
        request["ability_check_proficient"] = proficient
    return CombatAction(
        id=f"jack-check-{proficient}",
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["jack-checker"],
        request_json=request,
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待属性检定",
        idempotency_key=f"jack-check-{proficient}",
    )


def _jack_of_all_trades_target(*, proficiency_bonus: int | None = 5) -> Combatant:
    snapshot = {
        "rule_modifiers": {
            "ability_check:self::jack": {
                "id": "jack_of_all_trades:ability_check",
                "stat": "ability_check",
                "scope": "self",
                "operation": "add",
                "value_source": "half_proficiency_bonus",
                "applies_when": "ability_check_without_proficiency",
                "source": "万事通",
            }
        },
        "feature_runtime": {
            "progression": (
                {"proficiency_bonus": proficiency_bonus}
                if proficiency_bonus is not None
                else {}
            )
        },
    }
    return Combatant(
        id="jack-checker",
        entity_type="character",
        display_name="万事通检定者",
        hp=20,
        max_hp=20,
        snapshot_json=snapshot,
    )


def test_jack_of_all_trades_adds_half_proficiency_only_when_explicitly_unproficient() -> None:
    action = _jack_of_all_trades_check_action(proficient=False)
    resolved = CombatEngineService._resolve_player_roll(
        action,
        _jack_of_all_trades_target(),
        PlayerRollResolutionCommand(action_version=1, roll_total=10),
    )

    assert resolved["roll_total"] == 12
    assert resolved["success"] is True
    assert resolved["applied_defenses"] == ["feature:万事通半熟练加值"]


def test_jack_of_all_trades_does_not_apply_to_proficient_or_unknown_checks() -> None:
    proficient = CombatEngineService._resolve_player_roll(
        _jack_of_all_trades_check_action(proficient=True),
        _jack_of_all_trades_target(),
        PlayerRollResolutionCommand(action_version=1, roll_total=10),
    )
    assert proficient["roll_total"] == 10
    assert proficient["applied_defenses"] == []

    with pytest.raises(ValueError, match="明确说明.*熟练加值"):
        CombatEngineService._resolve_player_roll(
            _jack_of_all_trades_check_action(),
            _jack_of_all_trades_target(),
            PlayerRollResolutionCommand(action_version=1, roll_total=10),
        )


def test_jack_of_all_trades_requires_authoritative_proficiency_bonus() -> None:
    with pytest.raises(ValueError, match="缺少权威熟练加值"):
        CombatEngineService._resolve_player_roll(
            _jack_of_all_trades_check_action(proficient=False),
            _jack_of_all_trades_target(proficiency_bonus=None),
            PlayerRollResolutionCommand(action_version=1, roll_total=10),
        )


def test_jack_of_all_trades_prompt_field_is_only_for_ability_checks() -> None:
    with pytest.raises(ValueError, match="only valid for ability checks"):
        PlayerRollPromptCommand(
            actor_combatant_id="actor",
            actor_version=1,
            target_combatant_id="target",
            target_version=1,
            action_name="检定",
            resolution_type="skill_check",
            skill="隐匿",
            dc=12,
            ability_check_proficient=False,
        )


@pytest.mark.parametrize(
    ("resolution_type", "request_fields"),
    [
        ("saving_throw", {"ability": "wisdom"}),
        ("ability_check", {"ability": "strength"}),
        ("skill_check", {"skill": "运动"}),
    ],
)
def test_bardic_inspiration_is_added_after_roll_selection_and_consumed_once(
    resolution_type: str,
    request_fields: dict[str, str],
) -> None:
    action = CombatAction(
        id=f"bardic-{resolution_type}",
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=[f"bardic-target-{resolution_type}"],
        request_json={
            "resolution_type": resolution_type,
            "dc": 15,
            "action_name": "关键一掷",
            "damage_on_failure": 0,
            **request_fields,
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待玩家骰",
        idempotency_key=f"bardic-{resolution_type}",
    )
    target = Combatant(
        id=f"bardic-target-{resolution_type}",
        entity_type="character",
        display_name="受激励者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "feature_dice": {
                "bardic_inspiration_die": {
                    "source": "吟游诗人激励",
                    "value": "D6",
                    "target_combatant_id": f"bardic-target-{resolution_type}",
                    "available": True,
                }
            }
        },
    )
    command = PlayerRollResolutionCommand(
        action_version=1,
        roll_total=10,
        bardic_inspiration_total=5,
    )

    preview = CombatEngineService._resolve_player_roll(action, target, command)
    assert preview["roll_total"] == 15
    assert preview["success"] is True
    assert preview["feature_dice_consumed"]["consumed"] is False
    assert target.snapshot_json["feature_dice"]["bardic_inspiration_die"]["available"] is True

    confirmed = CombatEngineService._resolve_player_roll(
        action,
        target,
        command,
        consume_defenses=True,
    )
    assert confirmed["roll_total"] == 15
    assert confirmed["success"] is True
    assert confirmed["feature_dice_consumed"] == {
        "die_key": "bardic_inspiration_die",
        "source": "吟游诗人激励",
        "die": "D6",
        "value": 5,
        "sides": 6,
        "consumed_for_action_id": action.id,
    }
    assert target.snapshot_json["feature_dice"]["bardic_inspiration_die"]["available"] is False

    with pytest.raises(ValueError, match="已被其他操作消费"):
        CombatEngineService._resolve_player_roll(action, target, command)


def test_bardic_inspiration_validates_die_range_and_rejects_reroll_stacking() -> None:
    action = CombatAction(
        id="bardic-validation",
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["bardic-validation-target"],
        request_json={
            "resolution_type": "saving_throw",
            "dc": 15,
            "ability": "wisdom",
            "action_name": "检定",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待玩家骰",
        idempotency_key="bardic-validation",
    )
    target = Combatant(
        id="bardic-validation-target",
        entity_type="character",
        display_name="激励骰校验",
        hp=20,
        max_hp=20,
        snapshot_json={
            "feature_dice": {
                "bardic_inspiration_die": {
                    "source": "吟游诗人激励",
                    "value": "D6",
                    "available": True,
                }
            }
        },
    )
    with pytest.raises(ValueError, match="1–6"):
        CombatEngineService._resolve_player_roll(
            action,
            target,
            PlayerRollResolutionCommand(
                action_version=1,
                roll_total=10,
                bardic_inspiration_total=7,
            ),
        )
    with pytest.raises(ValueError, match="不能与职业特性重掷"):
        CombatEngineService._resolve_player_roll(
            action,
            target,
            PlayerRollResolutionCommand(
                action_version=1,
                roll_total=10,
                bardic_inspiration_total=4,
                use_feature_reroll=True,
            ),
        )


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


def test_rage_activity_keeps_effect_alive_only_after_explicit_activity() -> None:
    target = Combatant(
        id="rage-lifecycle",
        entity_type="character",
        display_name="狂暴生命周期",
        conditions=["raging"],
        snapshot_json={
            "rage_activity": {
                "effect_id": "rage-effect",
                "attacked": False,
                "damaged": False,
            }
        },
    )
    effect = CombatEffect(id="rage-effect")
    assert CombatEngineService._rage_activity_should_end(target, effect) is True
    assert CombatEngineService._mark_rage_activity(target, attacked=True) is True
    assert CombatEngineService._rage_activity_should_end(target, effect) is False
    assert CombatEngineService._reset_rage_activity(target, effect) is True
    assert CombatEngineService._rage_activity_should_end(target, effect) is True


def test_rage_activity_counts_only_attacks_against_hostile_targets() -> None:
    raging_character = Combatant(
        id="raging-character",
        entity_type="character",
        display_name="狂暴者",
        conditions=["raging"],
    )
    ally = Combatant(
        id="ally",
        entity_type="companion",
        display_name="友军召唤物",
        snapshot_json={"disposition": "ally"},
    )
    hostile = Combatant(
        id="hostile",
        entity_type="monster",
        display_name="敌人",
    )
    assert CombatEngineService._rage_attack_counts_as_activity(raging_character, ally) is False
    assert CombatEngineService._rage_attack_counts_as_activity(raging_character, hostile) is True
    assert (
        CombatEngineService._rage_attack_counts_as_activity(
            raging_character,
            raging_character,
        )
        is False
    )


def test_divine_smite_rider_requires_melee_hit_and_selected_slot() -> None:
    actor = Combatant(
        id="paladin",
        entity_type="character",
        snapshot_json={
            "feature_runtime": {
                "attack_riders": [
                    {
                        "id": "divine_smite:bonus_damage",
                        "value": "2d8",
                        "damage_type": "radiant",
                        "applies_when": "divine_smite_selected_after_melee_weapon_or_unarmed_hit",
                        "minimum_spell_slot_level": 1,
                    }
                ]
            }
        },
    )
    target = Combatant(id="undead", entity_type="monster")
    melee = {
        "name": "长剑",
        "description": "近战武器攻击",
        "damage": "1d8+力量 挥砍",
        "is_weapon_attack": True,
    }
    riders = PlayerRoomService._eligible_attack_riders(
        actor,
        melee,
        target,
        special_inputs={
            "attack_rider_eligibility": {"divine_smite:bonus_damage": True},
            "divine_smite_slot_level": 3,
            "attack_rider_totals": {"divine_smite:bonus_damage": 20},
        },
        critical_hit=False,
        used_this_turn=set(),
    )
    assert riders[0]["expression"] == "4d8"
    assert riders[0]["total"] == 20
    assert riders[0]["resource_key"] == "spell_slots_3"
    assert riders[0]["selected_spell_slot_level"] == 3

    with pytest.raises(ValueError, match="圣武斩法术位环阶"):
        PlayerRoomService._eligible_attack_riders(
            actor,
            melee,
            target,
            special_inputs={
                "attack_rider_eligibility": {"divine_smite:bonus_damage": True},
                "divine_smite_slot_level": 6,
                "attack_rider_totals": {"divine_smite:bonus_damage": 20},
            },
            critical_hit=False,
            used_this_turn=set(),
        )


def test_indomitable_might_floors_strength_check_at_strength_score() -> None:
    action = CombatAction(
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["indomitable-checker"],
        request_json={
            "resolution_type": "ability_check",
            "dc": 17,
            "ability": "strength",
            "action_name": "掰断铁栅栏",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待力量属性检定",
        idempotency_key="indomitable-might-check",
    )
    target = Combatant(
        id="indomitable-checker",
        entity_type="character",
        display_name="不屈勇武检定者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "ability_scores": {"strength": 18},
            "rule_modifiers": {
                "indomitable_might:strength_check_floor": {
                    "stat": "ability_check",
                    "scope": "self",
                    "ability": "strength",
                    "operation": "set_minimum_total_from_ability",
                    "applies_when": "strength_ability_check_total_below_strength_score",
                    "source": "不屈勇武",
                }
            },
        },
    )

    resolved = CombatEngineService._resolve_player_roll(
        action,
        target,
        PlayerRollResolutionCommand(action_version=1, roll_total=5),
    )

    assert resolved["roll_total"] == 18
    assert resolved["success"] is True
    assert resolved["applied_defenses"] == ["feature:不屈勇武最低力量检定总值"]

    non_strength_action = CombatAction(
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["indomitable-checker"],
        request_json={
            "resolution_type": "ability_check",
            "dc": 17,
            "ability": "dexterity",
            "action_name": "翻越栅栏",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待敏捷属性检定",
        idempotency_key="indomitable-might-dexterity-check",
    )
    unchanged = CombatEngineService._resolve_player_roll(
        non_strength_action,
        target,
        PlayerRollResolutionCommand(action_version=1, roll_total=5),
    )
    assert unchanged["roll_total"] == 5
    assert unchanged["success"] is False


def test_poisoned_check_disadvantage_cancels_feature_advantage() -> None:
    action = CombatAction(
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["poisoned-checker"],
        request_json={
            "resolution_type": "skill_check",
            "dc": 15,
            "skill": "隐匿",
            "action_name": "潜行",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待技能检定",
        idempotency_key="poisoned-skill-check",
    )
    target = Combatant(
        id="poisoned-checker",
        entity_type="character",
        display_name="中毒检定者",
        hp=20,
        max_hp=20,
        conditions=["中毒"],
        snapshot_json={
            "rule_modifiers": {
                "skill_check:self:stealth": {
                    "stat": "skill_check",
                    "scope": "self",
                    "operation": "advantage",
                    "source": "可靠协助",
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

    assert resolved["roll_total"] == 5
    assert resolved["success"] is False
    assert resolved["applied_defenses"] == [
        "ability_check_advantage_disadvantage_cancelled",
        "condition:poisoned_disadvantage_check",
    ]


def test_frightened_check_disadvantage_requires_visible_fear_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = CombatAction(
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["frightened-checker"],
        request_json={
            "resolution_type": "skill_check",
            "dc": 15,
            "skill": "察觉",
            "action_name": "观察环境",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待察觉检定",
        idempotency_key="frightened-skill-check",
    )
    target = Combatant(
        id="frightened-checker",
        entity_type="character",
        display_name="恐慌检定者",
        hp=20,
        max_hp=20,
        conditions=["恐慌"],
    )
    monkeypatch.setattr(
        CombatEngineService,
        "_frightened_source_visibility",
        lambda *args: True,
    )

    visible = CombatEngineService._resolve_player_roll(
        action,
        target,
        PlayerRollResolutionCommand(
            action_version=1,
            roll_total=5,
            roll_totals=[5, 18],
        ),
        session=object(),
        combat=object(),
    )
    assert visible["roll_total"] == 5
    assert visible["success"] is False
    assert visible["applied_defenses"] == [
        "condition:frightened_disadvantage_check"
    ]

    monkeypatch.setattr(
        CombatEngineService,
        "_frightened_source_visibility",
        lambda *args: False,
    )
    hidden = CombatEngineService._resolve_player_roll(
        action,
        target,
        PlayerRollResolutionCommand(
            action_version=1,
            roll_total=18,
            roll_totals=[18, 5],
        ),
        session=object(),
        combat=object(),
    )
    assert hidden["roll_total"] == 18
    assert hidden["success"] is True
    assert hidden["applied_defenses"] == []


def test_blinded_explicit_sight_check_fails_without_inventing_visual_context() -> None:
    action = CombatAction(
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["blinded-checker"],
        request_json={
            "resolution_type": "skill_check",
            "dc": 15,
            "skill": "察觉",
            "requires_sight": True,
            "action_name": "读取唇语",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待视觉检定",
        idempotency_key="blinded-sight-check",
    )
    target = Combatant(
        id="blinded-checker",
        entity_type="character",
        display_name="目盲检定者",
        hp=20,
        max_hp=20,
        conditions=["目盲"],
    )

    sight_check = CombatEngineService._resolve_player_roll(
        action,
        target,
        PlayerRollResolutionCommand(action_version=1, roll_total=20),
    )
    assert sight_check["roll_total"] == -100_000
    assert sight_check["success"] is False
    assert sight_check["applied_defenses"] == ["condition_auto_fail_sight_check"]

    non_sight_action = CombatAction(
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["blinded-checker"],
        request_json={
            "resolution_type": "skill_check",
            "dc": 15,
            "skill": "察觉",
            "requires_sight": False,
            "action_name": "听见动静",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待非视觉检定",
        idempotency_key="blinded-non-sight-check",
    )
    non_sight = CombatEngineService._resolve_player_roll(
        non_sight_action,
        target,
        PlayerRollResolutionCommand(action_version=1, roll_total=20),
    )
    assert non_sight["roll_total"] == 20
    assert non_sight["success"] is True
    assert non_sight["applied_defenses"] == []


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


def test_disciplined_survivor_uses_focus_for_failed_save_reroll() -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.character = SimpleNamespace(
                resources={"focus": {"current": 1, "max": 4}},
                version=1,
                updated_at=None,
            )

        def get(self, _model: object, _entity_id: str) -> object:
            return self.character

    target = Combatant(
        id="disciplined-survivor",
        entity_type="character",
        entity_id="monk-character",
        display_name="圆融自在者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "feature_runtime": {
                "actions": {
                    "disciplined_survivor": {
                        "kind": "feature_action",
                        "name": "圆融自在",
                        "resolution_kind": "saving_throw_reroll",
                        "activation_window": "after_failed_saving_throw",
                        "resource_key": "focus",
                        "resource_cost": 1,
                    }
                },
                "resources": {"focus": {"current": 1, "max": 4}},
            }
        },
    )

    result = CombatEngineService._resolve_save_defenses(
        target,
        dc=15,
        ability="wisdom",
        roll_total=5,
        roll_totals=[5, 18],
        damage_on_success=0,
        damage_on_failure=10,
        is_magical=False,
        use_legendary_resistance=False,
        use_feature_reroll=True,
        consume=True,
        session=FakeSession(),
    )

    assert result["success"] is True
    assert result["effective_roll_total"] == 18
    assert result["feature_reroll_consumed"] == {
        "feature_id": "disciplined_survivor",
        "resource": "focus",
        "before": 1,
        "after": 0,
    }


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


def test_studied_attacks_contract_is_runtime_executable() -> None:
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "究明攻击",
                "kind": "class_feature",
                "class_name": "游荡者",
                "class_level": 13,
                "runtime": {},
            }
        ],
        class_levels={"游荡者": 13},
        total_level=13,
    )
    modifier = next(
        item
        for item in registry["combat_start"]["modifiers"]
        if item["id"] == "studied_attacks:next_attack_advantage"
    )
    assert modifier["automation_status"] == "full"
    assert modifier["requires_dm_adjudication"] is False
    assert modifier["runtime_execution"]["producer"] == "attack_miss_event"


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


def test_saving_throw_proficiency_is_applied_once_on_automatic_player_action_path() -> None:
    target = Combatant(
        id="proficient-save-target",
        entity_type="character",
        display_name="圆融自在角色",
        hp=20,
        max_hp=20,
        snapshot_json={
            "ability_scores": {"wisdom": 10, "charisma": 10, "dexterity": 10},
            "feature_runtime": {"progression": {"proficiency_bonus": 4}},
            "rule_modifiers": {
                "saving_throw:self::slippery": {
                    "stat": "saving_throw",
                    "scope": "self",
                    "abilities": ["wisdom", "charisma"],
                    "operation": "grant_proficiency",
                },
                "saving_throw:self::disciplined": {
                    "stat": "saving_throw",
                    "scope": "self",
                    "abilities": "all",
                    "operation": "grant_proficiency",
                },
            },
        },
    )

    wisdom_bonus = PlayerRoomService._rule_modifier(
        target, "saving_throw", scope="self", skill="wisdom"
    )[0]
    dexterity_bonus = PlayerRoomService._rule_modifier(
        target, "saving_throw", scope="self", skill="dexterity"
    )[0]

    assert wisdom_bonus == 4
    assert dexterity_bonus == 4


def test_saving_throw_proficiency_contract_is_full_and_explicit() -> None:
    registry = compile_feature_runtime_registry(
        [
            {
                "name": "圆滑心智",
                "class_name": "游荡者",
                "class_level": 15,
                "kind": "feature",
            },
            {
                "name": "圆融自在",
                "class_name": "游侠",
                "class_level": 18,
                "kind": "feature",
            },
        ],
        total_level=18,
        scalings={},
    )
    grants = {
        item["id"]: item
        for item in registry["combat_start"]["modifiers"]
        if item["operation"] == "grant_proficiency"
    }

    assert grants["slippery_mind:saving_throw_proficiencies"]["automation_status"] == "full"
    assert grants["slippery_mind:saving_throw_proficiencies"]["requires_dm_adjudication"] is False
    assert grants["disciplined_survivor:all_save_proficiency"]["automation_status"] == "full"
    assert grants["disciplined_survivor:all_save_proficiency"]["requires_dm_adjudication"] is False


def test_paladin_protection_aura_adds_charisma_modifier_to_self_save() -> None:
    paladin = Combatant(
        id="protection-aura-paladin",
        entity_type="character",
        display_name="守护灵光圣武士",
        hp=20,
        max_hp=20,
        snapshot_json={
            "ability_scores": {"charisma": 16},
            "rule_modifiers": {
                "saving_throw:self_and_allies_within_10ft::aura": {
                    "stat": "saving_throw",
                    "scope": "self_and_allies_within_10ft",
                    "operation": "add",
                    "value_source": "charisma_modifier",
                    "minimum": 1,
                    "applies_when": "within_aura_of_protection",
                }
            },
        },
    )
    weak_paladin = Combatant(
        id="weak-protection-aura-paladin",
        entity_type="character",
        display_name="低魅力圣武士",
        hp=20,
        max_hp=20,
        snapshot_json={
            "ability_scores": {"charisma": 8},
            "rule_modifiers": paladin.snapshot_json["rule_modifiers"],
        },
    )

    assert PlayerRoomService._rule_modifier(
        paladin, "saving_throw", scope="self", skill="wisdom"
    )[0] == 3
    assert PlayerRoomService._rule_modifier(
        weak_paladin, "saving_throw", scope="self", skill="wisdom"
    )[0] == 1
