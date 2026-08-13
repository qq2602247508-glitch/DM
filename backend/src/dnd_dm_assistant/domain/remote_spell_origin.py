"""Provenance-bound remote spell origin resolution.

This contract is intentionally persistence- and feature-name-agnostic.  It
resolves an already-authorized entity origin against the existing
``SpatialAuthority`` facts; it does not create entities, mutate combat, or
decide which feature owns the origin.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from dnd_dm_assistant.domain.spatial_authority import SpatialAuthority

REMOTE_SPELL_ORIGIN_SCHEMA = "remote.spell.origin.v1"


@dataclass(frozen=True, slots=True)
class RemoteSpellOriginContract:
    source_record_id: str
    source_fingerprint: str
    actor_id: str
    origin_kind: str = "entity"
    origin_id: str = ""
    max_range_ft: int | None = None
    require_line_of_effect: bool = True
    target_kind: str = "one_creature"

    def __post_init__(self) -> None:
        values = {
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "actor_id": self.actor_id,
            "origin_id": self.origin_id,
        }
        if any(not str(value).strip() for value in values.values()):
            raise ValueError("remote spell origin provenance, actor, and origin are required")
        if self.origin_kind != "entity":
            raise ValueError("remote spell origin only supports entity origins")
        if self.max_range_ft is not None and (
            isinstance(self.max_range_ft, bool) or self.max_range_ft < 0
        ):
            raise ValueError("remote spell origin max_range_ft must be non-negative")
        if self.target_kind not in {"one_creature", "multiple_creatures"}:
            raise ValueError("remote spell origin target_kind is unsupported")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": REMOTE_SPELL_ORIGIN_SCHEMA,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "actor_id": self.actor_id,
            "origin_kind": self.origin_kind,
            "origin_id": self.origin_id,
            "max_range_ft": self.max_range_ft,
            "require_line_of_effect": self.require_line_of_effect,
            "target_kind": self.target_kind,
        }


@dataclass(frozen=True, slots=True)
class RemoteSpellOriginResolution:
    origin_id: str
    target_ids: tuple[str, ...]
    distances_ft: dict[str, int]
    line_of_effect: dict[str, bool]


def resolve_remote_spell_origin(
    contract: RemoteSpellOriginContract,
    *,
    actor_id: str,
    authorized_origin_ids: Sequence[str],
    target_ids: Sequence[str],
    spatial: SpatialAuthority,
) -> RemoteSpellOriginResolution:
    """Resolve one remote origin using authoritative scene facts.

    Authorization is deliberately supplied as an explicit source-owned set.
    A caller cannot infer authority from a feature or spell name.
    """

    if str(actor_id).strip() != contract.actor_id:
        raise ValueError("remote spell origin actor authorization failed")
    if contract.origin_id not in {str(item).strip() for item in authorized_origin_ids}:
        raise ValueError("remote spell origin source authorization failed")
    normalized_targets = tuple(
        dict.fromkeys(str(item).strip() for item in target_ids if str(item).strip())
    )
    if not normalized_targets:
        raise ValueError("remote spell origin requires at least one target")
    if contract.target_kind == "one_creature" and len(normalized_targets) != 1:
        raise ValueError("remote spell origin single-target resolution is invalid")
    if contract.target_kind == "multiple_creatures" and len(normalized_targets) < 1:
        raise ValueError("remote spell origin multi-target resolution is invalid")

    distances: dict[str, int] = {}
    line_of_effect: dict[str, bool] = {}
    for target_id in normalized_targets:
        distance = spatial.distance_between(contract.origin_id, target_id)
        if contract.max_range_ft is not None and distance > contract.max_range_ft:
            raise ValueError(f"remote spell origin target is outside range: {target_id}")
        has_line = spatial.has_line_of_sight(contract.origin_id, target_id)
        if contract.require_line_of_effect and not has_line:
            raise ValueError(f"remote spell origin target lacks line of effect: {target_id}")
        distances[target_id] = distance
        line_of_effect[target_id] = has_line
    return RemoteSpellOriginResolution(
        origin_id=contract.origin_id,
        target_ids=normalized_targets,
        distances_ft=distances,
        line_of_effect=line_of_effect,
    )
