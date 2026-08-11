from __future__ import annotations

import json
from pathlib import Path

from dnd_dm_assistant.application.feature_compiler import FeatureCompiler
from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackRegistry,
    load_feature_pack,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = (
    ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"
)
ISOLATED_ROOT = (
    ROOT
    / "data/content-ir/isolated-packs/tashas-cauldron-2026-08-12/feature-contract-batch-I"
)
CONTRACT_REPORT = ROOT / "reports/tashas-feature-contract-batch-I-2026-08-12.json"
RUNTIME_REPORT = ROOT / "reports/tashas-feature-contract-runtime-batch-I-2026-08-12.json"


def _specs() -> list[FeatureSpec]:
    values = []
    for path in sorted(ASSET_ROOT.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        values.append(
            FeatureSpec.from_dict(
                {key: value for key, value in raw.items() if key in FeatureSpec._FIELDS},
                path=str(path),
            )
        )
    return values


def test_round_II_feature_contract_batch_hits_explicit_gate() -> None:
    report = json.loads(CONTRACT_REPORT.read_text(encoding="utf-8"))
    assert report["reviewed_total"] == 64
    assert report["authored_typed_ir"] == 64
    assert report["compile_full"] >= 58
    assert report["compile_status_counts"]["full"] >= 58
    assert report["compile_status_counts"]["partial"] <= 6
    assert sum(report["compile_status_counts"].values()) == 64
    assert report["manual_boundary_total"] <= 5
    assert all(item["compile"]["compile_status"] != "invalid" for item in report["entries"])


def test_round_II_assets_keep_real_provenance_and_closed_compiler_status() -> None:
    specs = _specs()
    assert len(specs) == 64
    results = [FeatureCompiler(status_authority="compiler").compile(spec) for spec in specs]
    assert sum(item.compile_status == "full" for item in results) >= 58
    assert sum(item.compile_status == "partial" for item in results) <= 6
    assert sum(item.compile_status in {"full", "partial"} for item in results) == 64
    assert all(spec.source_book == "塔莎的万事坩埚" for spec in specs)
    assert all(spec.source_trust == "authored_ir" for spec in specs)
    assert all(spec.review_status == "reviewed" for spec in specs)
    assert all(spec.source_record_id and spec.source_fingerprint for spec in specs)


def test_round_II_isolated_registry_reload_and_character_growth_close() -> None:
    report = json.loads(RUNTIME_REPORT.read_text(encoding="utf-8"))
    assert report["formal_apply"] is False
    assert report["dry_run"]["counts"]["full"] >= 58
    assert report["dry_run"]["counts"]["partial"] <= 6
    assert report["dry_run"]["counts"].get("manual", 0) == 0
    assert report["dry_run"]["counts"].get("invalid", 0) == 0
    assert report["registry_lookup_full"] == report["dry_run"]["counts"]["full"]
    assert report["registry_partial_hidden"] == report["dry_run"]["counts"]["partial"]
    assert report["character_growth"]["closed_loop"] is True
    assert report["character_growth"]["feature_grants"] >= 58

    manifest = load_feature_pack(ISOLATED_ROOT / "manifest.json")
    registry = FeaturePackRegistry(ISOLATED_ROOT / "feature-runtime-registry")
    registry.reload()
    assert registry.lookup(
        "content.tashas-cauldron.round2.feature.rune-knight-bonus-proficiencies",
        pack_id="tashas-cauldron",
        pack_version="source-7011166c19bd",
    )
    assert len(manifest.features) == 64


def test_multiple_spell_grants_merge_without_losing_per_spell_metadata() -> None:
    payload_path = (
        ISOLATED_ROOT
        / "feature-runtime-registry/tashas-cauldron--source-7011166c19bd.json"
    )
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    feature_id = "content.tashas-cauldron.round2.feature.aberrant-mind-psionic-spell-list"
    runtime = payload["runtime_contracts"][feature_id]
    advancement = runtime["advancement"]
    assert len(advancement["spells"]) == 10
    assert len(advancement["spell_grants"]) == 10
