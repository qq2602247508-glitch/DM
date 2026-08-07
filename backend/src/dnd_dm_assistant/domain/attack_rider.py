"""Configuration-driven effects that happen after an attack has hit.

``post_hit_rider`` is deliberately a domain executor, not a catalogue of
class features.  It only knows the structured facts supplied in its input:
the hit, combatant state, action tags, resources, submitted roll totals and
the target's save result.  A feature identifier is retained for audit and
idempotency keys, but is never used to select a rule branch.

The returned ``commit`` is a plan rather than a database write.  Persistence
adapters are responsible for atomically recording the returned idempotency
key, spending the listed resources and applying the emitted effect blocks.
This keeps a save prompt from consuming a resource twice when it is replayed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from typing import Any

POST_HIT_RIDER_KIND = "post_hit_rider"
POST_HIT_TRIGGER = "after_hit"

_DAMAGE_TERM = re.compile(
    r"(?P<sign>[+-]?)(?:(?P<count>\d*)d(?P<sides>\d+)|(?P<fixed>\d+)|@(?P<binding>[A-Za-z_][A-Za-z0-9_]*))",
    re.IGNORECASE,
)
_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_:-]*$")
_FREQUENCIES = {
    "each_eligible_hit",
    "once_per_attack",
    "once_per_turn",
    "once_per_target_per_turn",
}
_EFFECT_KINDS = {"condition", "move", "modifier"}
_MODIFIER_STATS = {
    "armor_class",
    "speed_ft",
    "attack_roll",
    "damage_roll",
    "saving_throw",
    "ability_check",
    "skill_check",
    "action",
    "bonus_action",
    "reaction",
}
_MODIFIER_OPERATIONS = {"add", "set", "advantage", "disadvantage", "grant"}
_MOVE_TYPES = {"walk", "fly", "swim", "burrow", "teleport", "forced"}
_MOVE_DIRECTIONS = {"chosen", "toward", "away", "push", "pull"}
_DURATION_UNITS = {
    "instant",
    "round",
    "minute",
    "hour",
    "day",
    "until_save",
    "until_removed",
    "permanent",
}


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _text(value: object) -> str:
    return str(value or "").strip()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_set(value: object) -> set[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return set()
    return {_text(item).casefold() for item in value if _text(item)}


def _required_string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be a list")
    result = [_text(item) for item in value]
    if not result or any(not item for item in result):
        raise ValueError(f"{label} must contain non-empty values")
    return result


def _identifier(value: object, label: str) -> str:
    result = _text(value)
    if not _IDENTIFIER.fullmatch(result):
        raise ValueError(f"{label} must be an identifier")
    return result


def _validate_duration(value: object, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = _mapping(value)
    if not raw:
        raise ValueError(f"{label} must be an object")
    unit = _text(raw.get("unit"))
    if unit not in _DURATION_UNITS:
        raise ValueError(f"{label} has an unsupported unit")
    raw_amount = raw.get("value")
    timed = unit in {"round", "minute", "hour", "day"}
    amount = _integer(raw_amount)
    if timed and (amount is None or amount < 1):
        raise ValueError(f"{label} timed units require a positive value")
    if not timed and raw_amount is not None:
        raise ValueError(f"{label} untimed units cannot have a value")
    return {"unit": unit, **({"value": amount} if timed else {})}


def _normalize_effects(
    raw_effects: object,
    *,
    rider_id: str,
    branch: str,
) -> list[dict[str, Any]]:
    if raw_effects is None:
        return []
    if not isinstance(raw_effects, list):
        raise ValueError(f"{branch} must be a list")

    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_effects, start=1):
        effect = _mapping(raw)
        if not effect:
            raise ValueError(f"{branch} contains an invalid effect")
        kind = _text(effect.get("kind"))
        if kind not in _EFFECT_KINDS:
            raise ValueError(f"{branch} has an unsupported effect kind")
        effect_id = _identifier(effect.get("id") or f"{rider_id}:{branch}:{index}", "effect id")
        if effect_id in seen_ids:
            raise ValueError(f"{branch} effect ids must be unique")
        seen_ids.add(effect_id)
        normalized: dict[str, Any] = {"id": effect_id, "kind": kind}

        if kind == "condition":
            operation = _text(effect.get("operation") or "apply")
            condition = _text(effect.get("condition"))
            if operation not in {"apply", "remove"} or not condition:
                raise ValueError(f"{branch} condition effect is invalid")
            normalized.update({"operation": operation, "condition": condition})
            duration = _validate_duration(effect.get("duration"), f"{branch} condition duration")
            if duration is not None:
                normalized["duration"] = duration
            save_ends = effect.get("save_ends", False)
            if not isinstance(save_ends, bool):
                raise ValueError(f"{branch} condition save_ends must be a boolean")
            if save_ends:
                normalized["save_ends"] = True
        elif kind == "move":
            distance = _integer(effect.get("distance_ft"))
            movement_type = _text(effect.get("movement_type") or "forced")
            direction = _text(effect.get("direction") or "chosen")
            if distance is None or not 0 <= distance <= 10_000:
                raise ValueError(f"{branch} move distance_ft is invalid")
            if movement_type not in _MOVE_TYPES or direction not in _MOVE_DIRECTIONS:
                raise ValueError(f"{branch} move effect is invalid")
            normalized.update(
                {
                    "distance_ft": distance,
                    "movement_type": movement_type,
                    "direction": direction,
                }
            )
        else:
            stat = _text(effect.get("stat"))
            operation = _text(effect.get("operation"))
            value = _integer(effect.get("value"))
            if stat not in _MODIFIER_STATS or operation not in _MODIFIER_OPERATIONS:
                raise ValueError(f"{branch} modifier effect is invalid")
            needs_value = operation in {"add", "set"}
            if needs_value != (value is not None):
                raise ValueError(f"{branch} modifier value does not match its operation")
            normalized.update({"stat": stat, "operation": operation})
            if value is not None:
                normalized["value"] = value
            duration = _validate_duration(effect.get("duration"), f"{branch} modifier duration")
            if duration is not None:
                normalized["duration"] = duration

        source = _text(effect.get("source"))
        if source:
            normalized["source"] = source
        result.append(normalized)
    return result


def _damage_bounds(
    expression: object,
    *,
    bindings: Mapping[str, int],
    critical_hit: bool,
    critical_doubles_dice: bool,
    allow_missing_bindings: bool = False,
) -> tuple[int, int]:
    """Return deterministic min/max bounds for a reported damage total."""

    normalized = _text(expression).replace(" ", "")
    if not normalized:
        raise ValueError("post-hit rider damage expression is required")
    cursor = 0
    minimum = 0
    maximum = 0
    for match in _DAMAGE_TERM.finditer(normalized):
        if match.start() != cursor:
            raise ValueError("post-hit rider damage expression is unsupported")
        cursor = match.end()
        sign = -1 if match.group("sign") == "-" else 1
        if match.group("count") is not None:
            count = int(match.group("count") or "1")
            sides = int(match.group("sides"))
            if count < 1 or sides < 1:
                raise ValueError("post-hit rider damage dice are invalid")
            if critical_hit and critical_doubles_dice:
                count *= 2
            low, high = count, count * sides
        elif match.group("fixed") is not None:
            low = high = int(match.group("fixed"))
        else:
            binding = str(match.group("binding"))
            value = bindings.get(binding)
            if not isinstance(value, int):
                if not allow_missing_bindings:
                    raise ValueError(f"post-hit rider damage binding is missing: {binding}")
                value = 0
            low = high = value
        if sign > 0:
            minimum += low
            maximum += high
        else:
            minimum -= high
            maximum -= low
    if cursor != len(normalized) or minimum < 0 or maximum < minimum:
        raise ValueError("post-hit rider damage expression is unsupported")
    return minimum, maximum


def _normalize_damage_components(
    spec: Mapping[str, Any],
    *,
    bindings: Mapping[str, int],
    critical_hit: bool,
    require_totals: bool,
    inputs: Mapping[str, object],
    allow_missing_bindings: bool = False,
) -> list[dict[str, Any]]:
    raw_damage = spec.get("damage")
    if raw_damage is None:
        return []
    raw_components = raw_damage if isinstance(raw_damage, list) else [raw_damage]
    if not raw_components:
        raise ValueError("post-hit rider damage cannot be empty")

    rider_id = _identifier(spec.get("id"), "post-hit rider id")
    result: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_component in enumerate(raw_components, start=1):
        component = _mapping(raw_component)
        if not component:
            raise ValueError("post-hit rider damage component must be an object")
        component_id = _identifier(component.get("id") or f"damage-{index}", "damage component id")
        if component_id in seen_ids:
            raise ValueError("post-hit rider damage component ids must be unique")
        seen_ids.add(component_id)
        expression = _text(component.get("expression"))
        damage_type = _text(component.get("damage_type"))
        input_key = _identifier(
            component.get("input_key") or f"{rider_id}:{component_id}:total",
            "damage input key",
        )
        doubles = component.get("critical_doubles_dice", True)
        if not isinstance(doubles, bool):
            raise ValueError("critical_doubles_dice must be a boolean")
        minimum, maximum = _damage_bounds(
            expression,
            bindings=bindings,
            critical_hit=critical_hit,
            critical_doubles_dice=doubles,
            allow_missing_bindings=allow_missing_bindings,
        )
        if not damage_type:
            raise ValueError("post-hit rider damage_type is required")
        entry: dict[str, Any] = {
            "id": component_id,
            "expression": expression,
            "damage_type": damage_type,
            "input_key": input_key,
            "minimum": minimum,
            "maximum": maximum,
            "critical_doubles_dice": doubles,
        }
        if require_totals:
            reported = _integer(inputs.get(input_key))
            if reported is None:
                raise ValueError(f"post-hit rider damage total is required: {input_key}")
            if not minimum <= reported <= maximum:
                raise ValueError(
                    "post-hit rider damage total must be between "
                    f"{minimum} and {maximum}: {input_key}"
                )
            entry["reported_total"] = reported
        result.append(entry)
    return result


def _normalize_save(
    raw_save: object,
    *,
    bindings: Mapping[str, int],
    inputs: Mapping[str, object],
    allow_missing_dc_source: bool = False,
) -> tuple[dict[str, Any] | None, bool | None]:
    if raw_save is None:
        return None, None
    save = _mapping(raw_save)
    if not save:
        raise ValueError("post-hit rider saving_throw must be an object")
    ability = _text(save.get("ability"))
    input_key = _identifier(save.get("input_key") or "save_total", "saving throw input key")
    raw_dc = _integer(save.get("dc"))
    dc_source = _text(save.get("dc_source"))
    if (raw_dc is None) == (not dc_source):
        raise ValueError("post-hit rider saving_throw needs exactly one of dc or dc_source")
    if dc_source:
        _identifier(dc_source, "saving throw dc_source")
    dc = raw_dc if raw_dc is not None else bindings.get(dc_source)
    if dc is None and allow_missing_dc_source and dc_source:
        dc = 1
    if not ability or not isinstance(dc, int) or not 1 <= dc <= 100:
        raise ValueError("post-hit rider saving_throw is invalid")
    result: dict[str, Any] = {"ability": ability, "dc": dc, "input_key": input_key}
    if input_key not in inputs or inputs.get(input_key) is None:
        return result, None
    total = _integer(inputs.get(input_key))
    if total is None:
        raise ValueError(f"post-hit rider saving throw total is invalid: {input_key}")
    result["reported_total"] = total
    result["success"] = total >= dc
    return result, bool(result["success"])


def _normalize_choice(
    raw_choice: object,
    *,
    rider_id: str,
    inputs: Mapping[str, object],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], bool]:
    if raw_choice is None:
        return None, [], False
    choice = _mapping(raw_choice)
    if not choice:
        raise ValueError("post-hit rider choice must be an object")
    input_key = _identifier(choice.get("input_key"), "choice input key")
    raw_options = choice.get("options")
    if not isinstance(raw_options, list) or len(raw_options) < 2:
        raise ValueError("post-hit rider choice requires at least two options")
    options: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for raw_option in raw_options:
        option = _mapping(raw_option)
        key = _identifier(option.get("key"), "choice option key")
        if key in seen_keys:
            raise ValueError("post-hit rider choice option keys must be unique")
        seen_keys.add(key)
        label = _text(option.get("label") or key)
        effects = _normalize_effects(
            option.get("effects"),
            rider_id=rider_id,
            branch=f"choice-{key}",
        )
        options.append({"key": key, "label": label, "effects": effects})
    result = {"input_key": input_key, "options": options}
    selected = inputs.get(input_key)
    if selected is None:
        return result, [], True
    selected_key = _text(selected)
    selected_option: dict[str, Any] | None = None
    for candidate in options:
        if candidate["key"] == selected_key:
            selected_option = candidate
            break
    if selected_option is None:
        raise ValueError(f"post-hit rider choice is invalid: {input_key}")
    return {**result, "selected": selected_key}, deepcopy(selected_option["effects"]), False


def _validate_eligibility(raw_eligibility: object) -> dict[str, Any]:
    if raw_eligibility is None:
        return {}
    eligibility = _mapping(raw_eligibility)
    if not eligibility:
        raise ValueError("post-hit rider eligibility must be an object")
    allowed = {
        "actor_entity_types",
        "target_entity_types",
        "actor_factions",
        "target_factions",
        "actor_conditions_all",
        "actor_conditions_none",
        "target_conditions_all",
        "target_conditions_none",
        "action_tags_all",
        "action_tags_any",
        "action_tags_none",
        "attack_abilities",
        "target_relations",
        "actor_level",
    }
    unknown = sorted(set(eligibility) - allowed)
    if unknown:
        raise ValueError("unsupported post-hit rider eligibility: " + ", ".join(unknown))
    for key in allowed - {"actor_level"}:
        if key in eligibility:
            _required_string_list(eligibility[key], f"post-hit rider eligibility.{key}")
    if "actor_level" in eligibility:
        level = _mapping(eligibility["actor_level"])
        names = _required_string_list(level.get("class_names"), "actor_level.class_names")
        minimum = _integer(level.get("minimum"))
        if not names or minimum is None or minimum < 1:
            raise ValueError("post-hit rider actor_level is invalid")
    return eligibility


def _eligible(
    eligibility: Mapping[str, Any],
    *,
    actor: Mapping[str, object],
    target: Mapping[str, object],
    action: Mapping[str, object],
) -> bool:
    actor_conditions = _string_set(actor.get("conditions"))
    target_conditions = _string_set(target.get("conditions"))
    action_tags = _string_set(action.get("tags"))

    def exact_list(key: str, value: object) -> bool:
        allowed = _string_set(eligibility.get(key))
        return not allowed or _text(value).casefold() in allowed

    if not exact_list("actor_entity_types", actor.get("entity_type")):
        return False
    if not exact_list("target_entity_types", target.get("entity_type")):
        return False
    if not exact_list("actor_factions", actor.get("faction")):
        return False
    if not exact_list("target_factions", target.get("faction")):
        return False
    if not exact_list("target_relations", target.get("relation")):
        return False
    if not exact_list("attack_abilities", action.get("attack_ability") or action.get("ability")):
        return False
    if not _string_set(eligibility.get("actor_conditions_all")).issubset(actor_conditions):
        return False
    if _string_set(eligibility.get("actor_conditions_none")) & actor_conditions:
        return False
    if not _string_set(eligibility.get("target_conditions_all")).issubset(target_conditions):
        return False
    if _string_set(eligibility.get("target_conditions_none")) & target_conditions:
        return False
    tags_all = _string_set(eligibility.get("action_tags_all"))
    tags_any = _string_set(eligibility.get("action_tags_any"))
    tags_none = _string_set(eligibility.get("action_tags_none"))
    if not tags_all.issubset(action_tags) or (tags_any and not tags_any & action_tags):
        return False
    if tags_none & action_tags:
        return False

    raw_level = eligibility.get("actor_level")
    if raw_level is not None:
        level = _mapping(raw_level)
        class_names = _string_set(level.get("class_names"))
        minimum = _integer(level.get("minimum"))
        levels = _mapping(actor.get("class_levels"))
        matching_level = max(
            (
                value
                for name, raw_value in levels.items()
                if _text(name).casefold() in class_names
                if (value := _integer(raw_value)) is not None
            ),
            default=0,
        )
        if minimum is None or matching_level < minimum:
            return False
    return True


def _resource_spends(
    raw_resource: object,
    resources: Mapping[str, object],
) -> list[dict[str, Any]]:
    if raw_resource is None:
        return []
    resource = _mapping(raw_resource)
    key = _identifier(resource.get("key"), "resource key")
    amount = _integer(resource.get("amount"))
    if amount is None or amount < 1:
        raise ValueError("post-hit rider resource amount must be positive")
    raw_pool = resources.get(key)
    pool = _mapping(raw_pool)
    current = _integer(pool.get("current")) if pool else _integer(raw_pool)
    if current is None or current < amount:
        raise ValueError(f"post-hit rider resource is insufficient: {key}")
    return [{"key": key, "amount": amount}]


def _usage_token(
    *,
    rider_id: str,
    frequency: str,
    event_id: str,
    turn_id: str | None,
    target_id: str,
) -> str | None:
    if frequency == "each_eligible_hit":
        return None
    if frequency == "once_per_attack":
        return f"post-hit:{rider_id}:attack:{event_id}"
    if not turn_id:
        raise ValueError("post-hit rider frequency requires a turn_id")
    if frequency == "once_per_turn":
        return f"post-hit:{rider_id}:turn:{turn_id}"
    if frequency == "once_per_target_per_turn":
        if not target_id:
            raise ValueError("post-hit rider target frequency requires a target id")
        return f"post-hit:{rider_id}:turn:{turn_id}:target:{target_id}"
    raise ValueError("post-hit rider frequency is invalid")


def validate_post_hit_rider(spec: Mapping[str, object]) -> dict[str, Any]:
    """Validate a reusable post-hit rider contract without feature-name logic."""

    config = deepcopy(dict(spec))
    rider_id = _identifier(config.get("id"), "post-hit rider id")
    if config.get("kind") != POST_HIT_RIDER_KIND:
        raise ValueError("not a post-hit rider configuration")
    if config.get("trigger") != POST_HIT_TRIGGER:
        raise ValueError("post-hit rider trigger must be after_hit")
    frequency = _text(config.get("frequency") or "each_eligible_hit")
    if frequency not in _FREQUENCIES:
        raise ValueError("post-hit rider frequency is invalid")
    _validate_eligibility(config.get("eligibility"))
    # Resource availability is input-dependent, but its shape can still be
    # checked here without a combatant sheet.
    if config.get("resource") is not None:
        resource = _mapping(config.get("resource"))
        _identifier(resource.get("key"), "resource key")
        amount = _integer(resource.get("amount"))
        if amount is None or amount < 1:
            raise ValueError("post-hit rider resource amount must be positive")
    _normalize_damage_components(
        config,
        bindings={},
        critical_hit=False,
        require_totals=False,
        inputs={},
        allow_missing_bindings=True,
    )
    _normalize_save(
        config.get("saving_throw"),
        bindings={},
        inputs={},
        allow_missing_dc_source=True,
    )
    _normalize_effects(config.get("on_hit"), rider_id=rider_id, branch="on-hit")
    _normalize_effects(
        config.get("on_save_success"), rider_id=rider_id, branch="on-save-success"
    )
    _normalize_effects(
        config.get("on_save_failure"), rider_id=rider_id, branch="on-save-failure"
    )
    _normalize_choice(config.get("choice"), rider_id=rider_id, inputs={})
    return config


def post_hit_rider_input_requirements(
    spec: Mapping[str, object],
    *,
    bindings: Mapping[str, object] | None = None,
    critical_hit: bool = False,
) -> list[dict[str, Any]]:
    """Return player/DM inputs from a config and any authoritative bindings.

    Configurations using ``@binding`` damage terms or ``dc_source`` must pass
    those current values here.  The helper does not guess a class level, save
    DC, or modifier merely to make a prompt look complete.
    """

    config = validate_post_hit_rider(spec)
    numeric_bindings = {
        _text(key): value
        for key, raw_value in (bindings or {}).items()
        if _text(key) and (value := _integer(raw_value)) is not None
    }
    requirements: list[dict[str, Any]] = []
    choice, _, _ = _normalize_choice(config.get("choice"), rider_id=config["id"], inputs={})
    if choice is not None:
        requirements.append(
            {
                "key": choice["input_key"],
                "kind": "choice",
                "options": [
                    {"key": option["key"], "label": option["label"]}
                    for option in choice["options"]
                ],
            }
        )
    for component in _normalize_damage_components(
        config,
        bindings=numeric_bindings,
        critical_hit=critical_hit,
        require_totals=False,
        inputs={},
    ):
        if component["minimum"] != component["maximum"]:
            requirements.append(
                {
                    "key": component["input_key"],
                    "kind": "damage_total",
                    "expression": component["expression"],
                    "minimum": component["minimum"],
                    "maximum": component["maximum"],
                }
            )
    save, _ = _normalize_save(
        config.get("saving_throw"), bindings=numeric_bindings, inputs={}
    )
    if save is not None:
        requirements.append(
            {
                "key": save["input_key"],
                "kind": "saving_throw_total",
                "ability": save["ability"],
                "dc": save["dc"],
            }
        )
    return requirements


def resolve_post_hit_rider(
    spec: Mapping[str, object],
    *,
    hit: bool,
    actor: Mapping[str, object],
    target: Mapping[str, object],
    action: Mapping[str, object],
    resources: Mapping[str, object],
    event_id: str,
    turn_id: str | None = None,
    inputs: Mapping[str, object] | None = None,
    bindings: Mapping[str, object] | None = None,
    used_tokens: Iterable[object] = (),
    critical_hit: bool = False,
) -> dict[str, Any] | None:
    """Prepare or resolve one configured rider after a confirmed hit.

    The resolver makes no database changes.  ``pending_choice`` and
    ``pending_save`` intentionally carry no commit plan, so an adapter cannot
    spend a resource merely by opening a player/DM input window.
    """

    if not hit:
        return None
    config = validate_post_hit_rider(spec)
    rider_id = _identifier(config.get("id"), "post-hit rider id")
    if not _eligible(
        _validate_eligibility(config.get("eligibility")), actor=actor, target=target, action=action
    ):
        return None
    normalized_event = _text(event_id)
    if not normalized_event:
        raise ValueError("post-hit rider event_id is required")
    frequency = _text(config.get("frequency") or "each_eligible_hit")
    target_id = _text(target.get("id"))
    usage_token = _usage_token(
        rider_id=rider_id,
        frequency=frequency,
        event_id=normalized_event,
        turn_id=_text(turn_id) or None,
        target_id=target_id,
    )
    resolution_key = f"post-hit:{normalized_event}:{rider_id}"
    if usage_token is not None and usage_token in {_text(value) for value in used_tokens}:
        return {
            "status": "already_used",
            "rider_id": rider_id,
            "resolution_key": resolution_key,
            "usage_token": usage_token,
        }

    supplied_inputs = dict(inputs or {})
    numeric_bindings = {
        _text(key): value
        for key, raw_value in (bindings or {}).items()
        if _text(key) and (value := _integer(raw_value)) is not None
    }
    choice, choice_effects, choice_pending = _normalize_choice(
        config.get("choice"), rider_id=rider_id, inputs=supplied_inputs
    )
    if choice_pending:
        assert choice is not None
        return {
            "status": "pending_choice",
            "rider_id": rider_id,
            "resolution_key": resolution_key,
            "usage_token": usage_token,
            "choice": {
                "input_key": choice["input_key"],
                "options": [
                    {"key": option["key"], "label": option["label"]}
                    for option in choice["options"]
                ],
            },
            "commit": None,
        }

    save, save_success = _normalize_save(
        config.get("saving_throw"), bindings=numeric_bindings, inputs=supplied_inputs
    )
    if save is not None and save_success is None:
        return {
            "status": "pending_save",
            "rider_id": rider_id,
            "resolution_key": resolution_key,
            "usage_token": usage_token,
            "selected_choice": choice.get("selected") if choice is not None else None,
            "saving_throw": save,
            "damage_requirements": _normalize_damage_components(
                config,
                bindings=numeric_bindings,
                critical_hit=critical_hit,
                require_totals=False,
                inputs=supplied_inputs,
            ),
            "commit": None,
        }

    damage = _normalize_damage_components(
        config,
        bindings=numeric_bindings,
        critical_hit=critical_hit,
        require_totals=True,
        inputs=supplied_inputs,
    )
    effects = _normalize_effects(config.get("on_hit"), rider_id=rider_id, branch="on-hit")
    effects.extend(choice_effects)
    if save_success is True:
        effects.extend(
            _normalize_effects(
                config.get("on_save_success"), rider_id=rider_id, branch="on-save-success"
            )
        )
    elif save_success is False:
        effects.extend(
            _normalize_effects(
                config.get("on_save_failure"), rider_id=rider_id, branch="on-save-failure"
            )
        )
    spends = _resource_spends(config.get("resource"), resources)
    return {
        "status": "resolved",
        "rider_id": rider_id,
        "resolution_key": resolution_key,
        "usage_token": usage_token,
        "selected_choice": choice.get("selected") if choice is not None else None,
        "damage": damage,
        "saving_throw": save,
        "effects": effects,
        "commit": {
            "idempotency_key": resolution_key,
            "usage_token": usage_token,
            "resource_spends": spends,
        },
    }


def post_hit_effects_as_rule_blocks(
    effects: Iterable[Mapping[str, object]],
) -> list[dict[str, Any]]:
    """Adapt resolved effects to existing combat rule-block dictionaries.

    This is only a compatibility adapter for the older combat effect consumer.
    It does not decide eligibility, roll totals, save results, frequency or
    resources; those all belong to :func:`resolve_post_hit_rider`.
    """

    blocks: list[dict[str, Any]] = []
    for raw_effect in effects:
        effect = deepcopy(dict(raw_effect))
        duration = effect.pop("duration", None)
        if duration is not None:
            duration_spec = _validate_duration(duration, "post-hit effect duration")
            assert duration_spec is not None
            effect_id = _identifier(effect.get("id"), "effect id")
            duration_id = f"{effect_id}:duration"
            blocks.append({"id": duration_id, "kind": "duration", **duration_spec})
            effect["duration_block_id"] = duration_id
        blocks.append(effect)
    return blocks
