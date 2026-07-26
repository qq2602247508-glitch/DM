from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DamageModifier = Literal["normal", "resistance", "vulnerability", "immunity"]

_DAMAGE_TYPE_LABELS = {
    "acid": "强酸",
    "bludgeoning": "钝击",
    "cold": "寒冷",
    "fire": "火焰",
    "force": "力场",
    "lightning": "闪电",
    "necrotic": "黯蚀",
    "piercing": "穿刺",
    "poison": "毒素",
    "psychic": "心灵",
    "radiant": "光耀",
    "slashing": "挥砍",
    "thunder": "雷鸣",
}


@dataclass(frozen=True, slots=True)
class DamageResolution:
    original_damage: int
    adjusted_damage: int
    damage_type: str
    modifier: DamageModifier
    temporary_hp_lost: int
    hp_lost: int
    remaining_temporary_hp: int
    remaining_hp: int
    unapplied_damage: int
    explanation: str


@dataclass(frozen=True, slots=True)
class HealingResolution:
    requested_healing: int
    hp_gained: int
    remaining_hp: int
    effective_max_hp: int
    unapplied_healing: int


@dataclass(frozen=True, slots=True)
class MaxHpReductionResolution:
    added_reduction: int
    max_hp_reduction: int
    effective_max_hp: int
    hp_lost: int
    remaining_hp: int


@dataclass(frozen=True, slots=True)
class DeathSaveResolution:
    roll: int
    successes: int
    failures: int
    stable: bool
    dead: bool
    pending_death_confirmation: bool
    hp_restored: int
    explanation: str


def _non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _normalized_types(values: tuple[str, ...]) -> frozenset[str]:
    return frozenset(value.strip().lower() for value in values if value.strip())


def resolve_damage(
    *,
    amount: int,
    current_hp: int,
    temporary_hp: int,
    damage_type: str,
    resistances: tuple[str, ...],
    vulnerabilities: tuple[str, ...],
    immunities: tuple[str, ...],
) -> DamageResolution:
    _non_negative("amount", amount)
    _non_negative("current_hp", current_hp)
    _non_negative("temporary_hp", temporary_hp)
    normalized_type = damage_type.strip().lower()
    if not normalized_type:
        raise ValueError("damage_type must not be blank")

    resistant = normalized_type in _normalized_types(resistances)
    vulnerable = normalized_type in _normalized_types(vulnerabilities)
    immune = normalized_type in _normalized_types(immunities)
    modifier: DamageModifier = "normal"
    adjusted = amount
    adjustment_text = ""
    if immune:
        modifier = "immunity"
        adjusted = 0
        adjustment_text = " → 免疫使伤害归零"
    elif resistant and not vulnerable:
        modifier = "resistance"
        adjusted = amount // 2
        adjustment_text = f" → 抗性减半向下取整为 {adjusted}"
    elif vulnerable and not resistant:
        modifier = "vulnerability"
        adjusted = amount * 2
        adjustment_text = f" → 易伤翻倍为 {adjusted}"

    temporary_hp_lost = min(temporary_hp, adjusted)
    remaining_after_temporary = adjusted - temporary_hp_lost
    hp_lost = min(current_hp, remaining_after_temporary)
    unapplied = remaining_after_temporary - hp_lost
    label = _DAMAGE_TYPE_LABELS.get(normalized_type, normalized_type)
    explanation = f"{amount} 点{label}伤害{adjustment_text}"
    if temporary_hp_lost:
        explanation += f" → 临时生命吸收 {temporary_hp_lost}"
    explanation += f" → HP 扣除 {hp_lost}"
    return DamageResolution(
        original_damage=amount,
        adjusted_damage=adjusted,
        damage_type=normalized_type,
        modifier=modifier,
        temporary_hp_lost=temporary_hp_lost,
        hp_lost=hp_lost,
        remaining_temporary_hp=temporary_hp - temporary_hp_lost,
        remaining_hp=current_hp - hp_lost,
        unapplied_damage=unapplied,
        explanation=explanation,
    )


def resolve_healing(
    *,
    amount: int,
    current_hp: int,
    max_hp: int,
    max_hp_reduction: int,
) -> HealingResolution:
    for name, value in (
        ("amount", amount),
        ("current_hp", current_hp),
        ("max_hp", max_hp),
        ("max_hp_reduction", max_hp_reduction),
    ):
        _non_negative(name, value)
    effective_max = max(0, max_hp - min(max_hp, max_hp_reduction))
    bounded_current = min(current_hp, effective_max)
    gained = min(amount, effective_max - bounded_current)
    return HealingResolution(
        requested_healing=amount,
        hp_gained=gained,
        remaining_hp=bounded_current + gained,
        effective_max_hp=effective_max,
        unapplied_healing=amount - gained,
    )


def apply_max_hp_reduction(
    *,
    amount: int,
    current_hp: int,
    max_hp: int,
    current_reduction: int,
) -> MaxHpReductionResolution:
    for name, value in (
        ("amount", amount),
        ("current_hp", current_hp),
        ("max_hp", max_hp),
        ("current_reduction", current_reduction),
    ):
        _non_negative(name, value)
    reduction = min(max_hp, current_reduction + amount)
    effective_max = max_hp - reduction
    remaining_hp = min(current_hp, effective_max)
    return MaxHpReductionResolution(
        added_reduction=reduction - min(max_hp, current_reduction),
        max_hp_reduction=reduction,
        effective_max_hp=effective_max,
        hp_lost=current_hp - remaining_hp,
        remaining_hp=remaining_hp,
    )


def resolve_death_save(
    *,
    roll: int,
    successes: int,
    failures: int,
) -> DeathSaveResolution:
    if not 1 <= roll <= 20:
        raise ValueError("roll must be between 1 and 20")
    if not 0 <= successes <= 3:
        raise ValueError("successes must be between 0 and 3")
    if not 0 <= failures <= 3:
        raise ValueError("failures must be between 0 and 3")

    if roll == 20:
        return DeathSaveResolution(
            roll=roll,
            successes=0,
            failures=0,
            stable=False,
            dead=False,
            pending_death_confirmation=False,
            hp_restored=1,
            explanation="自然 20：恢复 1 点生命并重置死亡豁免",
        )

    next_successes = successes
    next_failures = failures
    if roll == 1:
        next_failures = min(3, failures + 2)
        explanation = "自然 1：累计两次失败"
    elif roll >= 10:
        next_successes = min(3, successes + 1)
        explanation = f"{roll}：死亡豁免成功"
    else:
        next_failures = min(3, failures + 1)
        explanation = f"{roll}：死亡豁免失败"

    stable = next_successes >= 3
    pending_death = next_failures >= 3
    if stable:
        explanation += "，角色已稳定"
    if pending_death:
        explanation += "，等待 DM 确认死亡"
    return DeathSaveResolution(
        roll=roll,
        successes=next_successes,
        failures=next_failures,
        stable=stable,
        dead=False,
        pending_death_confirmation=pending_death,
        hp_restored=0,
        explanation=explanation,
    )
