# ruff: noqa: E501
"""Template and Candidate IR authority for the unified content workbench.

The template layer is deliberately descriptive.  It can match a source record
to a reviewed shape and copy only fields that are explicit in the normalized
source.  It never turns a source draft into an executable spec.  The review
authority is the only boundary that can produce ``authored_ir`` data.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_workbench import (
    COMPILER_FINGERPRINT,
    _bounded_source_text,
    _fingerprint,
    _is_feature_candidate,
    _is_spell_detail,
    _pack_id_for_book,
    _safe_filename,
    _source_fingerprint,
    _source_record_id,
    _text,
    compile_spell_spec,
    compile_typed_feature_spec,
    load_records,
)
from dnd_dm_assistant.application.rule_metadata import spell_rule_fields
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

TEMPLATE_SCHEMA_VERSION = "content-ir-template-catalog-1"
CANDIDATE_SCHEMA_VERSION = "content-ir-candidate-1"
REVIEW_SCHEMA_VERSION = "content-ir-review-authority-1"
FORBIDDEN_INFERENCE_FIELDS = (
    "operator",
    "target_semantics",
    "action_economy",
    "resource_costs",
    "complex_duration_triggers",
    "summon_control",
    "choice_values",
    "complex_movement",
    "attack_or_save_branch",
)

_SPELL_REQUIRED = {
    "saving_throw": ["save_ability"],
    "damage": ["expression", "damage_type"],
    "healing": ["expression"],
    "temporary_hp": ["amount", "expression"],
    "concentration": ["required"],
    "area": ["shape", "size_ft"],
    "upcast": ["increments", "per_slot"],
    "apply_condition": ["condition"],
}
_SPELL_OPTIONAL = {
    "saving_throw": ["half_on_success", "target", "range"],
    "damage": ["target", "timing", "on_failure", "on_success"],
    "healing": ["target", "timing"],
    "temporary_hp": ["target", "duration"],
    "concentration": ["duration", "applies_to"],
    "area": ["origin", "target", "range"],
    "upcast": ["text", "applies_to"],
    "apply_condition": ["duration", "on_failure"],
}


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def _iter_typed(input_dir: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(input_dir.rglob("*.json")):
        if path.name in {"manifest.json", "compile-result.json", "report.json"}:
            continue
        try:
            value = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if value.get("kind") in {"spell", "feature"} and value.get("review_status") == "reviewed":
            result.append(value)
    return result


def _spell_shape(spec: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item.get("type") or "") for item in spec.get("clauses") or [] if item.get("type")
    )


def _feature_shape(spec: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(effect.get("operator") or "")
        for clause in spec.get("clauses") or []
        for effect in clause.get("effects") or []
        if effect.get("operator")
    )


def _compile_metadata(spec: Mapping[str, Any]) -> tuple[list[str], list[str], list[str]]:
    kind = str(spec.get("kind") or "")
    if kind == "spell":
        compiled = compile_spell_spec(
            __import__(
                "dnd_dm_assistant.application.content_ir_workbench",
                fromlist=["SpellSpec"],
            ).SpellSpec.from_dict(spec)
        )
        return (
            list(compiled.get("capability_ids") or []),
            ["spell_runtime_materializer"],
            ["spell_economy.cast", "combat_engine.action", "combat_engine.effect"],
        )
    feature_value = dict(spec)
    feature_value.pop("kind", None)
    compiled = compile_typed_feature_spec(FeatureSpec.from_dict(feature_value, "template.feature"))
    capability_ids = sorted(
        {
            str(capability)
            for clause in compiled.get("clause_results") or []
            for capability in clause.get("capability_ids") or []
        }
    )
    materializers = sorted(
        {
            str(block.get("materializer_id"))
            for block in compiled.get("generated_runtime_blocks") or []
            if block.get("materializer_id")
        }
    )
    return (
        capability_ids,
        materializers,
        ["combat_engine.feature_action", "advancement_service", "rest_service"],
    )


def _requirements(kind: str, shape: tuple[str, ...]) -> list[str]:
    requirements = ["source_evidence", "reviewed_typed_ir", "byte_identical_compile"]
    if kind == "spell":
        requirements.extend(["known_spell", "character_version_cas", "idempotency_key"])
        if any(item in shape for item in ("damage", "healing", "temporary_hp", "apply_condition")):
            requirements.append("combat_target_and_target_version")
        if "saving_throw" in shape:
            requirements.append("saving_throw_input")
        if "attack_roll" in shape:
            requirements.append("attack_roll_input")
        if "concentration" in shape:
            requirements.append("concentration_state")
    else:
        requirements.extend(["character_or_combatant", "actor_version_cas", "idempotency_key"])
    return requirements


def build_template_catalog(input_dir: Path, output: Path) -> dict[str, Any]:
    """Extract stable, name-independent templates from reviewed Typed IR."""

    typed = _iter_typed(input_dir)
    grouped: dict[tuple[str, tuple[str, ...]], list[dict[str, Any]]] = {}
    for spec in typed:
        kind = str(spec["kind"])
        shape = _spell_shape(spec) if kind == "spell" else _feature_shape(spec)
        if shape:
            grouped.setdefault((kind, shape), []).append(spec)

    templates: list[dict[str, Any]] = []
    for index, ((kind, shape), examples) in enumerate(sorted(grouped.items())):
        capability_ids: set[str] = set()
        materializers: set[str] = set()
        consumers: set[str] = set()
        for example in examples:
            try:
                capabilities, example_materializers, example_consumers = _compile_metadata(example)
            except (TypeError, ValueError):
                capabilities, example_materializers, example_consumers = [], [], []
            capability_ids.update(capabilities)
            materializers.update(example_materializers)
            consumers.update(example_consumers)
        required_fields: dict[str, list[str]] = {}
        optional_fields: dict[str, list[str]] = {}
        if kind == "spell":
            for clause_type in shape:
                required_fields[clause_type] = list(
                    _SPELL_REQUIRED.get(clause_type, ["type", "clause_id"])
                )
                optional_fields[clause_type] = list(_SPELL_OPTIONAL.get(clause_type, []))
        else:
            for clause in examples[0].get("clauses") or []:
                for effect in clause.get("effects") or []:
                    operator = str(effect.get("operator") or "")
                    required_fields[operator] = sorted((effect.get("parameters") or {}).keys())
                    optional_fields[operator] = []
        runtime_requirements = _requirements(kind, shape)
        fingerprint_payload = {
            "kind": kind,
            "shape": list(shape),
            "required_fields": required_fields,
            "optional_fields": optional_fields,
            "forbidden_inference_fields": list(FORBIDDEN_INFERENCE_FIELDS),
            "capability_ids": sorted(capability_ids),
            "materializer_ids": sorted(materializers),
            "runtime_requirements": runtime_requirements,
        }
        templates.append(
            {
                "template_id": f"{kind}.shape.{index + 1:03d}",
                "schema_version": "content-ir-template-1",
                "content_kind": kind,
                "required_fields": required_fields,
                "optional_fields": optional_fields,
                "forbidden_inference_fields": list(FORBIDDEN_INFERENCE_FIELDS),
                "clause_shape": list(shape),
                "capability_ids": sorted(capability_ids),
                "materializer_ids": sorted(materializers),
                "runtime_requirements": runtime_requirements,
                "production_consumers": sorted(consumers),
                "validation_rules": [
                    "all required typed fields must be explicit or reviewed",
                    "source_fingerprint and template_fingerprint must remain stable",
                    "generated_candidate cannot be compile_full",
                    "production_runtime_full requires production evidence",
                ],
                "source_examples": [
                    str(
                        item.get("source_record_id")
                        or item.get("spell_id")
                        or item.get("feature_id")
                    )
                    for item in sorted(
                        examples,
                        key=lambda value: str(value.get("name") or value.get("source_name") or ""),
                    )[:8]
                ],
                "template_fingerprint": _fingerprint(fingerprint_payload),
            }
        )
    catalog = {
        "schema_version": TEMPLATE_SCHEMA_VERSION,
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "template_count": len(templates),
        "templates": templates,
        "catalog_fingerprint": _fingerprint(templates),
    }
    _write_json(output, catalog)
    return catalog


def _match_template(
    catalog: Mapping[str, Any], kind: str, shape: tuple[str, ...]
) -> dict[str, Any] | None:
    candidates = [
        item for item in catalog.get("templates") or [] if item.get("content_kind") == kind
    ]
    exact = [item for item in candidates if tuple(item.get("clause_shape") or []) == shape]
    if exact:
        return sorted(exact, key=lambda item: str(item.get("template_id")))[0]
    if not candidates:
        return None
    # Matching is descriptive only.  It does not authorize executable output.
    return max(
        candidates,
        key=lambda item: len(set(shape).intersection(item.get("clause_shape") or [])),
    )


def _spell_candidate(
    record: Mapping[str, Any], catalog: Mapping[str, Any], pack_id: str
) -> dict[str, Any]:
    fields = spell_rule_fields(record)
    exact: dict[str, Any] = {}
    uncertain: dict[str, Any] = {}
    missing: list[str] = []
    clauses: list[dict[str, Any]] = []
    if fields.get("save") and fields.get("damage_expression") and fields.get("damage_type"):
        clauses.extend(
            [
                {"type": "saving_throw", "save_ability": _text(fields["save"]).replace("豁免", "")},
                {
                    "type": "damage",
                    "expression": fields["damage_expression"],
                    "damage_type": fields["damage_type"],
                    "on_failure": "full",
                },
            ]
        )
        exact.update(
            {
                "save": fields["save"],
                "damage_expression": fields["damage_expression"],
                "damage_type": fields["damage_type"],
            }
        )
    elif fields.get("healing"):
        clauses.append({"type": "healing", "expression": fields["healing"]})
        exact["healing"] = fields["healing"]
    elif fields.get("temporary_hp"):
        clauses.append({"type": "temporary_hp", "expression": fields.get("healing")})
        exact["temporary_hp"] = True
    elif fields.get("damage_expression") and fields.get("damage_type"):
        uncertain["operator"] = "attack_roll_or_other_damage_operator_requires_review"
        uncertain["damage_expression"] = fields["damage_expression"]
        uncertain["damage_type"] = fields["damage_type"]
        missing.append("attack_or_save")
    if fields.get("area_shape") and fields.get("area_size_ft"):
        clauses.append(
            {"type": "area", "shape": fields["area_shape"], "size_ft": fields["area_size_ft"]}
        )
        exact.update({"area_shape": fields["area_shape"], "area_size_ft": fields["area_size_ft"]})
    if fields.get("concentration") is True:
        clauses.append({"type": "concentration", "required": True})
        exact["concentration"] = True
    if fields.get("upcast_damage_dice") or fields.get("upcast_healing_dice"):
        increment = fields.get("upcast_damage_dice") or fields.get("upcast_healing_dice")
        clauses.append({"type": "upcast", "increments": f"{increment}d", "per_slot": 1})
        exact["upcast"] = increment
    if fields.get("conditions") and fields.get("save"):
        for condition in fields["conditions"]:
            clauses.append({"type": "apply_condition", "condition": condition})
        exact["conditions"] = list(fields["conditions"])
    if not clauses:
        missing.append("typed_clause_mapping")
    shape = tuple(str(item.get("type")) for item in clauses)
    template = _match_template(catalog, "spell", shape)
    confidence = "high" if clauses and not uncertain else "medium" if clauses else "low"
    source_id = _source_record_id(record)
    source_text = _bounded_source_text(record)
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "candidate_id": f"{pack_id}:candidate:{source_id}",
        "kind": "spell_candidate",
        "content_kind": "spell",
        "name": _text(record.get("name")),
        "spell_id": source_id,
        "source_book": _text(record.get("source_book")),
        "source_record_id": source_id,
        "source_path": _text(record.get("source_relative_path")),
        "source_fingerprint": _source_fingerprint(record),
        "source_evidence": {
            "source_path": _text(record.get("source_relative_path")),
            "source_text": source_text,
        },
        "template_match": {
            "template_id": template.get("template_id") if template else None,
            "template_fingerprint": template.get("template_fingerprint") if template else None,
            "confidence": confidence,
            "matched_shape": list(shape),
        },
        "exact_fields": exact,
        "uncertain_fields": uncertain,
        "missing_fields": sorted(set(missing)),
        "required_review_fields": sorted(
            set(["name", "level", "clauses", "target", "action_economy", *missing])
        ),
        "draft_fields": fields,
        "candidate_clauses": clauses,
        "candidate_status": "generated_candidate",
        "compile_status": "never_full_before_review",
        "runtime_levels": {
            "compile_full": False,
            "runtime_preview_full": False,
            "production_runtime_full": False,
        },
    }


def _feature_candidate(
    record: Mapping[str, Any], catalog: Mapping[str, Any], pack_id: str
) -> dict[str, Any]:
    source_id = _source_record_id(record)
    source_text = _bounded_source_text(record)
    template = _match_template(catalog, "feature", ())
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "candidate_id": f"{pack_id}:candidate:{source_id}",
        "kind": "feature_candidate",
        "content_kind": "feature",
        "name": _text(record.get("name")),
        "feature_id": f"{pack_id}:feature:{source_id}",
        "source_book": _text(record.get("source_book")),
        "source_record_id": source_id,
        "source_path": _text(record.get("source_relative_path")),
        "source_fingerprint": _source_fingerprint(record),
        "source_evidence": {
            "source_path": _text(record.get("source_relative_path")),
            "source_text": source_text,
        },
        "template_match": {
            "template_id": template.get("template_id") if template else None,
            "template_fingerprint": template.get("template_fingerprint") if template else None,
            "confidence": "low",
            "matched_shape": [],
        },
        "exact_fields": {
            key: value
            for key, value in {
                "class_name": record.get("class_name"),
                "level": record.get("level"),
            }.items()
            if value not in (None, "")
        },
        "uncertain_fields": {"operator": "feature_semantics_require_review"},
        "missing_fields": ["typed_clause_mapping", "operator", "targeting", "action_economy"],
        "required_review_fields": [
            "source_name",
            "class_name",
            "level",
            "clauses",
            "operator",
            "targeting",
        ],
        "draft_fields": {"source_text": source_text},
        "candidate_clauses": [],
        "candidate_status": "generated_candidate",
        "compile_status": "never_full_before_review",
        "runtime_levels": {
            "compile_full": False,
            "runtime_preview_full": False,
            "production_runtime_full": False,
        },
    }


def generate_candidates(
    source_root: Path,
    catalog_path: Path,
    *,
    book: str,
    kind: str,
    output: Path,
    limit: int | None = None,
) -> dict[str, Any]:
    catalog = _read_json(catalog_path)
    records = load_records(source_root)
    pack_id = _pack_id_for_book(book)
    selected = [
        record
        for record in records
        if (
            kind == "spell"
            and _is_spell_detail(record)
            or kind == "feature"
            and _is_feature_candidate(record)
        )
        and (
            _text(record.get("source_book")) == book
            or _text(record.get("source_relative_path")).startswith(book + "/")
        )
    ]
    selected = sorted(
        selected,
        key=lambda item: (_text(item.get("source_relative_path")), _text(item.get("name"))),
    )
    if limit is not None:
        selected = selected[:limit]
    if output.exists():
        for path in sorted(output.rglob("*.json"), reverse=True):
            path.unlink()
    output.mkdir(parents=True, exist_ok=True)
    candidates = [
        _spell_candidate(record, catalog, pack_id)
        if kind == "spell"
        else _feature_candidate(record, catalog, pack_id)
        for record in selected
    ]
    paths: list[str] = []
    for candidate in candidates:
        filename = _safe_filename(str(candidate["candidate_id"])) + ".json"
        path = output / filename
        _write_json(path, candidate)
        paths.append(str(path.relative_to(output)))
    report = {
        "schema_version": "content-ir-candidate-generation-1",
        "book": book,
        "kind": kind,
        "source_record_count": len(selected),
        "generated_candidate_count": len(candidates),
        "candidate_paths": paths,
        "candidate_status": "generated_candidate",
        "catalog_fingerprint": catalog.get("catalog_fingerprint"),
        "counts_by_confidence": dict(
            Counter(str(item["template_match"].get("confidence")) for item in candidates)
        ),
        "counts_with_uncertainty": sum(bool(item.get("uncertain_fields")) for item in candidates),
        "report_fingerprint": _fingerprint({"book": book, "kind": kind, "candidate_paths": paths}),
    }
    _write_json(output / "generation-report.json", report)
    return report


def candidate_report(input_dir: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        if path.name == "generation-report.json":
            continue
        try:
            rows.append(_read_json(path))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return {
        "schema_version": "content-ir-candidate-report-1",
        "candidate_count": len(rows),
        "counts_by_kind": dict(Counter(str(row.get("content_kind")) for row in rows)),
        "counts_by_status": dict(Counter(str(row.get("candidate_status")) for row in rows)),
        "counts_by_confidence": dict(
            Counter(str((row.get("template_match") or {}).get("confidence")) for row in rows)
        ),
        "source_fingerprints": sorted(str(row.get("source_fingerprint")) for row in rows),
        "candidate_ids": sorted(str(row.get("candidate_id")) for row in rows),
    }


def validate_review_authority(input_dir: Path, catalog_path: Path) -> dict[str, Any]:
    catalog = _read_json(catalog_path)
    by_id = {str(item.get("template_id")): item for item in catalog.get("templates") or []}
    rows: list[dict[str, Any]] = []
    stale: list[str] = []
    errors: list[dict[str, Any]] = []
    for path in sorted(input_dir.rglob("*.json")):
        if path.name in {"generation-report.json", "review-report.json"}:
            continue
        try:
            row = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            row.get("candidate_status") != "reviewed_candidate"
            and row.get("review_status") != "reviewed"
        ):
            continue
        rows.append(row)
        match = row.get("template_match") or {}
        if not match and row.get("review_status") == "reviewed":
            kind = "spell" if row.get("kind") == "spell" else "feature"
            shape = _spell_shape(row) if kind == "spell" else _feature_shape(row)
            template = _match_template(catalog, kind, shape)
            match = {
                "template_id": template.get("template_id") if template else None,
                "template_fingerprint": template.get("template_fingerprint") if template else None,
            }
        template = by_id.get(str(match.get("template_id")))
        if template is None or template.get("template_fingerprint") != match.get(
            "template_fingerprint"
        ):
            stale.append(str(row.get("candidate_id") or row.get("source_record_id")))
        required = row.get("required_review_fields") or []
        missing = [
            field
            for field in required
            if row.get(field) in (None, "", [], {})
            and field not in (row.get("reviewed_fields") or [])
        ]
        if row.get("review_status") == "reviewed" and missing:
            errors.append(
                {"id": row.get("candidate_id") or row.get("source_record_id"), "missing": missing}
            )
    result = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "reviewed_count": len(rows),
        "stale_count": len(stale),
        "stale_ids": sorted(stale),
        "invalid_count": len(errors),
        "errors": errors,
        "review_gate": "pass" if not stale and not errors else "fail",
        "catalog_fingerprint": catalog.get("catalog_fingerprint"),
    }
    _write_json(input_dir / "review-report.json", result)
    return result


def compile_reviewed_directory(input_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Create a mixed typed-only artifact and send it through the real compiler."""

    from dnd_dm_assistant.application.content_ir_workbench import (
        _manifest_fingerprint,
        compile_artifact_directory,
    )

    if output_dir.exists():
        for path in sorted(output_dir.rglob("*.json"), reverse=True):
            path.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)
    typed_paths: list[str] = []
    source_fingerprints: dict[str, str] = {}
    for path in sorted(input_dir.rglob("*.json")):
        if path.name in {
            "manifest.json",
            "compile-result.json",
            "generation-report.json",
            "review-report.json",
        }:
            continue
        try:
            value = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if value.get("kind") not in {"spell", "feature"}:
            continue
        if value.get("review_status") != "reviewed":
            continue
        relative = Path("typed-ir") / path.relative_to(input_dir)
        destination = output_dir / relative
        _write_json(destination, value)
        typed_paths.append(relative.as_posix())
        source_id = _text(value.get("source_record_id"))
        source_fp = _text(value.get("source_fingerprint"))
        if source_id and source_fp:
            source_fingerprints[source_id] = source_fp
    manifest: dict[str, Any] = {
        "schema_version": "content-ir-workbench-manifest-2",
        "pack_id": None,
        "pack_version": None,
        "source_book": None,
        "namespace": "content.batch-II",
        "ruleset_version": None,
        "source_fingerprints": dict(sorted(source_fingerprints.items())),
        "draft_paths": [],
        "typed_ir_paths": sorted(typed_paths),
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry_version": "content-capabilities-1",
        "production_targets": {
            "database": False,
            "feature_registry": False,
            "spell_registry": False,
            "campaign": False,
            "character": False,
        },
        "replay": {"policy": "same-manifest-fingerprint-is-idempotent"},
    }
    manifest["manifest_fingerprint"] = _manifest_fingerprint(manifest)
    _write_json(output_dir / "manifest.json", manifest)
    result = compile_artifact_directory(output_dir, write_files=True)
    result["reviewed_typed_ir_count"] = len(typed_paths)
    _write_json(output_dir / "reviewed-compile-result.json", result)
    return result
