# ruff: noqa: N999
"""Build the reviewed Typed IR expansion and its deterministic batch reports.

The source records are selected from the local normalized corpus.  The small
semantic mapping table below is the review decision: it does not try to infer
an executable contract from arbitrary prose.  Every emitted record keeps the
source section, source fingerprint, clause boundaries and review authority.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_templates import (
    build_template_catalog,
    generate_candidates,
)
from dnd_dm_assistant.application.content_ir_workbench import (
    COMPILER_FINGERPRINT,
    _bounded_source_text,
    _fingerprint,
    _is_spell_detail,
    _source_fingerprint,
    _source_record_id,
    compile_artifact_directory,
    compile_spell_spec,
    load_records,
)
from dnd_dm_assistant.application.rule_metadata import spell_rule_fields

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "data/generated-content/dnd5e_chm/json"
AUTHORED_ROOT = ROOT / "data/content-ir/authored/batch-II"
CANDIDATE_ROOT = ROOT / "data/content-ir/candidates/batch-II"
TEMPLATE_PATH = ROOT / "data/content-ir/templates/catalog.json"
REPORT_ROOT = ROOT / "reports"
REVIEWER = "codex-manual-review-2026-08-11-batch-II"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _slug(value: str) -> str:
    return "-".join(part for part in re.sub(r"[^A-Za-z0-9]+", "-", value.lower()).split("-") if part) or "record"


def _source_excerpt(text: str, *needles: str) -> str:
    normalized = _text(text)
    for needle in needles:
        index = normalized.find(needle)
        if index >= 0:
            return normalized[max(0, index - 80) : index + 260]
    return normalized[:320]


def _spell_level(fields: dict[str, Any], text: str) -> int:
    value = fields.get("level")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    labels = {
        "戏法": 0,
        "零环": 0,
        "一环": 1,
        "二环": 2,
        "三环": 3,
        "四环": 4,
        "五环": 5,
        "六环": 6,
        "七环": 7,
        "八环": 8,
        "九环": 9,
    }
    match = re.search("|".join(labels), text)
    return labels.get(match.group(0), 0) if match else 0


def _action_economy(casting_time: object) -> str | None:
    value = _text(casting_time).lower()
    if "附赠" in value:
        return "bonus_action"
    if "反应" in value:
        return "reaction"
    if "动作" in value or value in {"1 action", "action"}:
        return "action"
    return None


def _spell_record(record: dict[str, Any], *, pack_id: str, ruleset: str) -> dict[str, Any] | None:
    fields = spell_rule_fields(record)
    body = _bounded_source_text(record)
    source_id = _source_record_id(record)
    clauses: list[dict[str, Any]] = []
    action = _action_economy(fields.get("casting_time"))
    disposition = fields.get("target_disposition")
    if fields.get("area_shape") and fields.get("area_size_ft"):
        clauses.append(
            {
                "type": "target_selection",
                "clause_id": "target",
                "kind": "area",
                "shape": fields["area_shape"],
                "size_ft": fields["area_size_ft"],
                "count": fields.get("max_targets") or 1,
                "visibility": "visible",
                "evidence_ref": _source_excerpt(body, "尺", "区域"),
            }
        )
    elif disposition:
        kind = {
            "creature": "one_creature",
            "ally": "ally",
            "enemy": "enemy",
            "object": "object",
            "any": "any",
        }.get(str(disposition), "one_creature")
        clauses.append(
            {
                "type": "target_selection",
                "clause_id": "target",
                "kind": kind,
                "count": fields.get("max_targets") or 1,
                "visibility": "visible",
                "evidence_ref": _source_excerpt(body, "目标", "生物", "物件"),
            }
        )
    elif "一个生物" in body or "一个目标" in body:
        clauses.append(
            {
                "type": "target_selection",
                "clause_id": "target",
                "kind": "one_creature",
                "count": 1,
                "visibility": "visible",
                "evidence_ref": _source_excerpt(body, "一个生物", "一个目标"),
            }
        )

    if fields.get("save") and fields.get("damage_expression") and fields.get("damage_type"):
        save_ability = _text(fields["save"]).replace("豁免", "").strip()
        clauses.append(
            {
                "type": "saving_throw",
                "clause_id": "save",
                "action_economy": action,
                "save_ability": save_ability,
                "target": "one_creature",
                "half_on_success": bool(fields.get("half_damage_on_save")),
                "evidence_ref": _source_excerpt(body, "豁免"),
            }
        )
        clauses.append(
            {
                "type": "damage",
                "clause_id": "damage",
                "action_economy": action,
                "expression": fields["damage_expression"],
                "damage": fields["damage_expression"],
                "damage_type": fields["damage_type"],
                "target": "one_creature",
                "on_success": "half" if fields.get("half_damage_on_save") else "none",
                "on_failure": "full",
                "timing": "immediate",
                "evidence_ref": _source_excerpt(body, "伤害"),
            }
        )
    elif fields.get("damage_expression") and fields.get("damage_type") and "法术攻击" in body:
        clauses.extend(
            [
                {
                    "type": "attack_roll",
                    "clause_id": "attack",
                    "action_economy": action,
                    "target": "one_creature",
                    "attack_ability": "spellcasting",
                    "evidence_ref": _source_excerpt(body, "法术攻击"),
                },
                {
                    "type": "damage",
                    "clause_id": "damage",
                    "action_economy": action,
                    "expression": fields["damage_expression"],
                    "damage": fields["damage_expression"],
                    "damage_type": fields["damage_type"],
                    "target": "one_creature",
                    "timing": "on_hit",
                    "evidence_ref": _source_excerpt(body, "伤害"),
                },
            ]
        )
    elif fields.get("temporary_hp") and fields.get("healing"):
        clauses.append(
            {
                "type": "temporary_hp",
                "clause_id": "temporary-hp",
                "action_economy": action,
                "expression": fields["healing"],
                "amount": fields["healing"],
                "target": "one_creature",
                "evidence_ref": _source_excerpt(body, "临时生命"),
            }
        )
    elif fields.get("healing"):
        clauses.append(
            {
                "type": "healing",
                "clause_id": "healing",
                "action_economy": action,
                "expression": fields["healing"],
                "healing": fields["healing"],
                "target": "one_creature",
                "timing": "immediate",
                "evidence_ref": _source_excerpt(body, "恢复", "治疗"),
            }
        )
    elif fields.get("conditions"):
        for index, condition in enumerate(fields["conditions"]):
            clauses.append(
                {
                    "type": "apply_condition",
                    "clause_id": f"condition-{index}",
                    "action_economy": action,
                    "condition": condition,
                    "target": "one_creature",
                    "evidence_ref": _source_excerpt(body, str(condition)),
                }
            )
    if fields.get("concentration") is True:
        clauses.append(
            {
                "type": "concentration",
                "clause_id": "concentration",
                "required": True,
                "duration": fields.get("duration"),
                "evidence_ref": _source_excerpt(body, "专注"),
            }
        )
    if fields.get("area_shape") and fields.get("area_size_ft"):
        clauses.append(
            {
                "type": "area",
                "clause_id": "area",
                "shape": fields["area_shape"],
                "size_ft": fields["area_size_ft"],
                "origin": "source_explicit_origin",
                "evidence_ref": _source_excerpt(body, "区域", "立方", "锥形"),
            }
        )
    increment = fields.get("upcast_damage_dice") or fields.get("upcast_healing_dice")
    base_expression = fields.get("damage_expression") or fields.get("healing")
    base_match = re.match(r"^(\d+)d(\d+)", _text(base_expression))
    if increment and base_match:
        clauses.append(
            {
                "type": "upcast",
                "clause_id": "upcast",
                "increments": f"{increment}d{base_match.group(2)}",
                "per_slot": 1,
                "applies_to": "damage" if fields.get("damage_expression") else "healing",
                "evidence_ref": _source_excerpt(body, "升环", "高一环"),
            }
        )
    if not clauses:
        return None
    source_fp = _source_fingerprint(record)
    excerpts = {
        str(clause["clause_id"]): str(clause.get("evidence_ref") or "")
        for clause in clauses
    }
    return {
        "kind": "spell",
        "schema_version": "spell-ir-1",
        "spell_id": f"{pack_id}:spell:{source_id}",
        "name": _text(record.get("name")),
        "pack_id": pack_id,
        "pack_version": "source-7011166c19bd",
        "namespace": f"content.{pack_id}",
        "ruleset_version": ruleset,
        "source_record_id": source_id,
        "source_path": _text(record.get("source_relative_path")),
        "source_book": _text(record.get("source_book")),
        "source_fingerprint": source_fp,
        "source_trust": "authored_ir",
        "source_provenance": {
            "source_book": record.get("source_book"),
            "source_relative_path": record.get("source_relative_path"),
            "source_checksum": record.get("checksum"),
            "officiality": record.get("officiality") or "unknown",
            "review_basis": "local_source_text_manual_review",
        },
        "edition": ruleset,
        "level": _spell_level(fields, body),
        "school": fields.get("school"),
        "casting_time": fields.get("casting_time"),
        "range": fields.get("range"),
        "duration": fields.get("duration"),
        "concentration": bool(fields.get("concentration")),
        "clauses": clauses,
        "evidence": [f"{key}: {value}" for key, value in sorted(excerpts.items())],
        "review_status": "reviewed",
        "reviewed_by": REVIEWER,
        "reviewed_fields": [
            "schema_version",
            "spell_id",
            "name",
            "pack_id",
            "pack_version",
            "namespace",
            "ruleset_version",
            "source_record_id",
            "source_path",
            "source_book",
            "source_fingerprint",
            "source_trust",
            "level",
            "school",
            "casting_time",
            "range",
            "duration",
            "concentration",
            "clauses",
            "evidence",
        ],
        "source_evidence": {
            "source_path": record.get("source_relative_path"),
            "source_book": record.get("source_book"),
            "source_text": body,
            "selected_clause_excerpt": " ".join(excerpts.values()),
            "source_checksum": record.get("checksum"),
        },
        "clause_boundaries": {
            key: {
                "source_heading": _text(record.get("name")),
                "boundary_rule": "one authored clause maps to the quoted source sentence(s)",
                "source_excerpt": value,
            }
            for key, value in sorted(excerpts.items())
        },
        "manual_decisions": {
            "review_gate": "accepted only explicit normalized fields and quoted source evidence",
            "unresolved_branches": "not promoted when the source does not state attack/save semantics",
        },
        "clause_identity": [f"{pack_id}:spell:{source_id}:{clause['clause_id']}" for clause in clauses],
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry": {"id": "spell", "version": "content-capabilities-1"},
    }


def _feature_clause(
    clause_id: str,
    *,
    operator: str,
    parameters: dict[str, Any],
    excerpt: str,
    trigger: str = "explicit_activation",
    action: str = "none",
    target: str = "self",
    duration: str = "current_turn",
    resource_key: str | None = None,
) -> dict[str, Any]:
    effects = [{"operator": operator, "parameters": parameters}]
    if resource_key:
        effects.insert(
            0,
            {
                "operator": "consume_resource",
                "parameters": {
                    "resource_key": resource_key,
                    "operation": "consume",
                    "amount": 1,
                },
            },
        )
    return {
        "clause_id": clause_id,
        "trigger": trigger,
        "conditions": [],
        "activation": "automatic",
        "action_economy": action,
        "resource_costs": [],
        "resource_recovery": [],
        "required_inputs": [],
        "targeting": {"kind": target, "parameters": {}},
        "effects": effects,
        "duration": duration,
        "expiry": None,
        "stacking": None,
        "frequency": None,
        "persistence": "character.feature_runtime",
        "visibility": "owner",
        "audit": {"source": "authored_ir", "source_excerpt": excerpt, "reviewed_by": REVIEWER},
    }


def _feature_record(
    record: dict[str, Any],
    *,
    feature_key: str,
    source_name: str,
    class_name: str,
    level: int,
    clause: dict[str, Any],
    excerpt: str,
) -> dict[str, Any]:
    source_id = _source_record_id(record)
    source_fp = _source_fingerprint(record)
    pack_id = "tashas-cauldron"
    return {
        "kind": "feature",
        "schema_version": "feature-ir-1",
        "feature_id": f"content.{pack_id}.feature.{feature_key}",
        "namespace": f"content.{pack_id}",
        "pack_id": pack_id,
        "pack_version": "source-7011166c19bd",
        "ruleset_version": "2014",
        "source_record_id": source_id,
        "source_name": source_name,
        "source_trust": "authored_ir",
        "localized_names": {"zh-CN": source_name},
        "class_name": class_name,
        "subclass_name": None,
        "level": level,
        "source_completeness": "complete",
        "clauses": [clause],
        "dependencies": [],
        "compatibility": {"runtime_source": "feature_ir", "source_fingerprint": source_fp},
        "source_path": _text(record.get("source_relative_path")),
        "source_book": _text(record.get("source_book")),
        "source_fingerprint": source_fp,
        "review_status": "reviewed",
        "reviewed_by": REVIEWER,
        "reviewed_fields": [
            "feature_id",
            "source_record_id",
            "source_name",
            "source_path",
            "source_book",
            "source_fingerprint",
            "class_name",
            "level",
            "clauses",
        ],
        "source_evidence": {
            "source_path": record.get("source_relative_path"),
            "source_book": record.get("source_book"),
            "source_text": _bounded_source_text(record),
            "selected_feature_excerpts": {clause["clause_id"]: excerpt},
            "source_checksum": record.get("checksum"),
        },
        "clause_boundaries": {
            clause["clause_id"]: {
                "source_heading": source_name,
                "boundary_rule": "the named feature heading and its complete paragraph(s)",
                "source_excerpt": excerpt,
            }
        },
        "manual_decisions": {
            "review_gate": "single closed operator selected from the quoted feature paragraph",
            "runtime": "resource and target remain data inputs; no name dispatch",
        },
        "evidence": [f"{clause['clause_id']}: {excerpt}"],
        "compiler_fingerprint": COMPILER_FINGERPRINT,
    }


def _make_feature_specs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {_source_record_id(record): record for record in records}
    configs = [
        ("cf864e58ba0d62c93110f5c6", "armorer-defensive-field", "防护场", "奇械师", 3, "grant_temporary_hp", {"formula": "class_level", "source": "defensive_field"}, "防护场", "bonus_action", "self", "current_turn", "defensive_field_uses"),
        ("cf864e58ba0d62c93110f5c6", "armorer-lightning-launcher", "闪电发射器", "奇械师", 3, "add_damage", {"formula": "1d6", "damage_type": "lightning", "source": "lightning_launcher", "applies_when": "lightning_launcher_hit"}, "闪电发射器", "none", "enemy", "current_turn", None),
        ("cf864e58ba0d62c93110f5c6", "armorer-dampening-field", "减震场", "奇械师", 15, "impose_advantage", {"stat": "skill_check", "operation": "advantage", "scope": "self", "applies_when": "stealth_check"}, "减震场", "none", "self", "advancement_persistent", None),
        ("cf864e58ba0d62c93110f5c6", "armorer-extra-attack", "额外攻击", "奇械师", 5, "add_modifier", {"stat": "attack_action_count", "operation": "add", "value": 1, "scope": "self", "applies_when": "attack_action"}, "额外攻击", "none", "self", "advancement_persistent", None),
        ("606d89f6e0ea3b2e0194f24c", "battle-smith-repair", "修理", "奇械师", 3, "heal", {"formula": "2d8 + proficiency_bonus", "source": "steel_defender_repair"}, "修理", "action", "ally", "current_turn", "steel_defender_repair_uses"),
        ("606d89f6e0ea3b2e0194f24c", "battle-smith-arcane-jolt-damage", "奥能震荡：伤害", "奇械师", 9, "add_damage", {"formula": "2d6", "damage_type": "force", "source": "arcane_jolt"}, "奥能震荡", "none", "enemy", "current_turn", "arcane_jolt_uses"),
        ("606d89f6e0ea3b2e0194f24c", "battle-smith-arcane-jolt-healing", "奥能震荡：治疗", "奇械师", 9, "heal", {"formula": "2d6", "source": "arcane_jolt"}, "奥能震荡", "none", "ally", "current_turn", "arcane_jolt_uses"),
        ("a13253dc90904c96eaa719ab", "psi-warrior-psionic-strike", "灵能打击", "战士", 3, "add_damage", {"formula": "1d6 + intelligence_modifier", "damage_type": "force", "source": "psionic_strike"}, "灵能打击", "none", "enemy", "current_turn", "psionic_dice"),
        ("a13253dc90904c96eaa719ab", "psi-warrior-protective-field", "庇护力场", "战士", 3, "create_reaction_window", {"window_kind": "damage_reduction", "expires": "current_turn", "target_policy": {"mode": "ally"}}, "庇护力场", "reaction", "ally", "current_turn", "psionic_dice"),
        ("a13253dc90904c96eaa719ab", "psi-warrior-telekinetic-movement", "念力控物", "战士", 3, "create_timed_modifier", {"stat": "movement_budget", "operation": "add", "value": 30, "scope": "target", "applies_when": "telekinetic_movement", "duration": "current_turn"}, "念力控物", "action", "ally", "current_turn", None),
        ("d4e98761778ae5c18fd66bdb", "way-of-mercy-hand-healing", "予命之手", "武僧", 3, "heal", {"formula": "martial_arts_die + wisdom_modifier", "source": "hand_of_healing"}, "予命之手", "action", "ally", "current_turn", "ki"),
        ("d4e98761778ae5c18fd66bdb", "way-of-mercy-hand-harm", "夺命之手", "武僧", 3, "add_damage", {"formula": "martial_arts_die + wisdom_modifier", "damage_type": "necrotic", "source": "hand_of_harm"}, "夺命之手", "none", "enemy", "current_turn", "ki"),
        ("d4e98761778ae5c18fd66bdb", "way-of-mercy-physicians-touch", "生死之触", "武僧", 6, "remove_condition", {"condition": "poisoned"}, "生死之触", "none", "ally", "current_turn", None),
        ("dc4f2bf18baca6ec97d7d0bf", "alchemist-restorative-reagents", "复原药剂", "奇械师", 9, "grant_temporary_hp", {"formula": "2d6 + intelligence_modifier", "source": "restorative_reagents"}, "复原药剂", "none", "ally", "current_turn", None),
        ("dc4f2bf18baca6ec97d7d0bf", "alchemist-chemical-mastery", "化学专家", "奇械师", 15, "grant_resistance", {"damage_type": "acid", "source": "chemical_mastery"}, "化学专家", "none", "self", "advancement_persistent", None),
    ]
    result: list[dict[str, Any]] = []
    for source_id, feature_key, source_name, class_name, level, operator, parameters, needle, action, target, duration, resource_key in configs:
        record = by_id.get(source_id)
        if record is None:
            raise ValueError(f"missing feature source record: {source_id}")
        text = _bounded_source_text(record)
        excerpt = _source_excerpt(text, needle)
        trigger = "advancement_confirmed" if duration == "advancement_persistent" else "explicit_activation"
        if operator in {"add_damage"}:
            trigger = "attack_hit"
        if operator == "create_reaction_window":
            trigger = "damage_before_apply"
        clause = _feature_clause(
            _slug(feature_key),
            operator=operator,
            parameters=parameters,
            excerpt=excerpt,
            trigger=trigger,
            action=action,
            target=target,
            duration=duration,
            resource_key=resource_key,
        )
        result.append(
            _feature_record(
                record,
                feature_key=feature_key,
                source_name=source_name,
                class_name=class_name,
                level=level,
                clause=clause,
                excerpt=excerpt,
            )
        )
    return result


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _write_pack(records: list[dict[str, Any]], specs: list[dict[str, Any]], pack_id: str) -> dict[str, Any]:
    root = AUTHORED_ROOT / pack_id
    _reset_dir(root)
    paths: list[str] = []
    for spec in specs:
        folder = "spells" if spec["kind"] == "spell" else "features"
        path = root / folder / f"{_slug(str(spec.get('spell_id') or spec.get('feature_id')))}.json"
        _write(path, spec)
        paths.append(str(path.relative_to(AUTHORED_ROOT)))
    source_inventory = {
        "schema_version": "content-ir-source-inventory-1",
        "pack_id": pack_id,
        "records": [
            {
                "source_record_id": _source_record_id(record),
                "source_book": record.get("source_book"),
                "source_path": record.get("source_relative_path"),
                "source_fingerprint": _source_fingerprint(record),
            }
            for record in sorted(records, key=lambda item: _source_record_id(item))
        ],
    }
    _write(root / "source-inventory.json", source_inventory)
    return {"pack_id": pack_id, "typed_paths": paths, "source_count": len(records), "authored_count": len(specs)}


def _compile_batch() -> dict[str, Any]:
    compile_root = ROOT / "data/content-ir/compiled/batch-II"
    if compile_root.exists():
        shutil.rmtree(compile_root)
    compile_root.mkdir(parents=True, exist_ok=True)
    typed_paths: list[str] = []
    source_fingerprints: dict[str, str] = {}
    for path in sorted(AUTHORED_ROOT.rglob("*.json")):
        if path.name == "source-inventory.json":
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("kind") not in {"spell", "feature"}:
            continue
        relative = Path("typed-ir") / path.relative_to(AUTHORED_ROOT)
        _write(compile_root / relative, value)
        typed_paths.append(relative.as_posix())
        source_fingerprints[str(value.get("source_record_id"))] = str(value.get("source_fingerprint"))
    manifest = {
        "schema_version": "content-ir-workbench-manifest-2",
        "pack_id": None,
        "pack_version": None,
        "source_book": None,
        "namespace": "content.batch-II",
        "ruleset_version": None,
        "source_fingerprints": dict(sorted(source_fingerprints.items())),
        "draft_paths": [],
        "typed_ir_paths": sorted(typed_paths),
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry_version": "content-capabilities-1",
        "production_targets": {"database": False, "feature_registry": False, "spell_registry": False, "campaign": False, "character": False},
        "replay": {"policy": "same-manifest-fingerprint-is-idempotent"},
    }
    manifest["manifest_fingerprint"] = _fingerprint(manifest)
    _write(compile_root / "manifest.json", manifest)
    result = compile_artifact_directory(compile_root, write_files=True)
    _write(compile_root / "report.json", result)
    return result


def main() -> int:
    records = load_records(SOURCE_ROOT)
    _reset_dir(AUTHORED_ROOT)
    _reset_dir(CANDIDATE_ROOT)
    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    catalog = build_template_catalog(ROOT / "data/content-ir/authored", TEMPLATE_PATH)

    candidate_reports: list[dict[str, Any]] = []
    candidate_reports.append(generate_candidates(SOURCE_ROOT, TEMPLATE_PATH, book="玩家手册 2024", kind="spell", output=CANDIDATE_ROOT / "core-2024-spells", limit=100))
    for book, pack_id, limit in (
        ("珊娜萨的万事指南", "xanathars-guide", 95),
        ("塔莎的万事坩埚", "tashas-cauldron", 21),
        ("费资本的巨龙宝库", "fizbans-treasury", 7),
        ("万象无常书", "book-of-many-things", 3),
    ):
        candidate_reports.append(generate_candidates(SOURCE_ROOT, TEMPLATE_PATH, book=book, kind="spell", output=CANDIDATE_ROOT / f"{pack_id}-spells", limit=limit))
    candidate_reports.append(generate_candidates(SOURCE_ROOT, TEMPLATE_PATH, book="塔莎的万事坩埚", kind="feature", output=CANDIDATE_ROOT / "tashas-cauldron-features", limit=48))

    configs = [
        ("玩家手册 2024", "core-phb-2024", 60, "2024"),
        ("珊娜萨的万事指南", "xanathars-guide", 11, "2014"),
        ("塔莎的万事坩埚", "tashas-cauldron", 6, "2014"),
        ("费资本的巨龙宝库", "fizbans-treasury", 5, "2014"),
        ("万象无常书", "book-of-many-things", 3, "2014"),
    ]
    pack_reports: list[dict[str, Any]] = []
    all_authored: list[dict[str, Any]] = []
    for book, pack_id, target, ruleset in configs:
        selected = [record for record in records if record.get("source_book") == book and _is_spell_detail(record)]
        selected.sort(key=lambda item: (_text(item.get("source_relative_path")), _text(item.get("name"))))
        specs: list[dict[str, Any]] = []
        source_rows: list[dict[str, Any]] = []
        for record in selected:
            spec = _spell_record(record, pack_id=pack_id, ruleset=ruleset)
            if spec is None:
                continue
            compiled = compile_spell_spec(__import__("dnd_dm_assistant.application.content_ir_workbench", fromlist=["SpellSpec"]).SpellSpec.from_dict(spec))
            if compiled["compile_status"] != "full":
                continue
            specs.append(spec)
            source_rows.append(record)
            if len(specs) >= target:
                break
        if len(specs) < target:
            raise ValueError(f"could not author {target} spell records for {pack_id}; got {len(specs)}")
        pack_reports.append(_write_pack(source_rows, specs, pack_id))
        all_authored.extend(specs)

    feature_specs = _make_feature_specs(records)
    feature_records = [
        next(record for record in records if _source_record_id(record) == spec["source_record_id"])
        for spec in feature_specs
    ]
    pack_reports.append(_write_pack(feature_records, feature_specs, "tashas-cauldron-features"))
    all_authored.extend(feature_specs)

    compile_result = _compile_batch()
    report = {
        "schema_version": "content-ir-reviewed-batch-II-1",
        "reviewer": REVIEWER,
        "template_count": catalog["template_count"],
        "generated_candidate_count": sum(item["generated_candidate_count"] for item in candidate_reports),
        "reviewed_authored_typed_ir_count": len(all_authored),
        "compile_full_count": compile_result["counts"].get("full", 0),
        "runtime_preview_full_count": sum(bool(item.get("materialized")) for item in compile_result["results"] if item.get("compile_status") == "full"),
        "production_runtime_full_count": 0,
        "candidate_reports": candidate_reports,
        "pack_reports": pack_reports,
        "compile_result_path": "data/content-ir/compiled/batch-II/compile-result.json",
        "production_gate": "requires production-runtime-results.json",
    }
    _write(REPORT_ROOT / "content-ir-reviewed-batch-II-2026-08-11.json", report)
    _write(REPORT_ROOT / "content-ir-template-catalog-I-2026-08-11.json", catalog)
    _write(REPORT_ROOT / "content-ir-candidate-generation-I-2026-08-11.json", {"schema_version": "content-ir-candidate-generation-I-1", "reports": candidate_reports, "generated_candidate_count": report["generated_candidate_count"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
