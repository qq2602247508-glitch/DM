"""Reloadable isolated Content Pack runtime registry.

This registry is intentionally separate from the formal production registry.
It validates a generated pack directory, re-parses every ItemSpec, rebuilds
the generic item projection and records the boundary as
``isolated_runtime_validated``.  It never mutates the formal registry,
database, campaign or character state.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dnd_dm_assistant.domain.content_ir_status import (
    build_status_layers,
    summarize_status_layers,
)
from dnd_dm_assistant.domain.item_spec import (
    ItemIRValidationError,
    ItemSpec,
    compile_item_spec,
    item_runtime_projection,
)

RUNTIME_REGISTRY_SCHEMA_VERSION = "content-pack-runtime-registry-1"


class ContentPackRuntimeRegistryError(ValueError):
    """Raised when an isolated pack cannot be safely reloaded."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentPackRuntimeRegistryError(f"invalid JSON: {path}") from exc
    if not isinstance(value, Mapping):
        raise ContentPackRuntimeRegistryError(f"expected object: {path}")
    return dict(value)


class ContentPackRuntimeRegistry:
    """Read-only registry for a generated isolated content-pack directory."""

    def __init__(self, pack_dir: Path) -> None:
        self.pack_dir = pack_dir
        self.manifest: dict[str, Any] = {}
        self.runtime_definitions: dict[str, Any] = {}
        self.entries: dict[str, dict[str, Any]] = {}
        self._loaded = False

    def reload(self) -> dict[str, Any]:
        manifest = _read_json(self.pack_dir / "manifest.json")
        if manifest.get("formal_apply") is not False:
            raise ContentPackRuntimeRegistryError(
                "isolated registry must not have formal_apply=true"
            )
        runtime = _read_json(self.pack_dir / str(manifest.get("runtime_definitions")))
        item_defs = runtime.get("item_definitions")
        if not isinstance(item_defs, list):
            raise ContentPackRuntimeRegistryError(
                "runtime-definitions.item_definitions must be an array"
            )
        self.manifest = manifest
        self.runtime_definitions = runtime
        self.entries = {}
        for index, definition in enumerate(item_defs):
            if not isinstance(definition, Mapping):
                raise ContentPackRuntimeRegistryError(
                    f"item_definitions[{index}] must be an object"
                )
            item_id = str(definition.get("item_id") or "").strip()
            if not item_id or item_id in self.entries:
                raise ContentPackRuntimeRegistryError(
                    f"duplicate or missing item_id at item_definitions[{index}]"
                )
            item_path = self.pack_dir / str(definition.get("typed_ir_path") or "")
            raw_spec = _read_json(item_path)
            try:
                spec = ItemSpec.from_dict(
                    {
                        key: value
                        for key, value in raw_spec.items()
                        if key in ItemSpec._FIELDS
                    },
                    path=str(item_path),
                )
            except ItemIRValidationError as exc:
                raise ContentPackRuntimeRegistryError(str(exc)) from exc
            if spec.item_id != item_id:
                raise ContentPackRuntimeRegistryError(
                    f"item id mismatch: {item_id} != {spec.item_id}"
                )
            if spec.pack_id != str(manifest.get("pack_id")):
                raise ContentPackRuntimeRegistryError(
                    f"item {item_id} belongs to {spec.pack_id}, not the pack"
                )
            if spec.pack_version != str(manifest.get("pack_version")):
                raise ContentPackRuntimeRegistryError(
                    f"item {item_id} has a different pack version"
                )
            compiled = compile_item_spec(spec)
            declared_status = str(definition.get("compile_status") or "")
            if declared_status != compiled["compile_status"]:
                raise ContentPackRuntimeRegistryError(
                    f"item {item_id} compile status drift: "
                    f"{declared_status!r} != {compiled['compile_status']!r}"
                )
            projection = item_runtime_projection(spec)
            declared_consumers = sorted(str(item) for item in definition.get("consumer_ids", []))
            if declared_consumers != sorted(projection["consumer_ids"]):
                raise ContentPackRuntimeRegistryError(
                    f"item {item_id} consumer projection drift"
                )
            compile_full = compiled["compile_status"] == "full"
            self.entries[item_id] = {
                "item_id": item_id,
                "item_kind": spec.item_kind,
                "source_fingerprint": spec.source_fingerprint,
                "item_fingerprint": spec.fingerprint(),
                "compile": compiled,
                "runtime_projection": projection,
                "status_layers": build_status_layers(
                    source_identified=True,
                    draft=True,
                    candidate=True,
                    reviewed=True,
                    authored_typed_ir=True,
                    compile_full=compile_full,
                    runtime_preview_full=compile_full,
                    isolated_runtime_validated=compile_full,
                    registered_production_full=False,
                ),
            }
        self._loaded = True
        return self.summary()

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.reload()

    def lookup(self, item_id: str) -> dict[str, Any] | None:
        self._ensure_loaded()
        entry = self.entries.get(str(item_id))
        return dict(entry) if entry is not None else None

    def summary(self) -> dict[str, Any]:
        self._ensure_loaded()
        rows = list(self.entries.values())
        layer_counts = summarize_status_layers(rows)
        return {
            "schema_version": RUNTIME_REGISTRY_SCHEMA_VERSION,
            "pack_id": self.manifest.get("pack_id"),
            "pack_version": self.manifest.get("pack_version"),
            "formal_apply": bool(self.manifest.get("formal_apply")),
            "entry_total": len(rows),
            "compile_full": sum(bool(row["status_layers"]["compile_full"]) for row in rows),
            "runtime_preview_full": sum(
                bool(row["status_layers"]["runtime_preview_full"]) for row in rows
            ),
            "isolated_runtime_validated": layer_counts["isolated_runtime_validated"],
            "registered_production_full": layer_counts["registered_production_full"],
            "dm_assisted": layer_counts["dm_assisted"],
            "game_usable": layer_counts["game_usable"],
            "blocked": sum(
                not bool(row["status_layers"]["isolated_runtime_validated"])
                for row in rows
            ),
            "status_layers": layer_counts,
            "entry_ids": sorted(self.entries),
            "isolated_runtime_validated_ids": sorted(
                item_id
                for item_id, row in self.entries.items()
                if row["status_layers"].get("isolated_runtime_validated")
            ),
            "registered_production_full_ids": [],
            "dm_assisted_ids": [],
        }
