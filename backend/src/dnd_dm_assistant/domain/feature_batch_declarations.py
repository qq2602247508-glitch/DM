"""Batch feature declarations compiled into typed runtime registries.

This module is the *batch assembly layer* for features that share one exact
runtime shape: a combat-turn self-buff that costs a long-rest resource,
activates a typed condition, and gates passive modifiers/defenses/movement on
that condition.  Every entry is data: the generator produces the same typed
blocks that a hand-written registry would, and the existing production
consumers (feature action, roll/save/attack modifier resolver, defense
resolver, movement-mode resolver, rest service) execute them without any
feature-name branch.

The declaration table deliberately contains only entries whose every effect is
consumed by a real, already-wired runtime path.  A feature that needs a new
engine mechanism is left out of this batch and stays partial.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BatchBuffFeature:
    """One self-buff feature with a typed condition-gated effect bundle."""

    key: str
    name: str
    class_name: str
    subclass_name: str
    level: int
    condition: str
    duration_value: int
    resource_key: str
    resource_label: str
    action_cost: str = "bonus_action"
    reset_options: dict[str, Any] | None = None
    modifiers: tuple[dict[str, Any], ...] = ()
    defenses: tuple[dict[str, Any], ...] = ()
    movement_modes: tuple[dict[str, Any], ...] = ()
    effect_kinds: tuple[str, ...] = ()
    triggers: tuple[dict[str, Any], ...] = ()


# The first production batch: features whose complete effect set is (1) a
# combat-turn activation, (2) one long-rest resource, (3) a duration
# condition, and (4) self-targeted typed passives already consumed by the
# modifier/defense/movement resolvers.
BATCH_BUFF_FEATURES: tuple[BatchBuffFeature, ...] = (
    BatchBuffFeature(
        key="divine_rage",
        name="神之狂暴",
        class_name="野蛮人",
        subclass_name="狂热者道途",
        level=14,
        condition="divine_rage",
        duration_value=1,
        resource_key="divine_rage",
        resource_label="神之狂暴",
        movement_modes=(
            {
                "id": "divine_rage:flight",
                "mode": "fly",
                "speed_source": "current_speed",
                "applies_when": "divine_rage",
            },
        ),
        defenses=(
            {
                "kind": "damage_resistance",
                "damage_types": ["necrotic", "psychic", "radiant"],
                "required_conditions": ["divine_rage"],
            },
        ),
        effect_kinds=("activate_duration_condition",),
    ),
    BatchBuffFeature(
        key="dance_virtuoso",
        name="炫目舞步",
        class_name="吟游诗人",
        subclass_name="舞蹈学院",
        level=3,
        condition="dance_virtuoso",
        duration_value=0,
        resource_key="",
        resource_label="",
        action_cost="none",
        modifiers=(
            {
                "stat": "armor_class",
                "operation": "set_base_formula",
                "formula": "10+dexterity_modifier+charisma_modifier",
                "scope": "self",
                "applies_when": "not_wearing_armor",
                "shield_allowed": False,
                "source": "炫目舞步",
            },
            {
                "stat": "ability_check",
                "operation": "advantage",
                "scope": "self",
                "applies_when": "every_charisma_ability_check",
                "source": "炫目舞步",
            },
        ),
        effect_kinds=(),
    ),
)


def _resource_entry(
    feature: BatchBuffFeature,
) -> tuple[str, dict[str, Any]]:
    return (
        feature.resource_key,
        {
            "label": feature.resource_label,
            "max": 1,
            "max_formula": "fixed_one",
            "resource_kind": "feature_uses",
            "recovery": "long_rest",
            "recovery_events": [{"rest": "long_rest", "operation": "set_to_max"}],
            "source": (
                f"{feature.class_name}·{feature.subclass_name}·"
                f"{feature.level}级{feature.name}"
            ),
            "requires_dm_adjudication": False,
            "automation_status": "full",
        },
    )


def _runtime_config(feature: BatchBuffFeature) -> dict[str, Any]:
    action_id = f"{feature.class_name}:{feature.subclass_name}:{feature.key}"
    actions: dict[str, Any] = {}
    if feature.resource_key:
        effects: list[dict[str, Any]] = [
            {
                "kind": "activate_duration_condition",
                "condition": feature.condition,
                "duration_unit": "minutes",
                "duration_value": feature.duration_value,
            }
        ]
        action: dict[str, Any] = {
            "id": action_id,
            "name": feature.name,
            "kind": "feature_action",
            "action_cost": feature.action_cost,
            "resource_key": "$feature_resource",
            "resource_cost": 1,
            "target": "self",
            "resolution_kind": "condition",
            "effects": effects,
            "resource_lifecycle": {
                "events": [{"trigger": "long_rest", "operation": "set_to_max"}]
            },
            "runtime_execution": {
                "status": "ready",
                "consumer": "combat_feature_action_and_player_roll_resolution",
                "effect_kinds": list(feature.effect_kinds),
            },
            "automation_status": "full",
            "requires_dm_adjudication": False,
        }
        if feature.reset_options is not None:
            action["reset_options"] = dict(feature.reset_options)
        actions[action_id] = action
    modifiers = []
    for item in feature.modifiers:
        entry = dict(item)
        entry.setdefault("automation_status", "full")
        entry.setdefault("requires_dm_adjudication", False)
        entry.setdefault(
            "runtime_execution",
            {"status": "ready", "consumer": "typed_modifier_resolvers"},
        )
        modifiers.append(entry)
    defenses = []
    for item in feature.defenses:
        entry = dict(item)
        entry.setdefault("automation_status", "full")
        entry.setdefault("requires_dm_adjudication", False)
        entry.setdefault(
            "runtime_execution",
            {"status": "ready", "consumer": "typed_defense_resolvers"},
        )
        defenses.append(entry)
    movement_modes = []
    for item in feature.movement_modes:
        entry = dict(item)
        entry.setdefault("automation_status", "full")
        entry.setdefault("requires_dm_adjudication", False)
        entry.setdefault(
            "runtime_execution",
            {"status": "ready", "consumer": "turn_budget_movement_mode_resolver"},
        )
        movement_modes.append(entry)
    return {
        "combat_start": {
            "modifiers": modifiers,
            "defenses": defenses,
            "movement_modes": movement_modes,
        },
        "resources": (
            {
                "$feature_resource": {
                    "key": "$feature_resource",
                    "label": feature.resource_label,
                    "max": 1,
                    "resource_kind": "feature_uses",
                    "recovery": "long_rest",
                    "recovery_events": [
                        {"rest": "long_rest", "operation": "set_to_max"}
                    ],
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                }
            }
            if feature.resource_key
            else {}
        ),
        "actions": actions,
        "triggers": [dict(item) for item in feature.triggers],
        "attack_riders": [],
        "automation_status": "full",
        "requires_dm_adjudication": False,
    }


def batch_runtime_configs() -> dict[str, dict[str, Any]]:
    """Return generated runtime registries keyed by the feature's Chinese name."""

    return {feature.name: _runtime_config(feature) for feature in BATCH_BUFF_FEATURES}


def batch_resource_updates() -> dict[str, tuple[str, dict[str, Any]]]:
    """Return the resource key/update for every batch feature by Chinese name."""

    return {feature.name: _resource_entry(feature) for feature in BATCH_BUFF_FEATURES}


def batch_keys() -> tuple[str, ...]:
    return tuple(feature.name for feature in BATCH_BUFF_FEATURES)
