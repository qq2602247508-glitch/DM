"""Deterministic, idempotent Feature Pack importer.

The importer stores compiled definitions in a local registry directory.  It
does not mutate character snapshots and it never promotes unsupported rules to
``full``.  A future database-backed pack store can reuse the same manifest and
compile contracts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.feature_compiler import CompileResult, FeatureCompiler
from dnd_dm_assistant.domain.feature_ir import (
    FeatureIRValidationError,
    FeatureSpec,
    canonical_json,
)

FEATURE_PACK_SCHEMA_VERSION = "feature-pack-1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


class FeaturePackImportError(ValueError):
    """Raised when a pack cannot be safely parsed or applied."""


def _required(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FeaturePackImportError(f"{path} must be a non-empty string")
    return value.strip()


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FeaturePackImportError(f"{path} must be an object")
    return {str(key): value[key] for key in value}


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise FeaturePackImportError(f"{path} must be an array")
    return value


def _strict_keys(value: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise FeaturePackImportError(f"{path} contains unknown fields: {', '.join(unknown)}")


@dataclass(frozen=True)
class FeaturePackManifest:
    schema_version: str
    pack_id: str
    pack_version: str
    ruleset_version: str
    namespace: str
    display_name: str
    source_metadata: dict[str, Any]
    dependencies: tuple[str, ...]
    features: tuple[FeatureSpec, ...]
    compatibility: dict[str, Any]
    migration: dict[str, Any]

    _FIELDS = frozenset(
        {
            "schema_version",
            "pack_id",
            "pack_version",
            "ruleset_version",
            "namespace",
            "display_name",
            "source_metadata",
            "dependencies",
            "features",
            "compatibility",
            "migration",
        }
    )

    @classmethod
    def from_dict(cls, value: object, path: str = "pack") -> FeaturePackManifest:
        data = _mapping(value, path)
        _strict_keys(data, cls._FIELDS, path)
        schema_version = _required(data.get("schema_version"), f"{path}.schema_version")
        if schema_version != FEATURE_PACK_SCHEMA_VERSION:
            raise FeaturePackImportError(f"{path}.schema_version {schema_version!r} is unsupported")
        pack_id = _required(data.get("pack_id"), f"{path}.pack_id")
        namespace = _required(data.get("namespace"), f"{path}.namespace")
        for value_name, value_data in (("pack_id", pack_id), ("namespace", namespace)):
            if not _SAFE_ID.fullmatch(value_data):
                raise FeaturePackImportError(f"{path}.{value_name} contains unsafe characters")
        pack_version = _required(data.get("pack_version"), f"{path}.pack_version")
        ruleset_version = _required(data.get("ruleset_version"), f"{path}.ruleset_version")
        display_name = _required(data.get("display_name"), f"{path}.display_name")
        raw_dependencies = _list(data.get("dependencies", []), f"{path}.dependencies")
        dependencies = tuple(
            _required(item, f"{path}.dependencies[{index}]")
            for index, item in enumerate(raw_dependencies)
        )
        raw_features = _list(data.get("features"), f"{path}.features")
        if not raw_features:
            raise FeaturePackImportError(f"{path}.features must contain at least one feature")
        try:
            features = tuple(
                FeatureSpec.from_dict(item, f"{path}.features[{index}]")
                for index, item in enumerate(raw_features)
            )
        except FeatureIRValidationError as exc:
            raise FeaturePackImportError(str(exc)) from exc
        ids = [item.feature_id for item in features]
        if len(ids) != len(set(ids)):
            raise FeaturePackImportError(f"{path}.features contains duplicate feature_id")
        for feature in features:
            if feature.pack_id != pack_id or feature.namespace != namespace:
                raise FeaturePackImportError(
                    f"{path}.features[{feature.feature_id}] pack_id/namespace mismatch"
                )
            if feature.pack_version != pack_version:
                raise FeaturePackImportError(
                    f"{path}.features[{feature.feature_id}] pack_version mismatch"
                )
        return cls(
            schema_version=schema_version,
            pack_id=pack_id,
            pack_version=pack_version,
            ruleset_version=ruleset_version,
            namespace=namespace,
            display_name=display_name,
            source_metadata=_mapping(data.get("source_metadata", {}), f"{path}.source_metadata"),
            dependencies=dependencies,
            features=features,
            compatibility=_mapping(data.get("compatibility", {}), f"{path}.compatibility"),
            migration=_mapping(data.get("migration", {}), f"{path}.migration"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "ruleset_version": self.ruleset_version,
            "namespace": self.namespace,
            "display_name": self.display_name,
            "source_metadata": self.source_metadata,
            "dependencies": list(self.dependencies),
            "features": [item.to_dict() for item in self.features],
            "compatibility": self.compatibility,
            "migration": self.migration,
        }

    def fingerprint(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True)
class FeaturePackImportResult:
    pack_id: str
    pack_version: str
    mode: str
    applied: bool
    idempotent_replay: bool
    feature_results: tuple[CompileResult, ...]
    conflicts: tuple[str, ...]
    migration_plan: dict[str, Any]

    @property
    def counts(self) -> dict[str, int]:
        counts = {"full": 0, "partial": 0, "manual": 0, "invalid": 0}
        for result in self.feature_results:
            counts[result.compile_status] = counts.get(result.compile_status, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "mode": self.mode,
            "applied": self.applied,
            "idempotent_replay": self.idempotent_replay,
            "counts": self.counts,
            "feature_results": [item.to_dict() for item in self.feature_results],
            "conflicts": list(self.conflicts),
            "migration_plan": self.migration_plan,
        }


class FeaturePackImporter:
    """Compile, dry-run and persist versioned feature pack manifests."""

    def __init__(
        self,
        target_dir: Path | None = None,
        compiler: FeatureCompiler | None = None,
    ) -> None:
        self.target_dir = target_dir
        self.compiler = compiler or FeatureCompiler()

    def compile(self, manifest: FeaturePackManifest) -> tuple[CompileResult, ...]:
        available = {item.feature_id for item in manifest.features}
        compiler = FeatureCompiler(
            self.compiler.catalog,
            available_feature_ids=available,
            status_authority=self.compiler.status_authority,
        )
        return tuple(
            compiler.compile(
                feature,
                legacy_adapter_used=False,
            )
            for feature in sorted(manifest.features, key=lambda item: item.feature_id)
        )

    def dry_run(self, manifest: FeaturePackManifest) -> FeaturePackImportResult:
        results = self.compile(manifest)
        conflicts, migration_plan = self._compare_existing(manifest)
        return FeaturePackImportResult(
            pack_id=manifest.pack_id,
            pack_version=manifest.pack_version,
            mode="dry-run",
            applied=False,
            idempotent_replay=False,
            feature_results=results,
            conflicts=conflicts,
            migration_plan=migration_plan,
        )

    def apply(self, manifest: FeaturePackManifest) -> FeaturePackImportResult:
        if self.target_dir is None:
            raise FeaturePackImportError("apply requires a target_dir")
        result = self.dry_run(manifest)
        if any(item.compile_status == "invalid" for item in result.feature_results):
            raise FeaturePackImportError("invalid feature cannot be applied")
        if result.conflicts:
            raise FeaturePackImportError("; ".join(result.conflicts))
        target = self.target_dir
        target.mkdir(parents=True, exist_ok=True)
        path = self._manifest_path(manifest.pack_id, manifest.pack_version)
        payload = {
            "manifest": manifest.to_dict(),
            "compile": result.to_dict(),
            "fingerprint": manifest.fingerprint(),
        }
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if path.exists():
            try:
                existing_payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise FeaturePackImportError(
                    f"pack/version file is invalid: {path.name}"
                ) from exc
            if existing_payload.get("fingerprint") != manifest.fingerprint():
                raise FeaturePackImportError(
                    f"pack/version already exists with a different fingerprint: {path.name}"
                )
            return FeaturePackImportResult(
                **{
                    **result.__dict__,
                    "mode": "apply",
                    "applied": False,
                    "idempotent_replay": True,
                }
            )
        path.write_text(serialized, encoding="utf-8")
        self._write_index(manifest, path)
        return FeaturePackImportResult(
            **{
                **result.__dict__,
                "mode": "apply",
                "applied": True,
                "idempotent_replay": False,
            }
        )

    def _manifest_path(self, pack_id: str, pack_version: str) -> Path:
        if self.target_dir is None:
            raise FeaturePackImportError("target_dir is required")
        safe_version = re.sub(r"[^A-Za-z0-9_.-]+", "_", pack_version)
        return self.target_dir / f"{pack_id}--{safe_version}.json"

    def _index_path(self) -> Path:
        if self.target_dir is None:
            raise FeaturePackImportError("target_dir is required")
        return self.target_dir / "index.json"

    def _write_index(self, manifest: FeaturePackManifest, path: Path) -> None:
        index_path = self._index_path()
        current: dict[str, Any] = {}
        if index_path.exists():
            try:
                current = json.loads(index_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise FeaturePackImportError("feature pack index is invalid") from exc
        packs = current.get("packs")
        if not isinstance(packs, dict):
            packs = {}
        packs[manifest.pack_id] = {
            "pack_version": manifest.pack_version,
            "path": path.name,
            "fingerprint": manifest.fingerprint(),
        }
        index_path.write_text(
            json.dumps({"packs": packs}, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def _compare_existing(
        self,
        manifest: FeaturePackManifest,
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        if self.target_dir is None:
            return (), {"kind": "new_pack", "changed_features": []}
        path = self._manifest_path(manifest.pack_id, manifest.pack_version)
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return (f"existing pack file is invalid: {path.name}",), {}
            if existing.get("fingerprint") == manifest.fingerprint():
                return (), {"kind": "idempotent_replay", "changed_features": []}
            return (
                f"pack/version conflict: {manifest.pack_id}@{manifest.pack_version}",
            ), {}
        index_path = self._index_path()
        if not index_path.exists():
            return (), {"kind": "new_pack", "changed_features": []}
        try:
            index = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return ("feature pack index is invalid",), {}
        prior = index.get("packs", {}).get(manifest.pack_id)
        if not isinstance(prior, Mapping):
            return (), {"kind": "new_pack", "changed_features": []}
        return (), {
            "kind": "version_update",
            "previous_version": prior.get("pack_version"),
            "changed_features": [],
            "breaking_change": bool(manifest.migration.get("breaking_change", False)),
        }


def load_feature_pack(path: Path) -> FeaturePackManifest:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeaturePackImportError(f"cannot read feature pack: {path}") from exc
    return FeaturePackManifest.from_dict(value, path=str(path))
