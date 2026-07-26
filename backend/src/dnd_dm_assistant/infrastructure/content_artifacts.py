from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dnd_dm_assistant.domain.content import NormalizedEntity, QualityReport, SourceProvenance


def stable_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        + "\n"
    ).encode("utf-8")


def entity_json_bytes(entity: NormalizedEntity) -> bytes:
    return stable_json_bytes(entity.model_dump(mode="json"))


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        for name in ("raw", "markdown", "json", "manifests", "reports"):
            (root / name).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() == content:
            return False
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    def write_raw(self, canonical_url: str, body: bytes) -> Path:
        key = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:24]
        path = self.root / "raw" / f"{key}.html"
        self._atomic_write(path, body)
        return path

    def write_entity(self, entity: NormalizedEntity) -> tuple[Path, bool, bool]:
        type_dir = entity.content_type.value
        json_path = self.root / "json" / type_dir / f"{entity.stable_id}.json"
        markdown_path = self.root / "markdown" / type_dir / f"{entity.stable_id}.md"
        checksum_changed = False
        if json_path.exists():
            try:
                previous = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                checksum_changed = True
            else:
                checksum_changed = previous.get("checksum") != entity.checksum
        json_changed = self._atomic_write(json_path, entity_json_bytes(entity))
        self._atomic_write(markdown_path, entity.content_markdown.encode("utf-8"))
        return json_path, json_changed, checksum_changed

    def write_report(self, report: QualityReport) -> Path:
        path = self.root / "reports" / f"{report.run_id}.json"
        self._atomic_write(path, stable_json_bytes(report.model_dump(mode="json")))
        return path

    def write_manifest(
        self,
        *,
        run_id: str,
        source: str,
        robots_status: str,
        record_ids: tuple[str, ...],
        provenance: SourceProvenance,
    ) -> Path:
        path = self.root / "manifests" / f"{run_id}.json"
        manifest = {
            "completed_at": datetime.now(UTC).isoformat(),
            "record_ids": list(record_ids),
            "robots_status": robots_status,
            "run_id": run_id,
            "source": source,
            "provenance": provenance.model_dump(mode="json"),
        }
        self._atomic_write(path, stable_json_bytes(manifest))
        return path

    def validate(self) -> tuple[int, tuple[str, ...]]:
        errors: list[str] = []
        count = 0
        for path in sorted((self.root / "json").glob("*/*.json")):
            count += 1
            try:
                entity = NormalizedEntity.model_validate_json(path.read_bytes())
            except Exception as exc:
                errors.append(f"{path}: {exc}")
                continue
            markdown_path = (
                self.root / "markdown" / entity.content_type.value / f"{entity.stable_id}.md"
            )
            if not markdown_path.exists():
                errors.append(f"{path}: missing Markdown artifact")
            elif hashlib.sha256(markdown_path.read_bytes()).hexdigest() != entity.checksum:
                errors.append(f"{path}: Markdown checksum mismatch")
        return count, tuple(errors)

    def size_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
