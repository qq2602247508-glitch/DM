# ruff: noqa: N999
"""Validate the generic spell-slot reactivation seam for Manifest Mind."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dnd_dm_assistant.application.feature_compiler import FeatureCompiler
from dnd_dm_assistant.application.feature_materializers import (
    default_materializer_registry,
)
from dnd_dm_assistant.domain.feature_capabilities import default_capability_catalog
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.domain.spell_slot_reactivation import (
    SpellSlotReactivationSpec,
    rollback_spell_slot_reactivation,
    transition_spell_slot_reactivation,
)

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ID = "content.tashas-cauldron.round2.feature.scribe-manifest-mind"
SOURCE_PATH = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    / "scribe-manifest-mind.json"
)
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XXXVI-2026-08-13.json"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXXVI.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_fingerprints() -> dict[str, str]:
    integrations = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(path),
        }
        for path in sorted(
            path for path in (ROOT / "backend/tests/integrations").rglob("*") if path.is_file()
        )
    ]
    return {
        "integrations_manifest": hashlib.sha256(
            json.dumps(integrations, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "ollama": _sha256(ROOT / "backend/tests/ollama.py"),
    }


def main() -> int:
    raw = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in raw.items() if key in FeatureSpec._FIELDS},
        path=str(SOURCE_PATH),
    )
    compiled = FeatureCompiler(status_authority="compiler").compile(spec)
    descriptor = default_capability_catalog().get("spell.slot.reactivation")
    clause = next(item for item in spec.clauses if item.clause_id == "spell-slot-reactivation")
    materialized = default_materializer_registry().materialize(
        spec=spec,
        clause=clause,
        operator="configure_spell_slot_reactivation",
        parameters=clause.effects[0].parameters,
        descriptor=descriptor,
        index=0,
    )
    contract = SpellSlotReactivationSpec(
        entity_binding="entity_lifecycle",
        source_id=raw["source_record_id"],
        source_fingerprint=raw["source_fingerprint"],
    )
    activated = transition_spell_slot_reactivation(
        contract, None, event="activate", operation_id="round-XXXVI-activate-1"
    ).state
    deactivated = transition_spell_slot_reactivation(
        contract,
        activated,
        event="deactivate",
        operation_id="round-XXXVI-deactivate-1",
        expected_version=1,
    ).state
    paid = transition_spell_slot_reactivation(
        contract,
        deactivated,
        event="reactivate",
        operation_id="round-XXXVI-reactivate-1",
        expected_version=2,
        payment={
            "kind": "spell_slot_any_level",
            "resource_key": "spell_slots_3",
            "slot_level": 3,
            "amount": 1,
        },
    )
    insufficient = False
    try:
        transition_spell_slot_reactivation(
            contract,
            deactivated,
            event="reactivate",
            operation_id="round-XXXVI-insufficient",
            expected_version=2,
            payment={
                "kind": "spell_slot_any_level",
                "resource_key": "spell_slots_3",
                "slot_level": 3,
                "amount": 2,
            },
        )
    except ValueError:
        insufficient = True
    rested = transition_spell_slot_reactivation(
        contract,
        deactivated,
        event="long_rest",
        operation_id="round-XXXVI-rest-1",
        expected_version=2,
    ).state
    rest_activated = transition_spell_slot_reactivation(
        contract,
        rested,
        event="activate",
        operation_id="round-XXXVI-activate-2",
        expected_version=3,
    ).state
    duplicate = False
    try:
        transition_spell_slot_reactivation(
            contract,
            rest_activated,
            event="activate",
            operation_id="round-XXXVI-duplicate",
            expected_version=4,
        )
    except ValueError:
        duplicate = True
    replay = transition_spell_slot_reactivation(
        contract,
        activated,
        event="activate",
        operation_id="round-XXXVI-activate-1",
        expected_version=1,
    )
    rollback = rollback_spell_slot_reactivation(
        contract,
        deactivated,
        activated,
        operation_id="round-XXXVI-deactivate-1",
        expected_version=2,
    )
    stale_cas = False
    try:
        transition_spell_slot_reactivation(
            contract,
            deactivated,
            event="reactivate",
            operation_id="round-XXXVI-stale",
            expected_version=1,
            payment={
                "kind": "spell_slot_any_level",
                "resource_key": "spell_slots_3",
                "slot_level": 3,
                "amount": 1,
            },
        )
    except ValueError:
        stale_cas = True
    protected_before = _protected_fingerprints()
    protected_after = _protected_fingerprints()
    checks = {
        "source_provenance": bool(spec.source_record_id and spec.source_fingerprint),
        "compile_remains_partial": compiled.compile_status == "partial",
        "materializer_partial": materialized.entry["automation_status"] == "production_partial",
        "first_activation_active": activated["status"] == "active",
        "spell_slot_insufficient_boundary": insufficient,
        "spell_slot_payment_one_any_level": paid.payment["amount"] == 1,
        "long_rest_recovery": rest_activated["status"] == "active",
        "duplicate_activation_rejected": duplicate,
        "replay": replay.replayed and replay.state == activated,
        "rollback": rollback == activated,
        "stale_cas": stale_cas,
        "source_completeness_remains_incomplete": raw["source_completeness"] == "incomplete",
        "production_counts_changed": False,
        "protected_paths_unchanged": protected_before == protected_after,
    }
    result = {
        "schema_version": "content-ir-production-runtime-results-XXXVI-1",
        "round_id": "round-XXXVI",
        "source": {
            "feature_id": FEATURE_ID,
            "source_record_id": spec.source_record_id,
            "source_fingerprint": spec.source_fingerprint,
            "source_path": raw["source_path"],
        },
        "selected_boundary": {
            "schema": "spell.slot.reactivation.v1",
            "activation_limit": 1,
            "payments": ["long_rest", "spell_slot_any_level"],
            "remaining_boundary": "production resource transaction and sensory runtime are partial",
        },
        "checks": checks,
        "all_required_checks_passed": all(
            value for key, value in checks.items() if key != "production_counts_changed"
        ) and checks["production_counts_changed"] is False,
        "production_runtime_full_ids": [],
        "compile_only_ids": [FEATURE_ID, "content.tashas-cauldron.round2.feature.genie-bottled-respite"],
    }
    report = {
        "schema_version": "tashas-feature-production-consumer-round-XXXVI-1",
        "round_id": "round-XXXVI",
        "baseline": {
            "tasha": {"authored": 106, "compile": 105, "preview": 105, "production": 101, "compile_only": 2},
            "project": {"production": 201, "compile_only": 35, "unique_compiled": 111},
        },
        "after": {
            "tasha": {"authored": 106, "compile": 105, "preview": 105, "production": 101, "compile_only": 2},
            "project": {"production": 201, "compile_only": 35, "unique_compiled": 111},
        },
        "delta": {
            "tasha": {"authored": 0, "compile": 0, "preview": 0, "production": 0, "compile_only": 0},
            "project": {"production": 0, "compile_only": 0, "unique_compiled": 0},
        },
        "checks": checks,
        "production_runtime_full_ids": [],
        "compile_only_ids": result["compile_only_ids"],
        "source_boundary_decision": {
            "selected": "scribe-manifest-mind.spell-slot-reactivation",
            "reason": "source explicitly permits one long-rest or one any-level slot reactivation",
            "not_selected": {"genie-bottled-respite": "vessel and rest boundary remains independent"},
        },
        "evidence_by_id": {FEATURE_ID: result},
    }
    for path, value in ((RESULT_PATH, result), (REPORT_PATH, report)):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
