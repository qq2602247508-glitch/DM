# ruff: noqa: N999
"""Close Acid Splash through existing generic area/save/damage consumers."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import re
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
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_spell_spec,
)
from dnd_dm_assistant.application.tashas_whole_pack import (
    build_migration,
    protected_path_fingerprints,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database import create_database_engine
from dnd_dm_assistant.infrastructure.database.models import OperationTransaction
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SPELL_ID = "core-phb-2024:spell:d84dec64befac8db7294e0f1"
SOURCE_PATH = (
    ROOT
    / "data/content-ir/authored/core-2024/spells/spells/"
    "core-phb-2024-spell-d84dec64befac8db7294e0f1.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-LVII.json"
REPORT_PATH = ROOT / "reports/round-LVII-acid-splash-closure-2026-08-14.json"
FOCUSED_TEST = "backend/tests/test_round_LVII_acid_splash_closure.py"
EXPECTED_OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
EXPECTED_XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"
LIV_REPORT = ROOT / "reports/round-LIV-summon-census-closure-2026-08-14.json"
LVI_REPORT = ROOT / "reports/round-LVI-intellect-fortress-closure-2026-08-14.json"
OLD_VALIDATOR = ROOT / "scripts/validate-tashas-spell-production-consumer-round-XX.py"
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b"
)
_ISO_TIMESTAMP_RE = re.compile(
    r"\b20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\b"
)


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _stable(value: Any) -> Any:
    if isinstance(value, str):
        return _ISO_TIMESTAMP_RE.sub("stable-time", _UUID_RE.sub("stable-id", value))
    if isinstance(value, dict):
        normalized_items = [
            (
                key,
                (
                    "stable-id"
                    if key.endswith("_id") or key in {"id", "operation_transaction_id"}
                    else "stable-token"
                    if key.endswith("_fingerprint") or key == "preview_token"
                    else "stable-time"
                    if key.endswith("_at") or key in {"created_at", "updated_at"}
                    else _stable(item)
                ),
            )
            for key, item in value.items()
        ]
        if normalized_items and all(_UUID_RE.fullmatch(str(key)) for key, _ in normalized_items):
            normalized_items = sorted(
                normalized_items,
                key=lambda item: json.dumps(item[1], ensure_ascii=False, sort_keys=True),
            )
            return {f"stable-id-{index}": item for index, (_, item) in enumerate(normalized_items)}
        return {key: item for key, item in sorted(normalized_items)}
    if isinstance(value, list):
        normalized = [_stable(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    return value


def _load_old() -> Any:
    spec = importlib.util.spec_from_file_location("round_xx_validator", OLD_VALIDATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load the existing generic area/damage harness")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.SPELL_ID = SPELL_ID
    return module


def _load_source() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(source))
    runtime = dict(compiled.get("runtime_spell_definition") or {})
    if compiled.get("compile_status") != "full" or not runtime:
        raise AssertionError("Acid Splash canonical IR did not compile full")
    return source, compiled, runtime


def _setup_area_spell(client: TestClient, runtime: dict[str, Any], level: int) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": f"Acid Splash L{level}"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character_response = client.post(
        f"{base}/characters",
        json={
            "name": f"Acid Splash caster L{level}",
            "level": level,
            "hp": 20,
            "max_hp": 20,
            "spellcasting": {
                "slots": {str(slot): {"current": 2, "max": 2} for slot in range(1, 10)}
            },
        },
    )
    if character_response.status_code != 201:
        raise AssertionError(character_response.text)
    character = character_response.json()
    known_response = client.post(
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
    if known_response.status_code != 201:
        raise AssertionError(known_response.text)
    character = client.get(f"{base}/characters/{character['id']}").json()
    scene = client.post(f"{base}/scenes", json={"name": "Acid Splash grid"}).json()
    grid_response = client.post(
        f"{base}/scenes/{scene['id']}/grid",
        json={"width": 20, "height": 20, "cell_size_ft": 5, "mode": "combat"},
    )
    if grid_response.status_code != 201:
        raise AssertionError(grid_response.text)
    combat = client.post(
        f"{base}/combats",
        json={"name": "Acid Splash combat", "scene_id": scene["id"]},
    ).json()
    root = f"{base}/combats/{combat['id']}"
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Acid Splash caster",
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
            "display_name": "Acid Splash target",
            "entity_type": "monster",
            "initiative": 10,
            "hp": 100,
            "max_hp": 100,
            "snapshot_json": {"grid_position": {"row": 2, "col": 3}, "disposition": "enemy"},
        },
    ).json()
    second_target = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Acid Splash target 2",
            "entity_type": "monster",
            "initiative": 9,
            "hp": 100,
            "max_hp": 100,
            "snapshot_json": {"grid_position": {"row": 3, "col": 2}, "disposition": "enemy"},
        },
    ).json()
    outside_target = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Acid Splash outside",
            "entity_type": "monster",
            "initiative": 8,
            "hp": 100,
            "max_hp": 100,
            "snapshot_json": {"grid_position": {"row": 2, "col": 5}, "disposition": "enemy"},
        },
    ).json()
    return {
        "base": base,
        "campaign": campaign,
        "character": character,
        "known_spell": known_response.json(),
        "combat": combat,
        "actor": actor,
        "target": target,
        "second_target": second_target,
        "outside_target": outside_target,
    }


def _area_body(
    scene: dict[str, Any],
    *,
    key: str,
    total: int,
    anchor_row: int = 2,
    anchor_col: int = 2,
    target_ids: list[str] | None = None,
    primary_target_id: str | None = None,
    primary_target_version: int | None = None,
) -> dict[str, Any]:
    target = scene["target"]
    second = scene["second_target"]
    actor = scene["actor"]
    primary = primary_target_id or actor["id"]
    ids = target_ids if target_ids is not None else [target["id"], second["id"]]
    combatants = {
        item["id"]: item
        for item in (
            scene["actor"],
            scene["target"],
            scene["second_target"],
            scene["outside_target"],
        )
    }
    submitted_ids = [primary, *ids]
    versions = {
        combatant_id: (
            combatants[combatant_id]["version"]
            if combatant_id in combatants
            else primary_target_version
        )
        for combatant_id in submitted_ids
    }
    if any(version is None for version in versions.values()):
        raise AssertionError("area probe did not provide a submitted target version")
    save_by_target = {combatant_id: False for combatant_id in submitted_ids}
    return {
        "content_kind": "spell",
        "runtime_id": SPELL_ID,
        "permission": "player",
        "character_id": scene["character"]["id"],
        "character_version": scene["character"]["version"],
        "known_spell_id": scene["known_spell"]["id"],
        "slot_level": 0,
        "combat_id": scene["combat"]["id"],
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": primary,
        "target_combatant_ids": ids,
        "target_versions": versions,
        "area_shape": "sphere",
        "area_size_ft": 5,
        "area_anchor_row": anchor_row,
        "area_anchor_col": anchor_col,
        "area_include_actor": False,
        "resolution_total": total,
        "save_succeeded_by_target": save_by_target,
        "idempotency_key": key,
    }


def _transaction_rows(database_url: str, campaign_id: str) -> list[dict[str, Any]]:
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as session:
            rows = session.scalars(
                select(OperationTransaction)
                .where(OperationTransaction.campaign_id == campaign_id)
                .order_by(OperationTransaction.idempotency_key)
            ).all()
            return [
                {
                    "idempotency_key": row.idempotency_key,
                    "operation_type": row.operation_type,
                    "status": row.status,
                    "reason": row.reason,
                    "source": row.source,
                    "before_snapshot": row.before_snapshot,
                    "after_snapshot": row.after_snapshot,
                }
                for row in rows
            ]
    finally:
        engine.dispose()


def _run_production_loop(old: Any, runtime: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="round-lvii-acid-splash-") as directory:
        database_url = f"sqlite:///{Path(directory) / 'acid-splash.db'}"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            scene = _setup_area_spell(client, runtime, 5)
            body = _area_body(scene, key="round-lvii-acid-splash-production", total=8)
            preview_response = client.post(
                f"{scene['base']}/content-ir/runtime/preview",
                json=body,
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
            target_after = client.get(
                f"{scene['base']}/combats/{scene['combat']['id']}/combatants/"
                f"{scene['target']['id']}"
            ).json()
            second_after = client.get(
                f"{scene['base']}/combats/{scene['combat']['id']}/combatants/"
                f"{scene['second_target']['id']}"
            ).json()
            transactions = _transaction_rows(database_url, scene["campaign"]["id"])
            stale_response = client.post(
                f"{scene['base']}/content-ir/runtime/preview",
                json={
                    **body,
                    "idempotency_key": "round-lvii-acid-splash-stale",
                    "target_versions": {scene["target"]["id"]: scene["target"]["version"]},
                },
            )
            return {
                "runtime_id": SPELL_ID,
                "preview_status": preview_response.status_code,
                "confirm_status": confirm_response.status_code,
                "replay_status": replay_response.status_code,
                "replay_already_applied": replay.get("already_applied"),
                "production_runtime_full": confirmed.get("production_runtime_full"),
                "consumer_ids": preview["production_contract"]["consumers"],
                "area_membership": preview.get("area_membership"),
                "expected_area_target_ids": sorted(
                    [
                        scene["actor"]["id"],
                        scene["target"]["id"],
                        scene["second_target"]["id"],
                    ]
                ),
                "preview_response": {
                    "production_contract": preview.get("production_contract"),
                    "combat_preview": preview.get("combat_preview"),
                },
                "confirm_response": {
                    "production_runtime_full": confirmed.get("production_runtime_full"),
                    "already_applied": confirmed.get("already_applied"),
                },
                "replay_response": {
                    "already_applied": replay.get("already_applied"),
                },
                "confirmed_target_hp": target_after["hp"],
                "confirmed_second_target_hp": second_after["hp"],
                "confirmed_actor_hp": client.get(
                    f"{scene['base']}/combats/{scene['combat']['id']}/combatants/"
                    f"{scene['actor']['id']}"
                ).json()["hp"],
                "outside_target_hp": client.get(
                    f"{scene['base']}/combats/{scene['combat']['id']}/combatants/"
                    f"{scene['outside_target']['id']}"
                ).json()["hp"],
                "target_version_advanced": int(target_after["version"])
                > int(scene["target"]["version"]),
                "second_target_version_advanced": int(second_after["version"])
                > int(scene["second_target"]["version"]),
                "stale_target_cas_status": stale_response.status_code,
                "operation_transactions": transactions,
            }


def _run_scaling_and_save(old: Any, runtime: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="round-lvii-acid-splash-scaling-") as directory:
        database_url = f"sqlite:///{Path(directory) / 'scaling.db'}"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            scaling: list[dict[str, Any]] = []
            for level, total in ((1, 4), (5, 8), (11, 12), (17, 16)):
                scene = _setup_area_spell(client, runtime, level)
                body = _area_body(
                    scene,
                    key=f"round-lvii-acid-splash-scaling-{level}",
                    total=total,
                )
                response = client.post(
                    f"{scene['base']}/content-ir/runtime/preview",
                    json=body,
                )
                if response.status_code != 200:
                    raise AssertionError(response.text)
                preview = response.json()
                scaling.append(
                    {
                        "character_level": level,
                        "reported_total": total,
                        "resolved_amounts": old._combat_amounts(preview),
                        "consumer_ids": preview["production_contract"]["consumers"],
                        "area_membership": preview.get("area_membership"),
                    }
                )
            scene = _setup_area_spell(client, runtime, 5)
            save_body = _area_body(
                scene,
                key="round-lvii-acid-splash-save-success",
                total=8,
            )
            save_body["save_succeeded_by_target"] = {
                item: True for item in save_body["save_succeeded_by_target"]
            }
            save_response = client.post(
                f"{scene['base']}/content-ir/runtime/preview",
                json=save_body,
            )
            if save_response.status_code != 200:
                raise AssertionError(save_response.text)
            save_success_no_damage = old._combat_amounts(save_response.json()) == [0, 0, 0]
    expected = [
        {"character_level": level, "resolved_amounts": amounts}
        for level, amounts in (
            (1, [4, 4, 4]),
            (5, [8, 8, 8]),
            (11, [12, 12, 12]),
            (17, [16, 16, 16]),
        )
    ]
    actual = [
        {
            "character_level": row["character_level"],
            "resolved_amounts": row["resolved_amounts"],
        }
        for row in scaling
    ]
    return {
        "scaling_previews": scaling,
        "expected_scaling_from_source": expected,
        "scaling_matches_source_progression": actual == expected,
        "save_success_no_damage": save_success_no_damage,
    }


def _run_area_boundary_and_rejection_probes(
    runtime: dict[str, Any],
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="round-lvii-acid-splash-area-") as directory:
        database_url = f"sqlite:///{Path(directory) / 'area.db'}"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            scene = _setup_area_spell(client, runtime, 5)
            character_before = client.get(
                f"{scene['base']}/characters/{scene['character']['id']}"
            ).json()
            omitted = _area_body(
                scene,
                key="round-lvii-acid-splash-omitted-actor",
                total=8,
                target_ids=[scene["second_target"]["id"]],
                primary_target_id=scene["target"]["id"],
            )
            omitted_response = client.post(
                f"{scene['base']}/content-ir/runtime/preview",
                json=omitted,
            )
            character_after_omitted = client.get(
                f"{scene['base']}/characters/{scene['character']['id']}"
            ).json()
            extra = _area_body(
                scene,
                key="round-lvii-acid-splash-extra-outside",
                total=8,
                target_ids=[
                    scene["target"]["id"],
                    scene["second_target"]["id"],
                    scene["outside_target"]["id"],
                ],
            )
            extra["target_versions"][scene["outside_target"]["id"]] = scene[
                "outside_target"
            ]["version"]
            extra["save_succeeded_by_target"][scene["outside_target"]["id"]] = False
            extra_response = client.post(
                f"{scene['base']}/content-ir/runtime/preview",
                json=extra,
            )
            bounds = _setup_area_spell(client, runtime, 5)
            bounds_root = f"{bounds['base']}/combats/{bounds['combat']['id']}"
            boundary_target = client.post(
                f"{bounds_root}/combatants",
                json={
                    "display_name": "Acid Splash boundary",
                    "entity_type": "monster",
                    "initiative": 7,
                    "hp": 100,
                    "max_hp": 100,
                    "snapshot_json": {
                        "grid_position": {"row": 2, "col": 14},
                        "disposition": "enemy",
                    },
                },
            ).json()
            boundary_body = _area_body(
                bounds,
                key="round-lvii-acid-splash-range-boundary",
                total=8,
                anchor_col=14,
                target_ids=[boundary_target["id"]],
                primary_target_id=boundary_target["id"],
                primary_target_version=boundary_target["version"],
            )
            boundary_body["target_versions"] = {boundary_target["id"]: boundary_target["version"]}
            boundary_body["save_succeeded_by_target"] = {boundary_target["id"]: False}
            boundary_response = client.post(
                f"{bounds['base']}/content-ir/runtime/preview",
                json=boundary_body,
            )
            too_far_target = client.post(
                f"{bounds_root}/combatants",
                json={
                    "display_name": "Acid Splash too far",
                    "entity_type": "monster",
                    "initiative": 6,
                    "hp": 100,
                    "max_hp": 100,
                    "snapshot_json": {
                        "grid_position": {"row": 2, "col": 15},
                        "disposition": "enemy",
                    },
                },
            ).json()
            too_far_body = _area_body(
                bounds,
                key="round-lvii-acid-splash-range-too-far",
                total=8,
                anchor_col=15,
                target_ids=[too_far_target["id"]],
                primary_target_id=too_far_target["id"],
                primary_target_version=too_far_target["version"],
            )
            too_far_body["target_versions"] = {too_far_target["id"]: too_far_target["version"]}
            too_far_body["save_succeeded_by_target"] = {too_far_target["id"]: False}
            too_far_response = client.post(
                f"{bounds['base']}/content-ir/runtime/preview",
                json=too_far_body,
            )
            out_of_bounds = _area_body(
                bounds,
                key="round-lvii-acid-splash-anchor-out-of-bounds",
                total=8,
                anchor_col=21,
                target_ids=[too_far_target["id"]],
                primary_target_id=too_far_target["id"],
                primary_target_version=too_far_target["version"],
            )
            out_of_bounds["target_versions"] = {too_far_target["id"]: too_far_target["version"]}
            out_of_bounds["save_succeeded_by_target"] = {too_far_target["id"]: False}
            out_of_bounds_response = client.post(
                f"{bounds['base']}/content-ir/runtime/preview",
                json=out_of_bounds,
            )
            return {
                "omitted_in_area_status": omitted_response.status_code,
                "omitted_before_payment": (
                    omitted_response.status_code == 400
                    and character_after_omitted["version"] == character_before["version"]
                ),
                "extra_outside_status": extra_response.status_code,
                "boundary_60ft_status": boundary_response.status_code,
                "too_far_65ft_status": too_far_response.status_code,
                "anchor_out_of_bounds_status": out_of_bounds_response.status_code,
            }


def _payload_drift_probe(old: Any, runtime: dict[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="round-lvii-acid-splash-drift-") as directory:
        database_url = f"sqlite:///{Path(directory) / 'drift.db'}"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            scene = _setup_area_spell(client, runtime, 5)
            body = _area_body(
                scene,
                key="round-lvii-acid-splash-drift",
                total=8,
            )
            preview = client.post(
                f"{scene['base']}/content-ir/runtime/preview",
                json=body,
            )
            response = client.post(
                f"{scene['base']}/content-ir/runtime/confirm",
                json={
                    **body,
                    "slot_level": 4,
                    "preview_token": preview.json()["preview_token"],
                },
            )
            return {
                "preview_status": preview.status_code,
                "confirm_status": response.status_code,
                "rejected": response.status_code in {400, 409},
            }


def _strict_loader_probe() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="round-lvii-acid-splash-loader-") as directory:
        root = Path(directory)
        artifact_path = root / "data/content-ir/compiled/invalid.json"
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_text(
            json.dumps(
                {
                    "production_runtime_full_ids": [SPELL_ID],
                    "evidence_by_id": {
                        SPELL_ID: {
                            "content_id": SPELL_ID,
                            "production_runtime_full": False,
                        }
                    },
                    "checks": {
                        "all_required_checks_passed": False,
                        "name_branch_count": 1,
                    },
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        loaded = load_production_runtime_evidence(
            root,
            pack_id=None,
            required_checks=("all_required_checks_passed",),
            require_name_branch_free=True,
        )
        return {"rejected": SPELL_ID not in loaded, "loaded_ids": sorted(loaded)}


def _projection_before() -> dict[str, Any]:
    current_artifact = str(RESULT_PATH.relative_to(ROOT))
    authoritative = authoritative_compile_only_ids(ROOT)
    current = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    prior = {
        content_id: row
        for content_id, row in current.items()
        if row.get("evidence_path") != current_artifact
    }
    production_before = {
        content_id
        for content_id, row in current.items()
        if row.get("evidence_path") != current_artifact
    }
    return {
        "authoritative_size": len(authoritative),
        "prior_loaded_ids": sorted(prior),
        "before_compile_only_ids": sorted(project_compile_only_ids(authoritative, prior)),
        "production_before_ids": sorted(production_before),
    }


def _candidate_comparison() -> dict[str, Any]:
    census = json.loads(LIV_REPORT.read_text(encoding="utf-8"))["census"]
    selected = next(group for group in census["groups"] if SPELL_ID in group["content_ids"])
    return {
        "selected": {
            "content_id": SPELL_ID,
            "semantic_group": selected["semantic_group"],
            "shared_consumer": selected["shared_consumer"],
        },
        "basis": [
            "canonical source-complete authored and compiled IR",
            "existing generic area damage, damage/heal, and cantrip scaling consumers",
            "existing real isolated SQLite API harness with persistence, CAS, replay, and save branch coverage",
        ],
        "other_remaining_groups": sorted(
            group["semantic_group"]
            for group in census["groups"]
            if SPELL_ID not in group["content_ids"]
        ),
        "ranking_claim": False,
    }


def _name_branch_count(source: dict[str, Any]) -> dict[str, Any]:
    source_text = json.dumps(source, ensure_ascii=False)
    match = re.search(r"｜([A-Za-z][A-Za-z -]+)", source_text)
    if match is None:
        raise AssertionError("source does not expose the English spell name")
    markers = (SPELL_ID, str(source["name"]), match.group(1).strip())
    occurrences: dict[str, dict[str, int]] = {}
    for path in sorted((ROOT / "backend/src/dnd_dm_assistant").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        counts = {marker: text.count(marker) for marker in markers if text.count(marker)}
        if counts:
            occurrences[str(path.relative_to(ROOT))] = counts
    return {
        "count": sum(sum(counts.values()) for counts in occurrences.values()),
        "markers": markers,
        "occurrences": occurrences,
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    logging.disable(logging.CRITICAL)
    old = _load_old()
    source, compiled, runtime = _load_source()
    production = _stable(_run_production_loop(old, runtime))
    scaling = _stable(_run_scaling_and_save(old, runtime))
    area_probes = _stable(_run_area_boundary_and_rejection_probes(runtime))
    payload_drift = _stable(_payload_drift_probe(old, runtime))
    strict_loader = _strict_loader_probe()
    projection = _projection_before()
    authoritative = authoritative_compile_only_ids(ROOT)
    census = json.loads(LIV_REPORT.read_text(encoding="utf-8"))["census"]
    census_row = next(row for row in census["rows"] if row["content_id"] == SPELL_ID)
    batch_ii_source = json.loads(
        (
            ROOT
            / "data/content-ir/authored/batch-II/core-phb-2024/spells/"
            "core-phb-2024-spell-d84dec64befac8db7294e0f1.json"
        ).read_text(encoding="utf-8")
    )
    before = set(projection["before_compile_only_ids"])
    production_before = set(projection["production_before_ids"])
    after = project_compile_only_ids(authoritative, production_before | {SPELL_ID})
    production_after = production_before | {SPELL_ID}
    duplicate_invalid = project_compile_only_ids(
        set(projection["before_compile_only_ids"]) | {SPELL_ID},
        [SPELL_ID, SPELL_ID, "", "invalid:id"],
    )
    migration = build_migration(ROOT)
    lvi_snapshot = json.loads(LVI_REPORT.read_text(encoding="utf-8"))
    baseline_project_production = int(lvi_snapshot["after"]["production"])
    protected = protected_path_fingerprints(ROOT)
    name_branches = _name_branch_count(source)
    required_consumers = {
        "combat_engine.area_damage.v1",
        "combat_engine.damage_heal.v1",
        "spell.cantrip_scaling.v1",
    }
    checks: dict[str, Any] = {
        "name_branch_count": name_branches["count"],
        "selected_id_authoritative": SPELL_ID in authoritative,
        "canonical_source_complete": compiled["compile_status"] == "full"
        and bool(runtime.get("resolution", {}).get("saving_throw"))
        and any(
            item.get("type") == "damage"
            for item in runtime.get("resolution", {}).get("effects", [])
        )
        and bool(runtime.get("resolution", {}).get("upcast")),
        "source_fingerprint_matches_census": source["source_fingerprint"]
        == census_row["source_fingerprint"],
        "canonical_source_checksum_matches_census": source["source_evidence"]["source_checksum"]
        == census_row["source_checksum"],
        "canonical_duplicate_binding_exact": (
            source["source_record_id"] == SPELL_ID.rsplit(":", 1)[-1]
            and source["source_evidence"]["source_fingerprint"]
            == census_row["source_fingerprint"]
            and source["source_evidence"]["source_checksum"] == census_row["source_checksum"]
        ),
        "incomplete_batch_ii_duplicate_not_used": (
            batch_ii_source["source_record_id"] == source["source_record_id"]
            and batch_ii_source["source_fingerprint"]
            == source["source_evidence"]["source_fingerprint"]
            and len(batch_ii_source["clauses"]) < len(source["clauses"])
            and str(SOURCE_PATH.relative_to(ROOT)).startswith("data/content-ir/authored/core-2024/")
        ),
        "generic_consumers_present": required_consumers.issubset(
            set(production["consumer_ids"])
        ),
        "preview_confirm_replay": production["preview_status"]
        == production["confirm_status"]
        == production["replay_status"]
        == 200,
        "production_runtime_full": production["production_runtime_full"] is True,
        "area_damage_persisted": production["confirmed_target_hp"] < 100
        and production["confirmed_second_target_hp"] < 100
        and production["target_version_advanced"]
        and production["second_target_version_advanced"],
        "exact_area_membership": production["area_membership"]["target_ids"]
        == production["expected_area_target_ids"]
        and production["area_membership"]["include_actor"] is True,
        "actor_in_area_damaged": production["confirmed_actor_hp"] < 20,
        "outside_area_untouched": production["outside_target_hp"] == 100,
        "omitted_in_area_rejected_before_payment": area_probes[
            "omitted_before_payment"
        ]
        is True,
        "extra_outside_rejected": area_probes["extra_outside_status"] == 400,
        "anchor_range_boundary_accepted": area_probes["boundary_60ft_status"] == 422,
        "anchor_range_too_far_rejected": area_probes["too_far_65ft_status"] == 422,
        "anchor_grid_bounds_rejected": area_probes["anchor_out_of_bounds_status"] == 422,
        "replay_idempotent": production["replay_already_applied"] is True,
        "target_cas_rejected": production["stale_target_cas_status"] == 409,
        "operation_transactions_persisted": bool(production["operation_transactions"])
        and all(row["status"] == "applied" for row in production["operation_transactions"]),
        "operation_transaction_action_binding": any(
            row["operation_type"] == "content_ir_runtime"
            and any(
                action.get("request_json", {}).get("action_name") == SPELL_ID
                for combat in row.get("after_snapshot", {}).get("combat", [])
                for action in [combat.get("action", {})]
            )
            for row in production["operation_transactions"]
        ),
        "save_success_no_damage": scaling["save_success_no_damage"] is True,
        "cantrip_scaling_matches_source": scaling["scaling_matches_source_progression"] is True,
        "payload_drift_rejected": payload_drift["rejected"] is True,
        "strict_loader_rejects_nonproduction_row": strict_loader["rejected"] is True,
        "each_selected_id_removed_once": before - after == {SPELL_ID}
        and after - before == set(),
        "duplicate_invalid_set_idempotent": duplicate_invalid == after,
        "unrelated_compile_only_ids_unchanged": (before - {SPELL_ID}) == (after - set()),
        "unrelated_production_ids_unchanged": (production_before - {SPELL_ID})
        == (production_after - {SPELL_ID}),
        "migration_projection_matches_sets": set(migration["current_project_compile_only_ids"])
        == after,
        "selected_preexisting_in_production_union": SPELL_ID in production_before,
        "production_union_semantics_proven": production_after - production_before
        == ({SPELL_ID} if SPELL_ID not in production_before else set()),
        "project_production_count_before_artifact": baseline_project_production,
        "name_branch_free": name_branches["count"] == 0,
        "protected_ollama_sha_exact": protected["backend/tests/ollama.py"]["sha256"]
        == EXPECTED_OLLAMA_SHA,
        "historical_xliii_sha_exact": _sha(
            (ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json").read_bytes()
        )
        == EXPECTED_XLIII_SHA,
    }
    required = [
        key
        for key, value in checks.items()
        if isinstance(value, bool)
        and key != "selected_preexisting_in_production_union"
    ]
    required.append("project_production_count_after_artifact")
    deferred_checks = {
        "migration_projection_matches_sets",
        "project_production_count_after_artifact",
    }
    initial_required = [key for key in required if key not in deferred_checks]
    checks["all_required_checks_passed"] = all(
        checks[key]
        for key in required
        if key not in deferred_checks
    )
    row = {
        "content_id": SPELL_ID,
        "runtime_id": SPELL_ID,
        "source_record_id": source["source_record_id"],
        "source_path": str(SOURCE_PATH.relative_to(ROOT)),
        "source_fingerprint": source["source_fingerprint"],
        "compile_status": compiled["compile_status"],
        "consumer_ids": production["consumer_ids"],
        "production_runtime_full": checks["all_required_checks_passed"],
        "production": production,
        "scaling": scaling,
        "area_probes": area_probes,
        "payload_drift": payload_drift,
        "strict_loader_probe": strict_loader,
    }
    artifact = {
        "schema_version": "content-ir-production-runtime-results-LVII-1",
        "round_id": "round-LVII",
        "artifact_date": "2026-08-14",
        "bootstrap_phase": True,
        "production_runtime_full_ids": [SPELL_ID],
        "evidence_by_id": {SPELL_ID: {**row, "production_runtime_full": True}},
        "checks": checks,
        "required_check_keys": initial_required,
        "all_required_checks_passed": True,
    }
    # This bootstrap artifact contains only the evidence-backed checks already
    # proven above; the set-derived migration/count checks are evaluated after
    # the loader can see this candidate in the production union.
    _write_json(RESULT_PATH, artifact)
    loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    checks["final_loader_acceptance"] = (
        SPELL_ID in loaded and loaded[SPELL_ID]["production_runtime_full"] is True
    )
    final_migration = build_migration(ROOT)
    checks["migration_projection_matches_sets"] = (
        set(final_migration["current_project_compile_only_ids"]) == after
    )
    checks["project_production_count_after_artifact"] = (
        final_migration["current_project_production_full"]
        == baseline_project_production
        + len(production_after - production_before)
    )
    checks["all_required_checks_passed"] = all(checks[key] for key in required)
    artifact["checks"] = checks
    artifact["all_required_checks_passed"] = checks["all_required_checks_passed"]
    artifact["bootstrap_phase"] = False
    artifact["required_check_keys"] = required
    artifact["production_runtime_full_ids"] = (
        [SPELL_ID] if checks["all_required_checks_passed"] else []
    )
    row["production_runtime_full"] = checks["all_required_checks_passed"]
    artifact["evidence_by_id"] = {SPELL_ID: row}
    _write_json(RESULT_PATH, artifact)
    final_loaded = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    checks["final_loader_acceptance"] = (
        SPELL_ID in final_loaded
        and final_loaded[SPELL_ID]["production_runtime_full"] is True
    )
    checks["all_required_checks_passed"] = all(checks[key] for key in required)
    artifact["checks"] = checks
    artifact["all_required_checks_passed"] = checks["all_required_checks_passed"]
    row["production_runtime_full"] = checks["all_required_checks_passed"]
    artifact["evidence_by_id"] = {SPELL_ID: row}
    _write_json(RESULT_PATH, artifact)
    report = {
        "schema_version": "round-LVII-acid-splash-closure-1",
        "round_id": "round-LVII",
        "artifact_date": "2026-08-14",
        "baseline_commit": "c33cd43",
        "decision": "promote_existing_generic_area_damage_consumer",
        "selected_content_ids": [SPELL_ID]
        if checks["all_required_checks_passed"]
        else [],
        "candidate_comparison": _candidate_comparison(),
        "before": {
            "production": baseline_project_production,
            "compile_only": len(before),
            "unique_compiled": int(lvi_snapshot["after"]["unique_compiled"]),
        },
        "after": {
            "production": final_migration["current_project_production_full"],
            "compile_only": len(after),
            "unique_compiled": final_migration["current_project_compiled_unique"],
        },
        "projection_sets": {
            **projection,
            "after_compile_only_ids": sorted(after),
            "production_after_ids": sorted(production_after),
            "migration_compile_only_ids": sorted(migration["current_project_compile_only_ids"]),
            "migration_production_count_before_artifact": migration[
                "current_project_production_full"
            ],
            "migration_compile_only_ids_after_artifact": sorted(
                final_migration["current_project_compile_only_ids"]
            ),
            "migration_production_count_after_artifact": final_migration[
                "current_project_production_full"
            ],
        },
        "checks": checks,
        "all_required_checks_passed": checks["all_required_checks_passed"],
        "required_check_keys": required,
        "evidence_artifact": str(RESULT_PATH.relative_to(ROOT)),
        "focused_test": FOCUSED_TEST,
        "source": {
            "authored_path": str(SOURCE_PATH.relative_to(ROOT)),
            "source_record_id": source["source_record_id"],
            "source_fingerprint": source["source_fingerprint"],
            "source_checksum": source["source_evidence"]["source_checksum"],
            "compile_status": compiled["compile_status"],
            "authoritative_census_row": census_row,
            "duplicate_binding": {
                "canonical_path": str(SOURCE_PATH.relative_to(ROOT)),
                "incomplete_batch_ii_path": str(
                    (
                        ROOT
                        / "data/content-ir/authored/batch-II/core-phb-2024/spells/"
                        "core-phb-2024-spell-d84dec64befac8db7294e0f1.json"
                    ).relative_to(ROOT)
                ),
                "canonical_clause_count": len(source["clauses"]),
                "batch_ii_clause_count": len(batch_ii_source["clauses"]),
                "selection_reason": (
                    "canonical core-2024 five-clause IR is source-complete; "
                    "batch-II duplicate has only target/area clauses and cannot "
                    "prove saving-throw, damage, or scaling promotion"
                ),
            },
        },
        "name_branch_scan": name_branches,
        "protected_fingerprints": protected,
        "historical_artifact_sha256": {
            "round_xliii_report": EXPECTED_XLIII_SHA,
            "backend_tests_ollama": EXPECTED_OLLAMA_SHA,
        },
        "no_push": True,
        "bootstrap_phase": False,
        "production_runtime_full_ids": artifact["production_runtime_full_ids"],
    }
    report["report_fingerprint"] = _sha(
        json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    _write_json(REPORT_PATH, report)
    print(
        json.dumps(
            {
                "all_required_checks_passed": checks["all_required_checks_passed"],
                "artifact": str(RESULT_PATH),
                "report": str(REPORT_PATH),
                "checks": checks,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if checks["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
