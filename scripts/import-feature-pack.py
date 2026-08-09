#!/usr/bin/env python3
# ruff: noqa: N999
"""Dry-run or apply a versioned Feature IR pack."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dnd_dm_assistant.application.feature_pack_importer import (
    FeaturePackImporter,
    FeaturePackImportError,
    load_feature_pack,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "data/feature-packs/compiled"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="compile without writing")
    mode.add_argument("--apply", action="store_true", help="write compiled pack")
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args()
    try:
        manifest = load_feature_pack(args.manifest)
        importer = FeaturePackImporter(target_dir=args.target_dir)
        result = (
            importer.apply(manifest)
            if args.apply
            else importer.dry_run(manifest)
        )
    except FeaturePackImportError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
