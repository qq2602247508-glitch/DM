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

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("conditions", "required_inputs", "production_evidence", "analysis_anchors"):
            value[key] = list(value[key])
        return value


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
            record = FeatureClauseRecord(
                feature_id=feature_id,
                clause_id=_stable_id(
                    "source-clause",
                    {"feature_id": feature_id, "index": index, "excerpt": excerpt},
                ),
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
                clause_status="source_incomplete" if source_incomplete else "production_partial",
                blocker_category=(
                    "source_incomplete"
                    if source_incomplete
                    else "missing_semantic_contract"
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
        "features": sorted(feature_ids),
        "clauses": [record.to_dict() for record in records],
    }
