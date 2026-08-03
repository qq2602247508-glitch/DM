"""Campaign-scoped, opt-in source-book content packs.

The local CHM corpus deliberately keeps its raw provenance fields.  Several
official supplement books were ingested before their ``officiality`` and
``edition`` metadata could be normalised, so treating every ``unknown`` record
as core content would be unsafe.  This registry makes the exception explicit:
only records whose ``source_book`` matches one of these named packs may be
promoted into the optional compendium view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContentPack:
    """A locally available official supplement that a campaign may opt into."""

    key: str
    label: str
    source_book: str
    summary: str
    source_edition: str
    automation_status: str
    content_types: tuple[str, ...]
    source_book_aliases: tuple[str, ...] = ()
    source_path_prefixes: tuple[str, ...] = ()
    requires_legacy: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "source_book": self.source_book,
            "summary": self.summary,
            "source_edition": self.source_edition,
            "automation_status": self.automation_status,
            "content_types": list(self.content_types),
            "character_option_policy": (
                "structured_or_dm_choice"
                if any(
                    item in self.content_types
                    for item in ("classes", "subclasses", "feats")
                )
                else "not_applicable"
            ),
            "requires_legacy": self.requires_legacy,
            "source_origin": "official_supplement",
            "default_enabled": False,
        }


_CONTENT_PACKS: tuple[ContentPack, ...] = (
    ContentPack(
        key="xanathars-guide",
        label="珊娜萨的万事指南",
        source_book="珊娜萨的万事指南",
        summary="可选法术、规则参考和魔法物品；法术详情可直接进入规则积木编译。",
        source_edition="2014-compatible",
        automation_status="partial",
        content_types=("spells", "classes", "subclasses", "feats", "rules", "items"),
        source_path_prefixes=("珊娜萨的万事指南",),
    ),
    ContentPack(
        key="tashas-cauldron",
        label="塔莎的万事坩埚",
        source_book="塔莎的万事坩埚",
        summary="可选法术、奇械师/子职业与物品；职业成长表仍以单独标准化状态显示。",
        source_edition="2014-compatible",
        automation_status="partial",
        content_types=("spells", "classes", "subclasses", "feats", "items", "rules"),
        source_path_prefixes=("塔莎的万事坩埚",),
    ),
    ContentPack(
        key="mordenkainen-multiverse",
        label="魔邓肯巨献：多元宇宙的怪物",
        source_book="魔邓肯巨献：多元宇宙的怪物",
        summary="怪物图鉴。含完整属性块的条目会导入为可实例化怪物原子。",
        source_edition="2014-compatible",
        automation_status="partial",
        content_types=("monsters",),
        source_book_aliases=("多元宇宙的怪物",),
        source_path_prefixes=("魔邓肯巨献：多元宇宙的怪物", "多元宇宙的怪物"),
    ),
    ContentPack(
        key="fizbans-treasury",
        label="费资本的巨龙宝库",
        source_book="费资本的巨龙宝库",
        summary="巨龙主题法术、物品与图鉴条目；只导入明确的法术详情和属性块。",
        source_edition="2014-compatible",
        automation_status="partial",
        content_types=("spells", "monsters", "items"),
        source_path_prefixes=("费资本的巨龙宝库",),
    ),
    ContentPack(
        key="bigbys-glory",
        label="毕格比巨献：巨人之荣耀",
        source_book="毕格比巨献：巨人之荣耀",
        summary="巨人图鉴与主题物品。原始库中未分类图鉴页会标成“待标准化”。",
        source_edition="2014-compatible",
        automation_status="partial",
        content_types=("classes", "subclasses", "feats", "monsters", "items"),
        source_book_aliases=("巨人之荣耀",),
        source_path_prefixes=("毕格比巨献：巨人之荣耀", "巨人之荣耀"),
    ),
    ContentPack(
        key="book-of-many-things",
        label="万象无常书",
        source_book="万象无常书",
        summary="卡牌主题法术、物品与遭遇内容；只有可识别的法术详情和属性块自动导入。",
        source_edition="2014-compatible",
        automation_status="partial",
        content_types=("spells", "monsters", "items"),
        source_path_prefixes=("万象无常书",),
    ),
)

CONTENT_PACKS_BY_KEY = {pack.key: pack for pack in _CONTENT_PACKS}
CONTENT_PACKS_BY_SOURCE_BOOK = {
    source_book: pack
    for pack in _CONTENT_PACKS
    for source_book in (pack.source_book, *pack.source_book_aliases)
}


def list_content_packs() -> tuple[dict[str, Any], ...]:
    """Return stable metadata for campaign creation and settings UIs."""

    return tuple(pack.as_dict() for pack in _CONTENT_PACKS)


def content_pack_for_record(
    record: dict[str, Any],
    *,
    allow_source_path: bool = False,
) -> ContentPack | None:
    source_book = str(record.get("source_book") or "").strip()
    direct = CONTENT_PACKS_BY_SOURCE_BOOK.get(source_book)
    if direct is not None:
        return direct

    if not allow_source_path:
        return None

    # Some character-option CHM pages were imported with a generic source_book
    # such as “本书速查”. Their relative path remains stable provenance.  This
    # opt-in fallback is deliberately not the global compendium default: a
    # prose page must not become an automatically compiled monster/action just
    # because it happens to live under a known book root.
    source_path = str(record.get("source_relative_path") or "").strip().strip("/")
    for pack in _CONTENT_PACKS:
        for prefix in pack.source_path_prefixes:
            normalized = prefix.strip().strip("/")
            if source_path == normalized or source_path.startswith(normalized + "/"):
                return pack
    return None


def normalize_enabled_content_packs(values: object) -> list[str]:
    """Validate and order a persisted campaign content-pack selection."""

    raw = values if isinstance(values, (list, tuple, set, frozenset)) else []
    keys = [str(value).strip() for value in raw if str(value).strip()]
    unknown = sorted(set(keys) - set(CONTENT_PACKS_BY_KEY))
    if unknown:
        raise ValueError(f"unknown content pack: {', '.join(unknown)}")
    selected = set(keys)
    return [pack.key for pack in _CONTENT_PACKS if pack.key in selected]


def validate_content_pack_compatibility(
    values: object,
    *,
    allow_legacy: bool = False,
    primary_rules_year: int = 2024,
) -> list[str]:
    """Return an ordered campaign selection after edition/origin validation.

    The registry is intentionally the only promotion path for records whose
    crawler metadata says ``unknown``.  Every currently shipped supplement is
    a 2014-compatible source, so a 2024 campaign must opt in to the legacy
    boundary before it can expose those records to advancement or the
    compendium.  Keeping this separate from ``normalize_*`` preserves its use
    for safe read-only parsing of a persisted selection.
    """

    if primary_rules_year != 2024:
        raise ValueError("only the 2024 primary rules year is supported")
    selected = normalize_enabled_content_packs(values)
    legacy = [
        CONTENT_PACKS_BY_KEY[key].label
        for key in selected
        if CONTENT_PACKS_BY_KEY[key].requires_legacy
    ]
    if legacy and not allow_legacy:
        raise ValueError(
            "这些内容包来自 2014/旧版兼容资料，需先开启 allow_legacy："
            + "、".join(legacy)
        )
    return selected


def normalized_record_edition(record: dict[str, Any]) -> str:
    """Return a stable edition label without trusting unregistered metadata."""

    pack = content_pack_for_record(record, allow_source_path=True)
    if pack is not None:
        return "2014" if pack.requires_legacy else pack.source_edition
    edition = str(record.get("normalized_edition") or record.get("edition") or "")
    return edition or "unknown"


def record_is_enabled_for_content_packs(
    record: dict[str, Any],
    enabled_content_packs: object,
    *,
    allow_source_path: bool = False,
    allow_legacy: bool = True,
) -> bool:
    """True only when a recognised supplementary source has been selected."""

    pack = content_pack_for_record(record, allow_source_path=allow_source_path)
    if pack is None:
        return False
    if pack.requires_legacy and not allow_legacy:
        return False
    if isinstance(enabled_content_packs, frozenset):
        selected = enabled_content_packs
    else:
        selected = frozenset(normalize_enabled_content_packs(enabled_content_packs))
    return pack.key in selected


def is_spell_detail_record(record: dict[str, Any]) -> bool:
    """Reject spell index/list pages even when the crawler labelled them spells."""

    if str(record.get("content_type") or "") != "spells":
        return False
    if "法术详述" not in str(record.get("source_relative_path") or ""):
        return False
    spell = record.get("spell")
    if not isinstance(spell, dict):
        return False
    # A list page typically has all these fields empty.  A cantrip can have a
    # null level, so do not require the level itself.
    return sum(
        bool(spell.get(key))
        for key in ("casting_time", "range", "duration", "school", "classes")
    ) >= 2
