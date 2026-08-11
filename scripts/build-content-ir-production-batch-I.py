# ruff: noqa: N999
"""Build the small authored IR delta needed for the production closeout.

The existing batch-II directory is immutable baseline data for this task.  The
new source-reviewed records live in batch-III and are compiled independently,
so reports can distinguish conversion of the existing 100 from newly authored
IR without conflating compile and production status.
"""

from __future__ import annotations

import json
import runpy
import shutil
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_artifact_directory,
    compile_spell_spec,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "data/generated-content/dnd5e_chm/json"
AUTHORED_ROOT = ROOT / "data/content-ir/authored/batch-III"
COMPILED_ROOT = ROOT / "data/content-ir/compiled/batch-III"
REPORT_ROOT = ROOT / "reports"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_builder() -> dict[str, Any]:
    return runpy.run_path(str(ROOT / "scripts/build-content-ir-batch-II.py"))


def _manual_damage_clause(
    *,
    expression: str,
    damage_type: str,
    save_ability: str | None,
    half_on_success: bool,
    excerpt: str,
) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    if save_ability:
        clauses.append(
            {
                "type": "saving_throw",
                "clause_id": "save",
                "action_economy": "action",
                "save_ability": save_ability,
                "target": "one_creature",
                "half_on_success": half_on_success,
                "evidence_ref": excerpt,
            }
        )
    clauses.append(
        {
            "type": "damage",
            "clause_id": "damage",
            "action_economy": "action",
            "expression": expression,
            "damage": expression,
            "damage_type": damage_type,
            "target": "one_creature",
            "on_success": "half" if half_on_success else "none",
            "on_failure": "full",
            "timing": "immediate",
            "evidence_ref": excerpt,
        }
    )
    return clauses


def _manualize_fizban(
    spec: dict[str, Any],
    *,
    source_id: str,
    name: str,
    clauses: list[dict[str, Any]],
    excerpt: str,
) -> dict[str, Any]:
    result = dict(spec)
    result["name"] = name
    result["clauses"] = clauses
    result["evidence"] = [
        f"{clause['clause_id']}: {clause.get('evidence_ref', excerpt)}" for clause in clauses
    ]
    result["clause_identity"] = [
        f"fizbans-treasury:spell:{source_id}:{clause['clause_id']}" for clause in clauses
    ]
    result["manual_decisions"] = {
        "review_gate": "source paragraph manually reconciled with normalized record",
        "runtime": "only the explicit damage/save/concentration clauses are executable",
    }
    return result


def _build_specs(builder: dict[str, Any]) -> list[dict[str, Any]]:
    records = builder["load_records"](SOURCE_ROOT)
    by_id = {builder["_source_record_id"](item): item for item in records}
    selected: list[tuple[str, str, str, str, str]] = [
        ("21db89639520a9951088e222", "core-phb-2024", "2024", "spell", "致盲斩"),
        ("3f4fae885921a47ad0c6f759", "core-phb-2024", "2024", "spell", "指使术"),
        ("5842f6550b16755fb544c642", "core-phb-2024", "2024", "spell", "信仰守卫"),
        ("5dd11cb3fbb6d21ea53739f2", "core-phb-2024", "2024", "spell", "疗伤术"),
        ("56193b76694eafc2025e1c0b", "core-phb-2024", "2024", "spell", "虚假生命"),
        ("2940fd0bac27b811329157a9", "core-phb-2024", "2024", "spell", "医疗术"),
        ("4d94c0c610e955904d8893aa", "xanathars-guide", "2014", "spell", "霜噬"),
        ("25fd183be8a5a886bc180e83", "xanathars-guide", "2014", "spell", "潮涌"),
        ("3552e12594b2d8e6067f24f5", "xanathars-guide", "2014", "spell", "心灵尖啸"),
        ("a87ab0181a321cb09fef2884", "xanathars-guide", "2014", "spell", "钢风斩"),
        ("ef0f92b557fb48d421d462e1", "tashas-cauldron", "2014", "spell", "心灵之楔"),
        ("084712e58fd3714db50148c5", "fizbans-treasury", "2014", "spell", "阿莎德隆奔行"),
        ("49a5bacc752aa90fbbfbf316", "fizbans-treasury", "2014", "spell", "劳洛希姆心灵长枪"),
    ]
    specs: list[dict[str, Any]] = []
    for source_id, pack_id, ruleset, _kind, name in selected:
        record = by_id.get(source_id)
        if record is None:
            raise ValueError(f"missing source record {source_id}")
        spec = builder["_spell_record"](record, pack_id=pack_id, ruleset=ruleset)
        if spec is None:
            raise ValueError(f"source record did not produce a typed spell {source_id}")
        if pack_id == "fizbans-treasury" and source_id.startswith("084712"):
            excerpt = builder["_bounded_source_text"](record)
            spec = _manualize_fizban(
                spec,
                source_id=source_id,
                name=name,
                clauses=[
                    *[clause for clause in spec["clauses"] if clause["type"] in {"target_selection", "concentration", "upcast"}],
                    {
                        "type": "damage",
                        "clause_id": "damage",
                        "action_economy": "bonus_action",
                        "expression": "1d6",
                        "damage": "1d6",
                        "damage_type": "火焰",
                        "target": "one_creature",
                        "timing": "on_enter",
                        "evidence_ref": excerpt,
                    },
                ],
                excerpt=excerpt,
            )
        elif pack_id == "fizbans-treasury" and source_id.startswith("49a5"):
            excerpt = builder["_bounded_source_text"](record)
            existing_target = [
                clause for clause in spec["clauses"] if clause["type"] == "target_selection"
            ]
            spec = _manualize_fizban(
                spec,
                source_id=source_id,
                name=name,
                clauses=[
                    *existing_target,
                    *_manual_damage_clause(
                        expression="7d6",
                        damage_type="心灵",
                        save_ability="智力",
                        half_on_success=True,
                        excerpt=excerpt,
                    ),
                    {
                        "type": "apply_condition",
                        "clause_id": "condition",
                        "action_economy": "action",
                        "condition": "失能",
                        "target": "one_creature",
                        "duration": "target_turn_start",
                        "evidence_ref": excerpt,
                    },
                ],
                excerpt=excerpt,
            )
        compiled = compile_spell_spec(SpellSpec.from_dict(spec))
        if compiled["compile_status"] != "full":
            raise ValueError(
                f"new authored spell must compile full: {source_id}: {compiled.get('blockers')}"
            )
        specs.append(spec)
    return specs


def main() -> int:
    builder = _load_builder()
    specs = _build_specs(builder)
    if len(specs) != 13:
        raise ValueError(f"expected 13 new authored specs, got {len(specs)}")
    if AUTHORED_ROOT.exists():
        shutil.rmtree(AUTHORED_ROOT)
    if COMPILED_ROOT.exists():
        shutil.rmtree(COMPILED_ROOT)
    AUTHORED_ROOT.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        pack_id = str(spec["pack_id"])
        path = AUTHORED_ROOT / pack_id / "spells" / f"{spec['spell_id'].replace(':', '-')}.json"
        _write(path, spec)
    _write(
        AUTHORED_ROOT / "source-inventory.json",
        {
            "schema_version": "content-ir-source-inventory-1",
            "records": [
                {
                    "spell_id": spec["spell_id"],
                    "source_record_id": spec["source_record_id"],
                    "source_book": spec["source_book"],
                    "source_path": spec["source_path"],
                    "source_fingerprint": spec["source_fingerprint"],
                }
                for spec in sorted(specs, key=lambda item: item["spell_id"])
            ],
        },
    )
    typed_paths: list[str] = []
    source_fingerprints: dict[str, str] = {}
    for path in sorted(AUTHORED_ROOT.rglob("*.json")):
        if path.name == "source-inventory.json":
            continue
        spec = json.loads(path.read_text(encoding="utf-8"))
        relative = Path("typed-ir") / path.relative_to(AUTHORED_ROOT)
        _write(COMPILED_ROOT / relative, spec)
        typed_paths.append(relative.as_posix())
        source_fingerprints[str(spec["source_record_id"])] = str(spec["source_fingerprint"])
    manifest = {
        "schema_version": "content-ir-workbench-manifest-2",
        "pack_id": None,
        "pack_version": None,
        "source_book": None,
        "namespace": "content.batch-III",
        "ruleset_version": None,
        "source_fingerprints": dict(sorted(source_fingerprints.items())),
        "draft_paths": [],
        "typed_ir_paths": sorted(typed_paths),
        "compiler_fingerprint": builder["COMPILER_FINGERPRINT"],
        "capability_registry_version": "content-capabilities-1",
        "production_targets": {"database": False, "feature_registry": False, "campaign": False},
        "replay": {"policy": "same-manifest-fingerprint-is-idempotent"},
    }
    manifest["manifest_fingerprint"] = builder["_fingerprint"](manifest)
    _write(COMPILED_ROOT / "manifest.json", manifest)
    result = compile_artifact_directory(COMPILED_ROOT, write_files=True)
    _write(COMPILED_ROOT / "report.json", result)
    _write(
        REPORT_ROOT / "content-ir-production-authored-batch-I-2026-08-11.json",
        {
            "schema_version": "content-ir-production-authored-batch-I-1",
            "authored_count": len(specs),
            "compile_full_count": result["counts"].get("full", 0),
            "spell_ids": sorted(spec["spell_id"] for spec in specs),
            "compiled_path": "data/content-ir/compiled/batch-III/compile-result.json",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
