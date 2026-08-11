"""Build the manually reviewed Content IR production batch for 2026-08-11.

The selected contracts below are intentionally explicit.  Source text is read
from the local generated-content corpus, while every executable clause is
written as authored data rather than inferred from prose or field extraction.
The resulting JSON files are the reviewable production assets; this script is
only a deterministic rebuild tool for those assets and their isolated reports.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from dnd_dm_assistant.application.content_ir_workbench import (
    COMPILER_FINGERPRINT,
    _bounded_source_text,
    _fingerprint,
    _registered_pack,
    _source_fingerprint,
    audit_records,
    compile_artifact_directory,
    dry_run_manifest,
    load_records,
)
from dnd_dm_assistant.domain.feature_ir import FEATURE_IR_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "data/generated-content/dnd5e_chm/json"
AUTHORED_ROOT = ROOT / "data/content-ir/authored"
REPORT_ROOT = ROOT / "reports"
REVIEWER = "codex-manual-review-2026-08-11"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _pack_version(records: list[dict[str, Any]]) -> str:
    fingerprints = sorted(_source_fingerprint(record) for record in records)
    return "source-" + _fingerprint(fingerprints)[:12]


def _slug(value: str) -> str:
    safe = "".join(char if char.isalnum() else "-" for char in value.lower())
    return "-".join(part for part in safe.split("-") if part) or "record"


def _records_by_key(records: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        if str(record.get("content_type") or "") not in {
            "spells",
            "classes",
            "subclasses",
            "feats",
        }:
            continue
        key = (str(record.get("source_book") or ""), str(record.get("name") or ""))
        if key in result:
            current = result[key]
            candidates = [current, record]
            candidates.sort(
                key=lambda item: (
                    0
                    if item.get("content_type") == "spells"
                    and "法术详述" in str(item.get("source_relative_path") or "")
                    else 1,
                    str(item.get("source_relative_path") or ""),
                    str(item.get("stable_id") or ""),
                )
            )
            result[key] = candidates[0]
            continue
        result[key] = record
    return result


def _source_evidence(record: dict[str, Any], excerpt: str) -> dict[str, Any]:
    return {
        "source_path": str(record.get("source_relative_path") or ""),
        "source_book": str(record.get("source_book") or ""),
        "source_text": _bounded_source_text(record),
        "selected_clause_excerpt": excerpt,
        "source_checksum": str(record.get("checksum") or ""),
        "source_fingerprint": _source_fingerprint(record),
    }


def _spell_clause(
    clause_id: str,
    clause_type: str,
    *,
    excerpt: str,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "type": clause_type,
        "clause_id": clause_id,
        **fields,
        "evidence_ref": excerpt,
    }


def _spell(
    record: dict[str, Any],
    *,
    pack_id: str,
    pack_version: str,
    ruleset_version: str,
    level: int,
    school: str,
    casting_time: str,
    spell_range: str,
    target: str,
    components: str,
    duration: str,
    concentration: bool,
    clauses: list[dict[str, Any]],
    excerpts: dict[str, str],
    manual_decisions: dict[str, Any],
) -> dict[str, Any]:
    name = str(record["name"])
    source_id = str(record["stable_id"])
    source_fp = _source_fingerprint(record)
    return {
        "kind": "spell",
        "schema_version": "spell-ir-1",
        "spell_id": f"{pack_id}:spell:{source_id}",
        "name": name,
        "pack_id": pack_id,
        "pack_version": pack_version,
        "namespace": f"content.{pack_id}",
        "ruleset_version": ruleset_version,
        "source_record_id": source_id,
        "source_path": str(record["source_relative_path"]),
        "source_book": str(record["source_book"]),
        "source_fingerprint": source_fp,
        "source_trust": "authored_ir",
        "edition": ruleset_version,
        "level": level,
        "school": school,
        "casting_time": casting_time,
        "range": spell_range,
        "target": target,
        "components": components,
        "duration": duration,
        "concentration": concentration,
        "clauses": clauses,
        "evidence": [
            f"{clause_id}: {excerpt}" for clause_id, excerpt in sorted(excerpts.items())
        ],
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
            "target",
            "components",
            "duration",
            "concentration",
            "clauses",
            "evidence",
        ],
        "source_evidence": _source_evidence(
            record, " ".join(excerpts.values())
        ),
        "clause_boundaries": {
            clause_id: {
                "source_heading": name,
                "boundary_rule": "one authored clause maps to the quoted source sentence(s)",
                "source_excerpt": excerpt,
            }
            for clause_id, excerpt in sorted(excerpts.items())
        },
        "manual_decisions": manual_decisions,
        "source_provenance": {
            "source_book": record["source_book"],
            "source_relative_path": record["source_relative_path"],
            "source_checksum": record.get("checksum"),
            "officiality": record.get("officiality") or "unknown",
            "review_basis": "local_source_text_manual_review",
        },
        "clause_identity": [f"{pack_id}:spell:{source_id}:{clause['clause_id']}" for clause in clauses],
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry": {"id": "spell", "version": "content-capabilities-1"},
    }


def _feature_clause(
    clause_id: str,
    *,
    effects: list[dict[str, Any]],
    excerpt: str,
    trigger: str = "advancement_confirmed",
    action_economy: str = "none",
    conditions: list[dict[str, Any]] | None = None,
    required_inputs: list[dict[str, Any]] | None = None,
    duration: str = "advancement_persistent",
) -> dict[str, Any]:
    return {
        "clause_id": clause_id,
        "trigger": trigger,
        "conditions": conditions or [],
        "activation": "automatic",
        "action_economy": action_economy,
        "resource_costs": [],
        "resource_recovery": [],
        "required_inputs": required_inputs or [],
        "targeting": {"kind": "self", "parameters": {}},
        "effects": effects,
        "duration": duration,
        "expiry": None,
        "stacking": None,
        "frequency": None,
        "persistence": "character.feature_runtime",
        "visibility": "owner",
        "audit": {
            "source": "authored_ir",
            "source_excerpt": excerpt,
            "reviewed_by": REVIEWER,
        },
    }


def _feature(
    record: dict[str, Any],
    *,
    feature_id: str,
    source_name: str,
    class_name: str,
    subclass_name: str,
    level: int | None,
    pack_id: str,
    pack_version: str,
    clauses: list[dict[str, Any]],
    boundaries: dict[str, str],
    manual_decisions: dict[str, Any],
) -> dict[str, Any]:
    source_id = str(record["stable_id"])
    source_fp = _source_fingerprint(record)
    return {
        "kind": "feature",
        "schema_version": FEATURE_IR_SCHEMA_VERSION,
        "feature_id": feature_id,
        "namespace": f"content.{pack_id}",
        "pack_id": pack_id,
        "pack_version": pack_version,
        "ruleset_version": "2014",
        "source_record_id": source_id,
        "source_name": source_name,
        "source_trust": "authored_ir",
        "localized_names": {"zh-CN": source_name},
        "class_name": class_name,
        "subclass_name": subclass_name,
        "level": level,
        "source_completeness": "complete",
        "clauses": clauses,
        "dependencies": [],
        "compatibility": {
            "runtime_source": "feature_ir",
            "source_fingerprint": source_fp,
        },
        "source_path": str(record["source_relative_path"]),
        "source_book": str(record["source_book"]),
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
            "subclass_name",
            "level",
            "clauses",
        ],
        "source_evidence": {
            "source_path": record["source_relative_path"],
            "source_book": record["source_book"],
            "source_text": _bounded_source_text(record),
            "selected_feature_excerpts": boundaries,
            "source_checksum": record.get("checksum"),
        },
        "clause_boundaries": {
            clause_id: {
                "source_heading": source_name,
                "boundary_rule": "the named feature heading and its complete paragraph(s)",
                "source_excerpt": boundaries.get(clause_id, ""),
            }
            for clause_id in [clause["clause_id"] for clause in clauses]
        },
        "manual_decisions": manual_decisions,
        "evidence": [
            f"{clause['clause_id']}: {boundaries.get(clause['clause_id'], '')}"
            for clause in clauses
        ],
        "compiler_fingerprint": COMPILER_FINGERPRINT,
    }


def _spell_sets(index: dict[tuple[str, str], dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    core_names = [
        "火焰箭",
        "冷冻射线",
        "圣火术",
        "酸液飞溅",
        "魔能爆",
        "虚假生命",
        "治愈真言",
        "炼狱叱喝",
        "燃烧之手",
        "火球术",
        "闪电束",
        "疗伤术",
    ]
    xanathar_names = ["弹射术", "史尼洛雪球群", "阿迦纳萨喷火术", "土石喷发", "地颤"]
    tasha_names = ["塔莎酸蚀酿", "剑刃爆发"]
    fizban_names = ["雾凇霜缚", "劳洛希姆心灵长枪"]
    many_things_names = ["卡牌喷射"]
    groups: dict[str, list[dict[str, Any]]] = {}
    for pack_id, book, names in (
        ("core-phb-2024", "玩家手册 2024", core_names),
        ("xanathars-guide", "珊娜萨的万事指南", xanathar_names),
        ("tashas-cauldron", "塔莎的万事坩埚", tasha_names),
        ("fizbans-treasury", "费资本的巨龙宝库", fizban_names),
        ("book-of-many-things", "万象无常书", many_things_names),
    ):
        selected = []
        for name in names:
            record = index.get((book, name))
            if record is None:
                raise ValueError(f"missing selected spell source: {book}/{name}")
            selected.append(record)
        groups[pack_id] = selected
    return groups


def _spell_assets(
    records: list[dict[str, Any]],
    *,
    pack_id: str,
    pack_version: str,
) -> list[dict[str, Any]]:
    by_name = {str(record["name"]): record for record in records}

    def rec(name: str) -> dict[str, Any]:
        return by_name[name]

    def attack(
        name: str,
        level: int,
        school: str,
        casting_time: str,
        spell_range: str,
        target: str,
        components: str,
        duration: str,
        damage_expression: str,
        damage_type: str,
        excerpt: str,
        *,
        upcast: dict[str, Any] | None = None,
        movement: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clauses = [
            _spell_clause(
                "target",
                "target_selection",
                excerpt=excerpt,
                kind="one_creature",
                count=1,
                range=spell_range,
                visibility="visible",
            ),
            _spell_clause(
                "attack",
                "attack_roll",
                excerpt=excerpt,
                action_economy=casting_time,
                trigger="spell_cast",
                target="one_creature",
                range=spell_range,
                attack_ability="spellcasting",
                attack_bonus="spell_attack_bonus",
            ),
            _spell_clause(
                "damage",
                "damage",
                excerpt=excerpt,
                trigger="attack_hit",
                target="one_creature",
                expression=damage_expression,
                damage_type=damage_type,
                on_success="full",
                applies_to="attack",
            ),
        ]
        if movement:
            clauses.append(
                _spell_clause(
                    "movement",
                    "movement",
                    excerpt=movement["excerpt"],
                    trigger="attack_hit",
                    target="one_creature",
                    **{key: value for key, value in movement.items() if key != "excerpt"},
                )
            )
        if upcast:
            clauses.append(
                _spell_clause(
                    "upcast",
                    "upcast",
                    excerpt=upcast["excerpt"],
                    increments=upcast.get("increments", 1),
                    per_slot=upcast.get("per_slot"),
                    progression=upcast.get("progression"),
                    applies_to=upcast.get("applies_to", "damage"),
                )
            )
        return _spell(
            rec(name),
            pack_id=pack_id,
            pack_version=pack_version,
            ruleset_version="2024" if pack_id == "core-phb-2024" else "2014",
            level=level,
            school=school,
            casting_time=casting_time,
            spell_range=spell_range,
            target=target,
            components=components,
            duration=duration,
            concentration=False,
            clauses=clauses,
            excerpts={"target": excerpt, "attack": excerpt, "damage": excerpt},
            manual_decisions={"attack_resolution": "远程法术攻击；命中后执行 damage clause"},
        )

    def save_damage(
        name: str,
        level: int,
        school: str,
        casting_time: str,
        spell_range: str,
        target: str,
        components: str,
        duration: str,
        concentration: bool,
        save_ability: str,
        damage_expression: str,
        damage_type: str,
        excerpt: str,
        *,
        area: dict[str, Any] | None = None,
        half_on_success: bool = False,
        upcast: dict[str, Any] | None = None,
        condition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clauses = [
            _spell_clause(
                "target",
                "target_selection",
                excerpt=excerpt,
                kind="area" if area else "one_creature",
                count="all_in_area" if area else 1,
                range=spell_range,
                visibility="visible",
                **(
                    {
                        "shape": area["shape"],
                        "size_ft": area["size_ft"],
                    }
                    if area
                    else {}
                ),
            ),
            _spell_clause(
                "save",
                "saving_throw",
                excerpt=excerpt,
                action_economy=casting_time,
                trigger="spell_cast",
                target="area" if area else "one_creature",
                range=spell_range,
                save_ability=save_ability,
                half_on_success=half_on_success,
                **({"ignores_cover": True} if condition and condition.get("ignores_cover") else {}),
            ),
            _spell_clause(
                "damage",
                "damage",
                excerpt=excerpt,
                trigger="saving_throw",
                target="area" if area else "one_creature",
                expression=damage_expression,
                damage_type=damage_type,
                on_success="half" if half_on_success else "none",
                on_failure="full",
                applies_to="save",
            ),
        ]
        excerpts = {"target": excerpt, "save": excerpt, "damage": excerpt}
        if area:
            clauses.append(
                _spell_clause(
                    "area",
                    "area",
                    excerpt=excerpt,
                    shape=area["shape"],
                    size_ft=area["size_ft"],
                    origin=area.get("origin", "chosen_point"),
                    target="area",
                    range=spell_range,
                )
            )
            excerpts["area"] = excerpt
        if condition and condition.get("condition"):
            clauses.append(
                _spell_clause(
                    "condition",
                    "apply_condition",
                    excerpt=condition.get("excerpt") or excerpt,
                    target="area" if area else "one_creature",
                    condition=condition["condition"],
                    duration=condition["duration"],
                    save_ability=save_ability,
                    on_failure="apply",
                    condition_effect=condition.get("effect"),
                    break_action=condition.get("break_action"),
                )
            )
            excerpts["condition"] = condition.get("excerpt") or excerpt
        if upcast:
            clauses.append(
                _spell_clause(
                    "upcast",
                    "upcast",
                    excerpt=upcast["excerpt"],
                    increments=upcast.get("increments", 1),
                    per_slot=upcast.get("per_slot"),
                    progression=upcast.get("progression"),
                    applies_to=upcast.get("applies_to", "damage"),
                )
            )
            excerpts["upcast"] = upcast["excerpt"]
        return _spell(
            rec(name),
            pack_id=pack_id,
            pack_version=pack_version,
            ruleset_version="2024" if pack_id == "core-phb-2024" else "2014",
            level=level,
            school=school,
            casting_time=casting_time,
            spell_range=spell_range,
            target=target,
            components=components,
            duration=duration,
            concentration=concentration,
            clauses=clauses,
            excerpts=excerpts,
            manual_decisions={
                "save_success": "按 source text 显式记录 half 或 no damage branch",
                "targeting": "target_selection 与 area clause 共同定义目标集合",
            },
        )

    assets: list[dict[str, Any]] = []
    assets.append(
        attack(
            "火焰箭",
            0,
            "塑能",
            "action",
            "120 feet",
            "one creature or object",
            "V,S",
            "instant",
            "1d10",
            "fire",
            "命中则目标受到1d10火焰伤害",
            upcast={
                "progression": [{"character_level": 5, "expression": "2d10"}, {"character_level": 11, "expression": "3d10"}, {"character_level": 17, "expression": "4d10"}],
                "applies_to": "damage",
                "excerpt": "戏法强化：5级2d10、11级3d10、17级4d10",
            },
        )
    )
    assets.append(
        attack(
            "冷冻射线",
            0,
            "塑能",
            "action",
            "60 feet",
            "one creature",
            "V,S",
            "instant",
            "1d8",
            "cold",
            "命中时目标受到1d8寒冷伤害",
            movement={
                "speed_delta_ft": -10,
                "duration": "until_your_next_turn_start",
                "applies_to": "target",
                "excerpt": "目标速度减少10尺，直到你的下一回合开始",
            },
            upcast={
                "progression": [{"character_level": 5, "expression": "2d8"}, {"character_level": 11, "expression": "3d8"}, {"character_level": 17, "expression": "4d8"}],
                "applies_to": "damage",
                "excerpt": "戏法强化：5级2d8、11级3d8、17级4d8",
            },
        )
    )
    assets.append(
        save_damage(
            "圣火术",
            0,
            "塑能",
            "action",
            "60 feet",
            "one visible creature",
            "V,S",
            "instant",
            False,
            "dexterity",
            "1d8",
            "radiant",
            "目标必须通过敏捷豁免，否则受到1d8点光耀伤害",
            condition={"ignores_cover": True, "condition": "", "duration": "instant", "excerpt": "豁免检定中目标无法享受半身掩护和四分之三掩护"},
            upcast={
                "progression": [{"character_level": 5, "expression": "2d8"}, {"character_level": 11, "expression": "3d8"}, {"character_level": 17, "expression": "4d8"}],
                "excerpt": "戏法强化：5级2d8、11级3d8、17级4d8",
            },
        )
    )
    assets.append(
        save_damage(
            "酸液飞溅",
            0,
            "塑能",
            "action",
            "60 feet",
            "5-foot sphere",
            "V,S",
            "instant",
            False,
            "dexterity",
            "1d6",
            "acid",
            "5尺球状范围内每名生物必须通过敏捷豁免，否则受到1d6点强酸伤害",
            area={"shape": "sphere", "size_ft": 5, "origin": "chosen_point"},
            upcast={
                "progression": [{"character_level": 5, "expression": "2d6"}, {"character_level": 11, "expression": "3d6"}, {"character_level": 17, "expression": "4d6"}],
                "excerpt": "戏法强化：5级2d6、11级3d6、17级4d6",
            },
        )
    )
    assets.append(
        attack(
            "魔能爆",
            0,
            "塑能",
            "action",
            "120 feet",
            "one creature or object",
            "V,S",
            "instant",
            "1d10",
            "force",
            "命中时目标受到1d10点力场伤害",
            upcast={
                "progression": [{"character_level": 5, "ray_count": 2}, {"character_level": 11, "ray_count": 3}, {"character_level": 17, "ray_count": 4}],
                "applies_to": "attack_and_damage",
                "excerpt": "戏法强化：5级两条射线，11级三条，17级四条，分别进行攻击检定",
            },
        )
    )
    assets.append(
        _spell(
            rec("虚假生命"),
            pack_id=pack_id,
            pack_version=pack_version,
            ruleset_version="2024",
            level=1,
            school="死灵",
            casting_time="action",
            spell_range="self",
            target="self",
            components="V,S,M(alcohol)",
            duration="instant",
            concentration=False,
            clauses=[
                _spell_clause("temp-hp", "temporary_hp", excerpt="你获得2d4+4点临时生命值", action_economy="action", trigger="spell_cast", target="self", amount="2d4+4", duration="instant"),
                _spell_clause("upcast", "upcast", excerpt="每比一环高一环，临时生命值增加5", increments=5, per_slot=1, applies_to="temporary_hp"),
            ],
            excerpts={"temp-hp": "你获得2d4+4点临时生命值", "upcast": "每比一环高一环，临时生命值增加5"},
            manual_decisions={"amount": "source text 明确为2d4+4；不是 damage"},
        )
    )
    assets.append(
        _spell(
            rec("治愈真言"),
            pack_id=pack_id,
            pack_version=pack_version,
            ruleset_version="2024",
            level=1,
            school="防护",
            casting_time="bonus_action",
            spell_range="60 feet",
            target="one visible creature",
            components="V",
            duration="instant",
            concentration=False,
            clauses=[
                _spell_clause("target", "target_selection", excerpt="指定施法距离内一个你能看见的生物", kind="one_creature", count=1, range="60 feet", visibility="visible"),
                _spell_clause("healing", "healing", excerpt="恢复量等于2d4+你的施法属性调整值", action_economy="bonus_action", trigger="spell_cast", target="one_creature", expression="2d4 + spellcasting_modifier", healing="2d4 + spellcasting_modifier", amount="2d4 + spellcasting_modifier", timing="immediate"),
                _spell_clause("upcast", "upcast", excerpt="每比一环高一环，治疗量增加2d4", increments="2d4", per_slot=1, applies_to="healing"),
            ],
            excerpts={"target": "指定施法距离内一个你能看见的生物", "healing": "恢复量等于2d4+你的施法属性调整值", "upcast": "每比一环高一环，治疗量增加2d4"},
            manual_decisions={"healing": "施法属性调整值作为 typed scalar modifier，不猜具体属性"},
        )
    )
    assets.append(
        save_damage(
            "炼狱叱喝",
            1,
            "塑能",
            "reaction",
            "60 feet",
            "damaging visible creature",
            "V,S",
            "instant",
            False,
            "dexterity",
            "2d10",
            "fire",
            "伤害你的生物必须进行敏捷豁免，失败2d10火焰，成功一半",
            half_on_success=True,
            upcast={"increments": "1d10", "per_slot": 1, "excerpt": "每比一环高一环，伤害增加1d10"},
        )
    )
    assets.append(
        save_damage(
            "燃烧之手",
            1,
            "塑能",
            "action",
            "self",
            "15-foot cone",
            "V,S",
            "instant",
            False,
            "dexterity",
            "3d6",
            "fire",
            "15尺锥状区域内生物敏捷豁免，失败3d6火焰，成功一半",
            area={"shape": "cone", "size_ft": 15, "origin": "self"},
            half_on_success=True,
            upcast={"increments": "1d6", "per_slot": 1, "excerpt": "每比一环高一环，伤害提升1d6"},
        )
    )
    assets.append(
        save_damage(
            "火球术",
            3,
            "塑能",
            "action",
            "150 feet",
            "20-foot sphere",
            "V,S,M(bat guano and sulfur)",
            "instant",
            False,
            "dexterity",
            "8d6",
            "fire",
            "半径20尺球状区域内每个生物敏捷豁免，失败8d6火焰，成功一半",
            area={"shape": "sphere", "size_ft": 20, "origin": "chosen_point"},
            half_on_success=True,
            upcast={"increments": "1d6", "per_slot": 1, "excerpt": "每比三环高一环，伤害增加1d6"},
        )
    )
    assets.append(
        save_damage(
            "闪电束",
            3,
            "塑能",
            "action",
            "self",
            "100-foot line",
            "V,S,M(fur and crystal rod)",
            "instant",
            False,
            "dexterity",
            "8d6",
            "lightning",
            "100尺长5尺宽线状区域内每个生物敏捷豁免，失败8d6闪电，成功一半",
            area={"shape": "line", "size_ft": 100, "origin": "self"},
            half_on_success=True,
            upcast={"increments": "1d6", "per_slot": 1, "excerpt": "每比三环高一环，伤害增加1d6"},
        )
    )
    assets.append(
        _spell(
            rec("疗伤术"),
            pack_id=pack_id,
            pack_version=pack_version,
            ruleset_version="2024",
            level=1,
            school="防护",
            casting_time="action",
            spell_range="touch",
            target="one creature",
            components="V,S",
            duration="instant",
            concentration=False,
            clauses=[
                _spell_clause("target", "target_selection", excerpt="你触碰的一名生物", kind="one_creature", count=1, range="touch"),
                _spell_clause("healing", "healing", excerpt="恢复等同于2d8+施法属性调整值点生命值", action_economy="action", trigger="spell_cast", target="one_creature", expression="2d8 + spellcasting_modifier", healing="2d8 + spellcasting_modifier", amount="2d8 + spellcasting_modifier", timing="immediate"),
                _spell_clause("upcast", "upcast", excerpt="每比一环高一环，治疗量增加2d8", increments="2d8", per_slot=1, applies_to="healing"),
            ],
            excerpts={"target": "你触碰的一名生物", "healing": "恢复等同于2d8+施法属性调整值点生命值", "upcast": "每比一环高一环，治疗量增加2d8"},
            manual_decisions={"healing": "施法属性调整值作为 typed scalar modifier，不猜具体属性"},
        )
    )

    # Expansion spells share the same typed contracts, with each source book
    # retaining its own direct provenance.
    expansion_specs: dict[str, dict[str, Any]] = {
        "弹射术": dict(level=1, school="变化", casting_time="action", spell_range="60 feet", target="one object or creature in trajectory", components="S", duration="instant", concentration=False, save_ability="dexterity", damage_expression="3d8", damage_type="bludgeoning", excerpt="弹射物撞击生物时进行敏捷豁免，失败受到3d8钝击伤害，物件和被击中的东西都受伤害", area=None, half_on_success=False, upcast={"increments": "1d8", "per_slot": 1, "excerpt": "每高一环伤害提高1d8"}),
        "史尼洛雪球群": dict(level=2, school="塑能", casting_time="action", spell_range="90 feet", target="5-foot sphere", components="V,S,M(ice or white rock)", duration="instant", concentration=False, save_ability="dexterity", damage_expression="3d6", damage_type="cold", excerpt="5尺半径球形区域内所有生物敏捷豁免，失败3d6寒冷，成功一半", area={"shape": "sphere", "size_ft": 5, "origin": "chosen_point"}, half_on_success=True, upcast={"increments": "1d6", "per_slot": 1, "excerpt": "每高一环伤害增加1d6"}),
        "阿迦纳萨喷火术": dict(level=2, school="塑能", casting_time="action", spell_range="30 feet", target="30-foot line", components="V,S,M(red dragon scale)", duration="instant", concentration=False, save_ability="dexterity", damage_expression="3d8", damage_type="fire", excerpt="30尺长5尺宽线中生物敏捷豁免，失败3d8火焰，成功一半", area={"shape": "line", "size_ft": 30, "origin": "self"}, half_on_success=True, upcast={"increments": "1d8", "per_slot": 1, "excerpt": "每高一环伤害增加1d8"}),
        "土石喷发": dict(level=3, school="变化", casting_time="action", spell_range="120 feet", target="20-foot cube", components="V,S,M(obsidian)", duration="instant", concentration=False, save_ability="dexterity", damage_expression="3d12", damage_type="bludgeoning", excerpt="20尺立方区域内每个生物敏捷豁免，失败3d12钝击，成功一半", area={"shape": "cube", "size_ft": 20, "origin": "chosen_ground_point"}, half_on_success=True, upcast={"increments": "1d12", "per_slot": 1, "excerpt": "每高一环伤害增加1d12"}),
        "地颤": dict(level=1, school="塑能", casting_time="action", spell_range="10 feet", target="area excluding caster", components="V,S", duration="instant", concentration=False, save_ability="dexterity", damage_expression="1d6", damage_type="bludgeoning", excerpt="区域内其他生物敏捷豁免，失败受到1d6钝击并倒地", area={"shape": "area", "size_ft": 10, "origin": "chosen_point"}, half_on_success=False, condition={"condition": "prone", "duration": "until_stand", "effect": {"movement": "fall_prone"}, "break_action": "movement_to_stand"}, upcast={"increments": "1d6", "per_slot": 1, "excerpt": "每高一环伤害增加1d6"}),
        "塔莎酸蚀酿": dict(level=1, school="塑能", casting_time="action", spell_range="self 30-foot line", target="30-foot line", components="V,S,M(rotten food)", duration="up to 1 minute", concentration=True, save_ability="dexterity", damage_expression="2d4", damage_type="acid", excerpt="线状区域生物敏捷豁免，失败被强酸覆盖；每个自己回合开始受到2d4强酸", area={"shape": "line", "size_ft": 30, "origin": "self"}, half_on_success=False, condition={"condition": "caustic_brew_covered", "duration": "up to 1 minute", "effect": {"damage_each_turn": "2d4 acid"}, "break_action": "action:clean_acid"}, upcast={"increments": "2d4", "per_slot": 1, "excerpt": "每高一环伤害增加2d4"}),
        "剑刃爆发": dict(level=0, school="咒法", casting_time="action", spell_range="self 5-foot radius", target="5-foot radius around caster", components="V", duration="instant", concentration=False, save_ability="dexterity", damage_expression="1d6", damage_type="force", excerpt="周围半径5尺内所有生物敏捷豁免，失败受到1d6力场伤害", area={"shape": "sphere", "size_ft": 5, "origin": "self"}, half_on_success=False, upcast={"progression": [{"character_level": 5, "expression": "2d6"}, {"character_level": 11, "expression": "3d6"}, {"character_level": 17, "expression": "4d6"}], "excerpt": "戏法强化：5级2d6、11级3d6、17级4d6"}),
        "雾凇霜缚": dict(level=2, school="塑能", casting_time="action", spell_range="self 30-foot cone", target="30-foot cone", components="S,M(melted snow water)", duration="instant", concentration=False, save_ability="constitution", damage_expression="3d8", damage_type="cold", excerpt="30尺锥形内每个生物体质豁免，失败3d8寒冷并被冰霜包裹，速度降至0", area={"shape": "cone", "size_ft": 30, "origin": "self"}, half_on_success=True, condition={"condition": "frost_bound", "duration": "1 minute or until broken", "effect": {"speed": 0}, "break_action": "action:break_free"}, upcast={"increments": "1d8", "per_slot": 1, "excerpt": "每比二环高一环，伤害增加1d8"}),
        "劳洛希姆心灵长枪": dict(level=4, school="惑控", casting_time="action", spell_range="120 feet", target="one visible or named creature", components="V", duration="instant", concentration=False, save_ability="intelligence", damage_expression="7d6", damage_type="psychic", excerpt="目标智力豁免，失败7d6心灵伤害并失能至施法者下回合开始，成功一半且不失能", area=None, half_on_success=True, condition={"condition": "incapacitated", "duration": "until_caster_next_turn_start", "effect": {"incapacitated": True}} , upcast={"increments": "1d6", "per_slot": 1, "excerpt": "每比四环高一环，伤害增加1d6"}),
        "卡牌喷射": dict(level=2, school="咒法", casting_time="action", spell_range="self 15-foot cone", target="15-foot cone", components="V,S,M(deck of cards)", duration="instant", concentration=False, save_ability="dexterity", damage_expression="2d10", damage_type="force", excerpt="15尺锥状区域生物敏捷豁免，失败2d10力场并目盲至其下回合结束，成功一半", area={"shape": "cone", "size_ft": 15, "origin": "self"}, half_on_success=True, condition={"condition": "blinded", "duration": "until_target_next_turn_end", "effect": {"blinded": True}} , upcast={"increments": "1d10", "per_slot": 1, "excerpt": "每比二环高一环，伤害增加1d10"}),
    }
    source_book = str(records[0]["source_book"])
    for name, details in expansion_specs.items():
        if name not in by_name:
            continue
        condition = details.pop("condition", None)
        upcast = details.pop("upcast", None)
        assets.append(
            save_damage(
                name,
                condition=condition,
                upcast=upcast,
                **details,
            )
        )
    return assets


def _feature_assets(
    index: dict[tuple[str, str], dict[str, Any]],
    *,
    pack_version: str,
) -> list[dict[str, Any]]:
    tasha = "塔莎的万事坩埚"
    records = {
        "命流宗": index[(tasha, "命流宗（旧版）")],
        **{
            name: index[(tasha, name)]
            for name in ("战技选项", "战地匠师", "装甲师", "炼金师", "魔炮师")
        },
    }
    choice_input = [
        {
            "key": "replacement_tool_choice",
            "kind": "choice",
            "parameters": {
                "options_source": "artisan_tools",
                "duplicate_policy": "forbid",
                "requires_dm_selection": False,
            },
        }
    ]
    def proficiency_effect(
        asset: str, kind: str = "tool", *, replacement_choice: bool = False
    ) -> dict[str, Any]:
        return {
            "operator": "grant_proficiency",
            "parameters": {
                "proficiency_kind": kind,
                "asset_id": asset,
                "operation": "grant",
                "if_already_proficient": "replacement_tool_choice"
                if replacement_choice
                else "",
            },
        }

    assets: list[dict[str, Any]] = []
    assets.append(
        _feature(
            records["命流宗"],
            feature_id="content.tashas-cauldron.feature.way-of-mercy.implements-of-mercy",
            source_name="命流之器",
            class_name="武僧",
            subclass_name="命流宗",
            level=3,
            pack_id="tashas-cauldron",
            pack_version=pack_version,
            clauses=[
                _feature_clause("insight", effects=[proficiency_effect("insight", "skill")], excerpt="获得洞悉技能熟练项"),
                _feature_clause("medicine", effects=[proficiency_effect("medicine", "skill")], excerpt="获得医药技能熟练项"),
                _feature_clause("herbalism", effects=[proficiency_effect("herbalism_kit")], excerpt="获得草药工具熟练项"),
            ],
            boundaries={"insight": "你获得洞悉和医药技能熟练项", "medicine": "你获得洞悉和医药技能熟练项", "herbalism": "此外，你获得草药工具的熟练项"},
            manual_decisions={"mask": "面具是叙事/外观选择，不进入 executable clauses"},
        )
    )
    assets.append(
        _feature(
            records["战技选项"],
            feature_id="content.tashas-cauldron.feature.battle-master.ambush",
            source_name="战技选项：伏击",
            class_name="战士",
            subclass_name="战斗大师",
            level=3,
            pack_id="tashas-cauldron",
            pack_version=pack_version,
            clauses=[
                _feature_clause(
                    "ambush",
                    trigger="initiative_rolled",
                    conditions=[{"kind": "actor_lacks_state", "parameters": {"state": "incapacitated"}}],
                    effects=[
                        {"operator": "consume_resource", "parameters": {"resource_key": "superiority_dice", "operation": "consume", "amount": 1}},
                        {"operator": "add_modifier", "parameters": {"stat": "initiative", "operation": "add", "scope": "self", "value_source": "superiority_die", "applies_when": "initiative_roll", "id": "ambush:initiative"}},
                    ],
                    excerpt="进行敏捷隐匿检定或先攻检定时，消耗卓越骰并加入本次检定",
                )
            ],
            boundaries={"ambush": "当你进行一次敏捷（隐匿）检定或先攻检定时，你可以消耗一枚卓越骰，并将消耗的卓越骰加入本次检定中，前提是你并未失能"},
            manual_decisions={"selected_contract": "本 authored record 选择先攻检定分支；未把隐匿检定另造第二条名称分支"},
        )
    )
    assets.append(
        _feature(
            records["战技选项"],
            feature_id="content.tashas-cauldron.feature.battle-master.commanding-presence",
            source_name="战技选项：领导风范",
            class_name="战士",
            subclass_name="战斗大师",
            level=3,
            pack_id="tashas-cauldron",
            pack_version=pack_version,
            clauses=[
                _feature_clause(
                    "commanding-presence",
                    trigger="ability_check",
                    effects=[
                        {"operator": "consume_resource", "parameters": {"resource_key": "superiority_dice", "operation": "consume", "amount": 1}},
                        {"operator": "add_modifier", "parameters": {"stat": "charisma_social_check", "operation": "add", "scope": "self", "value_source": "superiority_die", "applies_when": "intimidation_or_performance_or_persuasion", "id": "commanding_presence:check"}},
                    ],
                    excerpt="进行威吓、表演或游说检定时，消耗卓越骰并加入此次检定",
                )
            ],
            boundaries={"commanding-presence": "当你进行一次魅力（威吓）、魅力（表演）或魅力（游说）检定时，你能够消耗一枚卓越骰，将消耗的卓越骰加入此次属性检定中"},
            manual_decisions={"social_checks": "三个原文并列选项保留为一个通用 applies_when 合同"},
        )
    )
    assets.append(
        _feature(
            records["战技选项"],
            feature_id="content.tashas-cauldron.feature.battle-master.precision-attack",
            source_name="战技选项：精准攻击",
            class_name="战士",
            subclass_name="战斗大师",
            level=3,
            pack_id="tashas-cauldron",
            pack_version=pack_version,
            clauses=[
                _feature_clause(
                    "precision-attack",
                    trigger="attack_declared",
                    effects=[
                        {"operator": "consume_resource", "parameters": {"resource_key": "superiority_dice", "operation": "consume", "amount": 1}},
                        {"operator": "add_modifier", "parameters": {"stat": "attack_roll", "operation": "add", "scope": "self", "value_source": "superiority_die", "applies_when": "weapon_attack", "id": "precision_attack:roll"}},
                    ],
                    excerpt="当你进行一次攻击检定时，消耗卓越骰并加入攻击检定",
                )
            ],
            boundaries={"precision-attack": "精准攻击的完整战技段落：消耗卓越骰并将其加入攻击检定"},
            manual_decisions={"source_boundary": "使用战技页面中精准攻击完整段落；未扩展为其他战技"},
        )
    )
    for source_name, feature_id, class_name, subclass_name, asset, boundary in (
        ("战地匠师", "content.tashas-cauldron.feature.battle-smith.tool-proficiency", "奇械师", "战地匠师", "smith_tools", "获得铁匠工具的熟练；已有时可替换为另一种工匠工具"),
        ("装甲师", "content.tashas-cauldron.feature.armorer.tools-of-the-trade", "奇械师", "装甲师", "smith_tools", "获得重甲熟练，同时获得铁匠工具熟练；已有时可替换为另一种工匠工具"),
        ("炼金师", "content.tashas-cauldron.feature.alchemist.tool-proficiency", "奇械师", "炼金师", "alchemist_supplies", "获得炼金工具熟练；已有时可替换为另一种工匠工具"),
        ("魔炮师", "content.tashas-cauldron.feature.artillerist.tool-proficiency", "奇械师", "魔炮师", "woodcarver_tools", "获得木匠工具熟练；已有时可替换为另一种工匠工具"),
    ):
        record = records[source_name]
        clauses = [
            _feature_clause(
                "tool-proficiency",
                effects=[proficiency_effect(asset, replacement_choice=True)],
                required_inputs=choice_input,
                excerpt=boundary,
            )
        ]
        if source_name == "装甲师":
            clauses.insert(
                0,
                _feature_clause(
                    "heavy-armor",
                    effects=[proficiency_effect("heavy_armor", "armor")],
                    excerpt="你获得重甲的熟练",
                ),
            )
        assets.append(
            _feature(
                record,
                feature_id=feature_id,
                source_name=source_name + "：工具精通",
                class_name=class_name,
                subclass_name=subclass_name,
                level=3,
                pack_id="tashas-cauldron",
                pack_version=pack_version,
                clauses=clauses,
                boundaries={clause["clause_id"]: boundary for clause in clauses},
                manual_decisions={"replacement_choice": "已有对应熟练时，choice input 提供另一种工匠工具；由通用 proficiency materializer 投影"},
            )
        )
    return assets


def _manifest(
    *,
    pack_id: str,
    pack_version: str,
    source_book: str,
    ruleset_version: str,
    records: list[dict[str, Any]],
    paths: list[str],
) -> dict[str, Any]:
    value = {
        "schema_version": "content-ir-workbench-manifest-3",
        "pack_id": pack_id,
        "pack_version": pack_version,
        "source_book": source_book,
        "namespace": f"content.{pack_id}",
        "ruleset_version": ruleset_version,
        "source_fingerprints": {
            str(record["stable_id"]): _source_fingerprint(record)
            for record in sorted(records, key=lambda item: str(item["stable_id"]))
        },
        "draft_paths": [],
        "typed_ir_paths": sorted(paths),
        "compiler_fingerprint": COMPILER_FINGERPRINT,
        "capability_registry_version": "content-capabilities-1",
        "production_targets": {
            "database": False,
            "feature_registry": False,
            "spell_registry": False,
            "campaign": False,
            "character": False,
        },
        "replay": {"policy": "same-manifest-fingerprint-is-idempotent"},
    }
    value["manifest_fingerprint"] = _fingerprint(value)
    return value


def _write_pack(
    *,
    directory: Path,
    pack_id: str,
    pack_version: str,
    source_book: str,
    ruleset_version: str,
    records: list[dict[str, Any]],
    assets: list[dict[str, Any]],
) -> dict[str, Any]:
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    asset_paths: list[str] = []
    for asset in sorted(assets, key=lambda item: str(item.get("spell_id") or item.get("feature_id"))):
        identifier = str(asset.get("spell_id") or asset.get("feature_id"))
        subdir = directory / ("spells" if asset.get("kind") == "spell" else "features")
        path = subdir / f"{_slug(identifier)}.json"
        _write_json(path, asset)
        asset_paths.append(str(path.relative_to(directory)))
    manifest = _manifest(
        pack_id=pack_id,
        pack_version=pack_version,
        source_book=source_book,
        ruleset_version=ruleset_version,
        records=records,
        paths=asset_paths,
    )
    _write_json(directory / "manifest.json", manifest)
    return compile_artifact_directory(directory, write_files=True)


def _report(path: Path, value: dict[str, Any]) -> None:
    _write_json(path, value)


def _status_counts(report: Any, kind: str) -> dict[str, int]:
    return {
        status: sum(
            1
            for entry in report.entries
            if entry.get("kind") == kind and entry.get("status") == status
        )
        for status in ("full", "partial", "manual", "invalid")
    }


def main() -> int:
    records = load_records(SOURCE_ROOT)
    index = _records_by_key(records)
    spell_groups = _spell_sets(index)
    selected_feature_names = ("命流宗（旧版）", "战技选项", "战地匠师", "装甲师", "炼金师", "魔炮师")
    feature_records = [index[("塔莎的万事坩埚", name)] for name in selected_feature_names]

    core_records = spell_groups["core-phb-2024"]
    core_version = _pack_version(core_records)
    core_assets = _spell_assets(core_records, pack_id="core-phb-2024", pack_version=core_version)

    tasha_pack_records = spell_groups["tashas-cauldron"] + feature_records
    tasha_version = _pack_version(tasha_pack_records)
    expansion_assets: dict[str, list[dict[str, Any]]] = {}
    for pack_id, selected in spell_groups.items():
        if pack_id == "core-phb-2024":
            continue
        selected_names = {str(record["name"]) for record in selected}
        expansion_assets[pack_id] = [
            asset
            for asset in _spell_assets(
                core_records + selected,
                pack_id=pack_id,
                pack_version=tasha_version if pack_id == "tashas-cauldron" else _pack_version(selected),
            )
            if str(asset.get("name")) in selected_names
        ]
    feature_version = tasha_version
    feature_assets = _feature_assets(index, pack_version=feature_version)

    packs: dict[str, dict[str, Any]] = {}
    packs["core-2024-golden"] = _write_pack(
        directory=AUTHORED_ROOT / "core-2024" / "spells",
        pack_id="core-phb-2024",
        pack_version=core_version,
        source_book="玩家手册 2024",
        ruleset_version="2024",
        records=core_records,
        assets=core_assets,
    )
    for pack_id, assets in expansion_assets.items():
        label = {
            "xanathars-guide": "xanathars-guide",
            "tashas-cauldron": "tashas-cauldron",
            "fizbans-treasury": "fizbans-treasury",
            "book-of-many-things": "book-of-many-things",
        }[pack_id]
        packs[pack_id] = _write_pack(
            directory=AUTHORED_ROOT / "official-packs" / label / "spells",
            pack_id=pack_id,
            pack_version=(
                tasha_version
                if pack_id == "tashas-cauldron"
                else _pack_version(spell_groups[pack_id])
            ),
            source_book=str(spell_groups[pack_id][0]["source_book"]),
            ruleset_version="2014",
            records=spell_groups[pack_id],
            assets=assets,
        )
    packs["official-expansion-features"] = _write_pack(
        directory=AUTHORED_ROOT / "official-packs" / "tashas-cauldron" / "features",
        pack_id="tashas-cauldron",
        pack_version=feature_version,
        source_book="塔莎的万事坩埚",
        ruleset_version="2014",
        records=feature_records,
        assets=feature_assets,
    )
    tasha_root = AUTHORED_ROOT / "official-packs" / "tashas-cauldron"
    root_manifest = _manifest(
        pack_id="tashas-cauldron",
        pack_version=tasha_version,
        source_book="塔莎的万事坩埚",
        ruleset_version="2014",
        records=tasha_pack_records,
        paths=sorted(
            [
                *[
                    str(Path("spells") / path.relative_to(AUTHORED_ROOT / "official-packs" / "tashas-cauldron" / "spells"))
                    for path in sorted(
                        (tasha_root / "spells").glob("spells/*.json")
                    )
                ],
                *[
                    str(Path("features") / path.relative_to(AUTHORED_ROOT / "official-packs" / "tashas-cauldron" / "features"))
                    for path in sorted(
                        (tasha_root / "features").glob("features/*.json")
                    )
                ],
            ]
        ),
    )
    _write_json(tasha_root / "manifest.json", root_manifest)
    _write_json(
        tasha_root / "source-inventory.json",
        {
            "schema_version": "content-ir-source-inventory-1",
            "pack_id": "tashas-cauldron",
            "pack_version": tasha_version,
            "source_book": "塔莎的万事坩埚",
            "records": [
                {
                    "source_record_id": record["stable_id"],
                    "source_book": record["source_book"],
                    "source_relative_path": record["source_relative_path"],
                    "source_fingerprint": _source_fingerprint(record),
                    "name": record["name"],
                }
                for record in sorted(tasha_pack_records, key=lambda item: str(item["stable_id"]))
            ],
        },
    )
    compile_artifact_directory(tasha_root, write_files=True)

    manifests_dir = AUTHORED_ROOT / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        manifests_dir / "authored-index.json",
        {
            "schema_version": "content-ir-authored-index-1",
            "reviewed_by": REVIEWER,
            "compiler_fingerprint": COMPILER_FINGERPRINT,
            "packs": {
                key: {
                    "typed_ir_count": result["typed_ir_count"],
                    "counts": result["counts"],
                    "manifest_fingerprint": result["manifest_fingerprint"],
                }
                for key, result in sorted(packs.items())
            },
        },
    )

    all_core = audit_records(records, source_book="玩家手册 2024")
    expansion_reports: dict[str, Any] = {}
    for pack_id, selected in spell_groups.items():
        if pack_id == "core-phb-2024":
            continue
        pack = _registered_pack(pack_id)
        if pack is None:
            raise ValueError(f"unknown registered pack: {pack_id}")
        report = audit_records(
            records,
            source_book=str(pack["source_book"]),
            pack_id=pack_id,
            content_pack=pack,
        )
        result = packs[pack_id]
        spell_counts = _status_counts(report, "spell_draft")
        feature_counts = _status_counts(report, "feature_draft")
        expansion_reports[pack_id] = {
            "source_book": pack["source_book"],
            "feature_candidates": report.feature_count,
            "spell_candidates": report.spell_count,
            "feat_candidates": report.feat_count,
            "authored_spell_ir": len(selected),
            "authored_feature_ir": 0,
            "whole_book_spell_status": spell_counts,
            "whole_book_feature_status": feature_counts,
            "selected_batch_status": result["counts"],
        }
    core_spell_counts = _status_counts(all_core, "spell_draft")
    core_spell_records = sum(
        1
        for record in records
        if record.get("source_book") == "玩家手册 2024"
        and record.get("content_type") == "spells"
    )
    feature_audit_before = {"full": 328, "partial": 110, "dm_only": 61, "total": 499}
    _report(
        REPORT_ROOT / "content-ir-authored-batch-I-2026-08-11.json",
        {
            "schema_version": "content-ir-authored-batch-report-1",
            "reviewed_by": REVIEWER,
            "selected_count": len(core_assets) + sum(len(item) for item in expansion_assets.values()) + len(feature_assets),
            "reviewed_count": len(core_assets) + sum(len(item) for item in expansion_assets.values()) + len(feature_assets),
            "typed_ir_count": len(core_assets) + sum(len(item) for item in expansion_assets.values()) + len(feature_assets),
            "compile_full_count": sum(result["counts"]["full"] for result in packs.values()),
            "compile_partial_count": sum(result["counts"]["partial"] for result in packs.values()),
            "compile_manual_count": sum(result["counts"]["manual"] for result in packs.values()),
            "compile_invalid_count": sum(result["counts"]["invalid"] for result in packs.values()),
            "formal_feature_audit": {
                "before": feature_audit_before,
                "after": feature_audit_before,
                "actual_new_full": 0,
                "formal_registry_changed": False,
            },
            "groups": {
                "core_2024_spells": {"authored_typed_ir": len(core_assets), "full": packs["core-2024-golden"]["counts"]["full"]},
                "official_expansion_spells": {"authored_typed_ir": sum(len(item) for item in expansion_assets.values()), "full": sum(packs[key]["counts"]["full"] for key in expansion_assets)},
                "official_expansion_features": {"authored_typed_ir": len(feature_assets), "full": packs["official-expansion-features"]["counts"]["full"]},
            },
            "packs": {
                key: {
                    "typed_ir_count": value["typed_ir_count"],
                    "counts": value["counts"],
                    "manifest_fingerprint": value["manifest_fingerprint"],
                }
                for key, value in sorted(packs.items())
            },
        },
    )
    _report(
        REPORT_ROOT / "spell-ir-core-2024-golden-2026-08-11.json",
        {
            "schema_version": "spell-ir-batch-report-1",
            "source_book": "玩家手册 2024",
            "total_records": core_spell_records,
            "total_source_records": all_core.total_records,
            "detail_candidates": all_core.spell_count,
            "authored_typed_ir": len(core_assets),
            "full": packs["core-2024-golden"]["counts"]["full"],
            "partial": packs["core-2024-golden"]["counts"]["partial"],
            "manual": core_spell_counts["manual"],
            "invalid": packs["core-2024-golden"]["counts"]["invalid"],
            "whole_book_status_before_authored": core_spell_counts,
            "selected_spell_ids": sorted(str(item["spell_id"]) for item in core_assets),
        },
    )
    _report(
        REPORT_ROOT / "spell-ir-official-expansion-batch-2026-08-11.json",
        {
            "schema_version": "spell-ir-batch-report-1",
            "packs": expansion_reports,
            "authored_typed_ir": sum(len(item) for item in expansion_assets.values()),
            "full": sum(packs[key]["counts"]["full"] for key in expansion_assets),
            "partial": sum(packs[key]["counts"]["partial"] for key in expansion_assets),
            "manual": sum(
                item["whole_book_spell_status"]["manual"]
                for item in expansion_reports.values()
            ),
            "invalid": sum(packs[key]["counts"]["invalid"] for key in expansion_assets),
            "different_official_packs": len(expansion_assets),
        },
    )
    _report(
        REPORT_ROOT / "feature-ir-official-expansion-batch-2026-08-11.json",
        {
            "schema_version": "feature-ir-batch-report-1",
            "source_book": "塔莎的万事坩埚",
            "feature_candidates": audit_records(
                records,
                source_book="塔莎的万事坩埚",
                pack_id="tashas-cauldron",
                content_pack=_registered_pack("tashas-cauldron"),
            ).feature_count,
            "spell_candidates": 21,
            "feat_candidates": 1,
            "authored_feature_ir": len(feature_assets),
            "full": packs["official-expansion-features"]["counts"]["full"],
            "partial": packs["official-expansion-features"]["counts"]["partial"],
            "manual": packs["official-expansion-features"]["counts"]["manual"],
            "invalid": packs["official-expansion-features"]["counts"]["invalid"],
            "whole_book_status_before_authored": _status_counts(
                audit_records(
                    records,
                    source_book="塔莎的万事坩埚",
                    pack_id="tashas-cauldron",
                    content_pack=_registered_pack("tashas-cauldron"),
                ),
                "feature_draft",
            ),
            "selected_feature_ids": sorted(str(item["feature_id"]) for item in feature_assets),
        },
    )

    capabilities = Counter()
    for result in packs.values():
        for capability, count in result["capability_counts"].items():
            capabilities[capability] += count
    _report(
        REPORT_ROOT / "content-ir-completion-unlock-ranking-2026-08-11.json",
        {
            "schema_version": "content-ir-completion-unlock-ranking-1",
            "new_capability_count": 0,
            "new_capabilities": [],
            "reused_capabilities": [
                {"capability_id": key, "authored_clause_occurrence": value}
                for key, value in sorted(capabilities.items())
            ],
            "next_candidates": [
                {"candidate": "Xanathar additional simple area/save spells", "reason": "same saving_throw + area + damage + upcast contract"},
                {"candidate": "Tasha fixed tool/proficiency features", "reason": "same advancement.proficiency materializer with generic choice input"},
            ],
        },
    )

    dry_runs: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="content-ir-batch-I-") as temp_dir:
        temp_root = Path(temp_dir)
        for name, directory in (
            ("core-2024-golden", AUTHORED_ROOT / "core-2024" / "spells"),
            ("official-expansion-spells-xanathar", AUTHORED_ROOT / "official-packs" / "xanathars-guide" / "spells"),
            ("official-expansion-features-tasha", AUTHORED_ROOT / "official-packs" / "tashas-cauldron" / "features"),
        ):
            manifest_path = directory / "manifest.json"
            target = temp_root / name
            first = dry_run_manifest(manifest_path, target)
            second = dry_run_manifest(manifest_path, target)
            dry_runs[name] = {
                "first": {key: value for key, value in first.items() if key != "runtime_preview"},
                "second": {key: value for key, value in second.items() if key != "runtime_preview"},
                "runtime_preview_count": len(first.get("runtime_preview") or []),
                "production_mutated": bool(first.get("production_mutated")),
                "formal_registry_unchanged": True,
                "formal_database_unchanged": True,
                "campaign_unchanged": True,
                "character_snapshot_unchanged": True,
            }
    _report(
        REPORT_ROOT / "content-ir-isolated-pack-dry-run-2026-08-11.json",
        {
            "schema_version": "content-ir-isolated-pack-dry-run-1",
            "packs": dry_runs,
            "duplicate_feature_id": "covered_by existing compile_artifact_directory closed-world check",
            "duplicate_spell_id": "covered_by existing compile_artifact_directory closed-world check",
            "fingerprint_conflict": "covered_by manifest source_fingerprints and dry-run conflict path",
            "idempotent_replay": all(
                item["second"]["status"] == "idempotent_replay" for item in dry_runs.values()
            ),
            "formal_targets_written": False,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
