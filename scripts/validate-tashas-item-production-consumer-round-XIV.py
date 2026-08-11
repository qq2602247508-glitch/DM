# ruff: noqa: N999
"""Close the remaining complete ItemSpecs through generic item consumers."""

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
from dnd_dm_assistant.infrastructure.database.models import Character, EquipmentInstance
from dnd_dm_assistant.infrastructure.database.rest_service import RestService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = ROOT / "scripts/validate-tashas-item-production-consumer-round-X.py"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XVI.json"
REPORT_PATH = ROOT / "reports/tashas-item-production-consumer-round-XIV-2026-08-12.json"

ITEM_IDS = (
    "content.tashas-cauldron.item.tashas-cauldron-atom-7f82da3807a304a28c05c79b-shadowfell-shard-017",
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-a92dd000492e-001",
    "content.tashas-cauldron.item.tashas-cauldron-atom-932a86d7b29c891ff8c75d2c-shadowfellbrand-tattoo-006",
    "content.tashas-cauldron.item.tashas-cauldron-atom-953875067ac4d9a793c844f0-6ad29778c06b-000",
    "content.tashas-cauldron.item.tashas-cauldron-atom-953875067ac4d9a793c844f0-771dcd20c4dc-001",
)
CHRONICLE_ID = ITEM_IDS[-1]


def _load_harness():
    loader = importlib.util.spec_from_file_location("tashas_item_round_x_harness", HARNESS_PATH)
    if loader is None or loader.loader is None:
        raise RuntimeError("cannot load shared ItemSpec harness")
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    module.ITEM_IDS = ITEM_IDS
    return module


def _probe_dawn_boundary(client: TestClient, database_url: str, spec: object) -> bool:
    campaign = client.post("/api/v1/campaigns", json={"name": "Tasha Round XIV dawn boundary"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={"name": "Tasha dawn boundary actor", "level": 5, "hp": 20, "max_hp": 20},
    ).json()
    created = client.post(
        f"{base}/characters/assets/equipment",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": spec.name,
            "category": spec.item_kind,
            "metadata_json": {"item_spec": spec.to_dict()},
        },
    )
    if created.status_code != 201:
        raise RuntimeError(f"dawn boundary equipment failed: {created.status_code} {created.text[:400]}")
    engine = create_engine(database_url)
    with Session(engine) as session, session.begin():
        equipment = session.get(EquipmentInstance, created.json()["id"])
        character_row = session.get(Character, character["id"])
        if equipment is None or character_row is None:
            raise RuntimeError("dawn boundary rows were not persisted")
        equipment.charges = 0
        changes = RestService._item_charge_recovery(
            session,
            character_row,
            effective_type="long",
            completed=True,
        )
        return changes == []


def main() -> int:
    logging.disable(logging.CRITICAL)
    harness = _load_harness()
    specs = harness._load_specs()
    results: list[dict[str, object]] = []
    dawn_not_rest_recovered = False
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-XIV-items.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with TestClient(create_app(Settings(environment="test", database_url=database_url))) as client:
            for index, item_id in enumerate(ITEM_IDS, start=1):
                spec = specs[item_id]
                results.append(
                    harness._run_item(
                        client,
                        database_url,
                        spec,
                        index,
                        tattoo_roundtrip=spec.item_kind == "magic_tattoo",
                    )
                )
            dawn_not_rest_recovered = _probe_dawn_boundary(client, database_url, specs[CHRONICLE_ID])
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
    chronicle = next(item for item in results if item["content_id"] == CHRONICLE_ID)
    chronicle_spec = specs[CHRONICLE_ID]
    checks = {
        "selected_count": len(results),
        "production_runtime_full_count": len(production_ids),
        "all_create_preview_confirm_replay": len(passed) == len(results),
        "all_typed_consumers": all(item["typed_consumer"] for item in passed),
        "all_item_state_persisted": all(item["item_state_persisted"] for item in passed),
        "all_attunement_cas": all(item["attunement_persisted"] for item in passed),
        "all_tattoo_lifecycle_persisted": all(item["tattoo_lifecycle_persisted"] for item in passed),
        "charge_lifecycle_count": sum(bool(item["persisted"]["charges"] is not None) for item in passed),
        "chronicle_dawn_recovery_typed": (
            chronicle["persisted"]["charges"] == 2
            and chronicle_spec.charges.get("recovery_trigger") == "dawn"
        ),
        "dawn_not_rest_recovered": dawn_not_rest_recovered,
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
            "schema_version": "content-ir-production-runtime-results-XVI-1",
            "content_kind": "item",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "Round XIV closes the remaining complete ItemSpecs through generic equipment, attunement, tattoo and charge consumers on an isolated migrated database",
        },
    )
    harness._write(
        REPORT_PATH,
        {
            "schema_version": "tashas-item-production-consumer-round-XIV-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_item_ids": list(ITEM_IDS),
            "results": results,
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
            "platform_core_growth": "typed residual ItemSpec closeout reuses generic equipment/attunement/action/charge consumers; dawn remains a typed world-time boundary",
        },
    )
    print(
        json.dumps(
            {"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if (
        len(production_ids) != len(results)
        or not checks["chronicle_dawn_recovery_typed"]
        or not checks["dawn_not_rest_recovered"]
    ):
        raise SystemExit("Round XIV ItemSpec production consumer gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
