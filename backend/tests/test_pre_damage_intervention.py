from types import SimpleNamespace

import pytest

from dnd_dm_assistant.domain.pre_damage_intervention import (
    apply_pre_damage_intervention,
)


def _command(*amounts: int) -> SimpleNamespace:
    components = [
        SimpleNamespace(
            amount=amount,
            model_copy=lambda update, amount=amount: SimpleNamespace(amount=update["amount"]),
        )
        for amount in amounts
    ]
    return SimpleNamespace(
        amount=sum(amounts),
        damage_components=components,
        model_copy=lambda update: SimpleNamespace(
            **{
                "amount": update["amount"],
                "damage_components": update.get("damage_components", components),
            }
        ),
    )


def test_two_feature_ids_reuse_the_same_configuration_executor() -> None:
    halve = {
        "kind": "pre_damage_intervention",
        "damage_transform": {"operation": "multiply_each_component", "multiplier": 0.5},
        "input_requirements": [],
    }
    subtract = {
        "kind": "pre_damage_intervention",
        "damage_transform": {
            "operation": "subtract_total",
            "amount": "roll+bonus",
            "distribution": "components_in_order",
        },
        "input_requirements": [{"key": "roll", "kind": "die_roll", "die_sides": 10}],
    }
    first, first_result = apply_pre_damage_intervention(
        _command(9, 2), halve, inputs={}, bindings={}
    )
    second, second_result = apply_pre_damage_intervention(
        _command(10, 5), subtract, inputs={"roll": 4}, bindings={"bonus": 3}
    )
    assert [part.amount for part in first.damage_components] == [4, 1]
    assert first_result["operation"] == "multiply_each_component"
    assert [part.amount for part in second.damage_components] == [3, 5]
    assert second_result["delta"] == 7


def test_generic_executor_fails_closed_on_missing_bindings_and_invalid_rolls() -> None:
    spec = {
        "kind": "pre_damage_intervention",
        "damage_transform": {
            "operation": "subtract_total",
            "amount": "roll+class_level",
        },
        "input_requirements": [{"key": "roll", "kind": "die_roll", "die_sides": 6}],
    }
    with pytest.raises(ValueError, match="减伤公式"):
        apply_pre_damage_intervention(_command(10), spec, inputs={"roll": 4})
    with pytest.raises(ValueError, match="骰子范围"):
        apply_pre_damage_intervention(
            _command(10),
            spec,
            inputs={"roll": 7},
            bindings={"class_level": 3},
        )
    with pytest.raises(ValueError, match="未声明输入"):
        apply_pre_damage_intervention(
            _command(10),
            {
                "kind": "pre_damage_intervention",
                "damage_transform": {
                    "operation": "multiply_each_component",
                    "multiplier": 0.5,
                },
                "input_requirements": [],
            },
            inputs={"roll": 1},
        )
    with pytest.raises(ValueError, match="取整方式"):
        apply_pre_damage_intervention(
            _command(10),
            {
                "kind": "pre_damage_intervention",
                "damage_transform": {
                    "operation": "multiply_each_component",
                    "multiplier": 0.5,
                    "rounding": "ceiling",
                },
                "input_requirements": [],
            },
            inputs={},
        )
