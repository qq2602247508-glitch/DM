from __future__ import annotations

import json
import shutil
from pathlib import Path

from dnd_dm_assistant.application.content_ir_workbench import (
    COMPILER_FINGERPRINT,
    SpellSpec,
    compile_artifact_directory,
    compile_spell_spec,
    dry_run_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
AUTHORED = ROOT / "data/content-ir/authored"


def _manifest_dirs() -> list[Path]:
    return sorted(AUTHORED.glob("**/manifest.json"))


def _leaf_manifest_dirs() -> list[Path]:
    return [
        path
        for path in _manifest_dirs()
        if path.parent.name in {"spells", "features"}
    ]


def _typed_paths(manifest_path: Path) -> list[Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [manifest_path.parent / item for item in manifest["typed_ir_paths"]]


def test_real_authored_batch_has_thirty_typed_ir_and_thirty_full() -> None:
    manifests = _leaf_manifest_dirs()
    assert len(manifests) == 6
    results = [
        compile_artifact_directory(path.parent, write_files=False)
        for path in manifests
    ]
    assert sum(result["typed_ir_count"] for result in results) == 30
    assert sum(result["counts"]["full"] for result in results) == 30
    assert all(result["counts"]["partial"] == 0 for result in results)
    assert all(result["counts"]["manual"] == 0 for result in results)
    assert all(result["counts"]["invalid"] == 0 for result in results)


def test_real_authored_assets_keep_review_provenance() -> None:
    required = {
        "source_record_id",
        "source_path",
        "source_book",
        "source_fingerprint",
        "review_status",
        "reviewed_by",
        "reviewed_fields",
        "source_evidence",
        "clause_boundaries",
        "manual_decisions",
    }
    assets = [path for manifest in _leaf_manifest_dirs() for path in _typed_paths(manifest)]
    assert len(assets) == 30
    for path in assets:
        value = json.loads(path.read_text(encoding="utf-8"))
        assert required <= value.keys()
        assert value["review_status"] == "reviewed"
        assert value["source_trust"] == "authored_ir"
        assert value["compiler_fingerprint"] == COMPILER_FINGERPRINT


def test_core_spell_runtime_preview_is_standard_and_name_agnostic() -> None:
    manifest = AUTHORED / "core-2024/spells/manifest.json"
    result = compile_artifact_directory(manifest.parent, write_files=False)
    fireball = next(
        item for item in result["results"] if item["spell_id"].endswith("3a56665b98f37eed02921de6")
    )
    runtime = fireball["runtime_spell_definition"]
    assert runtime["runtime_schema_version"] == "spell-runtime-1"
    assert runtime["resolution"]["saving_throw"][0]["save_ability"] == "dexterity"
    assert runtime["resolution"]["effects"]
    assert runtime["source"]["source_trust"] == "authored_ir"


def test_expansion_feature_runtime_preview_is_materialized() -> None:
    manifest = AUTHORED / "official-packs/tashas-cauldron/features/manifest.json"
    result = compile_artifact_directory(manifest.parent, write_files=False)
    assert result["counts"]["full"] == 8
    ambush = next(
        item
        for item in result["results"]
        if item["feature_id"].endswith("battle-master.ambush")
    )
    assert ambush["runtime_definition"]["actions"] is not None
    assert ambush["materialized"] is True


def test_mixed_typed_feature_and_spell_pack_compiles(tmp_path: Path) -> None:
    spell_manifest = AUTHORED / "official-packs/tashas-cauldron/spells/manifest.json"
    feature_manifest = AUTHORED / "official-packs/tashas-cauldron/features/manifest.json"
    spell_value = json.loads(_typed_paths(spell_manifest)[0].read_text(encoding="utf-8"))
    feature_value = json.loads(_typed_paths(feature_manifest)[0].read_text(encoding="utf-8"))
    common_version = "mixed-test-v1"
    spell_value["pack_version"] = common_version
    feature_value["pack_version"] = common_version
    (tmp_path / "spells").mkdir()
    (tmp_path / "features").mkdir()
    (tmp_path / "spells/spell.json").write_text(
        json.dumps(spell_value, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "features/feature.json").write_text(
        json.dumps(feature_value, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {
        "schema_version": "content-ir-workbench-manifest-3",
        "pack_id": "tashas-cauldron",
        "pack_version": common_version,
        "source_book": "塔莎的万事坩埚",
        "namespace": "content.tashas-cauldron",
        "ruleset_version": "2014",
        "source_fingerprints": {
            spell_value["source_record_id"]: spell_value["source_fingerprint"],
            feature_value["source_record_id"]: feature_value["source_fingerprint"],
        },
        "draft_paths": [],
        "typed_ir_paths": ["spells/spell.json", "features/feature.json"],
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry_version": "content-capabilities-1",
        "production_targets": {
            "database": False,
            "feature_registry": False,
            "spell_registry": False,
            "campaign": False,
            "character": False,
        },
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    result = compile_artifact_directory(tmp_path, write_files=False)
    assert result["typed_ir_count"] == 2
    assert result["counts"]["full"] == 2
    assert {item["kind"] for item in result["results"]} == {"spell", "feature"}


def test_direct_typed_source_fingerprint_conflict_is_rejected(tmp_path: Path) -> None:
    source = AUTHORED / "core-2024/spells"
    shutil.copytree(source, tmp_path / "pack")
    typed = next((tmp_path / "pack").glob("spells/*.json"))
    value = json.loads(typed.read_text(encoding="utf-8"))
    value["source_fingerprint"] = "changed-by-test"
    typed.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    result = dry_run_manifest(
        tmp_path / "pack/manifest.json", tmp_path / "isolated"
    )
    assert result["status"] == "conflict"
    assert result["rolled_back"] is True
    assert not (tmp_path / "isolated").exists()


def test_authored_spell_unknown_clause_and_missing_parameter_fail_closed() -> None:
    unknown = SpellSpec.from_dict(
        {
            "schema_version": "spell-ir-1",
            "spell_id": "test:unknown",
            "name": "unknown",
            "level": 1,
            "clauses": [{"type": "rewrite_reality"}],
        }
    )
    assert compile_spell_spec(unknown)["compile_status"] == "invalid"
    missing = SpellSpec.from_dict(
        {
            "schema_version": "spell-ir-1",
            "spell_id": "test:missing",
            "name": "missing",
            "level": 1,
            "review_status": "reviewed",
            "source_record_id": "source",
            "source_path": "source",
            "source_book": "book",
            "source_fingerprint": "fp",
            "reviewed_by": "test",
            "reviewed_fields": ["clauses"],
            "source_evidence": {"source_text": "text"},
            "clause_boundaries": {"damage": {}},
            "manual_decisions": {},
            "clauses": [{"type": "damage", "expression": "1d6"}],
        }
    )
    assert compile_spell_spec(missing)["compile_status"] == "partial"
