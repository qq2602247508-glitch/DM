"""Source-bound private communication route seam."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

COMMUNICATION_ROUTE_SCHEMA = "spell.communication.route.v1"


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TypedSpellCommunicationRouteSpec:
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    sender_id: str
    target_id: str
    range_ft: int
    requires_visibility_or_familiarity: bool = True
    barrier_requires_familiarity: bool = True
    max_barrier_thickness_ft: int = 1
    target_only: bool = True
    private_reply: bool = True
    magical_silence_blocks: bool = True

    def __post_init__(self) -> None:
        for field in ("content_id", "source_record_id", "clause_id", "sender_id", "target_id"):
            if not str(getattr(self, field)).strip():
                raise ValueError(f"typed spell communication route {field} is required")
        fingerprint = self.source_fingerprint.strip()
        if len(fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in fingerprint.lower()
        ):
            raise ValueError("typed spell communication route source_fingerprint must be sha256")
        if self.sender_id == self.target_id:
            raise ValueError("typed spell communication route sender and target must differ")
        if (
            isinstance(self.range_ft, bool)
            or not isinstance(self.range_ft, int)
            or self.range_ft < 0
        ):
            raise ValueError("typed spell communication route range must be non-negative")
        if (
            isinstance(self.max_barrier_thickness_ft, bool)
            or not isinstance(self.max_barrier_thickness_ft, int)
            or self.max_barrier_thickness_ft < 0
        ):
            raise ValueError(
                "typed spell communication route barrier thickness must be non-negative"
            )
        if not self.target_only:
            raise ValueError("typed spell communication route must be target-only")
        if not self.private_reply:
            raise ValueError("typed spell communication route must allow private reply")

    def as_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "sender_id": self.sender_id,
            "target_id": self.target_id,
            "range_ft": self.range_ft,
            "requires_visibility_or_familiarity": self.requires_visibility_or_familiarity,
            "barrier_requires_familiarity": self.barrier_requires_familiarity,
            "max_barrier_thickness_ft": self.max_barrier_thickness_ft,
            "target_only": self.target_only,
            "private_reply": self.private_reply,
            "magical_silence_blocks": self.magical_silence_blocks,
        }


@dataclass(frozen=True, slots=True)
class TypedSpellCommunicationRouteReceipt:
    schema: str
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    sender_id: str
    target_id: str
    delivered_to: str
    private_reply_to: str
    request_fingerprint: str
    state_version_before: int
    state_version_after: int
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "sender_id": self.sender_id,
            "target_id": self.target_id,
            "delivered_to": self.delivered_to,
            "private_reply_to": self.private_reply_to,
            "request_fingerprint": self.request_fingerprint,
            "state_version_before": self.state_version_before,
            "state_version_after": self.state_version_after,
            "replayed": self.replayed,
        }


def apply_typed_spell_communication_route(
    spec: TypedSpellCommunicationRouteSpec,
    *,
    state: dict[str, Any],
    expected_version: int,
    distance_ft: int,
    visible: bool,
    familiar: bool,
    barrier_present: bool,
    barrier_thickness_ft: int = 0,
    sender_in_magical_silence: bool = False,
    target_in_magical_silence: bool = False,
    message_fingerprint: str,
    prior_receipt: TypedSpellCommunicationRouteReceipt | None = None,
) -> tuple[dict[str, Any], TypedSpellCommunicationRouteReceipt]:
    current_version = state.get("version", 0)
    if isinstance(current_version, bool) or not isinstance(current_version, int):
        raise ValueError("typed spell communication route state version is invalid")
    if current_version != expected_version:
        raise ValueError("typed spell communication route state version is stale")
    if isinstance(distance_ft, bool) or not isinstance(distance_ft, int) or distance_ft < 0:
        raise ValueError("typed spell communication route distance must be non-negative")
    if distance_ft > spec.range_ft:
        raise ValueError("typed spell communication route is out of range")
    if spec.requires_visibility_or_familiarity and not (visible or familiar):
        raise ValueError("typed spell communication route requires visibility or familiarity")
    if barrier_present:
        if (
            isinstance(barrier_thickness_ft, bool)
            or not isinstance(barrier_thickness_ft, int)
            or barrier_thickness_ft < 1
        ):
            raise ValueError("typed spell communication route barrier thickness is invalid")
        if barrier_thickness_ft > spec.max_barrier_thickness_ft:
            raise ValueError("typed spell communication route barrier is too thick")
        if spec.barrier_requires_familiarity and not familiar:
            raise ValueError("typed spell communication route barrier requires familiarity")
    elif barrier_thickness_ft != 0:
        raise ValueError("typed spell communication route has thickness without barrier")
    if spec.magical_silence_blocks and (sender_in_magical_silence or target_in_magical_silence):
        raise ValueError("typed spell communication route is blocked by magical silence")
    if len(message_fingerprint.strip()) != 64:
        raise ValueError("typed spell communication route message_fingerprint must be sha256")

    request_fingerprint = _fingerprint(
        {
            "spec": spec.as_dict(),
            "distance_ft": distance_ft,
            "visible": visible,
            "familiar": familiar,
            "barrier_present": barrier_present,
            "barrier_thickness_ft": barrier_thickness_ft,
            "sender_in_magical_silence": sender_in_magical_silence,
            "target_in_magical_silence": target_in_magical_silence,
            "message_fingerprint": message_fingerprint,
        }
    )
    if prior_receipt is not None:
        if prior_receipt.request_fingerprint != request_fingerprint:
            raise ValueError("typed spell communication route replay payload does not match")
        return dict(state), TypedSpellCommunicationRouteReceipt(
            **{**prior_receipt.as_dict(), "replayed": True}
        )

    routes = state.get("communication_routes", [])
    if not isinstance(routes, list) or any(not isinstance(item, Mapping) for item in routes):
        raise ValueError("typed spell communication route state is invalid")
    route_id = f"{spec.source_record_id}:{spec.sender_id}:{spec.target_id}"
    updated_routes = [dict(item) for item in routes if item.get("route_id") != route_id]
    updated_routes.append(
        {
            "route_id": route_id,
            "schema": COMMUNICATION_ROUTE_SCHEMA,
            "content_id": spec.content_id,
            "source_record_id": spec.source_record_id,
            "source_fingerprint": spec.source_fingerprint,
            "clause_id": spec.clause_id,
            "sender_id": spec.sender_id,
            "target_id": spec.target_id,
            "delivered_to": spec.target_id,
            "private_reply_to": spec.sender_id,
            "message_fingerprint": message_fingerprint,
            "target_only": spec.target_only,
            "private_reply": spec.private_reply,
        }
    )
    after_version = current_version + 1
    updated_state = {**state, "version": after_version, "communication_routes": updated_routes}
    receipt = TypedSpellCommunicationRouteReceipt(
        schema=COMMUNICATION_ROUTE_SCHEMA,
        content_id=spec.content_id,
        source_record_id=spec.source_record_id,
        source_fingerprint=spec.source_fingerprint,
        clause_id=spec.clause_id,
        sender_id=spec.sender_id,
        target_id=spec.target_id,
        delivered_to=spec.target_id,
        private_reply_to=spec.sender_id,
        request_fingerprint=request_fingerprint,
        state_version_before=current_version,
        state_version_after=after_version,
    )
    return updated_state, receipt
