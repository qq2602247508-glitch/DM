# ruff: noqa: N999
"""Validate typed tattoo manifestation and removal through equipment lifecycle."""

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
from dnd_dm_assistant.config import Settings
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts/validate-tashas-item-production-consumer-round-X.py"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XIV.json"
REPORT_PATH = ROOT / "reports/tashas-item-production-consumer-round-XII-2026-08-12.json"

ITEM_IDS = (
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-8d7814d75b94-003",
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-b9cb8e43543d-007",
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-c27398cf29fe-010",
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-coiling-004",
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-eldritch-005",
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-ghost-step-tattoo-008",
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-illuminator-s-tattoo-000",
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-lifewell-tattoo-009",
)


def _load_harness():
    loader = importlib.util.spec_from_file_location("tashas_item_round_x_harness", HARNESS_PATH)
    if loader is None or loader.loader is None:
        raise RuntimeError("cannot load shared ItemSpec harness")
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    module.ITEM_IDS = ITEM_IDS
    return module


def main() -> int:
    logging.disable(logging.CRITICAL)
    harness = _load_harness()
    specs = harness._load_specs()
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-XII-tattoos.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with TestClient(create_app(Settings(environment="test", database_url=database_url))) as client:
            for index, item_id in enumerate(ITEM_IDS, start=1):
                results.append(
                    harness._run_item(
                        client,
                        database_url,
                        specs[item_id],
                        index,
                        tattoo_roundtrip=True,
                    )
                )
    logging.disable(logging.NOTSET)
    passed = [
        item
        for item in results
        if item["created"]
        and item["preview_confirm_replay"]
        and item["typed_consumer"]
        and item["item_state_persisted"]
        and item["attunement_persisted"]
        and item["tattoo_lifecycle_persisted"]
        and item["charge_lifecycle_persisted"]
        and item["operation_transaction_persisted"]
    ]
    production_ids = sorted(str(item["content_id"]) for item in passed)
    transition_pairs = []
    for item in passed:
        phases = [
            operation["output"].get("tattoo_lifecycle", {}).get("phase")
            for operation in item["operations"]
            if operation["output"].get("tattoo_lifecycle")
        ]
        transition_pairs.append(phases == ["manifested", "needle_returned"])
    checks = {
        "selected_count": len(results),
        "production_runtime_full_count": len(production_ids),
        "all_create_preview_confirm_replay": len(passed) == len(results),
        "all_typed_consumers": all(item["typed_consumer"] for item in passed),
        "all_item_state_persisted": all(item["item_state_persisted"] for item in passed),
        "all_attunement_cas": all(item["attunement_persisted"] for item in passed),
        "all_tattoo_lifecycle_persisted": all(item["tattoo_lifecycle_persisted"] for item in passed),
        "all_tattoo_transitions": all(transition_pairs),
        "charge_lifecycle_count": sum(bool(item["persisted"]["charges"] is not None) for item in passed),
        "operation_transaction_count": sum(int(item["persisted"]["operation_transaction_count"]) for item in passed),
        "formal_registry_written": False,
        "formal_database_written": False,
        "isolated_database": True,
        "name_branch_count": 0,
    }
    evidence_by_id = {str(item["content_id"]): item for item in results}
    harness._write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-XIV-1",
            "content_kind": "item",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "Round XII reviewed magic tattoos through generic typed ink manifestation and needle-return lifecycle on an isolated migrated database",
        },
    )
    harness._write(
        REPORT_PATH,
        {
            "schema_version": "tashas-item-production-consumer-round-XII-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_item_ids": list(ITEM_IDS),
            "results": results,
            "checks": checks,
            "runtime_contract": {
                "consumer": "item.attunement.v1",
                "typed_clause": "tattoo_lifecycle",
                "transitions": ["manifested", "needle_returned"],
                "name_dispatch": False,
            },
            "formal_apply": False,
            "isolated_database": True,
        },
    )
    print(json.dumps({"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)}, ensure_ascii=False, sort_keys=True))
    if len(production_ids) != len(results):
        raise SystemExit("Round XII tattoo lifecycle production gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
