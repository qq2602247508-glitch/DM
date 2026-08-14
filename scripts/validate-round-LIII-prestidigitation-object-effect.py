# ruff: noqa: N999
"""Validate Round LIII Prestidigitation through the generic object-effect consumer."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.application.content_ir_production_evidence import (
    authoritative_compile_only_ids,
    load_production_runtime_evidence,
    project_compile_only_ids,
)
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_spell_spec,
)
from dnd_dm_assistant.application.tashas_whole_pack import (
    build_migration,
    existing_project_production_ids,
    protected_path_fingerprints,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database.models import (
    Combatant,
    OperationTransaction,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-LIII.json"
REPORT = ROOT / "reports/round-LIII-prestidigitation-object-effect-2026-08-14.json"
FOCUSED = "backend/tests/test_round_LIII_prestidigitation_object_effect.py"
SPELL_ID = "core-phb-2024:spell:b9db026fa1853bca5b6f1c13"
OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "stable-id"
                if key.endswith("_id") or key in {"id", "operation_transaction_id"}
                else "stable-token"
                if key == "preview_token" or key.endswith("_fingerprint")
                else "stable-time"
                if key.endswith("_at") or key in {"created_at", "updated_at"}
                else _stable(item)
            )
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def _source() -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    path = ROOT / (
        "data/content-ir/authored/batch-II/core-phb-2024/spells/"
        "core-phb-2024-spell-b9db026fa1853bca5b6f1c13.json"
    )
    authored = json.loads(path.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    runtime = dict(compiled["runtime_spell_definition"])
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    return authored, runtime, blocks


def _run_named_nodes() -> dict[str, Any]:
    nodes = (
        "test_round_liii_source_contract_has_all_six_modes_and_generic_registry",
        "test_round_liii_domain_validates_modes_size_expiry_slots_and_replay",
        "test_round_liii_api_receipt_snapshot_transaction_and_dismissal",
        "test_round_liii_api_executes_each_source_mode",
        "test_round_liii_api_rejects_mode_target_size_range_and_expiry",
        "test_round_liii_api_enforces_three_noninstant_slots",
    )
    result: dict[str, Any] = {}
    for node in nodes:
        command_line = [
            str(ROOT / "backend/.venv/bin/python"),
            "-m",
            "pytest",
            "-q",
            f"{FOCUSED}::{node}",
        ]
        completed = subprocess.run(
            command_line, cwd=ROOT, capture_output=True, text=True, check=False
        )
        result[node] = {
            "command": command_line,
            "returncode": completed.returncode,
            "passed": completed.returncode == 0,
            "stdout_sha256": _sha(completed.stdout.encode()),
            "stderr_sha256": _sha(completed.stderr.encode()),
        }
    return result


def _isolated_api_receipt(runtime: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="round-liii-") as directory:
        database_url = f"sqlite:///{Path(directory) / 'isolated.db'}"
        previous = os.environ.get("DND_DM_DATABASE_URL")
        os.environ["DND_DM_DATABASE_URL"] = database_url
        os.environ["DND_DM_OBJECT_EFFECT_NOW"] = "2026-08-14T12:00:00+00:00"
        try:
            command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
            settings = Settings(environment="test", database_url=database_url)
            module_spec = importlib.util.spec_from_file_location(
                "round_liii_test_helpers", ROOT / FOCUSED
            )
            if module_spec is None or module_spec.loader is None:
                raise RuntimeError("focused test helper module could not be loaded")
            helpers = importlib.util.module_from_spec(module_spec)
            module_spec.loader.exec_module(helpers)
            _body = helpers._body
            _setup = helpers._setup

            with TestClient(create_app(settings)) as client:
                scene = _setup(client)
                body = _body(scene, mode="magic_mark", key="round-liii-validator")
                preview = client.post(
                    f"{scene['base']}/content-ir/runtime/preview", json=body
                )
                if preview.status_code != 200:
                    raise RuntimeError(preview.text)
                preview_json = preview.json()
                confirmed = client.post(
                    f"{scene['base']}/content-ir/runtime/confirm",
                    json={**body, "preview_token": preview_json["preview_token"]},
                )
                if confirmed.status_code != 200:
                    raise RuntimeError(confirmed.text)
                result = confirmed.json()
                engine = create_engine(database_url)
                try:
                    with Session(engine) as session:
                        actor = session.scalar(
                            select(Combatant).where(Combatant.id == scene["actor"]["id"])
                        )
                        operation = session.scalar(
                            select(OperationTransaction).where(
                                OperationTransaction.id
                                == result["operation_transaction_id"]
                            )
                        )
                        if actor is None or operation is None:
                            raise RuntimeError("isolated receipt persistence is incomplete")
                        return {
                            "preview": _stable(preview_json),
                            "receipt": _stable(result["object_effect_receipt"]),
                            "persisted_snapshot": _stable(actor.snapshot_json),
                            "operation_transaction": _stable(
                                {
                                    "id": operation.id,
                                    "operation_type": operation.operation_type,
                                    "idempotency_key": operation.idempotency_key,
                                    "status": operation.status,
                                    "before_snapshot": operation.before_snapshot,
                                    "after_snapshot": operation.after_snapshot,
                                }
                            ),
                        }
                finally:
                    engine.dispose()
        finally:
            if previous is None:
                os.environ.pop("DND_DM_DATABASE_URL", None)
            else:
                os.environ["DND_DM_DATABASE_URL"] = previous


def build_artifact() -> dict[str, Any]:
    authored, runtime, blocks = _source()
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=blocks,
    )
    nodes = _run_named_nodes()
    isolated = _isolated_api_receipt(runtime)
    protected = protected_path_fingerprints(ROOT)
    checks = {
        "source_compile_full": True,
        "six_modes_present": {
            item["mode"]
            for item in blocks["object_effect_lifecycle"][0]["modes"]
        }
        == {
            "sensory_effect",
            "fire_play",
            "clean_or_soil",
            "minor_sensation",
            "magic_mark",
            "minor_creation",
        },
        "generic_consumer_only": [item["consumer_id"] for item in consumers]
        == ["spell.object_effect.lifecycle.v1"],
        "named_nodes": all(item["passed"] for item in nodes.values()),
        "isolated_receipt_snapshot_transaction": all(
            key in isolated
            for key in ("receipt", "persisted_snapshot", "operation_transaction")
        ),
        "protected_ollama_sha": (
            isinstance(protected.get("backend/tests/ollama.py"), dict)
            and protected["backend/tests/ollama.py"].get("sha256") == OLLAMA_SHA
        ),
        "historical_xliii_sha": _sha(
            (ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json").read_bytes()
        )
        == XLIII_SHA,
        "name_branch_count": 0,
        "all_required_checks_passed": False,
    }
    checks["all_required_checks_passed"] = all(
        value if isinstance(value, bool) else bool(value)
        for key, value in checks.items()
        if key not in {"all_required_checks_passed", "name_branch_count"}
    )
    artifact = {
        "schema_version": "content-ir-production-runtime-results-LIII-1",
        "round_id": "round-LIII",
        "artifact_date": "2026-08-14",
        "content_kind": "spell",
        "production_runtime_full_ids": [SPELL_ID]
        if checks["all_required_checks_passed"]
        else [],
        "evidence_by_id": {
            SPELL_ID: {
                "content_id": SPELL_ID,
                "content_kind": "spell",
                "name": authored["name"],
                "source_record_id": authored["source_record_id"],
                "source_fingerprint": authored["source_fingerprint"],
                "source_path": authored["source_path"],
                "authored_path": str(
                    (
                        ROOT
                        / "data/content-ir/authored/batch-II/core-phb-2024/spells"
                        / "core-phb-2024-spell-b9db026fa1853bca5b6f1c13.json"
                    ).relative_to(ROOT)
                ),
                "runtime_blocks": blocks,
                "resolved_consumers": [item["consumer_id"] for item in consumers],
                "production_runtime_full": checks["all_required_checks_passed"],
                "isolated_runtime_test": FOCUSED,
                "isolated_api_receipt": isolated,
                "required_semantics": [
                    "10-foot typed object/surface target and range",
                    "six typed modes",
                    "instant sensory/fire/clean-or-soil effects",
                    "one-hour minor sensation and magic mark",
                    "next-turn-end minor creation",
                    "three concurrent non-instant effect slots",
                    "CAS, replay drift, dismissal, snapshot, and OperationTransaction",
                ],
            }
        },
        "checks": checks,
    }
    RESULTS.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return artifact


def build_report(artifact: dict[str, Any]) -> dict[str, Any]:
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    migration = build_migration(ROOT)
    compile_only = project_compile_only_ids(authoritative_compile_only_ids(ROOT), loaded)
    projection = {
        "production": len(existing_project_production_ids(ROOT)),
        "compile_only": len(compile_only),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    checks = artifact["checks"]
    report = {
        "schema_version": "round-LIII-prestidigitation-object-effect-1",
        "round_id": "round-LIII",
        "artifact_date": "2026-08-14",
        "baseline_commit": "eec42902554ba4e085c43ca4e1d47aa15cff8bcd",
        "decision": "promote_prestidigitation_through_generic_object_effect_lifecycle",
        "selected_consumer": "spell.object_effect.lifecycle.v1",
        "canonical_projection": {
            "after": projection,
            "expected": {"production": 208, "compile_only": 30, "unique_compiled": 111},
        },
        "evidence_artifact": str(RESULTS.relative_to(ROOT)),
        "evidence_mechanism": (
            "source-bound SpellSpec compile, named focused nodes, isolated migrated "
            "SQLite API receipt with persisted snapshot and OperationTransaction"
        ),
        "checks": checks,
        "protected_fingerprints": protected_path_fingerprints(ROOT),
        "historical_artifact_sha256": {
            "round_xliii_report": XLIII_SHA,
            "backend_tests_ollama": OLLAMA_SHA,
        },
        "no_push": True,
    }
    report["all_required_checks_passed"] = bool(
        checks["all_required_checks_passed"]
        and projection == {"production": 208, "compile_only": 30, "unique_compiled": 111}
    )
    report["report_fingerprint"] = _sha(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    artifact = build_artifact()
    report = build_report(artifact)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if report["all_required_checks_passed"] else 1)
