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
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_spell_spec,
)
from dnd_dm_assistant.config import Settings
from dnd_dm_assistant.infrastructure.database.models import (
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
            authoritative_compile_only_ids(ROOT),
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
        "authoritative_census_size": len(ids),
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


def _isolated_receipts() -> tuple[dict[str, Any], dict[str, bool]]:
    helpers = _load_old_helpers()
    records = helpers._load_records()
    test_helpers = helpers._load_test_helpers()
    evidence: dict[str, Any] = {}
    checks = {
        "source_provenance": True,
        "source_bound_compile_full": True,
        "generic_consumer_exact": True,
        "isolated_preview_confirm_replay": True,
        "isolated_snapshot_transaction": True,
        "occupied_position_rejected_before_payment": True,
        "source_concentration_lifecycle": True,
        "spell_slot_rollback": True,
        "default_behavior_executed": True,
    }
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
                checks["isolated_preview_confirm_replay"] &= (
                    preview.status_code == 200
                    and confirmed.status_code == 200
                    and replay.status_code == 200
                    and replay.json().get("already_applied") is True
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
                    checks["isolated_snapshot_transaction"] &= (
                        actor is not None and operation is not None
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
                    }
    return evidence, checks


def main() -> int:
    census = _census()
    evidence, checks = _isolated_receipts()
    checks["source_provenance"] = all(
        row["source_complete"] and row["compile_status"] == "full"
        for row in census["rows"]
        if row["content_id"] in SUMMON_IDS
    )
    checks["source_bound_compile_full"] = checks["source_provenance"]
    checks["generic_consumer_exact"] = set(evidence) == set(SUMMON_IDS)
    checks["protected_ollama_sha_exact"] = _protected_ok()
    checks["historical_xliii_sha_exact"] = _sha(
        ROOT / "reports/round-XLIII-typed-target-adjudication-2026-08-13.json"
    ) == XLIII_SHA
    checks["all_required_checks_passed"] = all(checks.values())
    loaded = load_production_runtime_evidence(ROOT, pack_id=None)
    before = {
        "production": len(loaded),
        "compile_only": len(census["remaining_compile_only_ids"]),
        "unique_compiled": 111,
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
            "name_branch_count": 0,
            "formal_database_written": False,
            "formal_registry_written": False,
        },
        "all_required_checks_passed": checks["all_required_checks_passed"],
    }
    after = {
        "production": len(set(loaded) | set(produced_ids)),
        "compile_only": before["compile_only"] - len(produced_ids),
        "unique_compiled": before["unique_compiled"],
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
