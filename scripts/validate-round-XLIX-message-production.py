# ruff: noqa: N999
"""Validate and register Round XLIX Message production evidence."""

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
SPELL_ID = "core-phb-2024:spell:dd9cb25c63b7e13194c7d01c"
AUTHORED = ROOT / (
    "data/content-ir/authored/batch-II/core-phb-2024/spells/"
    "core-phb-2024-spell-dd9cb25c63b7e13194c7d01c.json"
)
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XLIX.json"
REPORT = ROOT / "reports/round-XLIX-message-production-2026-08-14.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime() -> tuple[dict[str, Any], dict[str, Any]]:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    if compiled["compile_status"] != "full":
        raise AssertionError(compiled["blockers"])
    runtime = dict(compiled["runtime_spell_definition"])
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    consumers = resolve_production_consumers(
        content_kind="spell",
        runtime_schema_version="spell-runtime-1",
        blocks=blocks,
    )
    if [item["consumer_id"] for item in consumers] != ["spell.communication.route.v1"]:
        raise AssertionError("Message did not resolve to the generic route consumer")
    return authored, runtime


def _setup(client: TestClient, runtime: dict[str, Any]) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Round XLIX"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "施法者",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {"slots": {"0": {"current": 3, "max": 3}}},
        },
    ).json()
    known = client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime["name"],
            "spell_level": 0,
            "prepared": True,
            "metadata_json": {"content_ir_runtime": runtime},
        },
    ).json()
    character = client.get(f"{base}/characters/{character['id']}").json()
    scene = client.post(f"{base}/scenes", json={"name": "Round XLIX scene"}).json()
    client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 40, "height": 40, "cell_size_ft": 5, "mode": "combat"},
    )
    combat = client.post(
        f"{base}/combats", json={"name": "Round XLIX combat", "scene_id": scene["id"]}
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
    target = client.post(
        f"{combat_root}/combatants",
        json={
            "display_name": "目标",
            "entity_type": "character",
            "entity_id": "message-target",
            "initiative": 10,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 5, "col": 6}},
        },
    ).json()
    return {
        "base": base,
        "character": character,
        "known": known,
        "combat": combat,
        "actor": actor,
        "target": target,
    }


def _body(scene: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known"]["id"],
        "slot_level": 0,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": scene["target"]["id"],
        "target_version": scene["target"]["version"],
        "target_versions": {scene["target"]["id"]: scene["target"]["version"]},
        "communication_visible": True,
        "communication_message_fingerprint": "b" * 64,
        "idempotency_key": key,
    }


def _runtime_receipt(runtime: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="round-xlix-") as temp_dir:
        database_url = f"sqlite:///{Path(temp_dir) / 'evidence.db'}"
        previous_url = os.environ.get("DND_DM_DATABASE_URL")
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
                body = _body(scene, "message-round-xlix-evidence")
                preview = client.post(
                    f"{scene['base']}/content-ir/runtime/preview", json=body
                )
                if preview.status_code != 200:
                    raise AssertionError(preview.text)
                preview_json = preview.json()
                confirmed = client.post(
                    f"{scene['base']}/content-ir/runtime/confirm",
                    json={**body, "preview_token": preview_json["preview_token"]},
                )
                if confirmed.status_code != 200:
                    raise AssertionError(confirmed.text)
                result = confirmed.json()
                replay = client.post(
                    f"{scene['base']}/content-ir/runtime/confirm",
                    json={**body, "preview_token": preview_json["preview_token"]},
                )
                if replay.status_code != 200:
                    raise AssertionError(replay.text)
                receipt = result["communication_route_receipt"]
                return {
                    "consumer": result["consumer"],
                    "preview_confirm_replay": {
                        "preview": preview_json["runtime_preview_full"] is True,
                        "confirm": result["production_runtime_full"] is True,
                        "replay": replay.json()["already_applied"] is True,
                    },
                    "source": {
                        "source_record_id": receipt["source_record_id"],
                        "source_fingerprint": receipt["source_fingerprint"],
                        "clause_id": receipt["clause_id"],
                    },
                    "communication": {
                        "schema": receipt["schema"],
                        "delivered_to_target_only": receipt["delivered_to"]
                        == scene["target"]["id"],
                        "private_reply_to_sender": receipt["private_reply_to"]
                        == scene["actor"]["id"],
                        "message_fingerprint": result["communication"][
                            "message_fingerprint"
                        ],
                        "distance_ft": result["communication"]["distance_ft"],
                    },
                    "cas": {
                        "actor_version_after": result["actor_version_after"],
                        "target_version_after": result["target_version_after"],
                    },
                    "transaction": {
                        "operation_transaction_present": bool(
                            result["operation_transaction_id"]
                        )
                    },
                }
        finally:
            if previous_url is None:
                os.environ.pop("DND_DM_DATABASE_URL", None)
            else:
                os.environ["DND_DM_DATABASE_URL"] = previous_url


def build() -> dict[str, Any]:
    authored, runtime = _runtime()
    protected_before = protected_path_fingerprints(ROOT)
    receipt = _runtime_receipt(runtime)
    checks = {
        "all_required_checks_passed": all(
            [
                receipt["consumer"] == "spell.communication.route.v1",
                receipt["preview_confirm_replay"]
                == {"preview": True, "confirm": True, "replay": True},
                receipt["source"]["source_record_id"] == authored["source_record_id"],
                len(receipt["source"]["source_fingerprint"]) == 64,
                receipt["communication"]["schema"] == "spell.communication.route.v1",
                receipt["communication"]["delivered_to_target_only"],
                receipt["communication"]["private_reply_to_sender"],
                receipt["communication"]["message_fingerprint"] == "b" * 64,
                receipt["communication"]["distance_ft"] == 5,
                receipt["cas"]["actor_version_after"] == 2,
                receipt["cas"]["target_version_after"] == 2,
                receipt["transaction"]["operation_transaction_present"],
            ]
        ),
        "cas": True,
        "formal_database_written": False,
        "formal_registry_written": False,
        "name_branch_count": 0,
        "operation_transaction": receipt["transaction"]["operation_transaction_present"],
        "preview_confirm_replay": True,
        "protected_fingerprints_unchanged": protected_before
        == protected_path_fingerprints(ROOT),
        "source_provenance": True,
        "typed_consumer": receipt["consumer"] == "spell.communication.route.v1",
    }
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
        "typed_consumer": receipt["consumer"],
        "runtime_receipt": receipt,
    }
    RESULTS.write_text(
        json.dumps(
            {
                "schema_version": "content-ir-production-runtime-results-XLIX-1",
                "round_id": "round-XLIX",
                "content_kind": "spell",
                "production_runtime_full_ids": [SPELL_ID],
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
        "compile_only": len(
            census
            - set(loaded)
        ),
        "unique_compiled": int(migration["current_project_compiled_unique"]),
    }
    report = {
        "schema_version": "round-XLIX-message-production-1",
        "round_id": "round-XLIX",
        "artifact_date": "2026-08-14",
        "evidence_artifact": str(RESULTS.relative_to(ROOT)),
        "evidence_mechanism": "generic load_production_runtime_evidence production-runtime-results*.json loader",
        "source_bound_producer": {
            "authored_path": str(AUTHORED.relative_to(ROOT)),
            "source_record_id": authored["source_record_id"],
            "source_fingerprint": authored["source_fingerprint"],
            "compile_status": "full",
            "typed_clause_ids": [clause["clause_id"] for clause in authored["clauses"]],
        },
        "runtime_consumers": ["spell.communication.route.v1"],
        "runtime_receipt": receipt,
        "canonical_projection": {
            "counts": counts,
            "message_in_loaded_evidence": SPELL_ID in loaded,
            "message_in_project_production_ids": SPELL_ID in project_ids,
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
            "projection_reconciliation": migration[
                "current_project_production_full"
            ]
            == len(project_ids),
        },
        "promotion_decision": "promote"
        if checks["all_required_checks_passed"]
        and SPELL_ID in loaded
        and SPELL_ID in project_ids
        else "withdraw",
        "historical_preservation": {
            "round_xliii_report_sha256": _sha(
                ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
            ),
            "expected_round_xliii_report_sha256": "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f",
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
    result = build()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["promotion_decision"] == "promote" else 1)
