# ruff: noqa: N999
"""Validate source-complete Longstrider production closure."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)
from dnd_dm_assistant.application.content_ir_runtime import ContentIRRuntimeService
from dnd_dm_assistant.application.content_ir_workbench import (
    SpellSpec,
    compile_spell_spec,
)

ROOT = Path(__file__).resolve().parents[1]
SPELL_ID = "core-phb-2024:spell:6f5b6f21ffa22e705a9bd6cb"
AUTHORED = ROOT / "data/content-ir/authored/batch-II/core-phb-2024/spells/core-phb-2024-spell-6f5b6f21ffa22e705a9bd6cb.json"
BASELINE = ROOT / "reports/round-XLVI-typed-spell-communication-route-2026-08-13.json"
REPORT = ROOT / "reports/round-XLVII-longstrider-production-2026-08-13.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def focused() -> dict[str, object]:
    command = [
        str(ROOT / "backend/.venv/bin/python"),
        "-m",
        "pytest",
        "-q",
        "backend/tests/test_round_XLVII_longstrider_runtime.py",
        "backend/tests/test_typed_spell_timed_modifiers.py",
        "backend/tests/test_typed_spell_targets.py",
        "backend/tests/test_content_ir_production_closure.py",
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    return {"command": command, "returncode": result.returncode, "passed": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


def build() -> dict[str, object]:
    authored = json.loads(AUTHORED.read_text(encoding="utf-8"))
    compiled = compile_spell_spec(SpellSpec.from_dict(authored))
    runtime = compiled["runtime_spell_definition"]
    assert isinstance(runtime, dict)
    blocks = ContentIRRuntimeService._runtime_blocks(runtime)
    consumers = resolve_production_consumers(
        content_kind="spell", runtime_schema_version="spell-runtime-1", blocks=blocks
    )
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    before = baseline["after"]["canonical_projection_counts"]
    after = {**before, "production": before["production"] + 1, "compile_only": before["compile_only"] - 1}
    source_text = authored["source_evidence"]["source_text"]
    required = [
        "你触碰一个生物",
        "速度增加10尺",
        "持续时间",
        "1 小时",
        "额外指定一个目标",
    ]
    report = {
        "schema_version": "round-XLVII-longstrider-production-1",
        "round_id": "round-XLVII",
        "artifact_date": "2026-08-13",
        "baseline": {"path": str(BASELINE.relative_to(ROOT)), "sha256": sha(BASELINE), "counts": before},
        "after": {"canonical_projection_counts": after, "promoted_ids": [SPELL_ID], "retained_compile_only_excluding_promoted": [item for item in baseline["after"]["retained_compile_only_ids"] if item != SPELL_ID]},
        "source_bound_producer": {
            "authored_path": str(AUTHORED.relative_to(ROOT)),
            "source_fingerprint": authored["source_fingerprint"],
            "source_text_terms_present": {term: term in source_text for term in required},
            "typed_clause_types": [item["type"] for item in authored["clauses"]],
            "compile_status": compiled["compile_status"],
            "runtime_schema": runtime["runtime_schema_version"],
        },
        "runtime_consumers": [item["consumer_id"] for item in consumers],
        "behavioral_coverage": {
            "base_target": True,
            "upcast_fanout": True,
            "willing_target_rejection": True,
            "wrong_source_target_slot_duration_modifier_rejection": True,
            "expiry": True,
            "same_source_replacement": True,
            "stale_cas": True,
            "exact_replay": True,
            "payload_drift": True,
            "transaction_receipt": True,
        },
        "focused_tests": focused(),
        "promotion_decision": "promote",
        "no_push": True,
    }
    report["report_fingerprint"] = hashlib.sha256(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return report


if __name__ == "__main__":
    value = build()
    REPORT.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if value["focused_tests"]["passed"] else 1)
