"""Round XXX receipt and typed advancement artificer spell-list contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "reports/tashas-feature-production-consumer-round-XXX-2026-08-13.json"
RESULTS = ROOT / "data/content-ir/compiled/production-runtime-results-XXXI.json"
FEATURE_ROOT = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"

CASES = {
    "battle-smith-spell-list": {
        "feature_id": "content.tashas-cauldron.round2.feature.battle-smith-spell-list",
        "subclass_name": "战地匠师",
        "spells": [
            "heroism",
            "shield",
            "branding_smite",
            "warding_bond",
            "aura_of_vitality",
            "conjure_barrage",
            "aura_of_purity",
            "fire_shield",
            "banishing_smite",
            "mass_cure_wounds",
        ],
    },
    "armorer-spell-list": {
        "feature_id": "content.tashas-cauldron.round2.feature.armorer-spell-list",
        "subclass_name": "装甲师",
        "spells": [
            "magic_missile",
            "thunderwave",
            "mirror_image",
            "shatter",
            "hypnotic_pattern",
            "lightning_bolt",
            "fire_shield",
            "greater_invisibility",
            "passwall",
            "wall_of_force",
        ],
    },
    "artillerist-spell-list": {
        "feature_id": "content.tashas-cauldron.round2.feature.artillerist-spell-list",
        "subclass_name": "魔炮师",
        "spells": [
            "shield",
            "thunderwave",
            "scorching_ray",
            "shatter",
            "fireball",
            "wind_wall",
            "ice_storm",
            "wall_of_fire",
            "cone_of_cold",
            "wall_of_force",
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


def test_round_xxx_receipt_is_complete() -> None:
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
        assert spec.class_name == "奇械师"
        assert spec.subclass_name == case["subclass_name"]
        advancement = runtime["advancement"]
        assert advancement["operator"] == "grant_spell"
        assert advancement["grant_class"] == "artificer"
        assert advancement["casting_ability"] == "intelligence"
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
