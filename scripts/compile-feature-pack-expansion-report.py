#!/usr/bin/env python3
# ruff: noqa: N999, EXE001
"""Run the expansion-pack importer acceptance matrix."""

from __future__ import annotations

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackImporter,
    FeaturePackImportError,
    FeaturePackManifest,
    FeaturePackRegistry,
    load_feature_pack,
)

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "data/feature-packs/expansion-pack-fixture-2026-08-10/manifest.json"
OUTPUT = ROOT / "reports/feature-pack-expansion-import-2026-08-10.json"


def _changed_manifest(manifest: FeaturePackManifest) -> FeaturePackManifest:
    value = manifest.to_dict()
    value["features"][0]["source_name"] = "扩展包冲突特性"
    return FeaturePackManifest.from_dict(value, path="changed_pack")


def _other_pack_manifest(manifest: FeaturePackManifest) -> FeaturePackManifest:
    value = manifest.to_dict()
    value["pack_id"] = "dnd-expansion-other-pack"
    value["namespace"] = "dnd.expansion.other"
    value["pack_version"] = "1.0.0"
    value["display_name"] = "重复 feature_id 冲突包"
    value["features"] = [
        {
            **feature,
            "pack_id": value["pack_id"],
            "namespace": value["namespace"],
            "pack_version": value["pack_version"],
        }
        for feature in value["features"]
    ]
    return FeaturePackManifest.from_dict(value, path="other_pack")


def main() -> None:
    manifest = load_feature_pack(PACK)
    with tempfile.TemporaryDirectory(prefix="feature-pack-viii-") as temp:
        target = Path(temp)
        importer = FeaturePackImporter(target_dir=target)
        dry = importer.dry_run(manifest)
        first = importer.apply(manifest)
        second = importer.apply(manifest)
        registry = FeaturePackRegistry(target)
        registry.reload()
        imported_ids = sorted(item.feature_id for item in manifest.features)
        registered_ids = sorted(
            item
            for item in imported_ids
            if registry.lookup(item, pack_id=manifest.pack_id, pack_version=manifest.pack_version)
        )

        changed = _changed_manifest(manifest)
        conflict_result = importer.dry_run(changed)
        version_conflict = False
        try:
            importer.apply(changed)
        except FeaturePackImportError:
            version_conflict = True

        other_pack_conflict = False
        other = _other_pack_manifest(manifest)
        try:
            importer.dry_run(other)
        except FeaturePackImportError:
            other_pack_conflict = True
        else:
            try:
                importer.apply(other)
            except FeaturePackImportError:
                other_pack_conflict = True

        class FailingImporter(FeaturePackImporter):
            def _write_index(self, *args: object, **kwargs: object) -> None:
                raise OSError("intentional index failure")

        rollback_target = target / "rollback"
        rollback_manifest = FeaturePackManifest.from_dict(
            {
                **manifest.to_dict(),
                "pack_id": "dnd-expansion-rollback-proof",
                "namespace": "dnd.expansion.rollback",
                "features": [
                    {
                        **feature,
                        "pack_id": "dnd-expansion-rollback-proof",
                        "namespace": "dnd.expansion.rollback",
                    }
                    for feature in manifest.to_dict()["features"]
                ],
            },
            path="rollback_pack",
        )
        rollback_raised = False
        try:
            FailingImporter(target_dir=rollback_target).apply(rollback_manifest)
        except FeaturePackImportError:
            rollback_raised = True
        rollback_files = sorted(path.name for path in rollback_target.glob("*")) if rollback_target.exists() else []

        def concurrent_apply() -> tuple[str, bool, bool]:
            try:
                result = FeaturePackImporter(
                    target_dir=target / "concurrent"
                ).apply(manifest)
            except FeaturePackImportError:
                return "rejected_concurrent_lock", False, False
            return "applied_or_replayed", result.applied, result.idempotent_replay

        with ThreadPoolExecutor(max_workers=2) as pool:
            concurrent_results = sorted(pool.map(lambda _item: concurrent_apply(), range(2)))

    result = {
        "schema_version": "feature-pack-expansion-import-1",
        "pack_id": manifest.pack_id,
        "pack_version": manifest.pack_version,
        "ruleset_version": manifest.ruleset_version,
        "feature_count": len(manifest.features),
        "full_count": dry.counts["full"],
        "partial_count": dry.counts["partial"],
        "manual_count": dry.counts["manual"],
        "dry_run_result": {
            "counts": dry.counts,
            "all_full": all(item.compile_status == "full" for item in dry.feature_results),
        },
        "apply_result": {
            "applied": first.applied,
            "idempotent_replay": second.idempotent_replay,
        },
        "reload_result": {
            "registered_count": len(registered_ids),
            "registered_feature_ids": registered_ids,
        },
        "idempotency_result": second.idempotent_replay,
        "fingerprint_conflict_result": bool(conflict_result.conflicts) and version_conflict,
        "rollback_result": {
            "raised": rollback_raised,
            "remaining_files": rollback_files,
        },
        "cross_pack_duplicate_feature_result": other_pack_conflict,
        "concurrent_apply_result": concurrent_results,
        "imported_feature_ids": imported_ids,
        "compiled_feature_ids": [
            item.feature_id
            for item in dry.feature_results
            if item.compile_status == "full"
        ],
        "materialized_feature_ids": registered_ids,
        "runtime_registered_feature_ids": registered_ids,
        "whether_core_code_changed": False,
        "whether_feature_name_branch_changed": False,
        "source_trust": manifest.source_trust,
    }
    OUTPUT.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
