from __future__ import annotations

import pytest

from dnd_dm_assistant.domain.typed_spell_communication_routes import (
    COMMUNICATION_ROUTE_SCHEMA,
    TypedSpellCommunicationRouteSpec,
    apply_typed_spell_communication_route,
)


def _spec(**overrides: object) -> TypedSpellCommunicationRouteSpec:
    values = {
        "content_id": "core-phb-2024:spell:message",
        "source_record_id": "dd9cb25c63b7e13194c7d01c",
        "source_fingerprint": "a" * 64,
        "clause_id": "communication_route",
        "sender_id": "caster",
        "target_id": "listener",
        "range_ft": 120,
    }
    values.update(overrides)
    return TypedSpellCommunicationRouteSpec(**values)


def _apply(**overrides: object):
    values = {
        "state": {"version": 2},
        "expected_version": 2,
        "distance_ft": 60,
        "visible": True,
        "familiar": False,
        "barrier_present": False,
        "message_fingerprint": "b" * 64,
    }
    values.update(overrides)
    return apply_typed_spell_communication_route(_spec(), **values)


def test_route_persists_target_only_delivery_and_private_reply() -> None:
    state, receipt = _apply()
    assert state["version"] == 3
    assert receipt.schema == COMMUNICATION_ROUTE_SCHEMA
    assert receipt.delivered_to == "listener"
    assert receipt.private_reply_to == "caster"
    assert state["communication_routes"][0]["message_fingerprint"] == "b" * 64


def test_route_allows_familiar_target_through_thin_barrier() -> None:
    state, receipt = _apply(
        visible=False,
        familiar=True,
        barrier_present=True,
        barrier_thickness_ft=1,
    )
    assert receipt.delivered_to == "listener"
    assert state["communication_routes"][0]["private_reply"] is True


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"visible": False, "familiar": False}, "visibility or familiarity"),
        ({"distance_ft": 121}, "out of range"),
        (
            {
                "visible": False,
                "familiar": True,
                "barrier_present": True,
                "barrier_thickness_ft": 2,
            },
            "too thick",
        ),
        ({"barrier_present": True, "barrier_thickness_ft": 1}, "requires familiarity"),
        ({"sender_in_magical_silence": True}, "magical silence"),
    ],
)
def test_route_gates_fail_closed(overrides: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _apply(**overrides)


def test_route_replay_is_idempotent_and_rejects_message_drift() -> None:
    state, receipt = _apply()
    replay_state, replay = _apply(
        state=state,
        expected_version=3,
        prior_receipt=receipt,
    )
    assert replay_state == state
    assert replay.replayed is True
    with pytest.raises(ValueError, match="replay payload"):
        _apply(
            state=state,
            expected_version=3,
            prior_receipt=receipt,
            message_fingerprint="c" * 64,
        )


def test_route_rejects_stale_cas_and_malformed_state() -> None:
    with pytest.raises(ValueError, match="stale"):
        _apply(expected_version=1)
    with pytest.raises(ValueError, match="state is invalid"):
        _apply(state={"version": 2, "communication_routes": "bad"})
