# ruff: noqa: N999
"""Plan feature migrations without promoting keyword matches to ``full``.

The class-feature audit intentionally reports overlapping source candidates.
This planner adds the missing execution-readiness layer: it groups non-full
rows by the first reusable contract that could consume them, records missing
fields and consumer state, and only marks a row ``batch_ready`` when its source
is available, its contract has a production consumer, and no manual boundary
was detected.  It does not mutate feature snapshots or audit statuses.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts/audit-class-feature-coverage.py"

# Ordered from the most specific event-driven contracts to broad structural
# labels.  The labels are planning buckets, not executor implementations.
TEMPLATE_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("zero_hp_intervention", "0 HP/死亡生命周期", ("zero_hp",)),
    ("attack_rider", "命中后骑手", ("hit_rider",)),
    ("roll_intervention", "掷骰干预", ("roll_intervention",)),
    ("pre_damage_intervention", "伤害前/防御干预", ("pre_damage_defense",)),
    ("aura_passive", "光环/范围被动", ("aura_range",)),
    ("summon_lifecycle", "召唤/伙伴", ("summon_companion",)),
    ("state_lifecycle", "状态生命周期", ("status_lifecycle",)),
    ("movement", "移动/位移", ("movement",)),
    ("damage_healing", "伤害/治疗", ("damage_healing",)),
    ("target_save_status", "目标/范围/豁免组合", ("target_range_save", "save_dc")),
    ("resource_lifecycle", "资源/恢复/频率", ("resource_recovery", "resource_binding")),
    ("action_trigger", "动作经济与触发条件", ("action_trigger", "action_economy")),
    ("spell_capability", "施法框架/法术修改", ("spellcasting", "spell_selection")),
    ("progression_grant", "成长授予/升级选择", ("advancement_choice",)),
    ("passive_modifier", "通用被动/数值修正", ()),
    ("manual_narrative", "DM/开放叙事", ("narrative_language",)),
)

PRODUCTION_CONSUMERS = {
    "zero_hp_intervention": "production_closed",
    "pre_damage_intervention": "production_closed",
    "aura_passive": "production_closed",
    "summon_lifecycle": "production_closed",
    "state_lifecycle": "production_closed",
    "movement": "production_closed",
    "damage_healing": "production_closed",
    "target_save_status": "production_closed",
    "resource_lifecycle": "production_closed",
    "action_trigger": "production_closed",
    "spell_capability": "production_partial",
    "progression_grant": "production_closed",
    "passive_modifier": "production_closed",
    "roll_intervention": "production_partial",
    "attack_rider": "production_partial",
    "manual_narrative": "manual_only",
}

# This inventory describes capabilities that already have a production event
# source and consumer.  It is intentionally planning metadata: a row does not
# become ``full`` merely because its capability exists.  The feature still
# needs a typed runtime contract and the audit remains authoritative.
CAPABILITY_SPECS: dict[str, dict[str, Any]] = {
    "zero_hp_intervention": {
        "trigger": "before_zero_hp_resolution",
        "producers": ["combat_damage_resolution"],
        "consumers": ["zero_hp_intervention_resolver"],
        "risk": "high",
        "needs": ["resource", "action_economy", "player_input", "targeting", "status"],
    },
    "attack_rider": {
        "trigger": "after_confirmed_attack_hit",
        "producers": ["combat_attack_resolution"],
        "consumers": ["attack_rider_resolver"],
        "risk": "high",
        "needs": ["resource", "player_input", "targeting", "status"],
    },
    "roll_intervention": {
        "trigger": "before_or_after_authoritative_d20_test",
        "producers": ["player_roll_resolution", "combat_attack_resolution"],
        "consumers": ["roll_intervention_resolver"],
        "risk": "medium",
        "needs": ["resource", "action_economy", "player_input", "targeting"],
    },
    "pre_damage_intervention": {
        "trigger": "before_damage_commit",
        "producers": ["combat_damage_resolution"],
        "consumers": ["pre_damage_intervention_resolver"],
        "risk": "high",
        "needs": ["resource", "action_economy", "player_input", "targeting"],
    },
    "aura_passive": {
        "trigger": "authoritative_context_resolution",
        "producers": ["combat_snapshot_compiler", "grid_visibility_resolver"],
        "consumers": ["ranged_passive_resolver"],
        "risk": "medium",
        "needs": ["targeting", "status"],
    },
    "summon_lifecycle": {
        "trigger": "feature_action_confirmation",
        "producers": ["combat_feature_action"],
        "consumers": ["summon_lifecycle_resolver"],
        "risk": "high",
        "needs": ["resource", "action_economy", "player_input", "targeting", "status"],
    },
    "state_lifecycle": {
        "trigger": "feature_action_or_combat_boundary",
        "producers": ["combat_feature_action", "combat_turn_boundary"],
        "consumers": ["feature_condition_lifecycle"],
        "risk": "medium",
        "needs": ["resource", "action_economy", "player_input", "status"],
    },
    "movement": {
        "trigger": "movement_or_feature_action",
        "producers": ["combat_movement", "combat_feature_action"],
        "consumers": ["authoritative_grid_movement"],
        "risk": "high",
        "needs": ["resource", "action_economy", "player_input", "targeting"],
    },
    "damage_healing": {
        "trigger": "damage_or_healing_resolution",
        "producers": ["combat_damage_resolution", "healing_resolution"],
        "consumers": ["typed_damage_healing_resolver"],
        "risk": "medium",
        "needs": ["resource", "player_input", "targeting"],
    },
    "target_save_status": {
        "trigger": "feature_action_confirmation",
        "producers": ["combat_feature_action"],
        "consumers": ["target_save_status_resolver"],
        "risk": "high",
        "needs": ["resource", "action_economy", "player_input", "targeting", "status"],
    },
    "resource_lifecycle": {
        "trigger": "advancement_rest_or_combat_boundary",
        "producers": ["advancement_service", "rest_service", "combat_boundary"],
        "consumers": ["character_resource_store"],
        "risk": "low",
        "needs": ["resource"],
    },
    "action_trigger": {
        "trigger": "typed_combat_event",
        "producers": ["combat_engine"],
        "consumers": ["feature_trigger_dispatch"],
        "risk": "medium",
        "needs": ["action_economy", "player_input", "targeting"],
    },
    "spell_capability": {
        "trigger": "advancement_or_spell_cast",
        "producers": ["advancement_service", "spell_economy"],
        "consumers": ["prepared_spell_and_cast_resolver"],
        "risk": "high",
        "needs": ["resource", "action_economy", "player_input", "targeting"],
    },
    "progression_grant": {
        "trigger": "advancement_confirmation",
        "producers": ["advancement_choice_requirements"],
        "consumers": ["advancement_service"],
        "risk": "low",
        "needs": ["player_input"],
    },
    "passive_modifier": {
        "trigger": "snapshot_or_context_resolution",
        "producers": ["feature_runtime_compiler"],
        "consumers": ["typed_modifier_resolvers"],
        "risk": "medium",
        "needs": [],
    },
    "manual_narrative": {
        "trigger": "dm_adjudication",
        "producers": [],
        "consumers": [],
        "risk": "manual",
        "needs": ["dm_input"],
    },
}

CANONICAL_GAP_CATEGORIES = frozenset(
    {
        "missing_runtime_contract",
        "producer_missing",
        "consumer_missing",
        "consumer_partial",
        "resource_missing",
        "action_economy_missing",
        "authoritative_targeting_missing",
        "ui_input_missing",
        "prerequisite_feature_missing",
        "source_missing",
        "manual_boundary",
        "needs_contract_review",
    }
)

FIELD_REQUIREMENTS = {
    "zero_hp_intervention": ("trigger", "eligibility", "save/result", "reset"),
    "attack_rider": (
        "after_hit trigger",
        "target/qualification",
        "resource/frequency",
        "effect",
    ),
    "roll_intervention": ("trigger", "operation", "input", "resource consumption"),
    "pre_damage_intervention": (
        "before_damage trigger",
        "damage eligibility",
        "transformation",
        "resource",
    ),
    "aura_passive": ("source/target relation", "range", "stacking", "effect"),
    "summon_lifecycle": ("template", "quantity", "control", "duration"),
    "state_lifecycle": ("condition", "duration/end", "immunity or removal"),
    "movement": ("destination/distance", "path rule", "action/resource"),
    "damage_healing": ("dice/expression", "type/effect", "target", "lifecycle"),
    "target_save_status": (
        "target/range",
        "save ability/DC",
        "success/failure",
        "effect",
    ),
    "resource_lifecycle": ("resource key", "cost", "recovery", "fail-closed"),
    "action_trigger": ("event", "action economy", "qualification", "effect"),
    "spell_capability": ("spell identity/list", "slot/choice", "consumer", "effect"),
    "progression_grant": ("choice schema", "validation", "grant consumer"),
    "passive_modifier": ("stat", "operation", "qualification", "consumer"),
    "manual_narrative": ("DM adjudication",),
}

MANUAL_MARKERS = (
    "需要 DM",
    "需由 DM",
    "由 DM",
    "需要选择",
    "任选",
    "自选",
    "具体法术",
    "具体形态",
    "具体选项",
    "开放叙事",
)


def _audit_module() -> Any:
    spec = importlib.util.spec_from_file_location("class_feature_audit", AUDIT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load class feature audit")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _template(row: dict[str, Any]) -> tuple[str, str]:
    name = "".join(str(row.get("feature_name") or "").split())
    if "传奇恩惠" in name or "史诗恩惠" in name:
        # Repeated source prose can contain markers from the selected feat's
        # description.  The class-table row itself is still an advancement
        # asset grant and must not drift into summon/damage buckets.
        return "progression_grant", "成长授予/升级选择"
    if "战斗风格" in name:
        return "progression_grant", "成长授予/升级选择"
    blocks = set(row.get("detected_blocks") or ())
    for key, label, required_blocks in TEMPLATE_RULES:
        if required_blocks and any(block in blocks for block in required_blocks):
            return key, label
    return "passive_modifier", "通用被动/数值修正"


def _missing_fields(row: dict[str, Any], template: str) -> list[str]:
    description = str(row.get("source_description") or "")
    missing = list(FIELD_REQUIREMENTS.get(template, ()))
    if row.get("source_parse") not in {"description_located", "description_reused"}:
        missing.insert(0, "source description")
    if template != "manual_narrative" and not description.strip():
        missing.insert(0, "source description")
    return list(dict.fromkeys(missing))


def _feature_id(row: dict[str, Any]) -> str:
    identity = "|".join(
        str(row.get(key) or "")
        for key in ("scope", "class_name", "subclass_name", "level", "feature_name")
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"class-feature:{digest}"


def _specialized_cluster(row: dict[str, Any], template: str) -> str:
    name = "".join(str(row.get("feature_name") or "").split())
    if "传奇恩惠" in name or "史诗恩惠" in name:
        return "advancement_asset_grant:epic_boon"
    if "战斗风格" in name:
        return "advancement_asset_grant:fighting_style"
    if "武器精通" in name:
        return "advancement_asset_grant:weapon_mastery_loadout"
    if "超魔法" in name:
        return "advancement_asset_grant:metamagic_options"
    if any(value in name for value in ("熟练探险家", "原初职能", "圣职")):
        return "advancement_asset_grant:growth_option_bundle"
    if any(value in name for value in ("魔法奥秘", "仪式学家", "战争训练")):
        return "advancement_asset_grant:spell_capability"
    return template


def _growth_asset_metadata(row: dict[str, Any]) -> dict[str, Any]:
    """Expose schema-v2 grant/effect boundaries for the growth-asset batch."""

    name = "".join(str(row.get("feature_name") or "").split())
    status = str(row.get("runtime_status") or "dm_only")
    metadata: dict[str, Any] = {
        "authoritative_catalog": None,
        "selected_asset_kind": None,
        "grant_consumer": None,
        "grant_status": None,
        "selected_asset_consumer": None,
        "selected_asset_status": None,
        "effect_status": status,
        "required_input": None,
        "duplicate_policy": None,
        "replacement_policy": None,
        "prerequisite_validation": None,
        "persisted_state": None,
    }
    if "武器精通" in name:
        metadata.update(
            authoritative_catalog="2024 weapon catalog+mastery property catalog",
            selected_asset_kind="weapon_mastery_loadout",
            grant_consumer="advancement_service",
            grant_status="full",
            selected_asset_consumer="rest_service",
            selected_asset_status="full",
            effect_status="separate_asset_contract",
            required_input="feature_choices_by_key|long_rest.weapon_ids",
            duplicate_policy="forbid",
            replacement_policy="class_policy_on_long_rest",
            prerequisite_validation="weapon_category_or_character_proficiency",
            persisted_state="character.proficiencies",
        )
    elif "超魔法" in name:
        metadata.update(
            authoritative_catalog="2024 metamagic option catalog",
            selected_asset_kind="metamagic_option",
            grant_consumer="advancement_service",
            grant_status="full",
            selected_asset_consumer="character.features",
            selected_asset_status="full",
            effect_status="separate_asset_contract",
            required_input="feature_choices_by_key",
            duplicate_policy="forbid",
            replacement_policy="replace_one_on_each_sorcerer_level",
            prerequisite_validation="catalog_identity+cumulative_target_total",
            persisted_state="character.features",
        )
    elif "战斗风格" in name:
        metadata.update(
            authoritative_catalog="2024 feat catalog:战斗风格",
            selected_asset_kind="feat_or_typed_spell_bundle",
            grant_consumer="advancement_service",
            grant_status="full" if status == "full" else "partial",
            selected_asset_consumer="feat_runtime_contract|spell_economy",
            selected_asset_status="separate_contract",
            required_input="feature_choices_by_key|subclass_feature_choices",
            duplicate_policy="forbid",
            replacement_policy=(
                "replace_on_fighter_level"
                if str(row.get("class_name") or "") == "战士"
                and str(row.get("scope") or "") == "core"
                else (
                    "replace_source_bound_cantrip_on_owner_class_level"
                    if str(row.get("class_name") or "") in {"圣武士", "游侠"}
                    else "source_specific"
                )
            ),
            prerequisite_validation="authoritative_feat_prerequisite_validator",
            persisted_state="character.features|character.spells",
        )
    elif "熟练探险家" in name:
        metadata.update(
            authoritative_catalog="character.proficient_skills|2024 core languages",
            selected_asset_kind="expertise+language",
            grant_consumer="advancement_service",
            grant_status="full",
            selected_asset_consumer="skill_modifier|character_language_assets",
            selected_asset_status="full",
            required_input="feature_choices_by_key",
            duplicate_policy="forbid",
            replacement_policy="none",
            prerequisite_validation="already_proficient+language_catalog",
            persisted_state="character.skills|character.proficiencies",
        )
    elif "原初职能" in name or name == "圣职":
        metadata.update(
            authoritative_catalog="closed_option_bundle|2024 spell catalog",
            selected_asset_kind="proficiency+cantrip+skill_modifier",
            grant_consumer="advancement_service",
            grant_status="full",
            selected_asset_consumer="equipment/attack|spell_economy|skill_modifier",
            selected_asset_status="full",
            required_input="feature_choices_by_key",
            duplicate_policy="forbid",
            replacement_policy="none",
            prerequisite_validation="closed_branch+spell_class_and_level",
            persisted_state="character.proficiencies|skills|spells",
        )
    elif "魔法奥秘" in name:
        metadata.update(
            authoritative_catalog="2024 bard/cleric/druid/wizard spell catalog",
            selected_asset_kind="spell_list_expansion",
            grant_consumer="advancement_service",
            grant_status="full",
            selected_asset_consumer="ordinary_bard_spell_learning_and_replacement",
            selected_asset_status="full",
            required_input="spell_additions|spell_removals",
            duplicate_policy="spell_identity",
            replacement_policy="bard_level_replacement",
            prerequisite_validation="bard_level_and_max_spell_level",
            persisted_state="character.spells",
        )
    elif "仪式学家" in name:
        metadata.update(
            authoritative_catalog="known wizard spellbook+ritual tag",
            selected_asset_kind="spellcasting_capability",
            grant_consumer="advancement_service",
            grant_status="full",
            selected_asset_consumer="spell_economy_service",
            selected_asset_status="full",
            required_input="ritual spell cast request",
            duplicate_policy="not_applicable",
            replacement_policy="not_applicable",
            prerequisite_validation="known+wizard+ritual+spellbook",
            persisted_state="character.features|known_spells",
        )
    elif "战争训练" in name:
        metadata.update(
            authoritative_catalog="fixed subclass proficiencies+equipped weapon",
            selected_asset_kind="proficiency+spellcasting_focus_permission",
            grant_consumer="advancement_service",
            grant_status="full",
            selected_asset_consumer="equipment_rules|spell_economy_service",
            selected_asset_status="full",
            required_input="focus_equipment_id",
            duplicate_policy="deduplicate",
            replacement_policy="not_applicable",
            prerequisite_validation="equipped_weapon+weapon_proficiency+spell_class",
            persisted_state="character.proficiencies|features",
        )
    return metadata


def _gap_category(readiness: str, blockers: list[str]) -> str | None:
    if readiness == "already_full":
        return None
    if readiness in CANONICAL_GAP_CATEGORIES:
        return readiness
    if any("consumer" in item for item in blockers):
        return "consumer_missing"
    return "missing_runtime_contract"


def _row_needs(row: dict[str, Any], template: str) -> set[str]:
    needs = set(CAPABILITY_SPECS[template]["needs"])
    blocks = set(row.get("detected_blocks") or ())
    description = str(row.get("source_description") or "")
    if blocks & {"resource_binding", "resource_recovery"}:
        needs.add("resource")
    if "action_economy" in blocks:
        needs.add("action_economy")
    if blocks & {"target_range_save", "aura_range"}:
        needs.add("targeting")
    if blocks & {"status_lifecycle", "zero_hp"}:
        needs.add("status")
    if any(marker in description for marker in ("选择", "由你决定", "掷", "投掷")):
        needs.add("player_input")
    return needs


def plan() -> dict[str, Any]:
    report = _audit_module().audit()
    rows: list[dict[str, Any]] = []
    for row in report["rows"]:
        if row["runtime_status"] == "full":
            readiness = "already_full"
            template, label = _template(row)
            blocker: list[str] = []
        else:
            template, label = _template(row)
            description = str(row.get("source_description") or "")
            has_manual_marker = any(marker in description for marker in MANUAL_MARKERS)
            source_available = row.get("source_parse") in {
                "description_located",
                "description_reused",
            }
            consumer = PRODUCTION_CONSUMERS[template]
            blocker = _missing_fields(row, template)
            if has_manual_marker or template == "manual_narrative":
                readiness = "manual_boundary"
                blocker.append("manual choice/adjudication boundary")
            elif not source_available:
                readiness = "missing_source"
            elif consumer == "manual_only":
                readiness = "manual_boundary"
            elif consumer == "production_partial":
                readiness = "consumer_partial"
                blocker.append("consumer integration or security closure")
            elif not row.get("runtime_sections"):
                readiness = "missing_runtime_contract"
                blocker.append("no runtime section/production configuration")
            else:
                readiness = "needs_contract_review"
                blocker.append("field-by-field contract review")
        needs = _row_needs(row, template)
        capability = CAPABILITY_SPECS[template]
        cluster = _specialized_cluster(row, template)
        gap_category = _gap_category(readiness, blocker)
        rows.append(
            {
                "feature_id": _feature_id(row),
                "scope": row["scope"],
                "class_name": row["class_name"],
                "subclass_name": row.get("subclass_name"),
                "level": row["level"],
                "feature_name": row["feature_name"],
                "runtime_status": row["runtime_status"],
                "runtime_reason": list(row.get("runtime_reasons") or ()),
                "runtime_sections": list(row.get("runtime_sections") or ()),
                "source_parse": row["source_parse"],
                "template": template,
                "template_label": label,
                "reusable_cluster": cluster,
                "trigger_time": capability["trigger"],
                "required_producers": list(capability["producers"]),
                "required_consumers": list(capability["consumers"]),
                "producer_available": bool(capability["producers"]),
                "consumer_available": PRODUCTION_CONSUMERS[template] != "manual_only",
                "consumer_status": PRODUCTION_CONSUMERS[template],
                "readiness": readiness,
                "gap_category": gap_category,
                "missing_fields": list(dict.fromkeys(blocker)),
                "requires_resource": "resource" in needs,
                "requires_action_economy": "action_economy" in needs,
                "requires_player_input": "player_input" in needs,
                "requires_dm_input": "dm_input" in needs,
                "requires_authoritative_targeting": "targeting" in needs,
                "requires_status_context": "status" in needs,
                "prerequisite_feature_missing": False,
                "estimated_risk": capability["risk"],
                "eligible_this_run": (
                    cluster == "advancement_asset_grant:epic_boon"
                    and row["runtime_status"] != "full"
                ),
                "contract_evidence": list(row.get("runtime_sections") or ()),
                "parameterized_contract_test": (
                    "backend/tests/test_progression_automation.py::"
                    "test_epic_boon_class_rows_share_one_authoritative_asset_grant_contract"
                    if cluster == "advancement_asset_grant:epic_boon"
                    and row["runtime_status"] == "full"
                    else None
                ),
                "representative_e2e_test": (
                    "backend/tests/test_advancement_matrix_api.py::"
                    "test_epic_boon_grant_is_authoritative_and_selected_feat_stays_separate"
                    if cluster == "advancement_asset_grant:epic_boon"
                    and row["runtime_status"] == "full"
                    else None
                ),
                "blocking_reason": list(dict.fromkeys(blocker)),
                **_growth_asset_metadata(row),
            }
        )

    rows.sort(
        key=lambda item: (
            str(item["reusable_cluster"]),
            str(item["readiness"]),
            str(item["class_name"]),
            str(item.get("subclass_name") or ""),
            int(item["level"]),
            str(item["feature_name"]),
        )
    )

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        group = grouped.setdefault(
            row["template"],
            {
                "label": row["template_label"],
                "consumer_status": row["consumer_status"],
                "total": 0,
                "already_full": 0,
                "missing_runtime_contract": 0,
                "needs_contract_review": 0,
                "consumer_partial": 0,
                "manual_boundary": 0,
                "missing_source": 0,
            },
        )
        group["total"] += 1
        group[row["readiness"]] = group.get(row["readiness"], 0) + 1

    readiness_counts = Counter(row["readiness"] for row in rows)
    clusters: dict[str, dict[str, Any]] = {}
    for row in rows:
        cluster = clusters.setdefault(
            row["reusable_cluster"],
            {
                "total_count": 0,
                "full_count": 0,
                "candidate_count": 0,
                "eligible_this_run": 0,
                "producer_available": True,
                "consumer_available": True,
                "requires_new_ui": False,
                "requires_new_persistence": False,
                "risk_counts": {},
                "readiness_counts": {},
            },
        )
        cluster["total_count"] += 1
        cluster["full_count"] += int(row["runtime_status"] == "full")
        cluster["candidate_count"] += int(row["runtime_status"] != "full")
        cluster["eligible_this_run"] += int(bool(row["eligible_this_run"]))
        cluster["producer_available"] = bool(
            cluster["producer_available"] and row["producer_available"]
        )
        cluster["consumer_available"] = bool(
            cluster["consumer_available"] and row["consumer_available"]
        )
        cluster["requires_new_ui"] = bool(
            cluster["requires_new_ui"]
            or (
                row["requires_player_input"]
                and not row["runtime_sections"]
                and row["reusable_cluster"] != "advancement_asset_grant:epic_boon"
            )
        )
        cluster["requires_new_persistence"] = bool(
            cluster["requires_new_persistence"]
            or row["requires_status_context"]
            or row["requires_resource"]
        )
        risk = str(row["estimated_risk"])
        cluster["risk_counts"][risk] = cluster["risk_counts"].get(risk, 0) + 1
        readiness = str(row["readiness"])
        cluster["readiness_counts"][readiness] = (
            cluster["readiness_counts"].get(readiness, 0) + 1
        )
    ordered_clusters = dict(
        sorted(
            clusters.items(),
            key=lambda item: (
                -int(item[1]["eligible_this_run"]),
                -int(item[1]["candidate_count"]),
                item[0],
            ),
        )
    )
    return {
        "schema_version": "feature-automation-migration-plan-2",
        "audit_scope": report["scope"],
        "audit_status_counts": report["status_counts"],
        "readiness_counts": dict(readiness_counts),
        "templates": grouped,
        "clusters": ordered_clusters,
        "rows": rows,
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    lines = [
        "# 特性自动化迁移预审报告",
        "",
        "这份报告只规划迁移，不修改运行时状态，也不把候选行直接升级为 `full`。",
        "",
        f"- 矩阵 schema：`{report['schema_version']}`",
        f"- 总条目：{report['audit_scope']['total_features']}",
        f"- 当前状态：`{report['audit_status_counts']}`",
        f"- 预审状态：`{report['readiness_counts']}`",
        "",
        "## 模板分组",
        "",
        "| 模板 | 条目 | 已 full | 缺运行时合同 | 待合同复核 | 消费者不完整 | 人工边界 | 缺源码 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, group in report["templates"].items():
        lines.append(
            "| {label} (`{key}`) | {total} | {already_full} | {missing_runtime_contract} | "
            "{needs_contract_review} | {consumer_partial} | {manual_boundary} | {missing_source} |".format(
                key=key, **group
            )
        )
    lines.extend(
        [
            "",
            "## 能力簇",
            "",
            "| 能力簇 | 总数 | full | 非 full | 本轮可直接迁移 | producer | consumer | 新 UI | 新持久化 |",
            "|---|---:|---:|---:|---:|:---:|:---:|:---:|:---:|",
            *[
                "| {key} | {total_count} | {full_count} | {candidate_count} | "
                "{eligible_this_run} | {producer} | {consumer} | {ui} | {persistence} |".format(
                    key=key,
                    producer="是" if cluster["producer_available"] else "否",
                    consumer="是" if cluster["consumer_available"] else "否",
                    ui="是" if cluster["requires_new_ui"] else "否",
                    persistence="是" if cluster["requires_new_persistence"] else "否",
                    **cluster,
                )
                for key, cluster in report["clusters"].items()
            ],
            "",
            "## 预审结论",
            "",
            "- `missing_runtime_contract`：源码命中积木，但还没有真实运行时合同；不能仅靠字段改成 `full`。",
            "- `needs_contract_review`：已有部分运行时结构，但仍需逐字段核对消费者、输入、资源和幂等。",
            "- `consumer_partial`：执行器存在，但生产接线或安全闭环未完成。",
            "- `manual_boundary`：包含选择、DM裁定或开放叙事，不能强行无人值守。",
            "- 只有完成真实配置、消费者、状态写入、输入链和测试后，才允许从本报告中产生 `full` 增量。",
            "",
            "## 下一批执行门槛",
            "",
            "下一批必须从一个模板中选择一组条目，先生成配置和定向测试，再跑499条审计。预审数字是候选分组，不是承诺的新增 `full` 数量。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        type=Path,
        default=ROOT / "reports/feature-automation-migration-plan-2026-08-07.json",
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=ROOT / "docs/feature-automation-migration-matrix-2026-08-09.md",
    )
    args = parser.parse_args()
    report = plan()
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(report, args.markdown)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "audit_scope",
                    "audit_status_counts",
                    "readiness_counts",
                    "templates",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
