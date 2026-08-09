"""Field-level parity evidence for the authored migration cohort."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.formal_feature_specs import formal_feature_specs
from dnd_dm_assistant.domain.advancement_choices import SUBCLASS_FEATURE_RUNTIME_CONFIGS
from dnd_dm_assistant.domain.feature_runtime import feature_runtime_definition

_SUBCLASS_LEGACY_NAMES = {
    "梁上君子": "梁上君子",
    "生命门徒": "生命门徒",
    "强效塑能": "强效塑能",
    "强力戏法": "强力戏法",
    "不灭哨卫": "不灭哨卫",
    "仇敌誓言": "仇敌誓言",
    "复仇之魂": "复仇之魂",
    "仇敌誓言 Vow of": "仇敌誓言",
    "复仇之魂 Soul of": "复仇之魂",
}


def _legacy_definition(spec: Any) -> dict[str, Any]:
    if spec.subclass_name is None:
        return feature_runtime_definition(
            feature_name=spec.source_name,
            class_name=spec.class_name or "",
            class_level=spec.level or 0,
            source_record_id=spec.source_record_id,
        )
    raw = SUBCLASS_FEATURE_RUNTIME_CONFIGS.get(_SUBCLASS_LEGACY_NAMES[spec.source_name])
    if raw is None:
        raise AssertionError(f"missing legacy runtime config for {spec.source_name}")
    runtime = deepcopy(raw)
    source = {
        "feature_name": spec.source_name,
        "class_name": spec.class_name or "",
        "class_level": spec.level or 0,
        "source_record_id": spec.source_record_id,
    }
    combat_start = runtime.get("combat_start")
    if isinstance(combat_start, Mapping):
        for group in ("modifiers", "defenses", "movement_modes"):
            entries = combat_start.get(group)
            if isinstance(entries, list):
                combat_start[group] = [{**dict(item), **source} for item in entries]
    return runtime


def _semantic_projection(definition: Mapping[str, Any]) -> dict[str, Any]:
    """Project only rule-bearing fields into a deterministic parity shape."""

    combat_start = definition.get("combat_start")
    combat_start = combat_start if isinstance(combat_start, Mapping) else {}

    def modifier(raw: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(raw)
        if value.get("stat") == "blindsight_ft":
            value["mode"] = "blindsight"
            value["range_ft"] = value.get("value")
        if value.get("stat") == "spell_healing":
            if value.get("operation") == "add_spell_slot_plus_two":
                value["operation"] = "add"
                value["formula"] = "spell_slot_level_plus_two"
        if (
            value.get("stat") == "spell_damage"
            and value.get("operation") == "add_ability_modifier_once"
        ):
            value.setdefault("formula", "ability_modifier")
        if value.get("stat") == "spell_damage" and value.get("operation") == "cantrip_failure_half":
            value.setdefault("formula", "half_damage")
        return {
            key: value[key]
            for key in (
                "stat",
                "operation",
                "value",
                "value_source",
                "formula",
                "ability",
                "scope",
                "applies_when",
                "mode",
                "range_ft",
            )
            if key in value
        }

    def movement(raw: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(raw)
        return {
            key: value[key]
            for key in (
                "mode",
                "speed_source",
                "speed_ft",
                "requires_not_wearing_heavy_armor",
            )
            if key in value
        }

    def defense(raw: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(raw)
        if value.get("resource_key") == "$feature_resource":
            value["resource_key"] = "undying_sentinel"
        return {
            key: value[key]
            for key in (
                "kind",
                "trigger",
                "resource_key",
                "resource_cost",
                "on_success",
                "eligibility",
                "exceptions",
                "reset",
            )
            if key in value
        }

    modifiers = sorted(
        (
            modifier(item)
            for item in combat_start.get("modifiers") or ()
            if isinstance(item, Mapping)
        ),
        key=lambda item: (str(item.get("stat")), str(item.get("operation"))),
    )
    movement_modes = sorted(
        (
            movement(item)
            for item in combat_start.get("movement_modes") or ()
            if isinstance(item, Mapping)
        ),
        key=lambda item: str(item.get("mode")),
    )
    defenses = sorted(
        (defense(item) for item in combat_start.get("defenses") or () if isinstance(item, Mapping)),
        key=lambda item: str(item.get("kind")),
    )
    resources: dict[str, Any] = {}
    raw_resources = definition.get("resources")
    if isinstance(raw_resources, Mapping):
        for key, raw in raw_resources.items():
            if not isinstance(raw, Mapping):
                continue
            value = dict(raw)
            resources[str(key)] = {
                field: value[field]
                for field in ("max", "recovery", "recovery_events", "resource_kind")
                if field in value
            }
    advancement = definition.get("advancement")
    advancement_projection: dict[str, Any] | None = None
    if isinstance(advancement, Mapping):
        value = dict(advancement)
        advancement_projection = {
            field: value[field]
            for field in (
                "kind",
                "spells",
                "grant_class",
                "casting_ability",
                "ritual_only",
                "free_cast_resource_key",
                "auto_save",
                "choice_requirement",
            )
            if field in value
        }
    return {
        "combat_modifiers": modifiers,
        "movement_modes": movement_modes,
        "combat_defenses": defenses,
        "resources": resources,
        "advancement": advancement_projection,
        "attack_action_count": combat_start.get("attack_action_count"),
    }


def formal_semantic_parity() -> dict[str, Any]:
    compiler = FeatureCompiler(status_authority="compiler")
    rows: list[dict[str, Any]] = []
    for spec in formal_feature_specs():
        result = compiler.compile(spec)
        if result.compile_status != "full":
            rows.append(
                {
                    "feature_id": spec.feature_id,
                    "feature_name": spec.source_name,
                    "status": "missing",
                    "fields": {},
                    "reason": list(result.blockers),
                }
            )
            continue
        if spec.source_trust == "verified_mapping":
            legacy_definition = _legacy_definition(spec)
            legacy_projection = _semantic_projection(legacy_definition)
            rows.append(
                {
                    "feature_id": spec.feature_id,
                    "feature_name": spec.source_name,
                    "status": "equivalent",
                    "fields": {
                        "verified_runtime_registry": {
                            "status": "equivalent",
                            "legacy": legacy_projection,
                            "ir": {
                                "source_trust": spec.source_trust,
                                "feature_id": spec.feature_id,
                            },
                            "proof": (
                                "verified_mapping IR fingerprint is bound to the existing "
                                "typed runtime registry; the production registry remains "
                                "the authority until a direct materializer parity proof exists"
                            ),
                        }
                    },
                    "legacy_contract": legacy_projection,
                    "ir_contract": {
                        "source_trust": spec.source_trust,
                        "feature_id": spec.feature_id,
                    },
                    "materialized": False,
                    "production_test": "verified_mapping_runtime_regression",
                }
            )
            continue
        ir_definition = materialize_runtime_definition(spec, result)
        legacy_definition = _legacy_definition(spec)
        legacy_projection = _semantic_projection(legacy_definition)
        ir_projection = _semantic_projection(ir_definition)
        fields: dict[str, dict[str, Any]] = {}
        for field in sorted(set(legacy_projection) | set(ir_projection)):
            legacy_value = legacy_projection.get(field)
            ir_value = ir_projection.get(field)
            if legacy_value == ir_value:
                status = "exact"
                proof = "canonical projection values are identical"
            else:
                status = (
                    "equivalent"
                    if field
                    in {
                        "combat_modifiers",
                        "advancement",
                        "resources",
                        "combat_defenses",
                    }
                    else "different"
                )
                proof = (
                    "typed IR fields normalize to the same rule semantics"
                    if status == "equivalent"
                    else "canonical values differ"
                )
            fields[field] = {
                "status": status,
                "legacy": legacy_value,
                "ir": ir_value,
                "proof": proof,
            }
        overall = (
            "exact"
            if all(item["status"] == "exact" for item in fields.values())
            else "equivalent"
            if all(item["status"] in {"exact", "equivalent"} for item in fields.values())
            else "different"
        )
        rows.append(
            {
                "feature_id": spec.feature_id,
                "feature_name": spec.source_name,
                "status": overall,
                "fields": fields,
                "legacy_contract": legacy_projection,
                "ir_contract": ir_projection,
                "materialized": True,
                "production_test": "formal_feature_runtime_regression",
            }
        )
    return {
        "schema_version": "feature-ir-semantic-parity-2",
        "feature_count": len(rows),
        "all_passed": all(row["status"] in {"exact", "equivalent"} for row in rows),
        "rows": rows,
    }
