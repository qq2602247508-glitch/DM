from __future__ import annotations

import pytest

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.feature_materializers import MaterializerError
from dnd_dm_assistant.domain.entity_lifecycle import (
    ENTITY_LIFECYCLE_SCHEMA,
    ENTITY_TERMINATION_REASONS,
    EntityLifecycleSpec,
    transition_entity_lifecycle,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.domain.remote_spell_origin import (
    RemoteSpellOriginContract,
    resolve_remote_spell_origin,
)
from dnd_dm_assistant.domain.rules_kernel_protocol import KernelPosition
from dnd_dm_assistant.domain.spatial_authority import DeterministicTestSpatialAuthority


def _spec() -> EntityLifecycleSpec:
    return EntityLifecycleSpec(
        entity_type="extradimensional_vessel",
        source_id="content.tashas-cauldron.round2.feature.genie-bottled-respite",
        source_fingerprint="source-fingerprint-001",
        max_entries=1,
    )


def test_entity_lifecycle_supports_create_enter_exit_expire_with_provenance() -> None:
    spec = _spec()
    created = transition_entity_lifecycle(
        spec, None, event="create", operation_id="entity-create-001", expected_version=0
    )
    entered = transition_entity_lifecycle(
        spec,
        created.state,
        event="enter",
        operation_id="entity-enter-001",
        expected_version=1,
        metadata={"owner_id": "character-1"},
    )
    exited = transition_entity_lifecycle(
        spec, entered.state, event="exit", operation_id="entity-exit-001", expected_version=2
    )
    expired = transition_entity_lifecycle(
        spec, exited.state, event="expire", operation_id="entity-expire-001", expected_version=3
    )

    assert expired.state["schema"] == ENTITY_LIFECYCLE_SCHEMA
    assert expired.state["status"] == "expired"
    assert expired.state["version"] == 4
    assert expired.state["source_id"] == spec.source_id
    assert expired.state["source_fingerprint"] == spec.source_fingerprint
    assert expired.state["active_entries"] == 0
    assert expired.state["metadata"] == {"owner_id": "character-1"}


def test_entity_lifecycle_fails_closed_for_invalid_state_and_terminal_reentry() -> None:
    spec = _spec()
    created = transition_entity_lifecycle(
        spec, None, event="create", operation_id="create-001", expected_version=0
    )
    with pytest.raises(ValueError, match="cannot exit from status created"):
        transition_entity_lifecycle(
            spec, created.state, event="exit", operation_id="exit-001", expected_version=1
        )
    expired = transition_entity_lifecycle(
        spec, created.state, event="expire", operation_id="expire-001", expected_version=1
    )
    with pytest.raises(ValueError, match="cannot enter from status expired"):
        transition_entity_lifecycle(
            spec, expired.state, event="enter", operation_id="enter-001", expected_version=2
        )
    with pytest.raises(ValueError, match="source_id does not match"):
        transition_entity_lifecycle(
            spec,
            {**created.state, "source_id": "untrusted-source"},
            event="expire",
            operation_id="expire-002",
            expected_version=1,
        )


def test_entity_lifecycle_replay_is_idempotent_but_payload_or_version_drift_is_rejected() -> None:
    spec = _spec()
    created = transition_entity_lifecycle(
        spec, None, event="create", operation_id="create-001", expected_version=0
    )
    replay = transition_entity_lifecycle(
        spec, created.state, event="create", operation_id="create-001", expected_version=1
    )
    assert replay.replayed is True
    assert replay.state == created.state

    with pytest.raises(ValueError, match="replay payload"):
        transition_entity_lifecycle(
            spec,
            created.state,
            event="create",
            operation_id="create-001",
            expected_version=1,
            metadata={"different": True},
        )


@pytest.mark.parametrize(
    "reason",
    [
        "dispel_magic",
        "source_object_destroyed",
        "owner_died",
        "owner_dismissed",
        "distance_expired",
    ],
)
def test_entity_lifecycle_termination_reasons_are_typed_and_terminal(reason: str) -> None:
    assert reason in ENTITY_TERMINATION_REASONS
    spec = _spec()
    created = transition_entity_lifecycle(
        spec, None, event="create", operation_id=f"create-{reason}", expected_version=0
    )
    entered = transition_entity_lifecycle(
        spec,
        created.state,
        event="enter",
        operation_id=f"enter-{reason}",
        expected_version=1,
        metadata={"owner_id": "character-1"},
    )
    terminated = transition_entity_lifecycle(
        spec,
        entered.state,
        event="terminate",
        operation_id=f"terminate-{reason}",
        expected_version=2,
        metadata={"termination_reason": reason},
    )
    assert terminated.state["status"] == "terminated"
    assert terminated.state["termination_reason"] == reason
    assert terminated.state["active_entries"] == 0
    replay = transition_entity_lifecycle(
        spec,
        terminated.state,
        event="terminate",
        operation_id=f"terminate-{reason}",
        expected_version=3,
        metadata={"termination_reason": reason},
    )
    assert replay.replayed is True
    with pytest.raises(ValueError, match="cannot enter from status terminated"):
        transition_entity_lifecycle(
            spec,
            terminated.state,
            event="enter",
            operation_id=f"reactivate-{reason}",
            expected_version=3,
        )
    with pytest.raises(ValueError, match="version conflict"):
        transition_entity_lifecycle(
            spec, created.state, event="enter", operation_id="enter-001", expected_version=0
        )


def test_entity_lifecycle_enforces_entry_capacity_and_empty_expiry() -> None:
    spec = _spec()
    created = transition_entity_lifecycle(
        spec, None, event="create", operation_id="create-001", expected_version=0
    )
    entered = transition_entity_lifecycle(
        spec, created.state, event="enter", operation_id="enter-001", expected_version=1
    )
    with pytest.raises(ValueError, match="max_entries exceeded"):
        transition_entity_lifecycle(
            spec, entered.state, event="enter", operation_id="enter-002", expected_version=2
        )
    with pytest.raises(ValueError, match="active entries"):
        transition_entity_lifecycle(
            spec, entered.state, event="expire", operation_id="expire-001", expected_version=2
        )
    exited = transition_entity_lifecycle(
        spec, entered.state, event="exit", operation_id="exit-001", expected_version=2
    )
    with pytest.raises(ValueError, match="cannot exit from status exited"):
        transition_entity_lifecycle(
            spec, exited.state, event="exit", operation_id="exit-002", expected_version=3
        )


def _feature_spec(*, source_fingerprint: str | None) -> FeatureSpec:
    return FeatureSpec.from_dict(
        {
            "schema_version": "feature-ir-1",
            "feature_id": "fixture:entity-lifecycle",
            "namespace": "fixture",
            "pack_id": "fixture",
            "pack_version": "1.0.0",
            "ruleset_version": "2014",
            "source_record_id": "fixture-source-1",
            "source_name": "Fixture Entity",
            "source_trust": "authored_ir",
            "localized_names": {},
            "class_name": None,
            "subclass_name": None,
            "level": 1,
            "source_completeness": "complete",
            "source_fingerprint": source_fingerprint,
            "clauses": [
                {
                    "clause_id": "lifecycle",
                    "trigger": "advancement_confirmed",
                    "activation": "automatic",
                    "action_economy": "none",
                    "targeting": {"kind": "self", "parameters": {}},
                    "effects": [
                        {
                            "operator": "configure_entity_lifecycle",
                            "parameters": {
                                "entity_type": "spectral_object",
                                "source_binding": "feature_source",
                                "max_entries": 1,
                            },
                        }
                    ],
                }
            ],
            "dependencies": [],
            "compatibility": {},
        }
    )


def test_entity_lifecycle_is_compiler_materializer_contract_with_provenance() -> None:
    spec = _feature_spec(source_fingerprint="fingerprint-001")
    result = FeatureCompiler().compile(spec)
    assert result.compile_status == "full"
    runtime = materialize_runtime_definition(spec, result)
    block = runtime["entity_lifecycles"][0]
    assert block["operator"] == "configure_entity_lifecycle"
    assert block["source_provenance"] == {
        "source_record_id": "fixture-source-1",
        "source_fingerprint": "fingerprint-001",
        "source_book": None,
        "source_path": None,
    }
    assert block["cas"]["expected_version_required"] is True
    assert block["idempotency"]["operation_id_field"] == "operation_id"


def test_entity_lifecycle_materializer_fails_closed_without_source_fingerprint() -> None:
    spec = _feature_spec(source_fingerprint=None)
    result = FeatureCompiler().compile(spec)
    assert result.compile_status == "full"
    with pytest.raises(MaterializerError, match="source fingerprint"):
        materialize_runtime_definition(spec, result)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"entity_type": "", "source_id": "source", "source_fingerprint": "fingerprint"},
            "entity_type",
        ),
        (
            {"entity_type": "object", "source_id": "", "source_fingerprint": "fingerprint"},
            "source_id",
        ),
        (
            {"entity_type": "object", "source_id": "source", "source_fingerprint": ""},
            "source_fingerprint",
        ),
        (
            {
                "entity_type": "object",
                "source_id": "source",
                "source_fingerprint": "fingerprint",
                "max_entries": 0,
            },
            "max_entries",
        ),
    ],
)
def test_entity_lifecycle_spec_rejects_missing_or_invalid_contract_fields(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        EntityLifecycleSpec(**kwargs)


def _remote_spec(*, source_fingerprint: str | None) -> FeatureSpec:
    return FeatureSpec.from_dict(
        {
            "schema_version": "feature-ir-1",
            "feature_id": "fixture:remote-origin",
            "namespace": "fixture",
            "pack_id": "fixture",
            "pack_version": "1.0.0",
            "ruleset_version": "2014",
            "source_record_id": "fixture-source-remote-1",
            "source_name": "Fixture Remote Origin",
            "source_trust": "authored_ir",
            "localized_names": {},
            "class_name": None,
            "subclass_name": None,
            "level": 1,
            "source_completeness": "complete",
            "source_fingerprint": source_fingerprint,
            "clauses": [
                {
                    "clause_id": "remote-origin",
                    "trigger": "spell_cast",
                    "activation": "automatic",
                    "action_economy": "none",
                    "targeting": {
                        "kind": "one_creature",
                        "parameters": {},
                    },
                    "effects": [
                        {
                            "operator": "configure_remote_spell_origin",
                            "parameters": {
                                "origin_kind": "entity",
                                "origin_binding": "entity_lifecycle",
                                "target_kind": "one_creature",
                                "max_range_ft": 30,
                                "require_line_of_effect": True,
                            },
                        }
                    ],
                }
            ],
            "dependencies": [],
            "compatibility": {},
        }
    )


def test_remote_spell_origin_resolves_authorized_origin_and_target_geometry() -> None:
    spatial = DeterministicTestSpatialAuthority()
    spatial.add_entity("origin-1", KernelPosition(row=1, col=1))
    spatial.add_entity("target-1", KernelPosition(row=1, col=5))
    contract = RemoteSpellOriginContract(
        source_record_id="source-1",
        source_fingerprint="fingerprint-1",
        actor_id="actor-1",
        origin_id="origin-1",
        max_range_ft=30,
    )

    resolved = resolve_remote_spell_origin(
        contract,
        actor_id="actor-1",
        authorized_origin_ids=("origin-1",),
        target_ids=("target-1",),
        spatial=spatial,
    )

    assert resolved.target_ids == ("target-1",)
    assert resolved.distances_ft == {"target-1": 20}
    assert resolved.line_of_effect == {"target-1": True}


@pytest.mark.parametrize(
    ("operation", "match"),
    [
        (
            {
                "actor_id": "other",
                "authorized_origin_ids": ("origin-1",),
                "target_ids": ("target-1",),
            },
            "actor authorization",
        ),
        (
            {
                "actor_id": "actor-1",
                "authorized_origin_ids": ("origin-2",),
                "target_ids": ("target-1",),
            },
            "source authorization",
        ),
        (
            {
                "actor_id": "actor-1",
                "authorized_origin_ids": ("origin-1",),
                "target_ids": (),
            },
            "at least one target",
        ),
        (
            {
                "actor_id": "actor-1",
                "authorized_origin_ids": ("origin-1",),
                "target_ids": ("target-1", "target-2"),
            },
            "single-target",
        ),
    ],
)
def test_remote_spell_origin_fails_closed_for_authorization_or_target_shape(
    operation: dict[str, object], match: str
) -> None:
    spatial = DeterministicTestSpatialAuthority()
    spatial.add_entity("origin-1", KernelPosition(row=1, col=1))
    spatial.add_entity("target-1", KernelPosition(row=1, col=2))
    spatial.add_entity("target-2", KernelPosition(row=1, col=3))
    contract = RemoteSpellOriginContract(
        source_record_id="source-1",
        source_fingerprint="fingerprint-1",
        actor_id="actor-1",
        origin_id="origin-1",
    )

    with pytest.raises(ValueError, match=match):
        resolve_remote_spell_origin(contract, spatial=spatial, **operation)


def test_remote_spell_origin_fails_closed_for_range_and_line_of_effect() -> None:
    spatial = DeterministicTestSpatialAuthority()
    spatial.add_entity("origin-1", KernelPosition(row=1, col=1))
    spatial.add_entity("target-1", KernelPosition(row=1, col=10))
    range_contract = RemoteSpellOriginContract(
        source_record_id="source-1",
        source_fingerprint="fingerprint-1",
        actor_id="actor-1",
        origin_id="origin-1",
        max_range_ft=30,
    )
    with pytest.raises(ValueError, match="outside range"):
        resolve_remote_spell_origin(
            range_contract,
            actor_id="actor-1",
            authorized_origin_ids=("origin-1",),
            target_ids=("target-1",),
            spatial=spatial,
        )

    blocked = DeterministicTestSpatialAuthority(blocked={(1, 3)})
    blocked.add_entity("origin-1", KernelPosition(row=1, col=1))
    blocked.add_entity("target-1", KernelPosition(row=1, col=5))
    line_contract = RemoteSpellOriginContract(
        source_record_id="source-1",
        source_fingerprint="fingerprint-1",
        actor_id="actor-1",
        origin_id="origin-1",
        max_range_ft=30,
    )
    with pytest.raises(ValueError, match="line of effect"):
        resolve_remote_spell_origin(
            line_contract,
            actor_id="actor-1",
            authorized_origin_ids=("origin-1",),
            target_ids=("target-1",),
            spatial=blocked,
        )


def test_remote_spell_origin_is_compiler_materializer_contract_with_provenance() -> None:
    spec = _remote_spec(source_fingerprint="fingerprint-remote-1")
    result = FeatureCompiler().compile(spec)
    assert result.compile_status == "full"
    runtime = materialize_runtime_definition(spec, result)
    block = runtime["spell_origins"][0]
    assert block["origin_contract"] == {
        "schema": "remote.spell.origin.v1",
        "origin_kind": "entity",
        "origin_binding": "entity_lifecycle",
        "target_kind": "one_creature",
        "max_range_ft": 30,
        "require_line_of_effect": True,
    }
    assert block["source_provenance"]["source_fingerprint"] == "fingerprint-remote-1"
    assert block["authorization"]["actor_id_required"] is True
    assert block["target_resolution"]["spatial_authority"] == "required"


def test_remote_spell_origin_materializer_requires_source_fingerprint() -> None:
    spec = _remote_spec(source_fingerprint=None)
    result = FeatureCompiler().compile(spec)
    assert result.compile_status == "full"
    with pytest.raises(MaterializerError, match="source fingerprint"):
        materialize_runtime_definition(spec, result)
