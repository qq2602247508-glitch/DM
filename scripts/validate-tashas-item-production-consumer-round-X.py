# ruff: noqa: N999
"""Validate a real ItemSpec equipment-consumer batch on an isolated database."""

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
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.domain.item_spec import ItemSpec, compile_item_spec
from dnd_dm_assistant.infrastructure.database.models import (
    Attunement,
    EquipmentInstance,
    OperationTransaction,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
ITEM_ROOT = ROOT / "data/content-ir/isolated-packs/tashas-cauldron-2026-08-11/items"
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XII.json"
REPORT_PATH = ROOT / "reports/tashas-item-production-consumer-round-X-2026-08-12.json"

ITEM_IDS = (
    "content.tashas-cauldron.item.tashas-cauldron-atom-4220452fa5c2c1b3aed918f5-amulet-of-the-devout-001",
    "content.tashas-cauldron.item.tashas-cauldron-atom-4220452fa5c2c1b3aed918f5-arcane-grimoire-002",
    "content.tashas-cauldron.item.tashas-cauldron-atom-4220452fa5c2c1b3aed918f5-bloodwell-vial-003",
    "content.tashas-cauldron.item.tashas-cauldron-atom-4220452fa5c2c1b3aed918f5-guardian-emblem-005",
    "content.tashas-cauldron.item.tashas-cauldron-atom-4220452fa5c2c1b3aed918f5-rhythm-maker-s-drum-008",
    "content.tashas-cauldron.item.tashas-cauldron-atom-7f82da3807a304a28c05c79b-alchemical-compendium-000",
    "content.tashas-cauldron.item.tashas-cauldron-atom-7f82da3807a304a28c05c79b-far-realm-shard-008",
    "content.tashas-cauldron.item.tashas-cauldron-atom-7f82da3807a304a28c05c79b-lyre-of-building-012",
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_specs() -> dict[str, ItemSpec]:
    specs: dict[str, ItemSpec] = {}
    for path in sorted(ITEM_ROOT.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        item_id = str(raw.get("item_id") or "")
        if item_id not in ITEM_IDS:
            continue
        spec = ItemSpec.from_dict({key: raw[key] for key in ItemSpec._FIELDS if key in raw}, str(path))
        compiled = compile_item_spec(spec)
        if compiled["compile_status"] != "full":
            raise RuntimeError(f"selected ItemSpec is not compile_full: {item_id}")
        specs[item_id] = spec
    if set(specs) != set(ITEM_IDS):
        raise RuntimeError("Round X selected ItemSpec set is incomplete")
    return specs


def _confirm_operation(
    client: TestClient,
    base: str,
    character: dict[str, Any],
    equipment_id: str,
    *,
    operation: str,
    key: str,
    action_id: str | None = None,
    slot: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "character_id": character["id"],
        "character_version": character["version"],
        "equipment_id": equipment_id,
        "operation": operation,
    }
    if action_id:
        body["action_id"] = action_id
    if slot:
        body["slot"] = slot
    preview = client.post(f"{base}/equipment/preview", json=body)
    if preview.status_code != 200:
        raise RuntimeError(f"{operation} preview failed: {preview.status_code} {preview.text[:400]}")
    preview_body = preview.json()
    confirm_body = {**body, "preview_token": preview_body["preview_token"], "idempotency_key": key}
    confirmed = client.post(f"{base}/equipment/confirm", json=confirm_body)
    if confirmed.status_code != 200:
        raise RuntimeError(f"{operation} confirm failed: {confirmed.status_code} {confirmed.text[:400]}")
    replay = client.post(f"{base}/equipment/confirm", json=confirm_body)
    if replay.status_code != 200 or replay.json() != confirmed.json():
        raise RuntimeError(f"{operation} replay failed: {replay.status_code} {replay.text[:400]}")
    output = confirmed.json()
    return {
        "operation": operation,
        "preview": True,
        "confirm": True,
        "replay": True,
        "idempotency_replayed": replay.json() == confirmed.json(),
        "output": {
            "operation": output.get("operation"),
            "confirmed": output.get("confirmed"),
            "slot": output.get("slot"),
            "warnings": output.get("warnings", []),
            "before": output.get("before", {}),
            "after": output.get("after", {}),
        },
    }


def _run_item(client: TestClient, database_url: str, spec: ItemSpec, index: int) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": f"Tasha Round X Item {index}"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={
            "name": f"Tasha typed item actor {index}",
            "level": 5,
            "hp": 20,
            "max_hp": 20,
            "proficiencies": ["军用武器", "轻甲", "中甲", "重甲", "盾牌"],
        },
    ).json()
    created = client.post(
        f"{base}/characters/assets/equipment",
        json={
            "character_id": character["id"],
            "character_version": character["version"],
            "name": spec.name,
            "category": spec.item_kind,
            "metadata_json": {
                "item_spec": spec.to_dict(),
                "source_record_id": spec.source_record_id,
            },
        },
    )
    if created.status_code != 201:
        raise RuntimeError(f"create equipment failed: {created.status_code} {created.text[:400]}")
    equipment = created.json()
    typed_projection = equipment.get("metadata_json", {}).get("item_spec", {})
    expected_consumers = compile_item_spec(spec)["consumer_ids"]
    operations: list[dict[str, Any]] = []
    current = client.get(f"{base}/characters/{character['id']}").json()
    if spec.requires_attunement:
        operations.append(
            _confirm_operation(
                client, base, current, equipment["id"], operation="attune", key=f"round-x-{index}-attune"
            )
        )
        current = client.get(f"{base}/characters/{character['id']}").json()
    else:
        operations.append(
            _confirm_operation(
                client,
                base,
                current,
                equipment["id"],
                operation="equip",
                slot=spec.equipped_slot or ("main_hand" if spec.item_kind == "weapon" else "worn"),
                key=f"round-x-{index}-equip",
            )
        )
        current = client.get(f"{base}/characters/{character['id']}").json()
    if spec.granted_actions:
        operations.append(
            _confirm_operation(
                client,
                base,
                current,
                equipment["id"],
                operation="use_action",
                action_id=str(spec.granted_actions[0]["action_id"]),
                key=f"round-x-{index}-action",
            )
        )
        if spec.charges and not int(spec.granted_actions[0].get("charge_cost") or 0):
            current = client.get(f"{base}/characters/{character['id']}").json()
            operations.append(
                _confirm_operation(
                    client,
                    base,
                    current,
                    equipment["id"],
                    operation="use_charge",
                    key=f"round-x-{index}-charge",
                )
            )
    elif spec.charges:
        current = client.get(f"{base}/characters/{character['id']}").json()
        operations.append(
            _confirm_operation(
                client,
                base,
                current,
                equipment["id"],
                operation="use_charge",
                key=f"round-x-{index}-charge",
            )
        )
    engine = create_engine(database_url)
    with Session(engine) as session:
        row = session.get(EquipmentInstance, equipment["id"])
        if row is None:
            raise RuntimeError(f"equipment row missing for {spec.item_id}")
        active_attunement = session.scalar(
            select(Attunement).where(
                Attunement.equipment_instance_id == row.id,
                Attunement.status == "active",
            )
        )
        transaction_count = int(
            session.scalar(
                select(func.count()).select_from(OperationTransaction).where(
                    OperationTransaction.campaign_id == campaign["id"],
                    OperationTransaction.operation_type.like("equipment_%"),
                )
            )
            or 0
        )
        persisted = {
            "item_id": row.metadata_json.get("item_spec", {}).get("item_id"),
            "item_fingerprint": row.metadata_json.get("item_spec", {}).get("item_fingerprint"),
            "attuned": active_attunement is not None,
            "charges": row.charges,
            "version": row.version,
            "operation_transaction_count": transaction_count,
        }
    return {
        "content_id": spec.item_id,
        "content_kind": "item",
        "item_name": spec.name,
        "compile_status": "full",
        "consumer_ids": expected_consumers,
        "typed_projection_consumers": typed_projection.get("consumer_ids", []),
        "created": True,
        "operations": operations,
        "preview_confirm_replay": all(item["preview"] and item["confirm"] and item["replay"] for item in operations),
        "typed_consumer": sorted(typed_projection.get("consumer_ids", [])) == sorted(expected_consumers),
        "item_state_persisted": persisted["item_id"] == spec.item_id and bool(persisted["item_fingerprint"]),
        "attunement_persisted": persisted["attuned"] == spec.requires_attunement,
        "charge_lifecycle_persisted": (
            not spec.charges
            or persisted["charges"] is not None
            and persisted["charges"] < int(spec.charges.get("current", spec.charges.get("maximum", 0)))
        ),
        "operation_transaction_persisted": persisted["operation_transaction_count"] == len(operations),
        "persisted": persisted,
    }


def main() -> int:
    logging.disable(logging.CRITICAL)
    specs = _load_specs()
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-X-items.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        with TestClient(create_app(Settings(environment="test", database_url=database_url))) as client:
            for index, item_id in enumerate(ITEM_IDS, start=1):
                results.append(_run_item(client, database_url, specs[item_id], index))
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
    ]
    production_ids = sorted(item["content_id"] for item in passed)
    checks = {
        "selected_count": len(results),
        "production_runtime_full_count": len(production_ids),
        "all_create_preview_confirm_replay": len(passed) == len(results),
        "all_typed_consumers": all(item["typed_consumer"] for item in passed),
        "all_item_state_persisted": all(item["item_state_persisted"] for item in passed),
        "all_attunement_cas": all(item["attunement_persisted"] for item in passed),
        "charge_lifecycle_count": sum(bool(item["persisted"]["charges"] is not None) for item in passed),
        "operation_transaction_count": sum(item["persisted"]["operation_transaction_count"] for item in passed),
        "formal_registry_written": False,
        "formal_database_written": False,
        "isolated_database": True,
        "name_branch_count": 0,
    }
    evidence_by_id = {item["content_id"]: item for item in results}
    _write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-XII-1",
            "content_kind": "item",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "Round X reviewed ItemSpec through real equipment create, attunement/equip and granted-action consumers on an isolated migrated database",
        },
    )
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-item-production-consumer-round-X-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_item_ids": list(ITEM_IDS),
            "results": results,
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
        },
    )
    print(json.dumps({"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)}, ensure_ascii=False, sort_keys=True))
    if len(production_ids) != len(results):
        raise SystemExit("Round X ItemSpec production consumer gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
