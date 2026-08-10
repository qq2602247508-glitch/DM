"""Read-only Content IR workbench for official source-pack audits.

The workbench deliberately stops at typed drafts for unstructured source
material.  It never promotes prose or extracted fields to executable ``full``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.rule_metadata import spell_rule_fields

STATUS_VALUES = ("full", "partial", "manual", "invalid")
_INDEX_RE = re.compile(r"(目录|概述|索引|速查|列表|清单)")
_SPELL_CLAUSE_TYPES = frozenset(
    {
        "attack_roll",
        "damage",
        "healing",
        "saving_throw",
        "apply_condition",
        "area",
        "duration",
        "upcast",
    }
)


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_spell_detail(record: dict[str, Any]) -> bool:
    path = str(record.get("source_relative_path") or "")
    name = _text(record.get("name"))
    if "法术详述" not in path:
        return False
    if not name or _INDEX_RE.search(name):
        return False
    return len(_text(record.get("content_plain_text") or record.get("content_markdown"))) >= 80


def _is_feature_candidate(record: dict[str, Any]) -> bool:
    path = str(record.get("source_relative_path") or "")
    name = _text(record.get("name"))
    if "职业" not in path or not name or _INDEX_RE.search(name):
        return False
    return len(_text(record.get("content_plain_text") or record.get("content_markdown"))) >= 80


@dataclass(frozen=True)
class SpellDraft:
    spell_id: str
    name: str
    source_book: str
    source_path: str
    edition: str
    officiality: str
    fields: dict[str, Any]
    source_fingerprint: str
    status: str = "manual"
    blockers: tuple[str, ...] = ("unstructured_source_requires_authored_spell_ir",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "spell_draft",
            "spell_id": self.spell_id,
            "name": self.name,
            "source_book": self.source_book,
            "source_path": self.source_path,
            "edition": self.edition,
            "officiality": self.officiality,
            "fields": self.fields,
            "source_fingerprint": self.source_fingerprint,
            "status": self.status,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class SpellSpec:
    """Closed typed spell contract; prose drafts cannot instantiate this."""

    spell_id: str
    name: str
    level: int
    clauses: tuple[dict[str, Any], ...]
    source_trust: str = "authored_ir"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SpellSpec:
        required = ("spell_id", "name", "level", "clauses")
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError("missing required SpellSpec fields: " + ", ".join(missing))
        if not isinstance(value["spell_id"], str) or not value["spell_id"].strip():
            raise ValueError("spell_id must be a non-empty string")
        if not isinstance(value["name"], str) or not value["name"].strip():
            raise ValueError("name must be a non-empty string")
        if not isinstance(value["level"], int) or not 0 <= value["level"] <= 9:
            raise ValueError("level must be an integer from 0 to 9")
        if not isinstance(value["clauses"], list) or not value["clauses"]:
            raise ValueError("clauses must be a non-empty array")
        for index, clause in enumerate(value["clauses"]):
            if not isinstance(clause, dict) or not isinstance(clause.get("type"), str):
                raise ValueError(f"clauses[{index}] must contain a typed clause type")
        return cls(
            spell_id=value["spell_id"].strip(),
            name=value["name"].strip(),
            level=value["level"],
            clauses=tuple(value["clauses"]),
            source_trust=str(value.get("source_trust") or "authored_ir"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "spell",
            "spell_id": self.spell_id,
            "name": self.name,
            "level": self.level,
            "clauses": list(self.clauses),
            "source_trust": self.source_trust,
        }


def compile_spell_spec(spec: SpellSpec) -> dict[str, Any]:
    """Compile only closed typed clauses; unknown clauses fail closed."""

    unsupported = sorted(
        {
            str(clause.get("type") or "")
            for clause in spec.clauses
            if clause.get("type") not in _SPELL_CLAUSE_TYPES
        }
    )
    blockers: list[str] = []
    if spec.source_trust not in {"authored_ir", "verified_mapping"}:
        blockers.append("source_trust_not_verified")
    blockers.extend(f"unsupported_spell_clause:{item}" for item in unsupported)
    status = "full" if not blockers else "invalid" if unsupported else "partial"
    runtime_blocks = (
        tuple(
            {
                "kind": "spell_clause",
                "spell_id": spec.spell_id,
                "clause": clause,
            }
            for clause in spec.clauses
        )
        if status == "full"
        else ()
    )
    return {
        "spell_id": spec.spell_id,
        "compile_status": status,
        "typed_clause_count": len(spec.clauses),
        "capability_ids": [f"spell:{clause['type']}" for clause in spec.clauses]
        if status == "full"
        else [],
        "unsupported_clause_ids": unsupported,
        "blockers": blockers,
        "runtime_blocks": list(runtime_blocks),
        "fingerprint": _fingerprint(spec.to_dict()),
    }


@dataclass(frozen=True)
class WorkbenchReport:
    source_root: str
    source_book: str | None
    total_records: int
    feature_count: int
    spell_count: int
    feat_count: int
    draft_count: int
    typed_ir_count: int
    counts: dict[str, int]
    source_untyped: int
    capability_counts: dict[str, int]
    blocker_counts: dict[str, int]
    entries: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "content-ir-workbench-report-1",
            "source_root": self.source_root,
            "source_book": self.source_book,
            "total_records": self.total_records,
            "feature_count": self.feature_count,
            "spell_count": self.spell_count,
            "feat_count": self.feat_count,
            "draft_count": self.draft_count,
            "typed_ir_count": self.typed_ir_count,
            "counts": self.counts,
            "source_untyped": self.source_untyped,
            "capability_counts": self.capability_counts,
            "blocker_counts": self.blocker_counts,
            "entries": list(self.entries),
        }


def load_records(json_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(json_root.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def extract_spell_draft(record: dict[str, Any]) -> SpellDraft:
    stable_id = _text(record.get("stable_id")) or _fingerprint(
        {"name": record.get("name"), "path": record.get("source_relative_path")}
    )[:24]
    fields = {**dict(record.get("spell") or {}), **spell_rule_fields(record)}
    return SpellDraft(
        spell_id=stable_id,
        name=_text(record.get("name")),
        source_book=_text(record.get("source_book")),
        source_path=_text(record.get("source_relative_path")),
        edition=_text(record.get("edition")) or "unknown",
        officiality=_text(record.get("officiality")) or "unknown",
        fields=fields,
        source_fingerprint=_fingerprint(
            {
                "name": record.get("name"),
                "source_relative_path": record.get("source_relative_path"),
                "content_markdown": record.get("content_markdown"),
                "content_plain_text": record.get("content_plain_text"),
            }
        ),
    )


def audit_records(
    records: list[dict[str, Any]], *, source_book: str | None = None, include_entries: bool = True
) -> WorkbenchReport:
    selected = [
        record
        for record in records
        if source_book is None
        or record.get("source_book") == source_book
        or str(record.get("source_relative_path") or "").startswith(source_book + "/")
    ]
    entries: list[dict[str, Any]] = []
    blockers: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    features = spells = feats = drafts = typed = 0
    for record in selected:
        kind = str(record.get("content_type") or "")
        if kind == "spells" and _is_spell_detail(record):
            spells += 1
            draft = extract_spell_draft(record)
            drafts += 1
            status = "manual"
            counts[status] += 1
            for blocker in draft.blockers:
                blockers[blocker] += 1
            if include_entries:
                entries.append({**draft.to_dict(), "content_type": "spell"})
        elif kind in {"classes", "subclasses"} and _is_feature_candidate(record):
            features += 1
            drafts += 1
            counts["manual"] += 1
            blockers["unstructured_source_requires_authored_feature_ir"] += 1
            if include_entries:
                entries.append(
                    {
                        "kind": "feature_draft",
                        "name": _text(record.get("name")),
                        "source_book": _text(record.get("source_book")),
                        "source_path": _text(record.get("source_relative_path")),
                        "source_fingerprint": _fingerprint(record),
                        "status": "manual",
                        "blockers": ["unstructured_source_requires_authored_feature_ir"],
                    }
                )
        elif kind == "feats":
            feats += 1
    return WorkbenchReport(
        source_root="generated-content",
        source_book=source_book,
        total_records=len(selected),
        feature_count=features,
        spell_count=spells,
        feat_count=feats,
        draft_count=drafts,
        typed_ir_count=typed,
        counts={status: counts.get(status, 0) for status in STATUS_VALUES},
        source_untyped=sum(1 for e in entries if e.get("status") == "manual"),
        capability_counts={},
        blocker_counts=dict(sorted(blockers.items())),
        entries=tuple(entries),
    )


def write_report(report: WorkbenchReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
