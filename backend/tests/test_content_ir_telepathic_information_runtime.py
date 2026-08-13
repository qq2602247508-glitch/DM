from __future__ import annotations

from dnd_dm_assistant.domain.entity_lifecycle import (
    EntityLifecycleSpec,
    transition_entity_lifecycle,
)
from dnd_dm_assistant.domain.rules_kernel_protocol import KernelPosition
from dnd_dm_assistant.domain.spatial_authority import DeterministicTestSpatialAuthority
from dnd_dm_assistant.domain.telepathic_information import (
    TELEPATHIC_INFORMATION_SCHEMA,
    share_authorized_sensory_information,
)


def test_telepathic_preview_confirm_replay_is_owner_only_no_action() -> None:
    spatial = DeterministicTestSpatialAuthority()
    spatial.add_entity("spectral", KernelPosition(row=2, col=2))
    spatial.add_entity("target", KernelPosition(row=2, col=4))
    lifecycle = transition_entity_lifecycle(
        EntityLifecycleSpec("spectral", "scribe-source", "scribe-fingerprint"),
        None,
        event="create",
        operation_id="telepathic-create",
        expected_version=None,
        metadata={"owner_character_id": "owner"},
    )
    lifecycle = transition_entity_lifecycle(
        EntityLifecycleSpec("spectral", "scribe-source", "scribe-fingerprint"),
        lifecycle.state,
        event="enter",
        operation_id="telepathic-enter",
        expected_version=1,
        metadata={"owner_character_id": "owner"},
    )
    senses = {
        "entity_binding": "entity_lifecycle",
        "senses": {"hearing": True, "darkvision_ft": 60},
        "source_provenance": {
            "source_record_id": "scribe-source",
            "source_fingerprint": "scribe-fingerprint",
        },
    }
    channel = {
        "schema": TELEPATHIC_INFORMATION_SCHEMA,
        "action_economy": "none",
        "visibility": "owner",
        "language_required": False,
        "response_required": False,
        "range_ft": 300,
    }
    lifecycle_record = {
        "state": lifecycle.state,
        "entity_id": "spectral",
        "source_provenance": senses["source_provenance"],
    }
    lifecycle_record["state"] = {
        **lifecycle_record["state"],
        "status": "entered",
        "metadata": {"owner_character_id": "owner"},
    }
    preview = share_authorized_sensory_information(
        channel,
        senses,
        lifecycle_record,
        owner_id="owner",
        target_id="target",
        spatial=spatial,
    )
    confirm = preview.as_dict()
    replay = share_authorized_sensory_information(
        channel,
        senses,
        lifecycle_record,
        owner_id="owner",
        target_id="target",
        spatial=spatial,
    ).as_dict()
    assert confirm["schema"] == TELEPATHIC_INFORMATION_SCHEMA
    assert confirm["action_economy"] == "none"
    assert confirm["language_required"] is False
    assert confirm["response_required"] is False
    assert replay == confirm


def test_telepathic_information_fails_closed_for_inactive_or_wrong_owner() -> None:
    spatial = DeterministicTestSpatialAuthority()
    spatial.add_entity("spectral", KernelPosition(row=2, col=2))
    spatial.add_entity("target", KernelPosition(row=2, col=4))
    lifecycle = {
        "entity_id": "spectral",
        "state": {"status": "expired"},
        "source_provenance": {
            "source_record_id": "scribe-source",
            "source_fingerprint": "scribe-fingerprint",
        },
    }
    senses = {
        "entity_binding": "entity_lifecycle",
        "senses": {"hearing": True},
        "source_provenance": lifecycle["source_provenance"],
    }
    channel = {
        "action_economy": "none",
        "visibility": "owner",
        "language_required": False,
        "response_required": False,
    }
    import pytest

    with pytest.raises(ValueError, match="active entity lifecycle"):
        share_authorized_sensory_information(
            channel, senses, lifecycle, owner_id="owner", target_id="target", spatial=spatial
        )
