"""Non-executable, source-backed Clause IR corpus for migration planning.

This is deliberately *not* :mod:`feature_ir`.  Feature IR is an authored,
executable contract.  The clause corpus is the intermediate review surface
between a located source description and such a contract.  Keeping the two
separate prevents the batch planner from promoting prose/keyword matches into
runtime behaviour.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

CLAUSE_CORPUS_SCHEMA_VERSION = "feature-clause-corpus-1"
REVIEWED_CLAUSE_SCHEMA_VERSION = "feature-clause-reviewed-1"

# These are review declarations, not executable rules.  They describe which
# contract fields still need an authored/runtime decision for a prose anchor.
_ANCHOR_REVIEW_FIELDS: dict[str, tuple[str, ...]] = {
    "action_economy": ("activation", "action_economy"),
    "action_trigger": ("trigger", "trigger_producer"),
    "advancement_choice": ("required_inputs", "effect_operator"),
    "aura_range": ("target_policy", "range", "visibility", "line_of_sight"),
    "choice_branch": ("required_inputs", "effect_operator", "effect_parameters"),
    "damage_healing": ("effect_operator", "effect_parameters", "required_consumer"),
    "hit_rider": ("trigger", "trigger_producer", "effect_operator", "required_consumer"),
    "movement": ("effect_operator", "effect_parameters", "required_consumer"),
    "narrative_language": ("effect_operator", "required_consumer"),
    "pre_damage_defense": ("trigger", "trigger_producer", "effect_operator", "required_consumer"),
    "resource_binding": ("resource_key", "resource_operation", "resource_amount_or_formula"),
    "resource_recovery": ("resource_key", "resource_recovery"),
    "roll_intervention": ("trigger", "trigger_producer", "effect_operator", "required_consumer"),
    "save_dc": ("saving_throw_ability", "dc_source", "effect_operator", "required_consumer"),
    "spell_modification": ("effect_operator", "effect_parameters", "required_consumer"),
    "spell_selection": ("required_inputs", "effect_operator", "effect_parameters"),
    "spellcasting": ("trigger", "effect_operator", "required_consumer"),
    "status_lifecycle": ("effect_operator", "effect_parameters", "duration", "expiry"),
    "summon_companion": ("effect_operator", "effect_parameters", "required_consumer"),
    "target_range_save": ("target_policy", "target_count", "range", "visibility", "line_of_sight"),
    "world_state": ("effect_operator", "effect_parameters", "required_consumer"),
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, value: object) -> str:
    return f"{prefix}:{hashlib.sha256(_canonical(value).encode()).hexdigest()[:20]}"


def stable_feature_id(row: Mapping[str, Any]) -> str:
    return _stable_id(
        "class-feature",
        {
            "scope": row.get("scope"),
            "class_name": row.get("class_name"),
            "subclass_name": row.get("subclass_name"),
            "level": row.get("level"),
            "feature_name": row.get("feature_name"),
            "source_record_id": row.get("source_record_id"),
        },
    )


def _source_completeness(source_parse: str) -> str:
    located = {"description_located", "description_reused"}
    return "complete" if source_parse in located else "incomplete"


def _segments(description: str) -> tuple[str, ...]:
    """Split source prose on author-provided paragraphs/list boundaries only.

    This has no semantic effect classification.  A segment is a review unit,
    not an inferred game rule; this is why it is safe to run over the entire
    corpus deterministically.
    """

    text = re.sub(r"\r\n?", "\n", description).strip()
    if not text:
        return ()
    parts = [
        part.strip()
        for part in re.split(r"\n\s*\n|^\s*-\s+", text, flags=re.MULTILINE)
        if part.strip()
    ]
    return tuple(parts or [text])


@dataclass(frozen=True)
class FeatureClauseRecord:
    feature_id: str
    clause_id: str
    feature_name: str
    parent_source_clause_id: str
    class_name: str | None
    subclass_name: str | None
    level: int | None
    source_record_id: str | None
    source_parse: str
    source_trust: str
    source_completeness: str
    source_excerpt: str
    source_segment_index: int
    trigger: str | None
    conditions: tuple[str, ...]
    activation: str | None
    action_economy: str | None
    target_policy: str | None
    visibility_range: str | None
    required_inputs: tuple[str, ...]
    resource_key: str | None
    resource_operation: str | None
    resource_amount_formula: str | None
    frequency: str | None
    duration: str | None
    expiry: str | None
    effect_operator: str | None
    effect_parameters: dict[str, Any] | None
    required_producer: str | None
    required_consumer: str | None
    persisted_state: str | None
    cas_requirements: str | None
    idempotency_requirements: str | None
    materializer: str | None
    validator: str | None
    production_evidence: tuple[str, ...]
    clause_status: str
    blocker_category: str
    blocker_details: str
    analysis_anchors: tuple[str, ...]
    source_fingerprint: str
    review_status: str
    reviewed_contract: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("conditions", "required_inputs", "production_evidence", "analysis_anchors"):
            value[key] = list(value[key])
        value.update(value.pop("reviewed_contract"))
        return value


def _reviewed_contract(
    *,
    row: Mapping[str, Any],
    feature_name: str,
    feature_id: str,
    clause_id: str,
    excerpt: str,
    source_fingerprint: str,
    anchors: tuple[str, ...],
    completeness: str,
    source_incomplete: bool,
) -> dict[str, Any]:
    """Return a fully shaped review record with explicit unknowns.

    Unknown operational values stay null.  The missing field list is the
    reviewed conclusion, so an empty value is never silently interpreted as a
    runtime rule.
    """

    missing: set[str] = set()
    for anchor in anchors:
        missing.update(_ANCHOR_REVIEW_FIELDS.get(anchor, ()))
    if not anchors:
        missing.update(
            {
                "trigger",
                "target_policy",
                "effect_operator",
                "effect_parameters",
                "required_producer",
                "required_consumer",
            }
        )
    if source_incomplete:
        missing.add("source_excerpt")
    reviewed_fields = (
        "feature_id",
        "clause_id",
        "parent_source_clause_id",
        "feature_name",
        "class_name",
        "subclass_name",
        "level",
        "source_record_id",
        "source_excerpt",
        "source_fingerprint",
        "source_parse",
        "source_trust",
        "source_completeness",
        "analysis_anchors",
    )
    blocker = "source_incomplete" if source_incomplete else "manual_boundary"
    return {
        "review_schema_version": REVIEWED_CLAUSE_SCHEMA_VERSION,
        "feature_name": feature_name,
        "parent_source_clause_id": clause_id,
        "source_fingerprint": source_fingerprint,
        "review_status": "reviewed_typed",
        "actor_policy": None,
        "target_count": None,
        "range": None,
        "visibility": None,
        "line_of_sight": None,
        "saving_throw_ability": None,
        "dc_source": None,
        "success_effect": None,
        "failure_effect": None,
        "ui_requirements": [],
        "implementation_risk": "requires_explicit_contract_review",
        "reviewed_fields": list(reviewed_fields),
        "missing_fields": sorted(missing),
        "review_anchor_labels": list(anchors),
        "review_notes": (
            "source is complete but operational semantics remain an explicit manual boundary"
            if completeness == "complete"
            else "source excerpt is incomplete and cannot be safely interpreted"
        ),
        "review_blocker_category": blocker,
        "review_blocker_details": (
            "missing operational fields: " + ", ".join(sorted(missing))
        ),
        "row_runtime_sections": list(row.get("runtime_sections") or ()),
    }


def compile_clause_corpus(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Build deterministic source review records for partial audit rows.

    Located source text is retained as a non-executable record, which replaces
    the unhelpful batch-preview diagnosis ``missing_typed_spec`` with the
    precise state ``missing_semantic_contract``.  Fields that require human
    rule interpretation remain ``None`` rather than being guessed.
    """

    records: list[FeatureClauseRecord] = []
    feature_ids: set[str] = set()
    source_parse_counts: dict[str, int] = {}
    for row in sorted(rows, key=lambda item: stable_feature_id(item)):
        if row.get("runtime_status") != "partial":
            continue
        feature_id = stable_feature_id(row)
        feature_ids.add(feature_id)
        source_parse = str(row.get("source_parse") or "missing")
        source_parse_counts[source_parse] = source_parse_counts.get(source_parse, 0) + 1
        completeness = _source_completeness(source_parse)
        description = str(row.get("source_description") or "")
        segments = _segments(description) if completeness == "complete" else ()
        if not segments:
            segments = ("",)
        anchors = tuple(sorted(str(item) for item in row.get("detected_blocks") or ()))
        for index, excerpt in enumerate(segments):
            source_incomplete = completeness != "complete"
            clause_id = _stable_id(
                "source-clause",
                {"feature_id": feature_id, "index": index, "excerpt": excerpt},
            )
            source_fingerprint = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
            record = FeatureClauseRecord(
                feature_id=feature_id,
                clause_id=clause_id,
                feature_name=str(row.get("feature_name") or ""),
                parent_source_clause_id=clause_id,
                class_name=row.get("class_name"),
                subclass_name=row.get("subclass_name"),
                level=row.get("level"),
                source_record_id=row.get("source_record_id"),
                source_parse=source_parse,
                source_trust="unstructured_source",
                source_completeness=completeness,
                source_excerpt=excerpt,
                source_segment_index=index,
                trigger=None,
                conditions=(),
                activation=None,
                action_economy=None,
                target_policy=None,
                visibility_range=None,
                required_inputs=(),
                resource_key=None,
                resource_operation=None,
                resource_amount_formula=None,
                frequency=None,
                duration=None,
                expiry=None,
                effect_operator=None,
                effect_parameters=None,
                required_producer=None,
                required_consumer=None,
                persisted_state=None,
                cas_requirements=None,
                idempotency_requirements=None,
                materializer=None,
                validator=None,
                production_evidence=(),
                clause_status="source_incomplete" if source_incomplete else "manual_boundary",
                blocker_category=(
                    "source_incomplete"
                    if source_incomplete
                    else "manual_boundary"
                ),
                blocker_details=(
                    "audit row has no complete located source description"
                    if source_incomplete
                    else (
                        "source is located; trigger/target/effect contract requires "
                        "explicit human review"
                    )
                ),
                analysis_anchors=anchors,
                source_fingerprint=source_fingerprint,
                review_status="reviewed_typed",
                reviewed_contract=_reviewed_contract(
                    row=row,
                    feature_name=str(row.get("feature_name") or ""),
                    feature_id=feature_id,
                    clause_id=clause_id,
                    excerpt=excerpt,
                    source_fingerprint=source_fingerprint,
                    anchors=anchors,
                    completeness=completeness,
                    source_incomplete=source_incomplete,
                ),
            )
            records.append(record)
    records.sort(key=lambda item: (item.feature_id, item.source_segment_index, item.clause_id))
    return {
        "schema_version": CLAUSE_CORPUS_SCHEMA_VERSION,
        "feature_count": len(feature_ids),
        "clause_count": len(records),
        "source_parse_counts": dict(sorted(source_parse_counts.items())),
        "source_complete_feature_count": sum(
            1 for record in {item.feature_id: item for item in records}.values()
            if record.source_completeness == "complete"
        ),
        "source_incomplete_feature_count": sum(
            1 for record in {item.feature_id: item for item in records}.values()
            if record.source_completeness != "complete"
        ),
        "executable_clause_count": 0,
        "reviewed_clause_count": len(records),
        "typed_clause_count": len(records),
        "manual_boundary_clause_count": sum(
            record.blocker_category == "manual_boundary" for record in records
        ),
        "source_incomplete_clause_count": sum(
            record.blocker_category == "source_incomplete" for record in records
        ),
        "features": sorted(feature_ids),
        "clauses": [record.to_dict() for record in records],
    }
