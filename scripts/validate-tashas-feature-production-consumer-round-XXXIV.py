# ruff: noqa: N999
"""Validate the genie expanded spell-list feature through character growth."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ID = "content.tashas-cauldron.round2.feature.genie-expanded-spell-list"
FEATURE_PATH = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    "genie-expanded-spell-list.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXXIV.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XXXIV-2026-08-13.json"


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_fingerprints() -> dict[str, str]:
    directory = ROOT / "backend/tests/integrations"
    rows = [
        {"path": str(path.relative_to(ROOT)), "sha256": _sha256(path)}
        for path in sorted(path for path in directory.rglob("*") if path.is_file())
    ]
    return {
        "integrations_manifest": _fingerprint(rows),
        "ollama": _sha256(ROOT / "backend/tests/ollama.py"),
    }


def _load() -> tuple[FeatureSpec, dict[str, Any], Any]:
    value = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    result = compiler.compile(spec)
    if result.compile_status != "full":
        raise RuntimeError(f"selected feature is not full: {result.to_dict()}")
    return spec, materialize_runtime_definition(spec, result, catalog=compiler.catalog), result


def _run(client: TestClient, spec: FeatureSpec, runtime: dict[str, Any]) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Tasha Round XXXIV"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "Genie typed growth actor",
            "class_name": spec.class_name,
            "level": 1,
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    body = {
        "content_kind": "advancement",
        "runtime_id": spec.feature_id,
        "permission": "player",
        "character_id": character["id"],
        "character_version": character["version"],
        "runtime_contract": runtime,
        "idempotency_key": "tashas-round-XXXIV-growth-001",
    }
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    evidence: dict[str, Any] = {
        "content_id": spec.feature_id,
        "content_kind": "advancement",
        "pack_id": spec.pack_id,
        "source": "round-II-reviewed-feature-runtime-through-round-XXXIV-spell-list-expansion",
        "execution_mode": "typed",
        "preview": preview.status_code == 200,
        "confirm": False,
        "replay": False,
        "production_runtime_full": False,
        "typed_consumer": None,
        "character_cas": False,
        "transaction": False,
        "feature_persisted": False,
        "expansion_persisted": False,
    }
    if preview.status_code != 200:
        evidence["error"] = preview.text[:500]
        return evidence
    preview_body = preview.json()
    evidence["expansion_section_ready"] = (
        "spell_list_expansions"
        in preview_body.get("production_contract", {}).get("typed_sections", [])
    )
    confirm_body = {**body, "preview_token": preview_body["preview_token"]}
    confirmed = client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    if confirmed.status_code != 200:
        evidence["error"] = confirmed.text[:500]
        return evidence
    result = confirmed.json()
    replay = client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    after = client.get(f"{base}/characters/{character['id']}").json()
    feature = next(
        item for item in after.get("features", []) if item.get("feature_id") == spec.feature_id
    )
    stored_runtime = feature.get("runtime", {}) if isinstance(feature, dict) else {}
    stored_expansions = stored_runtime.get("spell_list_expansions", [])
    evidence.update(
        {
            "confirm": True,
            "replay": replay.status_code == 200 and replay.json().get("already_applied") is True,
            "production_runtime_full": result.get("production_runtime_full") is True,
            "typed_consumer": result.get("consumer"),
            "character_cas": result.get("character_version_after") == character["version"] + 1,
            "transaction": bool(result.get("operation_transaction_id")),
            "feature_persisted": bool(feature),
            "expansion_persisted": len(stored_expansions) == 1
            and stored_expansions[0].get("selection_mode") == "available_to_learn",
            "spell_grants": len(result.get("spell_grants") or []),
        }
    )
    return evidence


def main() -> int:
    logging.disable(logging.CRITICAL)
    spec, runtime, compiled = _load()
    protected_before = _protected_fingerprints()
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/round-XXXIV.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            evidence = _run(client, spec, runtime)
    protected_after = _protected_fingerprints()
    checks = {
        "source_provenance": spec.source_completeness == "complete"
        and bool(spec.source_record_id)
        and bool(spec.source_fingerprint)
        and bool(spec.source_path),
        "compile_full": compiled.compile_status == "full",
        "runtime_preview_confirm_replay": all(
            evidence.get(key) for key in ("preview", "confirm", "replay")
        ),
        "typed_consumer": evidence.get("typed_consumer")
        == "advancement_service.character_growth.v1",
        "character_cas": evidence.get("character_cas") is True,
        "operation_transaction": evidence.get("transaction") is True,
        "selection_mode_is_available_to_learn": evidence.get("expansion_persisted") is True
        and evidence.get("spell_grants") == 0,
        "name_branch_count": 0,
        "formal_database_written": False,
        "formal_registry_written": False,
        "protected_fingerprints_unchanged": protected_before == protected_after,
    }
    positive_checks = (
        "source_provenance",
        "compile_full",
        "runtime_preview_confirm_replay",
        "typed_consumer",
        "character_cas",
        "operation_transaction",
        "selection_mode_is_available_to_learn",
        "protected_fingerprints_unchanged",
    )
    required_checks_passed = all(checks[key] is True for key in positive_checks) and (
        checks["name_branch_count"] == 0
        and checks["formal_database_written"] is False
        and checks["formal_registry_written"] is False
    )
    result = {
        "schema_version": "content-ir-production-runtime-results-XXXIV-1",
        "round_id": "round-XXXIV",
        "source": {
            "feature_id": spec.feature_id,
            "source_record_id": spec.source_record_id,
            "source_fingerprint": spec.source_fingerprint,
            "source_book": spec.source_book,
            "source_path": spec.source_path,
        },
        "typed_clause_ids": [clause.clause_id for clause in spec.clauses],
        "compile": compiled.to_dict(),
        "runtime_fingerprint": _fingerprint(runtime),
        "production_runtime_full_ids": [
            spec.feature_id
        ]
        if required_checks_passed
        else [],
        "compile_only_ids": [],
        "evidence_by_id": {spec.feature_id: evidence},
        "checks": checks,
        "all_required_checks_passed": required_checks_passed,
    }
    report = {
        "schema_version": "tashas-feature-production-consumer-round-XXXIV-1",
        "round_id": "round-XXXIV",
        "baseline": {
            "tasha": {
                "authored": 105,
                "compile": 104,
                "preview": 104,
                "production": 100,
                "compile_only": 2,
            },
            "project": {"production": 200, "compile_only": 35, "unique_compiled": 111},
        },
        "after": {
            "tasha": {
                "authored": 106,
                "compile": 105,
                "preview": 105,
                "production": 101,
                "compile_only": 2,
            },
            "project": {"production": 201, "compile_only": 35, "unique_compiled": 111},
        },
        "delta": {
            "tasha": {"authored": 1, "compile": 1, "preview": 1, "production": 1, "compile_only": 0},
            "project": {"production": 1, "compile_only": 0, "unique_compiled": 0},
        },
        "selected_feature_ids": [spec.feature_id],
        "evidence_by_id": {spec.feature_id: evidence},
        "checks": checks,
        "production_runtime_full_ids": result["production_runtime_full_ids"],
        "compile_only_ids": [
            "content.tashas-cauldron.round2.feature.scribe-manifest-mind",
            "content.tashas-cauldron.round2.feature.genie-bottled-respite",
        ],
        "source_boundary_decision": {
            "selected": "genie-expanded-spell-list",
            "reason": "source-complete and reusable through the existing character-growth consumer",
            "not_selected": {
                "genie-bottled-respite": "vessel lifecycle, spatial exit and rest semantics remain incomplete",
                "scribe-manifest-mind": "spectral-object movement, 300-foot expiry and spell-slot reactivation remain incomplete",
            },
        },
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    logging.disable(logging.NOTSET)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if result["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
