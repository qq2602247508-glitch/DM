from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from dnd_dm_assistant.domain.content import NormalizedEntity
from dnd_dm_assistant.domain.rag import IndexManifest
from dnd_dm_assistant.infrastructure.content_artifacts import stable_json_bytes


class JsonCorpusReader:
    def iter_records(
        self, root: Path
    ) -> Iterable[tuple[Path, NormalizedEntity | None, str | None]]:
        for path in sorted(root.glob("*/*.json")):
            try:
                entity = NormalizedEntity.model_validate_json(path.read_bytes())
            except Exception as exc:
                yield path, None, f"schema validation failed: {exc}"
                continue
            if path.stem != entity.stable_id:
                yield path, None, "filename does not match stable_id"
                continue
            if path.parent.name != entity.content_type.value:
                yield path, None, "directory does not match content_type"
                continue
            if not entity.content_markdown.strip() or not entity.content_plain_text.strip():
                yield path, None, "empty content"
                continue
            checksum = hashlib.sha256(entity.content_markdown.encode("utf-8")).hexdigest()
            if checksum != entity.checksum:
                yield path, None, "Markdown checksum mismatch"
                continue
            yield path, entity, None

    def get_record(self, root: Path, stable_id: str) -> NormalizedEntity | None:
        if not stable_id or not all(
            character.isalnum() or character in "_-" for character in stable_id
        ):
            return None
        matches = tuple(root.glob(f"*/{stable_id}.json"))
        if len(matches) != 1:
            return None
        try:
            entity = NormalizedEntity.model_validate_json(matches[0].read_bytes())
        except Exception:
            return None
        return entity if entity.stable_id == stable_id else None


class JsonIndexManifestStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> IndexManifest | None:
        if not self._path.exists():
            return None
        return IndexManifest.model_validate_json(self._path.read_bytes())

    def save(self, manifest: IndexManifest) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        content = stable_json_bytes(manifest.model_dump(mode="json"))
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.", dir=self._path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def invalidate(self) -> None:
        self._path.unlink(missing_ok=True)

    def raw(self) -> dict[str, object] | None:
        if not self._path.exists():
            return None
        value = json.loads(self._path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
