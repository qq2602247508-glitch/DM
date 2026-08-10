#!/usr/bin/env python3
# ruff: noqa: N999, EXE001
"""Build the checked-in expansion-pack Feature IR fixture."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

from dnd_dm_assistant.application.feature_pack_importer import FeaturePackManifest
from dnd_dm_assistant.application.harvest_feature_specs import harvest_feature_specs

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/feature-packs/expansion-pack-fixture-2026-08-10"
PACK_ID = "dnd-expansion-proof-2026"
PACK_VERSION = "1.0.0"
NAMESPACE = "dnd.expansion.proof"


def build() -> dict[str, object]:
    features = []
    source_fingerprints: dict[str, str] = {}
    for index, source in enumerate(
        sorted(harvest_feature_specs(), key=lambda item: item.feature_id),
        start=1,
    ):
        feature_id = f"expansion2026.feature.{index:02d}"
        source_name = f"扩展规则样例 {index:02d}"
        source_record_id = f"expansion-source-{index:02d}"
        feature = replace(
            source,
            feature_id=feature_id,
            namespace=NAMESPACE,
            pack_id=PACK_ID,
            pack_version=PACK_VERSION,
            source_record_id=source_record_id,
            source_name=source_name,
            localized_names={"zh-CN": source_name, "contract_origin": source.feature_id},
            class_name="扩展包职业",
            subclass_name="扩展包子职业",
            compatibility={
                **source.compatibility,
                "contract_origin": source.feature_id,
                "core_code_change_required": False,
            },
        )
        features.append(feature.to_dict())
        source_fingerprints[feature_id] = hashlib.sha256(
            (
                f"{source_record_id}|{source.feature_id}|"
                f"{source.fingerprint()}"
            ).encode()
        ).hexdigest()
    manifest = {
        "schema_version": "feature-pack-1",
        "pack_id": PACK_ID,
        "pack_version": PACK_VERSION,
        "ruleset_version": "2024",
        "namespace": NAMESPACE,
        "display_name": "扩展包 Feature IR 自动导入验证",
        "source_metadata": {
            "kind": "source-reviewed-authored-ir-fixture",
            "date": "2026-08-10",
            "feature_source_fingerprints": source_fingerprints,
            "natural_language_autocompile": False,
        },
        "source_trust": "authored_ir",
        "dependencies": [],
        "features": features,
        "compatibility": {
            "minimum_feature_ir_schema": "feature-ir-1",
            "requires_feature_name_branch": False,
            "portable_contracts": True,
        },
        "migration": {
            "breaking_change": False,
            "rollback": "remove pack version and restore registry index",
        },
    }
    FeaturePackManifest.from_dict(manifest, path="expansion_fixture")
    return manifest


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = build()
    serialized = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (OUTPUT / "manifest.json").write_text(serialized, encoding="utf-8")
    (OUTPUT / "features.json").write_text(
        json.dumps(manifest["features"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "source-metadata.json").write_text(
        json.dumps(manifest["source_metadata"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "pack_id": manifest["pack_id"],
                "pack_version": manifest["pack_version"],
                "feature_count": len(manifest["features"]),
                "output": str(OUTPUT),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
