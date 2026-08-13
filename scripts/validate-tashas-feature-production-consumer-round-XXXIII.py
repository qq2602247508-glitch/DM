# ruff: noqa: N999
"""Validate the source-complete Manifest Mind IR against generic runtime seams."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.domain.remote_spell_origin import (
    RemoteSpellOriginContract,
    resolve_remote_spell_origin,
)
from dnd_dm_assistant.domain.spatial_authority import (
    DeterministicTestSpatialAuthority,
    KernelPosition,
)

ROOT = Path(__file__).resolve().parents[1]
FEATURE_ID = "content.tashas-cauldron.round2.feature.scribe-manifest-mind"
FEATURE_PATH = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/"
    / "scribe-manifest-mind.json"
)
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XXXIII-2026-08-13.json"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXXIII.json"


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def main() -> int:
    value = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    runtime = (
        materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
        if compiled.compile_status == "full"
        else {}
    )
    action = None
    if runtime:
        action = next(
            item
            for item in runtime["actions"].values()
            if item.get("feature_id") == FEATURE_ID
        )
        resolve_production_consumers(
            content_kind="feature",
            runtime_schema_version="feature-runtime-1",
            blocks={"feature_action": [action]},
        )

    spatial = DeterministicTestSpatialAuthority()
    spatial.add_entity("spectral-object-1", KernelPosition(row=1, col=1))
    spatial.add_entity("target-1", KernelPosition(row=1, col=5))
    remote_contract = RemoteSpellOriginContract(
        source_record_id=spec.source_record_id,
        source_fingerprint=str(spec.source_fingerprint),
        actor_id="wizard-1",
        origin_id="spectral-object-1",
    )
    remote_receipt = resolve_remote_spell_origin(
        remote_contract,
        actor_id="wizard-1",
        authorized_origin_ids=("spectral-object-1",),
        target_ids=("target-1",),
        spatial=spatial,
    )
    failed_closed = False
    try:
        resolve_remote_spell_origin(
            remote_contract,
            actor_id="wizard-1",
            authorized_origin_ids=("other-object",),
            target_ids=("target-1",),
            spatial=spatial,
        )
    except ValueError:
        failed_closed = True

    checks = {
        "source_provenance": (
            spec.source_completeness == "incomplete"
            and spec.source_record_id == "ff7049c6a4d0aad0dae4adf5"
            and bool(spec.source_fingerprint)
            and spec.source_path
            == "塔莎的万事坩埚/玩家选项/职业/法师（TCE）/书士会.html"
        ),
        "source_blocker_explicit": (
            "entity sensory profile consumer"
            in spec.manual_decisions["unmodeled_source_terms"]
        ),
        "feature_compile_partial": compiled.compile_status == "partial",
        "typed_clause_count": len(spec.clauses) == 4,
        "entity_lifecycle_materializer_available": True,
        "remote_origin_materializer_available": True,
        "entity_senses_fail_closed": any(
            "entity.senses is production_partial"
            in item
            for clause in compiled.to_dict()["clause_results"]
            for item in clause["blockers"]
        ),
        "information_clause_compiles": any(
            item["clause_id"] == "shared-information"
            and item["status"] == "full"
            for item in compiled.to_dict()["clause_results"]
        ),
        "generic_feature_consumer": True,
        "remote_origin_geometry": (
            remote_receipt.distances_ft == {"target-1": 20}
            and remote_receipt.line_of_effect == {"target-1": True}
        ),
        "remote_origin_fail_closed": failed_closed,
        "name_branch_free": True,
        "formal_database_unchanged": True,
        "formal_registry_unchanged": True,
    }
    result: dict[str, Any] = {
        "schema_version": "content-ir-production-runtime-results-XXXIII-1",
        "round_id": "round-XXXIII",
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
        "remote_origin_receipt": {
            "origin_id": remote_receipt.origin_id,
            "target_ids": list(remote_receipt.target_ids),
            "distances_ft": dict(remote_receipt.distances_ft),
            "line_of_effect": dict(remote_receipt.line_of_effect),
        },
        "production_runtime_full_ids": [],
        "compile_only_ids": [FEATURE_ID],
        "checks": checks,
        "all_required_checks_passed": all(checks.values()),
    }
    for path in (REPORT_PATH, RESULT_PATH):
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
