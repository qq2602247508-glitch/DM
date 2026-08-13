from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.entity_spatial import EntitySpatialSpec, transition_entity_spatial
from dnd_dm_assistant.domain.rules_kernel_protocol import KernelPosition


def test_entity_spatial_preview_confirm_replay_consumes_bonus_action_contract() -> None:
    spec = EntitySpatialSpec("spectral", "scribe-source", "scribe-fingerprint")
    facts = {
        "visible_to_owner": True,
        "destination_unoccupied": True,
        "path_clear_of_objects": True,
        "action_economy": "bonus_action",
    }
    preview = transition_entity_spatial(
        spec,
        None,
        event="move",
        operation_id="spatial-preview-confirm",
        expected_version=None,
        entity_position=KernelPosition(row=2, col=2),
        owner_position=KernelPosition(row=2, col=2),
        destination=KernelPosition(row=2, col=8),
        spatial_facts=facts,
    )
    confirm = transition_entity_spatial(
        spec,
        preview.state,
        event="move",
        operation_id="spatial-replay",
        expected_version=1,
        entity_position=KernelPosition(row=2, col=8),
        owner_position=KernelPosition(row=2, col=2),
        destination=KernelPosition(row=2, col=8),
        spatial_facts=facts,
    )
    replay = transition_entity_spatial(
        spec,
        confirm.state,
        event="move",
        operation_id="spatial-replay",
        expected_version=2,
        entity_position=KernelPosition(row=2, col=8),
        owner_position=KernelPosition(row=2, col=2),
        destination=KernelPosition(row=2, col=8),
        spatial_facts=facts,
    )
    assert preview.state["version"] == 1
    assert confirm.state["version"] == 2
    assert replay.replayed is True


def test_entity_spatial_rejects_stale_and_expires_over_300_feet() -> None:
    spec = EntitySpatialSpec("spectral", "scribe-source", "scribe-fingerprint")
    facts = {
        "visible_to_owner": True,
        "destination_unoccupied": True,
        "path_clear_of_objects": True,
        "action_economy": "bonus_action",
    }
    created = transition_entity_spatial(
        spec,
        None,
        event="move",
        operation_id="spatial-create",
        expected_version=None,
        entity_position=KernelPosition(row=1, col=1),
        owner_position=KernelPosition(row=1, col=1),
        destination=KernelPosition(row=1, col=2),
        spatial_facts=facts,
    )
    with pytest.raises(ValueError, match="version conflict"):
        transition_entity_spatial(
            spec,
            created.state,
            event="check_separation",
            operation_id="stale",
            expected_version=0,
            entity_position=KernelPosition(row=1, col=2),
            owner_position=KernelPosition(row=1, col=1),
        )
    expired = transition_entity_spatial(
        spec,
        created.state,
        event="check_separation",
        operation_id="distance-expired",
        expected_version=1,
        entity_position=KernelPosition(row=1, col=2),
        owner_position=KernelPosition(row=1, col=63),
    )
    assert expired.expired is True
    assert expired.state["termination_reason"] == "distance_expired"
