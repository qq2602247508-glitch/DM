# ruff: noqa: N999
"""Run typed item-cast spell lists through the generic equipment consumer."""

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
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XVII.json"
REPORT_PATH = ROOT / "reports/tashas-item-production-consumer-round-XV-2026-08-12.json"

ITEM_IDS = (
    "content.tashas-cauldron.item.tashas-cauldron-atom-760b230e1396825928305642-3e9825c326a3-003",
    "content.tashas-cauldron.item.tashas-cauldron-atom-760b230e1396825928305642-db0e19f5d68b-001",
    "content.tashas-cauldron.item.tashas-cauldron-atom-760b230e1396825928305642-demonomiconofiggwilv-002",
)


def _load_harness():
    loader = importlib.util.spec_from_file_location("tashas_item_round_x_harness", HARNESS_PATH)
    if loader is None or loader.loader is None:
        raise RuntimeError("cannot load shared ItemSpec harness")
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    module.ITEM_IDS = ITEM_IDS
    return module


def _spell_consumer_persisted(item: dict[str, object]) -> bool:
    for operation in item["operations"]:
        output = operation.get("output")
        after = output.get("after") if isinstance(output, dict) else None
        spell_cast = after.get("item_spell_cast") if isinstance(after, dict) else None
        if (
            isinstance(spell_cast, dict)
            and spell_cast.get("consumer_id") == "item.granted_spell.v1"
            and spell_cast.get("grant_mode") == "item_cast"
            and spell_cast.get("spell_identities")
        ):
            return True
    return False


def main() -> int:
    logging.disable(logging.CRITICAL)
    harness = _load_harness()
    specs = harness._load_specs()
    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-XV-items.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with TestClient(create_app(Settings(environment="test", database_url=database_url))) as client:
            for index, item_id in enumerate(ITEM_IDS, start=1):
                results.append(harness._run_item(client, database_url, specs[item_id], index))
    logging.disable(logging.NOTSET)
    passed = [
        item
        for item in results
        if item["created"]
        and item["preview_confirm_replay"]
        and item["typed_consumer"]
        and item["item_state_persisted"]
        and item["attunement_persisted"]
        and item["charge_lifecycle_persisted"]
        and item["operation_transaction_persisted"]
        and _spell_consumer_persisted(item)
    ]
    production_ids = sorted(str(item["content_id"]) for item in passed)
    spell_identity_count = sum(
        len(
            operation["output"]["after"]["item_spell_cast"]["spell_identities"]
        )
        for item in passed
        for operation in item["operations"]
        if isinstance(operation.get("output"), dict)
        and isinstance(operation["output"].get("after"), dict)
        and isinstance(operation["output"]["after"].get("item_spell_cast"), dict)
    )
    checks = {
        "selected_count": len(results),
        "production_runtime_full_count": len(production_ids),
        "all_create_preview_confirm_replay": len(passed) == len(results),
        "all_typed_consumers": all(item["typed_consumer"] for item in passed),
        "all_item_state_persisted": all(item["item_state_persisted"] for item in passed),
        "all_attunement_cas": all(item["attunement_persisted"] for item in passed),
        "all_item_spell_consumers": all(_spell_consumer_persisted(item) for item in passed),
        "spell_identity_count": spell_identity_count,
        "charge_lifecycle_count": sum(bool(item["persisted"]["charges"] is not None) for item in passed),
        "operation_transaction_count": sum(
            int(item["persisted"]["operation_transaction_count"]) for item in passed
        ),
        "formal_registry_written": False,
        "formal_database_written": False,
        "isolated_database": True,
        "name_branch_count": 0,
    }
    evidence_by_id = {str(item["content_id"]): item for item in results}
    harness._write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-XVII-1",
            "content_kind": "item",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "Round XV runs typed item-cast spell lists through the generic equipment action consumer on an isolated migrated database",
        },
    )
    harness._write(
        REPORT_PATH,
        {
            "schema_version": "tashas-item-production-consumer-round-XV-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_item_ids": list(ITEM_IDS),
            "results": results,
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
            "platform_core_growth": "item.granted_spell.v1 now materializes typed item-cast spell identities in the equipment action preview/transaction snapshot",
        },
    )
    print(
        json.dumps(
            {"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if len(production_ids) != len(results) or spell_identity_count < 10:
        raise SystemExit("Round XV ItemSpec spell consumer gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
