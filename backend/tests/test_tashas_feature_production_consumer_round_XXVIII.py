"""Round XXVIII receipt and typed advancement Domain Spells contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XXVIII-2026-08-13.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXIX.json"
FEATURE_ROOT = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"

CASES = {
    "order-cleric-domain-spells": {
        "feature_id": "content.tashas-cauldron.round2.feature.order-cleric-domain-spells",
        "spells": [
            "command",
            "heroism",
            "hold_person",
            "zone_of_truth",
            "mass_healing_word",
            "slow",
            "compulsion",
            "locate_creature",
            "commune",
            "dominate_person",
        ],
    },
    "peace-cleric-domain-spells": {
        "feature_id": "content.tashas-cauldron.round2.feature.peace-cleric-domain-spells",
        "spells": [
            "heroism",
            "sanctuary",
            "aid",
            "warding_bond",
            "beacon_of_hope",
            "sending",
            "aura_of_purity",
            "otilukes_resilient_sphere",
            "greater_restoration",
            "rarys_telepathic_bond",
        ],
    },
    "twilight-cleric-domain-spells": {
        "feature_id": "content.tashas-cauldron.round2.feature.twilight-cleric-domain-spells",
        "spells": [
            "faerie_fire",
            "sleep",
            "moonbeam",
            "see_invisibility",
            "aura_of_vitality",
            "leomunds_tiny_hut",
            "aura_of_life",
            "greater_invisibility",
            "circle_of_power",
            "mislead",
        ],
    },
}


def _contract(slug: str) -> tuple[FeatureSpec, dict[str, object]]:
    path = FEATURE_ROOT / f"{slug}.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    spec = FeatureSpec.from_dict(
        {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
        path=str(path),
    )
    compiler = FeatureCompiler(status_authority="compiler")
    compiled = compiler.compile(spec)
    assert compiled.compile_status == "full"
    return spec, materialize_runtime_definition(spec, compiled, catalog=compiler.catalog)


def test_round_xxviii_receipt_is_complete() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    expected = [case["feature_id"] for case in CASES.values()]
    assert report["selected_feature_ids"] == expected
    assert results["production_runtime_full_ids"] == expected
    assert report["checks"]["production_runtime_full_count"] == 3
    assert results["checks"]["production_runtime_full_count"] == 3
    assert results["checks"]["name_branch_count"] == 0
    assert results["checks"]["formal_registry_written"] is False
    assert results["checks"]["formal_database_written"] is False
    assert results["checks"]["protected_fingerprints_unchanged"] is True
    assert all(
        item["typed_consumer"] == "advancement_service.character_growth.v1"
        and item["production_runtime_full"]
        and item["spell_grant_count"] == 10
        for item in results["evidence_by_id"].values()
    )


def test_each_domain_spells_feature_materializes_ten_always_prepared_spells() -> None:
    for slug, case in CASES.items():
        spec, runtime = _contract(slug)
        assert spec.source_completeness == "complete"
        assert spec.manual_decisions["unmodeled_source_terms"] == []
        assert spec.class_name == "牧师"
        assert spec.level == 1
        advancement = runtime["advancement"]
        assert advancement["operator"] == "grant_spell"
        assert advancement["grant_class"] == "cleric"
        assert advancement["casting_ability"] == "wisdom"
        assert advancement["grant_mode"] == "always_prepared"
        assert advancement["spells"] == case["spells"]
        assert advancement["runtime_execution"]["consumer"] == "advancement_service.spell_registry"


def test_domain_spell_lists_are_distinct_and_complete() -> None:
    spell_sets = {slug: set(case["spells"]) for slug, case in CASES.items()}
    for slug, spells in spell_sets.items():
        assert len(spells) == 10, slug
        for other_slug, other in spell_sets.items():
            if other_slug != slug:
                assert spells != other
