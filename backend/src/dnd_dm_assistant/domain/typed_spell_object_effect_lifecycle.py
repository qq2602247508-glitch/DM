"""Generic, source-bound object/surface effect lifecycle consumer.

The consumer is intentionally mode-driven rather than spell-name-driven.  A
reviewed runtime supplies the six typed modes and the request selects one of
them.  This module owns target/range/size validation, immediate versus timed
state, next-turn expiry, dismissal, three-slot concurrency, CAS, and replay.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

OBJECT_EFFECT_SCHEMA = "spell.object_effect.lifecycle.v1"
_MODES = {
    "sensory_effect",
    "fire_play",
    "clean_or_soil",
    "minor_sensation",
    "magic_mark",
    "minor_creation",
}
_TIMED_MODES = {"minor_sensation", "magic_mark", "minor_creation"}


def _fingerprint(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _positive_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError(f"{label} must be positive")
    return float(value)


@dataclass(frozen=True, slots=True)
class TypedSpellObjectEffectSpec:
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    source_id: str
    range_ft: int
    max_concurrent_noninstant: int
    modes: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        for field in ("content_id", "source_record_id", "clause_id", "source_id"):
            if not _text(getattr(self, field)):
                raise ValueError(f"object effect {field} is required")
        if len(self.source_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.source_fingerprint.lower()
        ):
            raise ValueError("object effect source_fingerprint must be sha256")
        if self.range_ft != 10:
            raise ValueError("object effect range must be 10 feet")
        if self.max_concurrent_noninstant != 3:
            raise ValueError("object effect concurrency must be three")
        if {str(item.get("mode") or "") for item in self.modes} != _MODES:
            raise ValueError("object effect contract must contain exactly six typed modes")
        for mode in self.modes:
            _validate_mode(mode)

    def mode(self, mode: str) -> Mapping[str, Any]:
        wanted = _text(mode)
        for item in self.modes:
            if _text(item.get("mode")) == wanted:
                return item
        raise ValueError("object effect mode is not supported by the source contract")

    def as_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "source_id": self.source_id,
            "range_ft": self.range_ft,
            "max_concurrent_noninstant": self.max_concurrent_noninstant,
            "modes": [dict(item) for item in self.modes],
        }


def _validate_mode(mode: Mapping[str, Any]) -> None:
    name = _text(mode.get("mode"))
    if name not in _MODES:
        raise ValueError("object effect mode is unsupported")
    if name in {"sensory_effect", "fire_play", "clean_or_soil"}:
        if _text(mode.get("lifecycle")) != "instant":
            raise ValueError("instant object effect mode has invalid lifecycle")
    else:
        if _text(mode.get("lifecycle")) != "timed":
            raise ValueError("timed object effect mode has invalid lifecycle")
    if name in {"minor_sensation", "magic_mark"} and (
        mode.get("duration_unit") != "hours" or mode.get("duration_value") != 1
    ):
        raise ValueError("one-hour object effect mode is invalid")
    if name == "minor_creation" and _text(mode.get("duration_unit")) != "next_turn_end":
        raise ValueError("minor creation must expire at next turn end")


def _validate_request(
    mode: Mapping[str, Any],
    *,
    target_kind: str,
    target_id: str | None,
    distance_ft: int,
    size_cubic_ft: float | None,
    nonliving: bool,
    payload: Mapping[str, Any],
) -> None:
    name = _text(mode.get("mode"))
    if isinstance(distance_ft, bool) or not isinstance(distance_ft, int) or distance_ft < 0:
        raise ValueError("object effect target distance is invalid")
    if distance_ft > 10:
        raise ValueError("object effect target is beyond the 10-foot range")
    if name == "sensory_effect":
        if target_kind != "none":
            raise ValueError("sensory effect does not accept an object target")
        if not _text(payload.get("sensory_kind")):
            raise ValueError("sensory effect requires a typed sensory kind")
        return
    if not target_id:
        raise ValueError("object effect target_id is required")
    allowed = {
        "fire_play": {"fire_source"},
        "clean_or_soil": {"object"},
        "minor_sensation": {"nonliving_material"},
        "magic_mark": {"object", "surface"},
        "minor_creation": {"creation_space"},
    }[name]
    if target_kind not in allowed:
        raise ValueError("object effect target kind is invalid for the selected mode")
    if name == "fire_play" and _text(payload.get("fire_source")) not in {
        "candle",
        "torch",
        "small_campfire",
    }:
        raise ValueError("fire play requires candle, torch, or small campfire")
    if name == "fire_play" and _text(payload.get("operation")) not in {"ignite", "extinguish"}:
        raise ValueError("fire play requires ignite or extinguish")
    if name == "clean_or_soil" and _text(payload.get("operation")) not in {"clean", "soil"}:
        raise ValueError("clean or soil requires clean or soil")
    if name == "minor_sensation" and not nonliving:
        raise ValueError("minor sensation requires nonliving material")
    if name == "minor_sensation" and _text(payload.get("sensation")) not in {
        "warm",
        "cool",
        "season",
    }:
        raise ValueError("minor sensation requires warm, cool, or season")
    if name == "magic_mark" and not _text(payload.get("mark_kind")):
        raise ValueError("magic mark requires a typed mark kind")
    if size_cubic_ft is not None and size_cubic_ft < 0:
        raise ValueError("object effect size is invalid")
    if name in {"clean_or_soil", "minor_sensation"}:
        if size_cubic_ft is None or size_cubic_ft > 1:
            raise ValueError("object effect target must be no larger than one cubic foot")
    if name == "minor_creation" and _text(payload.get("creation_kind")) not in {
        "trinket",
        "illusory_image",
    }:
        raise ValueError("minor creation requires trinket or illusory image")
    if name == "minor_creation":
        if size_cubic_ft is not None and size_cubic_ft > 1:
            raise ValueError("minor creation cannot exceed palm size")
        if payload.get("nonmagical") is not True or payload.get("no_damage") is not True:
            raise ValueError("minor creation must be nonmagical and harmless")
        if payload.get("no_value") is not True:
            raise ValueError("minor creation trinket/image has no value")


@dataclass(frozen=True, slots=True)
class TypedSpellObjectEffectReceipt:
    schema: str
    content_id: str
    source_record_id: str
    source_fingerprint: str
    clause_id: str
    effect_id: str
    mode: str
    lifecycle: str
    expires_at: str | None
    expires_turn: int | None
    state_version_before: int
    state_version_after: int
    request_fingerprint: str
    replayed: bool = False
    termination: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "content_id": self.content_id,
            "source_record_id": self.source_record_id,
            "source_fingerprint": self.source_fingerprint,
            "clause_id": self.clause_id,
            "effect_id": self.effect_id,
            "mode": self.mode,
            "lifecycle": self.lifecycle,
            "expires_at": self.expires_at,
            "expires_turn": self.expires_turn,
            "state_version_before": self.state_version_before,
            "state_version_after": self.state_version_after,
            "request_fingerprint": self.request_fingerprint,
            "replayed": self.replayed,
            "termination": self.termination,
        }


def apply_typed_spell_object_effect(
    spec: TypedSpellObjectEffectSpec,
    *,
    state: dict[str, Any],
    expected_version: int,
    now: datetime,
    mode: str,
    target_kind: str,
    target_id: str | None,
    distance_ft: int,
    size_cubic_ft: float | None,
    nonliving: bool,
    payload: Mapping[str, Any],
    current_turn: int,
    prior_receipt: TypedSpellObjectEffectReceipt | None = None,
) -> tuple[dict[str, Any], TypedSpellObjectEffectReceipt]:
    version = state.get("version", 0)
    if isinstance(version, bool) or not isinstance(version, int) or version != expected_version:
        raise ValueError("object effect state version is stale or invalid")
    if isinstance(current_turn, bool) or not isinstance(current_turn, int) or current_turn < 0:
        raise ValueError("object effect current_turn is invalid")
    mode_spec = spec.mode(mode)
    _validate_request(
        mode_spec,
        target_kind=target_kind,
        target_id=target_id,
        distance_ft=distance_ft,
        size_cubic_ft=size_cubic_ft,
        nonliving=nonliving,
        payload=payload,
    )
    started_at = _utc(now)
    request = {
        "spec": spec.as_dict(),
        "mode": mode,
        "target_kind": target_kind,
        "target_id": target_id,
        "distance_ft": distance_ft,
        "size_cubic_ft": size_cubic_ft,
        "nonliving": nonliving,
        "payload": dict(payload),
        "current_turn": current_turn,
        "started_at": started_at.isoformat(),
    }
    request_fingerprint = _fingerprint(request)
    if prior_receipt is not None:
        if prior_receipt.request_fingerprint != request_fingerprint:
            raise ValueError("object effect replay payload does not match")
        return dict(state), TypedSpellObjectEffectReceipt(
            **{**prior_receipt.as_dict(), "replayed": True}
        )

    effects = state.get("object_effects", [])
    if not isinstance(effects, list) or any(not isinstance(item, Mapping) for item in effects):
        raise ValueError("object effect state is invalid")
    active: list[dict[str, Any]] = []
    for item in effects:
        row = dict(item)
        if row.get("termination") is not None:
            continue
        expiry = row.get("expires_at")
        expired = False
        if expiry:
            expired = _utc(started_at) >= _utc(datetime.fromisoformat(str(expiry)))
        if row.get("expires_turn") is not None:
            expired = expired or current_turn > int(row["expires_turn"])
        if not expired:
            active.append(row)
    effect_id = f"{spec.source_id}:{mode}:{target_id or 'ambient'}"
    active = [row for row in active if row.get("effect_id") != effect_id]
    if (
        _text(mode_spec.get("lifecycle")) != "instant"
        and len(active) >= spec.max_concurrent_noninstant
    ):
        raise ValueError("object effect allows at most three different non-instant effects")
    lifecycle = _text(mode_spec.get("lifecycle"))
    expires_at: str | None = None
    expires_turn: int | None = None
    if lifecycle == "timed" and _text(mode_spec.get("duration_unit")) == "hours":
        expires_at = (started_at + timedelta(hours=int(mode_spec["duration_value"]))).isoformat()
    elif lifecycle == "timed":
        expires_turn = current_turn + 1
    if lifecycle != "instant":
        active.append(
            {
                "effect_id": effect_id,
                "content_id": spec.content_id,
                "source_record_id": spec.source_record_id,
                "source_fingerprint": spec.source_fingerprint,
                "clause_id": spec.clause_id,
                "mode": mode,
                "lifecycle": lifecycle,
                "target_kind": target_kind,
                "target_id": target_id,
                "distance_ft": distance_ft,
                "size_cubic_ft": size_cubic_ft,
                "nonliving": nonliving,
                "payload": dict(payload),
                "started_at": started_at.isoformat(),
                "expires_at": expires_at,
                "expires_turn": expires_turn,
                "termination": None,
            }
        )
    updated = {"version": version + 1, "object_effects": active}
    receipt = TypedSpellObjectEffectReceipt(
        schema=OBJECT_EFFECT_SCHEMA,
        content_id=spec.content_id,
        source_record_id=spec.source_record_id,
        source_fingerprint=spec.source_fingerprint,
        clause_id=spec.clause_id,
        effect_id=effect_id,
        mode=mode,
        lifecycle=lifecycle,
        expires_at=expires_at,
        expires_turn=expires_turn,
        state_version_before=version,
        state_version_after=version + 1,
        request_fingerprint=request_fingerprint,
    )
    return updated, receipt


def terminate_typed_spell_object_effect(
    state: Mapping[str, Any],
    *,
    expected_version: int,
    effect_id: str,
    reason: str,
    now: datetime,
    current_turn: int,
) -> tuple[dict[str, Any], TypedSpellObjectEffectReceipt]:
    version = state.get("version", 0)
    if version != expected_version:
        raise ValueError("object effect state version is stale")
    if reason not in {"dismiss", "expiry"}:
        raise ValueError("object effect termination reason is invalid")
    rows = state.get("object_effects", [])
    if not isinstance(rows, list):
        raise ValueError("object effect state is invalid")
    target = next((dict(row) for row in rows if row.get("effect_id") == effect_id), None)
    if target is None:
        raise ValueError("object effect is not active")
    if reason == "expiry":
        expired_at = target.get("expires_at")
        expired_turn = target.get("expires_turn")
        if expired_at and _utc(now) < _utc(datetime.fromisoformat(str(expired_at))):
            raise ValueError("object effect has not expired")
        if expired_turn is not None and current_turn <= int(expired_turn):
            raise ValueError("object effect has not reached next-turn expiry")
    target["termination"] = reason
    target["terminated_at"] = _utc(now).isoformat()
    updated = {
        "version": version + 1,
        "object_effects": [
            target if row.get("effect_id") == effect_id else dict(row) for row in rows
        ],
    }
    receipt = TypedSpellObjectEffectReceipt(
        schema=OBJECT_EFFECT_SCHEMA,
        content_id=_text(target.get("content_id")) or "unknown",
        source_record_id=_text(target.get("source_record_id")) or "unknown",
        source_fingerprint=_text(target.get("source_fingerprint")) or "0" * 64,
        clause_id=_text(target.get("clause_id")) or "object_effect_lifecycle",
        effect_id=effect_id,
        mode=_text(target.get("mode")),
        lifecycle=_text(target.get("lifecycle")),
        expires_at=target.get("expires_at"),
        expires_turn=target.get("expires_turn"),
        state_version_before=version,
        state_version_after=version + 1,
        request_fingerprint=_fingerprint(
            {"effect_id": effect_id, "reason": reason, "current_turn": current_turn}
        ),
        termination=reason,
    )
    return updated, receipt
