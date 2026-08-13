import json
from pathlib import Path

from sqlalchemy import inspect

from dnd_dm_assistant.application.feature_compiler import FeatureCompiler
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.domain.vessel_space import (
    VesselSpaceSpec,
    transition_vessel_space,
)
from dnd_dm_assistant.infrastructure.database.models import VesselSpace


def test_vessel_space_mapper_uses_vessel_id_as_the_sole_primary_key() -> None:
    mapper = inspect(VesselSpace)
    assert [column.key for column in mapper.primary_key] == ["vessel_id"]
    assert VesselSpace.__table__.c.id.primary_key is False


def _spec() -> VesselSpaceSpec:
    return VesselSpaceSpec(
        vessel_id="vessel-1",
        source_id="98620543cf94e974361c6567",
        source_fingerprint="e81b718b2ee8728e75cf77c2f00c33312a283a9e12d3654d9bb377a64ec745c7",
        max_occupants=5,
        duration_hours=8,
    )


def test_vessel_space_source_bound_lifecycle_replay_and_long_rest() -> None:
    spec = _spec()
    created = transition_vessel_space(
        spec,
        None,
        event="create",
        operation_id="create",
        expected_version=None,
        appearance="urn",
        owner_character_id="character-1",
    )
    entered = transition_vessel_space(
        spec,
        created.state,
        event="enter",
        operation_id="enter",
        expected_version=1,
        subject_ids=("owner", "ally"),
        facts={
            "vessel_touched": True,
            "source_owner": True,
            "entry_action_available": True,
            "all_creatures_voluntary": True,
            "all_creatures_visible": True,
        },
        owner_character_id="character-1",
    )
    replay = transition_vessel_space(
        spec,
        entered.state,
        event="enter",
        operation_id="enter",
        expected_version=2,
        subject_ids=("owner", "ally"),
        facts={
            "vessel_touched": True,
            "source_owner": True,
            "entry_action_available": True,
            "all_creatures_voluntary": True,
            "all_creatures_visible": True,
        },
        owner_character_id="character-1",
    )
    assert replay.replayed
    assert replay.state == entered.state
    try:
        transition_vessel_space(
            spec,
            entered.state,
            event="enter",
            operation_id="nested",
            expected_version=2,
            subject_ids=("owner",),
            facts={
                "vessel_touched": True,
                "source_owner": True,
                "entry_action_available": True,
                "all_creatures_voluntary": True,
                "all_creatures_visible": True,
            },
            owner_character_id="character-1",
        )
    except ValueError as exc:
        assert "long rest" in str(exc)
    else:
        raise AssertionError("entry must be once per long rest")
    reset = transition_vessel_space(
        spec,
        entered.state,
        event="long_rest",
        operation_id="rest",
        expected_version=2,
        owner_character_id="character-1",
    )
    assert reset.state["entry_used_since_long_rest"] is False


def test_vessel_space_fail_closed_facts_capacity_cas_and_destruction_payload() -> None:
    spec = _spec()
    created = transition_vessel_space(
        spec,
        None,
        event="create",
        operation_id="create",
        expected_version=None,
        appearance="urn",
        owner_character_id="character-1",
    )
    missing = {
        "vessel_touched": True,
        "source_owner": True,
        "entry_action_available": True,
        "all_creatures_visible": True,
    }
    try:
        transition_vessel_space(
            spec,
            created.state,
            event="enter",
            operation_id="missing-voluntary",
            expected_version=1,
            subject_ids=("owner",),
            facts=missing,
            owner_character_id="character-1",
        )
    except ValueError as exc:
        assert "voluntary" in str(exc)
    else:
        raise AssertionError("voluntary status must be authoritative")
    entered = transition_vessel_space(
        spec,
        created.state,
        event="enter",
        operation_id="enter",
        expected_version=1,
        subject_ids=("owner", "a", "b", "c", "d"),
        facts={**missing, "all_creatures_voluntary": True},
        owner_character_id="character-1",
    )
    try:
        transition_vessel_space(
            spec,
            entered.state,
            event="exit",
            operation_id="stale",
            expected_version=1,
            facts={"destination_nearest_unoccupied": True},
            owner_character_id="character-1",
        )
    except ValueError as exc:
        assert "version conflict" in str(exc)
    else:
        raise AssertionError("stale CAS must fail")
    destroyed = transition_vessel_space(
        spec,
        entered.state,
        event="destroy",
        operation_id="destroy",
        expected_version=2,
        facts={
            "nearest_unoccupied_for_occupants": True,
            "nearest_unoccupied_for_items": True,
        },
        owner_character_id="character-1",
    )
    assert destroyed.state["status"] == "destroyed"
    assert destroyed.ejected_occupants == ("owner", "a", "b", "c", "d")


def test_genie_feature_compiler_closes_against_real_vessel_consumer() -> None:
    path = (
        Path(__file__).resolve().parents[2]
        / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
        / "genie-bottled-respite.json"
    )
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw.pop("kind", None)
    result = FeatureCompiler().compile(FeatureSpec.from_dict(raw, path=str(path)))
    assert result.compile_status == "full"
    assert "source is incomplete" not in result.blockers
    assert result.blockers == ()
    assert result.clause_results[0].status == "full"
    assert result.clause_results[0].capability_ids == ("vessel.space",)
