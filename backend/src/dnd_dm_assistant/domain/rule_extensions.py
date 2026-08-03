from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dnd_dm_assistant.domain.rule_blocks import NarrativeBlock, RulePlan


@dataclass(frozen=True)
class RuleExtension:
    """One explicitly opt-in D&D rules module.

    The local corpus contains core rules, legacy variants and third-party text in
    the same index.  This registry is the safety boundary: only named modules can
    be enabled, and every module carries its source and automation status into the
    campaign-scoped atomic library.
    """

    key: str
    label: str
    category: str
    summary: str
    source_record_name: str
    source_edition: str
    automation_status: str
    tags: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    requires_legacy: bool = False

    def atom(self) -> dict[str, Any]:
        plan = RulePlan(
            source_kind="rule",
            source_name=self.label,
            source_ref=f"local-rule:{self.source_record_name}",
            blocks=(
                NarrativeBlock(
                    id="rule-reference",
                    text=self.summary,
                    requires_dm_adjudication=self.automation_status != "full",
                ),
            ),
            root_block_ids=("rule-reference",),
            automation_confidence=(
                "exact"
                if self.automation_status == "full"
                else "partial"
                if self.automation_status == "partial"
                else "manual"
            ),
            automation_ready=self.automation_status == "full",
            unresolved_reasons=(
                ()
                if self.automation_status == "full"
                else ("该扩展已纳入规则库，但当前引擎仍需 DM 裁定或后续专用执行器",)
            ),
        )
        return {
            "entry_type": "rule",
            "name": self.label,
            "description": self.summary,
            "source_kind": "official",
            "source_record_id": f"local-rule:{self.source_record_name}",
            "source_name": f"本地 D&D 资料库 · {self.source_record_name}",
            "family_key": f"rule-extension:{self.category}",
            "tags": ["规则扩展", self.category, self.source_edition, *self.tags],
            "filters_json": {
                "extension_key": self.key,
                "category": self.category,
                "edition": self.source_edition,
                "automation_status": self.automation_status,
                "source_record_name": self.source_record_name,
            },
            "rules_json": {
                "extension_key": self.key,
                "source_record_name": self.source_record_name,
                "rule_plan": plan.model_dump(mode="json"),
            },
        }


_EXTENSIONS: tuple[RuleExtension, ...] = (
    RuleExtension(
        "encumbrance_variant",
        "变体负重",
        "探索",
        "启用后库存执行器按变体负重阈值标记负重状态；速度惩罚仍由 DM 在场景中执行。",
        "负重",
        "2024",
        "partial",
        ("已有引擎支持",),
    ),
    RuleExtension(
        "initiative_fixed",
        "固定先攻",
        "战斗",
        "使用固定先攻值替代每轮掷骰；具体数值由 DM 在遭遇中确认。",
        "先攻变体",
        "legacy",
        "dm_only",
        requires_legacy=True,
        conflicts_with=("initiative_side",),
    ),
    RuleExtension(
        "initiative_side",
        "阵营先攻",
        "战斗",
        "按阵营或队伍共享先攻顺序；同一阵营的行动顺序由 DM 确定。",
        "先攻变体",
        "legacy",
        "dm_only",
        requires_legacy=True,
        conflicts_with=("initiative_fixed",),
    ),
    RuleExtension(
        "cover",
        "掩体与命中掩体",
        "战斗",
        "启用掩体对 AC、敏捷豁免和攻击线的影响；当前保留 DM 复核入口。",
        "命中掩体",
        "legacy",
        "partial",
        requires_legacy=True,
    ),
    RuleExtension(
        "cleave",
        "顺劈",
        "战斗",
        "近战攻击溢出伤害时，可将剩余伤害转向相邻目标；是否满足条件由战斗引擎与 DM 共同确认。",
        "战斗选用项",
        "legacy",
        "partial",
        requires_legacy=True,
    ),
    RuleExtension(
        "hero_points",
        "英雄点数",
        "角色",
        "角色可消耗英雄点数获得一次额外优势或避免一次失败，具体消费时机需记录。",
        "英雄点数",
        "legacy",
        "partial",
        requires_legacy=True,
    ),
    RuleExtension(
        "fear_horror",
        "恐惧与惊恐",
        "叙事",
        "将恐惧与惊恐作为角色状态和场景后果处理，不把叙事文本误当成固定数值。",
        "心慌与惊恐",
        "legacy",
        "dm_only",
        requires_legacy=True,
    ),
    RuleExtension(
        "honor_sanity",
        "荣誉与理智",
        "角色",
        "增加荣誉或理智这类额外能力维度；具体初值、检定和恢复方式需由团规确认。",
        "新属性：荣誉和理智",
        "legacy",
        "dm_only",
        requires_legacy=True,
    ),
    RuleExtension(
        "chases",
        "追逐",
        "探索",
        "启用追逐阶段的障碍、冲刺和结束条件记录；当前以结构化 DM 裁定为主。",
        "追逐",
        "legacy",
        "partial",
        requires_legacy=True,
    ),
    RuleExtension(
        "lingering_injuries",
        "重伤",
        "角色",
        "启用重伤后果记录；不会自动凭 HP 猜测伤势，必须由 DM 选择具体后果。",
        "重伤",
        "legacy",
        "dm_only",
        requires_legacy=True,
    ),
    RuleExtension(
        "morale",
        "士气",
        "战斗",
        "为 NPC 与怪物保留士气裁定入口，撤退、投降和继续战斗由 DM 确认。",
        "士气",
        "legacy",
        "dm_only",
        requires_legacy=True,
    ),
    RuleExtension(
        "poisons_diseases",
        "毒药与疾病",
        "探索",
        "启用毒药、疾病的来源、持续和治疗记录；不会从物品名称自动推断伤害。",
        "毒药 / 疾病",
        "legacy",
        "partial",
        requires_legacy=True,
    ),
    RuleExtension(
        "firearms_explosives",
        "枪械与爆炸物",
        "战斗",
        "启用资料库中的枪械和爆炸物原子；具体伤害、装填和区域效果以条目积木为准。",
        "枪械 / 爆炸物",
        "legacy",
        "partial",
        requires_legacy=True,
    ),
    RuleExtension(
        "multiclassing",
        "兼职",
        "角色",
        "允许车卡阶段记录多职业等级、前置条件和多职业资源；升级仍需逐项确认。",
        "兼职规则",
        "2024",
        "partial",
    ),
    RuleExtension(
        "skill_variants",
        "技能变体",
        "角色",
        "启用本地资料中的技能变体；不会自动覆盖核心技能，需在车卡时明确选择。",
        "技能变体",
        "legacy",
        "dm_only",
        requires_legacy=True,
    ),
)

EXTENSIONS_BY_KEY = {extension.key: extension for extension in _EXTENSIONS}


def list_rule_extensions() -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "key": extension.key,
            "label": extension.label,
            "category": extension.category,
            "summary": extension.summary,
            "source_record_name": extension.source_record_name,
            "source_edition": extension.source_edition,
            "automation_status": extension.automation_status,
            "tags": list(extension.tags),
            "conflicts_with": list(extension.conflicts_with),
            "requires_legacy": extension.requires_legacy,
        }
        for extension in _EXTENSIONS
    )


def normalize_enabled_extensions(
    values: object,
    *,
    allow_legacy: bool = False,
) -> list[str]:
    raw = values if isinstance(values, (list, tuple, set)) else []
    keys = [str(value).strip() for value in raw if str(value).strip()]
    unknown = sorted(set(keys) - set(EXTENSIONS_BY_KEY))
    if unknown:
        raise ValueError(f"unknown rule extension: {', '.join(unknown)}")
    selected = set(keys)
    conflicts = sorted(
        f"{key} ↔ {conflict}"
        for key in selected
        for conflict in EXTENSIONS_BY_KEY[key].conflicts_with
        if conflict in selected and key < conflict
    )
    if conflicts:
        raise ValueError(f"conflicting rule extensions: {', '.join(conflicts)}")
    legacy = sorted(
        EXTENSIONS_BY_KEY[key].label
        for key in selected
        if EXTENSIONS_BY_KEY[key].requires_legacy
    )
    if legacy and not allow_legacy:
        raise ValueError(
            "这些规则扩展来自旧版/变体资料，需先开启 allow_legacy：" + "、".join(legacy)
        )
    return [extension.key for extension in _EXTENSIONS if extension.key in selected]


def seed_atoms_for_extensions(values: object) -> tuple[dict[str, Any], ...]:
    keys = normalize_enabled_extensions(values, allow_legacy=True)
    return tuple(EXTENSIONS_BY_KEY[key].atom() for key in keys)


def runtime_effects_for_extensions(values: object) -> dict[str, Any]:
    """Return only configuration effects that have a concrete local executor.

    Rule atoms remain useful reference material, but they must not imply that a
    module changes play until it drives a matching service.  The inventory
    summary already implements the variant thresholds, so enabling this module
    is the explicit switch that selects that executor mode.
    """

    keys = normalize_enabled_extensions(values, allow_legacy=True)
    if "encumbrance_variant" in keys:
        return {"encumbrance_mode": "variant"}
    return {}
