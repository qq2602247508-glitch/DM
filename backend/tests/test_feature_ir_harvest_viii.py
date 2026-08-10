from __future__ import annotations

import json
from pathlib import Path

import pytest

from dnd_dm_assistant.application.feature_compiler import (
    FeatureCompiler,
    materialize_runtime_definition,
)
from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackImporter,
    FeaturePackImportError,
    FeaturePackRegistry,
    load_feature_pack,
)
from dnd_dm_assistant.application.harvest_feature_specs import harvest_feature_specs

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data/feature-packs/expansion-pack-fixture-2026-08-10/manifest.json"


def test_harvest_viii_has_eight_direct_authored_full_specs() -> None:
    compiler = FeatureCompiler(status_authority="compiler")
    specs = harvest_feature_specs()

    assert len(specs) == 8
    assert {item.source_trust for item in specs} == {"authored_ir"}
    results = [compiler.compile(item) for item in specs]
    assert all(item.compile_status == "full" for item in results)
    assert all(
        materialize_runtime_definition(spec, result, catalog=compiler.catalog)
        for spec, result in zip(specs, results, strict=True)
    )


def test_expansion_pack_compiles_applies_reloads_and_is_idempotent(tmp_path: Path) -> None:
    manifest = load_feature_pack(PACK)
    importer = FeaturePackImporter(target_dir=tmp_path)

    dry = importer.dry_run(manifest)
    first = importer.apply(manifest)
    second = importer.apply(manifest)

    assert dry.counts == {"full": 8, "partial": 0, "manual": 0, "invalid": 0}
    assert first.applied is True
    assert second.idempotent_replay is True

    registry = FeaturePackRegistry(tmp_path)
    registry.reload()
    assert all(registry.lookup(item.feature_id) for item in manifest.features)


def test_expansion_pack_fingerprint_conflict_and_duplicate_feature_fail_closed(
    tmp_path: Path,
) -> None:
    manifest = load_feature_pack(PACK)
    importer = FeaturePackImporter(target_dir=tmp_path)
    importer.apply(manifest)

    changed = json.loads(PACK.read_text(encoding="utf-8"))
    changed["features"][0]["source_name"] = "冲突"
    changed_manifest = type(manifest).from_dict(changed)
    with pytest.raises(FeaturePackImportError, match="pack/version conflict"):
        importer.apply(changed_manifest)

    other = json.loads(PACK.read_text(encoding="utf-8"))
    other["pack_id"] = "other-expansion-pack"
    other["namespace"] = "dnd.expansion.other"
    for feature in other["features"]:
        feature["pack_id"] = other["pack_id"]
        feature["namespace"] = other["namespace"]
    other_manifest = type(manifest).from_dict(other)
    with pytest.raises(FeaturePackImportError, match="already registered"):
        importer.apply(other_manifest)


def test_expansion_pack_apply_rolls_back_when_index_write_fails(tmp_path: Path) -> None:
    manifest = load_feature_pack(PACK)

    class FailingImporter(FeaturePackImporter):
        def _write_index(self, *args: object, **kwargs: object) -> None:
            raise OSError("intentional test failure")

    with pytest.raises(FeaturePackImportError, match="rolled back"):
        FailingImporter(target_dir=tmp_path).apply(manifest)
    assert list(tmp_path.iterdir()) == []
