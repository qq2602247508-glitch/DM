# ruff: noqa: E501
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
COMPILE_RESULT = ROOT / "data/content-ir/compiled/batch-II/compile-result.json"


def _runtime_rows() -> list[dict[str, Any]]:
    result = json.loads(COMPILE_RESULT.read_text(encoding="utf-8"))
    return [row["runtime_spell_definition"] for row in result["results"] if row.get("runtime_spell_definition")]


def _feature_runtime(feature_id: str) -> dict[str, Any]:
    result = json.loads(COMPILE_RESULT.read_text(encoding="utf-8"))
    row = next(item for item in result["results"] if item.get("feature_id") == feature_id)
    return row["runtime_definition"]


def test_real_spell_content_ir_runtime_entry_is_full_and_idempotent(
    campaign_client: TestClient,
) -> None:
    runtime = next(
        item
        for item in _runtime_rows()
        if item["spell_id"].startswith("core-phb-2024:")
        and any(
            effect.get("type") in {"damage", "healing", "temporary_hp"}
            and (effect.get("damage_type") or effect.get("healing") or effect.get("amount"))
            for effect in item["resolution"].get("effects", [])
        )
    )
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "Content IR spell test"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{base}/characters",
        json={"name": "施法者", "hp": 8, "max_hp": 20, "spellcasting": {"slots": {str(level): {"current": 2, "max": 2} for level in range(1, 10)}}},
    ).json()
    known = campaign_client.post(
        f"{base}/characters/assets/spells",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": runtime["name"],
            "spell_level": runtime["level"],
            "prepared": True,
            "metadata_json": {"content_ir_runtime": runtime},
        },
    )
    assert known.status_code == 201, known.text
    character = campaign_client.get(f"{base}/characters/{character['id']}").json()
    combat = campaign_client.post(f"{base}/combats", json={"name": "Content IR spell combat"}).json()
    root = f"{base}/combats/{combat['id']}"
    actor = campaign_client.post(f"{root}/combatants", json={"display_name": "施法者", "entity_type": "character", "entity_id": character["id"], "hp": 20, "max_hp": 20, "initiative": 20}).json()
    target = campaign_client.post(f"{root}/combatants", json={"display_name": "目标", "entity_type": "monster", "hp": 30, "max_hp": 30, "initiative": 10}).json()
    body: dict[str, Any] = {
        "content_kind": "spell",
        "runtime_id": runtime["spell_id"],
        "permission": "player",
        "character_id": character["id"],
        "character_version": character["version"],
        "known_spell_id": known.json()["id"],
        "slot_level": runtime["level"],
        "combat_id": combat["id"],
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "resolution_total": 3,
        "idempotency_key": "content-ir-test-spell-001",
    }
    if runtime["resolution"].get("saving_throw"):
        body["save_succeeded"] = False
    if runtime["resolution"].get("attack_roll"):
        body["attack_roll_total"] = 20
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    confirm_body = {**body, "preview_token": preview.json()["preview_token"]}
    confirmed = campaign_client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["production_runtime_full"] is True
    replay = campaign_client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["already_applied"] is True


def test_real_feature_content_ir_runtime_entry_uses_data_registry(
    campaign_client: TestClient,
) -> None:
    feature_id = "content.tashas-cauldron.feature.armorer-defensive-field"
    runtime = _feature_runtime(feature_id)
    action = next(iter(runtime["actions"].values()))
    campaign = campaign_client.post("/api/v1/campaigns", json={"name": "Content IR feature test"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = campaign_client.post(
        f"{base}/characters",
        json={"name": "奇械师", "hp": 20, "max_hp": 20, "resources": {"defensive_field_uses": {"current": 1, "max": 1}}},
    ).json()
    combat = campaign_client.post(f"{base}/combats", json={"name": "Content IR feature combat"}).json()
    root = f"{base}/combats/{combat['id']}"
    actor = campaign_client.post(
        f"{root}/combatants",
        json={"display_name": "奇械师", "entity_type": "character", "entity_id": character["id"], "hp": 20, "max_hp": 20, "initiative": 20, "snapshot_json": {"feature_runtime": runtime}},
    ).json()
    body = {
        "content_kind": "feature",
        "runtime_id": feature_id,
        "permission": "player",
        "combat_id": combat["id"],
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": actor["id"],
        "target_version": actor["version"],
        "resolution_total": 3,
        "idempotency_key": "content-ir-test-feature-001",
    }
    assert action["kind"] == "feature_action"
    preview = campaign_client.post(f"{base}/content-ir/runtime/preview", json=body)
    assert preview.status_code == 200, preview.text
    confirmed = campaign_client.post(f"{base}/content-ir/runtime/confirm", json={**body, "preview_token": preview.json()["preview_token"]})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["production_runtime_full"] is True


def test_batch_II_reports_keep_layer_boundaries_and_thresholds() -> None:
    reviewed = json.loads((ROOT / "reports/content-ir-reviewed-batch-II-2026-08-11.json").read_text(encoding="utf-8"))
    validation = json.loads((ROOT / "reports/content-ir-production-runtime-validation-2026-08-11.json").read_text(encoding="utf-8"))
    audit = json.loads((ROOT / "reports/content-ir-runtime-level-audit-2026-08-11.json").read_text(encoding="utf-8"))
    assert reviewed["template_count"] >= 8
    assert reviewed["generated_candidate_count"] >= 100
    assert reviewed["reviewed_authored_typed_ir_count"] >= 80
    assert reviewed["compile_full_count"] >= 60
    assert reviewed["runtime_preview_full_count"] >= 60
    assert reviewed["production_runtime_full_count"] >= 20
    assert validation["spell_runtime_loop_count"] >= 15
    assert validation["feature_runtime_loop_count"] >= 5
    assert validation["all_required_checks_passed"] is True
    assert audit["formal_feature_audit_unchanged"]["after"] == {"total": 499, "full": 328, "partial": 110, "dm_only": 61}
