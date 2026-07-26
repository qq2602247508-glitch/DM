from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from urllib.parse import unquote, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, PageElement, Tag

from dnd_dm_assistant.domain.content import (
    ContentType,
    NavigationRecord,
    NormalizedEntity,
    SpellFields,
)
from dnd_dm_assistant.integrations.content.url_policy import UrlPolicy, UrlRejected

HEADING_RE = re.compile(r"^h([1-6])$", re.IGNORECASE)
SPACE_RE = re.compile(r"[ \t\u3000]+")
BLANK_RE = re.compile(r"\n{3,}")
CHINESE_LEVELS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def decode_html(body: bytes, content_type: str = "") -> tuple[str, tuple[str, ...]]:
    warnings: list[str] = []
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return body.decode("utf-16"), ("decoded_with_utf-16",)
        except UnicodeDecodeError:
            warnings.append("invalid_utf16_bom")
    declared_match = re.search(r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", content_type, re.I)
    encodings = [declared_match.group(1)] if declared_match else []
    encodings.extend(["utf-8-sig", "gb18030"])
    tried: set[str] = set()
    for encoding in encodings:
        normalized = encoding.lower()
        if normalized in tried:
            continue
        tried.add(normalized)
        try:
            text = body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        if normalized not in {"utf-8", "utf-8-sig"}:
            warnings.append(f"decoded_with_{normalized}")
        return text, tuple(warnings)
    warnings.append("decode_replacement_characters")
    return body.decode("utf-8", errors="replace"), tuple(warnings)


def _clean_inline(value: str) -> str:
    return SPACE_RE.sub(" ", value.replace("\xa0", " ")).strip()


def _clean_markdown(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return BLANK_RE.sub("\n\n", "\n".join(lines)).strip() + "\n"


def _plain_text(nodes: Sequence[PageElement]) -> str:
    values: list[str] = []
    for node in nodes:
        if isinstance(node, NavigableString):
            value = _clean_inline(str(node))
        elif isinstance(node, Tag):
            value = _clean_inline(node.get_text(" ", strip=True))
        else:
            value = ""
        if value:
            values.append(value)
    return "\n".join(values).strip()


class MarkdownRenderer:
    def __init__(self, policy: UrlPolicy) -> None:
        self.policy = policy
        self.warnings: list[str] = []

    def render(self, nodes: Sequence[PageElement]) -> str:
        return _clean_markdown("".join(self._node(node) for node in nodes))

    def _node(self, node: PageElement) -> str:
        if isinstance(node, NavigableString):
            return _clean_inline(str(node))
        if not isinstance(node, Tag) or not node.name:
            return ""
        name = node.name.lower()
        if name in {"script", "style", "noscript", "iframe", "svg", "canvas", "form"}:
            return ""
        if name in {"nav", "header", "footer"} or self._is_ui_noise(node):
            return ""
        if name == "br":
            return "\n"
        if heading := HEADING_RE.match(name):
            content = self._children(node)
            return f"\n\n{'#' * int(heading.group(1))} {content}\n\n"
        if name == "p":
            return f"\n\n{self._children(node)}\n\n"
        if name in {"strong", "b"}:
            return f"**{self._children(node)}**"
        if name in {"em", "i"}:
            return f"*{self._children(node)}*"
        if name == "code":
            return f"`{self._children(node)}`"
        if name == "blockquote":
            content = self._children(node).strip()
            return "\n\n" + "\n".join(f"> {line}" for line in content.splitlines()) + "\n\n"
        if name in {"ul", "ol"}:
            return self._list(node, ordered=name == "ol")
        if name == "table":
            return self._table(node)
        if name == "a":
            text = self._children(node) or _clean_inline(str(node.get("title", "")))
            href = str(node.get("href", "")).strip()
            if not href or href == "#":
                return text
            try:
                safe_url = self.policy.canonicalize(href)
            except UrlRejected:
                self.warnings.append(f"unsafe_link_removed:{href}")
                return text
            return f"[{text}]({safe_url})"
        if name == "img":
            return ""
        return self._children(node)

    def _children(self, node: Tag) -> str:
        return "".join(self._node(child) for child in node.children)

    @staticmethod
    def _is_ui_noise(node: Tag) -> bool:
        marker = " ".join(
            (
                str(node.get("id", "")),
                " ".join(str(item) for item in node.get("class", [])),
                str(node.get("role", "")),
            )
        ).lower()
        return any(value in marker for value in ("navigation", "sidebar", "breadcrumb", "toolbar"))

    def _list(self, node: Tag, *, ordered: bool) -> str:
        lines: list[str] = []
        index = 1
        for child in node.find_all("li", recursive=False):
            prefix = f"{index}." if ordered else "-"
            content = self._children(child).strip()
            lines.append(f"{prefix} {content}")
            index += 1
        return f"\n\n{'\n'.join(lines)}\n\n" if lines else ""

    def _table(self, node: Tag) -> str:
        rows: list[list[str]] = []
        for row in node.find_all("tr"):
            cells = [
                _clean_inline(cell.get_text(" ", strip=True)).replace("|", "\\|")
                for cell in row.find_all(["th", "td"], recursive=False)
            ]
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        output = [
            "| " + " | ".join(padded[0]) + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
        ]
        output.extend("| " + " | ".join(row) + " |" for row in padded[1:])
        return f"\n\n{'\n'.join(output)}\n\n"


def _strip_noise(soup: BeautifulSoup) -> None:
    for node in soup.find_all(
        [
            "script",
            "style",
            "noscript",
            "iframe",
            "svg",
            "canvas",
            "form",
            "nav",
            "header",
            "footer",
        ]
    ):
        node.decompose()
    for node in soup.find_all(True):
        if node.attrs is None:
            continue
        marker = " ".join(
            (
                str(node.get("id", "")),
                " ".join(str(value) for value in node.get("class", [])),
                str(node.get("role", "")),
            )
        ).lower()
        if any(value in marker for value in ("navigation", "sidebar", "breadcrumb", "toolbar")):
            node.decompose()


def _heading_path(heading: Tag) -> tuple[str, ...]:
    match = HEADING_RE.match(heading.name or "")
    if not match:
        return ()
    level = int(match.group(1))
    previous: dict[int, str] = {}
    for candidate in heading.find_all_previous(re.compile(r"^h[1-6]$", re.I)):
        if not isinstance(candidate, Tag):
            continue
        candidate_match = HEADING_RE.match(candidate.name or "")
        if candidate_match is None:
            continue
        candidate_level = int(candidate_match.group(1))
        if candidate_level < level and candidate_level not in previous:
            previous[candidate_level] = _clean_inline(candidate.get_text(" ", strip=True))
    return tuple(previous[key] for key in sorted(previous))


def _section_nodes(heading: Tag) -> tuple[PageElement, ...]:
    match = HEADING_RE.match(heading.name or "")
    level = int(match.group(1)) if match else 6
    nodes: list[PageElement] = [heading]
    for sibling in heading.next_siblings:
        if isinstance(sibling, Tag):
            sibling_match = HEADING_RE.match(sibling.name or "")
            if sibling_match and int(sibling_match.group(1)) <= level:
                break
        nodes.append(sibling)
    return tuple(nodes)


def _name_aliases(raw_heading: str, fallback: str) -> tuple[str, tuple[str, ...]]:
    value = _clean_inline(raw_heading) or fallback
    parts = tuple(part.strip() for part in re.split(r"[｜|]", value) if part.strip())
    if not parts:
        return fallback, ()
    return parts[0], parts[1:]


def _labeled_value(text: str, *labels: str) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})\s*[:：]\s*(.+?)"
        rf"(?=\n|(?:施法时间|施法距离|射程|法术成分|成分|持续时间)\s*[:：]|$)",
        text,
        re.I,
    )
    return _clean_inline(match.group(1)) if match else None


SPELL_LABELS: dict[str, str] = {
    "施法时间": "casting_time",
    "施法距离": "range",
    "射程": "range",
    "法术成分": "components",
    "成分": "components",
    "持续时间": "duration",
}
BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "div",
    "dl",
    "fieldset",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "ul",
}


def _spell_label(tag: Tag) -> str | None:
    if (tag.name or "").lower() not in {"strong", "b"}:
        return None
    label = _clean_inline(tag.get_text(" ", strip=True)).rstrip(":：").strip()
    return SPELL_LABELS.get(label)


def _inline_text_until_boundary(node: PageElement) -> tuple[str, bool]:
    if isinstance(node, NavigableString):
        return str(node), False
    if not isinstance(node, Tag) or not node.name:
        return "", False
    name = node.name.lower()
    if name == "br" or _spell_label(node) is not None or name in BLOCK_TAGS:
        return "", True
    values: list[str] = []
    for child in node.children:
        value, stopped = _inline_text_until_boundary(child)
        values.append(value)
        if stopped:
            return " ".join(values), True
    return " ".join(values), False


def _value_after_spell_label(label: Tag) -> str | None:
    values: list[str] = []
    for sibling in label.next_siblings:
        value, stopped = _inline_text_until_boundary(sibling)
        values.append(value)
        if stopped:
            break
    cleaned = _clean_inline(" ".join(values))
    return cleaned or None


def _structured_spell_labels(nodes: Sequence[PageElement]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for root in nodes:
        if not isinstance(root, Tag):
            continue
        candidates = [root] if _spell_label(root) is not None else []
        candidates.extend(root.find_all(["strong", "b"]))
        for candidate in candidates:
            field = _spell_label(candidate)
            if field is None or field in fields:
                continue
            value = _value_after_spell_label(candidate)
            if value is not None:
                fields[field] = value
    return fields


def _spell_fields(plain: str, nodes: Sequence[PageElement]) -> tuple[SpellFields, tuple[str, ...]]:
    italic_text = " ".join(
        node.get_text(" ", strip=True)
        for root in nodes
        if isinstance(root, Tag)
        for node in root.find_all(["em", "i"])
    )
    descriptor = _clean_inline(italic_text)
    level_match = re.search(r"([零一二三四五六七八九]|\d)\s*环", descriptor)
    level: int | None = None
    if level_match:
        raw_level = level_match.group(1)
        level = CHINESE_LEVELS.get(raw_level, int(raw_level) if raw_level.isdigit() else 0)
    school_match = re.search(r"(防护|咒法|预言|附魔|塑能|幻术|死灵|变化)", descriptor)
    class_match = re.search(r"[（(]([^）)]+)[）)]", descriptor)
    classes = (
        tuple(
            value.strip() for value in re.split(r"[,，、/]", class_match.group(1)) if value.strip()
        )
        if class_match
        else ()
    )
    damage_match = re.search(r"(\d+d\d+(?:\s*[+-]\s*\d+)?)", plain, re.I)
    damage_type_match = re.search(
        r"(火焰|寒冷|闪电|雷鸣|酸蚀|毒素|力场|光耀|黯蚀|心灵|穿刺|挥砍|钝击)"
        r"\s*(?:伤害)?",
        plain,
    )
    save_match = re.search(r"(力量|敏捷|体质|智力|感知|魅力)(?:豁免|检定)", plain)
    upcast_match = re.search(r"((?:升环|高环施法|使用更高环位).+)", plain, re.S)

    structured = _structured_spell_labels(nodes)
    casting_time = structured.get("casting_time") or _labeled_value(plain, "施法时间")
    spell_range = structured.get("range") or _labeled_value(plain, "施法距离", "射程")
    components = structured.get("components") or _labeled_value(plain, "法术成分", "成分")
    duration = structured.get("duration") or _labeled_value(plain, "持续时间")
    warnings: list[str] = []
    for field_name, value in (
        ("level", level),
        ("school", school_match),
        ("casting_time", casting_time),
        ("range", spell_range),
        ("components", components),
        ("duration", duration),
    ):
        if value is None:
            warnings.append(f"missing_spell_{field_name}")
    return (
        SpellFields(
            level=level,
            school=school_match.group(1) if school_match else None,
            classes=classes,
            casting_time=casting_time,
            range=spell_range,
            components=components,
            duration=duration,
            damage_expression=damage_match.group(1) if damage_match else None,
            damage_type=damage_type_match.group(1) if damage_type_match else None,
            save=f"{save_match.group(1)}豁免" if save_match else None,
            ritual="仪式" in descriptor if descriptor else None,
            concentration="专注" in (duration or "") if duration else None,
            upcast_text=_clean_inline(upcast_match.group(1)) if upcast_match else None,
        ),
        tuple(warnings),
    )


def _canonical_entity_url(page_url: str, fragment: str | None) -> str:
    parts = urlsplit(page_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, fragment or ""))


def _stable_id(canonical_url: str, content_type: ContentType) -> str:
    material = f"{content_type.value}\n{canonical_url}".encode()
    return hashlib.sha256(material).hexdigest()[:24]


def _build_entity(
    *,
    record: NavigationRecord,
    page_url: str,
    nodes: Sequence[PageElement],
    heading: Tag | None,
    policy: UrlPolicy,
    fetched_at: datetime,
    run_id: str,
    inherited_warnings: Iterable[str],
    repository_url: str | None,
    source_revision: str | None,
    source_ref: str | None,
    source_relative_path: str | None,
    source_license: str,
) -> NormalizedEntity | None:
    renderer = MarkdownRenderer(policy)
    markdown = renderer.render(nodes)
    plain = _plain_text(nodes)
    if not markdown.strip() or not plain:
        return None

    raw_heading = heading.get_text(" ", strip=True) if heading is not None else record.title
    name, heading_aliases = _name_aliases(raw_heading, record.title)
    aliases = tuple(dict.fromkeys((*record.aliases, *heading_aliases)))
    fragment = (
        str(heading.get("id")) if heading is not None and heading.get("id") else record.fragment
    )
    canonical_url = _canonical_entity_url(page_url, fragment)
    checksum = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    spell: SpellFields | None = None
    warnings = list(inherited_warnings)
    warnings.extend(record.warnings)
    warnings.extend(renderer.warnings)
    if record.content_type is ContentType.SPELLS:
        spell, spell_warnings = _spell_fields(plain, nodes)
        warnings.extend(spell_warnings)
    heading_path = (*record.path_hierarchy, *(_heading_path(heading) if heading else ()), name)
    return NormalizedEntity(
        stable_id=_stable_id(canonical_url, record.content_type),
        name=name,
        aliases=aliases,
        content_type=record.content_type,
        source_url=record.url or canonical_url,
        canonical_url=canonical_url,
        repository_url=repository_url,
        source_revision=source_revision,
        source_ref=source_ref,
        source_relative_path=source_relative_path,
        source_license=source_license,
        source_book=record.source_book,
        edition=record.edition,
        officiality=record.officiality,
        legacy=record.legacy,
        heading_path=tuple(dict.fromkeys(value for value in heading_path if value)),
        fragment=fragment,
        content_markdown=markdown,
        content_plain_text=plain,
        checksum=checksum,
        fetched_at=fetched_at,
        run_id=run_id,
        spell=spell,
        warnings=tuple(sorted(set(warnings))),
    )


def parse_entities(
    html: str,
    *,
    record: NavigationRecord,
    page_url: str,
    policy: UrlPolicy,
    fetched_at: datetime,
    run_id: str,
    inherited_warnings: Iterable[str] = (),
    repository_url: str | None = None,
    source_revision: str | None = None,
    source_ref: str | None = None,
    source_relative_path: str | None = None,
    source_license: str = "unknown",
) -> tuple[NormalizedEntity, ...]:
    soup = BeautifulSoup(html, "html.parser")
    _strip_noise(soup)
    headings: list[Tag] = []
    if record.fragment:
        target = soup.find(id=unquote(record.fragment))
        if isinstance(target, Tag) and HEADING_RE.match(target.name or ""):
            headings = [target]
    elif record.content_type is ContentType.SPELLS:
        headings = [
            heading
            for heading in soup.find_all(re.compile(r"^h4$", re.I))
            if isinstance(heading, Tag) and heading.get("id")
        ]

    entities: list[NormalizedEntity] = []
    if headings:
        for heading in headings:
            entity = _build_entity(
                record=record,
                page_url=page_url,
                nodes=_section_nodes(heading),
                heading=heading,
                policy=policy,
                fetched_at=fetched_at,
                run_id=run_id,
                inherited_warnings=inherited_warnings,
                repository_url=repository_url,
                source_revision=source_revision,
                source_ref=source_ref,
                source_relative_path=source_relative_path,
                source_license=source_license,
            )
            if entity is not None:
                entities.append(entity)
    else:
        root = soup.body or soup
        entity = _build_entity(
            record=record,
            page_url=page_url,
            nodes=tuple(root.children),
            heading=None,
            policy=policy,
            fetched_at=fetched_at,
            run_id=run_id,
            inherited_warnings=inherited_warnings,
            repository_url=repository_url,
            source_revision=source_revision,
            source_ref=source_ref,
            source_relative_path=source_relative_path,
            source_license=source_license,
        )
        if entity is not None:
            entities.append(entity)
    deduplicated = {entity.stable_id: entity for entity in entities}
    return tuple(deduplicated[key] for key in sorted(deduplicated))
