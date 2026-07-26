from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Tag

from dnd_dm_assistant.domain.content import NavigationRecord, RejectedUrl
from dnd_dm_assistant.integrations.content.classification import classify
from dnd_dm_assistant.integrations.content.repository import Snapshot
from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy, UrlRejected

HEADING_RE = re.compile(r"^h([1-6])$", re.IGNORECASE)


@dataclass(frozen=True)
class NavigationDiscovery:
    records: tuple[NavigationRecord, ...]
    rejected_urls: tuple[RejectedUrl, ...]
    duplicate_count: int


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _ancestor_labels(anchor: Tag) -> tuple[str, ...]:
    labels: list[str] = []
    for parent in reversed(tuple(anchor.parents)):
        if not isinstance(parent, Tag) or parent.name != "li":
            continue
        direct = " ".join(
            child.strip()
            for child in parent.find_all(string=True, recursive=False)
            if child.strip()
        )
        if direct:
            labels.append(_clean_text(direct))
    return tuple(labels)


def parse_navigation(html: str, *, page_url: str, policy: UrlPolicy) -> NavigationDiscovery:
    soup = BeautifulSoup(html, "html.parser")
    heading_stack: list[str] = []
    ordered: list[NavigationRecord] = []
    positions: dict[str, int] = {}
    rejected: list[RejectedUrl] = []
    duplicate_count = 0

    for node in soup.descendants:
        if not isinstance(node, Tag) or not node.name:
            continue
        heading_match = HEADING_RE.match(node.name)
        if heading_match:
            level = int(heading_match.group(1))
            heading_stack[level - 1 :] = []
            heading_stack.extend([""] * (level - 1 - len(heading_stack)))
            heading_stack.append(_clean_text(node.get_text(" ", strip=True)))
            continue
        if node.name != "a":
            continue

        title = _clean_text(node.get_text(" ", strip=True))
        if not title:
            title = _clean_text(str(node.get("title", ""))) or "(untitled)"
        hierarchy = tuple(value for value in (*heading_stack, *_ancestor_labels(node)) if value)
        href_value = node.get("href")
        href = str(href_value).strip() if href_value is not None else ""

        if not href or href == "#":
            classification = classify(title, page_url, hierarchy)
            ordered.append(
                NavigationRecord(
                    title=title,
                    path_hierarchy=hierarchy,
                    source_book=classification.source_book,
                    edition=classification.edition,
                    officiality=classification.officiality,
                    legacy=classification.legacy,
                    content_type=classification.content_type,
                    fetchable=False,
                    warnings=tuple(sorted((*classification.warnings, "placeholder_href"))),
                )
            )
            continue

        try:
            canonical = policy.canonicalize(href)
        except UrlRejected as exc:
            rejected.append(RejectedUrl(url=href, reason=str(exc)))
            continue

        fragment = unquote(urlsplit(canonical).fragment) or None
        classification = classify(title, canonical, hierarchy)
        record = NavigationRecord(
            title=title,
            url=policy.canonicalize(href),
            canonical_url=canonical,
            path_hierarchy=hierarchy,
            source_book=classification.source_book,
            edition=classification.edition,
            officiality=classification.officiality,
            legacy=classification.legacy,
            content_type=classification.content_type,
            fragment=fragment,
            fetchable=True,
            warnings=classification.warnings,
        )
        existing_position = positions.get(canonical)
        if existing_position is None:
            positions[canonical] = len(ordered)
            ordered.append(record)
            continue

        duplicate_count += 1
        existing = ordered[existing_position]
        aliases = tuple(dict.fromkeys((*existing.aliases, existing.title, title)))
        ordered[existing_position] = existing.model_copy(
            update={
                "aliases": tuple(alias for alias in aliases if alias != existing.title),
                "path_hierarchy": existing.path_hierarchy or hierarchy,
            }
        )

    return NavigationDiscovery(
        records=tuple(ordered),
        rejected_urls=tuple(rejected),
        duplicate_count=duplicate_count,
    )


def parse_wcp_navigation(text: str, *, policy: UrlPolicy) -> NavigationDiscovery:
    values: dict[int, dict[str, str]] = {}
    pattern = re.compile(r"^TitleList\.(Title|Level|Url)\.(\d+)=(.*)$")
    for raw_line in text.splitlines():
        match = pattern.match(raw_line.strip())
        if match is None:
            continue
        field, raw_index, value = match.groups()
        values.setdefault(int(raw_index), {})[field.lower()] = value.strip()

    ordered: list[NavigationRecord] = []
    positions: dict[str, int] = {}
    rejected: list[RejectedUrl] = []
    hierarchy: list[str] = []
    duplicate_count = 0
    for index in sorted(values):
        item = values[index]
        title = _clean_text(item.get("title", "")) or "(untitled)"
        try:
            level = max(0, int(item.get("level", "0")))
        except ValueError:
            level = 0
        hierarchy[level:] = []
        parent_hierarchy = tuple(hierarchy)
        hierarchy.append(title)
        href = item.get("url", "").replace("\\", "/").strip()
        if not href or href == "#":
            classification = classify(title, policy.base_url, parent_hierarchy)
            ordered.append(
                NavigationRecord(
                    title=title,
                    path_hierarchy=parent_hierarchy,
                    source_book=classification.source_book,
                    edition=classification.edition,
                    officiality=classification.officiality,
                    legacy=classification.legacy,
                    content_type=classification.content_type,
                    fetchable=False,
                    warnings=tuple(sorted((*classification.warnings, "placeholder_href"))),
                )
            )
            continue
        try:
            canonical = policy.canonicalize(f"/{href.lstrip('/')}")
        except UrlRejected as exc:
            rejected.append(RejectedUrl(url=href, reason=str(exc)))
            continue
        fragment = unquote(urlsplit(canonical).fragment) or None
        classification = classify(title, canonical, parent_hierarchy)
        record = NavigationRecord(
            title=title,
            url=canonical,
            canonical_url=canonical,
            path_hierarchy=parent_hierarchy,
            source_book=classification.source_book,
            edition=classification.edition,
            officiality=classification.officiality,
            legacy=classification.legacy,
            content_type=classification.content_type,
            fragment=fragment,
            fetchable=True,
            warnings=classification.warnings,
        )
        existing_position = positions.get(canonical)
        if existing_position is None:
            positions[canonical] = len(ordered)
            ordered.append(record)
            continue
        duplicate_count += 1
        existing = ordered[existing_position]
        aliases = tuple(dict.fromkeys((*existing.aliases, title)))
        ordered[existing_position] = existing.model_copy(update={"aliases": aliases})
    return NavigationDiscovery(
        records=tuple(ordered),
        rejected_urls=tuple(rejected),
        duplicate_count=duplicate_count,
    )


def discover_snapshot_files(
    snapshot: Snapshot,
    *,
    policy: UrlPolicy,
    navigation: NavigationDiscovery | None = None,
) -> NavigationDiscovery:
    navigation_by_page: dict[str, NavigationRecord] = {}
    if navigation is not None:
        for record in navigation.records:
            if not record.canonical_url:
                continue
            page_parts = urlsplit(record.canonical_url)
            page_url = page_parts._replace(fragment="").geturl()
            navigation_by_page.setdefault(page_url, record)

    records: list[NavigationRecord] = []
    rejected = list(navigation.rejected_urls if navigation else ())
    for path in sorted(
        (
            candidate
            for candidate in snapshot.content_root.rglob("*")
            if candidate.is_file()
            and not candidate.is_symlink()
            and candidate.suffix.lower() in {".htm", ".html"}
        ),
        key=lambda candidate: candidate.relative_to(snapshot.content_root).as_posix(),
    ):
        relative = path.relative_to(snapshot.content_root).as_posix()
        try:
            canonical = policy.canonicalize(f"/{relative}")
        except UrlRejected as exc:
            rejected.append(RejectedUrl(url=relative, reason=str(exc)))
            continue
        nav_record = navigation_by_page.get(canonical)
        hierarchy = (
            nav_record.path_hierarchy
            if nav_record is not None
            else tuple(Path(relative).parent.parts)
        )
        title = nav_record.title if nav_record is not None else path.stem
        classification = classify(title, canonical, hierarchy)
        records.append(
            NavigationRecord(
                title=title,
                aliases=nav_record.aliases if nav_record is not None else (),
                url=canonical,
                canonical_url=canonical,
                path_hierarchy=hierarchy,
                source_book=classification.source_book,
                edition=classification.edition,
                officiality=classification.officiality,
                legacy=classification.legacy,
                content_type=classification.content_type,
                fetchable=True,
                warnings=classification.warnings,
            )
        )
    return NavigationDiscovery(
        records=tuple(records),
        rejected_urls=tuple(rejected),
        duplicate_count=navigation.duplicate_count if navigation else 0,
    )
