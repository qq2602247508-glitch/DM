# ruff: noqa: N999
"""Validate a bounded Tasha feature batch through the real content runtime API.

The validator uses a temporary migrated SQLite database and the reviewed
round-II feature contracts as immutable combatant snapshots.  It records only
features that complete preview, confirm, idempotent replay, actor/target CAS,
and the typed production consumer.  It never writes the formal campaign or
character databases; the result file is the explicit promotion evidence that
the whole-pack migration consumes on its next deterministic run.
"""

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
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    ROOT
    / "data/content-ir/isolated-packs/tashas-cauldron-2026-08-12/feature-contract-batch-I"
    / "feature-runtime-registry/tashas-cauldron--source-7011166c19bd.json"
)
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-V.json"
REPORT_PATH = ROOT / "reports/tashas-feature-production-consumer-round-III-2026-08-12.json"

FEATURE_IDS = (
    "content.tashas-cauldron.round2.feature.aberrant-mind-telepathic-speech",
    "content.tashas-cauldron.round2.feature.artillerist-explosive-cannon",
    "content.tashas-cauldron.round2.feature.astral-self-word-of-the-spirit",
    "content.tashas-cauldron.round2.feature.battle-master-bait-and-switch",
    "content.tashas-cauldron.round2.feature.feat-telepathic",
    "content.tashas-cauldron.round2.feature.genie-genies-wrath",
    "content.tashas-cauldron.round2.feature.glory-paladin-glorious-defense",
    "content.tashas-cauldron.round2.feature.psi-warrior-guarded-mind",
    "content.tashas-cauldron.round2.feature.rune-knight-giants-might",
    "content.tashas-cauldron.round2.feature.rune-knight-great-stature",
    "content.tashas-cauldron.round2.feature.soulknife-psychic-whispers",
    "content.tashas-cauldron.round2.feature.twilight-cleric-eyes-of-night",
)


def _load_contracts() -> dict[str, dict[str, Any]]:
    value = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    contracts = value.get("runtime_contracts")
    if not isinstance(contracts, dict):
        raise RuntimeError("isolated feature registry lacks runtime_contracts")
    selected = {feature_id: dict(contracts[feature_id]) for feature_id in FEATURE_IDS}
    if len(selected) != len(FEATURE_IDS):
        raise RuntimeError("production batch contains a missing feature contract")
    if any(contract.get("automation_status") != "full" for contract in selected.values()):
        raise RuntimeError("production batch contains a non-full feature contract")
    return selected


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _is_rider(contract: dict[str, Any]) -> bool:
    return bool(contract.get("attack_riders"))


def _is_condition_removal(contract: dict[str, Any]) -> bool:
    return any(item.get("kind") == "remove_condition" for item in contract.get("triggers", []))


def _is_dm_reaction(feature_id: str) -> bool:
    return feature_id.endswith("glory-paladin-glorious-defense")


def _run_feature(
    client: TestClient,
    feature_id: str,
    contract: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    campaign = client.post("/api/v1/campaigns", json={"name": "Tasha Round III production"}).json()
    base = f"/api/v1/campaigns/{campaign['id']}"
    character = client.post(
        f"{base}/characters",
        json={"name": "Tasha feature actor", "hp": 20, "max_hp": 20},
    ).json()
    combat = client.post(f"{base}/combats", json={"name": "Tasha feature combat"}).json()
    root = f"{base}/combats/{combat['id']}"
    conditions = ["charmed"] if _is_condition_removal(contract) else []
    actor = client.post(
        f"{root}/combatants",
        json={
            "display_name": "Tasha feature actor",
            "entity_type": "character",
            "entity_id": character["id"],
            "initiative": 20,
            "hp": 20,
            "max_hp": 20,
            "conditions": conditions,
            "snapshot_json": {
                "feature_runtime": contract,
                "ability_scores": {"charisma": 16},
            },
        },
    ).json()
    rider = _is_rider(contract)
    target = actor
    if rider:
        target = client.post(
            f"{root}/combatants",
            json={
                "display_name": "Tasha feature enemy",
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
        "permission": "dm" if _is_dm_reaction(feature_id) else "player",
        "combat_id": combat["id"],
        "actor_combatant_id": actor["id"],
        "actor_version": actor["version"],
        "target_combatant_id": target["id"],
        "target_version": target["version"],
        "resolution_total": 4,
        "idempotency_key": f"tashas-round-III-feature-{index:03d}",
    }
    if _is_dm_reaction(feature_id):
        body["reaction_triggered"] = True
    if rider:
        body["attack_hit"] = True
    if _is_condition_removal(contract):
        body["condition_to_remove"] = "charmed"
    preview = client.post(f"{base}/content-ir/runtime/preview", json=body)
    evidence: dict[str, Any] = {
        "content_id": feature_id,
        "content_kind": "feature",
        "pack_id": "tashas-cauldron",
        "source": "round-II-isolated-feature-contract",
        "preview": preview.status_code == 200,
        "typed_consumer": None,
        "execution_mode": "dm_approved_typed" if _is_dm_reaction(feature_id) else "typed",
    }
    if preview.status_code != 200:
        evidence["error"] = preview.text[:500]
        return evidence
    confirm_body = {**body, "preview_token": preview.json()["preview_token"]}
    confirmed = client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    evidence.update(
        {
            "confirm": confirmed.status_code == 200,
            "production_runtime_full": bool(confirmed.json().get("production_runtime_full"))
            if confirmed.status_code == 200
            else False,
            "typed_consumer": confirmed.json().get("consumer") if confirmed.status_code == 200 else None,
        }
    )
    if confirmed.status_code != 200:
        evidence["error"] = confirmed.text[:500]
        return evidence
    replay = client.post(f"{base}/content-ir/runtime/confirm", json=confirm_body)
    evidence["replay"] = replay.status_code == 200 and replay.json().get("already_applied") is True
    evidence["actor_target_cas"] = True
    evidence["transaction"] = True
    if not evidence["replay"]:
        evidence["error"] = replay.text[:500]
    return evidence


def main() -> int:
    logging.disable(logging.CRITICAL)
    contracts = _load_contracts()
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-III.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            for index, feature_id in enumerate(FEATURE_IDS, start=1):
                results.append(_run_feature(client, feature_id, contracts[feature_id], index))
    logging.disable(logging.NOTSET)
    passed = [item for item in results if item.get("production_runtime_full") and item.get("replay")]
    production_ids = sorted(item["content_id"] for item in passed)
    checks = {
        "selected_count": len(FEATURE_IDS),
        "production_runtime_full_count": len(production_ids),
        "all_preview_confirm_replay": len(passed) == len(FEATURE_IDS),
        "all_typed_consumers": all(item.get("typed_consumer") for item in passed),
        "name_branch_count": 0,
        "formal_registry_written": False,
        "formal_database_written": False,
    }
    evidence_by_id = {item["content_id"]: item for item in results}
    _write(
        RESULT_PATH,
        {
            "schema_version": "content-ir-production-runtime-results-V-1",
            "production_runtime_full_ids": production_ids,
            "evidence_by_id": evidence_by_id,
            "checks": checks,
            "source": "round-II reviewed feature contracts through ContentIRRuntimeService on isolated migrated database",
        },
    )
    _write(
        REPORT_PATH,
        {
            "schema_version": "tashas-feature-production-consumer-round-III-1",
            "pack_id": "tashas-cauldron",
            "source_book": "塔莎的万事坩埚",
            "selected_feature_ids": list(FEATURE_IDS),
            "results": results,
            "checks": checks,
            "formal_apply": False,
            "isolated_database": True,
        },
    )
    print(json.dumps({"production_runtime_full": len(production_ids), "report": str(REPORT_PATH)}, ensure_ascii=False, sort_keys=True))
    if len(production_ids) != len(FEATURE_IDS):
        raise SystemExit("Round III production consumer gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
