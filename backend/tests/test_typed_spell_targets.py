from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.typed_spell_targets import (
    TypedSpellTargetSpec,
    resolve_typed_spell_targets,
)


def _spec() -> TypedSpellTargetSpec:
    return TypedSpellTargetSpec(
        content_id="core-phb-2024:spell:longstrider",
        source_record_id="6f5b6f21ffa22e705a9bd6cb",
        source_fingerprint="8" * 64,
        clause_id="target",
        target_kind="one_creature",
        base_target_count=1,
        range_ft=0,
        source_slot_level=1,
        target_count_increment=1,
    )


def test_typed_spell_target_fanout_resolves_upcast_targets_with_source_receipt() -> None:
    receipt = resolve_typed_spell_targets(
        _spec(),
        slot_level=3,
        target_ids=["target-a", "target-b", "target-c"],
    )
    assert receipt.maximum_target_count == 3
    assert receipt.target_ids == ("target-a", "target-b", "target-c")
    assert receipt.source_record_id == "6f5b6f21ffa22e705a9bd6cb"
    assert receipt.as_dict()["schema"] == "spell.target.fanout.v1"


def test_typed_spell_target_fanout_is_idempotent_and_rejects_payload_drift() -> None:
    first = resolve_typed_spell_targets(_spec(), slot_level=2, target_ids=["target-a", "target-b"])
    replay = resolve_typed_spell_targets(
        _spec(),
        slot_level=2,
        target_ids=["target-a", "target-b"],
        prior_receipt=first,
    )
    assert replay.replayed is True
    assert replay.as_dict() == {**first.as_dict(), "replayed": True}
    with pytest.raises(ValueError, match="replay payload"):
        resolve_typed_spell_targets(
            _spec(), slot_level=2, target_ids=["target-a"], prior_receipt=first
        )


@pytest.mark.parametrize(
    ("slot_level", "target_ids", "message"),
    [
        (0, ["target-a"], "below source level"),
        (1, ["target-a", "target-b"], "exceeds maximum"),
        (3, ["target-a", "target-a"], "unique"),
        (3, [], "must not be empty"),
    ],
)
def test_typed_spell_target_fanout_fails_closed(
    slot_level: int, target_ids: list[str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        resolve_typed_spell_targets(_spec(), slot_level=slot_level, target_ids=target_ids)
