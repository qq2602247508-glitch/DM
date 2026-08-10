#!/usr/bin/env python3
# ruff: noqa: N999
"""Real-corpus exact semantic cluster census for Feature IR migration.

This script is intentionally not an executor and never mutates audit status.
It computes a stable, deterministic semantic signature for every audited row
and groups rows only when their typed rule fields are identical or proven
equivalent.  Coarse audit labels (movement, resource_lifecycle, aura_passive,
...) are never sufficient to merge rows.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDIT_SCRIPT = ROOT / "scripts" / "audit-class-feature-coverage.py"


def _load_audit() -> dict[str, Any]:
    spec = importlib.util.spec_from_file_location("feature_audit_census", AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit()


def _has(text: str, *markers: str) -> bool:
    return any(marker in text for marker in markers)


def _re(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text))


def semantic_signature(row: dict[str, Any]) -> dict[str, Any]:
    """Compute the exact typed rule signature of one audited row."""

    description = str(row.get("source_description") or "")
    name = str(row.get("feature_name") or "")
    text = f"{name}\n{description}"

    # Activation / action economy markers.
    action_economy: list[str] = []
    if _has(text, "附赠动作"):
        action_economy.append("bonus_action")
    if _has(text, "以一个动作", "作为一个动作", "魔法动作"):
        action_economy.append("action")
    if _has(text, "以反应", "作为反应", "能够以反应", "可以用反应"):
        action_economy.append("reaction")
    if _has(text, "无需动作"):
        action_economy.append("no_action")
    if not action_economy and _re(text, r"当你|每当|回合开始|回合结束|受到|命中"):
        action_economy.append("triggered")

    # Resource semantics.
    resource: list[str] = []
    for marker, key in (
        ("诗人激励", "bardic_inspiration"),
        ("引导神力", "channel_divinity"),
        ("荒野变形", "wild_shape"),
        ("狂暴", "rage"),
        ("术法点", "sorcery_points"),
        ("灵能骰", "psionic_dice"),
        ("卓越骰", "superiority_dice"),
        ("法术位", "spell_slot"),
        ("熟练加值", "proficiency_bonus"),
    ):
        if marker in text:
            resource.append(key)
    if _has(text, "长休"):
        resource.append("long_rest_recovery")
    if _has(text, "短休"):
        resource.append("short_rest_recovery")
    if _has(text, "次数等于"):
        resource.append("uses_ability_modifier")

    # Trigger vocabulary.
    trigger: list[str] = []
    for marker, key in (
        ("激活狂暴", "on_rage_activation"),
        ("狂暴激活期间", "while_raging"),
        ("荒野变形", "wild_shape_related"),
        ("被击中", "on_hit"),
        ("受到伤害", "on_damage_taken"),
        ("豁免失败", "on_save_failure"),
        ("检定失败", "on_check_failure"),
        ("施展", "on_spell_cast"),
        ("回合开始", "on_turn_start"),
        ("回合结束时", "on_turn_end"),
        ("命中", "on_attack_hit"),
        ("死亡豁免", "on_death_save"),
        ("投掷先攻", "on_initiative_roll"),
        ("长休", "on_long_rest"),
    ):
        if marker in text:
            trigger.append(key)

    # Target shape.
    target: list[str] = ["self"]
    if _re(text, r"[0-9]+尺内.{0,24}(?:盟友|友方|生物)|选择.{0,8}(?:盟友|生物)"):
        target.append("allies_or_creatures")
    if _re(text, r"敌人|目标生物|一名生物"):
        target.append("enemy")
    if _has(text, "幻象", "召唤", "精魂", "行侣", "伙伴"):
        target.append("summon")
    if _re(text, r"[0-9]+尺(?:半径|光环|区域|范围|立方)"):
        target.append("area")

    # Effect families.
    effects: list[str] = []
    if _has(text, "临时生命"):
        effects.append("temporary_hp")
    if _has(text, "恢复生命", "恢复生命值", "治疗"):
        effects.append("healing")
    if _has(text, "抗性"):
        effects.append("damage_resistance")
    if _has(text, "免疫"):
        effects.append("damage_immunity")
    if _has(text, "优势"):
        effects.append("advantage")
    if _has(text, "劣势"):
        effects.append("disadvantage")
    if _has(text, "飞行", "飞行速度"):
        effects.append("flight")
    if _has(text, "攀爬"):
        effects.append("climb")
    if _has(text, "游泳"):
        effects.append("swim")
    if _has(text, "传送"):
        effects.append("teleport")
    if _has(text, "隐形"):
        effects.append("invisible")
    if _has(text, "魅惑", "恐慌", "震慑", "束缚", "目盲", "倒地"):
        effects.append("condition")
    if _has(text, "豁免"):
        effects.append("saving_throw")
    if _has(text, "检定"):
        effects.append("ability_check")
    if _has(text, "速度"):
        effects.append("speed")
    if _has(text, "伤害"):
        effects.append("damage")
    if _has(text, "光照"):
        effects.append("light")
    if _has(text, "重掷", "重骰"):
        effects.append("reroll")
    if _has(text, "额外攻击", "进行攻击", "徒手打击", "武器攻击"):
        effects.append("attack")
    if _has(text, "生命值降至0", "生命值将要降至0"):
        effects.append("zero_hp")
    if _has(text, "豁免检定具有优势", "豁免检定具有劣势"):
        effects.append("save_advantage_modifier")

    duration: list[str] = []
    if _has(text, "1小时"):
        duration.append("one_hour")
    elif _re(text, r"([0-9]+|十)分钟"):
        duration.append("minutes")
    if _has(text, "持续至你完成一次长休", "直至完成长休"):
        duration.append("until_long_rest")
    if _has(text, "本回合结束", "你的下个回合开始", "当前回合结束"):
        duration.append("turn_scoped")
    if _has(text, "陷入失能"):
        duration.append("until_incapacitated")

    feature_id = row.get("feature_id") or row.get("stable_id")
    if not isinstance(feature_id, str) or not feature_id.strip():
        feature_id = (
            f"class-feature:{row.get('scope')}:{row.get('class_name')}:"
            f"{row.get('subclass_name') or ''}:{row.get('level')}:{row.get('feature_name')}"
        )
    contract = {
        "trigger": sorted(set(trigger)),
        "conditions": list(row.get("conditions") or ()),
        "activation": row.get("activation") or "unknown",
        "action_economy": sorted(set(action_economy)),
        "target_policy": sorted(set(target)),
        "input_requirements": list(row.get("input_requirements") or ()),
        "resource": sorted(set(resource)),
        "frequency": row.get("frequency") or [],
        "duration": sorted(set(duration)),
        "expiry": row.get("expiry") or [],
        "effect_operator": row.get("effect_operator") or sorted(set(effects)),
        "effect_parameters": row.get("effect_parameters") or {},
        "producer": row.get("producer"),
        "consumer": row.get("consumer") or sorted(set(row.get("capability_ids") or ())),
        "persisted_state": row.get("persisted_state") or sorted(
            set(row.get("runtime_sections") or ())
        ),
        "cas_support": row.get("cas_support"),
        "idempotency_support": row.get("idempotency_support"),
        "materializer": row.get("materializer"),
        "validator": row.get("validator"),
        "production_evidence": row.get("production_evidence")
        or sorted(set(row.get("compiler_blockers") or ())),
        "remaining_blocker": row.get("remaining_blocker")
        or row.get("blocker")
        or sorted(set(row.get("compiler_blockers") or ())),
    }
    missing_contract_fields = [
        key
        for key in (
            "producer",
            "consumer",
            "persisted_state",
            "cas_support",
            "idempotency_support",
            "materializer",
            "validator",
            "production_evidence",
        )
        if contract[key] in (None, [], "")
    ]
    classification = "exact_same_contract"
    if row.get("source_parse") == "structural_placeholder":
        classification = "source_incomplete"
    elif missing_contract_fields:
        classification = "missing_authority"
    elif contract["producer"] is None:
        classification = "missing_producer"
    elif contract["consumer"] is None:
        classification = "consumer_partial"
    signature: dict[str, Any] = {
        "feature_id": feature_id,
        "scope": row.get("scope"),
        "class_name": row.get("class_name"),
        "subclass_name": row.get("subclass_name"),
        "level": row.get("level"),
        "feature_name": row.get("feature_name"),
        "source_record_id": row.get("source_record_id"),
        "source_parse": row.get("source_parse"),
        "runtime_status": row.get("runtime_status"),
        "action_economy": sorted(set(action_economy)),
        "resource": sorted(set(resource)),
        "trigger": sorted(set(trigger)),
        "target": sorted(set(target)),
        "effects": sorted(set(effects)),
        "duration": sorted(set(duration)),
        "detected_blocks": sorted(set(row.get("detected_blocks") or ())),
        "source_trust": row.get("source_trust"),
        "semantic_contract": contract,
        "contract_missing_fields": missing_contract_fields,
        "classification": classification,
    }
    signature["signature_fingerprint"] = hashlib.sha256(
        json.dumps(
            contract,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    return signature


def census() -> dict[str, Any]:
    report = _load_audit()
    rows = list(report["rows"])
    signed = [semantic_signature(row) for row in rows]

    clusters: dict[str, list[dict[str, Any]]] = {}
    for signature in signed:
        clusters.setdefault(signature["signature_fingerprint"], []).append(signature)

    partial = [signature for signature in signed if signature["runtime_status"] == "partial"]
    partial_clusters: dict[str, list[dict[str, Any]]] = {}
    for signature in partial:
        partial_clusters.setdefault(signature["signature_fingerprint"], []).append(signature)

    superficial_groups: dict[str, list[dict[str, Any]]] = {}
    for signature in partial:
        coarse_key = json.dumps(
            {
                "effects": signature["effects"],
                "detected_blocks": signature["detected_blocks"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        superficial_groups.setdefault(coarse_key, []).append(signature)

    cluster_rows: list[dict[str, Any]] = []
    for fingerprint, members in sorted(
        partial_clusters.items(), key=lambda item: (-len(item[1]), item[0])
    ):
        first = members[0]
        cluster_rows.append(
            {
                "cluster_id": f"semantic:{fingerprint}",
                "member_count": len(members),
                "member_feature_ids": [member["feature_id"] for member in members],
                "action_economy": first["action_economy"],
                "resource": first["resource"],
                "trigger": first["trigger"],
                "target": first["target"],
                "effects": first["effects"],
                "duration": first["duration"],
                "detected_blocks": first["detected_blocks"],
                "classification": first["classification"],
                "contract_relation": "exact_same_contract",
                "contract_missing_fields": first["contract_missing_fields"],
                "production_closed": not first["contract_missing_fields"]
                and first["classification"] == "exact_same_contract",
                "needs_new_producer": "producer" in first["contract_missing_fields"],
                "needs_new_consumer": "consumer" in first["contract_missing_fields"],
                "needs_new_persistence": "persisted_state" in first["contract_missing_fields"],
                "needs_new_ui": "input_requirements" in first["contract_missing_fields"],
                "estimated_full_count": len(members)
                if not first["contract_missing_fields"]
                else 0,
                "blockers": first["semantic_contract"]["remaining_blocker"],
            }
        )

    effect_counts = Counter(effect for signature in partial for effect in signature["effects"])
    trigger_counts = Counter(trigger for signature in partial for trigger in signature["trigger"])
    resource_counts = Counter(resource for signature in partial for resource in signature["resource"])
    target_counts = Counter(target for signature in partial for target in signature["target"])

    return {
        "schema_version": "feature-ir-semantic-cluster-census-1",
        "audit_total": len(rows),
        "status_counts": dict(Counter(signature["runtime_status"] for signature in signed)),
        "partial_total": len(partial),
        "partial_exact_cluster_count": len(partial_clusters),
        "partial_signatures": partial,
        "largest_partial_clusters": cluster_rows[:40],
        "equivalent_contract_candidates": [],
        "superficially_similar_clusters": [
            {
                "similarity_key": (
                    "similarity:"
                    + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
                ),
                "member_count": len(members),
                "member_feature_ids": [item["feature_id"] for item in members],
                "reason": (
                    "coarse effects/blocks match but typed producer/consumer "
                    "contract differs"
                ),
                "merge_allowed": False,
            }
            for key, members in sorted(
                superficial_groups.items(),
                key=lambda item: (-len(item[1]), item[0]),
            )
            if len(members) > 1
            and len({item["signature_fingerprint"] for item in members}) > 1
        ][:40],
        "contract_relation_counts": {
            "exact_same_contract": len(partial_clusters),
            "equivalent_contract": 0,
            "superficially_similar": sum(
                1
                for members in superficial_groups.values()
                if len(members) > 1
                and len({item["signature_fingerprint"] for item in members}) > 1
            ),
        },
        "classification_counts": dict(
            sorted(Counter(item["classification"] for item in partial).items())
        ),
        "effect_counts": dict(sorted(effect_counts.items(), key=lambda item: -item[1])),
        "trigger_counts": dict(sorted(trigger_counts.items(), key=lambda item: -item[1])),
        "resource_counts": dict(sorted(resource_counts.items(), key=lambda item: -item[1])),
        "target_counts": dict(sorted(target_counts.items(), key=lambda item: -item[1])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        type=Path,
        default=ROOT / "reports/feature-ir-semantic-cluster-census-2026-08-10.json",
    )
    args = parser.parse_args()
    result = census()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "audit_total",
                    "status_counts",
                    "partial_total",
                    "partial_exact_cluster_count",
                    "largest_partial_clusters",
                    "effect_counts",
                    "trigger_counts",
                    "resource_counts",
                    "target_counts",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
