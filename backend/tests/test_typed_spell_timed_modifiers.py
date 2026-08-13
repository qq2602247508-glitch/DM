from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dnd_dm_assistant.domain.typed_spell_timed_modifiers import (
    TypedSpellTimedModifierSpec,
    apply_typed_spell_timed_modifier,
)

NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _spec(**overrides: object) -> TypedSpellTimedModifierSpec:
    values = {
        "content_id": "core-phb-2024:spell:longstrider",
        "source_record_id": "6f5b6f21ffa22e705a9bd6cb",
        "source_fingerprint": "a" * 64,
        "clause_id": "speed_modifier",
        "source_id": "spell:longstrider",
        "target_id": "combatant-a",
        "stat": "speed_ft",
        "operation": "add",
        "value": 10,
        "duration_unit": "hours",
        "duration_value": 1,
    }
    values.update(overrides)
    return TypedSpellTimedModifierSpec(**values)


def test_timed_spell_modifier_persists_source_bound_expiry_and_replaces_same_source() -> None:
    state, first = apply_typed_spell_timed_modifier(
        _spec(), state={"version": 4}, expected_version=4, now=NOW
    )
    assert state["version"] == 5
    assert state["timed_spell_modifiers"][0]["modifier"]["value"] == 10
    assert first.as_dict()["schema"] == "spell.timed_modifier.v1"
    assert first.expires_at == "2026-08-13T13:00:00+00:00"

    replaced, second = apply_typed_spell_timed_modifier(
        _spec(value=20),
        state=state,
        expected_version=5,
        now=NOW,
    )
    assert len(replaced["timed_spell_modifiers"]) == 1
    assert replaced["timed_spell_modifiers"][0]["modifier"]["value"] == 20
    assert second.state_version_after == 6


def test_timed_spell_modifier_replay_is_idempotent_and_rejects_drift() -> None:
    state, receipt = apply_typed_spell_timed_modifier(
        _spec(), state={"version": 0}, expected_version=0, now=NOW
    )
    replay_state, replay = apply_typed_spell_timed_modifier(
        _spec(),
        state=state,
        expected_version=1,
        now=NOW,
        prior_receipt=receipt,
    )
    assert replay.replayed is True
    assert replay_state == state
    with pytest.raises(ValueError, match="replay payload"):
        apply_typed_spell_timed_modifier(
            _spec(value=20),
            state=state,
            expected_version=1,
            now=NOW,
            prior_receipt=receipt,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"stat": "armor_class"}, "stat is unsupported"),
        ({"duration_unit": "rounds"}, "duration unit is unsupported"),
        ({"source_fingerprint": "not-a-sha"}, "source_fingerprint"),
        ({"stacking": "stack"}, "stacking"),
    ],
)
def test_timed_spell_modifier_fails_closed(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _spec(**overrides)


def test_timed_spell_modifier_rejects_stale_cas_and_malformed_state() -> None:
    with pytest.raises(ValueError, match="stale"):
        apply_typed_spell_timed_modifier(
            _spec(), state={"version": 2}, expected_version=1, now=NOW
        )
    with pytest.raises(ValueError, match="state is invalid"):
        apply_typed_spell_timed_modifier(
            _spec(), state={"version": 0, "timed_spell_modifiers": "bad"},
            expected_version=0, now=NOW
        )
