"""Configuration-driven interventions for an already-reported d20 result.

The combat and player-room services own prompts, resources, and persistence.
This module deliberately owns only the reusable rule portion: deciding whether
one configuration is eligible, validating declared player/DM roll input, and
calculating the resulting total.  It never recognises a feature ID, rolls a
die, or mutates a resource.  That boundary lets different class features use
the same executor without making a named-feature branch look generic.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy

ROLL_INTERVENTION_KIND = "roll_intervention"
ROLL_INTERVENTION_OPERATIONS = frozenset(
    {
        "reroll",
        "reroll_with_add",
        "add",
        "add_die",
        "advantage",
        "disadvantage",
        "set_minimum",
        "set_minimum_d20",
        "replace_d20",
        "failure_recovery",
    }
)

# A roll intervention is often a short-lived window rather than a passive
# modifier.  Keep the lifecycle vocabulary in the domain module so every
# consumer (combat, player-room replay, and future non-combat rolls) validates
# the same persisted shape.  ``window`` is deliberately clock-oriented: the
# caller supplies the authoritative event clock and remains responsible for
# writing the returned state in its transaction.
ROLL_INTERVENTION_WINDOW_PHASES = frozenset(
    {"before_d20_test", "after_d20_test", "after_failed_d20_test"}
)
ROLL_INTERVENTION_WINDOW_EXPIRIES = frozenset(
    {"operation", "turn_end", "next_turn_start", "round_end", "duration_end", "rest"}
)

_INTEGER_EXPRESSION = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*|\d+|[+\-*]",
)
_INTEGER_ATOM = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")
_MAX_TOTAL = 100_000


def _integer(value: object, default: int | None = None) -> int | None:
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
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalized_set(values: Iterable[object]) -> set[str]:
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def validate_roll_intervention_window(spec: Mapping[str, object]) -> dict[str, object]:
    """Validate and normalize the optional persisted roll window contract.

    A malformed window is rejected instead of silently becoming an always-on
    feature.  ``phase`` defaults to the historical trigger so old snapshots
    continue to replay exactly as before.  ``max_uses`` and ``uses`` are kept
    as non-negative integers; consumers decrement ``uses`` only after their
    idempotent confirmation transaction succeeds.
    """

    raw = spec.get("window")
    if raw is None:
        return {
            "phase": str(spec.get("trigger") or "after_failed_d20_test").strip().casefold(),
            "expires": "operation",
        }
    window = _mapping(raw)
    phase = str(window.get("phase") or spec.get("trigger") or "").strip().casefold()
    if phase not in ROLL_INTERVENTION_WINDOW_PHASES:
        raise ValueError("掷骰干预窗口 phase 无效")
    expires = str(window.get("expires") or "operation").strip().casefold()
    if expires not in ROLL_INTERVENTION_WINDOW_EXPIRIES:
        raise ValueError("掷骰干预窗口 expires 无效")
    normalized: dict[str, object] = {"phase": phase, "expires": expires}
    for key in ("state_key", "source_event_id", "target_combatant_id"):
        value = window.get(key)
        if value is not None:
            value = str(value).strip()
            if not value:
                raise ValueError(f"掷骰干预窗口 {key} 无效")
            normalized[key] = value
    for key in ("max_uses", "uses", "created_round", "created_turn_index", "expires_round"):
        value = _integer(window.get(key))
        if value is None or value < 0:
            if window.get(key) is not None:
                raise ValueError(f"掷骰干预窗口 {key} 无效")
            continue
        normalized[key] = value
    max_uses = normalized.get("max_uses")
    uses = normalized.get("uses")
    if isinstance(max_uses, int) and isinstance(uses, int) and uses > max_uses:
        raise ValueError("掷骰干预窗口 uses 不能超过 max_uses")
    return normalized


def roll_intervention_window_state(
    spec: Mapping[str, object],
    *,
    event_phase: str,
    state: Mapping[str, object] | None = None,
    round_number: int | None = None,
    turn_index: int | None = None,
) -> dict[str, object] | None:
    """Return a durable, eligible window state for one roll event.

    This is pure and idempotent.  It never mutates ``state`` and therefore can
    be called for preview and confirmation.  The caller persists the returned
    ``uses``/``consumed_for_operation_id`` fields after applying the result.
    """

    window = validate_roll_intervention_window(spec)
    phase = str(event_phase).strip().casefold()
    if window["phase"] != phase:
        return None
    current = dict(state or {})
    if current.get("consumed") is True:
        return None
    if isinstance(current.get("uses"), int) and current["uses"] <= 0:
        return None
    expires = str(window.get("expires") or "operation")
    if expires == "round_end" and isinstance(current.get("expires_round"), int):
        if round_number is not None and round_number > current["expires_round"]:
            return None
    if expires == "next_turn_start":
        if (
            isinstance(current.get("expires_round"), int)
            and isinstance(current.get("expires_turn_index"), int)
            and round_number is not None
            and turn_index is not None
            and (round_number, turn_index)
            >= (current["expires_round"], current["expires_turn_index"])
        ):
            return None
    result = {**window, **current, "phase": phase}
    if "uses" not in result and isinstance(result.get("max_uses"), int):
        result["uses"] = result["max_uses"]
    return result


def consume_roll_intervention_window(
    state: Mapping[str, object],
    *,
    operation_id: str,
    consume: bool = True,
) -> dict[str, object]:
    """Apply one idempotent consumption to a persisted window state."""

    operation_id = str(operation_id).strip()
    if not operation_id:
        raise ValueError("掷骰干预窗口消费需要 operation_id")
    current = dict(state)
    consumed_for = current.get("consumed_for_operation_id")
    if consumed_for == operation_id:
        return current
    if current.get("consumed") is True:
        raise ValueError("掷骰干预窗口已被其他操作消费")
    if not consume:
        return current
    uses = current.get("uses")
    if isinstance(uses, int):
        if uses <= 0:
            raise ValueError("掷骰干预窗口次数不足")
        current["uses"] = uses - 1
        if current["uses"] == 0:
            current["consumed"] = True
    elif current.get("max_uses") == 1 or current.get("expires") == "operation":
        current["consumed"] = True
    current["consumed_for_operation_id"] = operation_id
    return current


def _operation_spec(spec: Mapping[str, object]) -> dict[str, object]:
    """Normalize the compact and expanded operation forms.

    The preferred contract is ``{"operation": {"kind": "add_die", ...}}``.
    Accepting a string operation keeps existing compilers free to emit compact
    data while the executor still has one internal shape.
    """

    raw_operation = spec.get("operation")
    if isinstance(raw_operation, Mapping):
        result = dict(raw_operation)
    elif isinstance(raw_operation, str):
        result = {"kind": raw_operation}
    else:
        raw_effect = spec.get("effect")
        result = dict(raw_effect) if isinstance(raw_effect, Mapping) else {}
    if "kind" not in result and isinstance(result.get("operation"), str):
        result["kind"] = result["operation"]
    return result


def _operation_kind(spec: Mapping[str, object]) -> str:
    return str(_operation_spec(spec).get("kind") or "").strip().casefold()


def _resource_current(resources: Mapping[str, object], key: str) -> int:
    raw = resources.get(key)
    if isinstance(raw, Mapping):
        return _integer(raw.get("current"), 0) or 0
    return _integer(raw, 0) or 0


def _bound_level(
    level_spec: Mapping[str, object], class_levels: Mapping[str, object]
) -> tuple[str, int] | None:
    class_names = _normalized_set(_string_list(level_spec.get("class_names")))
    if not class_names:
        return None
    level = max(
        (
            _integer(value, 0) or 0
            for name, value in class_levels.items()
            if str(name).strip().casefold() in class_names
        ),
        default=0,
    )
    minimum = _integer(level_spec.get("minimum"), 1)
    binding = str(level_spec.get("bind_as") or "class_level").strip()
    if minimum is None or minimum < 0 or not binding or level < minimum:
        return None
    return binding, level


def _context_set(context: Mapping[str, object], key: str) -> set[str]:
    return _normalized_set(_string_list(context.get(key)))


def _eligible_bindings(
    spec: Mapping[str, object], context: Mapping[str, object]
) -> dict[str, int] | None:
    """Return bound values when a generic eligibility contract is satisfied.

    Unknown/malformed conditions fail closed.  Optional fields are intentionally
    data-oriented rather than feature names: class level and resource values
    are exposed to amount expressions through ``bind_as`` only.
    """

    eligibility = _mapping(spec.get("eligibility"))
    conditions = _context_set(context, "conditions")
    for context_key, eligibility_key in (
        ("entity_type", "entity_types"),
        ("faction", "factions"),
        ("test_kind", "test_kinds"),
        ("ability", "abilities"),
        ("skill", "skills"),
        ("attack_type", "attack_types"),
    ):
        allowed = _normalized_set(_string_list(eligibility.get(eligibility_key)))
        if not allowed:
            continue
        context_value = str(context.get(context_key) or "").strip().casefold()
        if not context_value or context_value not in allowed:
            return None
    required = _normalized_set(_string_list(eligibility.get("required_conditions")))
    forbidden = _normalized_set(_string_list(eligibility.get("forbidden_conditions")))
    if not required.issubset(conditions) or forbidden & conditions:
        return None
    state_spec = _mapping(eligibility.get("state"))
    state_key = str(state_spec.get("key") or "").strip()
    if state_key:
        states = _mapping(context.get("feature_states"))
        if states.get(state_key) is not True:
            return None
    if "proficient" in eligibility:
        proficient = eligibility.get("proficient")
        if not isinstance(proficient, bool) or context.get("proficient") is not proficient:
            return None

    bindings: dict[str, int] = {}
    level_spec = _mapping(eligibility.get("level"))
    if level_spec:
        class_levels = _mapping(context.get("class_levels"))
        resolved_level = _bound_level(level_spec, class_levels)
        if resolved_level is None:
            return None
        binding, level = resolved_level
        bindings[binding] = level

    resource_spec = _mapping(eligibility.get("resource"))
    if resource_spec:
        key = str(resource_spec.get("key") or "").strip()
        minimum = _integer(resource_spec.get("minimum"), 1)
        if not key or minimum is None or minimum < 0:
            return None
        resources = _mapping(context.get("resources"))
        resource_current = _resource_current(resources, key)
        if resource_current < minimum:
            return None
        binding = str(resource_spec.get("bind_as") or "").strip()
        if binding:
            bindings[binding] = resource_current
        value_binding = str(resource_spec.get("value_bind_as") or "").strip()
        raw_resource = resources.get(key)
        raw_value = raw_resource.get("value") if isinstance(raw_resource, Mapping) else None
        if value_binding and isinstance(raw_value, int) and not isinstance(raw_value, bool):
            bindings[value_binding] = raw_value
        elif value_binding and isinstance(raw_value, str):
            match = re.fullmatch(r"[dD]?(\d+)", raw_value.strip())
            if match:
                bindings[value_binding] = int(match.group(1))
        if value_binding and value_binding not in bindings:
            return None
    return bindings


def resolve_roll_interventions(
    interventions: Iterable[Mapping[str, object]],
    *,
    trigger: str,
    context: Mapping[str, object],
) -> list[dict[str, object]]:
    """Return eligible generic intervention configurations for one roll event.

    Returned data includes the evaluated eligibility bindings but remains a
    copy, so services may append prompt metadata without mutating a combat
    snapshot.  This resolver deliberately returns no malformed configuration
    rather than guessing a rule from a feature identifier.
    """

    normalized_trigger = str(trigger).strip().casefold()
    if not normalized_trigger:
        return []
    resolved: list[dict[str, object]] = []
    for raw_spec in interventions:
        spec = dict(raw_spec)
        feature_id = str(spec.get("id") or "").strip()
        operation = _operation_kind(spec)
        if (
            spec.get("kind") != ROLL_INTERVENTION_KIND
            or str(spec.get("trigger") or "").strip().casefold() != normalized_trigger
            or not feature_id
            or operation not in ROLL_INTERVENTION_OPERATIONS
        ):
            continue
        # Validate lifecycle metadata even when the current phase is selected
        # by a different consumer.  This prevents malformed persisted feature
        # windows from leaking into API projections or being applied later.
        try:
            window = validate_roll_intervention_window(spec)
        except ValueError:
            continue
        if window.get("phase") != normalized_trigger:
            continue
        bindings = _eligible_bindings(spec, context)
        if bindings is None:
            continue
        copied = deepcopy(spec)
        copied["window"] = window
        copied["resolved_bindings"] = bindings
        resolved.append(copied)
    return resolved


def resolve_roll_intervention(
    interventions: Iterable[Mapping[str, object]],
    *,
    trigger: str,
    context: Mapping[str, object],
) -> dict[str, object] | None:
    """Return the first eligible intervention, preserving configuration order."""

    resolved = resolve_roll_interventions(
        interventions,
        trigger=trigger,
        context=context,
    )
    return resolved[0] if resolved else None


def _expression_tokens(expression: str) -> list[str] | None:
    compact = expression.replace(" ", "")
    if not compact or "".join(_INTEGER_EXPRESSION.findall(compact)) != compact:
        return None
    tokens = _INTEGER_EXPRESSION.findall(compact)
    if not tokens:
        return None
    expects_atom = True
    for token in tokens:
        is_atom = _INTEGER_ATOM.fullmatch(token) is not None
        if expects_atom != is_atom:
            return None
        expects_atom = not expects_atom
    return None if expects_atom else tokens


def evaluate_roll_intervention_amount(
    expression: object,
    *,
    bindings: Mapping[str, int],
    inputs: Mapping[str, object],
) -> int | None:
    """Evaluate a deliberately small integer expression without ``eval``.

    The grammar is atoms joined by ``+``, ``-`` or ``*`` with ordinary
    multiplication precedence.  It covers static bonuses and level/proficiency bindings,
    while refusing arbitrary Python or dice notation (dice must be reported
    through ``add_die`` input instead).
    """

    literal = _integer(expression)
    if literal is not None:
        return literal
    if not isinstance(expression, str):
        return None
    tokens = _expression_tokens(expression)
    if tokens is None:
        return None
    names: dict[str, int] = {
        str(key): value for key, value in bindings.items() if isinstance(value, int)
    }
    names.update(
        {
            str(key): value
            for key, value in inputs.items()
            if isinstance(value, int) and not isinstance(value, bool)
        }
    )

    def atom(token: str) -> int | None:
        return int(token) if token.isdigit() else names.get(token)

    term = atom(tokens[0])
    if term is None:
        return None
    total = 0
    sign = 1
    for operator, token in zip(tokens[1::2], tokens[2::2], strict=True):
        value = atom(token)
        if value is None:
            return None
        if operator == "*":
            term *= value
        else:
            total += sign * term
            sign = 1 if operator == "+" else -1
            term = value
        if abs(total) > _MAX_TOTAL or abs(term) > _MAX_TOTAL:
            return None
    result = total + sign * term
    return result if abs(result) <= _MAX_TOTAL else None


def _input_requirements(spec: Mapping[str, object]) -> list[dict[str, object]]:
    raw = spec.get("input_requirements")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("掷骰干预输入要求格式无效")
    requirements: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_requirement in raw:
        requirement = _mapping(raw_requirement)
        key = str(requirement.get("key") or "").strip()
        kind = str(requirement.get("kind") or "").strip()
        if not key or not kind or key in seen:
            raise ValueError(f"掷骰干预输入要求无效：{key or 'unknown'}")
        seen.add(key)
        requirements.append(requirement)
    return requirements


def _validate_requirement(requirement: Mapping[str, object], value: object) -> None:
    key = str(requirement.get("key") or "").strip()
    kind = str(requirement.get("kind") or "").strip()
    number = _integer(value)
    if number is None:
        raise ValueError(f"掷骰干预缺少输入：{key}")
    if kind == "d20_roll":
        if not 1 <= number <= 20:
            raise ValueError(f"掷骰干预 d20 输入超出范围：{key}")
    elif kind == "die_roll":
        sides = _integer(requirement.get("die_sides"))
        if sides is None or sides < 1 or not 1 <= number <= sides:
            raise ValueError(f"掷骰干预骰子输入超出范围：{key}")
    elif kind == "roll_total":
        if not -_MAX_TOTAL <= number <= _MAX_TOTAL:
            raise ValueError(f"掷骰干预总值输入超出范围：{key}")
    elif kind == "signed_unit":
        if number not in {-1, 1}:
            raise ValueError(f"掷骰干预方向输入必须为 -1 或 1：{key}")
    elif kind != "integer":
        raise ValueError(f"暂未接入该掷骰干预输入类型：{key}")


def validate_roll_intervention_input(
    spec: Mapping[str, object], inputs: Mapping[str, object]
) -> None:
    """Validate declared external input and reject undeclared values."""

    requirements = _input_requirements(spec)
    expected = {str(requirement["key"]) for requirement in requirements}
    for requirement in requirements:
        _validate_requirement(requirement, inputs.get(str(requirement["key"])))
    unexpected = {
        str(key).strip()
        for key, value in inputs.items()
        if value is not None and str(key).strip() not in expected
    }
    if unexpected:
        raise ValueError(f"掷骰干预包含未声明输入：{', '.join(sorted(unexpected))}")


def _reported_totals(roll_total: object, roll_totals: Iterable[object]) -> list[int]:
    current = _integer(roll_total)
    if current is None or not -_MAX_TOTAL <= current <= _MAX_TOTAL:
        raise ValueError("掷骰干预原始总值无效")
    reported = [_integer(value) for value in roll_totals]
    if any(value is None or not -_MAX_TOTAL <= value <= _MAX_TOTAL for value in reported):
        raise ValueError("掷骰干预报告总值无效")
    values = [int(value) for value in reported if value is not None]
    return values or [current]


def _minimum(
    operation: Mapping[str, object], *, bindings: Mapping[str, int], inputs: Mapping[str, object]
) -> int:
    value = evaluate_roll_intervention_amount(
        operation.get("minimum"), bindings=bindings, inputs=inputs
    )
    if value is None:
        raise ValueError("掷骰干预最低值配置无效")
    return value


def _natural_roll(
    operation: Mapping[str, object],
    *,
    natural_roll: int | None,
    inputs: Mapping[str, object],
) -> int:
    input_key = str(operation.get("d20_input_key") or "d20_roll").strip()
    reported = natural_roll if natural_roll is not None else _integer(inputs.get(input_key))
    if reported is None or not 1 <= reported <= 20:
        raise ValueError("掷骰干预需要有效的天然 d20 结果")
    return reported


def _add_die_amount(
    operation: Mapping[str, object],
    *,
    inputs: Mapping[str, object],
    bindings: Mapping[str, int],
) -> int:
    input_key = str(operation.get("input_key") or "die_roll").strip()
    sides = _integer(operation.get("die_sides"))
    if sides is None and operation.get("die_sides_expression") is not None:
        sides = evaluate_roll_intervention_amount(
            operation.get("die_sides_expression"), bindings=bindings, inputs=inputs
        )
    value = _integer(inputs.get(input_key))
    if not input_key or sides is None or sides < 1 or value is None or not 1 <= value <= sides:
        raise ValueError("掷骰干预加骰输入无效")
    return value


def _two_reported_totals(reported_totals: list[int], *, label: str) -> tuple[int, int]:
    if len(reported_totals) != 2:
        raise ValueError(f"{label}需要提交恰好两个总值")
    return reported_totals[0], reported_totals[1]


def _apply_operation(
    operation: Mapping[str, object],
    *,
    original_total: int,
    reported_totals: list[int],
    inputs: Mapping[str, object],
    bindings: Mapping[str, int],
    natural_roll: int | None,
) -> tuple[int, dict[str, object]]:
    kind = str(operation.get("kind") or "").strip().casefold()
    if kind not in ROLL_INTERVENTION_OPERATIONS - {"failure_recovery"}:
        raise ValueError("暂未接入该掷骰干预操作")
    details: dict[str, object] = {}
    if kind in {"reroll", "reroll_with_add"}:
        pair = _two_reported_totals(reported_totals, label="重骰")
        if pair[0] != original_total:
            raise ValueError("重骰的第一个总值必须是原始总值")
        selection = str(operation.get("selection") or "replacement").strip().casefold()
        if selection == "replacement":
            effective = pair[1]
        elif selection == "highest":
            effective = max(pair)
        elif selection == "lowest":
            effective = min(pair)
        else:
            raise ValueError("重骰选择方式无效")
        details["reported_totals"] = tuple(pair)
        details["selection"] = selection
        if kind == "reroll_with_add":
            amount = evaluate_roll_intervention_amount(
                operation.get("amount", operation.get("value")),
                bindings=bindings,
                inputs=inputs,
            )
            if amount is None:
                raise ValueError("重骰加值配置无效")
            details["amount"] = amount
            effective += amount
        return effective, details
    if kind in {"advantage", "disadvantage"}:
        pair = _two_reported_totals(reported_totals, label="优势或劣势")
        details["reported_totals"] = tuple(pair)
        return (max(pair) if kind == "advantage" else min(pair)), details
    if kind == "add":
        amount = evaluate_roll_intervention_amount(
            operation.get("amount", operation.get("value")), bindings=bindings, inputs=inputs
        )
        if amount is None:
            raise ValueError("掷骰干预加值配置无效")
        details["amount"] = amount
        return original_total + amount, details
    if kind == "add_die":
        amount = _add_die_amount(operation, inputs=inputs, bindings=bindings)
        details["die_roll"] = amount
        details["die_sides"] = _integer(operation.get("die_sides"))
        return original_total + amount, details
    if kind in {"set_minimum", "set_minimum_d20"}:
        minimum = _minimum(operation, bindings=bindings, inputs=inputs)
        raw_basis = operation.get("basis")
        if raw_basis is None and kind == "set_minimum_d20":
            raw_basis = "d20"
        basis = str(raw_basis or "").strip().casefold()
        if basis == "total":
            details["minimum"] = minimum
            details["basis"] = basis
            return max(original_total, minimum), details
        if basis != "d20":
            raise ValueError("掷骰干预最低值依据无效")
        before = _natural_roll(operation, natural_roll=natural_roll, inputs=inputs)
        after = max(before, minimum)
        details.update(
            {
                "minimum": minimum,
                "basis": basis,
                "natural_roll_before": before,
                "natural_roll_after": after,
            }
        )
        return original_total + after - before, details
    # replace_d20
    replacement = _minimum(operation, bindings=bindings, inputs=inputs)
    if not 1 <= replacement <= 20:
        raise ValueError("替换 d20 结果必须在 1 到 20 之间")
    before = _natural_roll(operation, natural_roll=natural_roll, inputs=inputs)
    details.update({"natural_roll_before": before, "natural_roll_after": replacement})
    return original_total + replacement - before, details


def roll_intervention_idempotency_key(
    spec: Mapping[str, object], *, operation_id: str | None
) -> str | None:
    """Return a persistence key without persisting or consuming anything.

    Services use the returned key to make a prompt confirmation idempotent.
    An omitted operation ID intentionally returns ``None``: a shared rule
    definition alone is never enough to identify one combat-roll attempt.
    """

    if not operation_id:
        return None
    feature_id = str(spec.get("id") or "").strip()
    if not feature_id:
        return None
    idempotency = _mapping(spec.get("idempotency"))
    prefix = str(idempotency.get("prefix") or feature_id).strip()
    return f"{prefix}:{operation_id}" if prefix else None


def apply_roll_intervention(
    spec: Mapping[str, object],
    *,
    roll_total: int,
    roll_totals: Iterable[int] = (),
    inputs: Mapping[str, object] | None = None,
    bindings: Mapping[str, int] | None = None,
    natural_roll: int | None = None,
    dc: int | None = None,
    operation_id: str | None = None,
) -> dict[str, object]:
    """Apply one feature-ID-agnostic roll transform.

    Dice values are reported input, never server-generated.  ``failure_recovery``
    applies its nested ``recovery`` operation only after a failed total and
    returns whether a resource should be consumed; resource mutation stays in
    the caller's confirmed/idempotent persistence transaction.
    """

    if spec.get("kind") != ROLL_INTERVENTION_KIND:
        raise ValueError("不是有效的掷骰干预配置")
    feature_id = str(spec.get("id") or "").strip()
    if not feature_id:
        raise ValueError("掷骰干预缺少配置标识")
    operation = _operation_spec(spec)
    kind = str(operation.get("kind") or "").strip().casefold()
    if kind not in ROLL_INTERVENTION_OPERATIONS:
        raise ValueError("暂未接入该掷骰干预操作")
    actual_inputs = dict(inputs or {})
    actual_bindings = {
        str(key): value
        for key, value in _mapping(spec.get("resolved_bindings")).items()
        if isinstance(value, int) and not isinstance(value, bool)
    }
    actual_bindings.update(
        {
        str(key): value
        for key, value in (bindings or {}).items()
        if isinstance(value, int) and not isinstance(value, bool)
        }
    )
    validate_roll_intervention_input(spec, actual_inputs)
    reported_totals = _reported_totals(roll_total, roll_totals)
    original_total = _integer(roll_total)
    assert original_total is not None

    failure_recovery = kind == "failure_recovery"
    consume_when = "on_confirm"
    if failure_recovery:
        if dc is None or not -_MAX_TOTAL <= dc <= _MAX_TOTAL:
            raise ValueError("失败补救需要有效的难度等级")
        if original_total >= dc:
            raise ValueError("失败补救只能用于失败的掷骰")
        recovery = _mapping(operation.get("recovery") or operation.get("recovery_operation"))
        recovery_kind = str(recovery.get("kind") or "").strip().casefold()
        if not recovery or recovery_kind == "failure_recovery":
            raise ValueError("失败补救缺少有效的补救操作")
        effective_total, details = _apply_operation(
            recovery,
            original_total=original_total,
            reported_totals=reported_totals,
            inputs=actual_inputs,
            bindings=actual_bindings,
            natural_roll=natural_roll,
        )
        consume_when = str(operation.get("consume_when") or "on_success").strip().casefold()
        if consume_when not in {"on_success", "on_confirm", "never"}:
            raise ValueError("失败补救资源消耗时机无效")
        details["recovery_operation"] = recovery_kind
    else:
        effective_total, details = _apply_operation(
            operation,
            original_total=original_total,
            reported_totals=reported_totals,
            inputs=actual_inputs,
            bindings=actual_bindings,
            natural_roll=natural_roll,
        )

    if not -_MAX_TOTAL <= effective_total <= _MAX_TOTAL:
        raise ValueError("掷骰干预结果超出允许范围")
    success = effective_total >= dc if dc is not None else None
    resource = _mapping(spec.get("resource"))
    if resource:
        resource_key = str(resource.get("key") or "").strip()
        resource_cost = _integer(resource.get("cost"), 1)
        if not resource_key or resource_cost is None or resource_cost < 1:
            raise ValueError("掷骰干预资源配置无效")
    should_consume = bool(resource)
    if failure_recovery:
        should_consume = bool(resource) and (
            consume_when == "on_confirm" or (consume_when == "on_success" and success is True)
        )
        if consume_when == "never":
            should_consume = False
    return {
        "feature_id": feature_id,
        "operation": kind,
        "original_total": original_total,
        "effective_total": effective_total,
        "delta": effective_total - original_total,
        "success": success,
        "failure_recovered": failure_recovery and success is True,
        "resource": deepcopy(resource) if resource else None,
        "resource_should_consume": should_consume,
        "resource_consume_when": consume_when if resource else None,
        "idempotency_key": roll_intervention_idempotency_key(spec, operation_id=operation_id),
        "details": details,
    }
