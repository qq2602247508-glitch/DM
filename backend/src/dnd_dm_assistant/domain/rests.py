from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

ResourceRecovery = Literal["short_rest", "long_rest", "dawn", "special"] | None


@dataclass(frozen=True, slots=True)
class RestResource:
    """A resource whose recovery timing is explicit rather than inferred."""

    key: str
    current: int
    maximum: int
    recovery: ResourceRecovery


@dataclass(frozen=True, slots=True)
class HitDieSpend:
    die: str
    roll: int


@dataclass(frozen=True, slots=True)
class ShortRestResolution:
    completed: bool
    current_hp: int
    hp_gained: int
    hit_dice: dict[str, int]
    resources: tuple[RestResource, ...]
    ends_at: datetime | None


@dataclass(frozen=True, slots=True)
class LongRestResolution:
    completed: bool
    current_hp: int
    fatigue: int
    resources: tuple[RestResource, ...]
    ends_at: datetime | None


def _non_negative(name: str, value: int) -> None:
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


def _validate_hp(current_hp: int, max_hp: int) -> None:
    _non_negative("current_hp", current_hp)
    _non_negative("max_hp", max_hp)
    if current_hp > max_hp:
        raise ValueError("current_hp must not exceed max_hp")


def _validate_resources(resources: tuple[RestResource, ...]) -> None:
    seen: set[str] = set()
    for resource in resources:
        if not resource.key.strip():
            raise ValueError("resource key must not be blank")
        if resource.key in seen:
            raise ValueError(f"duplicate resource key: {resource.key}")
        seen.add(resource.key)
        _non_negative(f"resource {resource.key} current", resource.current)
        _non_negative(f"resource {resource.key} maximum", resource.maximum)
        if resource.current > resource.maximum:
            raise ValueError(f"resource {resource.key} current must not exceed maximum")


def _rest_end(started_at: datetime | None, duration: timedelta) -> datetime | None:
    return None if started_at is None else started_at + duration


def _refresh_resources(
    resources: tuple[RestResource, ...], *, recovery: frozenset[ResourceRecovery]
) -> tuple[RestResource, ...]:
    return tuple(
        RestResource(resource.key, resource.maximum, resource.maximum, resource.recovery)
        if resource.recovery in recovery
        else resource
        for resource in resources
    )


def resolve_short_rest(
    *,
    current_hp: int,
    max_hp: int,
    constitution_modifier: int,
    hit_dice: dict[str, int],
    spends: tuple[HitDieSpend, ...],
    resources: tuple[RestResource, ...],
    interrupted: bool = False,
    started_at: datetime | None = None,
) -> ShortRestResolution:
    """Resolve a completed 2024 short rest without mutating campaign state.

    ``interrupted`` deliberately returns the original state: interrupted short
    rests confer no healing or resource recovery.
    """

    _validate_hp(current_hp, max_hp)
    if current_hp < 1:
        raise ValueError("a creature needs at least 1 HP to begin a short rest")
    _validate_resources(resources)
    remaining_dice = dict(hit_dice)
    for die, count in remaining_dice.items():
        if not die.strip():
            raise ValueError("hit die must not be blank")
        _non_negative(f"hit dice {die}", count)

    if interrupted:
        return ShortRestResolution(
            completed=False,
            current_hp=current_hp,
            hp_gained=0,
            hit_dice=remaining_dice,
            resources=resources,
            ends_at=_rest_end(started_at, timedelta(hours=1)),
        )

    healed = 0
    for spend in spends:
        if remaining_dice.get(spend.die, 0) < 1:
            raise ValueError(f"hit die {spend.die} is not available")
        if spend.roll < 1:
            raise ValueError("hit die roll must be at least 1")
        remaining_dice[spend.die] -= 1
        healed += max(1, spend.roll + constitution_modifier)

    actual_healing = min(healed, max_hp - current_hp)
    return ShortRestResolution(
        completed=True,
        current_hp=current_hp + actual_healing,
        hp_gained=actual_healing,
        hit_dice=remaining_dice,
        resources=_refresh_resources(resources, recovery=frozenset({"short_rest"})),
        ends_at=_rest_end(started_at, timedelta(hours=1)),
    )


def resolve_long_rest(
    *,
    current_hp: int,
    max_hp: int,
    fatigue: int,
    resources: tuple[RestResource, ...],
    started_at: datetime | None = None,
) -> LongRestResolution:
    """Resolve the deterministic benefits of a completed 2024 long rest.

    Dawn, special and unknown resources are intentionally preserved. Their
    triggers require their own explicit rule rather than being guessed here.
    """

    _validate_hp(current_hp, max_hp)
    if current_hp < 1:
        raise ValueError("a creature needs at least 1 HP to begin a long rest")
    _non_negative("fatigue", fatigue)
    _validate_resources(resources)
    return LongRestResolution(
        completed=True,
        current_hp=max_hp,
        fatigue=max(0, fatigue - 1),
        resources=_refresh_resources(
            resources, recovery=frozenset({"short_rest", "long_rest"})
        ),
        ends_at=_rest_end(started_at, timedelta(hours=8)),
    )
