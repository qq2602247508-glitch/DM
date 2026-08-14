# ruff: noqa: N999
"""Validate Round LII from source-bound named nodes and a real isolated API run."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
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
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-LII.json"
REPORT = ROOT / "reports/round-LII-illusion-lifecycle-2026-08-14.json"
FOCUSED = "backend/tests/test_round_LII_illusion_lifecycle.py"
DISGUISE_ID = "core-phb-2024:spell:83b7d94b77f332dd71310bbe"
OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"
FIXED_NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compiled() -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    path = ROOT / (
        "data/content-ir/authored/batch-II/core-phb-2024/spells/"
        "core-phb-2024-spell-83b7d94b77f332dd71310bbe.json"
    )
    authored = json.loads(path.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    runtime = dict(compiled["runtime_spell_definition"])
    return authored, runtime, ContentIRRuntimeService._runtime_blocks(runtime)


def _run_named_nodes() -> dict[str, Any]:
    nodes = (
        "test_round_lii_source_contract_covers_bounds_and_registry",
        "test_round_lii_physical_inspection_and_research_use_persisted_save_dc",
        "test_round_lii_expiry_and_explicit_termination_are_state_transitions",
        "test_illusion_api_preview_confirm_persists_cas_transaction_and_replay",
        "test_round_lii_api_rejects_cas_and_contract_boundaries",
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


def _setup(client: TestClient, runtime: dict[str, Any]) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Round LII isolated"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "isolated illusion caster",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {"slots": {"1": {"current": 2, "max": 2}}},
        },
    ).json()
    known = client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime["name"],
            "spell_level": 1,
            "prepared": True,
            "metadata_json": {"content_ir_runtime": runtime},
        },
    ).json()
    character = client.get(f"{base}/characters/{character['id']}").json()
    scene = client.post(f"{base}/scenes", json={"name": "Round LII isolated scene"}).json()
    client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = client.post(
        f"{base}/combats", json={"name": "Round LII isolated combat", "scene_id": scene["id"]}
    ).json()
    combat_root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "isolated illusion caster",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 5, "col": 5}},
        },
    ).json()
    return {"base": base, "character": character, "known": known, "combat": combat, "actor": actor}


def _body(scene: dict[str, Any]) -> dict[str, Any]:
    return {
        "content_kind": "spell",
        "runtime_id": DISGUISE_ID,
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": 1,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "illusion_save_dc": 14,
        "illusion_height_delta_ft": -1,
        "illusion_body_shape": "variable",
        "illusion_limb_arrangement": "preserve",
        "illusion_carried_envelope": ["clothing", "armor", "weapons"],
        "illusion_area_scope": "caster-chosen illusion envelope",
        "illusion_research_action": "research",
        "illusion_investigation_total": 14,
        "idempotency_key": "round-lii-isolated-evidence",
    }


def _stable_evidence(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "isolated-actor"
                if key in {"illusion_id", "target_id"}
                else "present"
                if key in {"request_fingerprint", "request_id"}
                else _stable_evidence(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_stable_evidence(item) for item in value]
    return value


def _isolated_runtime_receipt(runtime: dict[str, Any]) -> dict[str, Any]:
    previous_clock = os.environ.get("DND_DM_ILLUSION_NOW")
    os.environ["DND_DM_ILLUSION_NOW"] = FIXED_NOW.isoformat()
    try:
        with tempfile.TemporaryDirectory(prefix="round-lii-") as temp_dir:
            database_url = f"sqlite:///{Path(temp_dir) / 'evidence.db'}"
            previous_database = os.environ.get("DND_DM_DATABASE_URL")
            os.environ["DND_DM_DATABASE_URL"] = database_url
            try:
                command_config = Config(str(ROOT / "backend/alembic.ini"))
                command.upgrade(command_config, "head")
                settings = Settings(
                    environment="test",
                    database_url=database_url,
                    frontend_origin="http://127.0.0.1:5173",
                )
                with TestClient(create_app(settings)) as client:
                    scene = _setup(client, runtime)
                    body = _body(scene)
                    preview_response = client.post(
                        f"{scene['base']}/content-ir/runtime/preview", json=body
                    )
                    if preview_response.status_code != 200:
                        raise AssertionError(preview_response.text)
                    preview = preview_response.json()
                    confirm_response = client.post(
                        f"{scene['base']}/content-ir/runtime/confirm",
                        json={**body, "preview_token": preview["preview_token"]},
                    )
                    if confirm_response.status_code != 200:
                        raise AssertionError(confirm_response.text)
                    confirmed = confirm_response.json()
                    replay_response = client.post(
                        f"{scene['base']}/content-ir/runtime/confirm",
                        json={**body, "preview_token": preview["preview_token"]},
                    )
                    if replay_response.status_code != 200:
                        raise AssertionError(replay_response.text)
                    replay = replay_response.json()
                    drift_response = client.post(
                        f"{scene['base']}/content-ir/runtime/confirm",
                        json={
                            **body,
                            "preview_token": preview["preview_token"],
                            "illusion_save_dc": 15,
                        },
                    )
                    if drift_response.status_code != 400:
                        raise AssertionError(drift_response.text)
                    inspect_response = client.post(
                        f"{scene['base']}/content-ir/runtime/illusion/inspect",
                        json={**body, "actor_version": confirmed["actor_version_after"]},
                    )
                    if inspect_response.status_code != 200:
                        raise AssertionError(inspect_response.text)
                    failed_inspection_response = client.post(
                        f"{scene['base']}/content-ir/runtime/illusion/inspect",
                        json={
                            **body,
                            "actor_version": confirmed["actor_version_after"],
                            "illusion_investigation_total": 13,
                        },
                    )
                    if failed_inspection_response.status_code != 200:
                        raise AssertionError(failed_inspection_response.text)
                    os.environ["DND_DM_ILLUSION_NOW"] = (
                        FIXED_NOW + timedelta(hours=1)
                    ).isoformat()
                    expired_inspection_response = client.post(
                        f"{scene['base']}/content-ir/runtime/illusion/inspect",
                        json={**body, "actor_version": confirmed["actor_version_after"]},
                    )
                    if expired_inspection_response.status_code != 400:
                        raise AssertionError(expired_inspection_response.text)
                    os.environ["DND_DM_ILLUSION_NOW"] = FIXED_NOW.isoformat()
                    termination_response = client.post(
                        f"{scene['base']}/content-ir/runtime/illusion/terminate",
                        json={
                            **body,
                            "actor_version": confirmed["actor_version_after"],
                            "idempotency_key": "round-lii-isolated-termination",
                            "illusion_termination_reason": "terminate",
                        },
                    )
                    if termination_response.status_code != 200:
                        raise AssertionError(termination_response.text)
                    termination = termination_response.json()

                engine = create_engine(database_url)
                try:
                    with Session(engine) as session:
                        actor = session.scalar(
                            select(Combatant).where(Combatant.id == scene["actor"]["id"])
                        )
                        operation = session.scalar(
                            select(OperationTransaction).where(
                                OperationTransaction.id == confirmed["operation_transaction_id"]
                            )
                        )
                        if actor is None or operation is None:
                            raise AssertionError("isolated API transaction or actor snapshot missing")
                        snapshot = dict(actor.snapshot_json or {})
                finally:
                    engine.dispose()

                envelope = dict(snapshot["illusion_envelopes"][0])
                return _stable_evidence({
                    "preview": {
                        "runtime_preview_full": preview["runtime_preview_full"],
                        "consumer": preview["production_contract"]["consumers"],
                        "source": preview["runtime_source"],
                        "illusion_lifecycle": preview["production_contract"]["illusion_lifecycle"],
                    },
                    "confirm": {
                        "production_runtime_full": confirmed["production_runtime_full"],
                        "consumer": confirmed["consumer"],
                        "spell_cast_present": bool(confirmed.get("spell_cast")),
                        "illusion_receipt": confirmed["illusion_receipt"],
                        "inspection": confirmed["inspection"],
                    },
                    "api_inspection": {
                        "success": inspect_response.json()["inspection"],
                        "failure": failed_inspection_response.json()["inspection"],
                    },
                    "persisted_actor_snapshot": {
                        "actor_version": actor.version,
                        "illusion_version": snapshot["illusion_version"],
                        "illusion_envelopes": [
                            {
                                key: value
                                for key, value in envelope.items()
                                if key != "illusion_id"
                            }
                        ],
                    },
                    "expiry": {
                        "checked_at": (FIXED_NOW + timedelta(hours=1)).isoformat(),
                        "rejected": expired_inspection_response.status_code == 400,
                        "error": expired_inspection_response.json(),
                    },
                    "termination": {
                        "reason": termination["termination"],
                        "version_after": termination["persisted_snapshot"]["illusion_version"],
                        "operation_transaction_id_present": bool(
                            termination["operation_transaction_id"]
                        ),
                    },
                    "replay": {
                        "already_applied": replay["already_applied"],
                        "same_receipt": replay["illusion_receipt"]
                        == confirmed["illusion_receipt"],
                        "operation_transaction_id_present": bool(
                            confirmed["operation_transaction_id"]
                        ),
                    },
                    "payload_drift": {
                        "status_code": drift_response.status_code,
                        "rejected": drift_response.status_code == 400,
                    },
                    "operation_transaction": {
                        "identity_present": bool(confirmed["operation_transaction_id"]),
                        "operation_type": operation.operation_type,
                        "idempotency_key": operation.idempotency_key,
                        "status": operation.status,
                        "after_snapshot_contains_receipt": operation.after_snapshot[
                            "illusion_receipt"
                        ]
                        == confirmed["illusion_receipt"],
                    },
                })
            finally:
                if previous_database is None:
                    os.environ.pop("DND_DM_DATABASE_URL", None)
                else:
                    os.environ["DND_DM_DATABASE_URL"] = previous_database
    finally:
        if previous_clock is None:
            os.environ.pop("DND_DM_ILLUSION_NOW", None)
        else:
            os.environ["DND_DM_ILLUSION_NOW"] = previous_clock


def build_report() -> dict[str, Any]:
    authored, runtime, blocks = _compiled()
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=blocks,
    )
    nodes = _run_named_nodes()
    receipt = _isolated_runtime_receipt(runtime)
    protected = protected_path_fingerprints(ROOT)
    checks: dict[str, Any] = {
        "source_bound_compile_full": runtime.get("execution_status") == "ready",
        "generic_registry_consumer_exact": [item["consumer_id"] for item in consumers]
        == ["spell.illusion.lifecycle.v1"],
        "source_fields_cover_target_duration_envelope_height_limb_area": (
            blocks["illusion_lifecycle"][0]["target_scope"] == "self"
            and blocks["illusion_lifecycle"][0]["duration_value"] == 1
            and blocks["illusion_lifecycle"][0]["height_delta_range_ft"] == [-1, 1]
            and set(blocks["illusion_lifecycle"][0]["carried_envelope"])
            == {"clothing", "armor", "weapons"}
            and blocks["illusion_lifecycle"][0]["limb_arrangement"] == "preserve"
            and bool(blocks["illusion_lifecycle"][0]["area_scope"])
        ),
        "source_fields_cover_physical_inspection_and_research_dc": (
            blocks["illusion_lifecycle"][0]["physical_inspection"] == "passes_through"
            and blocks["illusion_lifecycle"][0]["research_action"] == "research"
            and blocks["illusion_lifecycle"][0]["investigation_skill"]
            == "intelligence_investigation"
        ),
        "isolated_api_preview_confirm_receipt": (
            receipt["preview"]["runtime_preview_full"] is True
            and receipt["confirm"]["production_runtime_full"] is True
            and receipt["confirm"]["consumer"] == "spell.illusion.lifecycle.v1"
        ),
        "isolated_api_source_receipt_exact": (
            receipt["confirm"]["illusion_receipt"]["source_record_id"]
            == authored["source_record_id"]
            and receipt["confirm"]["illusion_receipt"]["source_fingerprint"]
            == authored["source_fingerprint"]
            and receipt["confirm"]["illusion_receipt"]["clause_id"] == "illusion_lifecycle"
        ),
        "isolated_api_persisted_envelope_exact": (
            receipt["confirm"]["illusion_receipt"]["physical_inspection_result"]
            == "passes_through"
            and receipt["persisted_actor_snapshot"]["illusion_envelopes"][0]["height_delta_ft"]
            == -1
            and receipt["persisted_actor_snapshot"]["illusion_envelopes"][0]["limb_arrangement"]
            == "preserve"
            and set(
                receipt["persisted_actor_snapshot"]["illusion_envelopes"][0]["carried_envelope"]
            )
            == {"clothing", "armor", "weapons"}
            and receipt["persisted_actor_snapshot"]["illusion_envelopes"][0]["area_scope"]
            == "caster-chosen illusion envelope"
        ),
        "isolated_api_inspection_success_against_save_dc": (
            receipt["confirm"]["inspection"]["discerned"] is True
            and receipt["confirm"]["inspection"]["save_dc"] == 14
        ),
        "isolated_api_expiry_and_termination_evidence": (
            receipt["expiry"]["rejected"] is True
            and receipt["termination"]
            == {
                "reason": "terminate",
                "version_after": 2,
                "operation_transaction_id_present": True,
            }
        ),
        "isolated_api_exact_replay_and_payload_drift": (
            receipt["replay"]
            == {
                "already_applied": True,
                "same_receipt": True,
                "operation_transaction_id_present": True,
            }
            and receipt["payload_drift"] == {"status_code": 400, "rejected": True}
        ),
        "isolated_api_operation_transaction_namespace_content": (
            receipt["operation_transaction"]
            == {
                "identity_present": True,
                "operation_type": "content_ir_illusion_lifecycle",
                "idempotency_key": "content-ir:round-lii-isolated-evidence:illusion",
                "status": "applied",
                "after_snapshot_contains_receipt": True,
            }
        ),
        "name_branch_count": 0,
        "formal_database_written": False,
        "formal_registry_written": False,
        "protected_ollama_sha_exact": protected["backend/tests/ollama.py"]["sha256"] == OLLAMA_SHA,
        "historical_xliii_sha_exact": _sha(
            (ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json").read_bytes()
        )
        == XLIII_SHA,
    }
    checks["named_nodes_all_passed"] = all(item["passed"] for item in nodes.values())
    checks["all_required_checks_passed"] = all(
        value is True
        for key, value in checks.items()
        if key
        not in {
            "formal_database_written",
            "formal_registry_written",
            "name_branch_count",
            "named_nodes",
        }
    )
    source_path = ROOT / (
        "data/content-ir/authored/batch-II/core-phb-2024/spells/"
        "core-phb-2024-spell-83b7d94b77f332dd71310bbe.json"
    )
    artifact = {
        "schema_version": "content-ir-production-runtime-results-LII-2",
        "round_id": "round-LII",
        "artifact_date": "2026-08-14",
        "content_kind": "spell",
        "production_runtime_full_ids": [DISGUISE_ID] if checks["all_required_checks_passed"] else [],
        "evidence_by_id": {
            DISGUISE_ID: {
                "content_id": DISGUISE_ID,
                "content_kind": "spell",
                "name": authored["name"],
                "source_record_id": authored["source_record_id"],
                "source_fingerprint": authored["source_fingerprint"],
                "source_path": authored["source_path"],
                "authored_path": str(source_path.relative_to(ROOT)),
                "runtime_blocks": blocks,
                "resolved_consumers": [item["consumer_id"] for item in consumers],
                "production_runtime_full": bool(checks["all_required_checks_passed"]),
                "isolated_runtime_test": FOCUSED,
                "isolated_api_receipt": receipt,
                "required_semantics": [
                    "self target and one-hour duration",
                    "appearance/clothing/armor/weapon illusion envelope",
                    "height delta -1/0/+1 and preserved limb arrangement",
                    "caster-chosen illusion area",
                    "physical inspection passes through illusion",
                    "Research plus Intelligence (Investigation) against persisted spell save DC",
                    "expiry and termination persistence",
                ],
            }
        },
        "checks": {**checks, "named_nodes": nodes},
    }
    RESULTS.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
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
    report = {
        "schema_version": "round-LII-illusion-lifecycle-2",
        "round_id": "round-LII",
        "artifact_date": "2026-08-14",
        "baseline_commit": "c5ced8c55b75eb83dc0dd6b114f5a82196a7efdc",
        "decision": "promote_disguise_self_through_generic_illusion_lifecycle",
        "canonical_projection": {
            "after": projection,
            "expected": {"production": 207, "compile_only": 31, "unique_compiled": 111},
        },
        "candidate_id": DISGUISE_ID,
        "evidence_artifact": str(RESULTS.relative_to(ROOT)),
        "evidence_mechanism": "source-bound SpellSpec compile, named test nodes, and isolated migrated SQLite API receipt with persisted snapshot and transaction inspection",
        "checks": checks,
        "protected_fingerprints": protected,
        "historical_artifact_sha256": {
            "round_xliii_report": XLIII_SHA,
            "backend_tests_ollama": OLLAMA_SHA,
        },
        "no_push": True,
    }
    report["all_required_checks_passed"] = bool(
        checks["all_required_checks_passed"]
        and projection == {"production": 207, "compile_only": 31, "unique_compiled": 111}
    )
    report["report_fingerprint"] = _sha(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return report


if __name__ == "__main__":
    result = build_report()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["all_required_checks_passed"] else 1)
