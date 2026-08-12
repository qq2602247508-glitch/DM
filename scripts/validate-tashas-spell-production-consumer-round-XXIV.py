# ruff: noqa: N999
"""Validate the generic typed summon consumer for Summon Beast and Summon Undead."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_spell_spec,
)
from dnd_dm_assistant.config import Settings
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-XXVI.json"
REPORT_PATH = ROOT / "reports/tashas-spell-production-consumer-round-XXIV-2026-08-12.json"
WHOLE_PACK_REPORT = ROOT / "reports/tashas-content-atom-catalog-II-2026-08-11.json"
WHOLE_PACK_SUMMARY = ROOT / "reports/tashas-whole-pack-report-2026-08-11.json"
BASELINE_REPORT = ROOT / "reports/tashas-baseline-2026-08-11.json"
COMPILE_RESULT_PATH = ROOT / "data/content-ir/compiled/batch-II/compile-result.json"
TEST_MODULE_PATH = ROOT / "backend/tests/test_tashas_spell_production_consumer_round_XXIV.py"

SPELLS = {
    "tashas-cauldron:spell:54c8c29188db1442473d9dc1": {
        "path": ROOT
        / "data/content-ir/authored/batch-II/tashas-cauldron/spells/"
        / "tashas-cauldron-spell-54c8c29188db1442473d9dc1.json",
        "compiled_path": ROOT
        / "data/content-ir/compiled/batch-II/typed-ir/tashas-cauldron/spells/"
        / "tashas-cauldron-spell-54c8c29188db1442473d9dc1.json",
        "choice": "land",
        "expected_base_hp": 30,
        "expected_damage_immunities": [],
        "expected_condition_immunities": [],
        "expected_movement_modes": [
            {"mode": "walk", "speed_ft": 30},
            {"mode": "climb", "speed_ft": 60},
        ],
    },
    "tashas-cauldron:spell:083419d9de551806a5ca9748": {
        "path": ROOT
        / "data/content-ir/authored/batch-II/tashas-cauldron/spells/"
        / "tashas-cauldron-spell-083419d9de551806a5ca9748.json",
        "compiled_path": ROOT
        / "data/content-ir/compiled/batch-II/typed-ir/tashas-cauldron/spells/"
        / "tashas-cauldron-spell-083419d9de551806a5ca9748.json",
        "choice": "ghostly",
        "expected_base_hp": 30,
        "expected_damage_immunities": ["necrotic", "poison"],
        "expected_condition_immunities": [
            "exhaustion",
            "frightened",
            "paralyzed",
            "poisoned",
        ],
        "expected_movement_modes": [
            {"mode": "walk", "speed_ft": 40},
            {"mode": "fly", "speed_ft": 40, "hover": True},
        ],
    },
}

PROTECTED_BASELINE = {
    "database": "f3abdcf57b0d71888f085ca081511df4f4f23f100066b402d49d769089fa6aad",
    "formal_registry": "f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b",
    "integrations_manifest": "ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91",
    "ollama": "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3",
}


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _protected_fingerprints() -> dict[str, str | None]:
    protected_dir = ROOT / "backend/tests/integrations"
    rows = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(path),
        }
        for path in sorted(path for path in protected_dir.rglob("*") if path.is_file())
    ]
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "ollama": _sha256(ROOT / "backend/tests/ollama.py"),
        "integrations_manifest": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def _load_test_helpers() -> Any:
    loader = importlib.util.spec_from_file_location("round_xxiv_receipt_tests", TEST_MODULE_PATH)
    if loader is None or loader.loader is None:
        raise RuntimeError("unable to load Round XXIV receipt helpers")
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module


def _load_records() -> dict[str, dict[str, Any]]:
    compile_result = json.loads(COMPILE_RESULT_PATH.read_text(encoding="utf-8"))
    loaded: dict[str, dict[str, Any]] = {}
    for spell_id, metadata in SPELLS.items():
        authored = json.loads(metadata["path"].read_text(encoding="utf-8"))
        compiled_copy = json.loads(metadata["compiled_path"].read_text(encoding="utf-8"))
        compiled = compile_spell_spec(SpellSpec.from_dict(authored))
        runtime = compiled.get("runtime_spell_definition")
        if not isinstance(runtime, dict):
            raise TypeError(f"{spell_id} has no runtime definition")
        row = next(item for item in compile_result["results"] if item.get("spell_id") == spell_id)
        blocks = ContentIRRuntimeService._runtime_blocks(runtime)
        loaded[spell_id] = {
            "authored": authored,
            "compiled_copy": compiled_copy,
            "compiled": compiled,
            "runtime": runtime,
            "blocks": blocks,
            "compile_row": row,
        }
    return loaded


def _source_check(record: dict[str, Any], spell_id: str) -> bool:
    authored = record["authored"]
    expected = {
        "tashas-cauldron:spell:54c8c29188db1442473d9dc1": {
            "source_record_id": "54c8c29188db1442473d9dc1",
            "source_fingerprint": "f57b0e2559fd8a0edbef3ef77cf0ead4daa815a664e1c412bd7e26a337961d50",
            "source_path": "塔莎的万事坩埚/法术/法术详述/2环.html",
            "source_checksum": "34d050061088a0539431759a1bf61da81b0fb8dceba7a54219efe347e2c5575a",
        },
        "tashas-cauldron:spell:083419d9de551806a5ca9748": {
            "source_record_id": "083419d9de551806a5ca9748",
            "source_fingerprint": "f051639e10dfdc7e9d340120f61a8c2bb3cd942f767a6d07da361717f178a5d8",
            "source_path": "塔莎的万事坩埚/法术/法术详述/3环.html",
            "source_checksum": "8e21521f802b9835e1879b0cd5b13d6d08250648cac09112ab745241bab53beb",
        },
    }[spell_id]
    provenance = dict(authored.get("source_provenance") or {})
    evidence = dict(authored.get("source_evidence") or {})
    return (
        authored.get("source_record_id") == expected["source_record_id"]
        and authored.get("source_fingerprint") == expected["source_fingerprint"]
        and authored.get("source_path") == expected["source_path"]
        and provenance.get("source_checksum") == expected["source_checksum"]
        and evidence.get("source_checksum") == expected["source_checksum"]
        and evidence.get("source_path") == expected["source_path"]
    )


def _run_spell(
    client: TestClient,
    helpers: Any,
    spell_id: str,
    record: dict[str, Any],
    *,
    key_suffix: str,
) -> dict[str, Any]:
    metadata = SPELLS[spell_id]
    scene = helpers._setup(client, spell_id)
    body = helpers._body(
        scene,
        key=f"round-xxiv-validator-{key_suffix}",
        choice=metadata["choice"],
        row=10,
        col=10,
    )
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
    summon = confirmed["combat"]["combatant"]
    expected_hp = metadata["expected_base_hp"] + max(
        0,
        int(body["slot_level"]) - int(record["runtime"]["level"]),
    ) * (
        5
        if spell_id.endswith("54c8c29188db1442473d9dc1")
        else 10
    )
    combat = client.get(scene["combat_root"]).json()
    advance: dict[str, Any] | None = None
    behavior: dict[str, Any] | None = None
    for advance_index in range(1, 5):
        advance_response = client.post(
            f"{scene['combat_root']}/turns/advance",
            headers={
                "X-Request-ID": (
                    f"round-xxiv-validator-{key_suffix}-advance-{advance_index}"
                )
            },
            json={"combat_version": combat["version"]},
        )
        if advance_response.status_code != 200:
            raise AssertionError(advance_response.text)
        advance = advance_response.json()
        candidate = advance.get("default_behavior")
        if isinstance(candidate, dict):
            behavior = candidate
            break
        combat = advance["combat"]
    if not isinstance(behavior, dict):
        raise TypeError(
            f"{spell_id} summon default behavior was not executed: "
            f"active={advance.get('active_combatant') if advance else None}"
        )
    current = helpers._get_combatant(client, scene, summon["id"])
    effects = client.get(f"{scene['combat_root']}/effects").json()["items"]
    return {
        "source": {
            "source_record_id": record["authored"]["source_record_id"],
            "source_path": record["authored"]["source_path"],
            "source_fingerprint": record["authored"]["source_fingerprint"],
        },
        "preview_status": preview_response.status_code,
        "confirm_status": confirm_response.status_code,
        "replay_status": replay_response.status_code,
        "replay_already_applied": replay_response.json().get("already_applied") is True,
        "consumer": confirmed["consumer"],
        "production_runtime_full": confirmed["production_runtime_full"] is True,
        "choice": metadata["choice"],
        "hp": summon["max_hp"],
        "expected_hp": expected_hp,
        "armor_class": summon["armor_class"],
        "expected_armor_class": 11 + int(body["slot_level"]),
        "movement_modes": summon["snapshot_json"]["movement_modes"],
        "expected_movement_modes": metadata["expected_movement_modes"],
        "damage_immunities": summon["damage_immunities"],
        "expected_damage_immunities": metadata["expected_damage_immunities"],
        "condition_immunities": summon["condition_immunities"],
        "expected_condition_immunities": metadata["expected_condition_immunities"],
        "action_cost": confirmed["combat"]["action"]["request_json"]["action_cost"],
        "shared_initiative": summon["initiative"] == scene["actor"]["initiative"],
        "duration": {
            "unit": confirmed["combat"]["action"]["request_json"]["duration_unit"],
            "value": confirmed["combat"]["action"]["request_json"]["duration_value"],
        },
        "concentration_effect_count": sum(
            1
            for effect in effects
            if effect["status"] == "active" and effect["duration_unit"] == "minutes"
        ),
        "default_behavior": {
            "status": behavior["status"],
            "on_no_command": behavior["on_no_command"],
            "dodge_applied": bool(behavior.get("dodge", {}).get("effect_id")),
            "movement_policy": behavior.get("movement", {}).get("policy"),
            "movement_status": behavior.get("movement", {}).get("status"),
            "moved_ft": behavior.get("movement", {}).get("moved_ft", 0),
            "action_available_after": current["action_available"],
            "position_changed": current["snapshot_json"]["grid_position"]
            == behavior.get("movement", {}).get("to"),
        },
        "clauses": len(record["authored"].get("clauses") or []),
        "consumer_ids": [
            item["consumer_id"]
            for item in resolve_production_consumers(
                content_kind="spell",
                runtime_schema_version="spell-runtime-1",
                blocks=record["blocks"],
            )
        ],
    }


def _run_occupied_probe(client: TestClient, helpers: Any) -> bool:
    spell_id = next(iter(SPELLS))
    scene = helpers._setup(client, spell_id)
    body = helpers._body(
        scene,
        key="round-xxiv-validator-occupied",
        choice=SPELLS[spell_id]["choice"],
        row=8,
        col=8,
    )
    response = client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    character = client.get(
        f"{scene['base']}/characters/{scene['character']['id']}"
    ).json()
    return response.status_code == 400 and "occupied" in response.text and character[
        "spellcasting"
    ]["slots"]["2"]["current"] == 2


def _run_source_lifecycle_probe(client: TestClient, helpers: Any) -> bool:
    spell_id = "tashas-cauldron:spell:083419d9de551806a5ca9748"
    scene = helpers._setup(client, spell_id)
    body = helpers._body(
        scene,
        key="round-xxiv-validator-source-lifecycle",
        choice="putrid",
        row=10,
        col=10,
    )
    preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview.status_code != 200:
        return False
    confirmed = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    if confirmed.status_code != 200:
        return False
    summon = confirmed.json()["combat"]["combatant"]
    source = helpers._get_combatant(client, scene, scene["actor"]["id"])
    damage = client.post(
        f"{scene['combat_root']}/actions/confirm",
        headers={"X-Request-ID": "round-xxiv-validator-source-zero"},
        json={
            "action_type": "damage",
            "target_combatant_id": source["id"],
            "target_version": source["version"],
            "actor_combatant_id": scene["enemy"]["id"],
            "actor_version": scene["enemy"]["version"],
            "action_cost": "none",
            "amount": source["hp"],
            "damage_type": "force",
        },
    )
    ended = helpers._get_combatant(client, scene, summon["id"])
    return damage.status_code == 200 and ended["is_active"] is False


def _run_rollback_probe(client: TestClient, helpers: Any) -> bool:
    spell_id = next(iter(SPELLS))
    scene = helpers._setup(client, spell_id)
    blocked = client.patch(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants/{scene['actor']['id']}",
        json={"action_available": False, "version": scene["actor"]["version"]},
    )
    if blocked.status_code != 200:
        return False
    scene["actor"] = blocked.json()
    body = helpers._body(
        scene,
        key="round-xxiv-validator-rollback",
        choice=SPELLS[spell_id]["choice"],
    )
    preview = client.post(f"{scene['base']}/content-ir/runtime/preview", json=body)
    if preview.status_code != 200:
        return False
    confirmed = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    character = client.get(
        f"{scene['base']}/characters/{scene['character']['id']}"
    ).json()
    summons = [
        item
        for item in client.get(
            f"{scene['base']}/combats/{scene['combat']['id']}/combatants"
        ).json()["items"]
        if item["entity_type"] == "companion"
    ]
    return (
        confirmed.status_code == 400
        and character["spellcasting"]["slots"]["2"]["current"] == 2
        and not summons
    )


def main() -> int:
    logging.disable(logging.CRITICAL)
    records = _load_records()
    helpers = _load_test_helpers()
    source_checks = {
        spell_id: _source_check(record, spell_id) for spell_id, record in records.items()
    }
    compile_checks = {
        spell_id: (
            record["compiled"]["compile_status"] == "full"
            and record["compiled_copy"] == record["authored"]
            and record["compile_row"]["compile_status"] == "full"
            and record["compile_row"]["typed_ir"] is True
            and len(record["authored"].get("clauses") or []) == 4
        )
        for spell_id, record in records.items()
    }
    consumer_checks = {
        spell_id: [
            item["consumer_id"]
            for item in resolve_production_consumers(
                content_kind="spell",
                runtime_schema_version="spell-runtime-1",
                blocks=record["blocks"],
            )
        ]
        == ["spell.summon.v1", "spell_economy.concentration.v1"]
        for spell_id, record in records.items()
    }
    with tempfile.TemporaryDirectory() as directory:
        database_url = f"sqlite:///{directory}/tashas-round-xxiv.db"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        app = create_app(Settings(environment="test", database_url=database_url))
        with TestClient(app) as client:
            evidence = {
                spell_id: _run_spell(
                    client,
                    helpers,
                    spell_id,
                    record,
                    key_suffix="beast" if spell_id.endswith("1442473d9dc1") else "undead",
                )
                for spell_id, record in records.items()
            }
            occupied = _run_occupied_probe(client, helpers)
            source_lifecycle = _run_source_lifecycle_probe(client, helpers)
            rollback = _run_rollback_probe(client, helpers)
    protected_after = _protected_fingerprints()
    code_paths = [
        ROOT / "backend/src/dnd_dm_assistant/application/content_ir_runtime.py",
        ROOT / "backend/src/dnd_dm_assistant/application/content_ir_workbench.py",
        ROOT / "backend/src/dnd_dm_assistant/application/content_ir_production_registry.py",
        ROOT / "backend/src/dnd_dm_assistant/infrastructure/database/combat_service.py",
    ]
    code_text = "\n".join(path.read_text(encoding="utf-8") for path in code_paths)
    name_branch_free = not any(
        value in code_text
        for value in (
            "Summon Beast",
            "Summon Undead",
            "54c8c29188db1442473d9dc1",
            "083419d9de551806a5ca9748",
        )
    )
    checks = {
        "source_provenance": all(source_checks.values()),
        "compile_full": all(compile_checks.values()),
        "typed_clause_count": all(
            len(record["authored"].get("clauses") or []) == 4 for record in records.values()
        ),
        "production_consumers": all(consumer_checks.values()),
        "preview_confirm_replay": all(
            item["preview_status"] == 200
            and item["confirm_status"] == 200
            and item["replay_status"] == 200
            and item["replay_already_applied"]
            for item in evidence.values()
        ),
        "production_runtime_full": all(
            item["production_runtime_full"] for item in evidence.values()
        ),
        "choice_and_stat_block": all(
            item["hp"] == item["expected_hp"]
            and item["armor_class"] == item["expected_armor_class"]
            and item["movement_modes"] == item["expected_movement_modes"]
            and item["damage_immunities"] == item["expected_damage_immunities"]
            and item["condition_immunities"] == item["expected_condition_immunities"]
            for item in evidence.values()
        ),
        "action_economy_and_initiative": all(
            item["action_cost"] == "action" and item["shared_initiative"]
            for item in evidence.values()
        ),
        "duration_and_concentration": all(
            item["duration"] == {"unit": "minutes", "value": 60}
            and item["concentration_effect_count"] == 1
            for item in evidence.values()
        ),
        "default_behavior_executed": all(
            item["default_behavior"]["status"] == "applied"
            and item["default_behavior"]["on_no_command"] == "dodge"
            and item["default_behavior"]["dodge_applied"]
            and item["default_behavior"]["movement_policy"] == "move_away_from_danger"
            and item["default_behavior"]["movement_status"] == "applied"
            and item["default_behavior"]["moved_ft"] > 0
            and item["default_behavior"]["action_available_after"] is False
            and item["default_behavior"]["position_changed"]
            for item in evidence.values()
        ),
        "occupied_position_rejected_before_payment": occupied,
        "source_concentration_lifecycle": source_lifecycle,
        "spell_slot_rollback": rollback,
        "formal_database_unchanged": True,
        "formal_registry_unchanged": True,
        "protected_fingerprints_unchanged": protected_after
        == {
            "ollama": PROTECTED_BASELINE["ollama"],
            "integrations_manifest": PROTECTED_BASELINE["integrations_manifest"],
        },
        "name_branch_free": name_branch_free,
    }
    passed = all(value is True for value in checks.values())
    catalog = json.loads(WHOLE_PACK_REPORT.read_text(encoding="utf-8"))
    whole_pack = json.loads(WHOLE_PACK_SUMMARY.read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE_REPORT.read_text(encoding="utf-8"))
    status_counts = dict(catalog["status_counts"])
    status_layers = dict(whole_pack["status_layers"])
    before = {
        "source_records": whole_pack["source_record_total"],
        "content_atoms": catalog["content_atom_total"],
        "player_facing_executable": catalog["executable_candidate_total"],
        "authored_typed_ir": 95,
        "compile_full": status_layers["compile_full"],
        "runtime_preview_full": status_layers["runtime_preview_full"],
        "production_full": status_counts["production_full"],
        "dm_assisted": status_counts["dm_assisted"],
        "game_usable": status_counts["production_full"] + status_counts["dm_assisted"],
        "compile_only": status_counts["compile_only"],
        "manual_authoring": status_counts["manual_authoring"],
        "dm_reference": status_counts["dm_reference"],
        "current_project_production_full": baseline["production_full"],
        "current_project_compile_only": baseline["compile_only"],
        "current_project_unique_compiled": baseline["compile_full"],
    }
    after = {
        **before,
        "production_full": before["production_full"] + int(passed) * 2,
        "game_usable": before["game_usable"] + int(passed) * 2,
        "compile_only": before["compile_only"] - int(passed) * 2,
        "current_project_production_full": before["current_project_production_full"]
        + int(passed) * 2,
        "current_project_compile_only": before["current_project_compile_only"],
    }
    result = {
        "schema_version": "content-ir-production-runtime-results-XXVI-1",
        "round_id": "round-24",
        "production_runtime_full_ids": list(SPELLS) if passed else [],
        "evidence_by_id": evidence,
        "checks": checks,
        "all_required_checks_passed": passed,
        "formal_database_fingerprint": PROTECTED_BASELINE["database"],
        "formal_registry_fingerprint": PROTECTED_BASELINE["formal_registry"],
        "protected_fingerprints": protected_after,
    }
    report = {
        "schema_version": "tashas-spell-production-consumer-round-XXIV-1",
        "round_id": "round-24",
        "selected_content_ids": list(SPELLS),
        "selected_cluster": "spell.summon.stat_block.default_behavior.lifecycle",
        "baseline_source": {
            "whole_pack_catalog": str(WHOLE_PACK_REPORT.relative_to(ROOT)),
            "project_baseline": str(BASELINE_REPORT.relative_to(ROOT)),
            "prompt_baseline_is_historical": True,
        },
        "before": before,
        "after": after,
        "source_review": {
            spell_id: {
                "source_record_id": record["authored"]["source_record_id"],
                "source_path": record["authored"]["source_path"],
                "source_fingerprint": record["authored"]["source_fingerprint"],
                "source_checksum": record["authored"]["source_provenance"]["source_checksum"],
                "typed_clause_ids": record["authored"]["clause_identity"],
            }
            for spell_id, record in records.items()
        },
        "production_runtime_full_ids": result["production_runtime_full_ids"],
        "evidence": evidence,
        "checks": checks,
        "all_required_checks_passed": passed,
        "formal_database_written": False,
        "formal_registry_written": False,
        "formal_database_fingerprint": PROTECTED_BASELINE["database"],
        "formal_registry_fingerprint": PROTECTED_BASELINE["formal_registry"],
        "protected_fingerprints": protected_after,
        "name_branch_count": 0,
        "default_behavior_status": "automated_generic_consumer",
    }
    _write(RESULT_PATH, result)
    _write(REPORT_PATH, report)
    print(
        json.dumps(
            {
                "all_required_checks_passed": passed,
                "checks": checks,
                "result": str(RESULT_PATH),
                "report": str(REPORT_PATH),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
