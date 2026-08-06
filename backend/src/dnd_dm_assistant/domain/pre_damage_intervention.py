"""Configuration-driven damage-before-resolution interventions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

KIND = "pre_damage_intervention"


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _expression(expression: object, bindings: Mapping[str, int]) -> int | None:
    text = str(expression or "").replace(" ", "")
    parts = text.split("+")
    if not parts or any(not part for part in parts):
        return None
    total = 0
    for part in parts:
        if part.isdigit():
            total += int(part)
            continue
        value = bindings.get(part)
        if not isinstance(value, int):
            return None
        total += value
    return total


def validate_intervention_input(spec: Mapping[str, object], inputs: Mapping[str, object]) -> None:
    """Fail closed when the frozen configuration requires missing/invalid input."""
    requirements = spec.get("input_requirements")
    if not isinstance(requirements, list):
        requirements = []
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            raise ValueError("伤害前反应输入要求格式无效")
        key = str(requirement.get("key") or "").strip()
        value = _number(inputs.get(key))
        if not key or value is None:
            raise ValueError(f"伤害前反应缺少输入：{key or 'unknown'}")
        if requirement.get("kind") == "die_roll":
            sides = _number(requirement.get("die_sides"))
            if sides is None or value < 1 or value > sides:
                raise ValueError(f"伤害前反应输入超出骰子范围：{key}")


def apply_pre_damage_intervention(
    command: Any,
    spec: Mapping[str, object],
    *,
    inputs: Mapping[str, object],
    bindings: Mapping[str, int] | None = None,
) -> tuple[Any, dict[str, object]]:
    """Apply a generic configured transform before defenses and HP."""
    if spec.get("kind") != KIND:
        raise ValueError("不是有效的伤害前反应配置")
    validate_intervention_input(spec, inputs)
    transform = spec.get("damage_transform")
    transform = transform if isinstance(transform, Mapping) else {}
    operation = str(transform.get("operation") or "").strip()
    components = list(getattr(command, "damage_components", None) or [])
    original = (
        [int(component.amount) for component in components] if components else [int(command.amount)]
    )
    values = list(original)
    if operation == "multiply_each_component":
        multiplier = transform.get("multiplier")
        if not isinstance(multiplier, (int, float)) or multiplier < 0:
            raise ValueError("伤害前反应倍率配置无效")
        values = [max(0, int(amount * multiplier)) for amount in values]
    elif operation == "subtract_total":
        names = {key: value for key, value in (bindings or {}).items() if isinstance(value, int)}
        names.update({key: value for key, value in inputs.items() if isinstance(value, int)})
        amount = _expression(transform.get("amount"), names)
        if amount is None or amount < 0:
            raise ValueError("伤害前反应减伤公式无效")
        remaining = amount
        values = []
        for value in original:
            reduction = min(value, remaining)
            values.append(max(0, value - reduction))
            remaining = max(0, remaining - value)
    else:
        raise ValueError("暂未接入该伤害前变换")
    if components:
        updated = [
            component.model_copy(update={"amount": value})
            for component, value in zip(components, values, strict=True)
        ]
        result = command.model_copy(update={"amount": sum(values), "damage_components": updated})
    else:
        result = command.model_copy(update={"amount": values[0]})
    return result, {
        "operation": operation,
        "original_amount": sum(original),
        "result_amount": sum(values),
        "delta": sum(original) - sum(values),
        "zero_damage": sum(values) == 0,
    }
