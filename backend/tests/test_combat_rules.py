from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.combat import (
    apply_max_hp_reduction,
    resolve_damage,
    resolve_death_save,
    resolve_healing,
)


def test_temporary_hp_absorbs_resisted_damage_first() -> None:
    result = resolve_damage(
        amount=9,
        current_hp=20,
        temporary_hp=3,
        damage_type="fire",
        resistances=("fire",),
        vulnerabilities=(),
        immunities=(),
    )

    assert result.adjusted_damage == 4
    assert result.temporary_hp_lost == 3
    assert result.hp_lost == 1
    assert result.remaining_temporary_hp == 0
    assert result.remaining_hp == 19
    assert result.modifier == "resistance"
    assert result.explanation == "9 点火焰伤害 → 抗性减半向下取整为 4 → 临时生命吸收 3 → HP 扣除 1"


def test_vulnerability_doubles_damage() -> None:
    result = resolve_damage(
        amount=7,
        current_hp=30,
        temporary_hp=0,
        damage_type="cold",
        resistances=(),
        vulnerabilities=("cold",),
        immunities=(),
    )

    assert result.adjusted_damage == 14
    assert result.remaining_hp == 16
    assert result.modifier == "vulnerability"


def test_immunity_reduces_damage_to_zero() -> None:
    result = resolve_damage(
        amount=100,
        current_hp=8,
        temporary_hp=5,
        damage_type="poison",
        resistances=(),
        vulnerabilities=(),
        immunities=("poison",),
    )

    assert result.adjusted_damage == 0
    assert result.remaining_hp == 8
    assert result.remaining_temporary_hp == 5
    assert result.modifier == "immunity"


def test_resistance_and_vulnerability_cancel_each_other() -> None:
    result = resolve_damage(
        amount=11,
        current_hp=20,
        temporary_hp=0,
        damage_type="lightning",
        resistances=("lightning",),
        vulnerabilities=("lightning",),
        immunities=(),
    )

    assert result.adjusted_damage == 11
    assert result.modifier == "normal"


def test_chinese_damage_type_aliases_use_the_same_resistance_pipeline() -> None:
    result = resolve_damage(
        amount=9,
        current_hp=20,
        temporary_hp=0,
        damage_type="力场",
        resistances=("force",),
        vulnerabilities=(),
        immunities=(),
    )

    assert result.damage_type == "force"
    assert result.adjusted_damage == 4
    assert result.modifier == "resistance"


def test_damage_cannot_reduce_hp_below_zero() -> None:
    result = resolve_damage(
        amount=50,
        current_hp=6,
        temporary_hp=2,
        damage_type="slashing",
        resistances=(),
        vulnerabilities=(),
        immunities=(),
    )

    assert result.temporary_hp_lost == 2
    assert result.hp_lost == 6
    assert result.remaining_hp == 0
    assert result.unapplied_damage == 42


def test_healing_does_not_exceed_effective_max_hp() -> None:
    result = resolve_healing(
        amount=12,
        current_hp=15,
        max_hp=25,
        max_hp_reduction=6,
    )

    assert result.effective_max_hp == 19
    assert result.hp_gained == 4
    assert result.remaining_hp == 19
    assert result.unapplied_healing == 8


def test_max_hp_reduction_clamps_current_hp() -> None:
    result = apply_max_hp_reduction(
        amount=8,
        current_hp=24,
        max_hp=30,
        current_reduction=2,
    )

    assert result.max_hp_reduction == 10
    assert result.effective_max_hp == 20
    assert result.remaining_hp == 20
    assert result.hp_lost == 4


@pytest.mark.parametrize(
    ("roll", "successes", "failures", "expected_successes", "expected_failures"),
    [
        (10, 0, 0, 1, 0),
        (9, 0, 0, 0, 1),
        (1, 0, 0, 0, 2),
    ],
)
def test_death_save_applies_2024_roll_outcomes(
    roll: int,
    successes: int,
    failures: int,
    expected_successes: int,
    expected_failures: int,
) -> None:
    result = resolve_death_save(
        roll=roll,
        successes=successes,
        failures=failures,
    )

    assert result.successes == expected_successes
    assert result.failures == expected_failures


def test_natural_twenty_restores_one_hp_and_resets_track() -> None:
    result = resolve_death_save(roll=20, successes=2, failures=2)

    assert result.hp_restored == 1
    assert result.successes == 0
    assert result.failures == 0
    assert result.stable is False


def test_third_failure_marks_combatant_dead() -> None:
    result = resolve_death_save(roll=4, successes=0, failures=2)

    assert result.failures == 3
    assert result.pending_death_confirmation is False
    assert result.dead is True
