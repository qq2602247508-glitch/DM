from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from dnd_dm_assistant.domain.content import (
    NavigationRecord,
    NormalizedEntity,
    QualityAccumulator,
    QualityReport,
    SourceProvenance,
)
from dnd_dm_assistant.infrastructure.content_artifacts import ArtifactStore
from dnd_dm_assistant.integrations.content.fetcher import FetchError, SafeHttpFetcher
from dnd_dm_assistant.integrations.content.navigation import (
    NavigationDiscovery,
    discover_snapshot_files,
    parse_navigation,
    parse_wcp_navigation,
)
from dnd_dm_assistant.integrations.content.parser import decode_html, parse_entities
from dnd_dm_assistant.integrations.content.repository import RepositoryError, Snapshot
from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy


def deterministic_run_id(provenance: SourceProvenance, max_pages: int) -> str:
    material = (
        f"{provenance.source_kind}\n{provenance.repository_url}\n"
        f"{provenance.revision}\n{provenance.source_ref}\n"
        f"{provenance.declared_license}\n{max_pages}"
    )
    return f"run-{hashlib.sha256(material.encode()).hexdigest()[:16]}"


def _page_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _group_fetchable(
    discovery: NavigationDiscovery,
) -> dict[str, list[NavigationRecord]]:
    grouped: dict[str, list[NavigationRecord]] = defaultdict(list)
    for record in discovery.records:
        if record.fetchable and record.canonical_url:
            grouped[_page_url(record.canonical_url)].append(record)
    return dict(grouped)


def _emit_entities(
    entities: tuple[NormalizedEntity, ...],
    *,
    store: ArtifactStore,
    accumulator: QualityAccumulator,
    emitted: dict[str, NormalizedEntity],
) -> None:
    for entity in entities:
        previous = emitted.get(entity.stable_id)
        if previous is not None:
            accumulator.duplicates += 1
            if previous.checksum != entity.checksum:
                accumulator.errors.append(f"conflicting_duplicate:{entity.stable_id}")
                accumulator.failed += 1
            continue
        emitted[entity.stable_id] = entity
        _, _, checksum_changed = store.write_entity(entity)
        if checksum_changed:
            accumulator.checksum_changes += 1
        accumulator.count_entity(entity)


def normalize_snapshot(
    *,
    snapshot: Snapshot,
    policy: UrlPolicy,
    store: ArtifactStore,
    max_pages: int,
    source_kind: Literal["fixture", "local_snapshot", "github_snapshot"] = "local_snapshot",
    fetched_at: datetime | None = None,
) -> QualityReport:
    started_at = time.monotonic()
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    provenance = SourceProvenance(
        source_kind=source_kind,
        repository_url=snapshot.repository_url,
        revision=snapshot.revision,
        source_ref=snapshot.source_ref,
        declared_license=snapshot.declared_license,
        checkout_path=str(snapshot.checkout_root),
    )
    run_id = deterministic_run_id(provenance, max_pages)
    accumulator = QualityAccumulator(run_id)
    navigation_path = snapshot.find_navigation()
    navigation_bytes = navigation_path.read_bytes()
    navigation_html, navigation_warnings = decode_html(navigation_bytes)
    relative_nav = navigation_path.relative_to(snapshot.checkout_root).as_posix()
    navigation_url = policy.canonicalize(f"/{relative_nav}")
    navigation_discovery = (
        parse_wcp_navigation(navigation_html, policy=policy)
        if navigation_path.suffix.lower() == ".wcp"
        else parse_navigation(navigation_html, page_url=navigation_url, policy=policy)
    )
    discovery = (
        discover_snapshot_files(
            snapshot,
            policy=policy,
            navigation=navigation_discovery,
        )
        if navigation_path.suffix.lower() == ".wcp"
        else navigation_discovery
    )
    accumulator.discovered = len(discovery.records)
    accumulator.duplicates = discovery.duplicate_count
    accumulator.rejected.extend(discovery.rejected_urls)
    accumulator.warnings.extend(navigation_warnings)
    accumulator.skipped += sum(not record.fetchable for record in discovery.records)

    grouped = _group_fetchable(discovery)
    selected_pages = tuple(grouped.items())[:max_pages]
    accumulator.skipped += sum(len(records) for _, records in tuple(grouped.items())[max_pages:])
    emitted: dict[str, NormalizedEntity] = {}
    stable_fetched_at = fetched_at or snapshot.snapshot_at
    for page_url, records in selected_pages:
        try:
            page_path, relative_path = snapshot.resolve_url(page_url)
            body = page_path.read_bytes()
        except (OSError, RepositoryError) as exc:
            accumulator.failed += len(records)
            accumulator.errors.append(f"{page_url}:{exc}")
            continue
        store.write_raw(page_url, body)
        accumulator.fetched += 1
        html, decode_warnings = decode_html(body)
        for record in records:
            entities = parse_entities(
                html,
                record=record,
                page_url=page_url,
                policy=policy,
                fetched_at=stable_fetched_at,
                run_id=run_id,
                inherited_warnings=decode_warnings,
                repository_url=snapshot.repository_url,
                source_revision=snapshot.revision,
                source_ref=snapshot.source_ref,
                source_relative_path=relative_path,
                source_license=snapshot.declared_license,
            )
            accumulator.parsed += 1
            if not entities:
                accumulator.failed += 1
                accumulator.errors.append(f"no_entity:{record.canonical_url}")
                continue
            _emit_entities(
                entities,
                store=store,
                accumulator=accumulator,
                emitted=emitted,
            )

    store.write_manifest(
        run_id=run_id,
        source=navigation_url,
        robots_status="offline_snapshot_not_applicable",
        record_ids=tuple(sorted(emitted)),
        provenance=provenance,
    )
    accumulator.elapsed_seconds = time.monotonic() - started_at
    accumulator.output_bytes = store.size_bytes()
    report = accumulator.build()
    store.write_report(report)
    accumulator.output_bytes = store.size_bytes()
    report = accumulator.build()
    store.write_report(report)
    return report


async def crawl_website(
    *,
    fetcher: SafeHttpFetcher,
    policy: UrlPolicy,
    store: ArtifactStore,
    max_pages: int,
    navigation_url: str = "/webhelplefth.htm",
) -> QualityReport:
    started_at = time.monotonic()
    provenance = SourceProvenance(source_kind="website")
    run_id = deterministic_run_id(provenance, max_pages)
    accumulator = QualityAccumulator(run_id)
    robots_status = await fetcher.check_robots()
    navigation_page = await fetcher.fetch(navigation_url)
    navigation_html, navigation_warnings = decode_html(
        navigation_page.body, navigation_page.content_type
    )
    discovery = parse_navigation(
        navigation_html,
        page_url=navigation_page.canonical_url,
        policy=policy,
    )
    accumulator.discovered = len(discovery.records)
    accumulator.duplicates = discovery.duplicate_count
    accumulator.rejected.extend(discovery.rejected_urls)
    accumulator.warnings.extend(navigation_warnings)
    accumulator.skipped += sum(not record.fetchable for record in discovery.records)
    grouped = _group_fetchable(discovery)
    selected_pages = tuple(grouped.items())[:max_pages]
    accumulator.skipped += sum(len(records) for _, records in tuple(grouped.items())[max_pages:])
    emitted: dict[str, NormalizedEntity] = {}

    for page_url, records in selected_pages:
        try:
            page = await fetcher.fetch(page_url)
        except FetchError as exc:
            accumulator.failed += len(records)
            accumulator.errors.append(f"{page_url}:{exc}")
            continue
        store.write_raw(page.canonical_url, page.body)
        accumulator.fetched += 1
        html, decode_warnings = decode_html(page.body, page.content_type)
        for record in records:
            entities = parse_entities(
                html,
                record=record,
                page_url=page.canonical_url,
                policy=policy,
                fetched_at=page.fetched_at,
                run_id=run_id,
                inherited_warnings=decode_warnings,
            )
            accumulator.parsed += 1
            if not entities:
                accumulator.failed += 1
                continue
            _emit_entities(
                entities,
                store=store,
                accumulator=accumulator,
                emitted=emitted,
            )
    store.write_manifest(
        run_id=run_id,
        source=policy.canonicalize(navigation_url),
        robots_status=robots_status,
        record_ids=tuple(sorted(emitted)),
        provenance=provenance,
    )
    accumulator.elapsed_seconds = time.monotonic() - started_at
    accumulator.output_bytes = store.size_bytes()
    report = accumulator.build()
    store.write_report(report)
    accumulator.output_bytes = store.size_bytes()
    report = accumulator.build()
    store.write_report(report)
    return report
