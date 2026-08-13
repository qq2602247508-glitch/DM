"""Build the evidence-driven source-boundary matrix for Bottled Respite."""

# ruff: noqa: N999

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features/genie-bottled-respite.json"
REPORT = ROOT / "reports/tashas-genie-vessel-source-boundary-2026-08-13.json"


def main() -> int:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    excerpt = raw["source_evidence"]["source_excerpt"]
    matrix = [
        {"id": "enter_action", "source": "以一个动作", "status": "contracted", "runtime": "vessel.space.v1"},
        {"id": "touch_vessel", "source": "在你触碰你器皿的情况下", "status": "contracted", "runtime": "authoritative_fact"},
        {"id": "companion_capacity", "source": "10级器皿庇护所：最多5个可见自愿生物", "status": "excluded_from_selected_feature", "runtime": "future Sanctuary Vessel capability"},
        {"id": "companion_distance", "source": "10级器皿庇护所：30尺内", "status": "excluded_from_selected_feature", "runtime": "future Sanctuary Vessel capability"},
        {"id": "interior_geometry", "source": "20尺半径，20尺高的圆柱形异次元空间", "status": "contracted", "runtime": "vessel.space.v1"},
        {"id": "interior_state", "source": "温度适宜、舒适的垫子和茶几", "status": "contracted", "runtime": "vessel.space.v1"},
        {"id": "external_sound", "source": "如同身在器皿所在之处一般听到外界的声音", "status": "blocked", "runtime": "sensory bridge"},
        {"id": "duration", "source": "熟练加值双倍数目的小时", "status": "contracted", "runtime": "proficiency_bonus_times_2"},
        {"id": "leave_conditions", "source": "死亡、器皿被摧毁、附赠动作离开", "status": "contracted", "runtime": "entity lifecycle"},
        {"id": "exit_placement", "source": "距离它最近的未占据空间", "status": "contracted", "runtime": "SpatialAuthority"},
        {"id": "carried_items", "source": "器皿内的一切物件将被留在其中直到被取出", "status": "blocked", "runtime": "containment/item consumer"},
        {"id": "destroyed_items", "source": "器皿被摧毁，物品完好无损出现在最近未占据空间", "status": "blocked", "runtime": "containment/item relocation"},
        {"id": "long_rest_limit", "source": "直到完成一次长休前不能再度进入", "status": "contracted", "runtime": "RestService reset"},
        {"id": "sanctuary_eject", "source": "10级器皿庇护所：附赠动作逐出任意数目的生物", "status": "excluded_from_selected_feature", "runtime": "future Sanctuary Vessel capability"},
        {"id": "sanctuary_short_rest", "source": "10级器皿庇护所：停留至少10分钟可视为完成短休", "status": "excluded_from_selected_feature", "runtime": "future Sanctuary Vessel capability"},
        {"id": "vessel_appearance", "source": "D6 器皿表：油灯、瓮、戒指、瓶子、小雕像、提灯", "status": "contracted", "runtime": "source-bound enum"},
        {"id": "vessel_size", "source": "微型物件", "status": "contracted", "runtime": "vessel.space.v1"},
        {"id": "nested_entry", "source": "source does not explicitly state nested entry", "status": "fail_closed_policy", "runtime": "vessel.space.v1"},
        {"id": "illegal_facts", "source": "user/DM cannot invent capacity, consent, position or occupancy", "status": "fail_closed_policy", "runtime": "authoritative facts"},
    ]
    report = {
        "schema_version": "tashas-genie-vessel-source-boundary-1",
        "feature_id": raw["feature_id"],
        "source": {
            "record_id": raw["source_record_id"],
            "fingerprint": raw["source_fingerprint"],
            "path": raw["source_path"],
            "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "excerpt": excerpt,
            "source_completeness": raw["source_completeness"],
        },
        "authored_ir": {
            "path": str(SOURCE.relative_to(ROOT)),
            "clause_ids": [item["clause_id"] for item in raw["clauses"]],
            "unmodeled_source_terms": raw["manual_decisions"]["unmodeled_source_terms"],
        },
        "matrix": matrix,
        "promotion": {
            "compile_only": True,
            "reason": "source is incomplete and vessel persistence/containment/API receipts are not closed",
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(REPORT), "entries": len(matrix)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
