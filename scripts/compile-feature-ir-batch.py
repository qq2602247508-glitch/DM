#!/usr/bin/env python3
# ruff: noqa: N999
"""Preview/replay a typed Feature IR batch against the real audit corpus."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.feature_ir_batch_compiler import (
    compile_audit_batch,
    parse_feature_specs,
)

ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = ROOT / "scripts/audit-class-feature-coverage.py"


def _audit_rows(path: Path | None) -> list[dict[str, Any]]:
    if path is not None:
        value = json.loads(path.read_text(encoding="utf-8"))
        rows = value.get("rows") if isinstance(value, dict) else None
        if not isinstance(rows, list):
            raise ValueError("audit JSON must contain rows")
        return [dict(item) for item in rows if isinstance(item, dict)]
    spec = importlib.util.spec_from_file_location("feature_batch_audit", AUDIT_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load audit script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return [
        dict(item)
        for item in module.audit()["rows"]
        if item.get("runtime_status") == "partial"
    ]


def _specs(path: Path | None) -> tuple[object, ...]:
    if path is None:
        return ()
    value = json.loads(path.read_text(encoding="utf-8"))
    raw = value.get("features") if isinstance(value, dict) else None
    if not isinstance(raw, list):
        raise TypeError("template manifest must contain features")
    return parse_feature_specs(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-json", type=Path)
    parser.add_argument("--template-manifest", type=Path)
    parser.add_argument("--existing", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("dry-run", "preview", "apply", "replay"),
        default="preview",
    )
    args = parser.parse_args()
    existing = (
        json.loads(args.existing.read_text(encoding="utf-8"))
        if args.existing is not None
        else None
    )
    result = compile_audit_batch(
        _audit_rows(args.audit_json),
        specs=_specs(args.template_manifest),
        mode=args.mode,
        existing=existing,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["conflicts"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
