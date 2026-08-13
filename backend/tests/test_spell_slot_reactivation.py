from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
)
from dnd_dm_assistant.application.feature_materializers import (
    default_materializer_registry,
)
from dnd_dm_assistant.domain.feature_capabilities import default_capability_catalog
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.domain.spell_slot_reactivation import (
    SpellSlotReactivationSpec,
    rollback_spell_slot_reactivation,
    transition_spell_slot_reactivation,
)

ROOT = Path(__file__).resolve().parents[2]
FEATURE = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    / "scribe-manifest-mind.json"
)
SOURCE_ID = "ff7049c6a4d0aad0dae4adf5"
SOURCE_FP = "dbbdb5b3ca9d86ece43c2f919d8483683f99068a478bccc401906057fccb920a"


def _spec() -> FeatureSpec:
    raw = json.loads(FEATURE.read_text(encoding="utf-8"))
    return FeatureSpec.from_dict(
        {key: item for key, item in raw.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE),
    )


def _contract() -> SpellSlotReactivationSpec:
    return SpellSlotReactivationSpec(
        entity_binding="entity_lifecycle",
        source_id=SOURCE_ID,
        source_fingerprint=SOURCE_FP,
    )


def _activated() -> dict[str, object]:
    return transition_spell_slot_reactivation(
        _contract(),
        None,
        event="activate",
        operation_id="activate-1",
    ).state


def test_source_bound_ir_materializes_partial_reactivation_contract() -> None:
    spec = _spec()
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    assert compiled.compile_status == "partial"
    assert any(
        "spell.slot.reactivation" in blocker
        for result in compiled.clause_results
        for blocker in result.blockers
    )

    clause = next(item for item in spec.clauses if item.clause_id == "spell-slot-reactivation")
    descriptor = default_capability_catalog().get("spell.slot.reactivation")
    assert descriptor is not None
    materialized = default_materializer_registry().materialize(
        spec=spec,
        clause=clause,
        operator="configure_spell_slot_reactivation",
        parameters=clause.effects[0].parameters,
        descriptor=descriptor,
        index=0,
    )
    assert materialized.section == "spell_slot_reactivations"
    assert materialized.entry["automation_status"] == "production_partial"
    assert materialized.entry["source_provenance"] == {
        "source_record_id": SOURCE_ID,
        "source_fingerprint": SOURCE_FP,
        "source_book": "塔莎的万事坩埚",
        "source_path": "塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html",
    }
    assert materialized.entry["reactivation_contract"]["spell_slot_amount"] == 1


def test_reactivation_requires_exactly_one_any_level_slot() -> None:
    state = _activated()
    state = transition_spell_slot_reactivation(
        _contract(), state, event="deactivate", operation_id="deactivate-1", expected_version=1
    ).state
    with pytest.raises(ValueError, match="consumes exactly one"):
        transition_spell_slot_reactivation(
            _contract(),
            state,
            event="reactivate",
            operation_id="reactivate-bad",
            expected_version=2,
            payment={
                "kind": "spell_slot_any_level",
                "resource_key": "spell_slots_3",
                "slot_level": 3,
                "amount": 2,
            },
        )
    result = transition_spell_slot_reactivation(
        _contract(),
        state,
        event="reactivate",
        operation_id="reactivate-1",
        expected_version=2,
        payment={
            "kind": "spell_slot_any_level",
            "resource_key": "spell_slots_3",
            "slot_level": 3,
            "amount": 1,
        },
    )
    assert result.state["status"] == "active"
    assert result.payment == {
        "kind": "spell_slot_any_level",
        "resource_key": "spell_slots_3",
        "slot_level": 3,
        "amount": 1,
    }


def test_long_rest_reactivates_once_and_duplicate_activation_is_rejected() -> None:
    state = _activated()
    state = transition_spell_slot_reactivation(
        _contract(), state, event="deactivate", operation_id="deactivate-1", expected_version=1
    ).state
    state = transition_spell_slot_reactivation(
        _contract(), state, event="long_rest", operation_id="rest-1", expected_version=2
    ).state
    assert state["reactivation_available"] is True
    state = transition_spell_slot_reactivation(
        _contract(), state, event="activate", operation_id="activate-2", expected_version=3
    ).state
    with pytest.raises(ValueError, match="activation is unavailable"):
        transition_spell_slot_reactivation(
            _contract(), state, event="activate", operation_id="activate-3", expected_version=4
        )


def test_replay_payload_drift_stale_cas_and_rollback_fail_closed() -> None:
    state = _activated()
    replay = transition_spell_slot_reactivation(
        _contract(), state, event="activate", operation_id="activate-1", expected_version=1
    )
    assert replay.replayed is True
    with pytest.raises(ValueError, match="replay payload"):
        transition_spell_slot_reactivation(
            _contract(),
            state,
            event="activate",
            operation_id="activate-1",
            expected_version=1,
            metadata={"drift": True},
        )
    with pytest.raises(ValueError, match="version conflict"):
        transition_spell_slot_reactivation(
            _contract(), state, event="deactivate", operation_id="stale", expected_version=99
        )
    prior = dict(state)
    current = transition_spell_slot_reactivation(
        _contract(), state, event="deactivate", operation_id="deactivate-1", expected_version=1
    ).state
    assert rollback_spell_slot_reactivation(
        _contract(), current, prior, operation_id="deactivate-1", expected_version=2
    ) == prior
    with pytest.raises(ValueError, match="rollback CAS"):
        rollback_spell_slot_reactivation(
            _contract(), current, prior, operation_id="deactivate-1", expected_version=1
        )
