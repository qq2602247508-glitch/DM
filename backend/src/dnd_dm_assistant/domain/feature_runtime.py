from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from math import floor
from typing import Any

FEATURE_RUNTIME_SCHEMA_VERSION = "1.2"


_SHORT_REST_RESTORE_ONE = {
    "rest": "short_rest",
    "operation": "restore",
    "amount": 1,
}
_LONG_REST_SET_TO_MAX = {
    "rest": "long_rest",
    "operation": "set_to_max",
}
_DAMAGE_TYPES_EXCEPT_FORCE = [
    "acid",
    "bludgeoning",
    "cold",
    "fire",
    "lightning",
    "necrotic",
    "piercing",
    "poison",
    "psychic",
    "radiant",
    "slashing",
    "thunder",
]
_AUTOMATION_STATUSES = frozenset({"full", "partial", "dm_only"})


def resource_recovery_events(
    key: str,
    value: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return only explicitly known recovery semantics for a class resource.

    ``recovery`` is retained as the legacy coarse-grained sheet field.  The
    event list preserves the 2024 distinction between resources that regain
    one use on a short rest and resources that regain their whole pool.  It is
    metadata for the runtime contract; rest execution remains owned by the
    existing rest service.
    """

    explicit = value.get("recovery_events")
    if isinstance(explicit, list):
        return deepcopy(explicit)

    recovery = str(value.get("recovery") or "")
    if key in {"rage", "second_wind", "channel_divinity", "wild_shape", "action_surge"}:
        return [deepcopy(_SHORT_REST_RESTORE_ONE), deepcopy(_LONG_REST_SET_TO_MAX)]
    if key in {"focus", "pact_slots"}:
        return [
            {"rest": "short_rest", "operation": "set_to_max"},
            deepcopy(_LONG_REST_SET_TO_MAX),
        ]
    if key == "bardic_inspiration" and recovery == "short_rest":
        return [
            {"rest": "short_rest", "operation": "set_to_max"},
            deepcopy(_LONG_REST_SET_TO_MAX),
        ]
    if recovery == "short_rest":
        return [
            {"rest": "short_rest", "operation": "set_to_max"},
            deepcopy(_LONG_REST_SET_TO_MAX),
        ]
    if recovery == "long_rest":
        return [deepcopy(_LONG_REST_SET_TO_MAX)]
    return []


def apply_initiative_start_resource_recovery(
    resources: Mapping[str, Mapping[str, Any]],
    feature_registry: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Apply only unambiguous ``initiative_start`` resource events.

    This helper intentionally consumes the typed event contract instead of
    matching feature names. Events with missing numeric state or an unknown
    condition are ignored and remain available for DM adjudication.
    """

    updated = {
        str(key): deepcopy(dict(value))
        for key, value in resources.items()
        if isinstance(value, Mapping)
    }
    applied: list[dict[str, Any]] = []
    registry_resources = feature_registry.get("resources")
    if not isinstance(registry_resources, Mapping):
        return updated, applied

    for key, raw_entry in registry_resources.items():
        if not isinstance(raw_entry, Mapping):
            continue
        current_entry = updated.get(str(key))
        if current_entry is None:
            continue
        current = current_entry.get("current")
        if not isinstance(current, int) or isinstance(current, bool):
            continue
        for raw_event in raw_entry.get("recovery_events") or ():
            if not isinstance(raw_event, Mapping) or raw_event.get("trigger") != (
                "initiative_start"
            ):
                continue
            condition = raw_event.get("condition")
            operation = raw_event.get("operation")
            next_value: int | None = None
            if (
                condition == "current_below_2"
                and operation == "set_to_minimum"
                and isinstance(raw_event.get("minimum"), int)
                and current < int(raw_event["minimum"])
            ):
                next_value = int(raw_event["minimum"])
            elif (
                condition == "current_zero"
                and operation == "restore"
                and current == 0
                and isinstance(raw_event.get("amount"), int)
            ):
                next_value = current + int(raw_event["amount"])
            if next_value is None:
                continue
            maximum = current_entry.get("max")
            if isinstance(maximum, int) and not isinstance(maximum, bool):
                next_value = min(next_value, maximum)
            if next_value == current:
                continue
            current_entry["current"] = next_value
            applied.append(
                {
                    "resource_key": str(key),
                    "before": current,
                    "after": next_value,
                    "operation": str(operation),
                    "condition": str(condition),
                }
            )
            current = next_value
    return updated, applied


def resolve_unarmored_defense_ac(
    current_armor_class: int,
    ability_scores: Mapping[str, Any],
    feature_registry: Mapping[str, Any],
    *,
    equipment_state_authoritative: bool,
    wearing_armor: bool,
    wielding_shield: bool,
) -> tuple[int, dict[str, Any] | None]:
    """Resolve a typed unarmored-defense formula when equipment is known."""

    if not equipment_state_authoritative or wearing_armor:
        return current_armor_class, None
    combat_start = feature_registry.get("combat_start")
    modifiers = combat_start.get("modifiers") if isinstance(combat_start, Mapping) else ()
    for raw_modifier in modifiers or ():
        if not isinstance(raw_modifier, Mapping):
            continue
        if (
            raw_modifier.get("stat") != "armor_class"
            or raw_modifier.get("operation") != "set_base_formula"
        ):
            continue
        formula = raw_modifier.get("formula")
        if formula == "10+dexterity_modifier+constitution_modifier":
            constitution_key = "constitution"
        elif formula == "10+dexterity_modifier+wisdom_modifier":
            constitution_key = "wisdom"
        else:
            continue
        shield_allowed = raw_modifier.get("shield_allowed") is True
        if wielding_shield and not shield_allowed:
            continue
        dexterity = int(
            ability_scores.get(
                "dexterity",
                ability_scores.get("dex", ability_scores.get("敏捷", 10)),
            )
        )
        secondary = int(
            ability_scores.get(
                constitution_key,
                ability_scores.get(
                    "体质" if constitution_key == "constitution" else "感知",
                    10,
                ),
            )
        )
        resolved = 10 + floor((dexterity - 10) / 2) + floor((secondary - 10) / 2)
        if wielding_shield:
            resolved += 2
        return resolved, {
            "mode": "unarmored_defense",
            "formula": formula,
            "feature_id": raw_modifier.get("id"),
            "wearing_armor": False,
            "wielding_shield": wielding_shield,
            "shield_allowed": shield_allowed,
            "ability_scores": {
                "dexterity": dexterity,
                constitution_key: secondary,
            },
        }
    return current_armor_class, None


def resolve_feature_speed(
    current_speed_ft: int,
    feature_registry: Mapping[str, Any],
    *,
    equipment_state_authoritative: bool,
    wearing_armor: bool,
    wielding_shield: bool,
    wearing_heavy_armor: bool | None = None,
) -> tuple[int, dict[str, Any] | None]:
    """Apply only typed, equipment-gated speed modifiers.

    Speed is stored on the combatant because movement, Dash, standing from
    prone, and turn refresh all consume that value.  Do not infer equipment
    from a character's name, class, or starter-equipment prose: without an
    authoritative equipment instance set, the safe result is the base speed.
    """

    combat_start = feature_registry.get("combat_start")
    modifiers = combat_start.get("modifiers") if isinstance(combat_start, Mapping) else ()
    speed_modifiers = [
        raw
        for raw in modifiers or ()
        if isinstance(raw, Mapping)
        and raw.get("stat") == "speed_ft"
        and raw.get("operation") == "add"
        and raw.get("scope", "self") == "self"
    ]
    if not speed_modifiers:
        return current_speed_ft, None

    resolved = int(current_speed_ft)
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for modifier in speed_modifiers:
        value = modifier.get("value")
        source = str(
            modifier.get("feature_name")
            or modifier.get("source_feature")
            or modifier.get("id")
            or "结构化速度特性"
        )
        record = {
            "id": modifier.get("id"),
            "source": source,
            "value": value,
            "condition": modifier.get("applies_when"),
        }
        if not isinstance(value, int) or isinstance(value, bool):
            skipped.append({**record, "reason": "speed_modifier_value_unresolved"})
            continue
        if not equipment_state_authoritative:
            skipped.append({**record, "reason": "equipment_state_not_authoritative"})
            continue
        condition = modifier.get("applies_when")
        if condition == "not_wearing_heavy_armor":
            if wearing_heavy_armor is True:
                skipped.append({**record, "reason": "wearing_heavy_armor"})
                continue
            if wearing_armor and wearing_heavy_armor is None:
                skipped.append({**record, "reason": "armor_type_not_explicit"})
                continue
        elif condition == "unarmored_and_not_using_shield":
            if wearing_armor or wielding_shield:
                skipped.append({
                    **record,
                    "reason": "wearing_armor_or_wielding_shield",
                })
                continue
        else:
            skipped.append({**record, "reason": "speed_condition_not_supported"})
            continue
        resolved += value
        applied.append({**record, "applied": True})

    return resolved, {
        "mode": "feature_speed",
        "base_speed_ft": int(current_speed_ft),
        "resolved_speed_ft": resolved,
        "equipment_state_authoritative": equipment_state_authoritative,
        "wearing_armor": wearing_armor,
        "wielding_shield": wielding_shield,
        "applied": applied,
        "skipped": skipped,
    }


def _identity(value: object) -> str:
    return re.sub(r"[\s_：:（）()\-]", "", str(value or "")).casefold()


def _source(
    feature_name: str,
    class_name: str,
    class_level: int,
    source_record_id: str | None,
) -> dict[str, Any]:
    return {
        "feature_name": feature_name,
        "class_name": class_name,
        "class_level": class_level,
        "source_record_id": source_record_id,
    }


def _resource_entry(key: str, value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "label",
        "current",
        "max",
        "max_formula",
        "recovery",
        "recovery_events",
        "slot_level",
        "source",
        "requires_dm_adjudication",
        "note",
        "value",
        "value_kind",
        "automation_status",
        "resource_kind",
    }
    entry = {"key": key, **{name: deepcopy(value[name]) for name in allowed if name in value}}
    if "recovery_events" not in entry:
        recovery_events = resource_recovery_events(key, value)
        if recovery_events:
            entry["recovery_events"] = recovery_events
    return entry


def _extra_attack_count(feature_name: str) -> int | None:
    identity = _identity(feature_name)
    if "额外攻击" not in identity and "extraattack" not in identity:
        return None
    if any(marker in identity for marker in ("三", "threeextraattacks")):
        return 4
    if any(marker in identity for marker in ("二", "twoextraattacks")):
        return 3
    return 2


def _is_defense_fighting_style(feature_name: str) -> bool:
    return _identity(feature_name) in {
        "防御",
        "防御defense",
        "defense",
        "战斗风格防御",
        "fightingstyledefense",
    }


def feature_runtime_definition(
    *,
    feature_name: str,
    class_name: str,
    class_level: int,
    source_record_id: str | None = None,
    resources: Mapping[str, Mapping[str, Any]] | None = None,
    tracked_resource_keys: Iterable[str] = (),
    tracked_scaling_keys: Iterable[str] = (),
    modifiers: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Return only runtime facts supported by the local structured rules.

    Empty sections are intentional: a caller can distinguish a known runtime
    feature from a named grant whose prose still requires DM adjudication.
    Scaling values remain keyed until the complete character registry is
    compiled, preventing a level-1 grant from freezing a later table value.
    """

    source = _source(feature_name, class_name, class_level, source_record_id)
    identity = _identity(feature_name)
    class_identity = _identity(class_name)
    definition: dict[str, Any] = {
        "combat_start": {"modifiers": [], "defenses": []},
        "resources": {},
        "actions": {},
        "attack_riders": [],
    }
    resource_values = resources or {}
    for key in tracked_resource_keys:
        value = resource_values.get(key)
        if value is not None:
            definition["resources"][key] = _resource_entry(key, value)

    for index, raw_modifier in enumerate(modifiers):
        modifier = deepcopy(dict(raw_modifier))
        if (
            (identity in {"狂暴", "rage"})
            and modifier.get("stat") == "damage_roll"
            and modifier.get("scaling_key") == "rage_damage"
        ):
            # The registry has a more precise attack rider below. Keep the
            # legacy modifier on the grant for existing snapshot consumers,
            # but do not make a new consumer apply the same damage twice.
            continue
        modifier.setdefault("id", f"{_identity(feature_name)}:modifier:{index + 1}")
        modifier.update(source)
        definition["combat_start"]["modifiers"].append(modifier)

    attack_count = _extra_attack_count(feature_name)
    if attack_count is not None:
        definition["combat_start"]["attack_action_count"] = attack_count

    if _is_defense_fighting_style(feature_name):
        definition["combat_start"]["modifiers"].append(
            {
                "id": "fighting_style_defense:armor_class",
                "stat": "armor_class",
                "operation": "add",
                "value": 1,
                "scope": "self",
                "applies_when": "wearing_armor",
                **source,
            }
        )

    if identity in {"无甲防御", "unarmoreddefense"}:
        formula: str | None = None
        requirements: list[str] = ["not_wearing_armor"]
        shield_allowed = False
        if class_identity in {"野蛮人", "barbarian"}:
            formula = "10+dexterity_modifier+constitution_modifier"
            shield_allowed = True
        elif class_identity in {"武僧", "monk"}:
            formula = "10+dexterity_modifier+wisdom_modifier"
            requirements.append("not_wielding_shield")
        if formula is not None:
            definition["combat_start"]["modifiers"].append(
                {
                    "id": f"{class_identity}:unarmored_defense",
                    "stat": "armor_class",
                    "operation": "set_base_formula",
                    "formula": formula,
                    "scope": "self",
                    "requirements": requirements,
                    "shield_allowed": shield_allowed,
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    **source,
                }
            )

    scaling_keys = set(tracked_scaling_keys)
    resource_keys = set(tracked_resource_keys)

    if identity in {"持久狂暴", "persistentrage"} and "rage" in resource_keys:
        # The local 2024 progression table treats Persistent Rage as the
        # point at which the rage pool is fully restored by either rest. Keep
        # that table fact typed on the resource; it is not a combat action and
        # must not create an invented button or initiative trigger.
        resource = definition["resources"].get("rage")
        if isinstance(resource, dict):
            resource["recovery_events"] = [
                {"rest": "short_rest", "operation": "set_to_max"},
                {"rest": "long_rest", "operation": "set_to_max"},
            ]

    if identity in {"先发激励", "superiorinspiration"} and "bardic_inspiration" in resource_keys:
        resource = definition["resources"].get("bardic_inspiration")
        if isinstance(resource, dict):
            resource["recovery_events"] = [
                *list(resource.get("recovery_events") or []),
                {
                    "trigger": "initiative_start",
                    "operation": "set_to_minimum",
                    "minimum": 2,
                    "condition": "current_below_2",
                }
            ]
            resource.update(
                {
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    "note": "先攻开始时，次数低于 2 会自动恢复至 2。",
                }
            )

    if identity in {"明镜止水", "perfectfocus"} and "focus" in resource_keys:
        resource = definition["resources"].get("focus")
        if isinstance(resource, dict):
            resource["recovery_events"] = [
                *list(resource.get("recovery_events") or []),
                {
                    "trigger": "initiative_start",
                    "operation": "set_to",
                    "value": 4,
                    "condition": "current_at_most_3_and_not_using_focus_feature",
                    "requires_dm_adjudication": True,
                }
            ]
            resource.update(
                {
                    "automation_status": "partial",
                    "requires_dm_adjudication": True,
                    "note": "先攻条件与恢复值已结构化；仍需判断本次是否使用运转周天。",
                }
            )

    if identity in {"大德鲁伊", "archdruid"} and "wild_shape" in resource_keys:
        resource = definition["resources"].get("wild_shape")
        if isinstance(resource, dict):
            resource["recovery_events"] = [
                *list(resource.get("recovery_events") or []),
                {
                    "trigger": "initiative_start",
                    "operation": "restore",
                    "amount": 1,
                    "condition": "current_zero",
                }
            ]
            resource.update(
                {
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    "note": "先攻开始时，野性形态次数为零会自动恢复一次。",
                }
            )

    if identity in {"先天术法", "innatesorcery"}:
        definition["resources"]["innate_sorcery"] = _resource_entry(
            "innate_sorcery",
            {
                "label": feature_name,
                "max": 2,
                "recovery": "long_rest",
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        )
        definition["actions"]["innate_sorcery"] = {
            "id": "innate_sorcery",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "bonus_action",
            "resource_key": "innate_sorcery",
            "resource_cost": 1,
            "target": "self",
            "resolution_kind": "condition",
            "duration": "1_minute",
            "effects": [
                {
                    "kind": "activate_duration_condition",
                    "condition": "innate_sorcery",
                    "duration_unit": "minutes",
                    "duration_value": 1,
                }
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["activate_duration_condition"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            **source,
        }
        definition["combat_start"]["modifiers"].extend(
            [
                {
                    "id": "innate_sorcery:spell_save_dc",
                    "stat": "spell_save_dc",
                    "operation": "add",
                    "value": 1,
                    "scope": "outgoing",
                    "applies_when": "innate_sorcery_active",
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    **source,
                },
                {
                    "id": "innate_sorcery:spell_attack_advantage",
                    "stat": "attack_roll",
                    "operation": "advantage",
                    "scope": "outgoing",
                    "applies_when": "innate_sorcery_active_and_sorcerer_spell",
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    **source,
                },
            ]
        )

    if "回气" in identity or "secondwind" in identity:
        if "second_wind" in resource_keys:
            resource = definition["resources"].get("second_wind")
            if isinstance(resource, dict):
                resource["recovery_events"] = [
                    {"rest": "short_rest", "operation": "restore", "amount": 1},
                    {"rest": "long_rest", "operation": "set_to_max"},
                ]
        definition["actions"]["second_wind"] = {
            "id": "second_wind",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "bonus_action",
            "resource_key": "second_wind",
            "resource_cost": 1,
            "target": "self",
            "resolution_kind": "healing",
            "healing_formula": "1d10+class_level",
            "effects": [{"kind": "healing"}],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["healing"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "消耗一次回气资源，掷 1d10+战士等级恢复生命。",
            **source,
        }

    if identity in {"狂暴", "rage"}:
        if "rage" in resource_keys:
            resource = definition["resources"].get("rage")
            if isinstance(resource, dict):
                resource["recovery_events"] = [
                    {"rest": "short_rest", "operation": "restore", "amount": 1},
                    {"rest": "long_rest", "operation": "set_to_max"},
                ]
        definition["actions"]["rage"] = {
            "id": "rage",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "bonus_action",
            "resource_key": "rage",
            "resource_cost": 1,
            "target": "self",
            "effects": [{
                "kind": "activate_duration_condition",
                "condition": "raging",
                "duration_unit": "minutes",
                "duration_value": 1,
            }],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["activate_duration_condition"],
                "remaining_dm_boundaries": [],
            },
            "requirements": ["not_wearing_heavy_armor"],
            "automation_status": "full",
            "requires_dm_adjudication": False,
            **source,
        }
        definition["combat_start"]["defenses"].append(
            {
                "id": "rage:physical_resistance",
                "operation": "resistance",
                "damage_types": ["bludgeoning", "piercing", "slashing"],
                "applies_when": "raging",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "conditional_damage_defense",
                },
                **source,
            }
        )
        definition["combat_start"]["modifiers"].extend(
            [
                {
                    "id": "rage:strength_check_advantage",
                    "stat": "ability_check",
                    "operation": "advantage",
                    "ability": "strength",
                    "scope": "self",
                    "applies_when": "raging",
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    "summary": "狂暴期间力量属性检定具有优势。",
                    **source,
                },
                {
                    "id": "rage:strength_saving_throw_advantage",
                    "stat": "saving_throw",
                    "operation": "advantage",
                    "ability": "strength",
                    "scope": "self",
                    "applies_when": "raging",
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    "summary": "狂暴期间力量豁免具有优势。",
                    **source,
                },
            ]
        )
        if "rage_damage" in scaling_keys:
            definition["attack_riders"].append(
                {
                    "id": "rage:bonus_damage",
                    "kind": "bonus_damage",
                    "scaling_key": "rage_damage",
                    "applies_when": "raging_strength_attack",
                    "frequency": "each_eligible_hit",
                    "runtime_execution": {
                        "status": "ready",
                        "consumer": "attack_rider_resolver",
                    },
                    **source,
                }
            )

    # These contracts reuse existing feature-action effects. Their attack-roll,
    # movement, and damage-interception semantics remain explicitly partial
    # until the combat engine has a shared condition evaluator for them.
    if "鲁莽攻击" in identity or "recklessattack" in identity:
        definition["actions"]["reckless_attack"] = {
            "id": "reckless_attack",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "none",
            "target": "self",
            "resolution_kind": "condition",
            "requirements": ["before_first_strength_attack_roll"],
            "activation_window": "before_first_strength_attack_on_turn",
            "effects": [
                {
                    "kind": "activate_timed_condition",
                    "condition": "reckless_attack",
                    "expires": "turn_start",
                }
            ],
            "rule_effects": [
                "advantage_on_strength_attack_rolls",
                "attackers_have_advantage_against_self",
            ],
            "attack_advantage": {
                "ability": "strength",
                "duration": "until_next_turn",
            },
            "incoming_attack_advantage": True,
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["activate_timed_condition"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "本回合力量武器攻击具有优势；直到下回合开始，攻击你也具有优势。",
            **source,
        }

    if "灵巧动作" in identity or "狡诈动作" in identity or "cunningaction" in identity:
        definition["actions"]["cunning_action"] = {
            "id": "cunning_action",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "bonus_action",
            "target": "self",
            "resolution_kind": "choice_required",
            "choices": ["dash", "disengage", "hide"],
            "allowed_actions": ["dash", "disengage", "hide"],
            "effects": [
                {
                    "kind": "cunning_action_choice",
                }
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["cunning_action_choice"],
                "remaining_dm_boundaries": ["hide_requires_explicit_outcome"],
            },
            "automation_status": "partial",
            "requires_dm_adjudication": True,
            "partial_reason": (
                "疾走和撤离由标准动作引擎真实执行；"
                "躲藏仍需 DM 提交明确成功/失败裁定。"
            ),
            **source,
        }

    if "稳定瞄准" in identity or "稳固瞄准" in identity or "steadyaim" in identity:
        definition["actions"]["steady_aim"] = {
            "id": "steady_aim",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "bonus_action",
            "target": "self",
            "resolution_kind": "condition",
            "requirements": ["not_moved_this_turn"],
            "activation_window": "before_next_attack_on_current_turn",
            "movement_after_use": 0,
            "movement_remaining_after_use": 0,
            "effects": [
                {
                    "kind": "activate_timed_condition",
                    "condition": "steady_aim",
                    "expires": "turn_end",
                }
            ],
            "rule_effects": ["advantage_on_next_attack_roll_this_turn"],
            "attack_advantage": {
                "frequency": "next_attack",
                "duration": "current_turn",
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["activate_timed_condition"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "本回合未移动时，速度归零；本回合下一次攻击掷骰具有优势。",
            **source,
        }

    if "直觉闪避" in identity or "uncannydodge" in identity:
        definition["actions"]["uncanny_dodge"] = {
            "id": "uncanny_dodge",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "reaction",
            "target": "self",
            "resolution_kind": "choice_required",
            "effects": [
                {
                    "kind": "requires_dm_choice",
                    "reason": (
                        "直觉闪避只能在可见攻击者命中后、伤害结算前触发，并将该次攻击伤害减半。"
                    ),
                }
            ],
            "trigger": {
                "event": "attacker_hits_self",
                "timing": "before_damage",
                "requirements": ["attacker_visible"],
            },
            "damage_multiplier": 0.5,
            "runtime_execution": {
                "status": "implemented",
                "consumer": "combat_feature_action",
            },
            "automation_status": "implemented",
            "requires_dm_adjudication": False,
            "partial_reason": (
                "玩家仍需在伤害落地前选择是否使用反应；"
                "服务端负责冻结攻击并按规则减半。"
            ),
            **source,
        }

    if (
        "偏转攻击" in identity
        or "拨挡攻击" in identity
        or "拨挡能量" in identity
        or "deflectattacks" in identity
        or "deflectenergy" in identity
    ):
        deflects_all_damage = "拨挡能量" in identity or "deflectenergy" in identity
        definition["actions"]["deflect_attacks"] = {
            "id": "deflect_attacks",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "reaction",
            "target": "self",
            "resolution_kind": "choice_required",
            "effects": [
                {
                    "kind": "requires_dm_choice",
                    "reason": "偏转攻击需要在命中后输入减伤骰；伤害归零后的反击分支仍需选择。",
                }
            ],
            "trigger": {"event": "attacker_hits_self", "timing": "before_damage"},
            "damage_reduction_formula": "1d10+dexterity_modifier+class_level",
            "eligible_damage_types": (
                "all" if deflects_all_damage else ["bludgeoning", "piercing", "slashing"]
            ),
            "redirect_resource_key": "focus",
            "redirect_resource_cost": 1,
            "redirect": {
                "resource_key": "focus",
                "resource_cost": 1,
                "range_ft": 5,
                "save_ability": "dexterity",
                "save_dc_formula": "8+dexterity_modifier+proficiency_bonus",
                "damage_formula": "2x martial_arts_die+dexterity_modifier",
                "damage_die_key": "martial_arts_die",
                "damage_dice_count": 2,
                "damage_type": "force",
                "successful_save_multiplier": 0.5,
            },
            "runtime_execution": {
                "status": "partial",
                "consumer": "combat_feature_action",
                "consumer_steps": [
                    "focus_consumption",
                    "target_selection_within_range",
                    "dexterity_save",
                    "redirect_damage",
                ],
            },
            "automation_status": "partial",
            "requires_dm_adjudication": True,
            "partial_reason": (
                "命中后减伤骰和伤害扣除已自动执行；"
                "伤害归零后的 Focus 消耗、目标选择、敏捷豁免和反击伤害骰"
                "由第二个持久化窗口收集。"
            ),
            **source,
        }

    if "偷袭" in identity or "sneakattack" in identity:
        if "sneak_attack" in scaling_keys:
            definition["attack_riders"].append(
                {
                    "id": "sneak_attack:bonus_damage",
                    "kind": "bonus_damage",
                    "scaling_key": "sneak_attack",
                    "damage_type": "weapon_damage_type",
                    "applies_when": "sneak_attack_eligible",
                    "frequency": "once_per_turn",
                    **source,
                }
            )

    if (
        "圣武斩" in identity
        or "神圣惩击" in identity
        or "divinesmite" in identity
        or "paladinssmite" in identity
    ):
        definition["actions"]["divine_smite"] = {
            "id": "divine_smite",
            "name": feature_name,
            "kind": "attack_rider_contract",
            "action_cost": "none",
            "target": "hit_target",
            "resolution_kind": "choice_required",
            "trigger": "after_melee_weapon_or_unarmed_hit",
            "choices": ["spell_slot_level", "reported_damage_total"],
            "requires_player_input": [
                {
                    "key": "spell_slot_level",
                    "kind": "select",
                    "minimum": 1,
                    "label": "消耗的法术位环阶",
                },
                {
                    "key": "damage_total",
                    "kind": "roll_total",
                    "label": "圣武斩伤害骰总值",
                },
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "attack_rider_resolver",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": (
                "命中近战武器或徒手攻击后，可选择法术位并提交圣武斩伤害骰；"
                "服务端校验并消耗对应法术位。"
            ),
            **source,
        }
        definition["attack_riders"].append(
            {
                "id": "divine_smite:bonus_damage",
                "kind": "bonus_damage",
                "value": "2d8",
                "damage_type": "radiant",
                "applies_when": "divine_smite_selected_after_melee_weapon_or_unarmed_hit",
                "frequency": "once_per_turn",
                "resource_key": "spell_slots",
                "resource_cost_mode": "selected_spell_slot",
                "minimum_spell_slot_level": 1,
                "damage_formula": "2d8 + 1d8 per slot level above 1st (maximum 5d8)",
                "requires_player_input": [
                    {
                        "key": "spell_slot_level",
                        "kind": "select",
                        "minimum": 1,
                        "label": "消耗的法术位环阶",
                    },
                    {
                        "key": "damage_total",
                        "kind": "roll_total",
                        "label": "圣武斩伤害骰总值",
                    },
                ],
                "automation_status": "full",
                "requires_dm_adjudication": False,
                **source,
            }
        )

    if "动作如潮" in identity or "行动如潮" in identity or "actionsurge" in identity:
        definition["actions"]["action_surge"] = {
            "id": "action_surge",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "none",
            "resource_key": "action_surge",
            "resource_cost": 1,
            "target": "self",
            "effects": [
                {"kind": "grant_action_budget", "amount": 1, "excludes": ["magic_action"]}
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["grant_action_budget"],
                "remaining_dm_boundaries": [],
            },
            "limits": ["once_per_turn"],
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "每回合只能使用一次；额外动作不能用于施放法术。",
            **source,
        }

    # These feature contracts are intentionally small and typed.  They expose
    # only effects whose input and rollback are deterministic; a feature that
    # still needs a chosen form, target geometry, or a branch remains DM-only
    # instead of being silently treated as a text label.
    if "不屈" in identity or "indomitable" in identity:
        if "indomitable" in resource_keys:
            definition["actions"]["indomitable"] = {
                "id": "indomitable",
                "name": feature_name,
                "kind": "feature_action",
                "action_cost": "none",
                "resource_key": "indomitable",
                "resource_cost": 1,
                "target": "self",
                "resolution_kind": "saving_throw_reroll",
                "activation_window": "after_failed_saving_throw",
                "effects": [{"kind": "grant_saving_throw_reroll", "scope": "self"}],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "saving_throw_resolution",
                    "effect_kinds": ["grant_saving_throw_reroll"],
                    "remaining_dm_boundaries": [],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                **source,
            }

    if "圣疗" in identity or "layonhands" in identity:
        if "lay_on_hands" in resource_keys:
            definition["actions"]["lay_on_hands"] = {
                "id": "lay_on_hands",
                "name": feature_name,
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "lay_on_hands",
                "resource_cost": 0,
                "resource_cost_mode": "amount_or_condition",
                "condition_cure_cost": 5,
                "condition_cure_options": ["poisoned", "diseased"],
            "target": "ally_or_self",
            "resolution_kind": "healing",
            "healing_formula": "lay_on_hands_pool",
            "effects": [{"kind": "healing"}, {"kind": "condition_cure"}],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["healing", "condition_cure"],
                "remaining_dm_boundaries": ["contact_distance_requires_authoritative_position"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
                **source,
            }

    if identity in {"荒野变形", "wildshape"} and "wild_shape" in resource_keys:
        definition["actions"]["wild_shape"] = {
            "id": "wild_shape",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "bonus_action",
            "resource_key": "wild_shape",
            "resource_cost": 1,
            "target": "self",
            "resolution_kind": "choice_required",
            "effects": [
                {
                    "kind": "requires_dm_choice",
                    "reason": "荒野变形的形态、临时生命值与动作选项需要 DM 选择",
                }
            ],
            **source,
        }

    if "吟游诗人激励" in identity or "bardicinspiration" in identity:
        if "bardic_inspiration" in resource_keys:
            definition["actions"]["bardic_inspiration"] = {
                "id": "bardic_inspiration",
                "name": feature_name,
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "bardic_inspiration",
                "resource_cost": 1,
                "target": "ally_or_self",
                "resolution_kind": "grant_dice",
                "dice_key": "bardic_inspiration_die",
                "effects": [
                    {"kind": "grant_roll_die", "die_key": "bardic_inspiration_die"}
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action",
                    "effect_kinds": ["grant_roll_die"],
                    "remaining_dm_boundaries": [
                        "target_range_visibility_and_audibility",
                        "one_die_per_target",
                        "failed_d20_consumption_window",
                    ],
                },
                "automation_status": "partial",
                "requires_dm_adjudication": True,
                "partial_reason": (
                    "激励骰授予与资源扣除由现有特性执行器结算；目标距离、可见/可听、"
                    "同一目标持有上限和失败 D20 后的消费窗口仍需 DM 裁定。"
                ),
                **source,
            }

    if identity in {"反迷惑", "countercharm"}:
        definition["actions"]["countercharm"] = {
            "id": "countercharm",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "reaction",
            "target": "self_or_ally_within_30ft",
            "resolution_kind": "saving_throw_reroll",
            "activation_window": "after_failed_saving_throw",
            "trigger": {
                "event": "saving_throw_failed",
                "conditions": ["charmed", "frightened"],
                "range_ft": 30,
            },
            "reroll_mode": "advantage",
            "effects": [
                {
                    "kind": "requires_dm_choice",
                    "reason": "反迷惑需要在魅惑或恐慌豁免失败后插入反应重骰窗口。",
                }
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "saving_throw_resolution",
                "effect_kinds": ["saving_throw_reroll"],
                "remaining_dm_boundaries": [
                    "multiple_eligible_reactors_require_dm_selection",
                    "missing_authoritative_grid_position",
                ],
            },
            "automation_status": "partial",
            "requires_dm_adjudication": True,
            "partial_reason": (
                "唯一符合距离和反应条件的吟游诗人可自动打开重骰窗口；"
                "多个候选者或缺少权威位置仍需 DM 选择。"
            ),
            **source,
        }

    if ("自然面纱" in identity or "natureveil" in identity) and "nature_veil" in resource_keys:
        definition["actions"]["nature_veil"] = {
            "id": "nature_veil",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "bonus_action",
            "resource_key": "nature_veil",
            "resource_cost": 1,
            "target": "self",
            "resolution_kind": "condition",
            "effects": [
                {
                    "kind": "activate_timed_condition",
                    "condition": "隐形",
                    "expires": "turn_start",
                }
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["activate_timed_condition"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "消耗一次自然面纱，在下一回合开始前保持隐形。",
            **source,
        }

    if ("不知疲倦" in identity or "tireless" in identity) and "tireless" in resource_keys:
        definition["actions"]["tireless"] = {
            "id": "tireless",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "action",
            "resource_key": "tireless",
            "resource_cost": 1,
            "target": "self",
            "resolution_kind": "temporary_healing",
            "healing_formula": "1d8+wisdom_modifier",
            "minimum_healing": 1,
            "rest_effects": [
                {
                    "kind": "reduce_exhaustion",
                    "rest": "short_rest",
                    "amount": 1,
                }
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action_and_rest_resolution",
                "effect_kinds": ["temporary_healing", "reduce_exhaustion"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "短休结束时力竭降低 1 级；也可消耗次数获得临时生命值。",
            **source,
        }

    if "引导神力" in identity or "channeldivinity" in identity:
        if "channel_divinity" in resource_keys:
            definition["actions"]["channel_divinity"] = {
                "id": "channel_divinity",
                "name": feature_name,
                "kind": "feature_action",
                "action_cost": "action",
                "resource_key": "channel_divinity",
                "resource_cost": 1,
                "target": "self",
                "resolution_kind": "choice_required",
                "effects": [
                    {
                        "kind": "requires_dm_choice",
                        "reason": "引导神力的具体选项来自牧师子职或特性分支",
                    }
                ],
                **source,
            }

    if "神圣干预" in identity or "divineintervention" in identity:
        if "divine_intervention" in resource_keys:
            definition["actions"]["divine_intervention"] = {
                "id": "divine_intervention",
                "name": feature_name,
                "kind": "feature_action",
                "action_cost": "action",
                "resource_key": "divine_intervention",
                "resource_cost": 1,
                "target": "self",
                "resolution_kind": "choice_required",
                "effects": [
                    {
                        "kind": "requires_dm_choice",
                        "reason": "神圣干预需要 DM 选择合法的牧师法术或祈愿术分支",
                    }
                ],
                **source,
            }

    if "反射闪避" in identity or "evasion" in identity:
        definition["combat_start"]["defenses"].append(
            {
                "id": "evasion",
                "kind": "evasion",
                "applies_when": (
                    "dexterity_saving_throw_for_half_damage_and_not_incapacitated"
                ),
                "success_damage_multiplier": 0,
                "failure_damage_multiplier": 0.5,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "saving_throw_damage_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "仅对成功豁免减半伤害的敏捷豁免生效；失能时不生效。",
                "source": feature_name,
                **source,
            }
        )

    if (
        "危机感应" in identity
        or "危机感知" in identity
        or "危险感知" in identity
        or "dangersense" in identity
    ):
        definition["combat_start"]["modifiers"].append(
            {
                "id": "danger_sense:dexterity_saving_throw_advantage",
                "stat": "saving_throw",
                "operation": "advantage",
                "ability": "dexterity",
                "scope": "self",
                "applies_when": "not_incapacitated",
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "未处于失能状态时，敏捷豁免具有优势。",
                **source,
            }
        )

    if "野性直觉" in identity or "feralinstinct" in identity:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "feral_instinct:initiative_advantage",
                "stat": "initiative",
                "operation": "advantage",
                "scope": "self",
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "先攻时投掷两枚 d20，取较高值。",
                **source,
            }
        )

    if identity in {"究明攻击", "studiedattacks"}:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "studied_attacks:next_attack_advantage",
                "stat": "attack_roll",
                "operation": "advantage",
                "scope": "outgoing",
                "applies_when": "next_attack_against_same_target_after_miss",
                "expires": "next_turn_end",
                "frequency": "next_attack",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_context_resolver",
                    "producer": "attack_miss_event",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": (
                    "明确失手后，为同一目标的下一次攻击真实提供优势，"
                    "并在下一回合结束时清理。"
                ),
                **source,
            }
        )

    if "可靠才能" in identity or "可靠天赋" in identity or "reliabletalent" in identity:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "reliable_talent:proficient_ability_check_floor",
                "stat": "ability_check",
                "operation": "set_minimum_d20",
                "minimum": 10,
                "scope": "self",
                "applies_when": "proficient_ability_check",
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "对熟练的属性/技能检定，d20 结果低于 10 时按 10 处理。",
                **source,
            }
        )

    if identity in {"圆滑心智", "slipperymind"}:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "slippery_mind:saving_throw_proficiencies",
                "stat": "saving_throw",
                "operation": "grant_proficiency",
                "abilities": ["wisdom", "charisma"],
                "scope": "self",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "saving_throw_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "系统自动替目标进行豁免时，对感知和魅力豁免加入一次权威熟练加值。",
                **source,
            }
        )

    if identity in {"飘忽不定", "elusive"}:
        definition["combat_start"]["defenses"].append(
            {
                "id": "elusive:suppress_incoming_advantage",
                "kind": "suppress_attack_advantage",
                "scope": "incoming",
                "applies_when": "not_incapacitated",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_context_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "未处于失能状态时，针对你的攻击不会因规则获得优势。",
                **source,
            }
        )

    if identity in {"幸运一击", "strokeofluck"}:
        definition["resources"]["stroke_of_luck"] = _resource_entry(
            "stroke_of_luck",
            {
                "label": feature_name,
                "max": 1,
                "recovery": "short_rest",
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        )
        definition["actions"]["stroke_of_luck"] = {
            "id": "stroke_of_luck",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "none",
            "resource_key": "stroke_of_luck",
            "resource_cost": 1,
            "target": "self",
            "resolution_kind": "d20_replacement",
            "activation_window": "after_failed_d20_test",
            "trigger": {"event": "d20_test_failed", "timing": "after_result"},
            "replacement": {"d20_roll": 20},
            "effects": [{"kind": "replace_d20_roll", "replacement": 20}],
            "runtime_execution": {
                "status": "ready",
                "consumer": "player_roll_resolution",
                "effect_kinds": ["replace_d20_roll"],
                "remaining_dm_boundaries": [],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            **source,
        }

    if identity in {"返本还元", "selfrestoration"}:
        definition["actions"]["self_restoration"] = {
            "id": "self_restoration",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "none",
            "target": "self",
            "resolution_kind": "condition_removal",
            "activation_window": "turn_end",
            "allowed_conditions": ["charmed", "frightened", "poisoned"],
            "effects": [{"kind": "condition_removal"}],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["condition_removal"],
                "remaining_dm_boundaries": [],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            **source,
        }
        definition["combat_start"]["defenses"].append(
            {
                "id": "self_restoration:end_turn_condition_removal",
                "kind": "end_turn_condition_removal",
                "conditions": ["charmed", "frightened", "poisoned"],
                "frequency": "one_at_each_turn_end",
                "automation_status": "full",
                "requires_dm_adjudication": False,
                **source,
            }
        )

    if identity in {"圆融自在", "disciplinedsurvivor"}:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "disciplined_survivor:all_save_proficiency",
                "stat": "saving_throw",
                "operation": "grant_proficiency",
                "abilities": "all",
                "scope": "self",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "saving_throw_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "系统自动替目标进行任意属性豁免时，加入一次权威熟练加值。",
                **source,
            }
        )
        definition["actions"]["disciplined_survivor"] = {
            "id": "disciplined_survivor",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "none",
            "resource_key": "focus",
            "resource_cost": 1,
            "target": "self",
            "resolution_kind": "saving_throw_reroll",
            "activation_window": "after_failed_saving_throw",
            "effects": [{"kind": "grant_saving_throw_reroll", "scope": "self"}],
            "runtime_execution": {
                "status": "ready",
                "consumer": "saving_throw_resolution",
                "effect_kinds": ["grant_saving_throw_reroll"],
                "remaining_dm_boundaries": [],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "失败豁免后打开即时重掷窗口；确认后真实消耗 1 点专注并以第二枚骰结算。",
            **source,
        }

    if identity in {"无懈可击", "superiordefense"}:
        definition["actions"]["superior_defense"] = {
            "id": "superior_defense",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "none",
            "resource_key": "focus",
            "resource_cost": 3,
            "target": "self",
            "activation_window": "turn_start",
            "resolution_kind": "condition",
            "duration": "1_minute_or_until_incapacitated",
            "effects": [
                {
                    "kind": "activate_duration_condition",
                    "condition": "superior_defense",
                    "duration_unit": "minutes",
                    "duration_value": 1,
                }
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["activate_duration_condition"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "回合开始消耗 3 点专注；持续 1 分钟或直到失能，除力场外的伤害获得抗性。",
            **source,
        }
        definition["combat_start"]["defenses"].append(
            {
                "id": "superior_defense:all_except_force_resistance",
                "operation": "resistance",
                "damage_types": deepcopy(_DAMAGE_TYPES_EXCEPT_FORCE),
                "applies_when": "superior_defense_active",
                "resource_key": "focus",
                "activation_cost": 3,
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "无懈可击激活期间由伤害引擎真实应用除力场外的抗性。",
                **source,
            }
        )

    if "坚韧狂暴" in identity or "不屈狂暴" in identity or "relentlessrage" in identity:
        definition["combat_start"]["defenses"].append(
            {
                "id": "relentless_rage:zero_hit_points_save",
                "kind": "zero_hit_points_save",
                "trigger": "self_would_drop_to_zero_hit_points_while_raging",
                "saving_throw": {
                    "ability": "constitution",
                    "initial_dc": 10,
                    "increase_after_each_success": 5,
                    "reset": "short_or_long_rest",
                },
                "hit_points_on_success": "2*barbarian_level",
                "does_not_apply_when": "dies_outright",
                "automation_status": "partial",
                "requires_dm_adjudication": True,
                "partial_reason": "濒死拦截、递增 DC 与短休重置需要事件型伤害结算支持。",
                **source,
            }
        )

    if "不屈耐力" in identity or "relentlessendurance" in identity:
        definition["resources"]["relentless_endurance"] = _resource_entry(
            "relentless_endurance",
            {
                "label": feature_name,
                "max": 1,
                "recovery": "long_rest",
                "automation_status": "full",
                "requires_dm_adjudication": False,
            },
        )
        definition["combat_start"]["defenses"].append(
            {
                "id": "relentless_endurance:drop_to_one_hit_point",
                "resource_key": "relentless_endurance",
                "resource_cost": 1,
                "trigger": "would_drop_to_zero_hit_points",
                "on_success": {"hit_points": 1},
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "zero_hp_damage_resolution",
                    "does_not_apply_when": "dies_outright",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                **source,
            }
        )

    if (
        "不屈勇武" in identity
        or "不屈之力" in identity
        or "不屈巨力" in identity
        or "indomitablemight" in identity
    ):
        definition["combat_start"]["modifiers"].append(
            {
                "id": "indomitable_might:strength_check_floor",
                "stat": "ability_check",
                "operation": "set_minimum_total_from_ability",
                "ability": "strength",
                "scope": "self",
                "applies_when": "strength_ability_check_total_below_strength_score",
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                    "operation": "set_minimum_total_from_ability",
                },
                "summary": "力量属性检定总值低于力量值时，按力量值结算。",
                **source,
            }
        )

    if identity in {"守护灵光", "auraofprotection"}:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "aura_of_protection:saving_throw",
                "stat": "saving_throw",
                "operation": "add",
                "scope": "self_and_allies_within_10ft",
                "value_source": "charisma_modifier",
                "minimum": 1,
                "applies_when": "within_aura_of_protection",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "saving_throw_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": (
                    "同阵营单位在圣武士 10 尺内进行豁免时，"
                    "加入圣武士魅力调整值（最低 +1）。"
                ),
                **source,
            }
        )

    if identity in {"勇气灵光", "auraofcourage"}:
        definition["combat_start"]["defenses"].append(
            {
                "id": "aura_of_courage:frightened_immunity",
                "kind": "condition_immunity",
                "condition": "frightened",
                "scope": "self_and_allies_within_10ft",
                "applies_when": "within_aura_of_courage",
                "requires_dm_adjudication": True,
                **source,
            }
        )

    if identity in {"万事通", "jackofalltrades"}:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "jack_of_all_trades:ability_check",
                "stat": "ability_check",
                "operation": "add",
                "scope": "self",
                "value_source": "half_proficiency_bonus",
                "applies_when": "ability_check_without_proficiency",
                "requires_dm_adjudication": True,
                **source,
            }
        )

    if identity in {"武艺", "martialarts"} and "martial_arts_die" in scaling_keys:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "martial_arts:damage_die",
                "stat": "damage_roll",
                "operation": "grant",
                "scope": "outgoing",
                "scaling_key": "martial_arts_die",
                "applies_when": "unarmored_martial_arts_attack",
                "requires_dm_adjudication": True,
                **source,
            }
        )

    if identity in {"光耀打击", "radiantstrikes"}:
        definition["attack_riders"].append(
            {
                "id": "radiant_strikes:bonus_damage",
                "kind": "bonus_damage",
                "value": "1d8",
                "damage_type": "radiant",
                "applies_when": "radiant_strikes_eligible",
                "frequency": "once_per_turn",
                "requires_dm_adjudication": True,
                **source,
            }
        )

    if identity in {"凶蛮打击", "brutalstrike"}:
        definition["attack_riders"].append(
            {
                "id": "brutal_strike:bonus_damage",
                "kind": "bonus_damage",
                "value": "1d10",
                "damage_type": "weapon_damage_type",
                "applies_when": "brutal_strike_eligible",
                "frequency": "once_per_turn",
                "requires_dm_adjudication": True,
                **source,
            }
        )

    if identity in {"永恒追猎", "relentlesshunter"}:
        definition["combat_start"]["defenses"].append(
            {
                "id": "relentless_hunter:hunter_mark_concentration",
                "kind": "concentration_damage_immunity",
                "applies_when": "concentrating_on_hunters_mark",
                "trigger": "damage_received",
                "automation_status": "partial",
                "requires_dm_adjudication": True,
                "partial_reason": "猎人印记的专注来源尚未与通用专注检定事件关联。",
                **source,
            }
        )

    if identity in {"致命猎杀", "precisehunter"}:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "precise_hunter:marked_target_advantage",
                "stat": "attack_roll",
                "operation": "advantage",
                "scope": "outgoing",
                "applies_when": "target_is_current_hunters_mark",
                "automation_status": "partial",
                "requires_dm_adjudication": True,
                "partial_reason": "攻击优势已结构化；攻击引擎尚未自动关联当前猎人印记目标。",
                **source,
            }
        )

    if identity in {"屠灭众敌", "foeslayer"}:
        definition["attack_riders"].append(
            {
                "id": "foe_slayer:hunter_mark_damage",
                "kind": "bonus_damage",
                "value": "1d10",
                "damage_type": "force",
                "applies_when": "target_is_current_hunters_mark",
                "frequency": "each_eligible_hit",
                "automation_status": "partial",
                "requires_dm_adjudication": True,
                "partial_reason": (
                    "攻击附伤可结算；当前猎人印记目标仍需通过显式 eligibility 输入确认。"
                ),
                **source,
            }
        )

    return definition


def _entry_automation_status(entry: Mapping[str, Any]) -> str:
    """Return the conservative status for one typed runtime entry."""

    status = str(entry.get("automation_status") or "full")
    if status not in _AUTOMATION_STATUSES:
        status = "partial"
    effects = entry.get("effects")
    needs_choice = any(
        isinstance(effect, Mapping) and effect.get("kind") == "requires_dm_choice"
        for effect in (effects if isinstance(effects, list) else ())
    )
    if (entry.get("requires_dm_adjudication") or needs_choice) and status == "full":
        return "partial"
    return status


def _runtime_sections(definition: Mapping[str, Any]) -> tuple[str, ...]:
    sections: list[str] = []
    combat_start = definition.get("combat_start")
    if isinstance(combat_start, Mapping):
        if isinstance(combat_start.get("attack_action_count"), int):
            sections.append("attack_action_count")
        if combat_start.get("modifiers"):
            sections.append("combat_modifiers")
        if combat_start.get("defenses"):
            sections.append("combat_defenses")
    if definition.get("resources"):
        sections.append("resources")
    if definition.get("actions"):
        sections.append("actions")
    if definition.get("attack_riders"):
        sections.append("attack_riders")
    return tuple(sections)


def _runtime_entry_reasons(definition: Mapping[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []

    def add(value: object) -> None:
        text = str(value or "").strip()
        if text and text not in reasons:
            reasons.append(text)

    combat_start = definition.get("combat_start")
    if isinstance(combat_start, Mapping):
        entry_groups = (
            combat_start.get("modifiers"),
            combat_start.get("defenses"),
        )
    else:
        entry_groups = ()
    entry_groups = (
        *entry_groups,
        (definition.get("resources") or {}).values()
        if isinstance(definition.get("resources"), Mapping)
        else (),
        (definition.get("actions") or {}).values()
        if isinstance(definition.get("actions"), Mapping)
        else (),
        definition.get("attack_riders") or (),
    )
    for entries in entry_groups:
        for raw in entries or ():
            if not isinstance(raw, Mapping):
                continue
            add(raw.get("partial_reason"))
            if raw.get("requires_dm_adjudication"):
                add(raw.get("note"))
            effects = raw.get("effects")
            for effect in effects if isinstance(effects, list) else ():
                if isinstance(effect, Mapping) and effect.get("kind") == "requires_dm_choice":
                    add(effect.get("reason"))
    return tuple(reasons)


def feature_runtime_contract(
    *,
    feature_name: str,
    class_name: str,
    class_level: int,
    definition: Mapping[str, Any],
    kind: str = "feature",
    source_record_id: str | None = None,
    source_path: str | None = None,
    declared_status: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Summarise one named feature without turning its prose into automation.

    A compiled character registry used to expose only aggregate combat data and
    an ``dm_only`` catch-all.  That made it impossible to audit whether every
    table entry was deliberately classified.  This compact contract is emitted
    for every persisted grant: it states the grant's level/source, the typed
    sections available to the runtime, and why a partial or DM-only effect is
    not being presented as automatic.
    """

    sections = _runtime_sections(definition)
    statuses: list[str] = []
    combat_start = definition.get("combat_start")
    if isinstance(combat_start, Mapping):
        entries = (
            *list(combat_start.get("modifiers") or ()),
            *list(combat_start.get("defenses") or ()),
        )
        for raw in entries:
            if isinstance(raw, Mapping):
                statuses.append(_entry_automation_status(raw))
        if isinstance(combat_start.get("attack_action_count"), int):
            statuses.append("full")
    for raw_resources in (definition.get("resources"), definition.get("actions")):
        if isinstance(raw_resources, Mapping):
            statuses.extend(
                _entry_automation_status(raw)
                for raw in raw_resources.values()
                if isinstance(raw, Mapping)
            )
    for raw in definition.get("attack_riders") or ():
        if isinstance(raw, Mapping):
            statuses.append(_entry_automation_status(raw))

    normalized_declared = (
        declared_status if declared_status in _AUTOMATION_STATUSES else None
    )
    if not statuses:
        status = normalized_declared or "dm_only"
    elif any(value in {"partial", "dm_only"} for value in statuses):
        status = "partial"
    else:
        status = "full"

    reasons = list(_runtime_entry_reasons(definition))
    if status != "full" and note and note not in reasons:
        reasons.append(note)
    if status == "dm_only" and not reasons:
        reasons.append("该特性只有名称/来源授予时点；具体规则效果需要 DM 裁定。")
    if status == "partial" and not reasons:
        reasons.append("已结构化可验证字段；其余触发条件、目标或分支需要 DM 裁定。")

    source_key = ":".join(
        value
        for value in (
            _identity(class_name) or "unclassified",
            str(class_level),
            _identity(feature_name) or "unnamed",
            _identity(kind) or "feature",
        )
        if value
    )
    return {
        "id": source_key,
        "name": feature_name,
        "kind": kind,
        "class_name": class_name,
        "class_level": class_level,
        "source_record_id": source_record_id,
        "source_path": source_path,
        "automation_status": status,
        "requires_dm_adjudication": status != "full",
        "runtime_sections": list(sections),
        "reasons": reasons,
    }


def _has_runtime_entries(definition: Mapping[str, Any]) -> bool:
    combat_start = definition.get("combat_start")
    if isinstance(combat_start, Mapping):
        if "attack_action_count" in combat_start:
            return True
        if combat_start.get("modifiers") or combat_start.get("defenses"):
            return True
    return bool(
        definition.get("resources")
        or definition.get("actions")
        or definition.get("attack_riders")
    )


def _latest_scalings(
    grants: Iterable[Mapping[str, Any]],
    explicit: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for grant in grants:
        key = grant.get("scaling_key")
        if grant.get("kind") == "class_scaling" and isinstance(key, str):
            result[key] = grant.get("value")
    for key, value in (explicit or {}).items():
        result[key] = value.get("value")
    return result


def compile_feature_runtime_registry(
    feature_grants: Iterable[Mapping[str, Any]],
    *,
    resources: Mapping[str, Mapping[str, Any]] | None = None,
    scalings: Mapping[str, Mapping[str, Any]] | None = None,
    actions: Iterable[Mapping[str, Any]] = (),
    class_levels: Mapping[str, object] | None = None,
    total_level: int | None = None,
) -> dict[str, Any]:
    """Compile persisted feature grants into one combat/action contract.

    The compiler accepts the legacy tracked fields as well as the new embedded
    definitions. Unknown grants are never inferred from prose or names beyond
    the small allow-list in :func:`feature_runtime_definition`.
    """

    grants = [dict(item) for item in feature_grants]
    current_resources = resources or {}
    scaling_values = _latest_scalings(grants, scalings)
    current_class_levels: dict[str, int] = {}
    for grant in grants:
        class_name = str(grant.get("class_name") or "")
        if class_name:
            current_class_levels[class_name] = max(
                current_class_levels.get(class_name, 0),
                int(grant.get("class_level") or 0),
            )

    explicit_class_levels: dict[str, int] = {}
    for raw_name, raw_level in (class_levels or {}).items():
        name = str(raw_name).strip()
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            continue
        if name and level > 0:
            explicit_class_levels[name] = level
    effective_class_levels = explicit_class_levels or current_class_levels
    explicit_total = int(total_level or 0)
    effective_total_level = explicit_total if explicit_total > 0 else sum(
        effective_class_levels.values()
    )

    modifiers: dict[str, dict[str, Any]] = {}
    defenses: dict[str, dict[str, Any]] = {}
    resource_registry: dict[str, dict[str, Any]] = {}
    action_registry: dict[str, dict[str, Any]] = {}
    riders: dict[str, dict[str, Any]] = {}
    feature_contracts: dict[str, dict[str, Any]] = {}
    attack_action_count = 1

    for grant in grants:
        runtime = grant.get("runtime")
        runtime_data = dict(runtime) if isinstance(runtime, Mapping) else {}
        embedded = runtime_data.get("registry")
        if isinstance(embedded, Mapping):
            definition = deepcopy(dict(embedded))
        else:
            definition = feature_runtime_definition(
                feature_name=str(grant.get("name") or ""),
                class_name=str(grant.get("class_name") or ""),
                class_level=int(grant.get("class_level") or 0),
                source_record_id=(
                    str(grant["source_record_id"])
                    if grant.get("source_record_id") is not None
                    else None
                ),
                resources=current_resources,
                tracked_resource_keys=(runtime_data.get("tracked_resource_keys") or ()),
                tracked_scaling_keys=(runtime_data.get("tracked_scaling_keys") or ()),
                modifiers=(runtime_data.get("modifiers") or ()),
            )
        contract = feature_runtime_contract(
            feature_name=str(grant.get("name") or ""),
            class_name=str(grant.get("class_name") or ""),
            class_level=int(grant.get("class_level") or 0),
            kind=str(grant.get("kind") or "feature"),
            source_record_id=(
                str(grant["source_record_id"])
                if grant.get("source_record_id") is not None
                else None
            ),
            source_path=(
                str(grant["source_path"])
                if grant.get("source_path") is not None
                else None
            ),
            definition=definition,
            declared_status=(
                str(runtime_data.get("automation_status"))
                if runtime_data.get("automation_status") is not None
                else None
            ),
            note=(
                str(runtime_data.get("note"))
                if runtime_data.get("note") is not None
                else None
            ),
        )
        feature_contracts[contract["id"]] = contract

        combat_start = definition.get("combat_start")
        if isinstance(combat_start, Mapping):
            count = combat_start.get("attack_action_count")
            if isinstance(count, int):
                attack_action_count = max(attack_action_count, count)
            for raw in combat_start.get("modifiers") or ():
                if isinstance(raw, Mapping):
                    entry = deepcopy(dict(raw))
                    scaling_key = entry.get("scaling_key")
                    if isinstance(scaling_key, str) and scaling_key in scaling_values:
                        entry["value"] = scaling_values[scaling_key]
                    modifiers[str(entry.get("id") or len(modifiers))] = entry
            for raw in combat_start.get("defenses") or ():
                if isinstance(raw, Mapping):
                    entry = deepcopy(dict(raw))
                    defenses[str(entry.get("id") or len(defenses))] = entry

        raw_resources = definition.get("resources")
        if isinstance(raw_resources, Mapping):
            for key, raw in raw_resources.items():
                if isinstance(raw, Mapping):
                    resource_registry[str(key)] = deepcopy(dict(raw))

        for scaling_key in runtime_data.get("tracked_scaling_keys") or ():
            if not isinstance(scaling_key, str):
                continue
            raw_scaling = (scalings or {}).get(scaling_key)
            if not isinstance(raw_scaling, Mapping):
                continue
            resource_registry.setdefault(
                scaling_key,
                {
                    "key": scaling_key,
                    "resource_kind": "scaling",
                    **{
                        name: deepcopy(raw_scaling[name])
                        for name in (
                            "label",
                            "value",
                            "value_kind",
                            "source",
                            "automation_status",
                            "requires_dm_adjudication",
                        )
                        if name in raw_scaling
                    },
                },
            )

        raw_actions = definition.get("actions")
        if isinstance(raw_actions, Mapping):
            for key, raw in raw_actions.items():
                if isinstance(raw, Mapping):
                    entry = deepcopy(dict(raw))
                    class_name = str(entry.get("class_name") or "")
                    if entry.get("healing_formula") == "1d10+class_level":
                        entry["healing"] = f"1d10+{current_class_levels.get(class_name, 0)}"
                    if (
                        entry.get("damage_reduction_formula")
                        == "1d10+dexterity_modifier+class_level"
                    ):
                        entry["damage_reduction"] = (
                            "1d10+dexterity_modifier+"
                            f"{current_class_levels.get(class_name, 0)}"
                        )
                    dice_key = entry.get("dice_key")
                    if isinstance(dice_key, str):
                        dice = resource_registry.get(dice_key)
                        if isinstance(dice, Mapping) and dice.get("value") is not None:
                            entry["dice"] = dice["value"]
                    action_registry[str(key)] = entry

        for raw in definition.get("attack_riders") or ():
            if not isinstance(raw, Mapping):
                continue
            entry = deepcopy(dict(raw))
            scaling_key = entry.get("scaling_key")
            if isinstance(scaling_key, str) and scaling_key in scaling_values:
                entry["value"] = scaling_values[scaling_key]
            riders[str(entry.get("id") or len(riders))] = entry

    for key, value in current_resources.items():
        entry = _resource_entry(key, value)
        if key in resource_registry:
            preserved = {
                name: deepcopy(resource_registry[key][name])
                for name in ("recovery_events",)
                if name in resource_registry[key]
            }
            entry.update(preserved)
        resource_registry[key] = entry

    for raw in actions:
        if not isinstance(raw, Mapping):
            continue
        entry = deepcopy(dict(raw))
        key = str(entry.get("id") or entry.get("resource_key") or _identity(entry.get("name")))
        action_registry.setdefault(key, entry)

    contracts = list(feature_contracts.values())
    dm_only = [
        contract
        for contract in contracts
        if contract["automation_status"] == "dm_only"
    ]
    spell_slots = {
        key: deepcopy(value)
        for key, value in resource_registry.items()
        if key.startswith("spell_slots_")
    }

    return {
        "schema_version": FEATURE_RUNTIME_SCHEMA_VERSION,
        "progression": {
            "class_levels": dict(effective_class_levels),
            "total_level": effective_total_level or None,
            "proficiency_bonus": (
                2 + (min(20, effective_total_level) - 1) // 4
                if effective_total_level > 0
                else None
            ),
            "spell_slots": spell_slots,
        },
        "combat_start": {
            "attack_action_count": attack_action_count,
            "modifiers": list(modifiers.values()),
            "defenses": list(defenses.values()),
        },
        "resources": resource_registry,
        "actions": action_registry,
        "attack_riders": list(riders.values()),
        "feature_contracts": contracts,
        "dm_only": dm_only,
    }


def _feature_action_executor_ready(action: Mapping[str, Any]) -> bool:
    """Validate an explicitly partial action against the current executor.

    ``runtime_execution.status=ready`` means that the listed state mutation is
    deterministic today, not that every rule sentence is automated.  Keep the
    allow-list aligned with ``CombatEngineService.confirm_feature_action`` so a
    registry cannot expose an action button that the endpoint will reject.
    """

    execution = action.get("runtime_execution")
    if not isinstance(execution, Mapping):
        return False
    if execution.get("status") != "ready" or execution.get("consumer") != (
        "combat_feature_action"
    ):
        return False
    if action.get("action_cost") == "reaction":
        return False
    if action.get("resolution_kind") == "choice_required" and action.get("id") != (
        "cunning_action"
    ):
        return False
    effects = action.get("effects")
    effect_list = effects if isinstance(effects, list) else []
    effect_kinds = {
        str(effect.get("kind") or "")
        for effect in effect_list
        if isinstance(effect, Mapping)
    }
    supported = {
        "activate_condition",
        "activate_duration_condition",
        "activate_timed_condition",
        "grant_action_budget",
        "grant_saving_throw_reroll",
        "grant_roll_die",
        "cunning_action_choice",
        "temporary_healing",
        "healing",
        "condition_cure",
        "condition_removal",
    }
    if not effect_kinds or not effect_kinds <= supported:
        return False
    for effect in effect_list:
        if not isinstance(effect, Mapping):
            return False
        if effect.get("kind") == "activate_timed_condition" and not (
            effect.get("condition") in {"隐形", "reckless_attack", "steady_aim"}
            and effect.get("expires") in {"turn_start", "turn_end"}
        ):
            return False
        if effect.get("kind") == "activate_duration_condition" and not (
            effect.get("condition") in {"raging", "innate_sorcery", "superior_defense"}
            and effect.get("duration_unit") in {"rounds", "minutes"}
            and isinstance(effect.get("duration_value"), int)
            and effect.get("duration_value") >= 1
        ):
            return False
    declared = execution.get("effect_kinds")
    if isinstance(declared, list) and set(map(str, declared)) != effect_kinds:
        return False
    return True


def feature_runtime_action_projections(
    registry: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Expose executable class features through the normal combat action list.

    The registry is deliberately the source of truth here.  This projection is
    only a transport/UI shape; the combat endpoint still looks the feature up
    by ``feature_id`` in the immutable combat snapshot before applying it.
    Choice- or event-window-dependent entries remain in ``feature_contracts``
    for audit, but are not emitted as buttons that would predictably fail at
    confirmation. Keeping the projection next to the compiler prevents the
    sheet and the DM combat card from growing two different lists of class
    actions.
    """

    raw_actions = registry.get("actions")
    if not isinstance(raw_actions, Mapping):
        return []
    projections: list[dict[str, Any]] = []
    for feature_id, raw in raw_actions.items():
        if not isinstance(raw, Mapping) or raw.get("kind") != "feature_action":
            continue
        if raw.get("activation_window") in {
            "after_failed_saving_throw",
            "after_failed_d20_test",
        }:
            # Event-driven prompt, not a free-standing combat button.
            continue
        effects = raw.get("effects")
        needs_dm_choice = any(
            isinstance(effect, Mapping) and effect.get("kind") == "requires_dm_choice"
            for effect in (effects if isinstance(effects, list) else ())
        )
        executable_partial = _feature_action_executor_ready(raw)
        if needs_dm_choice or (
            raw.get("requires_dm_adjudication") and not executable_partial
        ):
            continue
        action = deepcopy(dict(raw))
        action["feature_id"] = str(feature_id)
        action["kind"] = "feature"
        action["runtime_feature"] = True
        action["cost"] = {
            "bonus_action": "附赠动作",
            "action": "动作",
            "reaction": "反应",
            "none": "特殊",
        }.get(str(action.get("action_cost") or "none"), "特殊")
        if action.get("resolution_kind") == "healing":
            healing = str(action.get("healing") or action.get("healing_formula") or "")
            action["healing"] = healing
            if action.get("resource_cost_mode") == "amount_or_condition":
                action["description"] = "职业特性：从资源池治疗，或消耗 5 点解除中毒/疾病"
            elif action.get("resource_cost_mode") == "amount":
                action["description"] = "职业特性：从资源池中消耗本次治疗数量并恢复生命"
            else:
                action["description"] = f"职业特性：恢复 {healing} 生命"
        elif action.get("resolution_kind") == "temporary_healing":
            healing = str(action.get("healing") or action.get("healing_formula") or "")
            action["healing"] = healing
            action["description"] = f"职业特性：投掷 {healing} 并获得临时生命值"
        elif action.get("resolution_kind") == "condition":
            action["description"] = str(action.get("summary") or "职业特性：施加临时战斗状态")
        elif action.get("resolution_kind") == "saving_throw_reroll":
            action["description"] = "职业特性：消耗一次资源，获得下一次失败豁免的重掷资格"
        elif action.get("resolution_kind") == "grant_dice":
            action["description"] = "职业特性：消耗资源，为目标记录一枚可在后续检定使用的激励骰"
        elif action.get("resolution_kind") == "condition_removal":
            action["description"] = "职业特性：回合结束时选择并移除一个已有的魅惑、恐慌或中毒状态"
        elif action.get("resolution_kind") == "choice_required":
            action["description"] = "职业特性：需要 DM 选择具体分支后执行"
        effects = action.get("effects")
        if isinstance(effects, list):
            conditions = [
                str(effect.get("condition"))
                for effect in effects
                if isinstance(effect, Mapping)
                and effect.get("kind") == "activate_condition"
                and effect.get("condition")
            ]
            if conditions and not action.get("summary"):
                action["description"] = f"职业特性：施加 {', '.join(conditions)} 状态"
        projections.append(action)
    return projections
