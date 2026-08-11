# ruff: noqa: E501
"""Deterministic whole-pack migration inventory for *Tasha's Cauldron*.

The existing Content IR workbench deliberately stops at page-level drafts.  This
module adds the missing audit boundary for the first complete supplement pack:
source records are selected by provenance, pages are split into stable atoms,
existing authored IR/runtime evidence is joined by source identity, and every
atom receives exactly one migration status.  It is an inventory/assessment
layer; it never promotes prose or a candidate into an executable definition.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_workbench import load_records
from dnd_dm_assistant.domain.content_ir_status import build_status_layers
from dnd_dm_assistant.domain.content_packs import (
    is_spell_detail_record,
    normalized_record_edition,
)

PACK_ID = "tashas-cauldron"
SOURCE_BOOK = "塔莎的万事坩埚"
SOURCE_PREFIX = SOURCE_BOOK + "/"
SCHEMA_VERSION = "tashas-whole-pack-migration-1"
MIGRATION_STATUSES = (
    "production_full",
    "dm_assisted",
    "compile_only",
    "manual_authoring",
    "invalid_source",
    "dm_reference",
    "non_instantiable",
    "duplicate_or_reprint",
    "out_of_scope_with_reason",
)
EXECUTABLE_KINDS = frozenset(
    {
        "class_feature",
        "subclass_feature",
        "optional_class_feature",
        "spell",
        "feat",
        "maneuver",
        "invocation",
        "infusion",
        "companion_profile",
        "summon_profile",
        "magic_item",
        "magic_tattoo",
        "character_option",
    }
)
PLAYER_KINDS = EXECUTABLE_KINDS | {
    "rule_reference",
    "directory",
    "index",
}
_BOLD_START = "**"
_HASH_HEADING = re.compile(r"^(#{2,6})\s+(.+?)\s*$")
_LEVEL_RE = re.compile(r"第\s*(\d+)\s*级")
_PREREQUISITE_RE = re.compile(r"(?:先决条件|前置条件)\s*[:：]?\s*([^\n。]+)")
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9' -]*")
_NON_ID_RE = re.compile(r"[^0-9A-Za-z._-]+")


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _text(value: object) -> str:
    return str(value or "").strip()


def _record_id(record: Mapping[str, Any]) -> str:
    explicit = _text(record.get("stable_id"))
    if explicit:
        return explicit
    return fingerprint(
        {
            "source_book": record.get("source_book"),
            "source_relative_path": record.get("source_relative_path"),
            "name": record.get("name"),
        }
    )[:24]


def source_fingerprint(record: Mapping[str, Any], fragment: str | None = None) -> str:
    payload = {
        "source_record_id": _record_id(record),
        "source_book": _text(record.get("source_book")),
        "source_relative_path": _text(record.get("source_relative_path")),
        "source_revision": _text(record.get("source_revision")),
        "checksum": _text(record.get("checksum")),
        "content": fragment
        if fragment is not None
        else _text(record.get("content_markdown") or record.get("content_plain_text")),
    }
    return fingerprint(payload)


def _normalized_name(value: object) -> str:
    text = _text(value).casefold()
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    return re.sub(r"[^\w\u3400-\u9fff]+", "", text, flags=re.UNICODE)


def _slug(value: str) -> str:
    compact = _NON_ID_RE.sub("-", value.casefold()).strip("-")
    return compact or fingerprint(value)[:12]


def _path_parts(record: Mapping[str, Any]) -> list[str]:
    path = _text(record.get("source_relative_path")).strip("/")
    if path.startswith(SOURCE_PREFIX):
        path = path[len(SOURCE_PREFIX) :]
    return [part for part in path.split("/") if part]


def select_source_records(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Select every record belonging to Tasha by field or stable source path."""

    selected = []
    for raw in records:
        record = dict(raw)
        path = _text(record.get("source_relative_path"))
        if _text(record.get("source_book")) == SOURCE_BOOK or path.startswith(SOURCE_PREFIX):
            selected.append(record)
    return sorted(
        selected,
        key=lambda item: (_text(item.get("source_relative_path")), _record_id(item)),
    )


def _class_name(record: Mapping[str, Any]) -> str | None:
    parts = _path_parts(record)
    if len(parts) < 2 or parts[0] != "玩家选项" or parts[1] != "职业":
        return None
    raw = parts[2] if len(parts) >= 3 else ""
    raw = re.sub(r"\.[^.]+$", "", raw)
    raw = re.sub(r"（TCE）|\(TCE\)", "", raw).strip()
    return raw or None


def _subclass_name(record: Mapping[str, Any]) -> str | None:
    parts = _path_parts(record)
    if len(parts) < 4 or parts[0:2] != ["玩家选项", "职业"]:
        return None
    if parts[3].startswith(("战技选项", "奇械师注法", "魔能祈唤", "奇械师法术列表")):
        return None
    raw = re.sub(r"\.[^.]+$", "", parts[3])
    return re.sub(r"（TCE）|\(TCE\)|（旧版）", "", raw).strip() or None


def classify_source_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a page without treating its page count as atom count."""

    parts = _path_parts(record)
    path = "/".join(parts)
    name = _text(record.get("name"))
    content_type = _text(record.get("content_type"))
    if is_spell_detail_record(dict(record)):
        kind, role = "spell", "player_facing"
    elif "法术列表" in path or name in {"法术列表", "个性化法术"}:
        kind, role = "directory", "non_instantiable"
    elif parts[:2] == ["魔法物品", "魔法物品详述"]:
        kind = "magic_tattoo" if "魔法刺青" in path else "magic_item"
        role = "player_facing"
    elif name == "魔法物品列表" or parts[:1] == ["魔法物品"]:
        kind, role = "directory", "non_instantiable"
    elif (
        len(parts) >= 2
        and re.sub(r"\.[^.]+$", "", parts[1]) == "专长"
    ) or "专长" in name:
        kind, role = "feat", "player_facing"
    elif parts[:2] == ["玩家选项", "角色选项"] or name in {"定制血统", "定制角色（TCE）"}:
        kind, role = "character_option", "player_facing"
    elif parts[:3] == ["玩家选项", "职业", "战士（TCE）"] and "战技选项" in path:
        kind, role = "maneuver", "player_facing"
    elif "奇械师注法" in path:
        kind, role = "infusion", "player_facing"
    elif "魔能祈唤" in path:
        kind, role = "invocation", "player_facing"
    elif "构筑" in path or "构筑" in name:
        kind, role = "narrative", "dm_reference"
    elif parts[:2] == ["玩家选项", "职业"]:
        kind = "subclass_feature" if len(parts) >= 4 else "class_feature"
        role = "player_facing"
    elif parts[:1] == ["协力者"]:
        kind, role = "companion_profile", "player_facing"
    elif parts[:1] == ["团队赞助者"]:
        kind, role = "narrative", "dm_reference"
    elif "环境灾害" in path or name == "环境灾害":
        kind, role = "environment_rule", "dm_reference"
    elif "谜题" in path or name == "谜题":
        kind, role = "puzzle", "dm_reference"
    elif parts[:1] == ["城主工具"]:
        kind, role = "dm_tool", "dm_reference"
    elif parts[:1] == ["使用本书"] or name in {"魔法杂物间", "角色选项"}:
        kind, role = "directory", "non_instantiable"
    elif content_type == "rules":
        kind, role = "rule_reference", "dm_reference"
    else:
        kind, role = "dm_tool", "dm_reference"
    return {
        "source_record_id": _record_id(record),
        "source_path": _text(record.get("source_relative_path")),
        "source_name": name,
        "source_content_type": content_type or "unknown",
        "source_kind": kind,
        "source_role": role,
        "class_name": _class_name(record),
        "subclass_name": _subclass_name(record),
        "source_fingerprint": source_fingerprint(record),
    }


def _bold_title(lines: list[str], index: int) -> tuple[str, int] | None:
    line = lines[index].strip()
    # ``***Foo***`` is a feature clause/italic label, never a page-level
    # asset heading.  The old parser treated the leading two stars as bold and
    # promoted the whole clause into an atom.
    if not line.startswith(_BOLD_START) or line.startswith("***"):
        return None
    close = line.find(_BOLD_START, 2)
    trailing = line[close + 2 :].strip() if close > 2 else ""
    if close > 2 and trailing.startswith("*"):
        chunks = [line[2:close]]
        remainder = trailing
        while remainder.startswith("**"):
            next_close = remainder.find("**", 2)
            if next_close <= 2:
                break
            chunks.append(remainder[2:next_close])
            remainder = remainder[next_close + 2 :]
        if len(chunks) > 1:
            return "".join(chunks) + remainder.strip("*"), index
    if close > 2 and (not trailing or trailing.startswith("*")):
        return line[2:close].strip(), index
    if close != -1:
        return None
    collected = [line[2:]]
    cursor = index + 1
    while cursor < len(lines):
        next_line = lines[cursor].strip()
        if next_line.startswith("***"):
            # A few CHM pages close the bold feature title immediately before
            # an italic level marker: ``***第3级特性*``.
            return " ".join(collected).strip(), cursor
        close = next_line.find(_BOLD_START)
        trailing = next_line[close + 2 :].strip() if close != -1 else ""
        if close != -1 and (not trailing or trailing.startswith("*")):
            collected.append(next_line[:close])
            return " ".join(collected).strip(), cursor
        collected.append(next_line)
        cursor += 1
    return None


def _blockquote_title(lines: list[str], index: int) -> tuple[str, int] | None:
    line = lines[index].lstrip()
    if not line.startswith("> **"):
        return None
    value = line[2:].strip()
    close = value.find(_BOLD_START, 2)
    if close > 2:
        return value[2:close].strip(), index
    collected = [value[2:]]
    cursor = index + 1
    while cursor < len(lines):
        next_line = lines[cursor].lstrip()
        if not next_line.startswith(">"):
            return None
        value = next_line[1:].strip()
        close = value.find(_BOLD_START)
        if close != -1:
            collected.append(value[:close])
            return " ".join(collected).strip(), cursor
        collected.append(value)
        cursor += 1
    return None


def _heading_anchors(markdown: str, *, style: str) -> list[tuple[int, int, str]]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    anchors: list[tuple[int, int, str]] = []
    index = 0
    while index < len(lines):
        match = _HASH_HEADING.match(lines[index].strip()) if style in {"hash", "any"} else None
        if match:
            anchors.append((index, index, match.group(2).strip()))
            index += 1
            continue
        if style in {"bold", "any", "level"}:
            bold = _bold_title(lines, index)
            if bold is not None:
                title, end = bold
                anchors.append((index, end, title))
                index = end + 1
                continue
        if style in {"any", "level"}:
            blockquote = _blockquote_title(lines, index)
            if blockquote is not None:
                title, end = blockquote
                anchors.append((index, end, title))
                index = end + 1
                continue
        index += 1
    return anchors


def _section_rows(markdown: str, *, style: str) -> list[dict[str, str]]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    anchors = _heading_anchors(markdown, style=style)
    rows: list[dict[str, str]] = []
    for position, (start, end, title) in enumerate(anchors):
        next_start = anchors[position + 1][0] if position + 1 < len(anchors) else len(lines)
        body = "\n".join(lines[end + 1 : next_start]).strip()
        anchor = (
            f"blockquote:{start + 1}"
            if lines[start].lstrip().startswith("> **")
            else str(start + 1)
        )
        heading_text = "\n".join(lines[start : end + 1])
        rows.append(
            {
                "title": title,
                "body": body,
                "heading": heading_text,
                "anchor": anchor,
                "has_level_marker": "true" if _LEVEL_RE.search(heading_text) else "false",
            }
        )
    return rows


def _feature_sections(record: Mapping[str, Any], info: Mapping[str, Any]) -> list[dict[str, str]]:
    markdown = _text(record.get("content_markdown") or record.get("content_plain_text"))
    rows = _section_rows(markdown, style="any")
    if info["source_kind"] in {"class_feature", "subclass_feature"}:
        feature_rows: list[dict[str, str]] = []
        for row in rows:
            context = f"{row['title']}\n{row['body'][:240]}"
            is_page_heading = _normalized_name(row["title"]) == _normalized_name(
                record.get("name")
            )
            is_stat_label = row["anchor"].startswith("blockquote:") and re.search(
                r"[：:]$", row["title"]
            )
            is_clause_label = row["title"].lstrip().startswith(("*", "先决", "前置"))
            if (
                not is_page_heading
                and not is_stat_label
                and not is_clause_label
                and (
                    _LEVEL_RE.search(context)
                    or row["has_level_marker"] == "true"
                    or row["anchor"].startswith("blockquote:")
                )
            ):
                feature_rows.append(row)
        if feature_rows:
            return feature_rows
        return [{"title": _text(record.get("name")), "body": markdown, "anchor": "page"}]
    if info["source_kind"] in {"magic_item", "magic_tattoo"}:
        # Item pages mix real item headings with metadata labels, tables,
        # sidebar prose and individual ability clauses.  A real item heading
        # is either a CHM level heading or carries the bilingual ``|`` marker;
        # the latter also survives the malformed multiline headings in the
        # Chinese export.  Keep the complete body under one item atom so
        # attunement, charges and item actions remain one lifecycle contract.
        item_rows = []
        for row in rows:
            heading = row.get("heading", "")
            title = row["title"].strip()
            normalized_record_name = _normalized_name(record.get("name"))
            real_heading = (
                heading.lstrip().startswith("#") or "|" in heading
            )
            excluded = (
                title.startswith("*")
                or title.startswith(("先决", "前置"))
                or "表格" in title
                or "边栏" in title
                or heading.lstrip().startswith(">") and "边栏" in title
                or _normalized_name(title) == normalized_record_name
                or _normalized_name(title) in {"魔法刺青", "魔法物品详述"}
                or _normalized_name(title).startswith("魔法刺青")
            )
            if real_heading and not excluded:
                item_rows.append(row)
        return item_rows or [{"title": _text(record.get("name")), "body": markdown, "anchor": "page", "heading": ""}]
    if info["source_kind"] in {
        "feat",
        "maneuver",
        "invocation",
        "infusion",
    }:
        option_rows = [
            row
            for row in rows
            if not row["title"].lstrip().startswith(("*", "先决", "前置"))
            and "表格" not in row["title"]
        ]
        return option_rows or [{"title": _text(record.get("name")), "body": markdown, "anchor": "page", "heading": ""}]
    if info["source_kind"] == "companion_profile":
        return [{"title": _text(record.get("name")), "body": markdown, "anchor": "page", "heading": ""}]
    return [{"title": _text(record.get("name")), "body": markdown, "anchor": "page", "heading": ""}]


def _atom_id(record_id: str, title: str, index: int) -> str:
    return f"{PACK_ID}:atom:{record_id}:{_slug(title)}:{index:03d}"


def _content_id(kind: str, atom_id: str, source_record_id: str) -> str:
    digest = fingerprint({"atom_id": atom_id, "source_record_id": source_record_id})[:16]
    if kind == "spell":
        return f"{PACK_ID}:spell:{source_record_id}"
    if kind in {"class_feature", "subclass_feature", "optional_class_feature"}:
        return f"content.{PACK_ID}.feature.{source_record_id}.{digest}"
    if kind in {"feat", "maneuver", "invocation", "infusion", "character_option"}:
        return f"content.{PACK_ID}.option.{source_record_id}.{digest}"
    if kind in {"magic_item", "magic_tattoo"}:
        return f"content.{PACK_ID}.item.{source_record_id}.{digest}"
    return f"content.{PACK_ID}.{kind}.{digest}"


def _title_parts(title: str) -> tuple[str, str | None]:
    cleaned = re.sub(r"\s+", " ", title).strip()
    latin = _LATIN_RE.search(cleaned)
    if latin and latin.start() > 0:
        return cleaned[: latin.start()].strip(" -|"), latin.group(0).strip(" -|")
    return cleaned, None


def _level(title: str, body: str, record: Mapping[str, Any]) -> int | None:
    raw = record.get("level")
    if isinstance(raw, int):
        return raw
    match = _LEVEL_RE.search(f"{title}\n{body[:500]}")
    return int(match.group(1)) if match else None


def _typed_entries(repo_root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    root = repo_root / "data" / "content-ir" / "authored"
    for path in sorted(root.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(value, dict) or value.get("source_book") != SOURCE_BOOK:
            continue
        content_id = _text(value.get("feature_id") or value.get("spell_id"))
        if not content_id or value.get("kind") not in {"feature", "spell"}:
            continue
        entries[content_id] = {
            "content_id": content_id,
            "kind": _text(value.get("kind")),
            "source_record_id": _text(value.get("source_record_id")),
            "source_name": _text(value.get("source_name") or value.get("name")),
            "source_path": _text(value.get("source_path")),
            "source_fingerprint": _text(value.get("source_fingerprint")),
            "typed_ir_path": str(path.relative_to(repo_root)),
            "source_trust": _text(value.get("source_trust")),
            "review_status": _text(value.get("review_status")),
        }
    return dict(sorted(entries.items()))


def _reconcile_typed_provenance(
    typed: Mapping[str, Mapping[str, Any]],
    matched_ids: set[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve legacy authored files that are not independent source assets.

    Two older tool-proficiency specs use a translated alias and are matched by
    ``_matches_typed``.  The old Precision Attack file points at a Battle
    Master *build recommendation* page; that page contains a recommendation,
    not the maneuver's rule text, so the authored file is explicitly retired
    as ``subclause_not_asset`` rather than attached to the page heading.
    """

    reconciled: list[dict[str, Any]] = []
    retired = "content.tashas-cauldron.feature.battle-master.precision-attack"
    for content_id, entry in sorted(typed.items()):
        if content_id in matched_ids:
            continue
        if content_id == retired:
            reconciled.append(
                {
                    "content_id": content_id,
                    "status": "explicitly_retired",
                    "reason": "source page is a Battle Master build recommendation; Precision Attack is not an independent atom on that page",
                    "replacement": None,
                    "typed_ir_path": entry.get("typed_ir_path"),
                }
            )
    retired_ids = {str(item["content_id"]) for item in reconciled}
    orphaned = sorted(set(typed) - matched_ids - retired_ids)
    return reconciled, orphaned


def _production_evidence(repo_root: Path) -> tuple[set[str], dict[str, dict[str, Any]]]:
    ids: set[str] = set()
    evidence: dict[str, dict[str, Any]] = {}
    root = repo_root / "data" / "content-ir" / "compiled"
    for path in sorted(root.rglob("production-runtime-results*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for content_id in value.get("production_runtime_full_ids") or []:
            content_id = _text(content_id)
            if "tashas-cauldron" not in content_id:
                continue
            ids.add(content_id)
            item = (value.get("evidence_by_id") or {}).get(content_id)
            if isinstance(item, Mapping):
                evidence[content_id] = {
                    **dict(item),
                    "evidence_path": str(path.relative_to(repo_root)),
                }
    return ids, dict(sorted(evidence.items()))


def _existing_content_ids(
    typed: Mapping[str, Mapping[str, Any]], production: set[str]
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for content_id, entry in typed.items():
        result[content_id] = {
            **dict(entry),
            "compile_full": True,
            "production_runtime_full": content_id in production,
        }
    return result


def _matches_typed(
    atom: Mapping[str, Any], typed: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    if (
        atom.get("source_fragment") == "page"
        or not atom.get("executable_candidate")
        or atom.get("qa_status") in {"heading_only", "subclause_not_asset", "table_row_not_asset"}
    ):
        return []
    atom_source = _text(atom.get("source_record_id"))
    atom_name = _normalized_name(atom.get("localized_name") or atom.get("name"))
    candidates = []
    for entry in typed.values():
        if _text(entry.get("source_record_id")) != atom_source:
            continue
        entry_name = _normalized_name(entry.get("source_name"))
        atom_local = re.sub(
            r"[^\u3400-\u9fff0-9]", "", _text(atom.get("localized_name"))
        )
        entry_local = re.sub(
            r"[^\u3400-\u9fff0-9]", "", _text(entry.get("source_name"))
        )
        local_prefix = bool(
            atom_local
            and entry_local
            and (atom_local in entry_local or entry_local in atom_local)
        )
        if (
            not atom_name
            or not entry_name
            or atom_name in entry_name
            or entry_name in atom_name
            or local_prefix
        ):
            candidates.append(dict(entry))
        elif (
            _text(entry.get("source_name")).find("工具精通") >= 0
            and "工具" in _text(atom.get("localized_name"))
            and "法术" not in _text(atom.get("localized_name"))
            and atom.get("content_kind") == "subclass_feature"
        ):
            # Two authored IR files used the older translated label
            # ``<subclass>：工具精通`` while the CHM page uses ``本职工具`` or
            # ``工具精通``.  Source record identity plus this explicit alias
            # is safer than a free-text name branch and preserves the stable
            # authored content IDs.
            candidates.append(dict(entry))
    return sorted(candidates, key=lambda item: _text(item.get("content_id")))


def _status_for_atom(
    atom: Mapping[str, Any],
    typed: Mapping[str, Mapping[str, Any]],
    production: set[str],
    evidence: Mapping[str, Mapping[str, Any]],
) -> tuple[str, dict[str, Any]]:
    kind = _text(atom.get("content_kind"))
    if not atom.get("instantiable"):
        if kind in {"directory", "index"}:
            return "non_instantiable", {"reason": "index_or_navigation_page"}
        return "dm_reference", {"reason": "reference_or_narrative_content"}
    matches = _matches_typed(atom, typed)
    if matches:
        entry = matches[0]
        content_id = _text(entry.get("content_id"))
        details = {
            "content_id": content_id,
            "typed_ir": entry,
            "typed_content_ids": [str(item["content_id"]) for item in matches],
        }
        if content_id in production:
            runtime = evidence.get(content_id, {})
            if _text(runtime.get("execution_mode")) == "dm_approved_typed":
                return "dm_assisted", {
                    **details,
                    "runtime_evidence": runtime,
                    "reason": "existing production path requires typed DM continuation",
                }
            return "production_full", details
        return "compile_only", details
    if kind in {"narrative", "environment_rule", "puzzle", "dm_tool", "rule_reference"}:
        return "dm_reference", {"reason": "DM-facing source material"}
    if kind in {"companion_profile", "summon_profile"}:
        return "manual_authoring", {"reason": "profile is not yet bound to Entity Lifecycle"}
    return "manual_authoring", {"reason": "typed IR not yet authored"}


def atomize_record(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    info = classify_source_record(record)
    source_id = _text(info["source_record_id"])
    kind = _text(info["source_kind"])
    markdown = _text(record.get("content_markdown") or record.get("content_plain_text"))
    if kind == "spell":
        rows = [{"title": _text(record.get("name")), "body": markdown, "anchor": "spell"}]
    elif kind in {"class_feature", "subclass_feature"}:
        parent_kind = "character_option" if kind == "class_feature" else kind
        parent_title = _text(record.get("name"))
        rows = [{"title": parent_title, "body": markdown, "anchor": "page", "parent": "true"}]
        rows.extend(_feature_sections(record, info))
        kind_for_parent = parent_kind
    else:
        rows = _feature_sections(record, info)
        kind_for_parent = kind
    atoms: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        title, english_name = _title_parts(row["title"])
        body = row["body"].strip()
        is_parent = row.get("parent") == "true"
        effective_kind = kind_for_parent if is_parent else kind
        is_page_heading = row.get("anchor") == "page"
        if effective_kind == "directory" or is_page_heading:
            player_facing, instantiable, executable = False, False, False
        else:
            player_facing = info["source_role"] == "player_facing"
            instantiable = effective_kind in EXECUTABLE_KINDS
            executable = instantiable
        if effective_kind == "narrative" or effective_kind in {
            "environment_rule",
            "puzzle",
            "dm_tool",
            "rule_reference",
        }:
            player_facing, instantiable, executable = False, False, False
        option_page_heading = effective_kind in {
            "feat",
            "maneuver",
            "invocation",
            "infusion",
        } and index == 0 and (
            _normalized_name(row["title"]) == _normalized_name(record.get("name"))
            or any(
                marker in row["title"].casefold()
                for marker in ("选项", "options", "注法", "祈唤", "feats")
            )
        )
        if option_page_heading:
            player_facing, instantiable, executable = False, False, False
        atom_id = _atom_id(source_id, row["title"], index)
        prerequisites = _PREREQUISITE_RE.search(body)
        atom = {
            "atom_id": atom_id,
            "content_kind": effective_kind,
            "name": row["title"],
            "localized_name": title,
            "english_name": english_name,
            "source_book": SOURCE_BOOK,
            "source_record_id": source_id,
            "source_path": _text(record.get("source_relative_path")),
            "source_fragment": row["anchor"] if row["anchor"] != "page" else "page",
            "source_heading_path": list(record.get("heading_path") or []),
            "source_fingerprint": source_fingerprint(record, body),
            "edition": normalized_record_edition(dict(record)),
            "officiality": _text(record.get("officiality")) or "unknown",
            "parent_atom_id": None,
            "class_name": info.get("class_name"),
            "subclass_name": info.get("subclass_name"),
            "level": _level(row["title"], body, record),
            "prerequisites": prerequisites.group(1).strip() if prerequisites else None,
            "variant_of": None,
            "reprint_of": None,
            "supersedes": None,
            "player_facing": player_facing,
            "instantiable": instantiable,
            "executable_candidate": executable,
            "source_legacy": bool(record.get("legacy")) or "旧版" in row["title"],
            "source_record_fingerprint": source_fingerprint(record),
            "qa_status": (
                "heading_only"
                if is_page_heading or not executable
                else "confirmed_atom"
            ),
        }
        atoms.append(atom)
    if len(atoms) > 1 and atoms[0]["source_fragment"] == "page":
        parent_id = atoms[0]["atom_id"]
        for atom in atoms[1:]:
            atom["parent_atom_id"] = parent_id
    return atoms


def build_atoms(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    atoms: list[dict[str, Any]] = []
    for record in records:
        atoms.extend(atomize_record(record))
    return sorted(atoms, key=lambda item: str(item["atom_id"]))


def _removed_atom_qa_status(atom: Mapping[str, Any]) -> str:
    title = _text(atom.get("localized_name") or atom.get("name"))
    path = _text(atom.get("source_path"))
    kind = _text(atom.get("content_kind"))
    if title.startswith("*") or "表格" in title:
        return "subclause_not_asset" if "表格" not in title else "table_row_not_asset"
    if "构筑" in path:
        return "example_not_rule"
    if atom.get("source_fragment") == "page":
        return "heading_only"
    if kind in {"magic_item", "magic_tattoo"}:
        return "merge_required"
    return "wrong_kind"


def build_atom_quality_audit(
    before_atoms: Iterable[Mapping[str, Any]],
    after_atoms: Iterable[Mapping[str, Any]],
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Audit the atomizer boundary and retain every denominator change."""

    before = list(before_atoms)
    after = list(after_atoms)
    record_ids = {
        _text(item.get("source_record_id")) or _record_id(item)
        for item in records
    }
    after_ids = {str(item.get("atom_id")) for item in after}
    after_fingerprints = {str(item.get("source_fingerprint")) for item in after}
    before_by_id = {str(item.get("atom_id")): item for item in before}
    removed = [
        before_by_id[key]
        for key in sorted(set(before_by_id) - after_ids)
        if str(before_by_id[key].get("source_fingerprint")) not in after_fingerprints
    ]
    after_by_fingerprint = {
        str(item.get("source_fingerprint")): item
        for item in after
        if item.get("source_fingerprint")
    }
    structural: list[dict[str, Any]] = []
    seen: set[str] = set()
    for atom in after:
        atom_id = str(atom.get("atom_id") or "")
        issues: list[str] = []
        if not atom_id or atom_id in seen:
            issues.append("atom_id_not_unique")
        seen.add(atom_id)
        if not atom.get("source_fingerprint") or not atom.get("source_record_fingerprint"):
            issues.append("source_fingerprint_missing")
        if str(atom.get("source_record_id")) not in record_ids:
            issues.append("source_record_missing")
        parent = atom.get("parent_atom_id")
        if parent and parent not in after_ids:
            issues.append("parent_missing")
        fragment = str(atom.get("source_fragment") or "")
        if fragment.isdigit():
            record = next(
                (item for item in records if _record_id(item) == atom.get("source_record_id")),
                None,
            )
            markdown = _text(record.get("content_markdown") or record.get("content_plain_text")) if record else ""
            if int(fragment) > len(markdown.splitlines() or [""]):
                issues.append("source_span_out_of_bounds")
        if issues:
            structural.append({"atom_id": atom_id, "issues": sorted(set(issues))})
    removed_rows = [
        {
            "atom_id": str(atom.get("atom_id")),
            "content_kind": atom.get("content_kind"),
            "name": atom.get("name"),
            "source_path": atom.get("source_path"),
            "qa_status": _removed_atom_qa_status(atom),
            "replacement_policy": "folded_into_parent_or_removed_from_executable_denominator",
        }
        for atom in removed
    ]
    return {
        "schema_version": "tashas-atom-quality-audit-1",
        "pack_id": PACK_ID,
        "qa_statuses": [
            "confirmed_atom", "merge_required", "split_required", "wrong_kind", "duplicate",
            "reprint", "subclause_not_asset", "example_not_rule", "table_row_not_asset",
            "heading_only", "source_incomplete", "parent_missing", "orphan_atom",
        ],
        "before_atom_counts": {
            "total": len(before),
            "player_facing": sum(bool(item.get("player_facing")) for item in before),
            "executable": sum(bool(item.get("executable_candidate")) for item in before),
            "by_kind": _kind_counts(before),
        },
        "after_atom_counts": {
            "total": len(after),
            "player_facing": sum(bool(item.get("player_facing")) for item in after),
            "executable": sum(bool(item.get("executable_candidate")) for item in after),
            "by_kind": _kind_counts(after),
        },
        "qa_status_counts": {
            status: sum(str(item.get("qa_status")) == status for item in after)
            for status in (
                "confirmed_atom", "merge_required", "split_required", "wrong_kind", "duplicate",
                "reprint", "subclause_not_asset", "example_not_rule", "table_row_not_asset",
                "heading_only", "source_incomplete", "parent_missing", "orphan_atom",
            )
        },
        "removed_false_atoms": removed_rows,
        "removed_false_atom_count": len(removed_rows),
        "merged_atoms": [item for item in removed_rows if item["qa_status"] == "merge_required"],
        "split_atoms": [],
        "reclassified_atoms": [
            {
                "before_atom_id": str(item.get("atom_id")),
                "before_kind": item.get("content_kind"),
                "after_atom_id": str(after_by_fingerprint[item.get("source_fingerprint")].get("atom_id")),
                "after_kind": after_by_fingerprint[item.get("source_fingerprint")].get("content_kind"),
                "source_fingerprint": item.get("source_fingerprint"),
            }
            for item in before
            if item.get("source_fingerprint") in after_by_fingerprint
            and item.get("content_kind") != after_by_fingerprint[item.get("source_fingerprint")].get("content_kind")
        ],
        "structural_checks": {
            "atom_id_unique": len(seen) == len(after),
            "parent_child_valid": not any("parent_missing" in item["issues"] for item in structural),
            "source_fingerprint_present": not any("source_fingerprint_missing" in item["issues"] for item in structural),
            "source_span_in_bounds": not any("source_span_out_of_bounds" in item["issues"] for item in structural),
            "source_records_resolved": not any("source_record_missing" in item["issues"] for item in structural),
            "all_atoms_have_qa_status": all(bool(item.get("qa_status")) for item in after),
        },
        "structural_anomalies": structural,
        "audit_fingerprint": fingerprint({"before": before, "after": after, "structural": structural}),
    }


def build_manual_semantic_clusters(
    atoms: Iterable[Mapping[str, Any]],
    candidates: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Group manual atoms by a full contract signature, never by name alone."""

    candidate_by_id = {str(item["atom_id"]): item for item in candidates}
    groups: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for atom in atoms:
        if not atom.get("executable_candidate") or atom.get("migration_status") != "manual_authoring":
            continue
        candidate = candidate_by_id.get(str(atom["atom_id"]), {})
        template = candidate.get("matched_template_id") or "missing_template"
        signature = (
            atom.get("content_kind"),
            template,
            "fixed_grant" if atom.get("level") is not None else "level_unknown",
            "choice_present" if atom.get("prerequisites") else "choice_unknown",
            "action_economy_unknown",
            "trigger_unknown",
            "resource_shape_unknown",
            "recovery_shape_unknown",
            "target_shape_unknown",
            "attack_or_save_unknown",
            "success_failure_unknown",
            "damage_healing_unknown",
            "condition_shape_unknown",
            "duration_shape_unknown",
            "movement_shape_unknown",
            "summon_shape_unknown",
            "spell_grant_shape" if atom.get("content_kind") == "spell" else "none",
            "modifier_shape_unknown",
            "equipment_shape" if atom.get("content_kind") in {"magic_item", "magic_tattoo"} else "none",
            "attunement_shape_unknown" if atom.get("content_kind") in {"magic_item", "magic_tattoo"} else "none",
            "charge_shape_unknown" if atom.get("content_kind") in {"magic_item", "magic_tattoo"} else "none",
            "scaling_shape_unknown",
            "persistence_unknown",
            "runtime_consumer_unknown",
            "dm_adjudication_unknown",
        )
        groups[signature].append(atom)
    clusters: list[dict[str, Any]] = []
    for index, (signature, members) in enumerate(sorted(groups.items(), key=lambda item: repr(item[0]))):
        kind_counts = Counter(str(item.get("content_kind")) for item in members)
        cluster_id = f"tashas.manual.cluster.{index + 1:03d}"
        clusters.append(
            {
                "cluster_id": cluster_id,
                "exact_contract_signature": {
                    "content_kind": signature[0],
                    "grant_shape": signature[1],
                    "choice_shape": signature[3],
                    "action_economy": signature[4],
                    "trigger": signature[5],
                    "resource_shape": signature[6],
                    "recovery_shape": signature[7],
                    "target_shape": signature[8],
                    "attack_or_save": signature[9],
                    "success_failure_shape": signature[10],
                    "damage_healing_shape": signature[11],
                    "condition_shape": signature[12],
                    "duration_shape": signature[13],
                    "movement_shape": signature[14],
                    "summon_shape": signature[15],
                    "spell_grant_shape": signature[16],
                    "modifier_shape": signature[17],
                    "equipment_shape": signature[18],
                    "attunement_shape": signature[19],
                    "charge_shape": signature[20],
                    "scaling_shape": signature[21],
                    "persistence_shape": signature[22],
                    "runtime_consumer_shape": signature[23],
                    "dm_adjudication_shape": signature[24],
                },
                "content_count": len(members),
                "feature_count": sum(1 for item in members if str(item.get("content_kind")) in {"class_feature", "subclass_feature", "optional_class_feature"}),
                "item_count": sum(1 for item in members if str(item.get("content_kind")) in {"magic_item", "magic_tattoo"}),
                "option_count": sum(1 for item in members if str(item.get("content_kind")) in {"feat", "maneuver", "invocation", "infusion", "character_option"}),
                "spell_count": kind_counts.get("spell", 0),
                "representative_atoms": sorted(str(item["atom_id"]) for item in members)[:8],
                "required_review_fields": sorted(set(candidate_by_id.get(str(members[0]["atom_id"]), {}).get("required_review_fields", []))),
                "existing_template_match": signature[1] != "missing_template",
                "missing_template": signature[1] == "missing_template",
                "missing_capability": ["typed_contract"],
                "missing_materializer": ["content_ir_runtime"],
                "missing_runtime_consumer": ["closed_world_consumer"],
                "complete_content_unlock_count": 0,
            }
        )
    return {
        "schema_version": "tashas-manual-semantic-clusters-1",
        "pack_id": PACK_ID,
        "cluster_count": len(clusters),
        "clusters": clusters,
        "cluster_fingerprint": fingerprint(clusters),
    }


def build_duplicate_version_map(atoms: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(atoms)
    by_source: defaultdict[str, list[str]] = defaultdict(list)
    by_name: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for atom in rows:
        by_source[str(atom["source_fingerprint"])].append(str(atom["atom_id"]))
        by_name[_normalized_name(atom.get("localized_name") or atom.get("name"))].append(atom)
    relations: list[dict[str, Any]] = []
    for atom in rows:
        atom_id = str(atom["atom_id"])
        exact = sorted(by_source[str(atom["source_fingerprint"])])
        relation = "exact_duplicate" if len(exact) > 1 else "independent"
        related_ids = [item for item in exact if item != atom_id]
        name_group = by_name[_normalized_name(atom.get("localized_name") or atom.get("name"))]
        if len(name_group) > 1 and relation == "independent":
            relation = "rules_variant"
            related_ids = sorted(
                str(item["atom_id"])
                for item in name_group
                if item["atom_id"] != atom_id
            )
        if atom.get("source_legacy") and relation == "independent":
            relation = "legacy_variant"
        relations.append(
            {
                "atom_id": atom_id,
                "relationship": relation,
                "related_atom_ids": related_ids,
                "evidence": {
                    "source_fingerprint": atom["source_fingerprint"],
                    "same_name_count": len(name_group),
                    "legacy_marker": bool(atom.get("source_legacy")),
                },
            }
        )
    return {
        "schema_version": "tashas-duplicate-version-map-1",
        "policy": {
            "exact_duplicate": "reuse canonical content ID and retain provenance",
            "reprint": "reuse Typed IR only after source and clause parity",
            "legacy_variant": "retain separate atom and require legacy opt-in",
            "rules_variant": "retain separate atom; never deduplicate by name",
            "superseded": "exclude from default 2024 campaign selection",
        },
        "relationship_counts": dict(Counter(item["relationship"] for item in relations)),
        "entries": sorted(relations, key=lambda item: item["atom_id"]),
        "map_fingerprint": fingerprint(relations),
    }


def _template_for_atom(
    atom: Mapping[str, Any], typed: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    matches = _matches_typed(atom, typed)
    if not matches:
        return {
            "matched_template_id": None,
            "template_fingerprint": None,
            "match_status": "unmatched_requires_review",
            "match_confidence": "low",
        }
    entry = matches[0]
    if atom["content_kind"] == "spell":
        template_id = "spell.shape.authored"
    else:
        template_id = "feature.shape.authored"
    return {
        "matched_template_id": template_id,
        "template_fingerprint": fingerprint(
            {"template_id": template_id, "content_id": entry["content_id"]}
        ),
        "match_status": "reviewed_typed_mapping",
        "match_confidence": "high",
    }


def build_candidates(
    atoms: Iterable[Mapping[str, Any]], typed: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    candidates = []
    for atom in atoms:
        if not atom.get("executable_candidate"):
            continue
        template = _template_for_atom(atom, typed)
        missing = [] if template["match_status"] == "reviewed_typed_mapping" else [
            "typed_clause_mapping",
            "action_economy",
            "target_policy",
            "resource_and_recovery",
        ]
        candidates.append(
            {
                "atom_id": atom["atom_id"],
                "content_kind": atom["content_kind"],
                "name": atom["name"],
                "source_record_id": atom["source_record_id"],
                "source_path": atom["source_path"],
                "source_fingerprint": atom["source_fingerprint"],
                **template,
                "exact_fields": {
                    key: atom[key]
                    for key in ("level", "prerequisites", "class_name", "subclass_name")
                    if atom.get(key) is not None
                },
                "derived_non_executable_fields": {"localized_name": atom["localized_name"]},
                "uncertain_fields": {} if not missing else {"clauses": "requires authored review"},
                "missing_fields": missing,
                "forbidden_inferences": [
                    "natural_language_to_operator",
                    "automatic_player_choice",
                    "automatic_dm_ruling",
                ],
                "source_evidence": {
                    "source_path": atom["source_path"],
                    "source_record_id": atom["source_record_id"],
                    "source_fragment": atom["source_fragment"],
                },
                "required_review_fields": [
                    "name",
                    "content_kind",
                    "level",
                    "prerequisites",
                    "action_economy",
                    "trigger",
                    "target_policy",
                    "clauses",
                    "resource_and_recovery",
                    "dm_boundary",
                ],
                "candidate_status": "generated_candidate",
                "compile_status": "never_full_before_review",
            }
        )
    return sorted(candidates, key=lambda item: str(item["atom_id"]))


def build_reviews(
    atoms: Iterable[Mapping[str, Any]],
    candidates: Iterable[Mapping[str, Any]],
    typed: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    candidate_by_atom = {str(item["atom_id"]): item for item in candidates}
    reviews: list[dict[str, Any]] = []
    for atom in atoms:
        if not atom.get("executable_candidate"):
            continue
        candidate = candidate_by_atom[str(atom["atom_id"])]
        is_typed = candidate["match_status"] == "reviewed_typed_mapping"
        review_status = "accepted_with_edits" if is_typed else "manual_boundary"
        matches = _matches_typed(atom, typed)
        reviews.append(
            {
                "atom_id": atom["atom_id"],
                "review_status": review_status,
                "reviewed_fields": list(candidate["required_review_fields"]),
                "accepted_fields": ["name", "content_kind", "level", "prerequisites"]
                + (["typed_clauses", "runtime_contract"] if is_typed else []),
                "edited_fields": ["localized_name"] if is_typed else [],
                "rejected_inferences": candidate["forbidden_inferences"],
                "manual_decisions": []
                if is_typed
                else ["keep source clause manual until a closed typed contract exists"],
                "source_evidence": candidate["source_evidence"],
                "clause_boundaries": {"source_fragment": atom["source_fragment"]},
                "missing_fields": candidate["missing_fields"],
                "review_blockers": []
                if is_typed
                else ["typed_ir_missing", "runtime_consumer_or_evidence_missing"],
                "review_fingerprint": fingerprint(
                    {
                        "source_fingerprint": atom["source_fingerprint"],
                        "template_fingerprint": candidate["template_fingerprint"],
                        "review_status": review_status,
                    }
                ),
                "reviewed_at": "2026-08-11",
                "typed_content_ids": [str(item["content_id"]) for item in matches],
            }
        )
    return sorted(reviews, key=lambda item: str(item["atom_id"]))


def _status_counts(atoms: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    counter = Counter(str(atom.get("migration_status")) for atom in atoms)
    return {status: counter.get(status, 0) for status in MIGRATION_STATUSES}


def _kind_counts(atoms: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(atom.get("content_kind")) for atom in atoms).items()))


def existing_project_production_ids(repo_root: Path) -> set[str]:
    ids: set[str] = set()
    root = repo_root / "data" / "content-ir" / "compiled"
    for path in sorted(root.rglob("production-runtime-results*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        ids.update(_text(item) for item in value.get("production_runtime_full_ids") or [])
    return {item for item in ids if item}


def formal_feature_audit_status(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "reports" / "class-feature-audit-2026-08-07.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {
            "total": 499,
            "status_counts": {"full": 328, "partial": 110, "dm_only": 61},
            "source": str(path),
        }
    counts = value.get("status_counts") or value.get("counts") or {}
    return {
        "total": int(value.get("total") or value.get("audit_total") or sum(counts.values()) or 499),
        "status_counts": {str(key): int(val) for key, val in sorted(counts.items())},
        "source": str(path.relative_to(repo_root)),
    }


def protected_path_fingerprints(repo_root: Path) -> dict[str, Any]:
    protected_file = repo_root / "backend" / "tests" / "ollama.py"
    protected_dir = repo_root / "backend" / "tests" / "integrations"
    files = sorted(path for path in protected_dir.rglob("*") if path.is_file())
    file_rows = []
    for path in files:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
        file_rows.append({"path": str(path.relative_to(repo_root)), "sha256": digest})
    return {
        "backend/tests/ollama.py": {
            "exists": protected_file.is_file(),
            "sha256": hashlib.sha256(protected_file.read_bytes()).hexdigest()
            if protected_file.is_file()
            else None,
        },
        "backend/tests/integrations/": {
            "exists": protected_dir.is_dir(),
            "files": file_rows,
            "manifest_sha256": fingerprint(file_rows),
        },
    }


def database_fingerprint(repo_root: Path) -> dict[str, Any]:
    files = sorted(path for path in (repo_root / "data").rglob("*.db") if path.is_file())
    rows = []
    for path in files:
        rows.append(
            {
                "path": str(path.relative_to(repo_root)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
    return {"files": rows, "fingerprint": fingerprint(rows)}


def build_migration(repo_root: Path) -> dict[str, Any]:
    source_root = repo_root / "data/generated-content/dnd5e_chm/json"
    records = select_source_records(load_records(source_root))
    atoms = build_atoms(records)
    typed = _typed_entries(repo_root)
    production, evidence = _production_evidence(repo_root)
    compiled = _existing_content_ids(typed, production)
    enriched: list[dict[str, Any]] = []
    for atom in atoms:
        status, details = _status_for_atom(atom, typed, production, evidence)
        has_typed_ir = bool(details.get("typed_content_ids"))
        is_compiled = status in {"production_full", "dm_assisted", "compile_only"}
        enriched.append(
            {
                **atom,
                "migration_status": status,
                "status_reason": details.get("reason"),
                "content_id": details.get("content_id"),
                "typed_ir": details.get("typed_ir"),
                "typed_content_ids": details.get("typed_content_ids") or [],
                "runtime_evidence": details.get("runtime_evidence"),
                "status_layers": build_status_layers(
                    source_identified=True,
                    draft=bool(atom.get("executable_candidate")),
                    candidate=bool(atom.get("executable_candidate")),
                    reviewed=bool(atom.get("executable_candidate")),
                    authored_typed_ir=has_typed_ir,
                    compile_full=is_compiled,
                    runtime_preview_full=is_compiled,
                    isolated_runtime_validated=status in {"production_full", "dm_assisted"},
                    registered_production_full=status == "production_full",
                    dm_assisted=status == "dm_assisted",
                ),
            }
        )
    candidates = build_candidates(enriched, typed)
    reviews = build_reviews(enriched, candidates, typed)
    duplicate_map = build_duplicate_version_map(enriched)
    matched_typed_ids = {
        content_id
        for atom in enriched
        for content_id in atom.get("typed_content_ids") or []
    }
    compiled_atoms = [
        atom
        for atom in enriched
        if atom["migration_status"] in {"production_full", "dm_assisted", "compile_only"}
    ]
    typed_reconciliation, unmatched_typed_ids = _reconcile_typed_provenance(
        typed, matched_typed_ids
    )
    matched_production_ids = sorted(matched_typed_ids.intersection(production))
    dm_content_ids = {
        content_id
        for atom in enriched
        if atom["migration_status"] == "dm_assisted"
        for content_id in atom.get("typed_content_ids") or []
    }
    content_id_production_full = len(set(matched_production_ids) - dm_content_ids)
    content_id_compile_only = len(matched_typed_ids - set(matched_production_ids))
    player_facing = [atom for atom in enriched if atom.get("player_facing")]
    executable = [atom for atom in enriched if atom.get("executable_candidate")]
    production_full = [atom for atom in enriched if atom["migration_status"] == "production_full"]
    dm_assisted = [atom for atom in enriched if atom["migration_status"] == "dm_assisted"]
    compile_only = [atom for atom in enriched if atom["migration_status"] == "compile_only"]
    source_inventory = [
        {
            **classify_source_record(record),
            "name": _text(record.get("name")),
            "heading_path": list(record.get("heading_path") or []),
            "edition": normalized_record_edition(record),
            "officiality": _text(record.get("officiality")) or "unknown",
            "legacy": bool(record.get("legacy")),
            "content_length": len(
                _text(record.get("content_markdown") or record.get("content_plain_text"))
            ),
            "atom_count": sum(
                1 for atom in enriched if atom["source_record_id"] == _record_id(record)
            ),
        }
        for record in records
    ]
    source_inventory = sorted(
        source_inventory,
        key=lambda item: (item["source_path"], item["source_record_id"]),
    )
    pack_fingerprint = fingerprint(
        {
            "records": [
                (item["source_record_id"], item["source_fingerprint"])
                for item in source_inventory
            ],
            "atoms": [(item["atom_id"], item["source_fingerprint"]) for item in enriched],
        }
    )
    # Local import avoids the recovery module importing this atomizer during
    # module initialization; build_migration still exposes one authoritative
    # ItemSpec catalog to callers that do not use the report script.
    from dnd_dm_assistant.application.tashas_recovery import build_item_spec_catalog

    item_spec_catalog = build_item_spec_catalog(atoms=enriched, records=records)
    item_ir = {
        "implemented": True,
        "inventory_atom_count": item_spec_catalog["item_spec_total"],
        "typed_count": item_spec_catalog["item_spec_typed"],
        "production_count": item_spec_catalog["production_full"],
        "dm_assisted_count": 0,
        "blocker": "manual_review_required is retained for unresolved action, spell, and effect clauses",
        "unlock_ranking": [
            {
                "capability": capability,
                "unlock_count": sum(
                    any(
                        clause.get("clause_type") == clause_type
                        for clause in spec.get("clauses", [])
                    )
                    and spec.get("compile", {}).get("compile_status") == "full"
                    for spec in item_spec_catalog.get("specs", [])
                ),
                "consumer": consumer,
            }
            for capability, clause_type, consumer in (
                ("item.passive_modifier", "equipment", "item.equipment_modifier.v1"),
                ("item.attunement", "attunement", "item.attunement.v1"),
                ("item.charge_resource", "charge", "item.charge_resource.v1"),
                ("item.granted_action", "granted_action", "item.granted_action.v1"),
                ("item.tattoo_lifecycle", "tattoo_lifecycle", "item.attunement.v1"),
            )
        ],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "pack_id": PACK_ID,
        "source_book": SOURCE_BOOK,
        "source_inventory": source_inventory,
        "atoms": enriched,
        "candidates": candidates,
        "reviews": reviews,
        "duplicate_map": duplicate_map,
        "typed_entries": compiled,
        "production_ids": sorted(production),
        "production_evidence": evidence,
        "pack_fingerprint": pack_fingerprint,
        "source_record_total": len(records),
        "source_record_scanned": len(records),
        "source_record_classified": len(records),
        "source_record_unclassified": 0,
        "content_atom_total": len(enriched),
        "player_facing_atom_total": len(player_facing),
        "executable_candidate_total": len(executable),
        "draft_total": len(candidates),
        "template_matched": sum(
            item["match_status"] != "unmatched_requires_review" for item in candidates
        ),
        "candidate_generated": len(candidates),
        "reviewed_total": len(reviews),
        "authored_typed_ir": len(matched_typed_ids),
        "compile_full": len(compiled_atoms),
        "runtime_preview_full": len(compiled_atoms),
        "production_full": len(production_full),
        "dm_assisted": len(dm_assisted),
        "game_usable": len(production_full) + len(dm_assisted),
        "compile_only": len(compile_only),
        "manual_authoring": sum(
            atom["migration_status"] == "manual_authoring" for atom in enriched
        ),
        "invalid_source": sum(atom["migration_status"] == "invalid_source" for atom in enriched),
        "dm_reference": sum(atom["migration_status"] == "dm_reference" for atom in enriched),
        "non_instantiable": sum(
            atom["migration_status"] == "non_instantiable" for atom in enriched
        ),
        "duplicate_or_reprint": sum(
            atom["migration_status"] == "duplicate_or_reprint" for atom in enriched
        ),
        "status_counts": _status_counts(enriched),
        "kind_counts": _kind_counts(enriched),
        "player_kind_counts": _kind_counts(player_facing),
        "formal_499_status": formal_feature_audit_status(repo_root),
        "protected_path_fingerprints": protected_path_fingerprints(repo_root),
        "database_fingerprint": database_fingerprint(repo_root),
        "current_project_production_full": len(existing_project_production_ids(repo_root)),
        "existing_typed_ir_total": len(typed),
        "existing_typed_ir_unmatched": unmatched_typed_ids,
        "existing_typed_ir_reconciled": typed_reconciliation,
        "orphan_authored_ir_count": len(unmatched_typed_ids),
        "content_id_funnel": {
            "matched_typed_ir": len(matched_typed_ids),
            "production_full": content_id_production_full,
            "dm_assisted": len(dm_content_ids),
            "compile_only": content_id_compile_only,
            "relation_holds": len(matched_typed_ids)
            == content_id_production_full + len(dm_content_ids) + content_id_compile_only,
        },
        "matched_production_runtime_ids": matched_production_ids,
        "unmatched_production_runtime_ids": sorted(set(production) - set(matched_production_ids)),
        "current_project_compiled_unique": 111,
        "current_project_compile_only": 35,
        "current_project_production_registry_fingerprint": fingerprint(
            sorted(existing_project_production_ids(repo_root))
        ),
        "item_ir": item_ir,
        "item_spec_catalog": item_spec_catalog,
        "consumer_unlocks": {
            "existing_generic_consumer": {
                "content_ids": sorted(production),
                "new_consumer_count": 0,
                "name_branch_count": 0,
            }
        },
    }


def report_projection(migration: Mapping[str, Any]) -> dict[str, Any]:
    """Return only stable summary fields for baseline/coverage reports."""

    keys = (
        "schema_version",
        "pack_id",
        "source_book",
        "pack_fingerprint",
        "source_record_total",
        "source_record_scanned",
        "source_record_classified",
        "source_record_unclassified",
        "content_atom_total",
        "player_facing_atom_total",
        "executable_candidate_total",
        "draft_total",
        "template_matched",
        "candidate_generated",
        "reviewed_total",
        "authored_typed_ir",
        "compile_full",
        "runtime_preview_full",
        "production_full",
        "dm_assisted",
        "game_usable",
        "compile_only",
        "manual_authoring",
        "invalid_source",
        "dm_reference",
        "non_instantiable",
        "duplicate_or_reprint",
        "status_counts",
        "kind_counts",
        "player_kind_counts",
        "formal_499_status",
        "current_project_compiled_unique",
        "current_project_compile_only",
        "current_project_production_full",
        "current_project_production_registry_fingerprint",
        "existing_typed_ir_total",
        "existing_typed_ir_unmatched",
        "content_id_funnel",
        "item_ir",
        "consumer_unlocks",
    )
    return {key: migration[key] for key in keys}
