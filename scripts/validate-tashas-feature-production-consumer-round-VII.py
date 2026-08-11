# ruff: noqa: N999
"""Validate the generic typed character-growth consumer for Tasha Feature IR."""

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
FEATURE_ROOT = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-IX.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-VII-2026-08-12.json"

FEATURE_CASES: tuple[tuple[str, dict[str, list[str]]], ...] = (
    ("content.tashas-cauldron.round2.feature.alchemist-spell-list", {}),
    ("content.tashas-cauldron.round2.feature.clockwork-soul-clockwork-magic", {}),
    (
        "content.tashas-cauldron.round2.feature.feat-fey-touched",
        {
            "chosen_divination_or_enchantment_1": ["detect_magic"],
            "chosen_ability": ["wisdom"],
        },
    ),
    (
        "content.tashas-cauldron.round2.feature.feat-shadow-touched",
        {
            "chosen_illusion_or_necromancy_1": ["silent_image"],
            "chosen_ability": ["charisma"],
        },
    ),
    (
        "content.tashas-cauldron.round2.feature.paladin-blessed-warrior",
        {"chosen_cleric_cantrip_1": ["guidance"], "chosen_cleric_cantrip_2": ["sacred_flame"]},
    ),
    ("content.tashas-cauldron.round2.feature.psi-warrior-telekinetic-master", {}),
    (
        "content.tashas-cauldron.round2.feature.ranger-druidic-warrior",
        {"chosen_druid_cantrip_1": ["druidcraft"], "chosen_druid_cantrip_2": ["thorn_whip"]},
    ),
    ("content.tashas-cauldron.round2.feature.swarmkeeper-spell-list", {}),
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_contracts() -> dict[str, tuple[FeatureSpec, dict[str, Any]]]:
    compiler = FeatureCompiler(status_authority="compiler")
    result: dict[str, tuple[FeatureSpec, dict[str, Any]]] = {}
    for path in sorted(FEATURE_ROOT.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        spec = FeatureSpec.from_dict(
            {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
            path=str(path),
        )
        if spec.feature_id not in {feature_id for feature_id, _ in FEATURE_CASES}:
            continue
        compiled = compiler.compile(spec)
        if compiled.compile_status != "full":
            raise RuntimeError(f"selected feature is not full: {spec.feature_id}")
        contract = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
        advancement = contract.get("advancement")
        if not isinstance(advancement, dict):
            raise TypeError(f"selected feature lacks advancement block: {spec.feature_id}")
        result[spec.feature_id] = (spec, contract)
    expected = {feature_id for feature_id, _ in FEATURE_CASES}
    if set(result) != expected:
        raise RuntimeError("Round VII selected feature contract is incomplete")
    return result


def _run_case(
    client: TestClient,
    feature_id: str,
    spec: FeatureSpec,
    contract: dict[str, Any],
    choices: dict[str, list[str]],
    index: int,
) -> dict[str, Any]:
    campaign = client.post(
        "/api/v1/campaigns", json={"name": "Tasha Round VII character growth"}
    ).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": "Tasha typed growth actor",
            "class_name": spec.class_name or "玩家角色",
            "level": max(1, int(spec.level or 5)),
            "hp": 20,
            "max_hp": 20,
        },
    ).json()
    body = {
        "content_kind": "advancement",
        "runtime_id": feature_id,
        "permission": "player",
        "character_id": character["id"],
        "character_version": character["version"],
        "advancement_choices": choices,
        "runtime_contract": contract,
        "idempotency_key": f"tashas-round-VII-growth-{index:03d}",
    }
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    evidence: dict[str, Any] = {
        "content_id": feature_id,
        "content_kind": "advancement",
        "pack_id": "tashas-cauldron",
        "source": "round-II-reviewed-feature-runtime-through-round-VII-character-consumer",
        "execution_mode": "typed",
        "preview": preview.status_code == 200,
        "typed_contract": True,
        "typed_consumer": None,
        "character_cas": False,
        "transaction": False,
        "choice_lifecycle": bool(choices),
        "advancement_block_ready": False,
    }
    if preview.status_code != 200:
        evidence["error"] = preview.text[:500]
        return evidence
    preview_body = preview.json()
    evidence["advancement_block_ready"] = bool(
        preview_body.get("production_contract", {}).get("typed_sections")
        and "advancement" in preview_body["production_contract"]["typed_sections"]
    )
    confirm_body = {**body, "preview_token": preview_body["preview_token"]}
    confirmed = client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    evidence.update(
        {
            "confirm": confirmed.status_code == 200,
            "production_runtime_full": (
                bool(confirmed.json().get("production_runtime_full"))
                if confirmed.status_code == 200
                else False
            ),
            "typed_consumer": (
                confirmed.json().get("consumer") if confirmed.status_code == 200 else None
            ),
        }
    )
    if confirmed.status_code != 200:
        evidence["error"] = confirmed.text[:500]
        return evidence
    replay = client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    after = client.get(f"{base}/characters/{character['id']}")
    after_body = after.json() if after.status_code == 200 else {}
    result = confirmed.json()
    feature_present = any(
        isinstance(item, dict) and item.get("feature_id") == feature_id
        for item in after_body.get("features", [])
    )
    evidence.update(
        {
            "replay": replay.status_code == 200 and replay.json().get("already_applied") is True,
            "character_cas": result.get("character_version_after") == character["version"] + 1,
            "transaction": bool(result.get("operation_transaction_id")),
            "feature_persisted": feature_present,
            "proficiency_grant_count": len(result.get("proficiency_grants") or []),
            "spell_grant_count": len(result.get("spell_grants") or []),
            "selected_choices": choices,
        }
    )
    if not evidence["replay"] or not evidence["feature_persisted"]:
        evidence["error"] = replay.text[:500]
    return evidence


def main() -> int:
    logging.disable(logging.CRITICAL)
    contracts = _load_contracts()
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-VII.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            for index, (feature_id, choices) in enumerate(FEATURE_CASES, start=1):
                spec, contract = contracts[feature_id]
                results.append(_run_case(client, feature_id, spec, contract, choices, index))
    logging.disable(logging.NOTSET)
    passed = [
        item
        for item in results
        if item.get("production_runtime_full")
        and item.get("preview")
        and item.get("confirm")
        and item.get("replay")
        and item.get("typed_consumer") == "advancement_service.character_growth.v1"
        and item.get("character_cas")
        and item.get("transaction")
        and item.get("feature_persisted")
        and item.get("advancement_block_ready")
    ]
    production_ids = sorted(item["content_id"] for item in passed)
    checks = {
        "selected_count": len(FEATURE_CASES),
        "production_runtime_full_count": len(production_ids),
        "all_preview_confirm_replay": len(passed) == len(FEATURE_CASES),
        "all_typed_consumers": all(item.get("typed_consumer") for item in passed),
        "character_cas_and_transaction": all(
            item.get("character_cas") and item.get("transaction") for item in passed
        ),
        "advancement_blocks_ready": all(item.get("advancement_block_ready") for item in passed),
        "choice_lifecycle_consumers": sum(bool(item.get("choice_lifecycle")) for item in passed),
        "grant_spell_consumer": any(item.get("spell_grant_count", 0) > 0 for item in passed),
        "formal_registry_written": False,
        "formal_database_written": False,
        "name_branch_count": 0,
    }
    evidence_by_id = {item["content_id"]: item for item in results}
    _write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-IX-1",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "Round-II reviewed Feature IR through real ContentIRRuntimeService character advancement on an isolated migrated database",
        },
    )
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-VII-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_feature_ids": [feature_id for feature_id, _ in FEATURE_CASES],
            "results": results,
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
        },
    )
    print(
        json.dumps(
            {"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if len(production_ids) != len(FEATURE_CASES):
        raise SystemExit("Round VII production consumer gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
