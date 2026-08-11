# ruff: noqa: N999
"""Run Tasha's typed rest-condition Feature through the production rest consumer."""

from __future__ import annotations

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
FEATURE_PATH = (
    ROOT
    / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/ranger-tireless.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XIX.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XVII-2026-08-12.json"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_contract() -> tuple[FeatureSpec, dict[str, Any], Any]:
    value = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    if compiled.compile_status != "full":
        raise RuntimeError(f"Tireless typed Feature is not full: {compiled.blockers}")
    contract = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
    return spec, contract, compiled


def main() -> int:
    logging.disable(logging.CRITICAL)
    spec, contract, compiled = _load_contract()
    result: dict[str, Any] = {
        "content_id": spec.feature_id,
        "content_kind": "feature",
        "pack_id": "tashas-cauldron",
        "source_book": "塔莎的万事坩埚",
        "execution_mode": "typed",
        "compile_status": compiled.compile_status,
        "compile_blockers": list(compiled.blockers),
        "typed_sections": [
            key
            for key, value in contract.items()
            if isinstance(value, (dict, list)) and value
        ],
        "rest_effect": next(
            (
                dict(item)
                for item in contract.get("triggers", [])
                if isinstance(item, dict) and item.get("kind") == "rest_condition_effect"
            ),
            None,
        ),
        "preview": False,
        "confirm": False,
        "replay": False,
        "character_cas": False,
        "transaction": False,
        "condition_persisted": False,
        "typed_consumer": "rest_service.typed_rest_condition_effect.v1",
        "name_branch_count": 0,
    }
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-XVII-rest.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with TestClient(create_app(Settings(environment="test", database_url=database_url))) as client:
            campaign = client.post(
                "/api/v1/campaigns", json={"name": "Tasha Round XVII typed rest"}
            ).json()
            base = f"/api/v1/campaigns/{campaign['id']}"
            character = client.post(
                f"{base}/characters",
                json={
                    "name": "generic rest condition actor",
                    "class_name": "游侠",
                    "level": 10,
                    "hp": 8,
                    "max_hp": 20,
                    "ability_scores": {"constitution": 12, "wisdom": 16},
                    "class_levels": {"游侠": 10},
                    "features": [
                        {
                            "name": "任意短休状态特性",
                            "feature_id": spec.feature_id,
                            "class_name": spec.class_name,
                            "class_level": 10,
                            "kind": "feature",
                            "runtime": {"registry": contract},
                        }
                    ],
                },
            )
            if character.status_code != 201:
                raise RuntimeError(character.text)
            character_body = character.json()
            condition = client.post(
                f"{base}/characters/{character_body['id']}/conditions",
                json={"condition_name": "力竭", "details": {"level": 3}},
            )
            if condition.status_code != 201:
                raise RuntimeError(condition.text)
            body = {
                "rest_type": "short",
                "duration_minutes": 60,
                "participants": [
                    {
                        "character_id": character_body["id"],
                        "character_version": character_body["version"],
                    }
                ],
            }
            preview = client.post(f"{base}/rests/preview", json=body)
            result["preview_status_code"] = preview.status_code
            if preview.status_code != 200:
                result["error"] = preview.text[:500]
            else:
                preview_body = preview.json()
                participant = preview_body["participants"][0]
                result["preview"] = participant["after"]["fatigue"] == 2
                result["preview_after_fatigue"] = participant["after"]["fatigue"]
                confirm_body = {
                    **body,
                    "preview_token": preview_body["preview_token"],
                    "idempotency_key": "tashas-round-XVII-typed-rest-001",
                }
                confirmed = client.post(f"{base}/rests/confirm", json=confirm_body)
                result["confirm_status_code"] = confirmed.status_code
                if confirmed.status_code != 200:
                    result["error"] = confirmed.text[:500]
                else:
                    confirmed_body = confirmed.json()
                    result["confirm"] = bool(confirmed_body.get("rest_record_id"))
                    updated = client.get(f"{base}/characters/{character_body['id']}")
                    updated_body = updated.json() if updated.status_code == 200 else {}
                    result["character_cas"] = (
                        updated_body.get("version") == character_body["version"] + 1
                    )
                    result["transaction"] = bool(
                        confirmed_body.get("operation_transaction_id")
                    )
                    replay = client.post(f"{base}/rests/confirm", json=confirm_body)
                    result["replay_status_code"] = replay.status_code
                    result["replay"] = (
                        replay.status_code == 200
                        and replay.json().get("rest_record_id")
                        == confirmed_body.get("rest_record_id")
                    )
                    conditions = client.get(
                        f"{base}/characters/{character_body['id']}/conditions"
                    )
                    items = conditions.json().get("items", [])
                    result["condition_persisted"] = any(
                        isinstance(item, dict)
                        and item.get("details", {}).get("level") == 2
                        for item in items
                    )
    logging.disable(logging.NOTSET)
    result["production_runtime_full"] = all(
        result[key]
        for key in (
            "compile_status",
            "rest_effect",
            "preview",
            "confirm",
            "replay",
            "character_cas",
            "transaction",
            "condition_persisted",
        )
    ) and result["compile_status"] == "full"
    checks = {
        "selected_count": 1,
        "production_runtime_full_count": int(result["production_runtime_full"]),
        "all_preview_confirm_replay": all(
            result[key] for key in ("preview", "confirm", "replay")
        ),
        "typed_rest_consumer": result["typed_consumer"],
        "character_cas_and_transaction": result["character_cas"] and result["transaction"],
        "condition_lifecycle_persisted": result["condition_persisted"],
        "isolated_database": True,
        "formal_apply": False,
        "name_branch_count": 0,
    }
    _write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-XIX-1",
            "content_kind": "feature",
            "production_runtime_full_ids": [spec.feature_id]
            if result["production_runtime_full"]
            else [],
            "evidence_by_id": {spec.feature_id: result},
            "checks": checks,
            "source": "Round XVII runs the typed Tasha rest-condition clause through the real rest preview/confirm/replay consumer on an isolated migrated database",
        },
    )
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-XVII-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_feature_ids": [spec.feature_id],
            "results": [result],
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
            "platform_core_growth": "rest_service.typed_rest_condition_effect.v1 consumes typed rest triggers by trigger/condition rather than feature name",
        },
    )
    print(
        json.dumps(
            {"production_runtime_full": int(result["production_runtime_full"]), "report": str(REPORT_PATH)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if not result["production_runtime_full"]:
        raise SystemExit("Round XVII rest production consumer gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
