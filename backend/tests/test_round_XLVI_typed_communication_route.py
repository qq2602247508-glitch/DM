from __future__ import annotations

import json
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/validate-round-XLVI-typed-spell-communication-route.py"
REPORT = ROOT / "reports/round-XLVI-typed-spell-communication-route-2026-08-13.json"


def test_round_xlvi_audit_is_conservative_and_deterministic() -> None:
    namespace = runpy.run_path(str(SCRIPT))
    first = namespace["build_report"]()
    second = namespace["build_report"]()
    assert first["after"]["promoted_ids"] == []
    assert len(first["after"]["retained_compile_only_ids"]) == 5
    assert first["count_delta"] == {"compile_only": 0, "production": 0, "unique_compiled": 0}
    assert first["report_fingerprint"] == second["report_fingerprint"]
    assert first["focused_tests"]["passed"] is True
    saved = json.loads(REPORT.read_text(encoding="utf-8"))
    assert saved["round_id"] == "round-XLVI"
    assert saved["promotion_decision"] == "no_promotion"
