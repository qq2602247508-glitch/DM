# ruff: noqa: N999
"""Validate and register Round L Speak with Animals production evidence."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from alembic.command import upgrade
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.application.content_ir_production_evidence import (
    authoritative_compile_only_ids,
    load_production_runtime_evidence,
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
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SPELL_ID = "core-phb-2024:spell:d82624a42cf6c33ccec927b8"
AUTHORED = ROOT / (
    "data/content-ir/authored/batch-II/core-phb-2024/spells/"
    "core-phb-2024-spell-d82624a42cf6c33ccec927b8.json"
)
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-L.json"
REPORT = ROOT / "reports/round-L-speak-with-animals-production-2026-08-14.json"
FOCUSED_TEST = "backend/tests/test_round_L_speak_with_animals_runtime.py"
FIXED_NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)

BEHAVIORAL_NODES = (
    "test_round_l_capability_persistence_receipt_and_behavioral_boundaries",
    "test_round_l_replay_is_exact_and_payload_drift_rejected",
    "test_round_l_character_cas_rejects_after_preview",
    "test_round_l_actor_cas_rejects_after_preview",
    "test_round_l_beast_cas_rejects_after_preview",
    "test_round_l_invalid_runtime_contract_rejects",
    "test_speak_with_animals_rejects_source_boundary_drift",
    "test_speak_with_animals_rejects_non_beast_and_stale_cas",
)


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz: object = None) -> datetime:
        return FIXED_NOW if tz is not None else FIXED_NOW.replace(tzinfo=None)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime() -> dict[str, object]:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    if compiled["compile_status"] != "full":
        raise AssertionError(compiled["blockers"])
    return dict(compiled["runtime_spell_definition"])


def _body(scene: dict[str, object], key: str) -> dict[str, object]:
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": 1,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "communication_beast_combatant_id": scene["beast"]["id"],
        "communication_beast_version": scene["beast"]["version"],
        "communication_influence_skill": "persuasion",
        "communication_information_scope": "surroundings_and_monsters",
        "communication_observation_age_hours": 24,
        "idempotency_key": key,
    }


def _isolated_runtime_evidence() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="round-l-") as directory:
        database_url = f"sqlite:///{Path(directory) / 'round-l.db'}"
        prior_url = os.environ.get("DND_DM_DATABASE_URL")
        os.environ["DND_DM_DATABASE_URL"] = database_url
        try:
            upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
            settings = Settings(environment="test", database_url=database_url)
            uuid_values = (uuid.UUID(int=index) for index in range(1, 1000))
            with (
                patch("uuid.uuid4", side_effect=lambda: next(uuid_values)),
                patch(
                    "dnd_dm_assistant.application.content_ir_runtime.datetime",
                    _FrozenDateTime,
                ),
                patch(
                    "dnd_dm_assistant.infrastructure.database.spell_economy_service.datetime",
                    _FrozenDateTime,
                ),
                TestClient(create_app(settings)) as client,
            ):
                campaign = client.post("/api/v1/campaigns", json={"name": "Round L"}).json()
                base = f"/api/v1/campaigns/{campaign['id']}"
                character = client.post(
                    f"{base}/characters",
                    json={
                        "name": "施法者",
                        "level": 5,
                        "hp": 20,
                        "max_hp": 20,
                        "spellcasting": {"slots": {"1": {"current": 2, "max": 2}}},
                    },
                ).json()
                runtime = _runtime()
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
                scene = client.post(f"{base}/scenes", json={"name": "Round L scene"}).json()
                client.post(
                    f"{base}/scenes/{scene['id']}/grid",
                    json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
                )
                combat = client.post(
                    f"{base}/combats", json={"name": "Round L combat", "scene_id": scene["id"]}
                ).json()
                combat_root = f"{base}/combats/{combat['id']}"
                actor = client.post(
                    f"{combat_root}/combatants",
                    json={
                        "display_name": "施法者",
                        "entity_type": "character",
                        "entity_id": character["id"],
                        "initiative": 20,
                        "hp": 20,
                        "max_hp": 20,
                        "snapshot_json": {"grid_position": {"row": 5, "col": 5}},
                    },
                ).json()
                beast = client.post(
                    f"{combat_root}/combatants",
                    json={
                        "display_name": "乌鸦",
                        "entity_type": "monster",
                        "entity_id": "raven",
                        "initiative": 10,
                        "hp": 5,
                        "max_hp": 5,
                        "snapshot_json": {
                            "grid_position": {"row": 5, "col": 6},
                            "creature_type": "beast",
                        },
                    },
                ).json()
                scene_data = {
                    "base": base,
                    "character": character,
                    "known": known,
                    "combat": combat,
                    "actor": actor,
                    "beast": beast,
                }
                body = _body(scene_data, "round-l-validator")
                preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
                if preview.status_code != 200:
                    raise AssertionError(preview.text)
                preview_json = preview.json()
                confirmed = client.post(
                    f"{base}/content-ir/runtime/confirm",
                    json={**body, "preview_token": preview_json["preview_token"]},
                )
                if confirmed.status_code != 200:
                    raise AssertionError(confirmed.text)
                result = confirmed.json()
                replay = client.post(
                    f"{base}/content-ir/runtime/confirm",
                    json={**body, "preview_token": preview_json["preview_token"]},
                )
                if replay.status_code != 200:
                    raise AssertionError(replay.text)
                with Session(client.app.state.database_engine) as session:  # type: ignore[attr-defined]
                    actor_row = session.get(Combatant, actor["id"])
                    operation = session.scalar(
                        select(OperationTransaction).where(
                            OperationTransaction.campaign_id == campaign["id"],
                            OperationTransaction.idempotency_key
                            == "content-ir:round-l-validator:capability",
                        )
                    )
                    if actor_row is None or operation is None:
                        raise AssertionError("isolated runtime persistence lookup failed")
                    persisted_snapshot = dict(actor_row.snapshot_json or {})
                    transaction = {
                        "id": operation.id,
                        "operation_type": operation.operation_type,
                        "idempotency_key": operation.idempotency_key,
                        "status": operation.status,
                        "source": operation.source,
                        "before_snapshot": operation.before_snapshot,
                        "after_snapshot": {
                            key: operation.after_snapshot[key]
                            for key in (
                                "consumer",
                                "runtime_id",
                                "communication_capability_receipt",
                                "communication",
                                "actor_combatant_id",
                                "actor_version_after",
                                "beast_version_after",
                            )
                        },
                    }
                return {
                    "preview": {
                        "preview_token": preview_json["preview_token"],
                        "consumer": preview_json["production_contract"]["consumers"],
                    },
                    "result": {
                            key: result[key]
                            for key in (
                                "consumer",
                                "runtime_id",
                                "communication_capability_receipt",
                            "communication",
                            "actor_combatant_id",
                            "actor_version_after",
                            "beast_version_after",
                            "operation_transaction_id",
                        )
                    },
                    "replay": {
                        "already_applied": replay.json()["already_applied"],
                        "receipt": replay.json()["communication_capability_receipt"],
                        "operation_transaction_id": replay.json()[
                            "operation_transaction_id"
                        ],
                    },
                    "persisted_actor_snapshot": persisted_snapshot,
                    "operation_transaction": transaction,
                }
        finally:
            if prior_url is None:
                os.environ.pop("DND_DM_DATABASE_URL", None)
            else:
                os.environ["DND_DM_DATABASE_URL"] = prior_url


def build() -> dict[str, object]:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    runtime = dict(compiled["runtime_spell_definition"])
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    consumers = resolve_production_consumers(
        content_kind="spell", runtime_schema_version="spell-runtime-1", blocks=blocks
    )
    protected_before = protected_path_fingerprints(ROOT)
    node_results: dict[str, bool] = {}
    node_stdout_sha256: dict[str, str] = {}
    for node in BEHAVIORAL_NODES:
        test = subprocess.run(
            [
                str(ROOT / "backend/.venv/bin/python"),
                "-m",
                "pytest",
                "-q",
                f"{FOCUSED_TEST}::{node}",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        node_results[node] = test.returncode == 0
        node_stdout_sha256[node] = hashlib.sha256(test.stdout.encode()).hexdigest()
    try:
        isolated = _isolated_runtime_evidence()
        isolated_ok = True
    except Exception as exc:  # noqa: BLE001
        isolated = {"error": f"{type(exc).__name__}: {exc}"}
        isolated_ok = False
    checks = {
        "compile_full": compiled["compile_status"] == "full",
        "typed_consumer": [item["consumer_id"] for item in consumers]
        == ["spell.communication.capability.v1"],
        "behavioral_nodes": node_results,
        "preview_confirm_replay": node_results[
            "test_round_l_capability_persistence_receipt_and_behavioral_boundaries"
        ]
        and node_results["test_round_l_replay_is_exact_and_payload_drift_rejected"],
        "character_actor_beast_cas": all(
            node_results[node]
            for node in (
                "test_round_l_character_cas_rejects_after_preview",
                "test_round_l_actor_cas_rejects_after_preview",
                "test_round_l_beast_cas_rejects_after_preview",
            )
        ),
        "invalid_runtime_source_contract": node_results[
            "test_round_l_invalid_runtime_contract_rejects"
        ],
        "invalid_runtime_input_scope": node_results[
            "test_speak_with_animals_rejects_source_boundary_drift"
        ],
        "invalid_non_beast_scope": node_results[
            "test_speak_with_animals_rejects_non_beast_and_stale_cas"
        ],
        "isolated_api_runtime": isolated_ok,
        "actual_receipt_fields": isolated_ok
        and isolated["result"]["communication_capability_receipt"]["duration_value"] == 10
        and isolated["result"]["communication_capability_receipt"]["expires_at"]
        != isolated["result"]["communication_capability_receipt"]["started_at"],
        "actual_persisted_snapshot": isolated_ok
        and bool(isolated["persisted_actor_snapshot"].get("communication_capabilities")),
        "actual_operation_transaction": isolated_ok
        and isolated["operation_transaction"]["operation_type"]
        == "content_ir_communication_capability"
        and isolated["operation_transaction"]["source"] == "combat",
        "actual_replay": isolated_ok
        and isolated["replay"]["already_applied"] is True
        and isolated["replay"]["receipt"]
        == isolated["result"]["communication_capability_receipt"],
        "name_branch_count": 0,
        "formal_database_written": False,
        "formal_registry_written": False,
        "protected_fingerprints_unchanged": protected_before
        == protected_path_fingerprints(ROOT),
    }
    checks["all_required_checks_passed"] = all(
        value if isinstance(value, bool) else all(value.values())
        for value in checks.values()
        if value not in (0, False) and not isinstance(value, dict)
    ) and all(node_results.values()) and isolated_ok
    evidence = {
        "content_id": SPELL_ID,
        "content_kind": "spell",
        "production_runtime_full": checks["all_required_checks_passed"],
        "source": {
            "authored_path": str(AUTHORED.relative_to(ROOT)),
            "source_record_id": authored["source_record_id"],
            "source_fingerprint": authored["source_fingerprint"],
            "source_path": authored["source_path"],
        },
        "typed_clause_ids": [clause["clause_id"] for clause in authored["clauses"]],
        "typed_consumer": "spell.communication.capability.v1",
        "runtime_receipt": isolated.get("result", {}).get(
            "communication_capability_receipt", {}
        ),
        "runtime_result": isolated.get("result", {}),
        "persisted_actor_snapshot": isolated.get("persisted_actor_snapshot", {}),
        "operation_transaction": isolated.get("operation_transaction", {}),
        "replay": isolated.get("replay", {}),
    }
    RESULTS.write_text(
        json.dumps(
            {
                "schema_version": "content-ir-production-runtime-results-L-1",
                "round_id": "round-L",
                "content_kind": "spell",
                "production_runtime_full_ids": [SPELL_ID]
                if checks["all_required_checks_passed"]
                else [],
                "evidence_by_id": {SPELL_ID: evidence},
                "checks": checks,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    migration = build_migration(ROOT)
    project_ids = existing_project_production_ids(ROOT)
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    census = authoritative_compile_only_ids(ROOT)
    counts = {
        "production": len(project_ids),
        "compile_only": len(census - set(loaded)),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    report: dict[str, object] = {
        "schema_version": "round-L-speak-with-animals-production-2",
        "round_id": "round-L",
        "artifact_date": "2026-08-14",
        "evidence_artifact": str(RESULTS.relative_to(ROOT)),
        "evidence_mechanism": "generic load_production_runtime_evidence production-runtime-results*.json loader",
        "source_bound_producer": {
            "authored_path": str(AUTHORED.relative_to(ROOT)),
            "source_record_id": authored["source_record_id"],
            "source_fingerprint": authored["source_fingerprint"],
            "compile_status": compiled["compile_status"],
            "typed_clause_ids": [clause["clause_id"] for clause in authored["clauses"]],
        },
        "runtime_consumers": [str(item["consumer_id"]) for item in consumers],
        "canonical_projection": {
            "counts": counts,
            "speak_with_animals_in_loaded_evidence": SPELL_ID in loaded,
            "speak_with_animals_in_project_production_ids": SPELL_ID in project_ids,
            "compile_only_census_size": len(census),
            "compile_only_after": counts["compile_only"],
            "migration_projection_matches_project_union": migration[
                "current_project_production_full"
            ]
            == len(project_ids),
        },
        "checks": checks
        | {
            "evidence_loader_inclusion": SPELL_ID in loaded,
            "projection_reconciliation": migration["current_project_production_full"]
            == len(project_ids),
        },
        "node_stdout_sha256": node_stdout_sha256,
        "historical_preservation": {
            "round_xliii_report_sha256": _sha(
                ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
            ),
            "expected_round_xliii_report_sha256": "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f",
        },
        "no_push": True,
    }
    report["promotion_decision"] = (
        "promote"
        if checks["all_required_checks_passed"]
        and SPELL_ID in loaded
        and SPELL_ID in project_ids
        else "withdraw"
    )
    report["report_fingerprint"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    result = build()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["promotion_decision"] == "promote" else 1)
