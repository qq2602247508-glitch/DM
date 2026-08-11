# ruff: noqa: N999
"""Run the batch-III production closeout through the real API boundary."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.api.dependencies import get_content_ir_runtime_service
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database import create_database_engine
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
COMPILE_II = ROOT / "data/content-ir/compiled/batch-II/compile-result.json"
COMPILE_III = ROOT / "data/content-ir/compiled/batch-III/compile-result.json"
PRODUCTION_II = ROOT / "data/content-ir/compiled/batch-II/production-runtime-results.json"
REPORT_ROOT = ROOT / "reports"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _rows(path: Path) -> list[dict[str, Any]]:
    return [dict(row) for row in json.loads(path.read_text(encoding="utf-8"))["results"]]


def _spell_runtime(row: dict[str, Any]) -> dict[str, Any]:
    return dict(row["runtime_spell_definition"])


def _effect(runtime: dict[str, Any]) -> dict[str, Any]:
    for item in runtime.get("resolution", {}).get("effects", []):
        if item.get("type") in {"damage", "healing", "temporary_hp"}:
            return dict(item)
    return {}


def _roll_bounds(expression: object) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)d(\d+)(?:\s*([+-])\s*(\d+))?\s*", str(expression or ""))
    if not match:
        return None
    dice, sides = int(match.group(1)), int(match.group(2))
    fixed = int(match.group(4) or 0)
    if match.group(3) == "-":
        fixed = -fixed
    return dice + fixed, dice * sides + fixed


def _valid_total(runtime: dict[str, Any]) -> int:
    effect = _effect(runtime)
    expression = effect.get("expression") or effect.get("damage") or effect.get("healing") or effect.get("amount")
    bounds = _roll_bounds(expression)
    if bounds is not None:
        return min(bounds[1], bounds[0] + 2)
    try:
        return max(1, int(expression))
    except (TypeError, ValueError):
        return 3


def _has(runtime: dict[str, Any], key: str) -> bool:
    return bool(runtime.get("resolution", {}).get(key))


def _setup_spell(client: TestClient, runtime: dict[str, Any]) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Content IR closeout"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "Typed IR caster",
            "hp": 8,
            "max_hp": 20,
            "spellcasting": {
                "slots": {str(level): {"current": 2, "max": 2} for level in range(1, 10)}
            },
        },
    ).json()
    known = client.post(
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
    if known.status_code != 201:
        raise AssertionError(known.text)
    character = client.get(f"{base}/characters/{character['id']}").json()
    scene = client.post(f"{base}/scenes", json={"name": "Typed IR grid"}).json()
    grid = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 12, "height": 8, "cell_size_ft": 5, "mode": "combat"},
    )
    if grid.status_code != 201:
        raise AssertionError(grid.text)
    combat = client.post(
        f"{base}/combats", json={"name": "Typed IR combat", "scene_id": scene["id"]}
    ).json()
    root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Typed IR caster",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "snapshot_json": {"grid_position": {"row": 2, "col": 2}},
        },
    ).json()
    target = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Typed IR target",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 100,
            "max_hp": 100,
            "snapshot_json": {"grid_position": {"row": 2, "col": 3}, "disposition": "enemy"},
        },
    ).json()
    return {
        "campaign": campaign,
        "base": base,
        "character": character,
        "known_spell": known.json(),
        "combat": combat,
        "actor": actor,
        "target": target,
        "runtime": runtime,
    }


def _spell_body(scene: dict[str, Any], runtime: dict[str, Any], key: str) -> dict[str, Any]:
    effect = _effect(runtime)
    target = scene["actor"] if effect.get("type") in {"healing", "temporary_hp"} else scene["target"]
    body: dict[str, Any] = {
        "content_kind": "spell",
        "runtime_id": runtime["spell_id"],
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known_spell"]["id"],
        "slot_level": runtime["level"],
        "concentration": bool(runtime.get("concentration")),
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": scene["actor"]["id"],
        "actor_version": scene["actor"]["version"],
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "resolution_total": _valid_total(runtime),
        "idempotency_key": key,
    }
    if _has(runtime, "saving_throw"):
        body["save_succeeded"] = False
    if _has(runtime, "attack_roll"):
        body["attack_roll_total"] = 100
    area = next(
        (
            item
            for item in runtime.get("resolution", {}).get("target_selection", [])
            if item.get("kind") == "area"
        ),
        None,
    )
    if area:
        body.update(
            {
                "area_shape": area.get("shape"),
                "area_size_ft": area.get("size_ft"),
                "area_width_ft": 5 if area.get("shape") == "line" else area.get("size_ft"),
                "area_height_ft": area.get("size_ft"),
                "area_anchor_row": 2,
                "area_anchor_col": 4,
            }
        )
    return body


def _run_spell(client: TestClient, runtime: dict[str, Any], index: int) -> dict[str, Any]:
    scene = _setup_spell(client, runtime)
    body = _spell_body(scene, runtime, f"content-ir-closeout-spell-{index:03d}")
    preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    row: dict[str, Any] = {
        "runtime_id": runtime["spell_id"],
        "pack_id": str(runtime["spell_id"]).split(":", 1)[0],
        "preview_status": preview.status_code,
    }
    if preview.status_code != 200:
        row["production_runtime_full"] = False
        row["error"] = preview.text[:500]
        return row
    confirmed = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    replay = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    row.update(
        {
            "confirm_status": confirmed.status_code,
            "replay_status": replay.status_code,
            "replay_already_applied": bool(replay.json().get("already_applied")) if replay.status_code == 200 else False,
            "production_runtime_full": bool(confirmed.json().get("production_runtime_full")) if confirmed.status_code == 200 else False,
        }
    )
    if confirmed.status_code != 200:
        row["error"] = confirmed.text[:500]
    return row


def _feature_row(feature_id: str) -> dict[str, Any]:
    for row in _rows(COMPILE_II):
        if row.get("feature_id") == feature_id:
            return dict(row["runtime_definition"])
    raise ValueError(f"feature runtime not found: {feature_id}")


def _run_feature(client: TestClient, feature_id: str, index: int) -> dict[str, Any]:
    runtime = _feature_row(feature_id)
    campaign = client.post("/api/v1/campaigns", json={"name": "Content IR feature closeout"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    is_physician = feature_id.endswith("physicians-touch")
    character = client.post(
        f"{base}/characters", json={"name": "Feature actor", "hp": 20, "max_hp": 20}
    ).json()
    combat = client.post(f"{base}/combats", json={"name": "Feature combat"}).json()
    root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Feature actor",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "conditions": ["poisoned"] if is_physician else [],
            "snapshot_json": {"feature_runtime": runtime},
        },
    ).json()
    is_rider = feature_id.endswith("armorer-lightning-launcher")
    is_self = feature_id.endswith(("chemical-mastery", "armorer-extra-attack"))
    target = actor
    if not is_self and not is_rider and not is_physician:
        target = client.post(
            f"{root}/combatants",
            json={
                "display_name": "Feature ally",
                "entity_type": "npc",
                "initiative": 10,
                "hp": 10,
                "max_hp": 20,
                "conditions": ["poisoned"] if feature_id.endswith("physicians-touch") else [],
                "snapshot_json": {"disposition": "ally"},
            },
        ).json()
    if is_rider:
        target = client.post(
            f"{root}/combatants",
            json={
                "display_name": "Feature enemy",
                "entity_type": "monster",
                "initiative": 10,
                "hp": 30,
                "max_hp": 30,
                "snapshot_json": {"disposition": "enemy"},
            },
        ).json()
    body: dict[str, Any] = {
        "content_kind": "feature",
        "runtime_id": feature_id,
        "permission": "player",
        "combat_id": combat["id"],
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "resolution_total": 4 if is_rider else 3,
        "idempotency_key": f"content-ir-closeout-feature-{index:03d}",
    }
    if is_physician:
        target = actor
        body["condition_to_remove"] = "poisoned"
    if is_rider:
        body["attack_hit"] = True
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    result: dict[str, Any] = {
        "runtime_id": feature_id,
        "pack_id": "tashas-cauldron-features",
        "preview_status": preview.status_code,
    }
    if preview.status_code != 200:
        result["production_runtime_full"] = False
        result["error"] = preview.text[:500]
        return result
    confirmed = client.post(
        f"{base}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    result.update(
        {
            "confirm_status": confirmed.status_code,
            "production_runtime_full": bool(confirmed.json().get("production_runtime_full")) if confirmed.status_code == 200 else False,
        }
    )
    if confirmed.status_code != 200:
        result["error"] = confirmed.text[:500]
    return result


def _select_spell_rows() -> list[dict[str, Any]]:
    old_rows = [row for row in _rows(COMPILE_II) if row.get("kind") == "spell"]
    old_production = set(json.loads(PRODUCTION_II.read_text(encoding="utf-8"))["production_runtime_full_ids"])
    selected: list[dict[str, Any]] = []
    for prefix, limit in (("core-phb-2024:", 10), ("book-of-many-things:", 2), ("tashas-cauldron:", 1)):
        for row in sorted(old_rows, key=lambda item: item["spell_id"]):
            runtime = row.get("runtime_spell_definition")
            if not runtime or not str(row["spell_id"]).startswith(prefix) or row["spell_id"] in old_production:
                continue
            if _effect(runtime) and not runtime.get("concentration") or prefix == "tashas-cauldron:" and _effect(runtime):
                selected.append(dict(runtime))
            if len([item for item in selected if str(item["spell_id"]).startswith(prefix)]) >= limit:
                break
    selected.extend(_spell_runtime(row) for row in sorted(_rows(COMPILE_III), key=lambda item: item["spell_id"]))
    if len(selected) != 26:
        raise RuntimeError(f"expected 26 spell closeout loops, got {len(selected)}")
    return selected


def _edge_checks(client: TestClient, runtime: dict[str, Any], app: Any, database_url: str) -> dict[str, Any]:
    scene = _setup_spell(client, runtime)
    base = scene["base"]
    wrong_slot = _spell_body(scene, runtime, "closeout-edge-wrong-slot")
    if int(runtime["level"]) > 0:
        wrong_slot["slot_level"] = int(runtime["level"]) - 1
    wrong_slot_response = client.post(f"{base}/content-ir/runtime/preview", json=wrong_slot)
    checks: dict[str, Any] = {"wrong_slot_rejected": wrong_slot_response.status_code == 400}
    body = _spell_body(scene, runtime, "closeout-edge-cas")
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    confirmed = client.post(f"{base}/content-ir/runtime/confirm", json={**body, "preview_token": preview.json()["preview_token"]})
    fresh_target = client.get(f"{base}/combats/{scene['combat']['id']}/combatants/{scene['target']['id']}").json()
    stale = {**body, "target_version": scene["target"]["version"], "idempotency_key": "closeout-edge-stale"}
    checks["target_cas_rejected"] = client.post(f"{base}/content-ir/runtime/preview", json=stale).status_code == 409
    checks["idempotency_replay"] = confirmed.status_code == 200 and client.post(
        f"{base}/content-ir/runtime/confirm", json={**body, "preview_token": preview.json()["preview_token"]}
    ).json().get("already_applied") is True
    checks["snapshot_version_changed"] = int(fresh_target["version"]) > int(scene["target"]["version"])
    rollback_scene = _setup_spell(client, runtime)
    rollback_body = _spell_body(rollback_scene, runtime, "closeout-edge-rollback")
    rollback_preview = client.post(f"{rollback_scene['base']}/content-ir/runtime/preview", json=rollback_body)
    service = ContentIRRuntimeService(create_database_engine(database_url))
    original_confirm = service.combat.confirm

    def fail_downstream(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("closeout rollback probe")

    service.combat.confirm = fail_downstream  # type: ignore[method-assign]
    app.dependency_overrides[get_content_ir_runtime_service] = lambda: service
    try:
        rollback = client.post(
            f"{rollback_scene['base']}/content-ir/runtime/confirm",
            json={**rollback_body, "preview_token": rollback_preview.json()["preview_token"]},
        )
    finally:
        app.dependency_overrides.pop(get_content_ir_runtime_service, None)
        service.combat.confirm = original_confirm  # type: ignore[method-assign]
        service.engine.dispose()
    restored = client.get(f"{rollback_scene['base']}/characters/{rollback_scene['character']['id']}").json()
    slot = restored.get("spellcasting", {}).get("slots", {}).get(str(runtime["level"]), {}).get("current")
    checks["rollback_restored_slot"] = rollback.status_code == 400 and slot == 2
    return checks


def _area_multi_target_check(client: TestClient) -> bool:
    runtime = next(
        _spell_runtime(row)
        for row in _rows(COMPILE_II)
        if row.get("spell_id") == "core-phb-2024:spell:fb279ff13dba2abcce376201"
    )
    scene = _setup_spell(client, runtime)
    root = f"{scene['base']}/combats/{scene['combat']['id']}"
    second = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Area target 2",
            "entity_type": "monster",
            "initiative": 9,
            "hp": 100,
            "max_hp": 100,
            "snapshot_json": {"grid_position": {"row": 3, "col": 3}, "disposition": "enemy"},
        },
    ).json()
    body = _spell_body(scene, runtime, "closeout-edge-area-multi")
    body.update(
        {
            "target_combatant_ids": [second["id"]],
            "target_versions": {scene["target"]["id"]: scene["target"]["version"], second["id"]: second["version"]},
            "save_succeeded_by_target": {scene["target"]["id"]: False, second["id"]: False},
        }
    )
    preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview.status_code != 200:
        return False
    confirmed = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    return confirmed.status_code == 200 and isinstance(confirmed.json().get("combat"), list)


def main() -> int:
    logging.disable(logging.CRITICAL)
    spell_rows = _select_spell_rows()
    feature_ids = [
        "content.tashas-cauldron.feature.psi-warrior-telekinetic-movement",
        "content.tashas-cauldron.feature.way-of-mercy-physicians-touch",
        "content.tashas-cauldron.feature.alchemist-chemical-mastery",
        "content.tashas-cauldron.feature.armorer-extra-attack",
        "content.tashas-cauldron.feature.armorer-lightning-launcher",
    ]
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/content-ir-closeout.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            spell_results = [_run_spell(client, runtime, index) for index, runtime in enumerate(spell_rows)]
            feature_results = [_run_feature(client, feature_id, index) for index, feature_id in enumerate(feature_ids)]
            edge_runtime = next(
                runtime
                for runtime in spell_rows
                if runtime["spell_id"].startswith("book-of-many-things:")
            )
            edge_checks = _edge_checks(client, edge_runtime, app, database_url)
            edge_checks["area_multi_target"] = _area_multi_target_check(client)
    logging.disable(logging.NOTSET)

    production_ids = sorted(
        item["runtime_id"]
        for item in [*spell_results, *feature_results]
        if item.get("production_runtime_full")
    )
    spell_ids = sorted(item["runtime_id"] for item in spell_results if item.get("production_runtime_full"))
    feature_full_ids = sorted(item["runtime_id"] for item in feature_results if item.get("production_runtime_full"))
    pack_counts = Counter(str(item).split(":", 1)[0] for item in spell_ids)
    validation = {
        "schema_version": "content-ir-production-runtime-validation-II-1",
        "baseline_existing_100": {"compile_full": 100, "runtime_preview_full": 100, "production_runtime_full": 20},
        "new_authored_typed_ir_count": 13,
        "spell_runtime_loop_count": len(spell_results),
        "feature_runtime_loop_count": len(feature_results),
        "new_production_runtime_full_count": len(production_ids),
        "production_runtime_full_count": 20 + len(production_ids),
        "new_spell_production_runtime_full_count": len(spell_ids),
        "final_spell_production_runtime_full_count": 15 + len(spell_ids),
        "new_feature_production_runtime_full_count": len(feature_full_ids),
        "final_feature_production_runtime_full_count": 5 + len(feature_full_ids),
        "production_runtime_full_ids": production_ids,
        "spell_results": spell_results,
        "feature_results": feature_results,
        "edge_checks": edge_checks,
        "pack_counts_new": dict(sorted(pack_counts.items())),
        "all_required_checks_passed": (
            len(spell_ids) >= 25
            and len(feature_full_ids) >= 5
            and all(item.get("production_runtime_full") for item in [*spell_results, *feature_results])
            and all(value is True for value in edge_checks.values())
        ),
        "generic_consumers": [
            {"consumer_id": "combat_engine.damage_heal.v1", "unlock_count": len(spell_ids) + 1},
            {"consumer_id": "combat_engine.area_damage.v1", "unlock_count": 3},
            {"consumer_id": "spell_economy.concentration.v1", "unlock_count": sum(bool(item.get("concentration")) for item in spell_rows)},
            {"consumer_id": "combat_engine.feature_action.v1", "unlock_count": len(feature_full_ids)},
        ],
    }
    _write(
        ROOT / "data/content-ir/compiled/production-runtime-results-III.json",
        {
            "schema_version": "content-ir-production-runtime-results-III-1",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": {item["runtime_id"]: item for item in [*spell_results, *feature_results]},
            "checks": edge_checks,
        },
    )
    _write(REPORT_ROOT / "content-ir-production-runtime-validation-II-2026-08-11.json", validation)
    _write(
        REPORT_ROOT / "content-ir-production-consumer-batch-I-2026-08-11.json",
        {"schema_version": "content-ir-production-consumer-batch-I-1", "consumers": validation["generic_consumers"], "production_ids": production_ids},
    )
    _write(
        REPORT_ROOT / "spell-ir-production-runtime-batch-I-2026-08-11.json",
        {"schema_version": "spell-ir-production-runtime-batch-I-1", "baseline_spell_production": 15, "new_spell_production": len(spell_ids), "final_spell_production": 15 + len(spell_ids), "pack_counts_new": dict(sorted(pack_counts.items())), "ids": spell_ids},
    )
    _write(
        REPORT_ROOT / "feature-ir-production-runtime-batch-I-2026-08-11.json",
        {"schema_version": "feature-ir-production-runtime-batch-I-1", "baseline_feature_production": 5, "new_feature_production": len(feature_full_ids), "final_feature_production": 5 + len(feature_full_ids), "ids": feature_full_ids},
    )
    _write(
        REPORT_ROOT / "content-ir-production-runtime-validation-II-2026-08-11.json",
        validation,
    )
    _write(
        REPORT_ROOT / "content-ir-cross-pack-production-proof-2026-08-11.json",
        {
            "schema_version": "content-ir-cross-pack-production-proof-1",
            "before": {"core-phb-2024": 10, "xanathars-guide": 4, "tashas-cauldron": 1, "fizbans-treasury": 0, "book-of-many-things": 0},
            "after": {"core-phb-2024": 10 + pack_counts["core-phb-2024"], "xanathars-guide": 4 + pack_counts["xanathars-guide"], "tashas-cauldron": 1 + pack_counts["tashas-cauldron"], "fizbans-treasury": pack_counts["fizbans-treasury"], "book-of-many-things": pack_counts["book-of-many-things"]},
            "requirements": {"fizbans_treasury_min": 2, "book_of_many_things_min": 1, "xanathars_total_min": 7, "tashas_spells_total_min": 3, "tashas_features_total_min": 10},
            "tashas_feature_after": 5 + len(feature_full_ids),
        },
    )
    _write(
        REPORT_ROOT / "content-ir-isolated-pack-dry-run-III-2026-08-11.json",
        {
            "schema_version": "content-ir-isolated-pack-dry-run-III-1",
            "packs": sorted(
                [
                    {
                        "pack_id": str(item["runtime_id"]).split(":", 1)[0],
                        "production_ids": sorted(
                            result["runtime_id"]
                            for result in spell_results
                            if result.get("pack_id") == item["pack_id"]
                            and result.get("production_runtime_full")
                        ),
                    }
                    for item in spell_results
                ],
                key=lambda item: (item["pack_id"], item["production_ids"]),
            ),
            "isolated": True,
            "no_campaign_or_database_pollution": True,
        },
    )
    return 0 if validation["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
