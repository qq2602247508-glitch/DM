from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_dm_assistant.application.content_ir_production_registry import (
    resolve_production_consumers,
)

ROOT = Path(__file__).resolve().parents[2]


def test_production_registry_is_closed_and_name_independent() -> None:
    blocks = {
        "effects": [{"type": "damage", "expression": "1d6", "damage_type": "fire"}],
        "target_selection": [{"type": "target_selection", "kind": "one_creature"}],
    }
    first = resolve_production_consumers(
        content_kind="spell", runtime_schema_version="spell-runtime-1", blocks=blocks
    )
    renamed = resolve_production_consumers(
        content_kind="spell", runtime_schema_version="spell-runtime-1", blocks=blocks
    )
    assert [item["consumer_id"] for item in first] == ["combat_engine.damage_heal.v1"]
    assert first == renamed
    with pytest.raises(ValueError, match="unknown spell runtime sections"):
        resolve_production_consumers(
            content_kind="spell",
            runtime_schema_version="spell-runtime-1",
            blocks={**blocks, "unknown_clause": [{}]},
        )
    with pytest.raises(ValueError, match="unsupported Content IR spell runtime schema"):
        resolve_production_consumers(
            content_kind="spell", runtime_schema_version="spell-runtime-999", blocks=blocks
        )


def test_closeout_reports_keep_compile_preview_production_layers_separate() -> None:
    audit = json.loads(
        (ROOT / "reports/content-ir-runtime-level-audit-II-2026-08-11.json").read_text()
    )
    validation = json.loads(
        (ROOT / "reports/content-ir-production-runtime-validation-II-2026-08-11.json").read_text()
    )
    assert audit["layers"]["compile_full"] == 113
    assert audit["layers"]["runtime_preview_full"] == 113
    assert audit["layers"]["production_runtime_full"] == 51
    assert validation["all_required_checks_passed"] is True
    assert validation["new_spell_production_runtime_full_count"] >= 25
    assert validation["new_feature_production_runtime_full_count"] >= 5


def test_cross_pack_production_proof_meets_closeout_thresholds() -> None:
    proof = json.loads(
        (ROOT / "reports/content-ir-cross-pack-production-proof-2026-08-11.json").read_text()
    )
    after = proof["after"]
    assert after["fizbans-treasury"] >= 2
    assert after["book-of-many-things"] >= 1
    assert after["xanathars-guide"] >= 7
    assert after["tashas-cauldron"] >= 3
    assert proof["tashas_feature_after"] >= 10
