"""Apply, reload and exercise the isolated Round-II Tasha feature pack.

The pack is intentionally written below ``data/content-ir/isolated-packs``.
FeaturePackImporter materializes only full contracts, FeaturePackRegistry
exposes only those full contracts, and the final step feeds the materialized
contracts into the existing character feature-runtime compiler.  No formal
feature registry, database or campaign/character row is touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from dnd_dm_assistant.application.feature_compiler import FeatureCompiler
from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackImporter,
    FeaturePackManifest,
    FeaturePackRegistry,
)
from dnd_dm_assistant.application.tashas_whole_pack import build_migration
from dnd_dm_assistant.domain.feature_ir import FeatureSpec
from dnd_dm_assistant.domain.feature_runtime import (
    compile_feature_runtime_registry,
    feature_runtime_action_projections,
)

PACK_ID = "tashas-cauldron"
PACK_VERSION = "source-7011166c19bd"
SOURCE_BOOK = "塔莎的万事坩埚"
ISOLATED_ROOT = ROOT / "data/content-ir/isolated-packs/tashas-cauldron-2026-08-12/feature-contract-batch-I"
MANIFEST_PATH = ISOLATED_ROOT / "manifest.json"
REGISTRY_DIR = ISOLATED_ROOT / "feature-runtime-registry"
REPORT_PATH = ROOT / "reports/tashas-feature-contract-runtime-batch-I-2026-08-12.json"


def _load_specs() -> list[FeatureSpec]:
    specs: list[FeatureSpec] = []
    source_root = ROOT / "data/content-ir/authored/round-II/tashas-feature-contract-batch-I/features"
    for path in sorted(source_root.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        specs.append(
            FeatureSpec.from_dict(
                {key: item for key, item in value.items() if key in FeatureSpec._FIELDS},
                path=str(path),
            )
        )
    if len(specs) != 64:
        raise SystemExit(f"expected 64 Round-II feature specs, found {len(specs)}")
    return specs


def _manifest(specs: list[FeatureSpec]) -> FeaturePackManifest:
    value = {
        "schema_version": "feature-pack-1",
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "ruleset_version": "2014",
        "namespace": "content.tashas-cauldron",
        "display_name": "塔莎 Feature/Option 语义契约批次 I（隔离）",
        "source_metadata": {
            "kind": "source-reviewed-authored-ir",
            "date": "2026-08-12",
            "feature_source_fingerprints": {
                spec.feature_id: str(spec.source_fingerprint or "") for spec in specs
            },
            "natural_language_autocompile": False,
        },
        "source_trust": "authored_ir",
        "dependencies": [],
        "features": [spec.to_dict() for spec in specs],
        "compatibility": {
            "formal_apply": False,
            "formal_registry": False,
            "database": False,
            "campaign": False,
            "character": False,
            "isolated_consumer": "feature_runtime_registry",
        },
        "migration": {
            "formal_apply": False,
            "breaking_change": False,
            "promotion": "blocked_until_formal_review_and_consumer_parity",
        },
    }
    return FeaturePackManifest.from_dict(value, path=str(MANIFEST_PATH))


def _character_growth_snapshot(
    manifest: FeaturePackManifest,
    payload: dict[str, Any],
    compile_result: Any,
) -> dict[str, Any]:
    result_by_id = {
        item.feature_id: item
        for item in compile_result.feature_results
        if item.compile_status == "full"
    }
    grants: list[dict[str, Any]] = []
    for spec in manifest.features:
        result = result_by_id.get(spec.feature_id)
        runtime = payload.get("runtime_contracts", {}).get(spec.feature_id)
        if result is None or not isinstance(runtime, dict):
            continue
        grants.append(
            {
                "feature_id": spec.feature_id,
                "name": spec.source_name,
                "class_name": spec.class_name or "",
                "class_level": int(spec.level or 1),
                "kind": "feature",
                "source_record_id": spec.source_record_id,
                "source_path": spec.source_path,
                "runtime": {
                    "registry": runtime,
                    "automation_status": "full",
                },
            }
        )
    runtime_registry = compile_feature_runtime_registry(
        grants,
        resources={},
        total_level=max((int(item.get("class_level") or 1) for item in grants), default=1),
    )
    actions = feature_runtime_action_projections(runtime_registry)
    return {
        "character_id": "isolated-round-II-character",
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "feature_grants": len(grants),
        "runtime_feature_contracts": len(runtime_registry.get("feature_contracts", {})),
        "proficiencies": len(runtime_registry.get("proficiencies", [])),
        "movement_modes": len(runtime_registry.get("combat_start", {}).get("movement_modes", [])),
        "resource_keys": sorted(runtime_registry.get("resources", {})),
        "action_projection_count": len(actions),
        "runtime_registry_fingerprint": runtime_registry.get("fingerprint"),
        "closed_loop": (
            len(grants) == len(result_by_id)
            and len(runtime_registry.get("feature_contracts", {})) == len(grants)
        ),
    }


def main() -> int:
    specs = _load_specs()
    manifest = _manifest(specs)
    ISOLATED_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    compiler = FeatureCompiler(status_authority="compiler")
    importer = FeaturePackImporter(target_dir=REGISTRY_DIR, compiler=compiler)
    dry = importer.dry_run(manifest)
    first = importer.apply(manifest)
    second = importer.apply(manifest)
    registry = FeaturePackRegistry(REGISTRY_DIR)
    registry.reload()
    registry.pin_character("isolated-round-II-character", PACK_ID, PACK_VERSION)
    full_ids = sorted(
        item.feature_id
        for item in dry.feature_results
        if item.compile_status == "full"
    )
    lookup_ids = [
        item["feature_id"]
        for feature_id in full_ids
        if (item := registry.lookup(feature_id, pack_id=PACK_ID, pack_version=PACK_VERSION))
    ]
    payload_path = REGISTRY_DIR / f"{PACK_ID}--{PACK_VERSION}.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    character_growth = _character_growth_snapshot(manifest, payload, dry)
    migration = build_migration(ROOT)
    report = {
        "schema_version": "tashas-feature-contract-runtime-batch-I-1",
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "source_book": SOURCE_BOOK,
        "formal_apply": False,
        "isolated_runtime_only": True,
        "manifest_fingerprint": manifest.fingerprint(),
        "dry_run": dry.to_dict(),
        "first_apply": first.to_dict(),
        "second_apply": second.to_dict(),
        "idempotent_replay": second.idempotent_replay,
        "registry_lookup_full": len(lookup_ids),
        "registry_lookup_full_ids": lookup_ids,
        "registry_partial_hidden": sum(
            registry.lookup(item.feature_id, pack_id=PACK_ID, pack_version=PACK_VERSION) is None
            for item in dry.feature_results
            if item.compile_status != "full"
        ),
        "character_growth": character_growth,
        "tasha_migration_snapshot": {
            "authored_typed_ir": migration["authored_typed_ir"],
            "runtime_preview_full": migration["runtime_preview_full"],
            "registered_production_full": migration["production_full"],
            "game_usable": migration["game_usable"],
            "formal_registry_unchanged": True,
        },
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "dry_counts": dry.counts,
        "registry_lookup_full": len(lookup_ids),
        "character_growth": character_growth,
        "report": str(REPORT_PATH),
    }, ensure_ascii=False, sort_keys=True))
    if dry.counts != {"full": 58, "partial": 6, "manual": 0, "invalid": 0}:
        raise SystemExit(f"unexpected dry-run counts: {dry.counts}")
    if not (first.applied or first.idempotent_replay) or not second.idempotent_replay:
        raise SystemExit("isolated feature pack did not apply idempotently")
    if len(lookup_ids) != 58 or not character_growth["closed_loop"]:
        raise SystemExit("isolated feature runtime or character growth gate failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
