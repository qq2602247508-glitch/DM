from datetime import UTC, datetime

import pytest

from dnd_dm_assistant.domain.rests import (
    HitDieSpend,
    RestResource,
    resolve_long_rest,
    resolve_short_rest,
)


def test_short_rest_requires_at_least_one_hp() -> None:
    with pytest.raises(ValueError, match="at least 1 HP"):
        resolve_short_rest(
            current_hp=0,
            max_hp=12,
            constitution_modifier=2,
            hit_dice={"d8": 1},
            spends=(),
            resources=(),
        )


def test_short_rest_spends_each_hit_die_and_caps_healing() -> None:
    result = resolve_short_rest(
        current_hp=14,
        max_hp=15,
        constitution_modifier=-3,
        hit_dice={"d8": 2},
        spends=(HitDieSpend(die="d8", roll=2), HitDieSpend(die="d8", roll=8)),
        resources=(RestResource("focus", current=0, maximum=3, recovery="short_rest"),),
    )

    # Each die heals at least one, then HP is capped at the maximum.
    assert result.hp_gained == 1
    assert result.current_hp == 15
    assert result.hit_dice == {"d8": 0}
    assert result.resources == (RestResource("focus", 3, 3, "short_rest"),)


def test_short_rest_rejects_spending_more_hit_dice_than_available() -> None:
    with pytest.raises(ValueError, match="not available"):
        resolve_short_rest(
            current_hp=4,
            max_hp=10,
            constitution_modifier=0,
            hit_dice={"d6": 1},
            spends=(HitDieSpend(die="d6", roll=3), HitDieSpend(die="d6", roll=4)),
            resources=(),
        )


def test_interrupted_short_rest_has_no_benefits_or_resource_refresh() -> None:
    resources = (
        RestResource("focus", current=0, maximum=3, recovery="short_rest"),
        RestResource("luck", current=0, maximum=1, recovery="long_rest"),
    )

    result = resolve_short_rest(
        current_hp=4,
        max_hp=10,
        constitution_modifier=2,
        hit_dice={"d8": 1},
        spends=(HitDieSpend(die="d8", roll=8),),
        resources=resources,
        interrupted=True,
    )

    assert result.completed is False
    assert result.current_hp == 4
    assert result.hit_dice == {"d8": 1}
    assert result.resources == resources


def test_long_rest_recovers_hp_eligible_resources_and_one_fatigue() -> None:
    started_at = datetime(2026, 7, 26, 22, tzinfo=UTC)
    resources = (
        RestResource("focus", current=0, maximum=3, recovery="short_rest"),
        RestResource("slots", current=1, maximum=4, recovery="long_rest"),
        RestResource("dawn", current=0, maximum=1, recovery="dawn"),
        RestResource("special", current=0, maximum=1, recovery="special"),
        RestResource("unknown", current=0, maximum=1, recovery=None),
    )

    result = resolve_long_rest(
        current_hp=3,
        max_hp=19,
        fatigue=2,
        resources=resources,
        started_at=started_at,
    )

    assert result.completed is True
    assert result.current_hp == 19
    assert result.fatigue == 1
    assert result.ends_at == datetime(2026, 7, 27, 6, tzinfo=UTC)
    assert result.resources == (
        RestResource("focus", 3, 3, "short_rest"),
        RestResource("slots", 4, 4, "long_rest"),
        RestResource("dawn", 0, 1, "dawn"),
        RestResource("special", 0, 1, "special"),
        RestResource("unknown", 0, 1, None),
    )


def test_long_rest_requires_at_least_one_hp() -> None:
    with pytest.raises(ValueError, match="at least 1 HP"):
        resolve_long_rest(
            current_hp=0,
            max_hp=12,
            fatigue=0,
            resources=(),
        )


def test_null_start_time_is_safe_for_both_rest_types() -> None:
    short = resolve_short_rest(
        current_hp=1,
        max_hp=8,
        constitution_modifier=0,
        hit_dice={},
        spends=(),
        resources=(),
        started_at=None,
    )
    long = resolve_long_rest(
        current_hp=1,
        max_hp=8,
        fatigue=0,
        resources=(),
        started_at=None,
    )

    assert short.ends_at is None
    assert long.ends_at is None
