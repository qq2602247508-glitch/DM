"""Round XXIX receipt and typed advancement always-prepared spell-list contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XXIX-2026-08-13.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXX.json"
FEATURE_ROOT = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"

CASES = {
    "wildfire-druid-circle-spells": {
        "feature_id": "content.tashas-cauldron.round2.feature.wildfire-druid-circle-spells",
        "class_name": "德鲁伊",
        "grant_class": "druid",
        "casting_ability": "wisdom",
        "spells": [
            "burning_hands",
            "cure_wounds",
            "flaming_sphere",
            "scorching_ray",
            "plant_growth",
            "revivify",
            "aura_of_life",
            "fire_shield",
            "flame_strike",
            "mass_cure_wounds",
        ],
    },
    "watchers-paladin-oath-spells": {
        "feature_id": "content.tashas-cauldron.round2.feature.watchers-paladin-oath-spells",
        "class_name": "圣武士",
        "grant_class": "paladin",
        "casting_ability": "charisma",
        "spells": [
            "alarm",
            "detect_magic",
            "moonbeam",
            "see_invisibility",
            "counterspell",
            "nondetection",
            "aura_of_purity",
            "banishment",
            "hold_monster",
            "scrying",
        ],
    },
    "glory-paladin-oath-spells": {
        "feature_id": "content.tashas-cauldron.round2.feature.glory-paladin-oath-spells",
        "class_name": "圣武士",
        "grant_class": "paladin",
        "casting_ability": "charisma",
        "spells": [
            "guiding_bolt",
            "heroism",
            "enhance_ability",
            "magic_weapon",
            "haste",
            "protection_from_energy",
            "compulsion",
            "freedom_of_movement",
            "commune",
            "flame_strike",
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


def test_round_xxix_receipt_is_complete() -> None:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    expected = [case["feature_id"] for case in CASES.values()]
    assert report["selected_feature_ids"] == expected
    assert sorted(results["production_runtime_full_ids"]) == sorted(expected)
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


def test_each_spell_list_feature_materializes_ten_always_prepared_spells() -> None:
    for slug, case in CASES.items():
        spec, runtime = _contract(slug)
        assert spec.source_completeness == "complete"
        assert spec.manual_decisions["unmodeled_source_terms"] == []
        assert spec.class_name == case["class_name"]
        advancement = runtime["advancement"]
        assert advancement["operator"] == "grant_spell"
        assert advancement["grant_class"] == case["grant_class"]
        assert advancement["casting_ability"] == case["casting_ability"]
        assert advancement["grant_mode"] == "always_prepared"
        assert advancement["spells"] == case["spells"]
        assert advancement["runtime_execution"]["consumer"] == "advancement_service.spell_registry"


def test_spell_lists_are_distinct_and_complete() -> None:
    spell_sets = {slug: set(case["spells"]) for slug, case in CASES.items()}
    for slug, spells in spell_sets.items():
        assert len(spells) == 10, slug
        for other_slug, other in spell_sets.items():
            if other_slug != slug:
                assert spells != other
