"""Round XXXI receipt and typed advancement Spores circle-spells contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XXXI-2026-08-13.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXXII.json"
FEATURE_ROOT = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"

CASE = {
    "slug": "spores-druid-circle-spells",
    "feature_id": "content.tashas-cauldron.round2.feature.spores-druid-circle-spells",
    "subclass_name": "孢子结社",
    "known_cantrip": "chill_touch",
    "always_prepared": [
        "blindness_deafness",
        "gentle_repose",
        "animate_dead",
        "gaseous_form",
        "blight",
        "confusion",
        "cloudkill",
        "contagion",
    ],
}


def _contract() -> tuple[FeatureSpec, dict[str, object]]:
    path = FEATURE_ROOT / f"{CASE['slug']}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(path),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    assert compiled.compile_status == "full"
    return spec, materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)


def test_round_xxxi_receipt_is_complete() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    expected = [CASE["feature_id"]]
    assert report["selected_feature_ids"] == expected
    assert sorted(results["production_runtime_full_ids"]) == expected
    assert results["checks"]["production_runtime_full_count"] == 1
    assert results["checks"]["spores_grant_mode_split"] is True
    assert results["checks"]["name_branch_count"] == 0
    assert results["checks"]["formal_registry_written"] is False
    assert results["checks"]["formal_database_written"] is False
    assert results["checks"]["protected_fingerprints_unchanged"] is True
    assert all(
        item["typed_consumer"] == "advancement_service.character_growth.v1"
        and item["production_runtime_full"]
        and item["spell_grant_count"] == 9
        for item in results["evidence_by_id"].values()
    )


def test_spores_materializes_one_known_cantrip_and_eight_always_prepared_spells() -> None:
    spec, runtime = _contract()
    assert spec.source_completeness == "complete"
    assert spec.manual_decisions["unmodeled_source_terms"] == []
    assert spec.class_name == "德鲁伊"
    assert spec.subclass_name == CASE["subclass_name"]
    advancement = runtime["advancement"]
    assert advancement["operator"] == "grant_spell"
    assert advancement["grant_class"] == "druid"
    assert advancement["casting_ability"] == "wisdom"
    # Two differing clauses are merged into one envelope, so the top-level
    # grant_mode is intentionally dropped; each grant keeps its own mode.
    assert "grant_mode" not in advancement
    assert advancement["spells"] == [CASE["known_cantrip"], *CASE["always_prepared"]]
    assert advancement["runtime_execution"]["consumer"] == "advancement_service.spell_registry"
    grants = advancement["spell_grants"]
    assert len(grants) == 9
    grant_modes = [grant["grant_mode"] for grant in grants]
    assert grant_modes.count("known") == 1
    assert grant_modes.count("always_prepared") == 8
    known_grant = next(grant for grant in grants if grant["grant_mode"] == "known")
    assert known_grant["spells"] == [CASE["known_cantrip"]]
    prepared_spells = [
        grant["spells"][0] for grant in grants if grant["grant_mode"] == "always_prepared"
    ]
    assert prepared_spells == CASE["always_prepared"]


def test_spore_spells_are_distinct_and_complete() -> None:
    all_spells = [CASE["known_cantrip"], *CASE["always_prepared"]]
    assert len(all_spells) == 9
    assert len(set(all_spells)) == 9
