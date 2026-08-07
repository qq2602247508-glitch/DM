from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any


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
        effect_status="dm_only",
        overall_status="partial",
        persisted_state=("features",),
        consumers=("feat_prerequisite_validator",),
        dm_boundary="所选传奇恩惠的具体规则效果尚未逐项执行。",
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
        effect_status="dm_only",
        overall_status="partial",
        persisted_state=("proficiencies", "features"),
        consumers=("feat_prerequisite_validator", "equipment_proficiency"),
        dm_boundary="武器精通词条还没有逐项接入攻击结算。",
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

    feature_requirements = [item for item in requirements if item.kind == "feature_option"]
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
            count = int(requirement.maximum)
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
    for key, raw_selections in choices_by_key.items():
        selections = [str(item).strip() for item in raw_selections if str(item).strip()]
        for selection in selections:
            effect_status = "dm_only"
            if key == "expertise":
                current = after_skills.get(selection)
                if not isinstance(current, Mapping) or not current.get("proficient"):
                    raise ValueError(f"expertise requires an already proficient skill: {selection}")
                if current.get("expertise"):
                    raise ValueError(f"skill already has expertise: {selection}")
                after_skills[selection] = {**dict(current), "expertise": True}
                effect_status = "full"
            elif key == "weapon_mastery":
                if selection in existing_masteries:
                    raise ValueError(f"weapon mastery already selected: {selection}")
                after_proficiencies.append(
                    {
                        "kind": "weapon_mastery",
                        "name": selection,
                        "class_name": class_name,
                        "class_level": class_level,
                    }
                )
                existing_masteries.add(selection)
            elif key == "fighting_style":
                # Defense is already consumed by the shared AC runtime. Other
                # styles are persisted but remain explicitly partial/DM-only.
                compact = "".join(selection.lower().split())
                effect_status = (
                    "full"
                    if compact in {"防御", "defense", "防御defense", "战斗风格防御"}
                    else "dm_only"
                )

            overall = "full" if effect_status == "full" else "partial"
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
