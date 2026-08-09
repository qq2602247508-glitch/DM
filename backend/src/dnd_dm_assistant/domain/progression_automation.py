from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any

from dnd_dm_assistant.domain.growth_asset_catalog import (
    metamagic_asset,
    weapon_asset,
    weapon_is_eligible,
)


@dataclass(frozen=True)
class ProgressionAutomationProfile:
    category: str
    choice_key: str
    executor_kind: str
    grant_status: str
    effect_status: str
    overall_status: str
    persisted_state: tuple[str, ...]
    consumers: tuple[str, ...]
    dm_boundary: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# This table is configuration for a generic advancement executor.  The executor
# below dispatches on operation/choice kind; it never checks a class or feature
# id.  A selected feat remains a separate runtime contract from the class-table
# feature that grants the choice.
PROGRESSION_AUTOMATION_PROFILES: dict[str, ProgressionAutomationProfile] = {
    "属性值提升": ProgressionAutomationProfile(
        category="ability_score_or_feat_choice",
        choice_key="asi_or_feat",
        executor_kind="advancement_choice_grant",
        grant_status="full",
        effect_status="full",
        overall_status="full",
        persisted_state=("ability_scores", "features"),
        consumers=("ability_checks", "saving_throws", "combat", "hit_points"),
    ),
    "传奇恩惠": ProgressionAutomationProfile(
        category="epic_boon_choice",
        choice_key="epic_boon",
        executor_kind="advancement_choice_grant",
        grant_status="full",
        # The level-19 class feature ends after granting one eligible feat.
        # The selected feat is persisted as its own feature/runtime contract,
        # so its effect status must not be folded into (or falsely inherited
        # by) the class-table grant.
        effect_status="separate_asset_contract",
        overall_status="full",
        persisted_state=("features",),
        consumers=("advancement_service", "feat_prerequisite_validator"),
    ),
    "战斗风格": ProgressionAutomationProfile(
        category="fighting_style_choice",
        choice_key="fighting_style",
        executor_kind="advancement_choice_grant",
        grant_status="full",
        effect_status="partial",
        overall_status="partial",
        persisted_state=("features",),
        consumers=("feature_runtime_registry", "combat_start_modifiers"),
        dm_boundary="只有已结构化的战斗风格效果会进入消费者；其他选项保留裁定。",
    ),
    "武器精通": ProgressionAutomationProfile(
        category="weapon_mastery_choice",
        choice_key="weapon_mastery",
        executor_kind="advancement_choice_grant",
        grant_status="full",
        effect_status="separate_asset_contract",
        overall_status="full",
        persisted_state=("proficiencies", "features"),
        consumers=("feat_prerequisite_validator", "equipment_proficiency"),
        dm_boundary="武器选择与重配已闭环；各精通词条是独立运行时合同。",
    ),
    "超魔法": ProgressionAutomationProfile(
        category="metamagic_asset_choice",
        choice_key="metamagic_options",
        executor_kind="advancement_choice_grant",
        grant_status="full",
        effect_status="separate_asset_contract",
        overall_status="full",
        persisted_state=("features",),
        consumers=("advancement_service", "authoritative_metamagic_catalog"),
        dm_boundary="超魔法选项的获取与替换已闭环；各选项的施法效果独立审计。",
    ),
    "专精": ProgressionAutomationProfile(
        category="expertise_choice",
        choice_key="expertise",
        executor_kind="advancement_choice_grant",
        grant_status="full",
        effect_status="full",
        overall_status="full",
        persisted_state=("skills", "features"),
        consumers=("noncombat_skill_modifier", "player_skill_checks"),
    ),
    # Wizard's Scholar is the same typed expertise grant as the class-table
    # Expertise feature.  Keeping it as a profile entry makes the class name
    # and feature name configuration-only; the grant executor still operates
    # on the generic ``expertise`` choice key.
    "学者": ProgressionAutomationProfile(
        category="expertise_choice",
        choice_key="expertise",
        executor_kind="advancement_choice_grant",
        grant_status="full",
        effect_status="full",
        overall_status="full",
        persisted_state=("skills", "features"),
        consumers=("noncombat_skill_modifier", "player_skill_checks"),
    ),
}


def progression_automation_profile(
    feature_name: str,
) -> ProgressionAutomationProfile | None:
    identity = "".join(str(feature_name).split())
    for marker, profile in PROGRESSION_AUTOMATION_PROFILES.items():
        if marker in identity:
            return profile
    return None


def assign_progression_choices(
    requirements: Iterable[Any],
    *,
    choices_by_key: Mapping[str, Iterable[object]] | None,
    legacy_choices: Iterable[object] = (),
) -> tuple[dict[str, list[str]], bool]:
    """Validate and assign typed feature choices.

    The legacy flat list is a compatibility adapter.  It is deterministically
    sliced in requirement order so old clients keep working, but new callers
    should always submit choices_by_key and never depend on that ordering.
    """

    feature_requirements = [
        item
        for item in requirements
        if item.kind
        in {
            "feature_option",
            "selected_asset",
            "selected_asset_replacement",
            "selected_expertise",
            "selected_language",
            "selected_option_bundle",
        }
    ]
    requirement_by_key = {str(item.key): item for item in feature_requirements}
    raw_typed = dict(choices_by_key or {})
    unknown = sorted(set(raw_typed) - set(requirement_by_key))
    if unknown:
        raise ValueError("unknown class feature choice keys: " + ", ".join(unknown))

    assigned = {
        str(key): [str(item).strip() for item in values if str(item).strip()]
        for key, values in raw_typed.items()
    }
    legacy = [str(item).strip() for item in legacy_choices if str(item).strip()]
    used_legacy_adapter = bool(legacy)
    if legacy and assigned:
        raise ValueError("use feature_choices_by_key or feature_choices, not both")
    if legacy:
        cursor = 0
        for requirement in feature_requirements:
            # The legacy flat payload cannot express which optional typed
            # requirement a value belongs to.  Consume only mandatory slots;
            # optional replacements must use the keyed contract.
            count = int(requirement.maximum) if int(requirement.minimum) > 0 else 0
            assigned[str(requirement.key)] = legacy[cursor : cursor + count]
            cursor += count
        if cursor != len(legacy):
            raise ValueError("legacy class feature choices do not match typed requirements")

    for key, requirement in requirement_by_key.items():
        selected = assigned.get(key, [])
        if len(set(selected)) != len(selected):
            raise ValueError(f"class feature choice {key} cannot contain duplicates")
        if not int(requirement.minimum) <= len(selected) <= int(requirement.maximum):
            raise ValueError(
                f"class feature choice {key} requires {requirement.minimum} to "
                f"{requirement.maximum} selections"
            )
        options = {str(item) for item in getattr(requirement, "options", ())}
        if options and requirement.kind == "selected_asset_replacement":
            replacement_values = {
                value
                for selection in selected
                for value in selection.split("->")
                if value
            }
            invalid = sorted(replacement_values - options)
            if invalid:
                raise ValueError(
                    f"class feature choice {key} contains unsupported replacement assets: "
                    + ", ".join(invalid)
                )
        elif options and key not in {"fighting_style"}:
            invalid = sorted(set(selected) - options)
            if invalid:
                raise ValueError(
                    f"class feature choice {key} contains unsupported selections: "
                    + ", ".join(invalid)
                )
    return assigned, used_legacy_adapter


def apply_progression_choice_grants(
    *,
    choices_by_key: Mapping[str, Iterable[str]],
    skills: Mapping[str, Any],
    proficiencies: Iterable[Any],
    class_name: str,
    class_level: int,
    total_level: int,
    source_record_id: str | None,
    rule_year: str | int,
    allowed_languages: Iterable[str] = (),
) -> dict[str, Any]:
    """Apply reusable sheet mutations for typed advancement choices."""

    after_skills = deepcopy(dict(skills))
    after_proficiencies = deepcopy(list(proficiencies))
    grants: list[dict[str, Any]] = []

    existing_masteries = {
        str(item.get("name") or "")
        for item in after_proficiencies
        if isinstance(item, Mapping) and item.get("kind") == "weapon_mastery"
    }
    language_catalog = {str(item) for item in allowed_languages}
    existing_languages = {
        str(item).removeprefix("语言：")
        for item in after_proficiencies
        if str(item).startswith("语言：")
    }

    def grant_skill_bonus(skill_names: Iterable[str]) -> None:
        for skill in skill_names:
            current = after_skills.get(skill)
            existing = dict(current) if isinstance(current, Mapping) else {}
            after_skills[skill] = {
                **existing,
                "bonus_ability_modifier": "wisdom",
                "bonus_minimum": 1,
                "bonus_source": "selected_option_bundle",
            }
    for key, raw_selections in choices_by_key.items():
        selections = [str(item).strip() for item in raw_selections if str(item).strip()]
        for selection in selections:
            effect_status = "dm_only"
            if key in {"expertise", "deft_explorer_expertise"}:
                current = after_skills.get(selection)
                if not isinstance(current, Mapping) or not current.get("proficient"):
                    raise ValueError(f"expertise requires an already proficient skill: {selection}")
                if current.get("expertise"):
                    raise ValueError(f"skill already has expertise: {selection}")
                after_skills[selection] = {**dict(current), "expertise": True}
                effect_status = "full"
            elif key == "deft_explorer_languages":
                if selection == "通用语" or selection not in language_catalog:
                    raise ValueError(f"unsupported deft explorer language: {selection}")
                if selection in existing_languages:
                    raise ValueError(f"language already known: {selection}")
                after_proficiencies.append(f"语言：{selection}")
                existing_languages.add(selection)
                effect_status = "full"
            elif key == "primal_order":
                if selection == "warden":
                    for proficiency in ("军用武器", "中甲"):
                        if proficiency not in after_proficiencies:
                            after_proficiencies.append(proficiency)
                elif selection == "magician":
                    grant_skill_bonus(("奥秘", "自然"))
                else:
                    raise ValueError(f"unsupported primal order: {selection}")
                effect_status = "full"
            elif key == "divine_order":
                if selection == "protector":
                    for proficiency in ("军用武器", "重甲"):
                        if proficiency not in after_proficiencies:
                            after_proficiencies.append(proficiency)
                elif selection == "thaumaturge":
                    grant_skill_bonus(("奥秘", "宗教"))
                else:
                    raise ValueError(f"unsupported divine order: {selection}")
                effect_status = "full"
            elif key in {
                "primal_order_cantrip",
                "divine_order_cantrip",
                "blessed_warrior_cantrips",
                "druidic_warrior_cantrips",
            }:
                # The authoritative spell catalog consumer materializes these
                # choices.  Keep only one full audit grant for the selected
                # option bundle rather than duplicating the spell asset here.
                continue
            elif key in {"fighting_style", "fighting_style_replacement"}:
                # The authoritative feat-catalog resolver owns these assets.
                # It persists the selected feat as an independent contract.
                continue
            elif key == "weapon_mastery":
                asset = weapon_asset(selection)
                if asset is None:
                    raise ValueError(f"weapon mastery is not in the 2024 catalog: {selection}")
                if asset.id in existing_masteries or asset.name in existing_masteries:
                    raise ValueError(f"weapon mastery already selected: {asset.name}")
                policy = {
                    "野蛮人": "simple_or_martial_melee",
                    "战士": "simple_or_martial",
                    "圣武士": "character_proficient",
                    "游侠": "character_proficient",
                    "游荡者": "character_proficient",
                }.get(class_name, "character_proficient")
                if not weapon_is_eligible(
                    asset,
                    policy=policy,
                    proficiencies=after_proficiencies,
                ):
                    raise ValueError(f"weapon mastery selection is not eligible: {asset.name}")
                after_proficiencies.append(
                    {
                        "kind": "weapon_mastery",
                        "id": asset.id,
                        "name": asset.name,
                        "weapon_category": asset.category,
                        "range_kind": asset.range_kind,
                        "mastery": asset.mastery,
                        "source_record_id": asset.source_record_id,
                        "mastery_source_record_id": "08fd9f442907e6520302fddf",
                        "class_name": class_name,
                        "class_level": class_level,
                        "selected_asset_status": "full",
                        "effect_status": "separate_asset_contract",
                    }
                )
                existing_masteries.update({asset.id, asset.name})
                selection = asset.name
            elif key == "metamagic_options":
                asset = metamagic_asset(selection)
                if asset is None:
                    raise ValueError(f"metamagic option is not in the 2024 catalog: {selection}")
                selection = asset.name
                effect_status = "separate_asset_contract"
            elif key == "metamagic_replacement":
                # Replacement is resolved against the character's persisted
                # option assets by AdvancementService.  This grant records the
                # typed intent without pretending the option effect is done.
                old, separator, new = selection.partition("->")
                if not separator or metamagic_asset(old) is None or metamagic_asset(new) is None:
                    raise ValueError("metamagic replacement must be old->new catalog options")
                selection = f"{metamagic_asset(old).name}->{metamagic_asset(new).name}"
                effect_status = "separate_asset_contract"

            overall = (
                "full"
                if effect_status in {"full", "separate_asset_contract"}
                else "partial"
            )
            grants.append(
                {
                    "name": selection,
                    "kind": "advancement_choice_grant",
                    "choice_key": key,
                    "class_name": class_name,
                    "class_level": class_level,
                    "level": total_level,
                    "source_record_id": source_record_id,
                    "rule_year": rule_year,
                    "runtime": {
                        "automation_status": overall,
                        "requires_dm_adjudication": overall != "full",
                        "execution": {
                            "kind": "advancement_choice_grant",
                            "consumer": "advancement_service",
                            "status": "ready",
                            "grant_status": "full",
                            "effect_status": effect_status,
                        },
                        "note": (
                            "选择已结构化授予并写入角色权威状态。"
                            if overall == "full"
                            else "选择已写入权威状态；具体规则效果尚未全部自动执行。"
                        ),
                    },
                }
            )
    return {
        "skills": after_skills,
        "proficiencies": after_proficiencies,
        "grants": grants,
    }


def progression_acceptance_matrix(rules: Iterable[Any]) -> list[dict[str, Any]]:
    """Build the auditable migration/acceptance rows for the five target classes."""

    rows: list[dict[str, Any]] = []
    for rule in rules:
        for level_rule in rule.levels:
            for feature in level_rule.features:
                profile = progression_automation_profile(feature)
                if profile is None:
                    continue
                rows.append(
                    {
                        "class_name": rule.name,
                        "class_level": level_rule.level,
                        "feature_name": feature,
                        **profile.as_dict(),
                        "config_present": True,
                        "real_consumer": bool(profile.consumers),
                    }
                )
    return rows
