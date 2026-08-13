from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.entity_spatial import (
    ENTITY_SPATIAL_SCHEMA,
    EntitySpatialSpec,
    transition_entity_spatial,
)
from dnd_dm_assistant.domain.rules_kernel_protocol import KernelPosition

SOURCE = EntitySpatialSpec(
    entity_id="spectral-object-1",
    source_id="scribe-source",
    source_fingerprint="scribe-fingerprint",
)


def test_entity_spatial_moves_within_30_feet_and_expires_past_300() -> None:
    created = transition_entity_spatial(
        SOURCE,
        None,
        event="move",
        operation_id="move-1",
        expected_version=None,
        entity_position=KernelPosition(row=1, col=1),
        owner_position=KernelPosition(row=1, col=1),
        destination=KernelPosition(row=1, col=7),
        spatial_facts={
            "visible_to_owner": True,
            "destination_unoccupied": True,
            "path_clear_of_objects": True,
        },
    )
    assert created.state["schema"] == ENTITY_SPATIAL_SCHEMA
    assert created.state["version"] == 1

    expired = transition_entity_spatial(
        SOURCE,
        created.state,
        event="check_separation",
        operation_id="separation-1",
        expected_version=1,
        entity_position=KernelPosition(row=1, col=7),
        owner_position=KernelPosition(row=1, col=69),
    )
    assert expired.expired is True
    assert expired.state["status"] == "expired"


@pytest.mark.parametrize(
    ("facts", "message"),
    [
        ({}, "owner visibility"),
        ({"visible_to_owner": True}, "unoccupied destination"),
        ({"visible_to_owner": True, "destination_unoccupied": True}, "objects"),
    ],
)
def test_entity_spatial_movement_fails_closed_on_missing_spatial_facts(
    facts: dict[str, bool],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        transition_entity_spatial(
            SOURCE,
            None,
            event="move",
            operation_id="move-fail",
            expected_version=None,
            entity_position=KernelPosition(row=1, col=1),
            owner_position=KernelPosition(row=1, col=1),
            destination=KernelPosition(row=1, col=2),
            spatial_facts=facts,
        )


def test_entity_spatial_replay_and_cas_reject_drift_and_stale_versions() -> None:
    created = transition_entity_spatial(
        SOURCE,
        None,
        event="move",
        operation_id="move-1",
        expected_version=None,
        entity_position=KernelPosition(row=1, col=1),
        owner_position=KernelPosition(row=1, col=1),
        destination=KernelPosition(row=1, col=2),
        spatial_facts={
            "visible_to_owner": True,
            "destination_unoccupied": True,
            "path_clear_of_objects": True,
        },
    )
    replay = transition_entity_spatial(
        SOURCE,
        created.state,
        event="move",
        operation_id="move-1",
        expected_version=1,
        entity_position=KernelPosition(row=1, col=1),
        owner_position=KernelPosition(row=1, col=1),
        destination=KernelPosition(row=1, col=2),
        spatial_facts={
            "visible_to_owner": True,
            "destination_unoccupied": True,
            "path_clear_of_objects": True,
        },
    )
    assert replay.replayed is True
    with pytest.raises(ValueError, match="replay payload"):
        transition_entity_spatial(
            SOURCE,
            created.state,
            event="move",
            operation_id="move-1",
            expected_version=1,
            entity_position=KernelPosition(row=1, col=1),
            owner_position=KernelPosition(row=1, col=1),
            destination=KernelPosition(row=1, col=3),
            spatial_facts={
                "visible_to_owner": True,
                "destination_unoccupied": True,
                "path_clear_of_objects": True,
            },
        )
    with pytest.raises(ValueError, match="version conflict"):
        transition_entity_spatial(
            SOURCE,
            created.state,
            event="check_separation",
            operation_id="stale",
            expected_version=0,
            entity_position=KernelPosition(row=1, col=2),
            owner_position=KernelPosition(row=1, col=1),
        )
