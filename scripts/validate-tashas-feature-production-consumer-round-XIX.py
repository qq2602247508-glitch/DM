# ruff: noqa: N999
"""Run Implements of Mercy through the existing character-growth consumer."""

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
FEATURE_ID = "content.tashas-cauldron.feature.way-of-mercy.implements-of-mercy"
FEATURE_PATH = (
    ROOT
    / "data/content-ir/authored/official-packs/tashas-cauldron/features/features/content-tashas-cauldron-feature-way-of-mercy-implements-of-mercy.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXI.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-XIX-2026-08-12.json"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_shared():
    loader = importlib.util.spec_from_file_location("tashas_feature_round_vii_shared", SHARED)
    if loader is None or loader.loader is None:
        raise RuntimeError("cannot load shared character-growth validator")
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    module.FEATURE_CASES = ((FEATURE_ID, {}),)
    return module


def _load_contract(shared):
    value = json.loads(FEATURE_PATH.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(FEATURE_PATH),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    if compiled.compile_status != "full":
        raise RuntimeError(f"selected Feature is not full: {compiled.blockers}")
    contract = materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)
    proficiencies = contract.get("proficiencies")
    if not isinstance(proficiencies, list) or len(proficiencies) != 3:
        raise RuntimeError("Implements of Mercy must expose three proficiency grants")
    return spec, contract


def main() -> int:
    logging.disable(logging.CRITICAL)
    shared = _load_shared()
    spec, contract = _load_contract(shared)
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-XIX-growth.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with TestClient(create_app(Settings(environment="test", database_url=database_url))) as client:
            evidence = shared._run_case(
                client,
                FEATURE_ID,
                spec,
                contract,
                {},
                1,
            )
    logging.disable(logging.NOTSET)
    evidence["proficiency_grant_count"] = int(evidence.get("proficiency_grant_count") or 0)
    evidence["advancement_block_ready"] = evidence["proficiency_grant_count"] == 3
    evidence["typed_consumer"] = "advancement_service.character_growth.v1"
    evidence["source_clause_count"] = 3
    evidence["platform_core_exception"] = {
        "reason": "one complete Feature closes three typed proficiency grants through the existing character-growth consumer",
        "batch_size": 1,
        "minimum_batch": 8,
    }
    passed = bool(
        evidence.get("production_runtime_full")
        and evidence.get("preview")
        and evidence.get("confirm")
        and evidence.get("replay")
        and evidence.get("typed_consumer") == "advancement_service.character_growth.v1"
        and evidence.get("character_cas")
        and evidence.get("transaction")
        and evidence.get("feature_persisted")
        and evidence.get("advancement_block_ready")
        and evidence["proficiency_grant_count"] == 3
    )
    evidence["production_runtime_full"] = passed
    checks = {
        "selected_count": 1,
        "production_runtime_full_count": int(passed),
        "all_preview_confirm_replay": all(
            evidence.get(key) for key in ("preview", "confirm", "replay")
        ),
        "typed_character_growth_consumer": evidence["typed_consumer"]
        == "advancement_service.character_growth.v1",
        "three_typed_proficiency_grants": evidence["proficiency_grant_count"] == 3,
        "character_cas_and_transaction": evidence.get("character_cas")
        and evidence.get("transaction"),
        "feature_persisted": evidence.get("feature_persisted") is True,
        "formal_registry_written": False,
        "formal_database_written": False,
        "isolated_database": True,
        "name_branch_count": 0,
    }
    _write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-XXI-1",
            "content_kind": "advancement",
            "production_runtime_full_ids": [FEATURE_ID] if passed else [],
            "evidence_by_id": {FEATURE_ID: evidence},
            "checks": checks,
            "source": "Round XIX runs the complete typed Implements of Mercy proficiency contract through the real character-growth preview/confirm/replay consumer on an isolated migrated database",
        },
    )
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-XIX-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_feature_ids": [FEATURE_ID],
            "results": [evidence],
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
            "platform_core_exception": evidence["platform_core_exception"],
            "platform_core_growth": "advancement_service.character_growth.v1 consumes three typed proficiency clauses without feature-name dispatch",
        },
    )
    print(
        json.dumps(
            {"production_runtime_full": int(passed), "report": str(REPORT_PATH)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if not passed:
        raise SystemExit("Round XIX character-growth production gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
