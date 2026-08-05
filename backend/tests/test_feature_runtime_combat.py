from __future__ import annotations

from dnd_dm_assistant.domain.feature_runtime import compile_feature_runtime_registry
from dnd_dm_assistant.infrastructure.database.combat_service import CombatEngineService
from dnd_dm_assistant.infrastructure.database.models import Combatant
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
