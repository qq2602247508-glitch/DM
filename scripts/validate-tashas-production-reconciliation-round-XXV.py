# ruff: noqa: N999
"""Validate Round XXV production evidence and whole-pack reconciliation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_evidence import (
    load_production_runtime_evidence,
)
from dnd_dm_assistant.application.content_ir_workbench import load_records
from dnd_dm_assistant.application.tashas_recovery import load_item_production_evidence
from dnd_dm_assistant.application.tashas_whole_pack import (
    PACK_ID,
    build_migration,
    database_fingerprint,
    existing_project_production_ids,
    protected_path_fingerprints,
    select_source_records,
)
from dnd_dm_assistant.domain.content_ir_status import summarize_status_layers

ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / "reports/tashas-production-reconciliation-round-XXV-2026-08-12.json"
WHOLE_PACK_PATH = ROOT / "reports/tashas-whole-pack-report-2026-08-11.json"
ITEM_PATH = ROOT / "reports/tashas-item-ir-report-2026-08-11.json"
BASELINE_PATH = ROOT / "reports/tashas-baseline-2026-08-11.json"
PROTECTED_FILE = ROOT / "backend/tests/ollama.py"
PROTECTED_DIR = ROOT / "backend/tests/integrations"
ROUND_XXVI_RESULT = (
    ROOT / "data/content-ir/compiled/production-runtime-results-XXVI.json"
)

EXPECTED_PROTECTED = {
    "database": "f3abdcf57b0d71888f085ca081511df4e4f23f100066b402d49d769089fa6aad",
    "formal_registry": "f4b5eab251b2f9f2d426ba271bb25faec773884a327f9d46e566791b97cbca6b",
    "integrations_manifest": "ae4ef9f5518ac28272643dc668c40ed49e76da052c84c7023bbb5636d303cd91",
    "ollama": "8027a6d8d23f42110ce9d0fa00308d0f15c54ebe19211735bdb549abc15e6ab3",
}


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _protected_fingerprints() -> dict[str, str | None]:
    rows = [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": _sha256(path),
        }
        for path in sorted(path for path in PROTECTED_DIR.rglob("*") if path.is_file())
    ]
    return {
        "ollama": _sha256(PROTECTED_FILE),
        "integrations_manifest": _fingerprint(rows),
    }


def main() -> int:
    migration = build_migration(ROOT)
    source_records = select_source_records(
        load_records(ROOT / "data/generated-content/dnd5e_chm/json")
    )
    tasha_evidence = load_production_runtime_evidence(ROOT, pack_id=PACK_ID)
    project_ids = existing_project_production_ids(ROOT)
    item_ids = load_item_production_evidence(ROOT)
    layers = summarize_status_layers(migration["atoms"])
    whole_pack = json.loads(WHOLE_PACK_PATH.read_text(encoding="utf-8"))
    item_report = json.loads(ITEM_PATH.read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    round_xxvi = json.loads(ROUND_XXVI_RESULT.read_text(encoding="utf-8"))
    current_database_fingerprint = database_fingerprint(ROOT)["fingerprint"]
    baseline_database_fingerprint = baseline["database_fingerprint"]["fingerprint"]
    current_protected = protected_path_fingerprints(ROOT)

    checks = {
        "source_records_144": len(source_records) == 144,
        "tasha_receipts_deduplicated_current_132": (
            len(tasha_evidence) == 132
            and len(tasha_evidence) == len(set(tasha_evidence))
        ),
        "project_receipts_deduplicated_current_189": (
            len(project_ids) == 189
            and len(project_ids) == len(set(project_ids))
        ),
        "tasha_receipts_subset_project": set(tasha_evidence).issubset(project_ids),
        "summon_beast_receipt_present": (
            "tashas-cauldron:spell:54c8c29188db1442473d9dc1" in tasha_evidence
        ),
        "summon_undead_receipt_present": (
            "tashas-cauldron:spell:083419d9de551806a5ca9748" in tasha_evidence
        ),
        "no_duplicate_tasha_receipt_ids": len(tasha_evidence) == len(set(tasha_evidence)),
        "item_evidence_40": len(item_ids) == 40,
        "item_evidence_is_item_scoped": all(
            item_id.startswith("content.tashas-cauldron.item.") for item_id in item_ids
        ),
        "atom_production_matches_status_layer": (
            migration["production_full"] == layers["registered_production_full"]
        ),
        "atom_dm_matches_status_layer": migration["dm_assisted"] == layers["dm_assisted"],
        "atom_game_usable_relation": (
            migration["game_usable"]
            == migration["production_full"] + migration["dm_assisted"]
            == layers["game_usable"]
        ),
        "whole_pack_report_current": (
            whole_pack["conversion"]["production_full"] == 89
            and whole_pack["conversion"]["dm_assisted"] == 2
            and whole_pack["conversion"]["game_usable"] == 91
            and whole_pack["conversion"]["compile_only"] == 3
        ),
        "item_report_current": (
            item_report["item_spec_total"] == 47
            and item_report["compile_full"] == 40
            and item_report["registered_production_full"] == 40
            and item_report["game_usable"] == 40
            and item_report["compile_only"] == 7
        ),
        "formal_database_unchanged": (
            current_database_fingerprint == baseline_database_fingerprint
            and baseline_database_fingerprint == EXPECTED_PROTECTED["database"]
            and round_xxvi.get("checks", {}).get("formal_database_unchanged") is True
        ),
        "formal_registry_unchanged": (
            round_xxvi.get("formal_registry_fingerprint")
            == EXPECTED_PROTECTED["formal_registry"]
            and round_xxvi.get("checks", {}).get("formal_registry_unchanged") is True
        ),
        "protected_paths_unchanged": current_protected
        == {
            "backend/tests/ollama.py": {
                "exists": True,
                "sha256": EXPECTED_PROTECTED["ollama"],
            },
            "backend/tests/integrations/": current_protected[
                "backend/tests/integrations/"
            ],
        }
        and _protected_fingerprints()
        == {
            "ollama": EXPECTED_PROTECTED["ollama"],
            "integrations_manifest": EXPECTED_PROTECTED["integrations_manifest"],
        },
        "name_branch_count_zero": (
            migration["item_spec_catalog"]["name_branch_count"] == 0
        ),
    }
    result = {
        "schema_version": "tashas-production-reconciliation-round-XXV-1",
        "round_id": "round-XXV",
        "pack_id": PACK_ID,
        "checks": checks,
        "counts": {
            "source_records": len(source_records),
            "tasha_receipts": len(tasha_evidence),
            "project_receipts": len(project_ids),
            "item_evidence": len(item_ids),
            "atom_status_layers": layers,
            "migration": {
                key: migration[key]
                for key in (
                    "content_atom_total",
                    "executable_candidate_total",
                    "authored_typed_ir",
                    "compile_full",
                    "runtime_preview_full",
                    "production_full",
                    "dm_assisted",
                    "game_usable",
                    "compile_only",
                    "manual_authoring",
                    "dm_reference",
                )
            },
        },
        "evidence": {
            "tasha_receipt_ids": sorted(tasha_evidence),
            "item_evidence_ids": sorted(item_ids),
            "current_whole_pack_report": str(WHOLE_PACK_PATH.relative_to(ROOT)),
            "current_item_report": str(ITEM_PATH.relative_to(ROOT)),
            "database_fingerprint": current_database_fingerprint,
            "baseline_database_fingerprint": baseline_database_fingerprint,
            "historical_round_xxvi_database_fingerprint": round_xxvi.get(
                "formal_database_fingerprint"
            ),
            "formal_registry_fingerprint": round_xxvi.get(
                "formal_registry_fingerprint"
            ),
            "protected_fingerprints": _protected_fingerprints(),
        },
    }
    RESULT_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"checks": checks, "result": str(RESULT_PATH.relative_to(ROOT))}, ensure_ascii=False, indent=2, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit("Round XXV reconciliation gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
