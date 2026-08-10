"""Read-only unified Content IR workbench.

The workbench has two intentionally separate typed domains:

* ``FeatureDraft`` -> authored ``FeatureSpec`` -> the existing FeatureCompiler
* ``SpellDraft`` -> authored ``SpellSpec`` -> the independent SpellCompiler

Both domains share provenance, fingerprints, status, blocker, capability and
replay metadata.  Source prose is evidence only.  It is never promoted to an
executable ``full`` result by field extraction, officiality, or keyword hits.
All artifact writers in this module target a caller-provided isolated
directory; no production database, registry, campaign, or character state is
reachable from the scan/compile/dry-run path.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.feature_compiler import FeatureCompiler
from dnd_dm_assistant.application.rule_metadata import spell_rule_fields
from dnd_dm_assistant.domain.content_packs import (
    CONTENT_PACKS_BY_KEY,
    content_pack_for_record,
    is_spell_detail_record,
    list_content_packs,
)
from dnd_dm_assistant.domain.feature_ir import FeatureSpec

STATUS_VALUES = ("full", "partial", "manual", "invalid")
REPORT_SCHEMA_VERSION = "content-ir-workbench-report-2"
MANIFEST_SCHEMA_VERSION = "content-ir-workbench-manifest-2"
COMPILER_FINGERPRINT = hashlib.sha256(
    b"local-dnd-content-ir-compiler:feature-ir-1:spell-ir-1:2026-08-10"
).hexdigest()
CAPABILITY_REGISTRY_VERSION = "content-capabilities-1"

_INDEX_RE = re.compile(r"(目录|概述|索引|速查|列表|清单|使用本书|前言|章节|附录)")
_DM_RE = re.compile(r"(城主工具|冒险之主|规则之主|世界之主|DM|DM专用|非玩家|环境灾害|谜题)")
_SPELL_CLAUSE_TYPES = frozenset(
    {
        "attack_roll",
        "saving_throw",
        "damage",
        "healing",
        "temporary_hp",
        "apply_condition",
        "remove_condition",
        "area",
        "duration",
        "concentration",
        "movement",
        "summon_or_creation",
        "resource_effect",
        "upcast",
        "spell_modifier",
        "target_selection",
    }
)
_SPELL_CLAUSE_CAPABILITIES = {
    clause_type: f"spell.{clause_type}.v1" for clause_type in sorted(_SPELL_CLAUSE_TYPES)
}
_SPELL_CLAUSE_FIELDS = {
    "attack_roll": frozenset({"type", "attack_ability", "attack_bonus", "range"}),
    "saving_throw": frozenset({"type", "save_ability", "dc", "half_on_success"}),
    "damage": frozenset({"type", "expression", "damage", "damage_type", "on_success"}),
    "healing": frozenset({"type", "expression", "healing", "amount", "on_success"}),
    "temporary_hp": frozenset({"type", "amount", "expression"}),
    "apply_condition": frozenset({"type", "condition", "duration", "save_ability"}),
    "remove_condition": frozenset({"type", "condition", "target"}),
    "area": frozenset({"type", "shape", "size", "size_ft", "origin", "target"}),
    "duration": frozenset({"type", "duration", "rounds", "concentration"}),
    "concentration": frozenset({"type", "required", "duration"}),
    "movement": frozenset({"type", "distance_ft", "movement_type", "direction", "speed"}),
    "summon_or_creation": frozenset({"type", "kind", "stat_block_id", "duration", "count"}),
    "resource_effect": frozenset({"type", "resource_key", "operation", "amount"}),
    "upcast": frozenset({"type", "increments", "text", "per_slot"}),
    "spell_modifier": frozenset({"type", "modifier", "value", "scope"}),
    "target_selection": frozenset({"type", "kind", "count", "range", "visibility"}),
}
_SPELL_REQUIRED_FIELDS = {
    "damage": (("expression", "damage"),),
    "healing": (("expression", "healing", "amount"),),
    "temporary_hp": (("amount", "expression"),),
    "saving_throw": (("save_ability",),),
    "apply_condition": (("condition",),),
    "remove_condition": (("condition",),),
    "area": (("shape",),),
    "duration": (("duration", "rounds"),),
    "concentration": (("required",),),
    "movement": (("distance_ft", "speed"),),
    "summon_or_creation": (("kind",),),
    "resource_effect": (("resource_key", "operation"),),
    "upcast": (("increments", "text", "per_slot"),),
    "spell_modifier": (("modifier",),),
    "target_selection": (("kind",),),
}
_SPELL_TOP_LEVEL_FIELDS = frozenset(
    {
        "spell_id",
        "name",
        "source_book",
        "source_record_id",
        "edition",
        "ruleset_version",
        "pack_id",
        "namespace",
        "level",
        "school",
        "casting_time",
        "range",
        "target",
        "components",
        "duration",
        "concentration",
        "attack_or_save",
        "save_ability",
        "damage",
        "healing",
        "damage_type",
        "conditions",
        "area",
        "upcast",
        "resource_effects",
        "summon_or_creation",
        "clauses",
        "source_trust",
        "source_fingerprint",
        "source_provenance",
        "clause_identity",
        "compiler_fingerprint",
        "capability_registry",
    }
)
_SEMANTIC_FIELDS = (
    "prerequisite",
    "choice",
    "resource",
    "action_economy",
    "trigger",
    "target",
    "range",
    "save",
    "damage",
    "healing",
    "condition",
    "duration",
    "movement",
    "spell_interaction",
)


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _record_text(record: Mapping[str, Any]) -> str:
    return str(record.get("content_markdown") or record.get("content_plain_text") or "").strip()


def _source_record_id(record: Mapping[str, Any]) -> str:
    explicit = _text(record.get("stable_id"))
    if explicit:
        return explicit
    return (
        "source:"
        + _fingerprint(
            {
                "source_book": record.get("source_book"),
                "source_relative_path": record.get("source_relative_path"),
                "name": record.get("name"),
            }
        )[:24]
    )


def _bounded_source_text(record: Mapping[str, Any]) -> str:
    """Keep one source section and cut accidental next-heading leakage.

    Normalized CHM records are already section-bounded by the parser.  This
    second boundary is deliberately cheap and deterministic so a malformed
    fixture or a future parser regression cannot make a spell consume the next
    spell or an appended stat block.
    """

    source = _record_text(record)
    if not source:
        return ""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    kept: list[str] = []
    first_heading_seen = False
    current_name = _text(record.get("name"))
    for line in lines:
        stripped = line.strip()
        heading = re.match(r"^#{1,6}\s+(.+?)\s*$", stripped)
        if heading:
            heading_name = _text(heading.group(1))
            if first_heading_seen and heading_name and heading_name != current_name:
                break
            first_heading_seen = True
        if (
            first_heading_seen
            and stripped
            and re.match(r"^(?:召唤物|属性数据|统计资料|Stat Block)\s*[:：]?$", stripped, re.I)
        ):
            break
        kept.append(line)
    result = "\n".join(kept).strip()
    if not result:
        result = source
    return result


def _source_fingerprint(record: Mapping[str, Any], bounded_text: str | None = None) -> str:
    return _fingerprint(
        {
            "source_record_id": _source_record_id(record),
            "source_book": record.get("source_book"),
            "source_relative_path": record.get("source_relative_path"),
            "source_url": record.get("source_url"),
            "source_revision": record.get("source_revision"),
            "content": bounded_text if bounded_text is not None else _bounded_source_text(record),
        }
    )


def _pack_version(records: Iterable[Mapping[str, Any]]) -> str:
    revisions = sorted(
        {_text(item.get("source_revision")) for item in records if item.get("source_revision")}
    )
    if revisions:
        return "source-" + _fingerprint(revisions)[:12]
    runs = sorted({_text(item.get("run_id")) for item in records if item.get("run_id")})
    return "run-" + _fingerprint(runs)[:12] if runs else "unknown"


def _namespace(pack_id: str) -> str:
    return f"content.{re.sub(r'[^A-Za-z0-9_.-]+', '-', pack_id).strip('-') or 'local'}"


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "record"


def _source_metadata(
    record: Mapping[str, Any],
    *,
    pack_id: str,
    namespace: str,
    ruleset_version: str,
    clause_identity: Iterable[str] = (),
    compiler_status: str = "draft",
    blockers: Iterable[str] = (),
) -> dict[str, Any]:
    bounded = _bounded_source_text(record)
    return {
        "source_provenance": {
            "source_book": _text(record.get("source_book")),
            "source_relative_path": _text(record.get("source_relative_path")),
            "source_url": _text(record.get("source_url")),
            "canonical_url": _text(record.get("canonical_url")),
            "source_revision": _text(record.get("source_revision")),
            "source_ref": _text(record.get("source_ref")),
            "source_license": _text(record.get("source_license")),
            "officiality": _text(record.get("officiality")) or "unknown",
            "registered_pack_origin": pack_id != "unregistered",
        },
        "source_record_id": _source_record_id(record),
        "source_fingerprint": _source_fingerprint(record, bounded),
        "pack_id": pack_id,
        "namespace": namespace,
        "ruleset_version": ruleset_version,
        "clause_identity": list(dict.fromkeys(str(item) for item in clause_identity if str(item))),
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry": {
            "id": "feature-and-spell",
            "version": CAPABILITY_REGISTRY_VERSION,
        },
        "compiler_status": compiler_status,
        "blockers": list(dict.fromkeys(str(item) for item in blockers if str(item))),
        "replay_metadata": {
            "idempotency_key": _fingerprint(
                {
                    "pack_id": pack_id,
                    "source_record_id": _source_record_id(record),
                    "source_fingerprint": _source_fingerprint(record, bounded),
                }
            ),
            "replay_policy": "same-source-fingerprint-is-idempotent",
        },
    }


def _is_index_or_non_instantiable(record: Mapping[str, Any]) -> str | None:
    path = _text(record.get("source_relative_path"))
    name = _text(record.get("name"))
    combined = f"{path}/{name}"
    if _INDEX_RE.search(name):
        return "index_or_list_name"
    if _DM_RE.search(combined):
        return "dm_or_narrative_content"
    if any(marker in path for marker in ("目录", "索引", "列表", "清单", "目录")):
        return "index_or_list_path"
    if name in {"职业", "子职业", "专长", "玩家选项", "法术", "角色选项"}:
        return "category_page"
    return None


def _is_spell_detail(record: Mapping[str, Any]) -> bool:
    path = _text(record.get("source_relative_path"))
    name = _text(record.get("name"))
    if str(record.get("content_type") or "") != "spells":
        return False
    if "法术详述" not in path or not name or _INDEX_RE.search(name):
        return False
    # Keep synthetic/unit-test records compatible with the old workbench while
    # rejecting real list pages through their path and structured evidence.
    if "法术列表" in path or "法术清单" in path:
        return False
    if is_spell_detail_record(dict(record)):
        return True
    return len(_bounded_source_text(record)) >= 80


def _feature_context(record: Mapping[str, Any]) -> tuple[str | None, str | None]:
    parts = [
        part
        for part in _text(record.get("source_relative_path")).replace("\\", "/").split("/")
        if part
    ]
    class_name: str | None = None
    subclass_name: str | None = None
    for index, part in enumerate(parts):
        if part in {"职业", "角色职业"} and index + 1 < len(parts):
            class_name = re.sub(r"\.(?:html?|x?htm)$", "", parts[index + 1]).strip()
            if index + 2 < len(parts):
                candidate = re.sub(r"\.(?:html?|x?htm)$", "", parts[index + 2]).strip()
                if candidate and candidate not in {"职业", "子职业"}:
                    subclass_name = candidate
            break
    if record.get("content_type") == "subclasses" and class_name is None:
        class_name = _text(record.get("class_name")) or None
    return class_name, subclass_name


def _is_feature_candidate(record: Mapping[str, Any]) -> bool:
    kind = str(record.get("content_type") or "")
    if kind not in {"classes", "subclasses", "feats"}:
        return False
    return bool(_text(record.get("name"))) and _is_index_or_non_instantiable(record) is None


def _is_other_player_option(record: Mapping[str, Any]) -> bool:
    if _is_index_or_non_instantiable(record) is not None:
        return False
    kind = str(record.get("content_type") or "")
    path = _text(record.get("source_relative_path"))
    return kind in {"backgrounds", "actions"} or (
        kind == "unknown"
        and any(marker in path for marker in ("玩家选项", "角色选项", "职业", "专长", "背景"))
    )


def _labeled_value(text: str, *labels: str) -> str | None:
    pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{pattern})\s*[:：]\s*([^\n。；;]+)", text, re.I)
    return _text(match.group(1)) if match else None


def _extract_level(text: str, record: Mapping[str, Any]) -> int | None:
    value = record.get("level")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    match = re.search(r"(?<!\d)(\d{1,2})\s*级", text)
    return int(match.group(1)) if match else None


def _extract_feature_draft(
    record: Mapping[str, Any],
    *,
    pack_id: str,
    pack_version: str,
    ruleset_version: str,
) -> dict[str, Any]:
    source_text = _bounded_source_text(record)
    class_name, subclass_name = _feature_context(record)
    feature_name = _text(record.get("name"))
    level = _extract_level(source_text, record)
    prerequisite = _labeled_value(source_text, "先决", "前置", "前提")
    feature = record.get("feature")
    structured = dict(feature) if isinstance(feature, Mapping) else {}
    fields: dict[str, Any] = {
        "class_name": _text(structured.get("class_name")) or class_name,
        "subclass_name": _text(structured.get("subclass_name")) or subclass_name,
        "feature_name": feature_name,
        "level": level,
        "source_path": _text(record.get("source_relative_path")),
        "source_text": source_text,
        "prerequisite": structured.get("prerequisite") or prerequisite,
        "choice": structured.get("choice"),
        "resource": structured.get("resource"),
        "action_economy": structured.get("action_economy"),
        "trigger": structured.get("trigger"),
        "target": structured.get("target"),
        "range": structured.get("range"),
        "save": structured.get("save"),
        "damage": structured.get("damage"),
        "healing": structured.get("healing"),
        "condition": structured.get("condition"),
        "duration": structured.get("duration"),
        "movement": structured.get("movement"),
        "spell_interaction": structured.get("spell_interaction"),
    }
    missing = [key for key in _SEMANTIC_FIELDS if fields.get(key) in (None, "", [], {})]
    blockers = ["unstructured_source_requires_authored_feature_ir"]
    blockers.extend(f"missing_field:{key}" for key in missing)
    metadata = _source_metadata(
        record,
        pack_id=pack_id,
        namespace=_namespace(pack_id),
        ruleset_version=ruleset_version,
        blockers=blockers,
    )
    return {
        "kind": "feature_draft",
        "feature_id": f"{pack_id}:feature:{_source_record_id(record)}",
        "source_book": _text(record.get("source_book")),
        "source_record_id": metadata["source_record_id"],
        "source_fingerprint": metadata["source_fingerprint"],
        "pack_id": pack_id,
        "pack_version": pack_version,
        "namespace": metadata["namespace"],
        "ruleset_version": ruleset_version,
        "source_trust": "generated_draft",
        "feature_name": feature_name,
        "class_name": fields["class_name"],
        "subclass_name": fields["subclass_name"],
        "level": level,
        "fields": fields,
        "missing_fields": missing,
        "manual_fields": list(missing),
        "blocker_category": "missing_typed_ir",
        "blocker_details": blockers,
        "status": "manual",
        "source_evidence": {
            "source_path": fields["source_path"],
            "source_text": source_text,
            "source_checksum": _text(record.get("checksum")),
        },
        "source_metadata": metadata,
        "non_instantiable": False,
    }


def _spell_fields_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(record.get("spell") or {})
    try:
        raw = {**raw, **spell_rule_fields(dict(record))}
    except (TypeError, ValueError):
        pass
    text = _bounded_source_text(record)
    save = _text(raw.get("save"))
    save_ability = None
    if save:
        save_ability = re.sub(r"\s*(豁免|检定)\s*", "", save).strip() or None
    return {
        "level": raw.get("level"),
        "school": raw.get("school"),
        "casting_time": raw.get("casting_time"),
        "range": raw.get("range"),
        "target": raw.get("target"),
        "components": raw.get("components"),
        "duration": raw.get("duration"),
        "concentration": raw.get("concentration"),
        "attack_or_save": "saving_throw" if save_ability else None,
        "save_ability": save_ability,
        "damage": raw.get("damage_expression"),
        "healing": raw.get("healing"),
        "damage_type": raw.get("damage_type"),
        "conditions": raw.get("conditions"),
        "area": raw.get("area"),
        "upcast": raw.get("upcast_text"),
        "resource_effects": raw.get("resource_effects"),
        "summon_or_creation": raw.get("summon_or_creation"),
        "clauses": [],
        "source_text": text,
    }


def extract_spell_draft(
    record: Mapping[str, Any],
    *,
    pack_id: str | None = None,
    pack_version: str = "unknown",
    ruleset_version: str | None = None,
) -> dict[str, Any]:
    """Extract source fields only; the result is never a typed SpellSpec."""

    source_book = _text(record.get("source_book"))
    effective_pack_id = pack_id or _pack_id_for_book(source_book)
    edition = _text(record.get("edition")) or "unknown"
    fields = _spell_fields_from_record(record)
    required = (
        "level",
        "school",
        "casting_time",
        "range",
        "target",
        "components",
        "duration",
        "concentration",
        "damage",
        "healing",
        "damage_type",
        "conditions",
        "area",
        "upcast",
        "resource_effects",
        "summon_or_creation",
    )
    missing = [key for key in required if fields.get(key) in (None, "", [], {})]
    blockers = ["unstructured_source_requires_authored_spell_ir"]
    blockers.extend(f"missing_field:{key}" for key in missing)
    metadata = _source_metadata(
        record,
        pack_id=effective_pack_id,
        namespace=_namespace(effective_pack_id),
        ruleset_version=ruleset_version or ("2024" if edition == "2024" else "2014"),
        blockers=blockers,
    )
    return {
        "kind": "spell_draft",
        "spell_id": _source_record_id(record),
        "name": _text(record.get("name")),
        "source_book": source_book,
        "source_record_id": metadata["source_record_id"],
        "source_path": _text(record.get("source_relative_path")),
        "edition": edition,
        "ruleset_version": ruleset_version or ("2024" if edition == "2024" else "2014"),
        "pack_id": effective_pack_id,
        "pack_version": pack_version,
        "namespace": metadata["namespace"],
        "source_trust": "generated_draft",
        "fields": fields,
        "source_text": fields["source_text"],
        "missing_fields": missing,
        "manual_fields": list(missing),
        "clauses": [],
        "status": "manual",
        "blocker_category": "missing_typed_ir",
        "blocker_details": blockers,
        "source_fingerprint": metadata["source_fingerprint"],
        "source_evidence": {
            "source_path": _text(record.get("source_relative_path")),
            "source_text": fields["source_text"],
            "source_checksum": _text(record.get("checksum")),
        },
        "source_metadata": metadata,
        "non_instantiable": False,
    }


@dataclass(frozen=True)
class SpellSpec:
    """Independent closed typed spell contract.

    Optional top-level fields default to ``None`` for a compact minimal
    capability smoke test, but every semantic clause still requires its own
    typed parameters.  Drafts never instantiate this class automatically.
    """

    spell_id: str
    name: str
    level: int
    clauses: tuple[dict[str, Any], ...]
    source_book: str | None = None
    source_record_id: str | None = None
    edition: str = "unknown"
    ruleset_version: str = "2024"
    pack_id: str = "core"
    namespace: str = "content.core"
    school: str | None = None
    casting_time: str | None = None
    range: str | None = None
    target: Any = None
    components: Any = None
    duration: Any = None
    concentration: bool | None = None
    attack_or_save: str | None = None
    save_ability: str | None = None
    damage: Any = None
    healing: Any = None
    damage_type: str | None = None
    conditions: tuple[Any, ...] = ()
    area: Any = None
    upcast: Any = None
    resource_effects: tuple[Any, ...] = ()
    summon_or_creation: Any = None
    source_trust: str = "authored_ir"
    source_fingerprint: str | None = None
    source_provenance: dict[str, Any] = field(default_factory=dict)
    clause_identity: tuple[str, ...] = ()
    compiler_fingerprint: str = COMPILER_FINGERPRINT
    capability_registry: dict[str, Any] = field(
        default_factory=lambda: {
            "id": "spell",
            "version": CAPABILITY_REGISTRY_VERSION,
        }
    )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SpellSpec:
        if not isinstance(value, Mapping):
            raise ValueError("SpellSpec must be an object")
        unknown = sorted(set(value) - _SPELL_TOP_LEVEL_FIELDS)
        if unknown:
            raise ValueError("SpellSpec contains unknown fields: " + ", ".join(unknown))
        required = ("spell_id", "name", "level", "clauses")
        missing = [key for key in required if key not in value]
        if missing:
            raise ValueError("missing required SpellSpec fields: " + ", ".join(missing))
        if not isinstance(value["spell_id"], str) or not value["spell_id"].strip():
            raise ValueError("spell_id must be a non-empty string")
        if not isinstance(value["name"], str) or not value["name"].strip():
            raise ValueError("name must be a non-empty string")
        if (
            not isinstance(value["level"], int)
            or isinstance(value["level"], bool)
            or not 0 <= value["level"] <= 9
        ):
            raise ValueError("level must be an integer from 0 to 9")
        if not isinstance(value["clauses"], list) or not value["clauses"]:
            raise ValueError("clauses must be a non-empty array")
        for index, clause in enumerate(value["clauses"]):
            if not isinstance(clause, Mapping) or not isinstance(clause.get("type"), str):
                raise ValueError(f"clauses[{index}] must contain a typed clause type")
        source_trust = str(value.get("source_trust") or "authored_ir")
        if source_trust not in {
            "authored_ir",
            "verified_mapping",
            "generated_draft",
            "unstructured_source",
            "unverified",
        }:
            raise ValueError(f"unsupported SpellSpec source_trust: {source_trust}")
        clauses = tuple(dict(clause) for clause in value["clauses"])
        source_provenance = (
            dict(value.get("source_provenance") or {})
            if isinstance(value.get("source_provenance") or {}, Mapping)
            else {}
        )
        conditions = value.get("conditions") or ()
        if not isinstance(conditions, (list, tuple)):
            raise ValueError("conditions must be an array")
        resource_effects = value.get("resource_effects") or ()
        if not isinstance(resource_effects, (list, tuple)):
            raise ValueError("resource_effects must be an array")
        capability_registry = value.get("capability_registry") or {
            "id": "spell",
            "version": CAPABILITY_REGISTRY_VERSION,
        }
        if not isinstance(capability_registry, Mapping):
            raise ValueError("capability_registry must be an object")
        return cls(
            spell_id=value["spell_id"].strip(),
            name=value["name"].strip(),
            level=value["level"],
            clauses=clauses,
            source_book=_text(value.get("source_book")) or None,
            source_record_id=_text(value.get("source_record_id")) or None,
            edition=_text(value.get("edition")) or "unknown",
            ruleset_version=_text(value.get("ruleset_version")) or "2024",
            pack_id=_text(value.get("pack_id")) or "core",
            namespace=_text(value.get("namespace")) or "content.core",
            school=_text(value.get("school")) or None,
            casting_time=_text(value.get("casting_time")) or None,
            range=_text(value.get("range")) or None,
            target=value.get("target"),
            components=value.get("components"),
            duration=value.get("duration"),
            concentration=value.get("concentration"),
            attack_or_save=_text(value.get("attack_or_save")) or None,
            save_ability=_text(value.get("save_ability")) or None,
            damage=value.get("damage"),
            healing=value.get("healing"),
            damage_type=_text(value.get("damage_type")) or None,
            conditions=tuple(conditions),
            area=value.get("area"),
            upcast=value.get("upcast"),
            resource_effects=tuple(resource_effects),
            summon_or_creation=value.get("summon_or_creation"),
            source_trust=source_trust,
            source_fingerprint=_text(value.get("source_fingerprint")) or None,
            source_provenance=source_provenance,
            clause_identity=tuple(
                str(item) for item in (value.get("clause_identity") or ()) if str(item).strip()
            ),
            compiler_fingerprint=_text(value.get("compiler_fingerprint")) or COMPILER_FINGERPRINT,
            capability_registry=dict(capability_registry),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "spell",
            "spell_id": self.spell_id,
            "name": self.name,
            "source_book": self.source_book,
            "source_record_id": self.source_record_id or self.spell_id,
            "edition": self.edition,
            "ruleset_version": self.ruleset_version,
            "pack_id": self.pack_id,
            "namespace": self.namespace,
            "level": self.level,
            "school": self.school,
            "casting_time": self.casting_time,
            "range": self.range,
            "target": self.target,
            "components": self.components,
            "duration": self.duration,
            "concentration": self.concentration,
            "attack_or_save": self.attack_or_save,
            "save_ability": self.save_ability,
            "damage": self.damage,
            "healing": self.healing,
            "damage_type": self.damage_type,
            "conditions": list(self.conditions),
            "area": self.area,
            "upcast": self.upcast,
            "resource_effects": list(self.resource_effects),
            "summon_or_creation": self.summon_or_creation,
            "clauses": [_jsonable(clause) for clause in self.clauses],
            "source_trust": self.source_trust,
            "source_fingerprint": self.source_fingerprint
            or _fingerprint(
                {
                    "source_record_id": self.source_record_id or self.spell_id,
                    "source_book": self.source_book,
                    "name": self.name,
                }
            ),
            "source_provenance": _jsonable(self.source_provenance),
            "clause_identity": list(self.clause_identity)
            or [f"{self.spell_id}:clause:{index}" for index, _ in enumerate(self.clauses)],
            "compiler_fingerprint": self.compiler_fingerprint,
            "capability_registry": _jsonable(self.capability_registry),
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _spell_clause_errors(clause: Mapping[str, Any], index: int) -> tuple[str, ...]:
    clause_type = _text(clause.get("type"))
    if not clause_type:
        return (f"clause:{index}:missing_type",)
    if clause_type not in _SPELL_CLAUSE_TYPES:
        return (f"unsupported_spell_clause:{clause_type}",)
    allowed = _SPELL_CLAUSE_FIELDS[clause_type]
    unknown = sorted(set(clause) - allowed)
    errors = [f"clause:{index}:unknown_field:{item}" for item in unknown]
    for options in _SPELL_REQUIRED_FIELDS.get(clause_type, ()):
        if not any(clause.get(key) not in (None, "") for key in options):
            errors.append(f"clause:{index}:missing_typed_parameter:{'/'.join(options)}")
    if clause_type == "concentration" and not isinstance(clause.get("required"), bool):
        errors.append(f"clause:{index}:required_must_be_bool")
    if clause_type in {"damage", "healing", "temporary_hp"}:
        expression = clause.get("expression") or clause.get("damage") or clause.get("healing")
        if expression is not None and not isinstance(expression, (str, int, float)):
            errors.append(f"clause:{index}:expression_must_be_scalar")
    return tuple(errors)


def compile_spell_spec(spec: SpellSpec) -> dict[str, Any]:
    """Compile and materialize every typed spell clause fail-closed."""

    clause_results: list[dict[str, Any]] = []
    blockers: list[str] = []
    capabilities: list[str] = []
    runtime_blocks: list[dict[str, Any]] = []
    for index, clause in enumerate(spec.clauses):
        errors = _spell_clause_errors(clause, index)
        clause_type = _text(clause.get("type"))
        capability = _SPELL_CLAUSE_CAPABILITIES.get(clause_type)
        if errors:
            blockers.extend(errors)
        elif capability:
            capabilities.append(capability)
            runtime_blocks.append(
                {
                    "kind": "spell_clause",
                    "spell_id": spec.spell_id,
                    "clause_id": f"{spec.spell_id}:clause:{index}",
                    "type": clause_type,
                    "capability_id": capability,
                    "parameters": _jsonable(clause),
                }
            )
        clause_results.append(
            {
                "clause_id": f"{spec.spell_id}:clause:{index}",
                "type": clause_type,
                "status": "full"
                if not errors
                else "invalid"
                if any(
                    item.startswith("unsupported_spell_clause") or ":unknown_field:" in item
                    for item in errors
                )
                else "partial",
                "capability_id": capability,
                "blockers": list(errors),
            }
        )
    if spec.source_trust not in {"authored_ir", "verified_mapping"}:
        blockers.append("source_trust_not_verified")
    if spec.compiler_fingerprint != COMPILER_FINGERPRINT:
        blockers.append("compiler_fingerprint_mismatch")
    if not spec.clauses:
        blockers.append("missing_typed_clauses")
    if any(
        item.startswith("unsupported_spell_clause") or ":unknown_field:" in item
        for item in blockers
    ):
        status = "invalid"
    elif blockers:
        status = "partial"
    elif any(item["status"] != "full" for item in clause_results):
        status = "partial"
    else:
        status = "full"
    if status != "full":
        runtime_blocks = []
    source_fp = spec.to_dict()["source_fingerprint"]
    result_without_fp = {
        "spell_id": spec.spell_id,
        "compile_status": status,
        "typed_clause_count": len(spec.clauses),
        "clause_results": clause_results,
        "capability_ids": sorted(set(capabilities)) if status == "full" else [],
        "unsupported_clause_ids": sorted(
            {
                _text(clause.get("type"))
                for clause in spec.clauses
                if _text(clause.get("type")) not in _SPELL_CLAUSE_TYPES
            }
        ),
        "blockers": sorted(set(blockers)),
        "runtime_blocks": runtime_blocks,
        "source_trust": spec.source_trust,
        "source_fingerprint": source_fp,
        "compiler_fingerprint": spec.compiler_fingerprint,
        "capability_registry": spec.capability_registry,
    }
    return {
        **result_without_fp,
        "fingerprint": _fingerprint(result_without_fp),
    }


def _pack_id_for_book(source_book: str) -> str:
    for pack in _registered_packs():
        if pack["source_book"] == source_book or source_book in pack.get("source_book_aliases", []):
            return str(pack["pack_id"])
    if source_book == "玩家手册 2024":
        return "core-phb-2024"
    if source_book in {"玩家手册 2014", "玩家手册"}:
        return "core-phb-2014"
    return "unregistered"


def _registered_packs() -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    for item in list_content_packs():
        packs.append(
            {
                "pack_id": str(item["key"]),
                "label": str(item["label"]),
                "source_book": str(item["source_book"]),
                "source_book_aliases": list(item.get("source_book_aliases") or []),
                "source_path_prefixes": list(item.get("source_path_prefixes") or []),
                "source_edition": str(item.get("source_edition") or "unknown"),
                "source_origin": str(item.get("source_origin") or "unknown"),
                "content_types": list(item.get("content_types") or []),
            }
        )
        source_pack = CONTENT_PACKS_BY_KEY.get(str(item["key"]))
        if source_pack is not None:
            packs[-1]["source_book_aliases"] = list(source_pack.source_book_aliases)
            packs[-1]["source_path_prefixes"] = list(source_pack.source_path_prefixes)
    return packs


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


def _select_records(
    records: Iterable[Mapping[str, Any]],
    *,
    source_book: str | None = None,
    pack_id: str | None = None,
    content_pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for raw in records:
        record = dict(raw)
        if content_pack is not None:
            pack = content_pack_for_record(record, allow_source_path=True)
            if pack is None or pack.key != content_pack["pack_id"]:
                continue
            # A registered pack is an explicit official source boundary, while
            # a record explicitly marked third-party remains excluded.
            if record.get("officiality") == "third_party":
                continue
        elif source_book is not None:
            core_book = source_book in {"玩家手册 2024", "玩家手册 2014", "玩家手册"}
            if record.get("source_book") != source_book and (
                core_book
                or not _text(record.get("source_relative_path")).startswith(source_book + "/")
            ):
                continue
        selected.append(record)
    return sorted(
        selected,
        key=lambda item: (
            _text(item.get("source_relative_path")),
            _text(item.get("name")),
            _source_record_id(item),
        ),
    )


def _excluded_entry(record: Mapping[str, Any], reason: str) -> dict[str, Any]:
    metadata = _source_metadata(
        record,
        pack_id="unregistered",
        namespace="content.unregistered",
        ruleset_version=_text(record.get("edition")) or "unknown",
        blockers=[reason],
    )
    return {
        "kind": "source_record",
        "name": _text(record.get("name")),
        "content_type": _text(record.get("content_type")) or "unknown",
        "source_book": _text(record.get("source_book")),
        "source_path": _text(record.get("source_relative_path")),
        "source_record_id": metadata["source_record_id"],
        "source_fingerprint": metadata["source_fingerprint"],
        "status": "manual",
        "non_instantiable": True,
        "exclusion_reason": reason,
        "source_metadata": metadata,
    }


def _capability_ranking(entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    occurrence: Counter[str] = Counter()
    evidence: defaultdict[str, set[str]] = defaultdict(set)
    for entry in entries:
        for capability in entry.get("capability_ids") or []:
            occurrence[str(capability)] += 1
            evidence[str(capability)].add(
                str(
                    entry.get("source_record_id")
                    or entry.get("spell_id")
                    or entry.get("feature_id")
                )
            )
    return [
        {
            "capability_id": capability,
            "occurrence_count": count,
            # Only compiled typed clauses with a production capability can
            # unlock anything.  Draft prevalence is not an unlock signal.
            "completion_unlock_count": count
            if any(
                entry.get("status") == "full"
                and capability in (entry.get("capability_ids") or [])
                and entry.get("typed_ir")
                for entry in entries
            )
            else 0,
            "evidence_record_ids": sorted(evidence[capability]),
        }
        for capability, count in sorted(occurrence.items(), key=lambda item: (-item[1], item[0]))
    ]


@dataclass(frozen=True)
class WorkbenchReport:
    source_root: str
    source_book: str | None
    total_records: int
    feature_count: int
    spell_count: int
    feat_count: int
    other_player_option_count: int = 0
    draft_count: int = 0
    typed_ir_count: int = 0
    counts: dict[str, int] = field(default_factory=lambda: {status: 0 for status in STATUS_VALUES})
    source_untyped: int = 0
    capability_counts: dict[str, int] = field(default_factory=dict)
    blocker_counts: dict[str, int] = field(default_factory=dict)
    entries: tuple[dict[str, Any], ...] = ()
    pack_id: str | None = None
    pack_version: str | None = None
    source_officiality_counts: dict[str, int] = field(default_factory=dict)
    edition_counts: dict[str, int] = field(default_factory=dict)
    non_instantiable_count: int = 0
    completion_unlock_ranking: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        top_blockers = [
            {"blocker": key, "count": value}
            for key, value in sorted(
                self.blocker_counts.items(), key=lambda item: (-item[1], item[0])
            )[:10]
        ]
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "source_root": self.source_root,
            "source_book": self.source_book,
            "pack_id": self.pack_id,
            "pack_version": self.pack_version,
            "total_records": self.total_records,
            "source_record_count": self.total_records,
            "feature_count": self.feature_count,
            "feature_candidate_count": self.feature_count,
            "spell_count": self.spell_count,
            "spell_candidate_count": self.spell_count,
            "feat_count": self.feat_count,
            "feat_candidate_count": self.feat_count,
            "other_player_option_count": self.other_player_option_count,
            "draft_count": self.draft_count,
            "typed_ir_count": self.typed_ir_count,
            "full_count": self.counts.get("full", 0),
            "partial_count": self.counts.get("partial", 0),
            "manual_count": self.counts.get("manual", 0),
            "invalid_count": self.counts.get("invalid", 0),
            "counts": {status: self.counts.get(status, 0) for status in STATUS_VALUES},
            "source_untyped": self.source_untyped,
            "source_untyped_count": self.source_untyped,
            "source_officiality_counts": dict(sorted(self.source_officiality_counts.items())),
            "edition_counts": dict(sorted(self.edition_counts.items())),
            "non_instantiable_count": self.non_instantiable_count,
            "capability_counts": dict(sorted(self.capability_counts.items())),
            "top_blockers": top_blockers,
            "blocker_counts": dict(sorted(self.blocker_counts.items())),
            "completion_unlock_ranking": list(self.completion_unlock_ranking),
            "entries": list(self.entries),
        }


def audit_records(
    records: list[dict[str, Any]],
    *,
    source_book: str | None = None,
    include_entries: bool = True,
    pack_id: str | None = None,
    pack_version: str | None = None,
    content_pack: Mapping[str, Any] | None = None,
) -> WorkbenchReport:
    """Audit one core book or one registered pack without mutating production."""

    selected = _select_records(
        records,
        source_book=source_book,
        pack_id=pack_id,
        content_pack=content_pack,
    )
    effective_pack_id = pack_id or _pack_id_for_book(source_book or "")
    effective_pack_version = pack_version or _pack_version(selected)
    entries: list[dict[str, Any]] = []
    blockers: Counter[str] = Counter()
    capability_counts: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    features = spells = feats = other = drafts = typed = non_instantiable = 0
    officiality = Counter(str(item.get("officiality") or "unknown") for item in selected)
    editions = Counter(str(item.get("edition") or "unknown") for item in selected)
    for record in selected:
        exclusion = _is_index_or_non_instantiable(record)
        if _is_spell_detail(record):
            spells += 1
            draft = extract_spell_draft(
                record,
                pack_id=effective_pack_id,
                pack_version=effective_pack_version,
                ruleset_version="2024" if _text(record.get("edition")) == "2024" else "2014",
            )
            drafts += 1
            counts[draft["status"]] += 1
            for blocker in draft["blocker_details"]:
                blockers[blocker] += 1
            if include_entries:
                entries.append({"content_type": "spell", **draft})
            continue
        if _is_feature_candidate(record):
            features = (
                features + 1
                if str(record.get("content_type")) in {"classes", "subclasses"}
                else features
            )
            feats = feats + 1 if str(record.get("content_type")) == "feats" else feats
            draft = _extract_feature_draft(
                record,
                pack_id=effective_pack_id,
                pack_version=effective_pack_version,
                ruleset_version="2024" if _text(record.get("edition")) == "2024" else "2014",
            )
            drafts += 1
            counts[draft["status"]] += 1
            for blocker in draft["blocker_details"]:
                blockers[blocker] += 1
            if include_entries:
                entries.append({"content_type": str(record.get("content_type")), **draft})
            continue
        if _is_other_player_option(record):
            other += 1
            draft = _extract_feature_draft(
                record,
                pack_id=effective_pack_id,
                pack_version=effective_pack_version,
                ruleset_version="2024" if _text(record.get("edition")) == "2024" else "2014",
            )
            draft["kind"] = "player_option_draft"
            draft["blocker_category"] = "other_player_option_requires_typed_ir"
            drafts += 1
            counts[draft["status"]] += 1
            for blocker in draft["blocker_details"]:
                blockers[blocker] += 1
            if include_entries:
                entries.append({"content_type": str(record.get("content_type")), **draft})
            continue
        if exclusion is not None:
            non_instantiable += 1
            if include_entries:
                entries.append(_excluded_entry(record, exclusion))
    entries = sorted(
        entries,
        key=lambda item: (
            str(item.get("kind")),
            str(item.get("source_path") or ""),
            str(item.get("name") or item.get("feature_name") or ""),
            str(item.get("source_record_id") or ""),
        ),
    )
    for entry in entries:
        for capability in entry.get("capability_ids") or []:
            capability_counts[str(capability)] += 1
    return WorkbenchReport(
        source_root="generated-content",
        source_book=source_book,
        pack_id=effective_pack_id,
        pack_version=effective_pack_version,
        total_records=len(selected),
        feature_count=features,
        spell_count=spells,
        feat_count=feats,
        other_player_option_count=other,
        draft_count=drafts,
        typed_ir_count=typed,
        counts={status: counts.get(status, 0) for status in STATUS_VALUES},
        source_untyped=drafts,
        capability_counts=dict(capability_counts),
        blocker_counts=dict(blockers),
        entries=tuple(entries),
        source_officiality_counts=dict(officiality),
        edition_counts=dict(editions),
        non_instantiable_count=non_instantiable,
        completion_unlock_ranking=tuple(_capability_ranking(entries)),
    )


def compile_feature_draft(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Keep a source draft out of the FeatureCompiler authority path."""

    return {
        "feature_id": _text(draft.get("feature_id")),
        "compile_status": (
            "invalid"
            if draft.get("status") == "invalid"
            else "manual"
            if draft.get("status") == "manual"
            else "partial"
        ),
        "status_authority": "none",
        "typed_ir": False,
        "materialized": False,
        "capability_ids": [],
        "blockers": sorted(
            set(
                str(item)
                for item in (
                    draft.get("blocker_details")
                    or draft.get("blockers")
                    or ["missing_typed_feature_ir"]
                )
            )
        ),
        "source_fingerprint": _text(draft.get("source_fingerprint")),
        "spec_fingerprint": None,
        "compiler_fingerprint": COMPILER_FINGERPRINT,
    }


def compile_typed_feature_spec(spec: FeatureSpec) -> dict[str, Any]:
    result = FeatureCompiler(status_authority="compiler").compile(spec)
    payload = result.to_dict()
    payload.update(
        {
            "typed_ir": True,
            "materialized": result.compile_status == "full",
            "spec_fingerprint": spec.fingerprint(),
            "source_fingerprint": _text(spec.compatibility.get("source_fingerprint"))
            or spec.fingerprint(),
            "compiler_fingerprint": COMPILER_FINGERPRINT,
        }
    )
    return payload


def write_report(report: WorkbenchReport, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _manifest_fingerprint(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_fingerprint", None)
    return _fingerprint(payload)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _registered_pack(pack_id_or_label: str) -> dict[str, Any] | None:
    needle = _text(pack_id_or_label)
    for item in _registered_packs():
        if needle in {
            item["pack_id"],
            item["label"],
            item["source_book"],
            *item["source_book_aliases"],
        }:
            return item
    return None


def scan_registered_official_packs(
    records: list[dict[str, Any]],
    *,
    workbench_root: Path,
) -> dict[str, Any]:
    """Scan every pack in the local official content-pack registry."""

    reports: dict[str, dict[str, Any]] = {}
    for pack in _registered_packs():
        selected = _select_records(records, content_pack=pack)
        report = audit_records(
            selected,
            pack_id=pack["pack_id"],
            pack_version=_pack_version(selected),
            source_book=pack["source_book"],
            content_pack=pack,
        )
        pack_dir = workbench_root / pack["pack_id"]
        compile_pack_records(
            selected,
            report=report,
            pack=pack,
            output_dir=pack_dir,
        )
        reports[pack["pack_id"]] = report.to_dict()
    return {
        "schema_version": "content-ir-workbench-official-index-1",
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry_version": CAPABILITY_REGISTRY_VERSION,
        "packs": reports,
    }


def compile_pack_records(
    records: list[dict[str, Any]],
    *,
    report: WorkbenchReport,
    pack: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Write a complete isolated scan/compile/dry-run/report artifact set."""

    if output_dir.exists():
        # Never clean an arbitrary path.  The workbench owns only its own
        # generated directory and makes repeated reports deterministic.
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)
    drafts_dir = output_dir / "drafts"
    typed_dir = output_dir / "typed-ir"
    drafts_dir.mkdir()
    typed_dir.mkdir()
    source_inventory = {
        "schema_version": "content-ir-source-inventory-1",
        "pack_id": report.pack_id,
        "pack_version": report.pack_version,
        "source_book": report.source_book,
        "records": [
            {
                "source_record_id": _source_record_id(record),
                "source_book": record.get("source_book"),
                "content_type": record.get("content_type"),
                "name": record.get("name"),
                "source_relative_path": record.get("source_relative_path"),
                "source_fingerprint": _source_fingerprint(record),
                "officiality": record.get("officiality") or "unknown",
                "edition": record.get("edition") or "unknown",
            }
            for record in sorted(
                records,
                key=lambda item: (_source_record_id(item), _text(item.get("source_relative_path"))),
            )
        ],
    }
    _write_json(output_dir / "source-inventory.json", source_inventory)
    draft_paths: list[str] = []
    for entry in report.entries:
        if entry.get("non_instantiable"):
            continue
        if entry.get("kind") not in {"spell_draft", "feature_draft", "player_option_draft"}:
            continue
        prefix = "spell" if entry.get("kind") == "spell_draft" else "feature"
        path = drafts_dir / f"{prefix}-{_safe_filename(_text(entry.get('source_record_id')))}.json"
        _write_json(path, entry)
        draft_paths.append(str(path.relative_to(output_dir)))
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "pack_id": report.pack_id,
        "pack_version": report.pack_version,
        "source_book": report.source_book,
        "namespace": _namespace(str(report.pack_id)),
        "ruleset_version": "2024" if report.source_book != "玩家手册 2014" else "2014",
        "source_fingerprints": {
            item["source_record_id"]: item["source_fingerprint"]
            for item in source_inventory["records"]
        },
        "draft_paths": sorted(draft_paths),
        "typed_ir_paths": [],
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry_version": CAPABILITY_REGISTRY_VERSION,
        "production_targets": {
            "database": False,
            "feature_registry": False,
            "spell_registry": False,
            "campaign": False,
            "character": False,
        },
        "replay": {"policy": "same-manifest-fingerprint-is-idempotent"},
    }
    manifest["manifest_fingerprint"] = _manifest_fingerprint(manifest)
    _write_json(output_dir / "manifest.json", manifest)
    compile_result = compile_artifact_directory(output_dir, write_files=True)
    dry_run = dry_run_manifest(
        output_dir / "manifest.json", output_dir / "isolated-runtime-preview"
    )
    _write_json(output_dir / "dry-run-result.json", dry_run)
    _write_json(
        output_dir / "compiled-runtime-preview.json",
        dry_run.get("runtime_preview", {}),
    )
    final_report = report.to_dict()
    final_report["compile_result"] = compile_result
    final_report["dry_run_result"] = {
        key: value for key, value in dry_run.items() if key != "runtime_preview"
    }
    _write_json(output_dir / "report.json", final_report)
    return final_report


def compile_artifact_directory(
    input_dir: Path, *, output_dir: Path | None = None, write_files: bool = True
) -> dict[str, Any]:
    """Compile Draft/typed files in an isolated artifact directory."""

    root = input_dir
    manifest = _read_json(root / "manifest.json")
    draft_entries: list[dict[str, Any]] = []
    for relative in sorted(manifest.get("draft_paths") or []):
        draft_entries.append(_read_json(root / relative))
    typed_features: dict[str, FeatureSpec] = {}
    typed_spells: dict[str, SpellSpec] = {}
    for relative in sorted(manifest.get("typed_ir_paths") or []):
        value = _read_json(root / relative)
        kind = value.get("kind")
        if kind == "feature":
            spec = FeatureSpec.from_dict(value, "typed.feature")
            if spec.feature_id in typed_features:
                raise ValueError(f"duplicate feature_id: {spec.feature_id}")
            typed_features[spec.feature_id] = spec
        elif kind == "spell":
            spec = SpellSpec.from_dict(value)
            if spec.spell_id in typed_spells:
                raise ValueError(f"duplicate spell_id: {spec.spell_id}")
            typed_spells[spec.spell_id] = spec
        else:
            raise ValueError(f"unknown typed IR kind: {kind}")
    results: list[dict[str, Any]] = []
    source_fingerprints = {
        str(key): str(value) for key, value in (manifest.get("source_fingerprints") or {}).items()
    }
    conflicts: list[str] = []
    for draft in sorted(
        draft_entries,
        key=lambda item: (_text(item.get("kind")), _text(item.get("source_record_id"))),
    ):
        source_id = _text(draft.get("source_record_id"))
        expected_source_fp = source_fingerprints.get(source_id)
        actual_source_fp = _text(draft.get("source_fingerprint"))
        if expected_source_fp and actual_source_fp and expected_source_fp != actual_source_fp:
            conflicts.append(f"{source_id}: source fingerprint conflict")
        if draft.get("kind") == "spell_draft":
            result = {
                "kind": "spell",
                "spell_id": _text(draft.get("spell_id")),
                "typed_ir": False,
                **compile_spell_draft(draft),
            }
            spec = typed_spells.get(result["spell_id"])
            if spec is not None:
                result = {
                    "kind": "spell",
                    "spell_id": spec.spell_id,
                    **compile_spell_spec(spec),
                    "typed_ir": True,
                    "materialized": compile_spell_spec(spec)["compile_status"] == "full",
                    "spec_fingerprint": _fingerprint(spec.to_dict()),
                }
        elif draft.get("kind") in {"feature_draft", "player_option_draft"}:
            result = {
                "kind": "feature",
                "feature_id": _text(draft.get("feature_id")),
                "typed_ir": False,
                **compile_feature_draft(draft),
            }
            spec = typed_features.get(result["feature_id"])
            if spec is not None:
                compiled = compile_typed_feature_spec(spec)
                result = {"kind": "feature", **compiled, "feature_id": spec.feature_id}
        else:
            continue
        results.append(result)
    ids = [str(item.get("spell_id") or item.get("feature_id")) for item in results]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate feature_id/spell_id in compiled artifact")
    counts = {status: 0 for status in STATUS_VALUES}
    capability_counts: Counter[str] = Counter()
    blockers: Counter[str] = Counter()
    typed_count = 0
    for result in results:
        status = str(result.get("compile_status") or result.get("status") or "invalid")
        counts[status] = counts.get(status, 0) + 1
        typed_count += bool(result.get("typed_ir"))
        for capability in result.get("capability_ids") or []:
            capability_counts[str(capability)] += 1
        for blocker in result.get("blockers") or []:
            blockers[str(blocker)] += 1
    output = {
        "schema_version": "content-ir-compile-result-1",
        "manifest_fingerprint": manifest.get("manifest_fingerprint")
        or _manifest_fingerprint(manifest),
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry_version": CAPABILITY_REGISTRY_VERSION,
        "counts": counts,
        "typed_ir_count": typed_count,
        "capability_counts": dict(sorted(capability_counts.items())),
        "blocker_counts": dict(sorted(blockers.items())),
        "conflicts": sorted(set(conflicts)),
        "results": results,
        "runtime_preview": [
            item
            for item in results
            if item.get("compile_status") == "full" and item.get("materialized")
        ],
    }
    if write_files:
        target = output_dir or root
        if target != root:
            if target.exists() and any(target.iterdir()):
                raise ValueError(f"compile output is not empty: {target}")
            target.mkdir(parents=True, exist_ok=True)
            for relative in [
                "manifest.json",
                "source-inventory.json",
                "report.json",
                *manifest.get("draft_paths", []),
                *manifest.get("typed_ir_paths", []),
            ]:
                source_path = root / relative
                if not source_path.exists():
                    continue
                if relative == "report.json":
                    relative = "source-report.json"
                destination = target / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination)
        _write_json(target / "compile-result.json", output)
    return output


def compile_spell_draft(draft: Mapping[str, Any]) -> dict[str, Any]:
    status = "invalid" if draft.get("status") == "invalid" else "manual"
    return {
        "compile_status": status,
        "status_authority": "none",
        "blockers": sorted(
            set(str(item) for item in draft.get("blocker_details") or ["missing_typed_spell_ir"])
        ),
        "capability_ids": [],
        "runtime_blocks": [],
        "source_fingerprint": _text(draft.get("source_fingerprint")),
        "spec_fingerprint": None,
        "compiler_fingerprint": COMPILER_FINGERPRINT,
    }


def dry_run_manifest(
    manifest_path: Path,
    isolated_target: Path,
) -> dict[str, Any]:
    """Materialize a pack preview in an isolated target with rollback."""

    manifest = _read_json(manifest_path)
    expected_fp = str(manifest.get("manifest_fingerprint") or _manifest_fingerprint(manifest))
    if str(manifest.get("compiler_fingerprint") or "") != COMPILER_FINGERPRINT:
        return {
            "schema_version": "content-ir-dry-run-1",
            "status": "conflict",
            "conflicts": ["compiler_fingerprint_mismatch"],
            "rolled_back": True,
            "production_mutated": False,
        }
    compile_result = compile_artifact_directory(manifest_path.parent, write_files=False)
    conflicts = list(compile_result.get("conflicts") or [])
    if any(
        not isinstance(value, str) or not value
        for value in (manifest.get("source_fingerprints") or {}).values()
    ):
        conflicts.append("invalid_source_fingerprint")
    if conflicts:
        return {
            "schema_version": "content-ir-dry-run-1",
            "status": "conflict",
            "manifest_fingerprint": expected_fp,
            "conflicts": sorted(set(conflicts)),
            "rolled_back": True,
            "production_mutated": False,
        }
    if isolated_target.exists():
        if isolated_target.is_file():
            return {
                "schema_version": "content-ir-dry-run-1",
                "status": "conflict",
                "manifest_fingerprint": expected_fp,
                "conflicts": ["isolated_target_is_file"],
                "rolled_back": True,
                "production_mutated": False,
            }
        marker = isolated_target / "dry-run-marker.json"
        if marker.exists():
            previous = _read_json(marker)
            if previous.get("manifest_fingerprint") == expected_fp:
                return {
                    "schema_version": "content-ir-dry-run-1",
                    "status": "idempotent_replay",
                    "manifest_fingerprint": expected_fp,
                    "conflicts": [],
                    "rolled_back": False,
                    "production_mutated": False,
                    "runtime_preview": previous.get("runtime_preview") or [],
                }
            return {
                "schema_version": "content-ir-dry-run-1",
                "status": "conflict",
                "manifest_fingerprint": expected_fp,
                "conflicts": ["isolated_target_manifest_conflict"],
                "rolled_back": True,
                "production_mutated": False,
            }
        if any(isolated_target.iterdir()):
            return {
                "schema_version": "content-ir-dry-run-1",
                "status": "conflict",
                "manifest_fingerprint": expected_fp,
                "conflicts": ["isolated_target_not_owned"],
                "rolled_back": True,
                "production_mutated": False,
            }
    staging = isolated_target.with_name(isolated_target.name + f".staging-{expected_fp[:12]}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=False)
    try:
        runtime_preview = compile_result.get("runtime_preview") or []
        _write_json(
            staging / "dry-run-marker.json",
            {
                "schema_version": "content-ir-dry-run-marker-1",
                "manifest_fingerprint": expected_fp,
                "runtime_preview": runtime_preview,
                "production_targets": manifest.get("production_targets") or {},
            },
        )
        _write_json(
            staging / "runtime-preview.json",
            {
                "schema_version": "content-ir-runtime-preview-1",
                "pack_id": manifest.get("pack_id"),
                "pack_version": manifest.get("pack_version"),
                "results": runtime_preview,
            },
        )
        isolated_target.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(isolated_target)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        return {
            "schema_version": "content-ir-dry-run-1",
            "status": "rolled_back",
            "manifest_fingerprint": expected_fp,
            "conflicts": ["dry_run_write_failed"],
            "rolled_back": True,
            "production_mutated": False,
        }
    return {
        "schema_version": "content-ir-dry-run-1",
        "status": "dry_run",
        "manifest_fingerprint": expected_fp,
        "conflicts": [],
        "rolled_back": False,
        "production_mutated": False,
        "formal_feature_registry_written": False,
        "formal_spell_registry_written": False,
        "campaign_written": False,
        "character_written": False,
        "runtime_preview": runtime_preview,
    }


def report_from_artifacts(input_dir: Path) -> dict[str, Any]:
    report_path = input_dir / "report.json"
    if report_path.exists():
        return _read_json(report_path)
    manifest = _read_json(input_dir / "manifest.json")
    compile_result = compile_artifact_directory(input_dir, write_files=False)
    source_report_path = input_dir / "source-report.json"
    if source_report_path.exists():
        report = _read_json(source_report_path)
        report["compile_result"] = compile_result
        report["dry_run_result"] = {
            "production_mutated": False,
            "formal_feature_registry_written": False,
            "formal_spell_registry_written": False,
        }
        return report
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "pack_id": manifest.get("pack_id"),
        "pack_version": manifest.get("pack_version"),
        "source_book": manifest.get("source_book"),
        "typed_ir_count": compile_result.get("typed_ir_count", 0),
        "counts": compile_result.get("counts", {status: 0 for status in STATUS_VALUES}),
        "compile_result": compile_result,
    }
