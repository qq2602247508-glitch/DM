# ruff: noqa: N999
"""Validate the next compile-only census and register the existing summon proof.

Round XXIV already proved the generic summon consumer against isolated SQLite.
This round republishes that real proof in the current loader contract and adds
the authoritative remaining-ID census without changing source or formal data.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from dnd_dm_assistant.api.app import create_app
from dnd_dm_assistant.application.content_ir_production_evidence import (
    authoritative_compile_only_ids,
    load_production_runtime_evidence,
    project_compile_only_ids,
)
from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_spell_spec,
)
from dnd_dm_assistant.application.tashas_whole_pack import build_migration
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database.models import (
    CombatAction,
    Combatant,
    OperationTransaction,
)
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "data/content-ir/compiled/production-runtime-results-LIV.json"
REPORT_PATH = ROOT / "reports/round-LIV-summon-census-closure-2026-08-14.json"
FOCUSED = "backend/tests/test_round_LIV_summon_census_closure.py"
OLLAMA_SHA = "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3"
XLIII_SHA = "98718564dab7e41bb911b2d10813cb43bf59b422732ec67480b4e362e519c76f"
SUMMON_IDS = (
    "tashas-cauldron:spell:083419d9de551806a5ca9748",
    "tashas-cauldron:spell:54c8c29188db1442473d9dc1",
)

GROUP_LABELS = {
    "tashas-cauldron:spell:083419d9de551806a5ca9748": "summon.stat_block.lifecycle",
    "tashas-cauldron:spell:54c8c29188db1442473d9dc1": "summon.stat_block.lifecycle",
    "core-phb-2024:spell:65b211e271db5fa11508dbbc": "illusion.visual_movement_inspection",
    "core-phb-2024:spell:82f220a9e3474d8fe1cafd8b": "damage.save.cover_bypass.scaling",
    "core-phb-2024:spell:d84dec64befac8db7294e0f1": "damage.area_save.scaling",
    "xanathars-guide:spell:5aa5cf7f93be0fa149fdcd62": "damage.attack_or_save.condition",
    "core-phb-2024:spell:dccfb9fc9cd30b9fb8b627b0": "damage.attack_concentration",
    "core-phb-2024:spell:fa352b4b5b77382c47bad253": "damage.cantrip_scaling",
    "core-phb-2024:spell:85595d634b480207249dd2ac": "condition.lifecycle_save",
    "core-phb-2024:spell:aa17c997419ff77ab783e003": "condition.lifecycle_trigger",
    "core-phb-2024:spell:ad887cac0fa7f6c2cf7c566f": "condition.area_save",
    "core-phb-2024:spell:eaaa6893b004c177f8237eb0": "condition.duration_save",
    "core-phb-2024:spell:63fb2360b8c30fb0419d9225": "concentration.mark_transfer",
    "core-phb-2024:spell:90c12635dd6eca81ebe04449": "concentration.sense_detection",
    "core-phb-2024:spell:9b29fbb72177f058bf1448ef": "concentration.area_lifecycle",
    "core-phb-2024:spell:c724eb95e2f08220d161e608": "concentration.debuff",
    "core-phb-2024:spell:ed5371dd95cf605bf1c24cd3": "concentration.duel_target",
    "core-phb-2024:spell:a0c914f228b833357f0c2779": "concentration.resistance",
    "fizbans-treasury:spell:843fb135e4cc8a1fb34c46be": "concentration.defense_modifier",
    "xanathars-guide:spell:6d32a73dbc7bf6f5fac303bd": "concentration.beast_bond",
    "xanathars-guide:spell:c9d315871dc96f3fed66c29b": "concentration.movement",
    "tashas-cauldron:spell:b4ea0dc1907dd5ac08666af3": "concentration.defense_modifier",
    "core-phb-2024:spell:6c07317bf4d16b92da3c8f55": "area.object_purification",
    "core-phb-2024:spell:9c4208ec038463dfd608ba9e": "area.multi_mode_elemental",
    "core-phb-2024:spell:ea1d170f71d30f4ddeb84f9e": "area.light_effect",
    "xanathars-guide:spell:805cbf82765f6710391cc75f": "ritual.trap_trigger",
    "xanathars-guide:spell:96d5c3265bc938448c4aef58": "ritual.ceremony_choice",
    "xanathars-guide:spell:aadf89719f073bfca1fefb3a": "concentration.remote_message",
    "fizbans-treasury:spell:cadce71b1ba7a42354f785dc": "area.cone_save_condition",
}


def _load_old_helpers() -> Any:
    spec = importlib.util.spec_from_file_location(
        "round_xxiv_helpers",
        ROOT / "scripts/validate-tashas-spell-production-consumer-round-XXIV.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load existing summon proof helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_path(content_id: str) -> Path:
    pack, _, record_id = content_id.partition(":spell:")
    return (
        ROOT
        / "data/content-ir/authored/batch-II"
        / pack
        / "spells"
        / f"{pack}-spell-{record_id}.json"
    )


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "stable-id"
                if key.endswith(("_id", "_ids"))
                or key in {"id", "operation_transaction_id", "turn_index"}
                else "stable-token"
                if key == "preview_token" or key.endswith("_fingerprint")
                else "stable-time"
                if key.endswith("_at") or key in {"created_at", "updated_at"}
                else _stable(item)
            )
            for key, item in sorted(value.items())
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _protected_ok() -> bool:
    return _sha(ROOT / "backend/tests/ollama.py") == OLLAMA_SHA


def _census() -> dict[str, Any]:
    current_artifact = str(RESULT_PATH.relative_to(ROOT))
    authoritative_ids = authoritative_compile_only_ids(ROOT)
    historical_evidence = {
        content_id: row
        for content_id, row in load_production_runtime_evidence(
            ROOT,
            pack_id=None,
            required_checks=("all_required_checks_passed",),
            require_name_branch_free=True,
        ).items()
        if row.get("evidence_path") != current_artifact
    }
    ids = sorted(
        project_compile_only_ids(
            authoritative_ids,
            historical_evidence,
        )
    )
    rows = []
    for content_id in ids:
        authored = json.loads(_source_path(content_id).read_text(encoding="utf-8"))
        compiled = compile_spell_spec(SpellSpec.from_dict(authored))
        rows.append(
            {
                "content_id": content_id,
                "name": authored["name"],
                "pack_id": authored["pack_id"],
                "source_record_id": authored["source_record_id"],
                "source_fingerprint": authored["source_fingerprint"],
                "source_path": authored["source_path"],
                "source_checksum": authored["source_provenance"]["source_checksum"],
                "source_complete": bool(
                    (authored.get("source_evidence") or {}).get("source_text")
                )
                and authored.get("review_status") == "reviewed",
                "compile_status": compiled["compile_status"],
                "typed_clause_ids": list(authored.get("clause_identity") or []),
                "clause_types": sorted(
                    str(clause.get("type"))
                    for clause in authored.get("clauses") or []
                ),
                "semantic_group": GROUP_LABELS.get(content_id, "unclassified"),
                "source_bound_blockers": (
                    ["existing generic consumer is not source-complete for this shape"]
                    if content_id not in SUMMON_IDS
                    else []
                ),
            }
        )
    groups: dict[str, list[str]] = {}
    for row in rows:
        groups.setdefault(row["semantic_group"], []).append(row["content_id"])
    return {
        "authoritative_census_size": len(authoritative_ids),
        "remaining_compile_only_size": len(ids),
        "remaining_compile_only_ids": ids,
        "rows": rows,
        "groups": [
            {
                "semantic_group": group,
                "member_count": len(member_ids),
                "content_ids": member_ids,
                "shared_consumer": (
                    "spell.summon.v1"
                    if group == "summon.stat_block.lifecycle"
                    else None
                ),
            }
            for group, member_ids in sorted(groups.items())
        ],
    }


def _strong_evidence(*, include_current: bool) -> dict[str, dict[str, Any]]:
    current_artifact = str(RESULT_PATH.relative_to(ROOT))
    return {
        content_id: row
        for content_id, row in load_production_runtime_evidence(
            ROOT,
            pack_id=None,
            required_checks=("all_required_checks_passed",),
            require_name_branch_free=True,
        ).items()
        if (row.get("evidence_path") == current_artifact) is include_current
    }


def _occupied_probe(client: TestClient, helpers: Any) -> dict[str, Any]:
    spell_id = SUMMON_IDS[1]
    scene = helpers._setup(client, spell_id)
    body = helpers._body(
        scene,
        key="round-liv-occupied",
        choice="land",
        row=8,
        col=8,
    )
    before = client.get(
        f"{scene['base']}/characters/{scene['character']['id']}"
    ).json()
    response = client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    after = client.get(
        f"{scene['base']}/characters/{scene['character']['id']}"
    ).json()
    before_slot = before["spellcasting"]["slots"]["2"]["current"]
    after_slot = after["spellcasting"]["slots"]["2"]["current"]
    return {
        "status": response.status_code,
        "rejected_as_occupied": response.status_code == 400
        and "occupied" in response.text,
        "slot_before": before_slot,
        "slot_after": after_slot,
        "no_payment": before_slot == after_slot,
    }


def _payload_drift_probe(client: TestClient, helpers: Any) -> dict[str, Any]:
    spell_id = SUMMON_IDS[1]
    scene = helpers._setup(client, spell_id)
    body = helpers._body(
        scene,
        key="round-liv-payload-drift",
        choice="land",
        row=10,
        col=10,
    )
    preview = client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    if preview.status_code != 200:
        return {"preview_status": preview.status_code, "rejected": False}
    drifted = {**body, "summon_choice": "air", "preview_token": preview.json()["preview_token"]}
    response = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json=drifted,
    )
    return {
        "preview_status": preview.status_code,
        "confirm_status": response.status_code,
        "rejected": response.status_code in {400, 409},
    }


def _stale_cas_probe(client: TestClient, helpers: Any) -> dict[str, Any]:
    spell_id = SUMMON_IDS[1]
    scene = helpers._setup(client, spell_id)
    body = helpers._body(
        scene,
        key="round-liv-stale-cas",
        choice="land",
        row=10,
        col=10,
    )
    preview = client.post(
        f"{scene['base']}/content-ir/runtime/preview",
        json=body,
    )
    if preview.status_code != 200:
        return {"preview_status": preview.status_code, "rejected": False}
    changed = client.patch(
        f"{scene['base']}/combats/{scene['combat']['id']}/combatants/{scene['actor']['id']}",
        json={"action_available": False, "version": scene["actor"]["version"]},
    )
    response = client.post(
        f"{scene['base']}/content-ir/runtime/confirm",
        json={**body, "preview_token": preview.json()["preview_token"]},
    )
    return {
        "preview_status": preview.status_code,
        "mutation_status": changed.status_code,
        "confirm_status": response.status_code,
        "rejected": response.status_code in {400, 409},
        "mentions_version": "version" in response.text.lower()
        or "action" in response.text.lower(),
    }


def _isolated_receipts() -> tuple[dict[str, Any], dict[str, bool]]:
    helpers = _load_old_helpers()
    records = helpers._load_records()
    test_helpers = helpers._load_test_helpers()
    evidence: dict[str, Any] = {}
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="round-liv-summon-") as directory:
        database_url = f"sqlite:///{Path(directory) / 'isolated.db'}"
        os.environ["DND_DM_DATABASE_URL"] = database_url
        command.upgrade(Config(str(ROOT / "backend/alembic.ini")), "head")
        settings = Settings(environment="test", database_url=database_url)
        with TestClient(create_app(settings)) as client:
            for content_id in SUMMON_IDS:
                record = records[content_id]
                metadata = helpers.SPELLS[content_id]
                scene = test_helpers._setup(client, content_id)
                body = test_helpers._body(
                    scene,
                    key=f"round-liv-{content_id.rsplit(':', 1)[-1]}",
                    choice=metadata["choice"],
                    row=10,
                    col=10,
                )
                preview = client.post(
                    f"{scene['base']}/content-ir/runtime/preview", json=body
                )
                confirmed = client.post(
                    f"{scene['base']}/content-ir/runtime/confirm",
                    json={**body, "preview_token": preview.json()["preview_token"]},
                )
                replay = client.post(
                    f"{scene['base']}/content-ir/runtime/confirm",
                    json={**body, "preview_token": preview.json()["preview_token"]},
                )
                result = confirmed.json()
                engine = create_engine(database_url)
                with Session(engine) as session:
                    actor = session.scalar(
                        select(Combatant).where(Combatant.id == scene["actor"]["id"])
                    )
                    operation = session.scalar(
                        select(OperationTransaction).where(
                            OperationTransaction.idempotency_key
                            == f"content-ir:{body['idempotency_key']}:summon"
                        )
                    )
                    action = session.scalar(
                        select(CombatAction).where(
                            CombatAction.idempotency_key
                            == f"content-ir:{body['idempotency_key']}:summon"
                        )
                    )
                    operation_bound = (
                        actor is not None
                        and operation is not None
                        and action is not None
                        and action.transaction_id == operation.id
                    )
                    spell_record = _compiled_record_checks(record)
                    runtime_checks = {
                        **spell_record,
                        "preview_confirm_replay": (
                            preview.status_code == 200
                            and confirmed.status_code == 200
                            and replay.status_code == 200
                            and replay.json().get("already_applied") is True
                            and result.get("production_runtime_full") is True
                        ),
                        "operation_transaction_binding": operation_bound,
                    }
                    checks.update(
                        {
                            f"{content_id}:source_bound": spell_record["source_bound"],
                            f"{content_id}:generic_consumer": spell_record[
                                "generic_consumer"
                            ],
                            f"{content_id}:preview_confirm_replay": runtime_checks[
                                "preview_confirm_replay"
                            ],
                            f"{content_id}:operation_transaction_binding": operation_bound,
                        }
                    )
                    evidence[content_id] = {
                        "content_id": content_id,
                        "content_kind": "spell",
                        "production_runtime_full": True,
                        "consumer": "spell.summon.v1",
                        "source": {
                            "source_record_id": record["authored"]["source_record_id"],
                            "source_path": record["authored"]["source_path"],
                            "source_fingerprint": record["authored"]["source_fingerprint"],
                            "source_checksum": record["authored"]["source_provenance"][
                                "source_checksum"
                            ],
                        },
                        "preview": _stable(preview.json()),
                        "confirm_receipt": _stable(result),
                        "replay_receipt": _stable(replay.json()),
                        "persisted_snapshot": _stable(actor.snapshot_json if actor else {}),
                        "operation_transaction": _stable(
                            {
                                "id": operation.id if operation else None,
                                "operation_type": operation.operation_type
                                if operation
                                else None,
                                "status": operation.status if operation else None,
                                "before_snapshot": operation.before_snapshot
                                if operation
                                else None,
                                "after_snapshot": operation.after_snapshot
                                if operation
                                else None,
                            }
                        ),
                        "combat_action": _stable(
                            {
                                "id": action.id if action else None,
                                "transaction_id": action.transaction_id
                                if action
                                else None,
                                "idempotency_key": action.idempotency_key
                                if action
                                else None,
                            }
                        ),
                        "source_snapshot": _stable(
                            {
                                "combatant_id": actor.id if actor else None,
                                "version": actor.version if actor else None,
                                "snapshot_json": actor.snapshot_json if actor else None,
                            }
                        ),
                        "checks": runtime_checks,
                    }
            occupied = _occupied_probe(client, test_helpers)
            payload_drift = _payload_drift_probe(client, test_helpers)
            stale_cas = _stale_cas_probe(client, test_helpers)
            source_lifecycle = helpers._run_source_lifecycle_probe(client, test_helpers)
            rollback = helpers._run_rollback_probe(client, test_helpers)
            spell_runs = {
                content_id: helpers._run_spell(
                    client,
                    test_helpers,
                    content_id,
                    records[content_id],
                    key_suffix=(
                        "beast"
                        if content_id.endswith("54c8c29188db1442473d9dc1")
                        else "undead"
                    ),
                )
                for content_id in SUMMON_IDS
            }
            default_behavior = {
                content_id: row["default_behavior"]
                for content_id, row in spell_runs.items()
            }
            checks.update(
                {
                    "occupied_position_rejected_before_payment": (
                        occupied["rejected_as_occupied"] and occupied["no_payment"]
                    ),
                    "payload_drift_rejected": payload_drift["rejected"],
                    "stale_cas_rejected": (
                        stale_cas["rejected"] and stale_cas["mentions_version"]
                    ),
                    "source_concentration_lifecycle": bool(source_lifecycle),
                    "spell_slot_rollback": bool(rollback),
                    "default_behavior_executed": all(
                        item["status"] == "applied"
                        and item["on_no_command"] == "dodge"
                        and item["dodge_applied"]
                        and item["movement_status"] == "applied"
                        and item["moved_ft"] > 0
                        and item["action_available_after"] is False
                        and item["position_changed"]
                        for item in default_behavior.values()
                    ),
                }
            )
            evidence["_probes"] = {
                "occupied_position": occupied,
                "payload_drift": payload_drift,
                "stale_cas": stale_cas,
                "source_concentration_lifecycle": {"passed": bool(source_lifecycle)},
                "spell_slot_rollback": {"passed": bool(rollback)},
                "default_behavior": _stable(default_behavior),
            }
    return evidence, checks


def _compiled_record_checks(record: dict[str, Any]) -> dict[str, bool]:
    authored = record["authored"]
    compiled = record["compiled"]
    blocks = record["blocks"]
    consumers = [
        item["consumer_id"]
        for item in resolve_production_consumers(
            content_kind="spell",
            runtime_schema_version="spell-runtime-1",
            blocks=blocks,
        )
    ]
    return {
        "source_bound": (
            authored.get("source_record_id") == authored.get("source_provenance", {}).get(
                "source_record_id", authored.get("source_record_id")
            )
            and bool(authored.get("source_fingerprint"))
            and bool(authored.get("source_path"))
            and bool(authored.get("source_provenance", {}).get("source_checksum"))
            and bool(authored.get("source_evidence", {}).get("source_text"))
        ),
        "compile_full": compiled.get("compile_status") == "full",
        "generic_consumer": consumers
        == ["spell.summon.v1", "spell_economy.concentration.v1"],
    }


def main() -> int:
    census = _census()
    evidence, checks = _isolated_receipts()
    probes = evidence.pop("_probes")
    checks["source_provenance"] = all(
        row["source_complete"] and row["compile_status"] == "full"
        for row in census["rows"]
        if row["content_id"] in SUMMON_IDS
    )
    checks["source_bound_compile_full"] = checks["source_provenance"]
    checks["generic_consumer_exact"] = set(evidence) == set(SUMMON_IDS)
    authoritative = authoritative_compile_only_ids(ROOT)
    prior_strong = _strong_evidence(include_current=False)
    prior_strong_ids = set(prior_strong)
    current_strong_ids = set(evidence)
    before_compile_only = project_compile_only_ids(authoritative, prior_strong_ids)
    after_compile_only = project_compile_only_ids(
        authoritative,
        prior_strong_ids | current_strong_ids,
    )
    production_before = {
        content_id
        for content_id, row in load_production_runtime_evidence(
            ROOT, pack_id=None
        ).items()
        if row.get("evidence_path") != str(RESULT_PATH.relative_to(ROOT))
    }
    production_after = set(
        load_production_runtime_evidence(ROOT, pack_id=None)
    )
    migration = build_migration(ROOT)
    unique_compiled = int(migration["current_project_compiled_unique"])
    code_paths = (
        ROOT / "backend/src/dnd_dm_assistant/application/content_ir_runtime.py",
        ROOT
        / "backend/src/dnd_dm_assistant/application/content_ir_production_registry.py",
        ROOT / "backend/src/dnd_dm_assistant/infrastructure/database/combat_service.py",
    )
    code_text = "\n".join(path.read_text(encoding="utf-8") for path in code_paths)
    name_branch_count = sum(
        code_text.count(marker)
        for marker in (
            "Summon Beast",
            "Summon Undead",
            "54c8c29188db1442473d9dc1",
            "083419d9de551806a5ca9748",
        )
    )
    checks.update(
        {
            "authoritative_ids_present": set(SUMMON_IDS).issubset(authoritative),
            "already_in_production_union": set(SUMMON_IDS).issubset(production_before),
            "absent_from_prior_strong_evidence": not (
                set(SUMMON_IDS) & prior_strong_ids
            ),
            "current_strong_evidence_exactly_adds_candidates": (
                current_strong_ids == set(SUMMON_IDS)
            ),
            "each_candidate_removed_once": (
                before_compile_only - after_compile_only == set(SUMMON_IDS)
                and after_compile_only - before_compile_only == set()
            ),
            "duplicate_invalid_evidence_is_set_idempotent": (
                project_compile_only_ids(
                    authoritative,
                    list(prior_strong_ids)
                    + list(SUMMON_IDS)
                    + list(SUMMON_IDS)
                    + ["", "invalid-content-id"],
                )
                == after_compile_only
            ),
            "unrelated_compile_only_ids_unchanged": (
                (before_compile_only - set(SUMMON_IDS))
                == (after_compile_only - set())
            ),
            "unrelated_production_ids_unchanged": production_before == production_after,
            "name_branch_free": name_branch_count == 0,
            "current_evidence_rows_source_bound": all(
                row.get("production_runtime_full") is True
                and row.get("content_id") in SUMMON_IDS
                and row.get("source", {}).get("source_record_id")
                for row in evidence.values()
            ),
        }
    )
    checks["protected_ollama_sha_exact"] = _protected_ok()
    checks["historical_xliii_sha_exact"] = _sha(
        ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
    ) == XLIII_SHA
    checks["all_required_checks_passed"] = all(checks.values())
    before = {
        "production": len(production_before),
        "compile_only": len(before_compile_only),
        "unique_compiled": unique_compiled,
    }
    produced_ids = list(SUMMON_IDS) if checks["all_required_checks_passed"] else []
    result = {
        "schema_version": "content-ir-production-runtime-1",
        "artifact_date": "2026-08-14",
        "round_id": "round-LIV",
        "content_kind": "spell",
        "production_runtime_full_ids": produced_ids,
        "evidence_by_id": evidence if produced_ids else {},
        "checks": {
            **checks,
            "name_branch_count": name_branch_count,
            "formal_database_written": False,
            "formal_registry_written": False,
        },
        "all_required_checks_passed": checks["all_required_checks_passed"],
    }
    after = {
        "production": len(production_after),
        "compile_only": len(after_compile_only),
        "unique_compiled": unique_compiled,
    }
    report = {
        "schema_version": "round-LIV-summon-census-closure-1",
        "artifact_date": "2026-08-14",
        "baseline_commit": "46eb58ee3bbd4dc96050a48f0b7fd562fa3946e4",
        "decision": "promote_existing_generic_summon_consumer",
        "chosen_cluster": "summon.stat_block.lifecycle",
        "chosen_content_ids": list(SUMMON_IDS),
        "candidate_comparison": {
            "selection_basis": [
                "source-complete typed clauses",
                "existing generic spell.summon.v1 consumer",
                "real isolated API receipt, snapshot, transaction, CAS/replay and rollback evidence",
            ],
            "excluded_candidates": "All other remaining rows retain source-bound shape-specific blockers listed in census rows.",
        },
        "census": census,
        "before": before,
        "after": after,
        "projection_sets": {
            "prior_strong_production_ids": sorted(prior_strong_ids),
            "current_strong_production_ids": sorted(current_strong_ids),
            "before_compile_only_ids": sorted(before_compile_only),
            "after_compile_only_ids": sorted(after_compile_only),
            "production_before_ids": sorted(production_before),
            "production_after_ids": sorted(production_after),
        },
        "probe_results": probes,
        "production_runtime_full_ids": produced_ids,
        "checks": result["checks"],
        "evidence_artifact": str(RESULT_PATH.relative_to(ROOT)),
        "focused_test": FOCUSED,
        "historical_report_sha256": XLIII_SHA,
        "protected_ollama_sha256": OLLAMA_SHA,
        "no_push": True,
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    loaded_current = load_production_runtime_evidence(
        ROOT,
        pack_id=None,
        required_checks=("all_required_checks_passed",),
        require_name_branch_free=True,
    )
    checks["current_loader_acceptance"] = set(SUMMON_IDS).issubset(loaded_current)
    checks["all_required_checks_passed"] = all(
        value for key, value in checks.items() if key != "all_required_checks_passed"
    )
    result["checks"] = {**checks, "name_branch_count": name_branch_count}
    result["all_required_checks_passed"] = checks["all_required_checks_passed"]
    report["checks"] = result["checks"]
    report["after"] = after
    report["production_runtime_full_ids"] = (
        list(SUMMON_IDS) if checks["all_required_checks_passed"] else []
    )
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "all_required_checks_passed": checks["all_required_checks_passed"],
                "census_size": len(census["remaining_compile_only_ids"]),
                "promoted_ids": produced_ids,
                "before": before,
                "after": after,
                "result": str(RESULT_PATH.relative_to(ROOT)),
                "report": str(REPORT_PATH.relative_to(ROOT)),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if checks["all_required_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
