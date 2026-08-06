from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

ZERO_HP_INTERVENTION_KIND = "zero_hp_intervention"
ZERO_HP_TRIGGER = "would_drop_to_zero_hit_points"


def _integer(value: object, default: int = 0) -> int:
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


def _string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalized_set(values: Iterable[object]) -> set[str]:
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def _evaluate_amount(expression: object, bindings: Mapping[str, int]) -> int | None:
    """Evaluate the deliberately small HP-expression language.

    Zero-HP interventions only need a non-negative integer, a bound value, or
    one multiplication between those atoms.  Keeping the grammar this small
    avoids evaluating arbitrary rule text while still covering level-scaled
    recovery such as ``2*barbarian_level``.
    """

    normalized = str(expression or "").strip().replace(" ", "")
    match = re.fullmatch(
        r"([A-Za-z_][A-Za-z0-9_]*|\d+)(?:\*([A-Za-z_][A-Za-z0-9_]*|\d+))?", normalized
    )
    if match is None:
        return None

    def atom(raw: str) -> int | None:
        if raw.isdigit():
            return int(raw)
        value = bindings.get(raw)
        return value if isinstance(value, int) and value >= 0 else None

    left = atom(match.group(1))
    right_raw = match.group(2)
    right = atom(right_raw) if right_raw is not None else 1
    if left is None or right is None:
        return None
    return left * right


def adapt_legacy_zero_hp_intervention(
    raw_defense: Mapping[str, object],
) -> dict[str, object]:
    """Translate the pre-contract Relentless Rage snapshot shape.

    This adapter is intentionally separate from the shared resolver.  It
    preserves already-running combat snapshots, while new feature definitions
    must publish the generic contract directly.
    """

    defense = dict(raw_defense)
    if not (
        defense.get("kind") == "zero_hit_points_save"
        and defense.get("trigger") == "self_would_drop_to_zero_hit_points_while_raging"
    ):
        return defense
    raw_save = defense.get("saving_throw")
    saving_throw = dict(raw_save) if isinstance(raw_save, dict) else {}
    return {
        **defense,
        "kind": ZERO_HP_INTERVENTION_KIND,
        "trigger": ZERO_HP_TRIGGER,
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
            "ability": saving_throw.get("ability", "constitution"),
            "initial_dc": saving_throw.get("initial_dc", 10),
            "increase_after_success": saving_throw.get("increase_after_each_success", 5),
        },
        "success": {
            "kind": "restore_hit_points",
            "amount": defense.get("hit_points_on_success", "2*barbarian_level"),
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
            "description": "降至 0 HP 且处于狂暴；请进行体质豁免以维持生命。",
            "result_key": "relentless_rage",
            "prompt_idempotency_prefix": "relentless-rage-save",
            "prompt_result_id_key": "relentless_rage_save_prompt_id",
        },
    }


def resolve_zero_hp_intervention(
    defenses: Iterable[Mapping[str, object]],
    *,
    resulting_hp: int,
    unapplied_damage: int,
    max_hp: int,
    entity_type: str,
    faction: str | None,
    conditions: Iterable[object],
    class_levels: Mapping[str, object],
    resources: Mapping[str, object],
    snapshot: Mapping[str, object],
) -> dict[str, object] | None:
    """Return the first fully structured, eligible zero-HP intervention.

    The resolver is feature-ID agnostic.  A feature participates only by
    supplying the shared contract fields; malformed or incomplete contracts
    fail closed.
    """

    if resulting_hp != 0:
        return None
    normalized_conditions = _normalized_set(conditions)
    normalized_faction = str(faction or "").strip().casefold()
    normalized_entity_type = entity_type.strip().casefold()

    for raw_defense in defenses:
        defense = dict(raw_defense)
        if (
            defense.get("kind") != ZERO_HP_INTERVENTION_KIND
            or defense.get("trigger") != ZERO_HP_TRIGGER
        ):
            continue
        exceptions = _normalized_set(_string_list(defense.get("exceptions")))
        if "outright_death" not in exceptions:
            continue
        if unapplied_damage >= max_hp:
            continue

        raw_eligibility = defense.get("eligibility")
        eligibility = dict(raw_eligibility) if isinstance(raw_eligibility, dict) else {}
        entity_types = _normalized_set(_string_list(eligibility.get("entity_types")))
        if entity_types and normalized_entity_type not in entity_types:
            continue
        factions = _normalized_set(_string_list(eligibility.get("factions")))
        if factions and normalized_faction not in factions:
            continue
        required_conditions = _normalized_set(_string_list(eligibility.get("required_conditions")))
        forbidden_conditions = _normalized_set(
            _string_list(eligibility.get("forbidden_conditions"))
        )
        if not required_conditions.issubset(normalized_conditions):
            continue
        if forbidden_conditions & normalized_conditions:
            continue

        bindings: dict[str, int] = {}
        raw_level = eligibility.get("level")
        if isinstance(raw_level, dict):
            level_spec = dict(raw_level)
            class_names = _normalized_set(_string_list(level_spec.get("class_names")))
            class_level = max(
                (
                    _integer(value)
                    for name, value in class_levels.items()
                    if str(name).strip().casefold() in class_names
                ),
                default=0,
            )
            minimum_level = _integer(level_spec.get("minimum"), 1)
            binding_name = str(level_spec.get("bind_as") or "class_level").strip()
            if not class_names or not binding_name or class_level < max(1, minimum_level):
                continue
            bindings[binding_name] = class_level

        raw_resource = eligibility.get("resource")
        if isinstance(raw_resource, dict):
            resource_spec = dict(raw_resource)
            resource_key = str(resource_spec.get("key") or "").strip()
            raw_pool = resources.get(resource_key)
            pool = dict(raw_pool) if isinstance(raw_pool, dict) else {}
            resource_current = _integer(pool.get("current"))
            resource_minimum = _integer(resource_spec.get("minimum"), 1)
            if not resource_key or resource_current < max(0, resource_minimum):
                continue
            binding_name = str(resource_spec.get("bind_as") or "").strip()
            if binding_name:
                bindings[binding_name] = resource_current

        raw_save = defense.get("saving_throw")
        saving_throw = dict(raw_save) if isinstance(raw_save, dict) else {}
        ability = str(saving_throw.get("ability") or "").strip()
        initial_dc = _integer(saving_throw.get("initial_dc"))
        dc_increase = _integer(saving_throw.get("increase_after_success"))
        if not ability or initial_dc < 1 or dc_increase < 0:
            continue

        raw_success = defense.get("success")
        success = dict(raw_success) if isinstance(raw_success, dict) else {}
        raw_failure = defense.get("failure")
        failure = dict(raw_failure) if isinstance(raw_failure, dict) else {}
        if success.get("kind") != "restore_hit_points":
            continue
        if failure.get("kind") != "continue_zero_hp_lifecycle":
            continue
        restore_hit_points = _evaluate_amount(success.get("amount"), bindings)
        if restore_hit_points is None or restore_hit_points < 1:
            continue

        raw_state = defense.get("state")
        state_spec = dict(raw_state) if isinstance(raw_state, dict) else {}
        state_key = str(state_spec.get("key") or "").strip()
        current_dc_field = str(state_spec.get("current_dc_field") or "current_dc").strip()
        if not state_key or not current_dc_field:
            continue
        raw_current_state = snapshot.get(state_key)
        current_state = dict(raw_current_state) if isinstance(raw_current_state, dict) else {}
        current_dc = max(initial_dc, _integer(current_state.get(current_dc_field), initial_dc))

        raw_presentation = defense.get("presentation")
        presentation = dict(raw_presentation) if isinstance(raw_presentation, dict) else {}
        feature_id = str(defense.get("id") or "").strip()
        if not feature_id:
            continue
        return {
            "feature_id": feature_id,
            "ability": ability,
            "dc": current_dc,
            "initial_dc": initial_dc,
            "increase_after_success": dc_increase,
            "restore_hit_points": restore_hit_points,
            "bindings": bindings,
            "state": state_spec,
            "resets": _string_list(defense.get("resets")),
            "presentation": presentation,
            "massive_damage": False,
        }
    return None


def reset_zero_hp_intervention_states(
    snapshot: Mapping[str, Any],
    defenses: Iterable[Mapping[str, object]],
    *,
    rest_event: str,
) -> tuple[dict[str, Any], list[str]]:
    """Reset every configured intervention state that names this rest event."""

    updated = deepcopy(dict(snapshot))
    reset_state_keys: list[str] = []
    for raw_defense in defenses:
        defense = dict(raw_defense)
        if (
            defense.get("kind") != ZERO_HP_INTERVENTION_KIND
            or defense.get("trigger") != ZERO_HP_TRIGGER
            or rest_event not in _string_list(defense.get("resets"))
        ):
            continue
        raw_save = defense.get("saving_throw")
        saving_throw = dict(raw_save) if isinstance(raw_save, dict) else {}
        initial_dc = _integer(saving_throw.get("initial_dc"))
        raw_state = defense.get("state")
        state_spec = dict(raw_state) if isinstance(raw_state, dict) else {}
        state_key = str(state_spec.get("key") or "").strip()
        current_dc_field = str(state_spec.get("current_dc_field") or "current_dc").strip()
        current_state = updated.get(state_key)
        if (
            initial_dc < 1
            or not state_key
            or not current_dc_field
            or not isinstance(current_state, dict)
        ):
            continue
        state = dict(current_state)
        state[current_dc_field] = initial_dc
        state["reset_reason"] = str(state_spec.get("reset_reason") or rest_event)
        updated[state_key] = state
        reset_state_keys.append(state_key)
    return updated, reset_state_keys
