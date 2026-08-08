"""Configuration-driven attack-resolution interventions.

These contracts pause an attack after a provisional hit/miss decision and
before damage lands, then recompute the authoritative outcome.  They are
deliberately name-agnostic: callers supply structured eligibility, operation
and cost data rather than feature IDs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

KIND = "attack_resolution_intervention"
SUPPORTED_OPERATIONS = frozenset(
    {
        "add_to_target_ac",
        "subtract_from_attack_total",
        "impose_disadvantage",
    }
)
SUPPORTED_PHASES = frozenset(
    {
        "after_provisional_hit",
        "before_attack_roll_resolution",
        "after_final_attack_resolution",
    }
)


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _expression(expression: object, bindings: Mapping[str, int]) -> int | None:
    text = str(expression or "").replace(" ", "")
    if not text:
        return None
    parts = text.split("+")
    if any(not part for part in parts):
        return None
    total = 0
    for part in parts:
        if part.isdigit() or (part.startswith("-") and part[1:].isdigit()):
            total += int(part)
            continue
        if part.startswith("max(") and part.endswith(")"):
            inner = part[4:-1]
            args = [item.strip() for item in inner.split(",")]
            values: list[int] = []
            for arg in args:
                if arg.isdigit() or (arg.startswith("-") and arg[1:].isdigit()):
                    values.append(int(arg))
                    continue
                bound = bindings.get(arg)
                if not isinstance(bound, int):
                    return None
                values.append(bound)
            if not values:
                return None
            total += max(values)
            continue
        bound = bindings.get(part)
        if not isinstance(bound, int):
            return None
        total += bound
    return total


def validate_attack_resolution_spec(spec: Mapping[str, object]) -> None:
    if spec.get("kind") != KIND:
        raise ValueError("不是有效的攻击决议干预配置")
    phase = str(spec.get("phase") or "").strip()
    if phase not in SUPPORTED_PHASES:
        raise ValueError(f"暂未接入该攻击决议阶段：{phase or 'missing'}")
    operation = spec.get("operation")
    if not isinstance(operation, Mapping):
        raise ValueError("攻击决议干预缺少 operation")
    op_kind = str(operation.get("kind") or "").strip()
    if op_kind not in SUPPORTED_OPERATIONS:
        raise ValueError(f"暂未接入该攻击决议操作：{op_kind or 'missing'}")


def validate_attack_resolution_input(
    spec: Mapping[str, object],
    inputs: Mapping[str, object],
) -> None:
    validate_attack_resolution_spec(spec)
    requirements = spec.get("input_requirements")
    if not isinstance(requirements, list):
        requirements = []
    expected: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            raise ValueError("攻击决议输入要求格式无效")
        key = str(requirement.get("key") or "").strip()
        if not key or key in expected:
            raise ValueError(f"攻击决议重复或无效输入：{key or 'unknown'}")
        expected.add(key)
        value = _number(inputs.get(key))
        if value is None:
            raise ValueError(f"攻击决议缺少输入：{key}")
        if requirement.get("kind") == "die_roll":
            sides = _number(requirement.get("die_sides"))
            if sides is None or value < 1 or value > sides:
                raise ValueError(f"攻击决议输入超出骰子范围：{key}")
        elif requirement.get("kind") != "integer":
            raise ValueError(f"暂未接入该攻击决议输入类型：{key}")
    unexpected = {
        str(key).strip()
        for key, value in inputs.items()
        if value is not None and str(key).strip() not in expected
    }
    if unexpected:
        raise ValueError(f"攻击决议包含未声明输入：{', '.join(sorted(unexpected))}")


def apply_attack_resolution_intervention(
    *,
    attack_roll_total: int | None,
    base_armor_class: int,
    cover_bonus: int = 0,
    critical_hit: bool = False,
    automatic_critical: bool = False,
    attack_roll_mode: str | None = None,
    attack_rolls: list[int] | None = None,
    attack_roll_totals: list[int] | None = None,
    spec: Mapping[str, object],
    inputs: Mapping[str, object] | None = None,
    bindings: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Return the recomputed attack outcome for a frozen intervention."""

    validate_attack_resolution_input(spec, inputs or {})
    operation = spec.get("operation")
    assert isinstance(operation, Mapping)
    op_kind = str(operation.get("kind") or "").strip()
    names = {key: value for key, value in (bindings or {}).items() if isinstance(value, int)}
    names.update(
        {key: value for key, value in (inputs or {}).items() if isinstance(value, int)}
    )

    effective_attack_total = attack_roll_total
    effective_ac = base_armor_class + max(0, cover_bonus)
    ac_bonus = 0
    attack_delta = 0
    imposed_disadvantage = False
    selected_roll: int | None = None

    if op_kind == "add_to_target_ac":
        amount = _expression(operation.get("amount"), names)
        if amount is None:
            raise ValueError("攻击决议 AC 加值公式无效")
        minimum = _number(operation.get("minimum"))
        if minimum is not None:
            amount = max(amount, minimum)
        if amount < 0:
            raise ValueError("攻击决议 AC 加值不能为负")
        ac_bonus = amount
        effective_ac += amount
    elif op_kind == "subtract_from_attack_total":
        if effective_attack_total is None:
            raise ValueError("攻击决议缺少可扣减的攻击总值")
        amount = _expression(operation.get("amount"), names)
        if amount is None or amount < 0:
            raise ValueError("攻击决议攻击减值公式无效")
        attack_delta = -amount
        effective_attack_total = effective_attack_total - amount
    elif op_kind == "impose_disadvantage":
        rolls = [int(value) for value in attack_rolls or []]
        if len(rolls) < 2:
            raise ValueError("施加劣势必须提交两个真实 d20 结果")
        if any(value < 1 or value > 20 for value in rolls[:2]):
            raise ValueError("劣势 d20 必须在 1–20 之间")
        imposed_disadvantage = True
        selected_roll = min(rolls[:2])
        totals = [int(value) for value in attack_roll_totals or []]
        if totals:
            if len(totals) != len(rolls):
                raise ValueError("施加劣势的 d20 与总值数量必须一致")
            if any(value < -100 or value > 1_000 for value in totals):
                raise ValueError("劣势攻击总值超出允许范围")
            selected_index = rolls.index(selected_roll)
            effective_attack_total = totals[selected_index]
        else:
            bonus = 0
            if effective_attack_total is not None and attack_roll_total is not None:
                # Preserve any non-d20 bonus that the provisional total included.
                bonus = (
                    effective_attack_total - max(rolls[:2])
                    if attack_roll_mode == "advantage"
                    else (effective_attack_total - rolls[0] if rolls else 0)
                )
            if attack_roll_total is not None and len(rolls) >= 1 and bonus == 0:
                natural = rolls[0]
                bonus = attack_roll_total - natural
            effective_attack_total = selected_roll + bonus
    else:  # pragma: no cover - guarded by validate
        raise ValueError(f"暂未接入该攻击决议操作：{op_kind}")

    if automatic_critical or critical_hit:
        hit = True
        hit_basis = "critical"
    elif effective_attack_total is None:
        raise ValueError("攻击决议缺少可重算的攻击总值")
    else:
        hit = effective_attack_total >= effective_ac
        hit_basis = "attack_roll"

    return {
        "operation": op_kind,
        "hit": hit,
        "hit_basis": hit_basis,
        "attack_roll_total": attack_roll_total,
        "effective_attack_total": effective_attack_total,
        "base_armor_class": base_armor_class,
        "cover_bonus": cover_bonus,
        "ac_bonus": ac_bonus,
        "attack_delta": attack_delta,
        "effective_armor_class": effective_ac,
        "imposed_disadvantage": imposed_disadvantage,
        "selected_d20": selected_roll,
        "became_miss": not hit,
    }
