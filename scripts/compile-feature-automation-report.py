#!/usr/bin/env python3
# ruff: noqa: N999
"""Generate capability, legacy parity and feature-pack readiness reports."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    legacy_feature_spec_from_audit_row,
)
from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackImporter,
    load_feature_pack,
)
from dnd_dm_assistant.domain.feature_capabilities import default_capability_catalog

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts/audit-class-feature-coverage.py"
DEMO_PACK = ROOT / "backend/tests/fixtures/feature_packs/automation_demo_pack.json"
REPORT_DIR = ROOT / "reports"


def _audit_module() -> Any:
    spec = importlib.util.spec_from_file_location("feature_audit_for_ir_report", AUDIT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load audit module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    audit_report = _audit_module().audit()
    catalog = default_capability_catalog()
    _write(
        REPORT_DIR / "feature-capability-catalog-2026-08-09.json",
        {
            "schema_version": "feature-capability-catalog-1",
            "capabilities": catalog.to_dict(),
            "counts": Counter(item.production_status for item in catalog.descriptors()),
            "fingerprint": catalog.fingerprint(),
        },
    )

    compiler = FeatureCompiler(catalog, status_authority="legacy")
    pilot_compiler = FeatureCompiler(catalog, status_authority="compiler")
    parity_rows: list[dict[str, Any]] = []
    parity_counts: Counter[str] = Counter()
    partial_rows: list[dict[str, Any]] = []
    for row in audit_report["rows"]:
        if row["runtime_status"] == "full":
            spec, adapter_used = legacy_feature_spec_from_audit_row(row)
            result = compiler.compile(spec, legacy_adapter_used=adapter_used)
            parity_counts[result.compile_status] += 1
            if result.compile_status == "full" and len(parity_rows) < 30:
                pilot_result = (
                    pilot_compiler.compile(spec, legacy_adapter_used=adapter_used)
                    if len(parity_rows) < 10
                    else None
                )
                parity_rows.append(
                    {
                        "feature_id": spec.feature_id,
                        "feature_name": row["feature_name"],
                        "runtime_sections": row.get("runtime_sections", []),
                        "legacy_status": row["runtime_status"],
                        "compiler_status": result.compile_status,
                        "status_authority": result.status_authority,
                        "legacy_adapter_used": result.legacy_adapter_used,
                        "fingerprint": result.fingerprint,
                        "pilot_authority": (
                            pilot_result.status_authority if pilot_result else "legacy"
                        ),
                        "pilot_compile_status": (
                            pilot_result.compile_status if pilot_result else None
                        ),
                    }
                )
        elif row["runtime_status"] != "dm_only" and len(partial_rows) < 10:
            spec, adapter_used = legacy_feature_spec_from_audit_row(row)
            result = compiler.compile(spec, legacy_adapter_used=adapter_used)
            partial_rows.append(
                {
                    "feature_id": spec.feature_id,
                    "feature_name": row["feature_name"],
                    "legacy_status": row["runtime_status"],
                    "compiler_status": result.compile_status,
                    "unsupported_operators": list(result.unsupported_operators),
                    "unsupported_conditions": list(result.unsupported_conditions),
                    "unsupported_combinations": list(result.unsupported_combinations),
                    "manual_boundaries": list(result.manual_boundaries),
                    "clause_results": [item.to_dict() for item in result.clause_results],
                }
            )

    _write(
        REPORT_DIR / "feature-ir-parity-2026-08-09.json",
        {
            "schema_version": "feature-ir-parity-1",
            "audit_status_counts": audit_report["status_counts"],
            "compiler_status_counts": dict(sorted(parity_counts.items())),
            "selected_parity_count": len(parity_rows),
            "compiler_pilot_count": sum(
                item["pilot_authority"] == "compiler" for item in parity_rows
            ),
            "selected_parity_rows": parity_rows,
            "partial_diagnostics": partial_rows,
            "legacy_adapter": True,
        },
    )

    demo_manifest = load_feature_pack(DEMO_PACK)
    demo_result = FeaturePackImporter(compiler=FeatureCompiler(catalog)).dry_run(demo_manifest)
    _write(
        REPORT_DIR / "feature-pack-readiness-2026-08-09.json",
        {
            "schema_version": "feature-pack-readiness-1",
            "pack_id": demo_manifest.pack_id,
            "pack_version": demo_manifest.pack_version,
            "counts": demo_result.counts,
            "feature_results": [item.to_dict() for item in demo_result.feature_results],
            "conflicts": list(demo_result.conflicts),
            "migration_plan": demo_result.migration_plan,
        },
    )
    print(
        json.dumps(
            {
                "capability_count": len(catalog.descriptors()),
                "parity": dict(sorted(parity_counts.items())),
                "selected_parity_count": len(parity_rows),
                "compiler_pilot_count": sum(
                    item["pilot_authority"] == "compiler" for item in parity_rows
                ),
                "demo_pack_counts": demo_result.counts,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
