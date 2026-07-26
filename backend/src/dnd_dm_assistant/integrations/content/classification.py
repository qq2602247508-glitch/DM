from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from dnd_dm_assistant.domain.content import (
    Classification,
    ContentType,
    Edition,
    Officiality,
)

CONTENT_MARKERS: tuple[tuple[ContentType, tuple[str, ...]], ...] = (
    (ContentType.SUBCLASSES, ("子职业", "子职", "subclass")),
    (ContentType.CLASSES, ("职业", "classes", "class")),
    (ContentType.SPELLS, ("法术", "spell")),
    (ContentType.MONSTERS, ("怪物", "monster", "生物图鉴")),
    (ContentType.FEATS, ("专长", "feat")),
    (ContentType.BACKGROUNDS, ("背景", "background")),
    (ContentType.CONDITIONS, ("状态", "条件", "condition")),
    (ContentType.ACTIONS, ("动作", "action")),
    (ContentType.EQUIPMENT, ("装备", "equipment")),
    (ContentType.ITEMS, ("魔法物品", "物品", "item")),
    (ContentType.RULES, ("规则", "rules", "rule", "玩法")),
)

BOOK_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("玩家手册 2024", ("玩家手册2024", "phb2024")),
    ("玩家手册 2014", ("玩家手册2014", "phb2014")),
    ("怪物图鉴 2025", ("怪物图鉴2025", "怪物手册2025", "mm2025")),
    ("怪物图鉴", ("怪物图鉴", "怪物手册", "monster manual")),
    ("地下城主指南", ("地下城主指南", "城主指南", "dmg")),
)

KNOWN_OFFICIAL_MARKERS = (
    "玩家手册",
    "怪物图鉴",
    "怪物手册",
    "地下城主指南",
    "城主指南",
    "phb",
    "dmg",
    "monster manual",
)


def _marker_present(marker: str, text: str) -> bool:
    lowered_marker = marker.lower()
    if lowered_marker.isascii() and lowered_marker.replace("-", "").replace("_", "").isalnum():
        return (
            re.search(
                rf"(?<![a-z0-9]){re.escape(lowered_marker)}(?![a-z0-9])",
                text,
            )
            is not None
        )
    return lowered_marker in text


def _content_type_for(title: str, path: str, hierarchy: tuple[str, ...]) -> ContentType:
    path_parts = tuple(part for part in path.strip("/").split("/") if part)
    basename = PurePosixPath(path).stem
    immediate_parent = path_parts[-2] if len(path_parts) > 1 else ""
    hierarchy_leaf = hierarchy[-1] if hierarchy else ""
    broad_evidence = (*hierarchy[:-1], *path_parts[:-2])
    tiers: tuple[tuple[str, ...], ...] = (
        (title,),
        (basename,),
        (immediate_parent,),
        (hierarchy_leaf,),
        broad_evidence,
    )
    for values in tiers:
        scores: dict[ContentType, int] = {}
        for value in values:
            lowered = value.lower()
            for candidate, markers in CONTENT_MARKERS:
                for marker in markers:
                    if not _marker_present(marker, lowered):
                        continue
                    exact_bonus = 20 if lowered.strip() == marker.lower() else 0
                    score = len(marker) + exact_bonus
                    scores[candidate] = max(scores.get(candidate, 0), score)
        if not scores:
            continue
        best_score = max(scores.values())
        winners = [candidate for candidate, score in scores.items() if score == best_score]
        if len(winners) == 1:
            return winners[0]
    return ContentType.UNKNOWN


def classify(title: str, url: str, hierarchy: tuple[str, ...] = ()) -> Classification:
    path = unquote(urlsplit(url).path)
    evidence = " / ".join((*hierarchy, title, path)).lower()

    content_type = _content_type_for(title, path, hierarchy)

    legacy = any(marker in evidence for marker in ("legacy", "遗留", "旧版"))
    third_party = any(marker in evidence for marker in ("第三方", "third-party", "third_party"))

    year_matches = set(re.findall(r"(?<!\d)(2014|2024|2025)(?!\d)", evidence))
    if legacy:
        edition = Edition.LEGACY
    elif len(year_matches) > 1:
        edition = Edition.MIXED
    elif year_matches == {"2014"}:
        edition = Edition.EDITION_2014
    elif year_matches == {"2024"}:
        edition = Edition.EDITION_2024
    elif year_matches == {"2025"}:
        edition = Edition.EDITION_2025
    elif (
        any(marker in evidence for marker in ("玩家手册", "怪物图鉴", "怪物手册", "城主指南"))
        and "2024" not in evidence
        and "2025" not in evidence
    ):
        edition = Edition.EDITION_2014
    else:
        edition = Edition.UNKNOWN

    source_book = next(
        (
            book
            for book, markers in BOOK_MARKERS
            if any(marker.lower() in evidence for marker in markers)
        ),
        None,
    )
    if source_book is None:
        path_parts = tuple(part for part in path.strip("/").split("/") if part)
        candidates = tuple(value for value in hierarchy if value) or path_parts
        if candidates:
            source_book = candidates[0]
            if source_book.lower() in {"topics", "第三方", "legacy"} and len(candidates) > 1:
                source_book = candidates[1]
    if third_party:
        officiality = Officiality.THIRD_PARTY
    elif any(marker in evidence for marker in KNOWN_OFFICIAL_MARKERS):
        officiality = Officiality.OFFICIAL
    else:
        officiality = Officiality.UNKNOWN

    warnings: list[str] = []
    if content_type is ContentType.UNKNOWN:
        warnings.append("unknown_content_type")
    if edition is Edition.UNKNOWN:
        warnings.append("unknown_edition")
    if officiality is Officiality.UNKNOWN:
        warnings.append("unknown_officiality")
    if source_book is None:
        warnings.append("unknown_source_book")
    return Classification(
        content_type=content_type,
        source_book=source_book,
        edition=edition,
        officiality=officiality,
        legacy=legacy,
        warnings=tuple(warnings),
    )
