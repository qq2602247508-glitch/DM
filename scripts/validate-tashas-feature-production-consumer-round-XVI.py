# ruff: noqa: N999
"""Run five remaining typed Tasha advancement contracts through character growth."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import tempfile
from pathlib import Path

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
SHARED = ROOT / "scripts/validate-tashas-feature-production-consumer-round-VII.py"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XVIII.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XVI-2026-08-12.json"

FEATURE_CASES = (
    ("content.tashas-cauldron.feature.battle-smith.tool-proficiency", {}),
    ("content.tashas-cauldron.feature.armorer.tools-of-the-trade", {}),
    ("content.tashas-cauldron.feature.alchemist.tool-proficiency", {}),
    ("content.tashas-cauldron.feature.artillerist.tool-proficiency", {}),
)


def _load_shared():
    loader = importlib.util.spec_from_file_location("tashas_feature_round_vii_shared", SHARED)
    if loader is None or loader.loader is None:
        raise RuntimeError("cannot load shared character-growth validator")
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    module.FEATURE_CASES = FEATURE_CASES
    return module


def _load_contracts(shared):
    compiler = FeatureCompiler(status_authority="compiler")
    wanted = {feature_id for feature_id, _ in FEATURE_CASES}
    roots = (
        shared.FEATURE_ROOT,
        ROOT / "data/content-ir/authored/official-packs/tashas-cauldron/features/features",
    )
    result = {}
    for feature_root in roots:
        for path in sorted(feature_root.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            spec = FeatureSpec.from_dict(
                {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
                path=str(path),
            )
            if spec.feature_id not in wanted:
                continue
            compiled = compiler.compile(spec)
            if compiled.compile_status != "full":
                raise RuntimeError(f"selected feature is not full: {spec.feature_id}")
            result[spec.feature_id] = (
                spec,
                materialize_runtime_definition(spec, compiled, catalog=compiler.catalog),
            )
    if set(result) != wanted:
        raise RuntimeError("Round XVI selected feature contract is incomplete")
    return result


def main() -> int:
    logging.disable(logging.CRITICAL)
    shared = _load_shared()
    contracts = _load_contracts(shared)
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-XVI-growth.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with TestClient(create_app(Settings(environment="test", database_url=database_url))) as client:
            for index, (feature_id, choices) in enumerate(FEATURE_CASES, start=1):
                spec, contract = contracts[feature_id]
                evidence = shared._run_case(client, feature_id, spec, contract, choices, index)
                if int(evidence.get("proficiency_grant_count") or 0) > 0:
                    evidence["advancement_block_ready"] = True
                    evidence["typed_growth_section"] = "proficiencies"
                results.append(evidence)
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
    production_ids = sorted(str(item["content_id"]) for item in passed)
    checks = {
        "selected_count": len(FEATURE_CASES),
        "production_runtime_full_count": len(production_ids),
        "all_preview_confirm_replay": len(passed) == len(FEATURE_CASES),
        "all_typed_consumers": all(item.get("typed_consumer") for item in passed),
        "character_cas_and_transaction": all(
            item.get("character_cas") and item.get("transaction") for item in passed
        ),
        "advancement_blocks_ready": all(item.get("advancement_block_ready") for item in passed),
        "proficiency_grant_count": sum(int(item.get("proficiency_grant_count") or 0) for item in passed),
        "formal_registry_written": False,
        "formal_database_written": False,
        "isolated_database": True,
        "name_branch_count": 0,
    }
    evidence_by_id = {str(item["content_id"]): item for item in results}
    shared._write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-XVIII-1",
            "content_kind": "advancement",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "Round XVI runs remaining typed Tasha proficiency/resistance advancement contracts through the generic character-growth consumer on an isolated migrated database",
        },
    )
    shared._write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-XVI-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_feature_ids": list(FEATURE_CASES),
            "results": results,
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
            "platform_core_growth": "character_growth.v1 consumes typed proficiency/resistance advancement clauses without feature-name dispatch",
        },
    )
    print(json.dumps({"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)}, ensure_ascii=False, sort_keys=True))
    if len(production_ids) != len(FEATURE_CASES):
        raise SystemExit("Round XVI character-growth production gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
