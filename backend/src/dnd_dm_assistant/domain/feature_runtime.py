from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from math import floor
from typing import Any

from dnd_dm_assistant.domain.feature_blocks import (
    feature_action_block_ready,
    feature_trigger_block_errors,
    resource_lifecycle_block_ready,
    resource_recovery_block_ready,
    structured_target_save_status,
)
from dnd_dm_assistant.domain.rule_blocks import (
    CLASS_FEATURE_BLOCK_SCHEMA_VERSION,
    ClassFeatureBlock,
)

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
_SPELLCASTING_CLASSES = frozenset(
    {
        "吟游诗人",
        "牧师",
        "德鲁伊",
        "术士",
        "法师",
        "圣武士",
        "游侠",
        "奇械师",
        "魔契师",
    }
)

# One source of truth for feature-condition lifecycle blocks.  The compiler
# gate and combat executor both consume this table, so a newly added feature
# state cannot become a UI button without a matching cleanup policy.
FEATURE_CONDITION_RUNTIME_SPECS: dict[str, dict[str, dict[str, Any]]] = {
    "activate_duration_condition": {
        "raging": {
            "state_name": "feature_raging",
            "duration_units": ["rounds", "minutes"],
        },
        "innate_sorcery": {
            "state_name": "feature_innate_sorcery",
            "duration_units": ["rounds", "minutes"],
        },
        "superior_defense": {
            "state_name": "superior_defense",
            "duration_units": ["rounds", "minutes"],
        },
        "starry_form": {
            "state_name": "feature_starry_form",
            "duration_units": ["minutes"],
        },
        "dragon_wings": {
            "state_name": "feature_dragon_wings",
            "duration_units": ["minutes"],
        },
    },
    "activate_timed_condition": {
        "隐形": {
            "state_name": "feature_invisible",
            "expires": ["turn_start", "turn_end"],
        },
        "reckless_attack": {
            "state_name": "feature_reckless_attack",
            "expires": ["turn_start", "turn_end"],
        },
        "steady_aim": {
            "state_name": "steady_aim",
            "expires": ["turn_start", "turn_end"],
        },
    },
}


def feature_condition_runtime_spec(
    effect_kind: str,
    condition: str,
) -> dict[str, Any] | None:
    """Return a copied lifecycle spec for one typed feature condition effect."""

    raw = FEATURE_CONDITION_RUNTIME_SPECS.get(effect_kind, {}).get(condition)
    return deepcopy(raw) if isinstance(raw, Mapping) else None


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
            next_value = resolve_resource_lifecycle_value(
                current,
                maximum=current_entry.get("max"),
                event=raw_event,
                condition=condition,
            )
            if next_value is None:
                continue
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


def resolve_resource_lifecycle_value(
    current: int,
    *,
    maximum: object,
    event: Mapping[str, Any],
    condition: object = None,
) -> int | None:
    """Apply one typed lifecycle event without mutating a resource store.

    Conditions are optional but, when present, are intentionally limited to
    state predicates used by the existing rules.  The resolver is generic:
    it does not branch on a class or feature identifier.
    """

    if not isinstance(current, int) or isinstance(current, bool) or current < 0:
        return None
    operation = str(event.get("operation") or "")
    if not resource_lifecycle_block_ready(
        {"key": "resource", "lifecycle_events": [{**dict(event), "trigger": "initiative_start"}]}
    ):
        return None
    if condition == "current_zero" and current != 0:
        return None
    if condition == "current_below_2":
        minimum = event.get("minimum")
        if not isinstance(minimum, int) or current >= minimum:
            return None
    if condition == "current_at_most_3":
        if current > 3:
            return None
    if condition not in {None, "current_zero", "current_below_2", "current_at_most_3"}:
        return None
    if operation == "set_to_max":
        next_value = maximum if isinstance(maximum, int) and not isinstance(maximum, bool) else None
    elif operation == "restore":
        amount = event.get("amount")
        next_value = (
            current + amount if isinstance(amount, int) and not isinstance(amount, bool) else None
        )
    elif operation == "set_to":
        value = event.get("value")
        next_value = value if isinstance(value, int) and not isinstance(value, bool) else None
    elif operation == "set_to_minimum":
        minimum = event.get("minimum")
        next_value = minimum if isinstance(minimum, int) and not isinstance(minimum, bool) else None
    else:
        return None
    if next_value is None:
        return None
    if isinstance(maximum, int) and not isinstance(maximum, bool):
        next_value = min(next_value, maximum)
    return max(0, next_value)


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
        elif formula == "10+dexterity_modifier+charisma_modifier":
            constitution_key = "charisma"
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
                    (
                        "体质"
                        if constitution_key == "constitution"
                        else "感知"
                        if constitution_key == "wisdom"
                        else "魅力"
                    ),
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
                skipped.append(
                    {
                        **record,
                        "reason": "wearing_armor_or_wielding_shield",
                    }
                )
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
        "die_size",
        "resource_kind",
        "automation_status",
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
        "triggers": [],
        "attack_riders": [],
    }
    if identity == "施法" and class_identity in _SPELLCASTING_CLASSES:
        # Spell slots, spell selection, and spell execution already share the
        # character spell-economy service.  This typed capability block records
        # that the class feature is the source of that capability; it does not
        # infer a spell list or bypass the existing slot/selection validators.
        definition["spellcasting"] = {
            "kind": "spellcasting_capability",
            "class_name": class_name,
            "consumer": "spell_economy_service",
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }

    if identity in {"专业预言", "expertdivination"}:
        definition["actions"]["expert_divination_slot_recovery"] = {
            "id": "expert_divination_slot_recovery",
            "name": feature_name,
            "kind": "spell_slot_recovery",
            "activation_window": "after_spell_cast",
            "requirements": [
                "divination_spell_level_at_least_2",
                "recovery_slot_lower_than_cast_slot",
                "recovery_slot_level_at_most_5",
            ],
            "input_requirements": [
                {
                    "key": "recovery_slot_level",
                    "kind": "player_or_dm_choice",
                    "minimum": 1,
                    "maximum": 5,
                }
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "spell_economy_service",
                "persistent_state": "spellcasting.slots",
                "idempotency": "spell_cast_operation",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": (
                "施放二环以上预言法术后，由玩家/DM选择一个低于施法环阶"
                "且不超过五环的已消耗法术位恢复。"
            ),
            **source,
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

    fixed_ability_adjustments = {
        "原初斗士": {"strength": 4, "constitution": 4},
        "天人合一": {"dexterity": 4, "wisdom": 4},
    }.get(identity)
    if fixed_ability_adjustments is not None:
        # These level-20 grants are not player choices or combat-only
        # modifiers.  The advancement transaction applies the declared
        # adjustments and raised caps to the authoritative character sheet;
        # downstream HP, attack, saving-throw, and skill consumers then read
        # the resulting ability scores normally.
        definition["advancement"] = {
            "kind": "fixed_ability_score_adjustment",
            "adjustments": fixed_ability_adjustments,
            "caps": {ability: 25 for ability in fixed_ability_adjustments},
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }

    mystic_arcanum_levels = {
        "玄奥秘法六环": 6,
        "玄奥秘法七环": 7,
        "玄奥秘法八环": 8,
        "玄奥秘法九环": 9,
    }
    mystic_arcanum_level = mystic_arcanum_levels.get(identity)
    if mystic_arcanum_level is not None and class_identity in {"魔契师", "warlock"}:
        resource_key = f"mystic_arcanum_{mystic_arcanum_level}"
        resource = definition["resources"].get(resource_key)
        if isinstance(resource, dict):
            resource.update(
                {
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    "note": "所选秘法由受控法术选择授予；免费施放消耗该资源并在长休恢复。",
                }
            )
        definition["advancement"] = {
            "kind": "selected_spell_grant",
            "selection_key": resource_key,
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service_and_player_action_resolution",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }

    scaling_keys = set(tracked_scaling_keys)
    resource_keys = set(tracked_resource_keys)

    if identity.startswith("信实坐骑") and "faithful_steed" in resource_keys:
        resource = definition["resources"].get("faithful_steed")
        if isinstance(resource, dict):
            resource.update(
                {
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    "note": "寻获坐骑始终准备；免费施法每次长休恢复一次。",
                }
            )
        definition["advancement"] = {
            "kind": "fixed_spell_grant",
            "spells": ["寻获坐骑"],
            "grant_class": "owner_class",
            "casting_ability": "charisma",
            "free_cast_resource_key": "faithful_steed",
            "runtime_execution": {
                "status": "ready",
                "consumer": "advancement_service_and_spell_economy_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }

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
                },
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
                    "condition": "current_at_most_3",
                },
            ]
            resource.update(
                {
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    "note": "先攻开始时功力低于4点会自动恢复至4点。",
                }
            )

    if (
        identity in {"百折不挠", "survivor"}
        or identity.startswith("百折不挠")
        or "survivor" in identity
    ):
        # Survivor has no spendable pool.  Both clauses are represented as
        # typed combat contracts: the death-save resolver consumes the
        # advantage/18–20 rule, while the turn boundary consumes the bloodied
        # healing trigger.
        definition["combat_start"]["defenses"].extend(
            [
                {
                    "id": "survivor:death_save_advantage",
                    "kind": "death_save_advantage",
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    **source,
                },
                {
                    "id": "survivor:death_save_18_is_20",
                    "kind": "death_save_success_threshold",
                    "minimum_roll": 18,
                    "treat_as": 20,
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    **source,
                },
            ]
        )
        definition["triggers"].append(
            {
                "id": "survivor:turn_start_bloodied_healing",
                "event": "turn_start",
                "effects": [
                    {
                        "kind": "restore_hit_points_if_bloodied",
                        "amount": 5,
                        "ability_modifier": "constitution",
                        "minimum": 1,
                    }
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "turn_start_feature_healing",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                **source,
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
                },
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
            "effects": [
                {
                    "kind": "activate_duration_condition",
                    "condition": "raging",
                    "duration_unit": "minutes",
                    "duration_value": 1,
                }
            ],
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
                "required_conditions": ["raging"],
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
            "adjudicated_actions": ["hide"],
            "input_requirements": [
                {
                    "key": "outcome",
                    "kind": "dm_outcome",
                    "required_for": ["hide"],
                }
            ],
            "effects": [
                {
                    "kind": "cunning_action_choice",
                }
            ],
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action",
                "effect_kinds": ["cunning_action_choice"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "三个分支均由配置驱动；躲藏的成功/失败由 DM 输入后写入真实隐匿状态。",
            **source,
        }

    if identity in {"战术转进", "tacticalshift"}:
        definition["triggers"].append(
            {
                "id": "tactical_shift:after_second_wind",
                "event": "after_feature_action",
                "action_id": "second_wind",
                "effects": [
                    {"kind": "grant_movement_budget", "amount_source": "half_current_speed"},
                    {"kind": "grant_disengage", "expires": "turn_end"},
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "feature_action_trigger_resolver",
                    "effect_kinds": ["grant_movement_budget", "grant_disengage"],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "使用回气后获得半速移动且不引发借机攻击。",
                **source,
            }
        )

    if identity in {"莽驰", "instinctivepounce"}:
        definition["triggers"].append(
            {
                "id": "instinctive_pounce:after_rage",
                "event": "after_feature_action",
                "action_id": "rage",
                "effects": [
                    {"kind": "grant_movement_budget", "amount_source": "half_current_speed"}
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "feature_action_trigger_resolver",
                    "effect_kinds": ["grant_movement_budget"],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "进入狂暴时获得至多半速移动。",
                **source,
            }
        )

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
            "effects": [],
            "trigger": {
                "event": "attacker_hits_self",
                "timing": "before_damage",
                "requirements": ["attacker_visible"],
            },
            "pre_damage_intervention": {
                "kind": "pre_damage_intervention",
                "eligibility": {
                    "entity_types": ["character"],
                    "damage_types": "all",
                    "forbidden_conditions": ["incapacitated"],
                },
                "input_requirements": [],
                "damage_transform": {
                    "operation": "multiply_each_component",
                    "multiplier": 0.5,
                    "rounding": "floor",
                },
            },
            "damage_multiplier": 0.5,
            "runtime_execution": {
                "status": "ready",
                "consumer": "pre_damage_reaction_window",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "可见攻击者命中后打开玩家反应窗口；接受时逐段减半并消费反应。",
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
            "effects": [],
            "trigger": {"event": "attacker_hits_self", "timing": "before_damage"},
            "pre_damage_intervention": {
                "kind": "pre_damage_intervention",
                "eligibility": {
                    "entity_types": ["character"],
                    "damage_types": (
                        "all" if deflects_all_damage else ["bludgeoning", "piercing", "slashing"]
                    ),
                    "forbidden_conditions": ["incapacitated"],
                },
                "input_requirements": [
                    {"key": "reduction_roll", "kind": "die_roll", "die_sides": 10}
                ],
                "damage_transform": {
                    "operation": "subtract_total",
                    "amount": "reduction_roll+dexterity_modifier+class_level",
                    "distribution": "components_in_order",
                    "minimum": 0,
                },
                "follow_up": {"kind": "deflect_redirect_adapter"},
            },
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
                "status": "ready",
                "consumer": "pre_damage_reaction_window",
                "consumer_steps": [
                    "focus_consumption",
                    "target_selection_within_range",
                    "dexterity_save",
                    "redirect_damage",
                ],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": (
                "命中后持久化收集减伤骰；归零时继续收集反击目标、豁免与伤害骰，"
                "并原子消费反应和功力。"
            ),
            **source,
        }

    if identity in {"轻身坠", "slowfall"}:
        definition["actions"]["slow_fall"] = {
            "id": "slow_fall",
            "name": feature_name,
            "kind": "feature_action",
            "action_cost": "reaction",
            "target": "self",
            "resolution_kind": "choice_required",
            "effects": [],
            "trigger": {"event": "takes_fall_damage", "timing": "before_damage"},
            "pre_damage_intervention": {
                "kind": "pre_damage_intervention",
                "eligibility": {
                    "entity_types": ["character"],
                    "damage_tags_all": ["fall"],
                    "forbidden_conditions": ["incapacitated"],
                },
                "input_requirements": [],
                "damage_transform": {
                    "operation": "subtract_total",
                    "amount": "class_level*5",
                    "distribution": "components_in_order",
                    "minimum": 0,
                },
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "pre_damage_reaction_window",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "坠落伤害落地前打开反应窗口，并按武僧等级×5减少伤害。",
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
            "effects": [{"kind": "grant_action_budget", "amount": 1, "excludes": ["magic_action"]}],
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

    if "圣疗" in identity or "复原之触" in identity or "layonhands" in identity:
        if "lay_on_hands" in resource_keys:
            condition_cure_options = ["poisoned", "diseased"]
            if "复原之触" in identity:
                condition_cure_options = [
                    "blinded",
                    "charmed",
                    "deafened",
                    "frightened",
                    "paralyzed",
                    "poisoned",
                    "stunned",
                ]
            definition["actions"]["lay_on_hands"] = {
                "id": "lay_on_hands",
                "name": feature_name,
                "kind": "feature_action",
                "action_cost": "bonus_action",
                "resource_key": "lay_on_hands",
                "resource_cost": 0,
                "resource_cost_mode": "amount_or_condition",
                "condition_cure_cost": 5,
                "condition_cure_options": condition_cure_options,
                "target": "ally_or_self",
                "target_policy": {
                    "mode": "ally_or_self",
                    "same_faction": True,
                    "range_ft": 5,
                },
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
                "target_policy": {
                    "mode": "ally_or_self",
                    "same_faction": True,
                    "range_ft": 60,
                    "requires_visible_or_audible": True,
                    "allow_self": False,
                },
                "resolution_kind": "grant_dice",
                "dice_key": "bardic_inspiration_die",
                "effects": [{"kind": "grant_roll_die", "die_key": "bardic_inspiration_die"}],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "combat_feature_action_and_player_roll_resolution",
                    "effect_kinds": ["grant_roll_die"],
                    "window": {
                        "phase": "after_failed_d20_test",
                        "expires": "duration_end",
                        "duration_unit": "hours",
                        "duration_value": 1,
                    },
                    "covered_rules": [
                        "target_range_visibility_or_audibility",
                        "one_die_per_target",
                        "failed_d20_consumption_window",
                    ],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
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
            "runtime_execution": {
                "status": "ready",
                "consumer": "saving_throw_reaction_window",
                "effect_kinds": ["saving_throw_reroll"],
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
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

    if identity in {"术法复苏", "sorceryrestoration"} and "sorcery_restoration" in resource_keys:
        definition["actions"]["sorcery_restoration"] = {
            "id": "sorcery_restoration",
            "name": feature_name,
            "kind": "rest_recovery",
            "trigger": "short_rest",
            "resource_key": "sorcery_restoration",
            "resource_cost": 1,
            "restore_resource_key": "sorcery_points",
            "maximum_amount_formula": "half_class_level_floor",
            "reset_trigger": "long_rest",
            "runtime_execution": {
                "status": "ready",
                "consumer": "rest_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "短休结束时可选择恢复不超过术士等级一半的术法点；使用权长休恢复。",
            **source,
        }

    if identity in {"秘法回流", "magicalcunning"} and "magical_cunning" in resource_keys:
        definition["actions"]["magical_cunning"] = {
            "id": "magical_cunning",
            "name": feature_name,
            "kind": "ritual_recovery",
            "trigger": "one_minute_ritual",
            "resource_key": "magical_cunning",
            "resource_cost": 1,
            "restore_resource_key": "pact_slots",
            "amount_formula": "half_expended_round_up",
            "reset_trigger": "long_rest",
            "runtime_execution": {
                "status": "ready",
                "consumer": "feature_recovery_service",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "完成一分钟秘传仪式后恢复一半已消耗的契约魔法法术位（向上取整）。",
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
                "applies_when": ("dexterity_saving_throw_for_half_damage_and_not_incapacitated"),
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
                    "明确失手后，为同一目标的下一次攻击真实提供优势，并在下一回合结束时清理。"
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
                "required_conditions": ["superior_defense"],
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
                "kind": "zero_hp_intervention",
                "trigger": "would_drop_to_zero_hit_points",
                "eligibility": {
                    "entity_types": ["character"],
                    "required_conditions": ["raging"],
                    "level": {
                        "class_names": ["野蛮人", "barbarian"],
                        "minimum": 1,
                        "bind_as": "barbarian_level",
                    },
                },
                "saving_throw": {
                    "ability": "constitution",
                    "initial_dc": 10,
                    "increase_after_success": 5,
                },
                "success": {
                    "kind": "restore_hit_points",
                    "amount": "2*barbarian_level",
                },
                "failure": {"kind": "continue_zero_hp_lifecycle"},
                "exceptions": ["outright_death"],
                "state": {
                    "key": "relentless_rage_state",
                    "current_dc_field": "current_dc",
                    "reset_reason": "short_or_long_rest",
                },
                "resets": ["short_rest", "long_rest"],
                "presentation": {
                    "action_name": "坚韧狂暴",
                    "description": "降至 0 HP；请进行体质豁免以维持生命。",
                    "result_key": "relentless_rage",
                    "prompt_idempotency_prefix": "relentless-rage-save",
                    "prompt_result_id_key": "relentless_rage_save_prompt_id",
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "zero_hp_intervention",
                    "effect_kinds": ["saving_throw_prompt", "restore_hit_points"],
                    "exceptions": ["outright_death"],
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
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
                "ranged_passive": {
                    "range_group": "paladin_aura_radius",
                    "stacking_group": "aura_of_protection_saving_throw",
                    "source_scope": "self",
                    "target_relation": "self_and_allies",
                    "range_ft": 10,
                    "requires_grid_position_for_others": True,
                    "source_forbidden_conditions": ["incapacitated"],
                    "stacking": "best",
                    "effect_kind": "numeric_modifier",
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "saving_throw_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": (
                    "同阵营单位在圣武士 10 尺内进行豁免时，加入圣武士魅力调整值（最低 +1）。"
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
                "ranged_passive": {
                    "range_group": "paladin_aura_radius",
                    "source_scope": "self",
                    "target_relation": "self_and_allies",
                    "range_ft": 10,
                    "requires_grid_position_for_others": True,
                    "source_forbidden_conditions": ["incapacitated"],
                    "stacking": "unique_source",
                    "effect_kind": "condition_immunity",
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "condition_immunity_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": (
                    "同阵营单位在圣武士 10 尺内获得恐慌免疫；距离或阵营变化后即时重新判断。"
                ),
                **source,
            }
        )

    if identity in {"灵光增效", "auraexpansion", "auraenhancement"}:
        definition["combat_start"]["defenses"].append(
            {
                "id": "aura_enhancement:range_override",
                "kind": "ranged_passive_range_override",
                "applies_to": "range_group",
                "target_range_group": "paladin_aura_radius",
                "range_ft": 30,
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "ranged_passive_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "由通用范围被动执行器将该来源的结构化灵光范围扩大到30尺。",
                **source,
            }
        )

    if identity in {"战术思维", "tacticalmind"}:
        definition["actions"]["tactical_mind"] = {
            "id": "tactical_mind",
            "name": feature_name,
            "kind": "roll_intervention",
            "trigger": "after_failed_d20_test",
            "eligibility": {
                "entity_types": ["character"],
                "test_kinds": ["ability_check"],
                "resource": {"key": "second_wind", "minimum": 1},
            },
            "input_requirements": [{"key": "tactical_die", "kind": "die_roll", "die_sides": 10}],
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
            "idempotency": {"prefix": "roll-intervention"},
            "runtime_execution": {
                "status": "ready",
                "consumer": "player_roll_resolution",
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
            "summary": "属性检定失败后输入1d10；仅补救成功时消耗一次回气。",
            **source,
        }

    if identity in {"万事通", "jackofalltrades"}:
        definition["combat_start"]["modifiers"].append(
            {
                "id": "jack_of_all_trades:ability_check",
                "stat": "ability_check",
                "operation": "add",
                "scope": "self",
                "value_source": "half_proficiency_bonus",
                "applies_when": "ability_check_without_proficiency",
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "player_roll_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
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

    if identity in {"震慑拳", "stunningstrike"}:
        definition["attack_riders"].append(
            {
                "id": "stunning_strike:post_hit_save",
                "kind": "post_hit_rider",
                "trigger": "after_hit",
                "frequency": "once_per_turn",
                "activation": {
                    "input_key": "activate_stunning_strike",
                    "label": "消耗1点功力发动震慑拳",
                },
                "eligibility": {
                    "actor_entity_types": ["character"],
                    "target_relations": ["enemy"],
                    "action_tags_any": ["unarmed", "monk_weapon"],
                    "actor_level": {"class_names": ["武僧", "monk"], "minimum": 5},
                },
                "resource": {"key": "focus", "amount": 1},
                "saving_throw": {
                    "ability": "constitution",
                    "dc_source": "feature_save_dc",
                    "dc_ability": "wisdom",
                    "input_key": "stunning_strike_save_total",
                },
                "on_save_failure": [
                    {
                        "id": "stunning_strike:stunned",
                        "kind": "condition",
                        "operation": "apply",
                        "condition": "stunned",
                        "duration": {"unit": "until_source_turn_start"},
                    }
                ],
                "on_save_success": [
                    {
                        "id": "stunning_strike:half_speed",
                        "kind": "modifier",
                        "stat": "speed_ft",
                        "operation": "set",
                        "value_source": "half_current",
                        "duration": {"unit": "until_source_turn_start"},
                    },
                    {
                        "id": "stunning_strike:next_attack_advantage",
                        "kind": "modifier",
                        "stat": "attack_roll",
                        "scope": "incoming",
                        "operation": "advantage",
                        "duration": {"unit": "until_next_attack"},
                    },
                ],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "post_hit_rider_follow_up",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "命中后持久化发动与体质豁免窗口，并原子消费功力和写入结果。",
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
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_damage_resolution",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
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
                "effect_names": ["猎人印记", "hunter's mark", "hunters_mark"],
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "concentration_check_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "专注于结构化猎人印记时，受到伤害不会创建专注豁免窗口。",
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
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "attack_context_resolver",
                    "eligibility": "actor_state_target_id",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": (
                    "仅当权威快照绑定的猎人印记目标一致时，攻击自动获得优势；缺少绑定则不生效。"
                ),
                **source,
            }
        )

    if identity in {"屠灭众敌", "foeslayer"}:
        definition["attack_riders"].append(
            {
                "id": "foe_slayer:hunter_mark_damage",
                "kind": "post_hit_rider",
                "trigger": "after_hit",
                "frequency": "each_eligible_hit",
                "eligibility": {
                    "target_relations": ["enemy"],
                    "action_tags_any": ["attack", "weapon", "unarmed", "spell_attack"],
                    "actor_state_target_id_keys": ["current_hunters_mark_target_id"],
                },
                "damage": {
                    "id": "hunter_mark_damage",
                    "expression": "1d10",
                    "damage_type": "force",
                    "input_key": "foe_slayer_total",
                },
                "runtime_execution": {
                    "status": "ready",
                    "consumer": "post_hit_rider_resolver",
                },
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "summary": "命中已由权威状态绑定的猎人印记目标后，校验并加入1d10力场伤害。",
                **source,
            }
        )

    return definition


def _entry_automation_status(entry: Mapping[str, Any]) -> str:
    """Return the conservative status for one typed runtime entry."""

    if entry.get("event") is not None and feature_trigger_block_errors(entry):
        return "partial"
    runtime = entry.get("runtime")
    runtime_data = runtime if isinstance(runtime, Mapping) else {}
    status = str(entry.get("automation_status") or runtime_data.get("automation_status") or "full")
    if status not in _AUTOMATION_STATUSES:
        status = "partial"
    effects = entry.get("effects")
    needs_choice = any(
        isinstance(effect, Mapping) and effect.get("kind") == "requires_dm_choice"
        for effect in (effects if isinstance(effects, list) else ())
    )
    if (
        entry.get("requires_dm_adjudication")
        or runtime_data.get("requires_dm_adjudication")
        or needs_choice
    ) and status == "full":
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
        if combat_start.get("movement_modes"):
            sections.append("movement_modes")
        if combat_start.get("first_turn_movement"):
            sections.append("first_turn_movement")
    if definition.get("resources"):
        sections.append("resources")
    if definition.get("actions"):
        sections.append("actions")
    if definition.get("triggers"):
        sections.append("triggers")
    if definition.get("attack_riders"):
        sections.append("attack_riders")
    if definition.get("spellcasting"):
        sections.append("spellcasting")
    if definition.get("proficiencies"):
        sections.append("proficiencies")
    if isinstance(definition.get("advancement"), Mapping):
        sections.append("advancement")
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
        definition.get("triggers") or (),
        definition.get("attack_riders") or (),
        definition.get("proficiencies") or (),
        (definition.get("advancement"),),
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
            *list(combat_start.get("movement_modes") or ()),
            *list(combat_start.get("first_turn_movement") or ()),
        )
        for raw in entries:
            if isinstance(raw, Mapping):
                statuses.append(_entry_automation_status(raw))
        if isinstance(combat_start.get("attack_action_count"), int):
            statuses.append("full")
    for raw_resources in (definition.get("resources"), definition.get("actions")):
        if isinstance(raw_resources, Mapping):
            for raw in raw_resources.values():
                if not isinstance(raw, Mapping):
                    continue
                entry_status = _entry_automation_status(raw)
                resources_section = raw_resources is definition.get("resources")
                if resources_section and (
                    not resource_recovery_block_ready(raw)
                    or not resource_lifecycle_block_ready(raw)
                ):
                    entry_status = "partial"
                if not resources_section and not structured_target_save_status(raw):
                    entry_status = "partial"
                statuses.append(entry_status)
    for raw_trigger in definition.get("triggers") or ():
        if isinstance(raw_trigger, Mapping):
            statuses.append(_entry_automation_status(raw_trigger))
    for raw in definition.get("attack_riders") or ():
        if isinstance(raw, Mapping):
            statuses.append(_entry_automation_status(raw))
    for raw in definition.get("proficiencies") or ():
        if isinstance(raw, Mapping):
            statuses.append(_entry_automation_status(raw))
    advancement = definition.get("advancement")
    if isinstance(advancement, Mapping):
        statuses.append(_entry_automation_status(advancement))
    prepared_spell_list = definition.get("prepared_spell_list")
    if isinstance(prepared_spell_list, Mapping):
        statuses.append(_entry_automation_status(prepared_spell_list))
    spellcasting = definition.get("spellcasting")
    if isinstance(spellcasting, Mapping):
        statuses.append(_entry_automation_status(spellcasting))

    normalized_declared = declared_status if declared_status in _AUTOMATION_STATUSES else None
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
        or definition.get("spellcasting")
    )


def _class_feature_block_identity(
    block_type: str,
    key: str,
    payload: Mapping[str, Any],
) -> tuple[str, str, int, str | None]:
    """Extract stable feature metadata without inferring rules from prose."""

    feature_name = str(payload.get("feature_name") or payload.get("name") or key).strip() or key
    class_name = str(payload.get("class_name") or "unclassified").strip() or "unclassified"
    raw_level = payload.get("class_level", 0)
    try:
        class_level = max(0, min(20, int(raw_level)))
    except (TypeError, ValueError):
        class_level = 0
    source_record_id = payload.get("source_record_id")
    source = str(source_record_id).strip() if source_record_id is not None else None
    return feature_name, class_name, class_level, source or None


def _stable_class_feature_block_id(
    block_type: str,
    key: str,
    payload: Mapping[str, Any],
) -> str:
    feature_name, class_name, class_level, source_record_id = _class_feature_block_identity(
        block_type, key, payload
    )
    identity = json.dumps(
        {
            "block_type": block_type,
            "key": key,
            "feature_name": feature_name,
            "class_name": class_name,
            "class_level": class_level,
            "source_record_id": source_record_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return f"class-feature:{block_type}:{digest}"


def compile_class_feature_blocks(registry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compile all legacy feature sections into one canonical block list.

    This is a transport/compiler boundary, not a second executor.  Each block
    retains the original typed payload so existing runtime consumers and the
    audit UI can migrate independently while receiving the same rule facts.
    """

    sources: list[tuple[str, str, Mapping[str, Any]]] = []
    combat_start = registry.get("combat_start")
    if isinstance(combat_start, Mapping):
        for index, raw in enumerate(combat_start.get("modifiers") or ()):
            if isinstance(raw, Mapping):
                sources.append(("modifier", str(raw.get("id") or index), raw))
        for index, raw in enumerate(combat_start.get("defenses") or ()):
            if isinstance(raw, Mapping):
                sources.append(("defense", str(raw.get("id") or index), raw))

    raw_resources = registry.get("resources")
    if isinstance(raw_resources, Mapping):
        for key, raw in raw_resources.items():
            if isinstance(raw, Mapping):
                sources.append(("resource", str(key), raw))

    raw_actions = registry.get("actions")
    if isinstance(raw_actions, Mapping):
        for key, raw in raw_actions.items():
            if isinstance(raw, Mapping):
                sources.append(("action", str(key), raw))

    for index, raw in enumerate(registry.get("attack_riders") or ()):
        if isinstance(raw, Mapping):
            sources.append(("attack_rider", str(raw.get("id") or index), raw))

    blocks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for block_type, key, raw in sources:
        payload = deepcopy(dict(raw))
        feature_name, class_name, class_level, source_record_id = _class_feature_block_identity(
            block_type, key, payload
        )
        block_id = _stable_class_feature_block_id(block_type, key, payload)
        if block_id in seen_ids:
            continue
        seen_ids.add(block_id)
        status = _entry_automation_status(payload)
        block = ClassFeatureBlock(
            id=block_id,
            block_type=block_type,  # type: ignore[arg-type]
            feature_name=feature_name,
            class_name=class_name,
            class_level=class_level,
            payload=payload,
            automation_status=status,  # type: ignore[arg-type]
            requires_dm_adjudication=status != "full",
            runtime_execution=(
                deepcopy(dict(payload["runtime_execution"]))
                if isinstance(payload.get("runtime_execution"), Mapping)
                else None
            ),
            source_record_id=source_record_id,
        )
        blocks.append(block.model_dump(mode="json"))
    return blocks


def feature_block_payloads(
    registry: Mapping[str, Any],
    block_type: str,
) -> list[dict[str, Any]]:
    """Read validated canonical payloads for a runtime consumer.

    Invalid or unknown blocks are ignored deliberately.  A malformed snapshot
    must not grant a feature effect merely because it contains a matching key.
    """

    raw_blocks = registry.get("feature_blocks")
    if not isinstance(raw_blocks, list):
        return []
    payloads: list[dict[str, Any]] = []
    for raw in raw_blocks:
        if not isinstance(raw, Mapping):
            continue
        try:
            block = ClassFeatureBlock.model_validate(dict(raw), strict=True)
        except Exception:
            continue
        if block.block_type == block_type:
            payloads.append(deepcopy(dict(block.payload)))
    return payloads


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
    effective_total_level = (
        explicit_total if explicit_total > 0 else sum(effective_class_levels.values())
    )

    modifiers: dict[str, dict[str, Any]] = {}
    defenses: dict[str, dict[str, Any]] = {}
    resource_registry: dict[str, dict[str, Any]] = {}
    action_registry: dict[str, dict[str, Any]] = {}
    spellcasting_registry: list[dict[str, Any]] = []
    trigger_registry: list[dict[str, Any]] = []
    riders: dict[str, dict[str, Any]] = {}
    rider_overlays: list[dict[str, Any]] = []
    action_overlays: list[dict[str, Any]] = []
    proficiency_registry: list[dict[str, Any]] = []
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
                str(grant["source_path"]) if grant.get("source_path") is not None else None
            ),
            definition=definition,
            declared_status=(
                str(runtime_data.get("automation_status"))
                if runtime_data.get("automation_status") is not None
                else (
                    str(definition.get("automation_status"))
                    if definition.get("automation_status") is not None
                    else None
                )
            ),
            note=(str(runtime_data.get("note")) if runtime_data.get("note") is not None else None),
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
                            f"1d10+dexterity_modifier+{current_class_levels.get(class_name, 0)}"
                        )
                    dice_key = entry.get("dice_key")
                    if isinstance(dice_key, str):
                        dice = resource_registry.get(dice_key)
                        if isinstance(dice, Mapping) and dice.get("value") is not None:
                            entry["dice"] = dice["value"]
                    action_registry[str(key)] = entry

        raw_spellcasting = definition.get("spellcasting")
        if isinstance(raw_spellcasting, Mapping):
            spellcasting_registry.append(deepcopy(dict(raw_spellcasting)))

        for raw_proficiency in definition.get("proficiencies") or ():
            if isinstance(raw_proficiency, Mapping):
                proficiency_registry.append(deepcopy(dict(raw_proficiency)))

        for raw_trigger in definition.get("triggers") or ():
            if isinstance(raw_trigger, Mapping):
                trigger_registry.append(deepcopy(dict(raw_trigger)))

        for raw in definition.get("attack_riders") or ():
            if not isinstance(raw, Mapping):
                continue
            entry = deepcopy(dict(raw))
            scaling_key = entry.get("scaling_key")
            if isinstance(scaling_key, str) and scaling_key in scaling_values:
                entry["value"] = scaling_values[scaling_key]
            riders[str(entry.get("id") or len(riders))] = entry
        for raw_overlay in definition.get("attack_rider_overlays") or ():
            if isinstance(raw_overlay, Mapping):
                rider_overlays.append(deepcopy(dict(raw_overlay)))
        for raw_overlay in definition.get("action_overlays") or ():
            if isinstance(raw_overlay, Mapping):
                action_overlays.append(deepcopy(dict(raw_overlay)))

    # Apply declared typed overlays after all feature grants have been merged.
    # This supports subclass enhancements such as adding a condition to an
    # existing rider without introducing feature-ID branches in the executor.
    for overlay in rider_overlays:
        target_id = str(overlay.get("target_id") or "").strip()
        target = riders.get(target_id)
        if not target_id or target is None:
            continue
        for field in ("on_hit", "on_save_success", "on_save_failure"):
            additions = overlay.get(field)
            if not isinstance(additions, list):
                continue
            existing = target.get(field)
            merged = list(existing) if isinstance(existing, list) else []
            existing_ids = {
                str(item.get("id") or "") for item in merged if isinstance(item, Mapping)
            }
            for item in additions:
                if not isinstance(item, Mapping):
                    continue
                item_id = str(item.get("id") or "").strip()
                if item_id and item_id in existing_ids:
                    continue
                merged.append(deepcopy(dict(item)))
                if item_id:
                    existing_ids.add(item_id)
            target[field] = merged

    for overlay in action_overlays:
        target_id = str(overlay.get("target_id") or "").strip()
        target = action_registry.get(target_id)
        if not target_id or target is None:
            continue
        for field in ("condition_cure_options",):
            additions = overlay.get(field)
            if not isinstance(additions, list):
                continue
            existing = target.get(field)
            merged = list(existing) if isinstance(existing, list) else []
            for item in additions:
                value = str(item).strip()
                if value and value not in merged:
                    merged.append(value)
            target[field] = merged

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
    dm_only = [contract for contract in contracts if contract["automation_status"] == "dm_only"]
    spell_slots = {
        key: deepcopy(value)
        for key, value in resource_registry.items()
        if key.startswith("spell_slots_")
    }

    registry = {
        "schema_version": FEATURE_RUNTIME_SCHEMA_VERSION,
        "feature_block_schema_version": CLASS_FEATURE_BLOCK_SCHEMA_VERSION,
        "progression": {
            "class_levels": dict(effective_class_levels),
            "total_level": effective_total_level or None,
            "proficiency_bonus": (
                2 + (min(20, effective_total_level) - 1) // 4 if effective_total_level > 0 else None
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
        "spellcasting": spellcasting_registry,
        "proficiencies": proficiency_registry,
        "triggers": trigger_registry,
        "attack_riders": list(riders.values()),
        "feature_contracts": contracts,
        "dm_only": dm_only,
    }
    registry["feature_blocks"] = compile_class_feature_blocks(registry)
    return registry


def _feature_action_executor_ready(action: Mapping[str, Any]) -> bool:
    """Validate an explicitly partial action against the current executor.

    ``runtime_execution.status=ready`` means that the listed state mutation is
    deterministic today, not that every rule sentence is automated.  Keep the
    allow-list aligned with ``CombatEngineService.confirm_feature_action`` so a
    registry cannot expose an action button that the endpoint will reject.
    """

    if not feature_action_block_ready(action):
        return False
    execution = action.get("runtime_execution")
    if not isinstance(execution, Mapping):
        return False
    if execution.get("status") != "ready" or execution.get("consumer") != ("combat_feature_action"):
        return False
    if action.get("action_cost") == "reaction":
        return False
    if action.get("resolution_kind") == "choice_required" and not action.get("allowed_actions"):
        return False
    effects = action.get("effects")
    effect_list = effects if isinstance(effects, list) else []
    effect_kinds = {
        str(effect.get("kind") or "") for effect in effect_list if isinstance(effect, Mapping)
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
        effect_kind = str(effect.get("kind") or "")
        condition = str(effect.get("condition") or "")
        spec = feature_condition_runtime_spec(effect_kind, condition)
        if effect_kind == "activate_timed_condition" and not (
            spec is not None and effect.get("expires") in spec.get("expires", ())
        ):
            return False
        if effect_kind == "activate_duration_condition" and not (
            spec is not None
            and effect.get("duration_unit") in spec.get("duration_units", ())
            and isinstance(effect.get("duration_value"), int)
            and effect.get("duration_value") >= 1
        ):
            return False
    resource = action.get("resource")
    if isinstance(resource, Mapping) and not resource_recovery_block_ready(resource):
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
    canonical_actions = feature_block_payloads(registry, "action")
    if canonical_actions:
        raw_actions = {
            str(item.get("id") or item.get("resource_key") or index): item
            for index, item in enumerate(canonical_actions)
        }
    elif not isinstance(raw_actions, Mapping):
        raw_actions = {}
    if not raw_actions:
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
        if needs_dm_choice or (raw.get("requires_dm_adjudication") and not executable_partial):
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
