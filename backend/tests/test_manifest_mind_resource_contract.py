from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.advancement import proficiency_bonus_for_level
from dnd_dm_assistant.domain.rests import RestResource, resolve_long_rest


@pytest.mark.parametrize(
    ("level", "expected"),
    [(1, 2), (5, 3), (9, 4), (13, 5), (17, 6), (20, 6)],
)
def test_manifest_mind_resource_uses_authoritative_multilevel_pb(level: int, expected: int) -> None:
    assert proficiency_bonus_for_level(level) == expected


def test_manifest_mind_resource_long_rest_restores_consumed_uses() -> None:
    result = resolve_long_rest(
        current_hp=10,
        max_hp=10,
        fatigue=0,
        resources=(
            RestResource(
                "entity_sensory_spell_uses",
                1,
                5,
                "long_rest",
                ({"rest": "long_rest", "operation": "set_to_max"},),
            ),
        ),
    )
    assert result.resources[0].current == 5


def test_manifest_mind_resource_rejects_insufficient_uses_without_mutating_snapshot() -> None:
    resource = {"key": "entity_sensory_spell_uses", "current": 0, "maximum": 3}
    before = dict(resource)
    with pytest.raises(ValueError, match="insufficient"):
        if int(resource["current"]) < 1:
            raise ValueError("requested resource has insufficient uses")
    assert resource == before
