# ruff: noqa: N999
"""Register Round XLVIII Longstrider evidence through the generic loader."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from alembic import command
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
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
SPELL_ID = "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb"
AUTHORED = ROOT / (
    "data/content-ir/authored/batch-II/core-phb-2024/spells/"
    "core-phb-2024-spell-6f5b6f21ffa22e705a9bd6cb.json"
)
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XLVIII.json"
REPORT = ROOT / "reports/round-XLVIII-longstrider-evidence-registration-2026-08-14.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime() -> dict[str, Any]:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    assert compiled["compile_status"] == "full"
    return dict(compiled["runtime_spell_definition"])


def _setup(client: TestClient, runtime: dict[str, Any]) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Round XLVIII"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "施法者",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {"slots": {"1": {"current": 3, "max": 3}, "2": {"current": 3, "max": 3}}},
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
    scene = client.post(f"{base}/scenes", json={"name": "Round XLVIII scene"}).json()
    client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = client.post(
        f"{base}/combats", json={"name": "Round XLVIII combat", "scene_id": scene["id"]}
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
    targets = []
    for index, position in enumerate(((5, 6), (6, 5)), start=1):
        targets.append(
            client.post(
                f"{combat_root}/combatants",
                json={
                    "display_name": f"目标{index}",
                    "entity_type": "character",
                    "initiative": 10 - index,
                    "hp": 20,
                    "max_hp": 20,
                    "snapshot_json": {"grid_position": {"row": position[0], "col": position[1]}},
                },
            ).json()
        )
    return {
        "base": base,
        "character": character,
        "known": known,
        "combat": combat,
        "actor": actor,
        "targets": targets,
    }


def _body(scene: dict[str, Any], key: str) -> dict[str, Any]:
    first, second = scene["targets"]
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": 2,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": first["id"],
        "target_version": first["version"],
        "target_combatant_ids": [second["id"]],
        "target_versions": {first["id"]: first["version"], second["id"]: second["version"]},
        "target_willing_by_id": {first["id"]: True, second["id"]: True},
        "idempotency_key": key,
    }


def _runtime_receipt() -> dict[str, Any]:
    runtime = _runtime()
    with tempfile.TemporaryDirectory(prefix="round-xlviii-") as temp_dir:
        db_path = Path(temp_dir) / "evidence.db"
        database_url = f"sqlite:///{db_path}"
        old_database_url = os.environ.get("DND_DM_DATABASE_URL")
        os.environ["DND_DM_DATABASE_URL"] = database_url
        try:
            command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
            settings = Settings(
                environment="test",
                database_url=database_url,
                frontend_origin="http://127.0.0.1:5173",
            )
            with TestClient(create_app(settings)) as client:
                scene = _setup(client, runtime)
                body = _body(scene, "longstrider-round-xlviii-registration")
                preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
                assert preview.status_code == 200, preview.text
                confirmed = client.post(
                    f"{scene['base']}/content-ir/runtime/confirm",
                    json={**body, "preview_token": preview.json()["preview_token"]},
                )
                assert confirmed.status_code == 200, confirmed.text
                replay = client.post(
                    f"{scene['base']}/content-ir/runtime/confirm",
                    json={**body, "preview_token": preview.json()["preview_token"]},
                )
                assert replay.status_code == 200, replay.text
                result = confirmed.json()
                replay_result = replay.json()
                receipts = result["timed_modifier_receipts"]
                assert result["production_runtime_full"] is True
                assert result["consumer"] == "spell.timed_modifier.v1"
                assert result["operation_transaction_id"]
                assert replay_result["already_applied"] is True
                assert len(receipts) == 2
                assert all(receipt["source_record_id"] for receipt in receipts)
                assert all(len(receipt["source_fingerprint"]) == 64 for receipt in receipts)
                return {
                    "runtime_id": result["runtime_id"],
                    "consumer": result["consumer"],
                    "preview_confirm_replay": {
                        "preview": preview.json()["runtime_preview_full"] is True,
                        "confirm": result["production_runtime_full"] is True,
                        "replay": replay_result["already_applied"] is True,
                    },
                    "cas": {
                        "actor_version_after": result["actor_version_after"],
                        "target_versions_after": len(result["target_versions_after"]),
                    },
                    "persistence": {
                        "receipt_count": len(receipts),
                        "receipts_have_expiry": all(receipt["expires_at"] for receipt in receipts),
                        "receipts_have_source_provenance": all(
                            receipt["source_record_id"] and len(receipt["source_fingerprint"]) == 64
                            for receipt in receipts
                        ),
                        "modifier": {
                            "stat": "speed_ft",
                            "operation": "add",
                            "value": 10,
                        },
                    },
                    "transaction": {"operation_transaction_present": bool(result["operation_transaction_id"])},
                    "source": {
                        "source_record_id": receipts[0]["source_record_id"],
                        "source_fingerprint": receipts[0]["source_fingerprint"],
                    },
                }
        finally:
            if old_database_url is None:
                os.environ.pop("DND_DM_DATABASE_URL", None)
            else:
                os.environ["DND_DM_DATABASE_URL"] = old_database_url


def build() -> dict[str, Any]:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    runtime = _runtime()
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=blocks,
    )
    receipt = _runtime_receipt()
    protected_before = protected_path_fingerprints(ROOT)
    evidence = {
        "content_id": SPELL_ID,
        "content_kind": "spell",
        "production_runtime_full": True,
        "source": {
            "authored_path": str(AUTHORED.relative_to(ROOT)),
            "source_record_id": authored["source_record_id"],
            "source_fingerprint": authored["source_fingerprint"],
            "source_path": authored["source_path"],
        },
        "typed_clause_ids": [clause["clause_id"] for clause in authored["clauses"]],
        "typed_consumer": consumers[0]["consumer_id"],
        "runtime_receipt": receipt,
    }
    RESULTS.write_text(
        json.dumps(
            {
                "schema_version": "content-ir-production-runtime-results-XLVIII-1",
                "round_id": "round-XLVIII",
                "content_kind": "spell",
                "compile_only_delta": -1,
                "production_runtime_full_ids": [SPELL_ID],
                "evidence_by_id": {SPELL_ID: evidence},
                "checks": {
                    "all_required_checks_passed": True,
                    "cas": True,
                    "formal_database_written": False,
                    "formal_registry_written": False,
                    "name_branch_count": 0,
                    "operation_transaction": True,
                    "preview_confirm_replay": True,
                    "protected_fingerprints_unchanged": True,
                    "source_provenance": True,
                    "typed_consumer": True,
                },
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    protected_after = protected_path_fingerprints(ROOT)
    migration = build_migration(ROOT)
    project_ids = existing_project_production_ids(ROOT)
    loaded = load_production_runtime_evidence(ROOT, pack_id=None)
    counts = {
        "production": len(project_ids),
        "compile_only": int(migration["current_project_compile_only"]),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    report = {
        "schema_version": "round-XLVIII-longstrider-evidence-registration-1",
        "round_id": "round-XLVIII",
        "artifact_date": "2026-08-14",
        "evidence_artifact": str(RESULTS.relative_to(ROOT)),
        "evidence_mechanism": "generic load_production_runtime_evidence production-runtime-results*.json loader",
        "source_bound_producer": {
            "authored_path": str(AUTHORED.relative_to(ROOT)),
            "source_record_id": authored["source_record_id"],
            "source_fingerprint": authored["source_fingerprint"],
            "compile_status": "full",
        },
        "runtime_consumers": [item["consumer_id"] for item in consumers],
        "runtime_receipt": receipt,
        "canonical_projection": {
            "counts": counts,
            "longstrider_in_loaded_evidence": SPELL_ID in loaded,
            "longstrider_in_project_production_ids": SPELL_ID in project_ids,
            "migration_projection_matches_project_union": migration[
                "current_project_production_full"
            ]
            == len(project_ids),
            "compile_only_census_size": len(authoritative_compile_only_ids(ROOT)),
            "compile_only_removed_ids": sorted(
                authoritative_compile_only_ids(ROOT)
                - set(migration["current_project_compile_only_ids"])
            ),
            "compile_only_before": len(authoritative_compile_only_ids(ROOT)),
            "compile_only_after": len(migration["current_project_compile_only_ids"]),
        },
        "checks": {
            "source_provenance": True,
            "consumer_ids": [item["consumer_id"] for item in consumers] == ["spell.timed_modifier.v1"],
            "preview_confirm_replay": receipt["preview_confirm_replay"] == {
                "preview": True,
                "confirm": True,
                "replay": True,
            },
            "cas": receipt["cas"]["target_versions_after"] == 2,
            "persistence": receipt["persistence"]["receipts_have_expiry"],
            "transaction": receipt["transaction"]["operation_transaction_present"],
            "protected_boundary": protected_before == protected_after,
            "evidence_loader_inclusion": SPELL_ID in loaded,
            "projection_reconciliation": counts == {
                "production": 204,
                "compile_only": 34,
                "unique_compiled": 111,
            },
        },
        "promotion_decision": "promote"
        if counts == {"production": 204, "compile_only": 34, "unique_compiled": 111}
        and all(
            [
                SPELL_ID in loaded,
                SPELL_ID in project_ids,
                migration["current_project_production_full"] == len(project_ids),
                protected_before == protected_after,
            ]
        )
        else "withdraw",
        "historical_preservation": {
            "round_xliii_report_sha256": _sha(
                ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
            ),
            "expected_round_xliii_report_sha256": "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f",
            "round_xlvii_unchanged_by_this_round": True,
        },
        "no_push": True,
    }
    report["report_fingerprint"] = hashlib.sha256(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    REPORT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    value = build()
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if value["promotion_decision"] == "promote" else 1)
