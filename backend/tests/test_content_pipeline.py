from __future__ import annotations

import hashlib
from pathlib import Path

from dnd_dm_assistant.application.content_ingestion import normalize_snapshot
from dnd_dm_assistant.domain.content import ContentType, NormalizedEntity
from dnd_dm_assistant.infrastructure.content_artifacts import ArtifactStore
from dnd_dm_assistant.integrations.content.navigation import discover_snapshot_files
from dnd_dm_assistant.integrations.content.repository import (
    REPOSITORIES,
    canonical_website_url,
    open_snapshot,
)
from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy


def _policy() -> UrlPolicy:
    return UrlPolicy(
        base_url="https://5echm.kagangtuya.top/",
        allowed_hosts=frozenset({"5echm.kagangtuya.top"}),
    )


def _snapshot():
    return open_snapshot(
        checkout_path=Path("backend/tests/fixtures/snapshot"),
        repository_url=REPOSITORIES["srd52"].repository_url,
        revision="a" * 40,
        source_ref="fixture-ref",
        declared_license=REPOSITORIES["srd52"].declared_license,
    )


def _tree_hash(root: Path, pattern: str) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.glob(pattern)):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def test_snapshot_pipeline_covers_all_types_and_provenance(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "generated")
    report = normalize_snapshot(
        snapshot=_snapshot(),
        policy=_policy(),
        store=store,
        max_pages=20,
        source_kind="fixture",
    )
    expected = {
        content_type.value for content_type in ContentType if content_type.value != "unknown"
    }
    assert set(report.by_content_type) == expected
    assert report.discovered == 14
    assert report.fetched == 13
    assert report.parsed == 13
    assert report.emitted == 13
    assert report.skipped == 1
    assert report.failed == 0
    assert report.duplicates == 1
    assert len(report.rejected_urls) == 2

    entities = [
        NormalizedEntity.model_validate_json(path.read_bytes())
        for path in sorted((tmp_path / "generated/json").glob("*/*.json"))
    ]
    assert len({entity.stable_id for entity in entities}) == len(entities)
    assert all(entity.source_revision == "a" * 40 for entity in entities)
    assert all(entity.source_ref == "fixture-ref" for entity in entities)
    assert all(entity.source_license == "CC-BY-4.0" for entity in entities)
    assert all(entity.repository_url == REPOSITORIES["srd52"].repository_url for entity in entities)
    assert all(entity.source_relative_path for entity in entities)


def test_deterministic_bytes_and_resumable_writes(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    normalize_snapshot(
        snapshot=_snapshot(),
        policy=_policy(),
        store=ArtifactStore(first),
        max_pages=20,
        source_kind="fixture",
    )
    first_hash = _tree_hash(first, "json/**/*.json") + _tree_hash(first, "markdown/**/*.md")
    tracked = next((first / "json").glob("*/*.json"))
    first_mtime = tracked.stat().st_mtime_ns
    normalize_snapshot(
        snapshot=_snapshot(),
        policy=_policy(),
        store=ArtifactStore(first),
        max_pages=20,
        source_kind="fixture",
    )
    assert tracked.stat().st_mtime_ns == first_mtime

    normalize_snapshot(
        snapshot=_snapshot(),
        policy=_policy(),
        store=ArtifactStore(second),
        max_pages=20,
        source_kind="fixture",
    )
    second_hash = _tree_hash(second, "json/**/*.json") + _tree_hash(second, "markdown/**/*.md")
    assert first_hash == second_hash


def test_repository_path_mapping_and_validation(tmp_path: Path) -> None:
    snapshot = _snapshot()
    url = canonical_website_url("topics/规则/核心规则.htm", _policy())
    path, relative = snapshot.resolve_url(url)
    assert path.name == "核心规则.htm"
    assert relative == "topics/规则/核心规则.htm"

    store = ArtifactStore(tmp_path / "generated")
    normalize_snapshot(
        snapshot=snapshot,
        policy=_policy(),
        store=store,
        max_pages=2,
        source_kind="fixture",
    )
    count, errors = store.validate()
    assert count == 2
    assert not errors


def test_filesystem_discovery_keeps_every_html_candidate() -> None:
    discovery = discover_snapshot_files(_snapshot(), policy=_policy())
    expected = sum(
        path.suffix.lower() in {".htm", ".html"}
        for path in Path("backend/tests/fixtures/snapshot").rglob("*")
        if path.is_file()
    )
    assert len(discovery.records) == expected
    assert all(record.fetchable for record in discovery.records)
    assert any(record.content_type is ContentType.UNKNOWN for record in discovery.records)
