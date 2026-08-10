"""Deterministic completion-unlock analysis for the Clause IR review corpus.

The planner intentionally distinguishes a repeated *word* from a repeated
capability contract.  A capability only receives a completion-unlock count
when every clause has a fully typed, field-equivalent missing contract; an
unreviewed source clause is reported, but never treated as a build target.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

UNLOCK_SCHEMA_VERSION = "feature-capability-unlock-1"
_CONTRACT_FIELDS = (
    "effect_operator",
    "trigger",
    "activation",
    "action_economy",
    "target_policy",
    "visibility_range",
    "required_producer",
    "required_consumer",
    "persisted_state",
    "cas_requirements",
    "idempotency_requirements",
    "materializer",
    "validator",
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _contract_key(clause: Mapping[str, Any]) -> str | None:
    """Return an exact contract ID only when no operational field is guessed."""

    if clause.get("clause_status") == "production_closed":
        return None
    payload = {field: clause.get(field) for field in _CONTRACT_FIELDS}
    if any(value is None or value == "" for value in payload.values()):
        return None
    payload["conditions"] = list(clause.get("conditions") or ())
    payload["required_inputs"] = list(clause.get("required_inputs") or ())
    payload["resource_key"] = clause.get("resource_key")
    payload["resource_operation"] = clause.get("resource_operation")
    payload["frequency"] = clause.get("frequency")
    payload["duration"] = clause.get("duration")
    payload["expiry"] = clause.get("expiry")
    payload["effect_parameters"] = clause.get("effect_parameters")
    return "capability:" + hashlib.sha256(_canonical(payload).encode()).hexdigest()[:20]


def plan_capability_unlocks(corpus: Mapping[str, Any]) -> dict[str, Any]:
    clauses = [item for item in corpus.get("clauses", []) if isinstance(item, Mapping)]
    by_feature: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for clause in clauses:
        by_feature[str(clause["feature_id"])].append(clause)

    by_capability: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    untyped: list[Mapping[str, Any]] = []
    for clause in clauses:
        key = _contract_key(clause)
        if key is None:
            untyped.append(clause)
        else:
            by_capability[key].append(clause)

    rows: list[dict[str, Any]] = []
    for capability_id, members in by_capability.items():
        member_ids = {str(item["feature_id"]) for item in members}
        completion_ids: list[str] = []
        remaining: dict[str, list[str]] = {}
        for feature_id in sorted(member_ids):
            keys = {
                _contract_key(item)
                for item in by_feature[feature_id]
                if item.get("clause_status") != "production_closed"
            }
            keys.discard(None)
            has_untyped = any(
                item.get("clause_status") != "production_closed" and _contract_key(item) is None
                for item in by_feature[feature_id]
            )
            if keys == {capability_id} and not has_untyped:
                completion_ids.append(feature_id)
            else:
                remaining[feature_id] = sorted(str(key) for key in keys if key != capability_id) + (
                    ["untyped_clause_requires_semantic_review"] if has_untyped else []
                )
        exemplar = members[0]
        rows.append(
            {
                "capability_id": capability_id,
                "normalized_missing_contract": {
                    field: exemplar.get(field) for field in _CONTRACT_FIELDS
                },
                "occurrence_count": len(members),
                "completion_unlock_count": len(completion_ids),
                "blocked_feature_ids": sorted(member_ids),
                "feature_ids_that_would_become_full": completion_ids,
                "clauses_already_production_closed": 0,
                "remaining_blockers_after_hypothetical_completion": remaining,
                "required_producer": exemplar.get("required_producer"),
                "required_consumer": exemplar.get("required_consumer"),
                "persistence": exemplar.get("persisted_state"),
                "cas": exemplar.get("cas_requirements"),
                "idempotency": exemplar.get("idempotency_requirements"),
                "ui_requirement": bool(exemplar.get("required_inputs")),
                "implementation_risk": "unknown_until_reviewed",
                "estimated_files": [],
                "required_tests": [],
                "existing_consumer_reused": False,
                "new_bounded_platform_required": True,
                "field_equivalence_proof": "canonical equality across all required contract fields",
            }
        )
    rows.sort(
        key=lambda item: (
            -item["completion_unlock_count"],
            -item["occurrence_count"],
            item["capability_id"],
        )
    )

    # A separate row makes the high frequency of unreviewed source visible but
    # gives it zero unlock credit: semantic review is not an executable platform.
    if untyped:
        rows.append(
            {
                "capability_id": "review:missing_semantic_contract",
                "normalized_missing_contract": None,
                "occurrence_count": len(untyped),
                "completion_unlock_count": 0,
                "blocked_feature_ids": sorted({str(item["feature_id"]) for item in untyped}),
                "feature_ids_that_would_become_full": [],
                "clauses_already_production_closed": 0,
                "remaining_blockers_after_hypothetical_completion": {},
                "required_producer": None,
                "required_consumer": None,
                "persistence": None,
                "cas": None,
                "idempotency": None,
                "ui_requirement": None,
                "implementation_risk": "not_an_implementation_capability",
                "estimated_files": [],
                "required_tests": ["human semantic clause review"],
                "existing_consumer_reused": False,
                "new_bounded_platform_required": False,
                "field_equivalence_proof": (
                    "not eligible: at least one required operational field is unknown"
                ),
            }
        )
    eligible = [item for item in rows if item["completion_unlock_count"] >= 8]
    return {
        "schema_version": UNLOCK_SCHEMA_VERSION,
        "feature_count": len(by_feature),
        "clause_count": len(clauses),
        "typed_missing_contract_count": sum(len(items) for items in by_capability.values()),
        "untyped_clause_count": len(untyped),
        "ranking": rows,
        "eligible_capability_ids": [item["capability_id"] for item in eligible],
        "qualified_cluster_found": bool(eligible),
        "selection_rule": (
            "completion_unlock_count >= 8; occurrence_count alone is never sufficient"
        ),
    }
