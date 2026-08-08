from __future__ import annotations

from types import SimpleNamespace

import pytest

from dnd_dm_assistant.api.schemas import (
    CombatActionCommand,
    PlayerRollPromptCommand,
    PlayerRollResolutionCommand,
)
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


def test_concentration_damage_immunity_is_data_driven_by_effect_name() -> None:
    target = Combatant(
        id="marked-hunter",
        entity_type="character",
        display_name="猎人",
        hp=20,
        max_hp=20,
        concentration={"name": "猎人印记", "effect_id": "mark-1"},
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "kind": "concentration_damage_immunity",
                            "applies_when": "concentrating_on_hunters_mark",
                            "effect_names": ["猎人印记", "hunter's mark"],
                        }
                    ]
                }
            }
        },
    )

    assert CombatEngineService._concentration_damage_immunity(target) is True
    target.concentration = {"name": "专注法术", "effect_id": "spell-1"}
    assert CombatEngineService._concentration_damage_immunity(target) is False


def test_typed_feature_damage_resistance_is_consumed_without_feature_name_branch() -> None:
    target = Combatant(
        id="avatar",
        entity_type="character",
        display_name="战争化身",
        hp=20,
        max_hp=20,
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "kind": "damage_resistance",
                            "damage_types": ["bludgeoning"],
                            "applies_when": "always",
                        }
                    ]
                }
            }
        },
    )

    resistances, _vulnerabilities, _immunities, applied, unresolved = (
        CombatEngineService._damage_defenses(
            target,
            SimpleNamespace(damage_tags=[]),
            ["bludgeoning"],
        )
    )
    assert "bludgeoning" in resistances
    assert applied
    assert unresolved == []


def test_psychic_reflection_returns_equal_adjusted_damage_to_source() -> None:
    source = Combatant(
        id="psychic-source",
        entity_type="character",
        display_name="心灵攻击者",
        hp=30,
        max_hp=30,
        temporary_hp=0,
        version=1,
        snapshot_json={},
    )
    target = Combatant(
        id="thought-shield-target",
        entity_type="character",
        display_name="思维之盾目标",
        hp=20,
        max_hp=20,
        temporary_hp=0,
        version=1,
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "kind": "damage_resistance",
                            "damage_types": ["psychic"],
                            "applies_when": "always",
                        },
                        {
                            "kind": "damage_reflection",
                            "damage_types": ["psychic"],
                            "reflection": "equal_adjusted_damage_to_source",
                        },
                    ]
                }
            }
        },
    )

    class _Rows:
        @staticmethod
        def all() -> list[object]:
            return []

    class _Session:
        def get(self, model: object, identifier: str) -> Combatant | None:
            return {source.id: source, target.id: target}.get(identifier)

        @staticmethod
        def scalars(*_args: object, **_kwargs: object) -> _Rows:
            return _Rows()

    command = CombatActionCommand(
        action_type="damage",
        target_combatant_id=target.id,
        target_version=1,
        actor_combatant_id=source.id,
        actor_version=1,
        amount=10,
        damage_type="psychic",
    )
    resolved = CombatEngineService._resolve(
        command,
        target,
        session=_Session(),  # type: ignore[arg-type]
        combat_id="combat",
    )

    assert resolved["result"]["adjusted_damage"] == 5
    assert resolved["result"]["psychic_reflection"]["adjusted_damage"] == 5
    assert source.hp == 25


def test_typed_damage_resistance_requires_every_declared_condition() -> None:
    target = Combatant(
        id="conditional-defense",
        entity_type="character",
        display_name="条件防御",
        hp=20,
        max_hp=20,
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "id": "test:conditional_resistance",
                            "kind": "damage_resistance",
                            "damage_types": ["slashing"],
                            "applies_when": "always",
                            "required_conditions": ["starry_form", "focused"],
                        }
                    ]
                }
            }
        },
    )

    before = CombatEngineService._damage_defenses(
        target,
        SimpleNamespace(damage_tags=[]),
        ["slashing"],
    )
    assert "slashing" not in before[0]

    target.conditions = ["starry_form"]
    partial = CombatEngineService._damage_defenses(
        target,
        SimpleNamespace(damage_tags=[]),
        ["slashing"],
    )
    assert "slashing" not in partial[0]

    target.conditions = ["starry_form", "focused"]
    active = CombatEngineService._damage_defenses(
        target,
        SimpleNamespace(damage_tags=[]),
        ["slashing"],
    )
    assert "slashing" in active[0]
    assert active[3] == ["test:conditional_resistance:resistance:slashing"]


def test_guarded_mind_psychic_resistance_is_consumed_by_damage_defense_resolver() -> None:
    target = Combatant(
        id="guarded-mind-defense",
        entity_type="character",
        display_name="意念守护者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "id": "guarded_mind:psychic_resistance",
                            "kind": "damage_resistance",
                            "damage_types": ["psychic"],
                            "applies_when": "always",
                        }
                    ]
                }
            }
        },
    )
    resistance = CombatEngineService._damage_defenses(
        target,
        SimpleNamespace(damage_tags=[]),
        ["psychic"],
    )
    assert "psychic" in resistance[0]
    assert resistance[3] == [
        "guarded_mind:psychic_resistance:resistance:psychic"
    ]


def test_typed_damage_resistance_fails_closed_for_invalid_condition_contract() -> None:
    target = Combatant(
        id="invalid-conditional-defense",
        entity_type="character",
        display_name="无效条件防御",
        hp=20,
        max_hp=20,
        conditions=["starry_form"],
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "kind": "damage_resistance",
                            "damage_types": ["slashing"],
                            "required_conditions": "starry_form",
                        }
                    ]
                }
            }
        },
    )

    resolved = CombatEngineService._damage_defenses(
        target,
        SimpleNamespace(damage_tags=[]),
        ["slashing"],
    )
    assert "slashing" not in resolved[0]


def test_required_conditions_gate_condition_immunity_at_shared_defense_boundary() -> None:
    target = Combatant(
        id="conditional-immunity",
        entity_type="character",
        display_name="条件免疫",
        hp=20,
        max_hp=20,
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "kind": "condition_immunity",
                            "condition": "charmed",
                            "applies_when": "always",
                            "required_conditions": ["focused"],
                        }
                    ]
                }
            }
        },
    )

    assert CombatEngineService._condition_is_immune(target, "charmed") is False
    target.conditions = ["focused"]
    assert CombatEngineService._condition_is_immune(target, "charmed") is True


def test_critical_threshold_block_uses_authoritative_natural_d20() -> None:
    actor = Combatant(
        id="champion",
        entity_type="character",
        display_name="勇士",
        snapshot_json={
            "rule_modifiers": {
                "test:critical_threshold": {
                    "id": "test:critical_threshold",
                    "stat": "attack_critical_threshold",
                    "operation": "set",
                    "scope": "outgoing",
                    "value": 19,
                    "applies_when": "always",
                }
            },
            "feature_runtime": {
                "combat_start": {
                    "modifiers": [
                        {
                            "id": "test:critical_threshold",
                            "stat": "attack_critical_threshold",
                            "operation": "set",
                            "scope": "outgoing",
                            "value": 19,
                            "applies_when": "always",
                        }
                    ]
                }
            }
        },
    )
    assert CombatEngineService._critical_attack_context(actor, attack_d20=19) == (
        "automatic_critical:feature_threshold"
    )
    assert CombatEngineService._critical_attack_context(actor, attack_d20=18) is None
    with pytest.raises(ValueError, match="天然 d20"):
        CombatEngineService._critical_attack_context(actor, attack_d20=None)
    command = CombatActionCommand(
        action_type="damage",
        target_combatant_id="target",
        target_version=1,
        actor_combatant_id="champion",
        actor_version=1,
        amount=1,
        damage_type="slashing",
        is_attack=True,
        attack_roll_total=19,
        attack_d20=19,
    )
    assert command.attack_d20 == 19


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
        damage_on_success=5,
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


def test_radiant_strikes_auto_selects_structured_weapon_attack_once_per_turn() -> None:
    actor = Combatant(
        id="radiant-paladin",
        entity_type="character",
        snapshot_json={
            "feature_runtime": {
                "attack_riders": [
                    {
                        "id": "radiant_strikes:bonus_damage",
                        "value": "1d8",
                        "damage_type": "radiant",
                        "applies_when": "radiant_strikes_eligible",
                        "frequency": "once_per_turn",
                    }
                ]
            }
        },
    )
    target = Combatant(id="radiant-target", entity_type="monster")
    weapon_attack = {
        "name": "长剑",
        "description": "近战武器攻击",
        "damage": "1d8+力量 挥砍",
        "is_weapon_attack": True,
    }

    riders = PlayerRoomService._eligible_attack_riders(
        actor,
        weapon_attack,
        target,
        special_inputs={
            "attack_rider_totals": {"radiant_strikes:bonus_damage": 6},
        },
        critical_hit=False,
        used_this_turn=set(),
    )
    assert len(riders) == 1
    assert riders[0]["rider_id"] == "radiant_strikes:bonus_damage"
    assert riders[0]["total"] == 6
    assert riders[0]["damage_type"] == "radiant"

    assert PlayerRoomService._eligible_attack_riders(
        actor,
        weapon_attack,
        target,
        special_inputs={
            "attack_rider_totals": {"radiant_strikes:bonus_damage": 6},
        },
        critical_hit=False,
        used_this_turn={"radiant_strikes:bonus_damage"},
    ) == []


def test_radiant_strikes_does_not_guess_non_attack_eligibility() -> None:
    actor = Combatant(
        id="radiant-paladin-no-attack",
        entity_type="character",
        snapshot_json={
            "feature_runtime": {
                "attack_riders": [
                    {
                        "id": "radiant_strikes:bonus_damage",
                        "value": "1d8",
                        "damage_type": "radiant",
                        "applies_when": "radiant_strikes_eligible",
                    }
                ]
            }
        },
    )
    target = Combatant(id="radiant-target-no-attack", entity_type="monster")
    assert PlayerRoomService._eligible_attack_riders(
        actor,
        {"name": "圣光祷告", "description": "一个动作"},
        target,
        special_inputs={
            "attack_rider_totals": {"radiant_strikes:bonus_damage": 8},
        },
        critical_hit=False,
        used_this_turn=set(),
    ) == []


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


def test_otherworldly_glamour_adds_wisdom_modifier_to_charisma_checks() -> None:
    action = CombatAction(
        id="glamour-check",
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["glamour-checker"],
        request_json={
            "resolution_type": "ability_check",
            "dc": 15,
            "ability": "charisma",
            "action_name": "游说守卫",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待魅力属性检定",
        idempotency_key="glamour-check",
    )
    target = Combatant(
        id="glamour-checker",
        entity_type="character",
        display_name="妖冶娴都检定者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "ability_scores": {"charisma": 14, "wisdom": 18},
            "rule_modifiers": {
                "glamour": {
                    "id": "otherworldly_glamour:charisma_check_bonus",
                    "stat": "ability_check",
                    "ability": "charisma",
                    "operation": "add",
                    "value_source": "wisdom_modifier",
                    "scope": "self",
                    "applies_when": "every_charisma_ability_check",
                    "source": "妖冶娴都",
                }
            },
        },
    )
    resolved = CombatEngineService._resolve_player_roll(
        action,
        target,
        PlayerRollResolutionCommand(action_version=1, roll_total=10),
    )
    assert resolved["roll_total"] == 14
    assert resolved["success"] is False
    assert resolved["applied_defenses"] == ["feature:妖冶娴都"]


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


def test_hunters_mark_target_binding_limits_attack_advantage_to_bound_target() -> None:
    actor = Combatant(
        id="marked-ranger",
        entity_type="character",
        display_name="猎人",
        hp=20,
        max_hp=20,
        snapshot_json={
            "current_hunters_mark_target_id": "marked-target",
            "rule_modifiers": {
                "precise_hunter:marked_target_advantage": {
                    "stat": "attack_roll",
                    "scope": "outgoing",
                    "operation": "advantage",
                    "source": "致命猎杀",
                    "applies_when": "target_is_current_hunters_mark",
                }
            },
        },
    )
    marked = Combatant(id="marked-target", entity_type="monster", hp=20, max_hp=20)
    other = Combatant(id="other-target", entity_type="monster", hp=20, max_hp=20)

    marked_advantage, _ = CombatEngineService._feature_attack_roll_contexts(
        actor, marked
    )
    other_advantage, _ = CombatEngineService._feature_attack_roll_contexts(actor, other)

    assert marked_advantage == ["致命猎杀"]
    assert other_advantage == []


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


def test_ranged_passive_condition_immunity_suppresses_but_does_not_delete_state() -> None:
    target = Combatant(
        id="generic-courage-source",
        entity_type="character",
        display_name="范围免疫来源",
        hp=20,
        max_hp=20,
        conditions=["frightened"],
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "condition": "frightened",
                            "ranged_passive": {
                                "range_group": "test_immunity",
                                "source_scope": "self",
                                "target_relation": "self_and_allies",
                                "range_ft": 10,
                                "source_forbidden_conditions": ["incapacitated"],
                                "effect_kind": "condition_immunity",
                            },
                        }
                    ]
                }
            }
        },
    )

    assert CombatEngineService._effective_condition_set(
        target, session=None, combat_id=None
    ) == set()
    assert target.conditions == ["frightened"]

    target.conditions = ["frightened", "stunned"]
    effective = CombatEngineService._effective_condition_set(
        target, session=None, combat_id=None
    )
    assert "frightened" in effective
    assert "stunned" in effective


def test_generic_ranged_passive_resolves_range_override_and_stacking_groups() -> None:
    target = Combatant(
        id="range-target",
        entity_type="character",
        display_name="范围目标",
        hp=20,
        max_hp=20,
        snapshot_json={
            "disposition": "ally",
            "grid_position": {"row": 0, "col": 5},
        },
    )
    source = Combatant(
        id="range-source",
        combat_id="combat",
        entity_type="character",
        display_name="范围来源",
        hp=20,
        max_hp=20,
        snapshot_json={
            "disposition": "ally",
            "ability_scores": {"charisma": 18},
            "grid_position": {"row": 0, "col": 0},
            "feature_runtime": {
                "combat_start": {
                    "modifiers": [
                        {
                            "stat": "saving_throw",
                            "operation": "add",
                            "value_source": "charisma_modifier",
                            "ranged_passive": {
                                "range_group": "expanded_group",
                                "stacking_group": "best_group",
                                "target_relation": "self_and_allies",
                                "range_ft": 10,
                                "effect_kind": "numeric_modifier",
                                "stacking": "best",
                            },
                        },
                        {
                            "stat": "saving_throw",
                            "operation": "add",
                            "value": 2,
                            "ranged_passive": {
                                "range_group": "expanded_group",
                                "stacking_group": "independent_group",
                                "target_relation": "self_and_allies",
                                "range_ft": 10,
                                "effect_kind": "numeric_modifier",
                                "stacking": "best",
                            },
                        },
                        {
                            "stat": "saving_throw",
                            "operation": "add",
                            "value": 99,
                            "ranged_passive": {
                                "range_group": "unrelated_group",
                                "stacking_group": "unrelated_group",
                                "target_relation": "self_and_allies",
                                "range_ft": 10,
                                "effect_kind": "numeric_modifier",
                                "stacking": "best",
                            },
                        },
                    ],
                    "defenses": [
                        {
                            "kind": "ranged_passive_range_override",
                            "applies_to": "range_group",
                            "target_range_group": "expanded_group",
                            "range_ft": 30,
                        }
                    ],
                }
            },
        },
    )

    class Rows:
        def all(self) -> list[Combatant]:
            return [source, target]

    class FakeSession:
        def get(self, _model: object, _entity_id: str) -> object:
            return SimpleNamespace(id="combat", scene_id="scene")

        def scalar(self, _query: object) -> object:
            return SimpleNamespace(cell_size_ft=5)

        def scalars(self, query: object) -> Rows:
            if "combat_effects" in str(query):
                return type("EmptyRows", (), {"all": lambda self: []})()
            return Rows()

    assert CombatEngineService._ranged_passive_numeric_modifier(
        target,
        stat="saving_throw",
        session=FakeSession(),
        combat_id="combat",
    ) == 6


def test_leading_evasion_applies_to_adjacent_ally_dexterity_save() -> None:
    source = Combatant(
        id="leading-evasion-source",
        combat_id="combat",
        entity_type="character",
        display_name="舞者",
        hp=20,
        max_hp=20,
        snapshot_json={
            "disposition": "ally",
            "grid_position": {"row": 0, "col": 0},
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "kind": "evasion",
                            "ranged_passive": {
                                "effect_kind": "evasion",
                                "target_relation": "self_and_allies",
                                "range_ft": 5,
                                "requires_grid_position_for_others": True,
                                "source_forbidden_conditions": ["incapacitated"],
                            },
                        }
                    ]
                }
            },
        },
    )
    target = Combatant(
        id="leading-evasion-ally",
        combat_id="combat",
        entity_type="character",
        display_name="邻近盟友",
        hp=20,
        max_hp=20,
        snapshot_json={"disposition": "ally", "grid_position": {"row": 0, "col": 1}},
    )

    class Rows:
        def all(self) -> list[Combatant]:
            return [source, target]

    class FakeSession:
        def get(self, model: object, _entity_id: str) -> object:
            if model is Combatant:
                return source if _entity_id == source.id else target
            return SimpleNamespace(id="combat", scene_id="scene")

        def scalar(self, _query: object) -> object:
            return SimpleNamespace(cell_size_ft=5)

        def scalars(self, query: object) -> Rows:
            if "combat_effects" in str(query):
                return type("EmptyRows", (), {"all": lambda self: []})()
            return Rows()

    passives = CombatEngineService._ranged_passive_effects(
        target,
        effect_kind="evasion",
        session=FakeSession(),
        combat_id="combat",
    )
    assert len(passives) == 1
    resolved = CombatEngineService._resolve_save_defenses(
        target,
        dc=15,
        ability="dexterity",
        roll_total=10,
        roll_totals=[10],
        damage_on_success=5,
        damage_on_failure=10,
        is_magical=False,
        use_legendary_resistance=False,
        use_feature_reroll=False,
        consume=False,
        session=FakeSession(),
        combat=SimpleNamespace(id="combat"),
    )

    assert resolved["success"] is False
    assert resolved["damage"] == 5
    assert "evasion" in resolved["applied_defenses"]


def test_turn_start_feature_state_producer_grants_heroic_inspiration_once() -> None:
    actor = Combatant(
        id="heroic-warrior",
        combat_id="combat",
        entity_type="character",
        display_name="勇士",
        hp=20,
        max_hp=20,
        speed_ft=30,
        snapshot_json={
            "feature_runtime": {
                "triggers": [
                    {
                        "event": "turn_start",
                        "effects": [
                            {
                                "kind": "grant_feature_state_if_missing",
                                "state_key": "heroic_inspiration",
                            }
                        ],
                    }
                ]
            }
        },
    )

    CombatEngineService._refresh_new_turn_resources(actor, round_number=1)
    assert actor.snapshot_json["feature_states"] == {"heroic_inspiration": True}
    actor.snapshot_json["feature_states"]["heroic_inspiration"] = False
    CombatEngineService._refresh_new_turn_resources(actor, round_number=1)
    assert actor.snapshot_json["feature_states"]["heroic_inspiration"] is True


def test_ranged_passive_damage_resistance_is_consumed_by_damage_resolver() -> None:
    target = Combatant(
        id="warded-ally",
        combat_id="combat",
        entity_type="character",
        display_name="灵光盟友",
        hp=20,
        max_hp=20,
        snapshot_json={
            "disposition": "ally",
            "grid_position": {"row": 0, "col": 1},
        },
    )
    source = Combatant(
        id="warding-paladin",
        combat_id="combat",
        entity_type="character",
        display_name="守御圣武士",
        hp=20,
        max_hp=20,
        snapshot_json={
            "disposition": "ally",
            "grid_position": {"row": 0, "col": 0},
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "id": "fixture:warding",
                            "kind": "damage_resistance",
                            "damage_types": ["psychic"],
                            "ranged_passive": {
                                "range_group": "warding",
                                "target_relation": "self_and_allies",
                                "range_ft": 10,
                                "effect_kind": "damage_resistance",
                            },
                        }
                    ]
                }
            },
        },
    )

    class Rows:
        def all(self) -> list[Combatant]:
            return [source, target]

    class FakeSession:
        def get(self, _model: object, _entity_id: str) -> object:
            return SimpleNamespace(id="combat", scene_id="scene")

        def scalar(self, _query: object) -> object:
            return SimpleNamespace(cell_size_ft=5)

        def scalars(self, _query: object) -> Rows:
            return Rows()

    resistances, _vulnerabilities, _immunities, applied, unresolved = (
        CombatEngineService._damage_defenses(
            target,
            SimpleNamespace(damage_tags=[]),
            ["psychic"],
            session=FakeSession(),
            combat_id="combat",
        )
    )
    assert "psychic" in resistances
    assert any("ranged_resistance" in value for value in applied)
    assert unresolved == []


def test_magical_spell_resistance_defense_is_data_driven() -> None:
    target = Combatant(
        id="spell-resistant",
        entity_type="character",
        display_name="法术抗性",
        hp=20,
        max_hp=20,
        snapshot_json={
            "feature_runtime": {
                "combat_start": {
                    "defenses": [
                        {
                            "id": "fixture:magic-save",
                            "kind": "saving_throw_advantage",
                            "applies_when": "magical",
                            "source": "fixture magic resistance",
                        },
                        {
                            "id": "fixture:magic-damage",
                            "kind": "damage_resistance",
                            "damage_types": ["fire"],
                            "applies_when": "magical",
                        },
                    ]
                }
            }
        },
    )
    save = CombatEngineService._resolve_save_defenses(
        target,
        dc=10,
        ability="wisdom",
        roll_total=5,
        roll_totals=[5, 15],
        damage_on_success=0,
        damage_on_failure=0,
        is_magical=True,
        use_legendary_resistance=False,
        use_feature_reroll=False,
        consume=False,
    )
    assert save["success"] is True
    assert "feature:fixture magic resistance" in save["applied_defenses"]
    resistances, _vulnerabilities, _immunities, applied, unresolved = (
        CombatEngineService._damage_defenses(
            target,
            SimpleNamespace(damage_tags=[], is_magical=True),
            ["fire"],
        )
    )
    assert "fire" in resistances
    assert any("fixture:magic-damage" in value for value in applied)
    assert unresolved == []


def test_tactical_mind_uses_generic_failure_recovery_and_consumes_only_on_success() -> None:
    action = CombatAction(
        id="tactical-check",
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["tactical-fighter"],
        request_json={
            "resolution_type": "ability_check",
            "ability": "strength",
            "ability_check_proficient": True,
            "dc": 15,
            "action_name": "战术检定",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待检定",
        idempotency_key="tactical-check",
    )

    def target() -> Combatant:
        return Combatant(
            id="tactical-fighter",
            entity_type="character",
            entity_id="fighter-character",
            display_name="战术战士",
            hp=20,
            max_hp=20,
            snapshot_json={
                "feature_runtime": {
                    "actions": {
                        "tactical_mind": {
                            "id": "tactical_mind",
                            "name": "战术思维",
                            "kind": "roll_intervention",
                            "trigger": "after_failed_d20_test",
                            "eligibility": {
                                "entity_types": ["character"],
                                "test_kinds": ["ability_check"],
                                "resource": {"key": "second_wind", "minimum": 1},
                            },
                            "input_requirements": [
                                {
                                    "key": "tactical_die",
                                    "kind": "die_roll",
                                    "die_sides": 10,
                                }
                            ],
                            "operation": {
                                "kind": "failure_recovery",
                                "recovery": {
                                    "kind": "add_die",
                                    "input_key": "tactical_die",
                                    "die_sides": 10,
                                },
                                "consume_when": "on_success",
                            },
                            "resource": {"key": "second_wind", "cost": 1},
                        }
                    },
                    "resources": {"second_wind": {"current": 2, "max": 2}},
                }
            },
        )

    class FakeSession:
        def __init__(self) -> None:
            self.character = SimpleNamespace(
                resources={"second_wind": {"current": 2, "max": 2}},
                version=1,
                updated_at=None,
            )

        def get(self, _model: object, _entity_id: str) -> object:
            return self.character

    opened = CombatEngineService._resolve_player_roll(
        action,
        target(),
        PlayerRollResolutionCommand(action_version=1, roll_total=12),
        session=FakeSession(),
    )
    assert opened["phase"] == "awaiting_roll_intervention"
    assert opened["roll_intervention_window"][0]["id"] == "tactical_mind"

    failed_session = FakeSession()
    failed = CombatEngineService._resolve_player_roll(
        action,
        target(),
        PlayerRollResolutionCommand(
            action_version=1,
            roll_total=12,
            roll_intervention_id="tactical_mind",
            roll_intervention_inputs={"tactical_die": 2},
        ),
        consume_defenses=True,
        session=failed_session,
    )
    assert failed["success"] is False
    assert failed["generic_resource_consumed"] is None
    assert failed_session.character.resources["second_wind"]["current"] == 2

    success_session = FakeSession()
    succeeded = CombatEngineService._resolve_player_roll(
        action,
        target(),
        PlayerRollResolutionCommand(
            action_version=1,
            roll_total=12,
            roll_intervention_id="tactical_mind",
            roll_intervention_inputs={"tactical_die": 4},
        ),
        consume_defenses=True,
        session=success_session,
    )
    assert succeeded["success"] is True
    assert succeeded["roll_total"] == 16
    assert succeeded["generic_resource_consumed"] == {
        "key": "second_wind",
        "cost": 1,
        "before": 2,
        "after": 1,
    }


def test_improved_warding_flare_applies_temporary_hp_post_effect() -> None:
    action = CombatAction(
        id="warding-flare-check",
        campaign_id="campaign",
        combat_id="combat",
        action_type="player_roll_prompt",
        target_combatant_ids=["warding-target"],
        request_json={
            "resolution_type": "armor_class",
            "dc": 15,
            "action_name": "命中测试",
        },
        result_json={},
        round_number=1,
        turn_index=0,
        summary="等待攻击检定",
        idempotency_key="warding-flare-check",
    )
    target = Combatant(
        id="warding-target",
        entity_type="character",
        entity_id="warding-character",
        display_name="守御目标",
        hp=20,
        max_hp=20,
        temporary_hp=0,
        reaction_available=True,
        version=1,
        snapshot_json={
            "ability_scores": {"wisdom": 18},
            "feature_runtime": {
                "actions": {
                    "warding_flare": {
                        "id": "warding_flare",
                        "name": "守御之光（精通）",
                        "kind": "roll_intervention",
                        "trigger": "after_d20_test",
                        "action_cost": "reaction",
                        "eligibility": {
                            "entity_types": ["character"],
                            "test_kinds": ["armor_class"],
                            "resource": {"key": "warding_flare", "minimum": 1},
                        },
                        "operation": {"kind": "disadvantage", "selection": "lowest"},
                        "input_requirements": [
                            {"key": "temporary_hp_total", "kind": "roll_total"}
                        ],
                        "post_effect": {
                            "kind": "grant_temporary_hp",
                            "input_key": "temporary_hp_total",
                            "dice_count": 2,
                            "die_sides": 6,
                            "ability_modifier": "wisdom",
                        },
                        "resource": {"key": "warding_flare", "cost": 1},
                    }
                }
            },
        },
    )

    class FakeSession:
        def __init__(self) -> None:
            self.character = SimpleNamespace(
                resources={"warding_flare": {"current": 1, "max": 1}},
                version=1,
                updated_at=None,
            )

        def get(self, _model: object, entity_id: str) -> object:
            return self.character if entity_id == "warding-character" else None

    resolved = CombatEngineService._resolve_player_roll(
        action,
        target,
        PlayerRollResolutionCommand(
            action_version=1,
            roll_total=17,
            roll_totals=[17, 12],
            roll_intervention_id="warding_flare",
            roll_intervention_inputs={"temporary_hp_total": 9},
        ),
        consume_defenses=True,
        session=FakeSession(),
    )
    assert resolved["success"] is False
    assert target.temporary_hp == 9
    assert resolved["generic_roll_intervention"]["post_effect"]["amount"] == 9


def test_combat_consumers_accept_a_snapshot_with_only_canonical_feature_blocks() -> None:
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
    canonical_only_runtime = {
        "feature_block_schema_version": registry["feature_block_schema_version"],
        "feature_blocks": registry["feature_blocks"],
        "progression": registry["progression"],
    }
    target = Combatant(
        id="canonical-feature-target",
        entity_type="character",
        display_name="canonical 特性目标",
        hp=20,
        max_hp=20,
        snapshot_json={"feature_runtime": canonical_only_runtime},
    )

    defenses = CombatEngineService._feature_defenses(target)

    assert any(item.get("kind") == "evasion" for item in defenses)


def test_feature_target_policy_enforces_faction_and_range_without_feature_names() -> None:
    actor = Combatant(
        id="feature-target-actor",
        entity_type="character",
        display_name="吟游诗人",
        hp=20,
        max_hp=20,
        snapshot_json={
            "disposition": "ally",
            "grid_position": {"row": 1, "col": 1},
        },
    )
    ally = Combatant(
        id="feature-target-ally",
        entity_type="character",
        display_name="盟友",
        hp=20,
        max_hp=20,
        snapshot_json={
            "disposition": "ally",
            "grid_position": {"row": 1, "col": 7},
        },
    )
    enemy = Combatant(
        id="feature-target-enemy",
        entity_type="monster",
        display_name="敌人",
        hp=20,
        max_hp=20,
        snapshot_json={
            "disposition": "enemy",
            "grid_position": {"row": 1, "col": 2},
        },
    )
    action = {
        "target_policy": {
            "mode": "ally_or_self",
            "same_faction": True,
            "range_ft": 60,
        }
    }
    combat = SimpleNamespace(scene_id=None)

    CombatEngineService._validate_feature_target_policy(
        None, combat, actor, ally, action
    )
    with pytest.raises(ValueError, match="同阵营"):
        CombatEngineService._validate_feature_target_policy(
            None, combat, actor, enemy, action
        )
    ally.snapshot_json = {
        "disposition": "ally",
        "grid_position": {"row": 1, "col": 14},
    }
    with pytest.raises(ValueError, match="60 尺"):
        CombatEngineService._validate_feature_target_policy(
            None, combat, actor, ally, action
        )
