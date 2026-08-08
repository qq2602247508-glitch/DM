from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.character_catalog import CharacterCatalog
from dnd_dm_assistant.domain.advancement import (
    average_hp_gain,
    merge_spell_slot_resources,
    proficiency_bonus_for_level,
    validate_multiclass_prerequisites,
)
from dnd_dm_assistant.domain.advancement_choices import (
    CORE_SELECTED_SPELL_GRANTS,
    advancement_choice_requirements,
    canonical_class_name,
    core_feat_rules_from_records,
    core_feature_grants,
    core_runtime_actions,
    extension_feat_rules_from_records,
    find_feat_rule,
    maximum_class_spell_level,
    progression_resource_updates,
    progression_scaling_updates,
    subclass_runtime_grants,
    validate_feat_prerequisites,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.feature_runtime import compile_feature_runtime_registry
from dnd_dm_assistant.domain.noncombat_actions import SKILL_RULES
from dnd_dm_assistant.domain.progression_automation import (
    apply_progression_choice_grants,
    assign_progression_choices,
)
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    AdvancementRecord,
    Campaign,
    Character,
    CharacterCompanion,
    OperationTransaction,
)

XP_THRESHOLDS = (
    0,
    300,
    900,
    2700,
    6500,
    14000,
    23000,
    34000,
    48000,
    64000,
    85000,
    100000,
    120000,
    140000,
    165000,
    195000,
    225000,
    265000,
    305000,
    355000,
)


def _fixed_subclass_spell_additions(
    subclass: dict[str, Any] | None,
    *,
    class_name: str,
    target_class_level: int,
    spell_catalog: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    """Resolve fixed subclass spell tables against the authoritative catalog.

    The source parser identifies only ``always prepared`` contracts.  This
    resolver then matches exact catalog names in those source descriptions;
    no spell is guessed from a feature identifier or free-form client input.
    """

    if not isinstance(subclass, dict):
        return []
    additions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in subclass.get("feature_definitions") or ():
        if not isinstance(raw, dict) or int(raw.get("class_level") or 0) > target_class_level:
            continue
        description = str(raw.get("description") or "")
        if "你选择的这些法术" in description or "自选法术" in description:
            continue
        if not re.search(r"(?:始终|总是)准备着(?:特定的法术|表中对应的法术)", description):
            continue
        if not re.search(r"(?:法术表|Spells|准备法术)", description, re.IGNORECASE):
            continue
        feature_id = str(raw.get("id") or raw.get("name") or "")
        for spell in spell_catalog:
            name = str(spell.get("name") or "").strip()
            source_id = str(spell.get("source_record_id") or "").strip()
            if len(name) < 2 or name not in description:
                continue
            identity = source_id or name
            if identity in seen:
                continue
            seen.add(identity)
            additions.append(
                {
                    **dict(spell),
                    "name": name,
                    "source_record_id": source_id or None,
                    "spell_level": int(spell.get("level") or 0),
                    "classes": list(spell.get("classes") or []),
                    "class_name": class_name,
                    "prepared": True,
                    "always_prepared": True,
                    "source_feature_id": feature_id,
                    "source_feature_name": str(raw.get("name") or ""),
                }
            )
    return additions


def _selected_subclass_spell_additions(
    grants: list[dict[str, Any]],
    *,
    selected_choices: dict[str, list[str]],
    spell_catalog: tuple[dict[str, Any], ...],
    owner_class: str,
    owner_level: int,
) -> list[dict[str, Any]]:
    """Resolve typed selected-spell grants without feature-name dispatch.

    A configuration contract supplies the allowed source classes, school,
    count and level ceiling.  This adapter validates choices against the local
    spell catalog, then writes ordinary spell-sheet rows consumed by existing
    preparation and spell-economy flows.
    """

    by_identity: dict[str, dict[str, Any]] = {}
    for spell in spell_catalog:
        for identity in (str(spell.get("source_record_id") or ""), str(spell.get("name") or "")):
            if identity:
                by_identity[identity] = spell
    additions: list[dict[str, Any]] = []
    for grant in grants:
        runtime = grant.get("runtime") if isinstance(grant, dict) else None
        registry = runtime.get("registry") if isinstance(runtime, dict) else None
        advancement = registry.get("advancement") if isinstance(registry, dict) else None
        if not isinstance(advancement, dict) or advancement.get("kind") != "selected_spell_grant":
            continue
        selection = advancement.get("selection")
        feature_id = str(grant.get("feature_id") or "").strip()
        if not isinstance(selection, dict) or not feature_id:
            raise ValueError("受控法术选择缺少特性或选择合同")
        choices = [
            str(item).strip() for item in selected_choices.get(feature_id, []) if str(item).strip()
        ]
        count = int(selection.get("count") or 0)
        if selection.get("add_one_per_new_spell_level") is True:
            # School specialists receive the initial two spells at level 3,
            # then exactly one more whenever their class first gains access to
            # a higher spell level.  The persisted selection is cumulative.
            count += max(0, maximum_class_spell_level(owner_class, owner_level) - 2)
        if count < 1 or len(choices) != count or len(set(choices)) != len(choices):
            raise ValueError(f"子职特性{feature_id}必须选择 {count} 道不重复法术")
        allowed_classes = {
            canonical_class_name(str(item)) for item in selection.get("allowed_classes") or ()
        }
        requested_school = str(selection.get("school") or "").strip()
        maximum = selection.get("maximum_level")
        maximum_level = (
            maximum_class_spell_level(owner_class, owner_level)
            if maximum == "owner_class"
            else int(maximum or 0)
        )
        grant_class = (
            owner_class
            if selection.get("grant_class") == "owner_class"
            else str(selection.get("grant_class") or owner_class)
        )
        for choice in choices:
            spell = by_identity.get(choice)
            if spell is None:
                raise ValueError(f"子职特性{feature_id}选择的法术不在本地2024目录：{choice}")
            spell_classes = {canonical_class_name(str(item)) for item in spell.get("classes") or ()}
            if not allowed_classes or not (spell_classes & allowed_classes):
                raise ValueError(f"子职特性{feature_id}选择了不允许来源的法术：{spell.get('name')}")
            if requested_school and str(spell.get("school") or "") != requested_school:
                raise ValueError(
                    f"子职特性{feature_id}选择的法术学派不符合要求：{spell.get('name')}"
                )
            spell_level = int(spell.get("level") or 0)
            if selection.get("spellbook") is True and spell_level < 1:
                raise ValueError(
                    f"子职特性{feature_id}不能将戏法作为法术书增补：{spell.get('name')}"
                )
            if spell_level > maximum_level:
                raise ValueError(f"子职特性{feature_id}选择的法术环阶过高：{spell.get('name')}")
            additions.append(
                {
                    **dict(spell),
                    "name": str(spell.get("name") or ""),
                    "source_record_id": str(spell.get("source_record_id") or "") or None,
                    "spell_level": spell_level,
                    "classes": list(spell.get("classes") or []),
                    "class_name": grant_class,
                    "prepared": bool(selection.get("always_prepared")),
                    "always_prepared": bool(selection.get("always_prepared")),
                    "spellbook": bool(selection.get("spellbook")),
                    "source_feature_id": feature_id,
                    "source_feature_name": str(grant.get("name") or ""),
                    "granted_spell_access": True,
                    "does_not_count_toward_level_learning": True,
                }
            )
    return additions


def _fixed_subclass_feature_spell_additions(
    grants: list[dict[str, Any]],
    *,
    spell_catalog: tuple[dict[str, Any], ...],
    owner_class: str,
) -> list[dict[str, Any]]:
    """Apply typed fixed spell grants from subclass runtime contracts."""

    by_name = {str(spell.get("name") or ""): spell for spell in spell_catalog}
    additions: list[dict[str, Any]] = []
    for grant in grants:
        runtime = grant.get("runtime") if isinstance(grant, dict) else None
        registry = runtime.get("registry") if isinstance(runtime, dict) else None
        advancement = registry.get("advancement") if isinstance(registry, dict) else None
        if not isinstance(advancement, dict) or advancement.get("kind") != "fixed_spell_grant":
            continue
        spell_names = advancement.get("spells")
        feature_id = str(grant.get("feature_id") or "").strip()
        if not feature_id or not isinstance(spell_names, list) or not spell_names:
            raise ValueError("固定法术授予缺少特性或法术合同")
        for spell_name in spell_names:
            spell = by_name.get(str(spell_name).strip())
            if spell is None:
                raise ValueError(f"固定法术授予未在本地2024目录找到：{spell_name}")
            spell_level = int(spell.get("level") or 0)
            additions.append(
                {
                    **dict(spell),
                    "name": str(spell.get("name") or ""),
                    "source_record_id": str(spell.get("source_record_id") or "") or None,
                    "spell_level": spell_level,
                    "classes": list(spell.get("classes") or []),
                    "class_name": (
                        owner_class
                        if advancement.get("grant_class") == "owner_class"
                        else str(advancement.get("grant_class") or owner_class)
                    ),
                    "prepared": True,
                    "always_prepared": True,
                    "spellcasting_ability": str(advancement.get("casting_ability") or ""),
                    "ritual_only": bool(advancement.get("ritual_only")),
                    "resource_key": str(advancement.get("free_cast_resource_key") or ""),
                    "resource_cost": 1 if advancement.get("free_cast_resource_key") else 0,
                    "source_feature_id": feature_id,
                    "source_feature_name": str(grant.get("name") or ""),
                    "granted_spell_access": True,
                    "does_not_count_toward_level_learning": True,
                }
            )
    return additions


def _selected_core_spell_additions(
    choices_by_key: dict[str, list[str]],
    *,
    spell_catalog: tuple[dict[str, Any], ...],
    owner_class: str,
) -> list[dict[str, Any]]:
    """Materialize configured core feature spell choices onto the sheet."""

    by_identity: dict[str, dict[str, Any]] = {}
    for spell in spell_catalog:
        for identity in (
            str(spell.get("source_record_id") or ""),
            str(spell.get("name") or ""),
        ):
            if identity:
                by_identity[identity] = spell
    additions: list[dict[str, Any]] = []
    for key, contract in CORE_SELECTED_SPELL_GRANTS.items():
        choices = [str(item).strip() for item in choices_by_key.get(key, []) if str(item).strip()]
        count = int(contract.get("count") or 0)
        if not choices:
            continue
        if len(choices) != count or len(set(choices)) != len(choices):
            raise ValueError(f"职业特性{key}必须选择 {count} 道不重复法术")
        allowed_classes = {
            canonical_class_name(str(item)) for item in contract.get("allowed_classes") or ()
        }
        exact_level = int(contract.get("exact_level") or 0)
        for choice in choices:
            spell = by_identity.get(choice)
            if spell is None:
                raise ValueError(f"职业特性{key}选择的法术不在本地2024目录：{choice}")
            spell_classes = {canonical_class_name(str(item)) for item in spell.get("classes") or ()}
            if not (spell_classes & allowed_classes):
                raise ValueError(f"职业特性{key}选择了不允许来源的法术：{spell.get('name')}")
            spell_level = int(spell.get("level") or 0)
            if spell_level != exact_level:
                raise ValueError(f"职业特性{key}必须选择{exact_level}环法术：{spell.get('name')}")
            additions.append(
                {
                    **dict(spell),
                    "name": str(spell.get("name") or ""),
                    "source_record_id": str(spell.get("source_record_id") or "") or None,
                    "spell_level": spell_level,
                    "classes": list(spell.get("classes") or []),
                    "class_name": owner_class,
                    "prepared": bool(contract.get("always_prepared")),
                    "always_prepared": bool(contract.get("always_prepared")),
                    "resource_key": str(contract.get("free_cast_resource_key") or ""),
                    "resource_cost": 1,
                    "source_feature_id": key,
                    "source_feature_name": key,
                    "granted_spell_access": True,
                    "does_not_count_toward_level_learning": True,
                }
            )
    return additions


class AdvancementService:
    def __init__(self, engine: Engine, catalog: CharacterCatalog) -> None:
        self.engine = engine
        self.catalog = catalog

    @staticmethod
    def _character(session: Session, campaign_id: str, character_id: str) -> Character:
        character = session.get(Character, character_id)
        if character is None or character.campaign_id != campaign_id:
            raise StateNotFoundError("character not found in campaign")
        return character

    def _class_rule(
        self,
        class_name: str,
        *,
        enabled_content_packs: object = (),
        allow_legacy: bool = False,
    ) -> Any:
        class_name = canonical_class_name(class_name)
        rule = next(
            (
                item
                for item in self.catalog.classes(
                    enabled_content_packs=enabled_content_packs,
                    allow_legacy=allow_legacy,
                )
                if item.name == class_name
            ),
            None,
        )
        if rule is None:
            raise ValueError(
                "selected class is unavailable in the campaign's structured rule catalog"
            )
        return rule

    def _spell_catalog(
        self,
        *,
        enabled_content_packs: object = (),
        allow_legacy: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        return tuple(
            dict(item)
            for item in self.catalog.options(
                enabled_content_packs=enabled_content_packs,
                allow_legacy=allow_legacy,
            ).get("spells", [])
        )

    def _feat_rules(
        self,
        *,
        enabled_content_packs: object = (),
        allow_legacy: bool = False,
    ) -> tuple[Any, ...]:
        records = self.catalog._records(
            enabled_content_packs=enabled_content_packs,
            allow_legacy=allow_legacy,
        )
        return (
            *core_feat_rules_from_records(records),
            *extension_feat_rules_from_records(
                record for record in records if record.get("content_pack_key")
            ),
        )

    @staticmethod
    def _merge_progression_resources(
        resources: dict[str, Any],
        updates: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        merged = dict(resources)
        for key, resource_update in updates.items():
            if "max" not in resource_update:
                # The catalog can describe a formula (for example bardic
                # inspiration) without enough persisted ability scores to
                # evaluate it.  Do not invent a usable total in that case.
                continue
            old = merged.get(key)
            old_max = int(old.get("max", 0)) if isinstance(old, dict) else 0
            old_current = int(old.get("current", old_max)) if isinstance(old, dict) else 0
            new_max = max(old_max, int(resource_update["max"]))
            merged[key] = {
                **(old if isinstance(old, dict) else {}),
                **resource_update,
                "current": min(new_max, old_current + max(0, new_max - old_max)),
            }
        return merged

    def _rebuild_multiclass_progression_resources(
        self,
        *,
        class_levels: dict[str, int],
        subclass_choices: dict[str, str],
        ability_scores: dict[str, int],
        enabled_content_packs: object,
        allow_legacy: bool,
        existing_resources: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        """Recalculate every owned class resource after an advancement.

        Shared spell slots were already recalculated during advancement, but
        class-specific pools were previously updated only for the class being
        leveled.  That left imported or newly-created multiclass sheets with a
        missing pool for the other class.  Pool keys remain shared where the
        sheet contract defines one; the merge preserves spent current values.
        """

        resources = merge_spell_slot_resources(
            dict(existing_resources),
            class_levels,
            subclass_choices,
        )
        updates: dict[str, dict[str, Any]] = {}
        for owned_class, class_level in sorted(class_levels.items()):
            class_rule = self._class_rule(
                owned_class,
                enabled_content_packs=enabled_content_packs,
                allow_legacy=allow_legacy,
            )
            updates.update(
                progression_resource_updates(
                    class_rule,
                    int(class_level),
                    ability_scores=ability_scores,
                )
            )
            selected_subclass_name = str(subclass_choices.get(owned_class) or "").strip()
            selected_subclass = next(
                (
                    dict(item)
                    for item in class_rule.subclasses
                    if str(item.get("name") or "") == selected_subclass_name
                ),
                None,
            )
            if selected_subclass is None:
                continue
            for subclass_level in range(1, int(class_level) + 1):
                subclass_update = subclass_runtime_grants(
                    selected_subclass,
                    class_name=owned_class,
                    target_class_level=subclass_level,
                    ability_scores=ability_scores,
                    current_class_level=int(class_level),
                )
                updates.update(dict(subclass_update["resources"]))
        return self._merge_progression_resources(resources, updates), updates

    @staticmethod
    def _state_from_character(character: Character) -> SimpleNamespace:
        """Copy just the persisted character state needed by a sequential preview."""

        return SimpleNamespace(
            id=character.id,
            name=character.name,
            version=character.version,
            level=character.level,
            experience=character.experience,
            class_name=character.class_name,
            hp=character.hp,
            max_hp=character.max_hp,
            ability_scores=deepcopy(dict(character.ability_scores or {})),
            class_levels=deepcopy(dict(character.class_levels or {})),
            subclass_choices=deepcopy(dict(character.subclass_choices or {})),
            spells=deepcopy(list(character.spells or [])),
            resources=deepcopy(dict(character.resources or {})),
            features=deepcopy(list(character.features or [])),
            actions=deepcopy(list(character.actions or [])),
            proficiencies=deepcopy(list(character.proficiencies or [])),
            skills=deepcopy(dict(character.skills or {})),
        )

    @staticmethod
    def _apply_preview_to_state(state: Any, preview: dict[str, Any]) -> None:
        """Advance an in-memory state by one already-validated preview."""

        after = dict(preview["after"])
        state.level = int(preview["to_level"])
        state.hp = int(after["hp"])
        state.max_hp = int(after["max_hp"])
        state.ability_scores = deepcopy(dict(after["ability_scores"]))
        state.class_levels = deepcopy(dict(after["class_levels"]))
        state.subclass_choices = deepcopy(dict(after["subclass_choices"]))
        state.spells = deepcopy(list(after["spells"]))
        state.resources = deepcopy(dict(after["resources"]))
        state.features = deepcopy(list(after.get("features", state.features)))
        state.actions = deepcopy(list(after.get("actions", state.actions)))
        state.proficiencies = deepcopy(list(after.get("proficiencies", state.proficiencies)))
        state.skills = deepcopy(dict(after.get("skills", state.skills)))
        state.version += 1

    @staticmethod
    def _apply_preview_to_character(
        character: Character,
        preview: dict[str, Any],
        *,
        updated_at: datetime,
    ) -> None:
        """Persist an already-confirmed preview without recomputing any rule."""

        after = dict(preview["after"])
        character.level = int(preview["to_level"])
        character.hp = int(after["hp"])
        character.max_hp = int(after["max_hp"])
        character.ability_scores = dict(after["ability_scores"])
        character.class_levels = dict(after["class_levels"])
        character.subclass_choices = dict(after["subclass_choices"])
        character.spells = list(after["spells"])
        character.resources = dict(after["resources"])
        character.features = list(after.get("features", character.features or []))
        character.actions = list(after.get("actions", character.actions or []))
        character.proficiencies = list(after.get("proficiencies", character.proficiencies or []))
        character.skills = dict(after.get("skills", character.skills or {}))
        character.version += 1
        character.updated_at = updated_at

    @staticmethod
    def _merge_runtime_actions(
        existing: list[Any],
        additions: list[dict[str, Any]],
    ) -> list[Any]:
        """Merge sheet actions by their durable class-feature identity."""

        result = [deepcopy(item) for item in existing]
        known = {
            (
                str(item.get("name") or ""),
                str(item.get("kind") or ""),
                str(item.get("class_name") or ""),
                int(item.get("class_level") or 0),
            )
            for item in result
            if isinstance(item, dict)
        }
        for action in additions:
            identity = (
                str(action.get("name") or ""),
                str(action.get("kind") or ""),
                str(action.get("class_name") or ""),
                int(action.get("class_level") or 0),
            )
            if identity not in known:
                result.append(deepcopy(action))
                known.add(identity)
        return result

    @staticmethod
    def _apply_preview_with_cas(
        session: Session,
        *,
        campaign_id: str,
        character: Character,
        preview: dict[str, Any],
        expected_version: int,
        updated_at: datetime,
    ) -> None:
        """Persist the already-previewed sheet with a database CAS predicate."""

        after = dict(preview["after"])
        outcome = session.execute(
            update(Character)
            .where(
                Character.id == character.id,
                Character.campaign_id == campaign_id,
                Character.version == expected_version,
            )
            .values(
                level=int(preview["to_level"]),
                hp=int(after["hp"]),
                max_hp=int(after["max_hp"]),
                ability_scores=dict(after["ability_scores"]),
                class_levels=dict(after["class_levels"]),
                subclass_choices=dict(after["subclass_choices"]),
                spells=list(after["spells"]),
                resources=dict(after["resources"]),
                features=list(after.get("features", character.features or [])),
                actions=list(after.get("actions", character.actions or [])),
                proficiencies=list(after.get("proficiencies", character.proficiencies or [])),
                skills=dict(after.get("skills", character.skills or {})),
                version=expected_version + 1,
                updated_at=updated_at,
            )
        )
        if outcome.rowcount != 1:
            actual = session.scalar(
                select(Character.version).where(
                    Character.id == character.id,
                    Character.campaign_id == campaign_id,
                )
            )
            raise VersionConflict(
                "character",
                character.id,
                expected_version,
                int(actual or 0),
            )
        session.expire(character)

    @staticmethod
    def _merge_feature_grants(
        existing: list[Any],
        grants: list[dict[str, Any]],
    ) -> list[Any]:
        """Avoid duplicate persisted grants when a preview is replayed in a batch."""

        result = [deepcopy(item) for item in existing]
        known = {
            (
                str(item.get("name") or ""),
                str(item.get("kind") or ""),
                str(item.get("class_name") or ""),
                int(item.get("class_level") or 0),
            )
            for item in result
            if isinstance(item, dict)
        }
        for grant in grants:
            identity = (
                str(grant.get("name") or ""),
                str(grant.get("kind") or ""),
                str(grant.get("class_name") or ""),
                int(grant.get("class_level") or 0),
            )
            if identity in known:
                continue
            result.append(deepcopy(grant))
            known.add(identity)
        return result

    @staticmethod
    def _apply_subclass_proficiency_choices(
        grants: list[dict[str, Any]],
        *,
        selected_choices: dict[str, list[str]],
        skills: dict[str, Any],
        allow_missing: bool = False,
    ) -> dict[str, dict[str, Any]]:
        """Apply configuration-driven subclass skill-proficiency selections.

        The choice request is already persisted on the subclass feature grant.
        This method additionally performs the consequential sheet mutation so
        the same choice is consumed by ``skill_modifier`` and player skill
        checks.  It reads only the typed advancement contract, never a
        subclass or feature name.
        """

        after = deepcopy(skills)
        for grant in grants:
            runtime = grant.get("runtime")
            registry = runtime.get("registry") if isinstance(runtime, dict) else None
            advancement = registry.get("advancement") if isinstance(registry, dict) else None
            if not isinstance(advancement, dict):
                continue
            if (
                advancement.get("kind") != "proficiency_choice"
                or advancement.get("option_kind") != "skill"
                or advancement.get("operation") != "grant_proficiency"
                or advancement.get("allowed_options") != "supported_skills"
            ):
                continue
            feature_id = str(grant.get("feature_id") or "").strip()
            requirement = advancement.get("choice_requirement")
            if not feature_id or not isinstance(requirement, dict):
                raise ValueError("子职技能熟练选择缺少可验证的特性或数量合同")
            choices = [
                str(choice).strip()
                for choice in selected_choices.get(feature_id, [])
                if str(choice).strip()
            ]
            minimum = int(requirement.get("minimum") or 0)
            maximum = int(requirement.get("maximum") or 0)
            if not minimum <= len(choices) <= maximum:
                if allow_missing:
                    continue
                raise ValueError(
                    f"子职特性{feature_id}必须选择 {minimum} 至 {maximum} 项技能，"
                    f"当前为 {len(choices)} 项"
                )
            if len(set(choices)) != len(choices):
                raise ValueError("子职技能熟练选择不能重复")
            invalid = sorted(set(choices) - set(SKILL_RULES))
            if invalid:
                raise ValueError("子职技能熟练包含不支持的技能：" + "、".join(invalid))
            for skill in choices:
                current = after.get(skill)
                existing = dict(current) if isinstance(current, dict) else {}
                after[skill] = {**existing, "proficient": True}
        return after

    @staticmethod
    def _apply_subclass_typed_proficiency_choices(
        grants: list[dict[str, Any]],
        *,
        selected_choices: dict[str, list[str]],
        skills: dict[str, Any],
        proficiencies: list[Any],
    ) -> tuple[dict[str, dict[str, Any]], list[Any]]:
        """Apply grouped skill/tool choices from a typed subclass contract."""

        after_skills = deepcopy(skills)
        after_proficiencies = deepcopy(proficiencies)
        for grant in grants:
            runtime = grant.get("runtime")
            registry = runtime.get("registry") if isinstance(runtime, dict) else None
            advancement = registry.get("advancement") if isinstance(registry, dict) else None
            if (
                not isinstance(advancement, dict)
                or advancement.get("kind") != "typed_proficiency_choice"
            ):
                continue
            feature_id = str(grant.get("feature_id") or "").strip()
            groups = advancement.get("choice_groups")
            if not feature_id or not isinstance(groups, list):
                raise ValueError("子职类型化熟练选择缺少特性或分组选项合同")
            choices = [
                str(choice).strip()
                for choice in selected_choices.get(feature_id, [])
                if str(choice).strip()
            ]
            if len(set(choices)) != len(choices):
                raise ValueError("子职类型化熟练选择不能重复")
            consumed: set[str] = set()
            for group in groups:
                if not isinstance(group, dict):
                    raise ValueError("子职类型化熟练选择分组无效")
                prefix = str(group.get("prefix") or "").strip()
                kind = str(group.get("kind") or "").strip()
                allowed = group.get("allowed_options")
                minimum = int(group.get("minimum") or 0)
                maximum = int(group.get("maximum") or 0)
                if not prefix or kind not in {"skill", "tool"} or not isinstance(allowed, list):
                    raise ValueError("子职类型化熟练选择分组不受支持")
                selected = [
                    choice.split(":", 1)[1].strip()
                    for choice in choices
                    if choice.startswith(prefix + ":") and choice.split(":", 1)[1].strip()
                ]
                consumed.update(prefix + ":" + name for name in selected)
                if not minimum <= len(selected) <= maximum:
                    raise ValueError(
                        f"子职特性{feature_id}必须选择 {minimum} 至 {maximum} 项{kind}，"
                        f"当前为 {len(selected)} 项"
                    )
                invalid = sorted(set(selected) - {str(item) for item in allowed})
                if invalid:
                    raise ValueError(
                        f"子职特性{feature_id}包含不允许的{kind}：" + "、".join(invalid)
                    )
                if kind == "skill":
                    unsupported = sorted(set(selected) - set(SKILL_RULES))
                    if unsupported:
                        raise ValueError("子职技能熟练包含不支持的技能：" + "、".join(unsupported))
                    for skill in selected:
                        current = after_skills.get(skill)
                        existing = dict(current) if isinstance(current, dict) else {}
                        after_skills[skill] = {**existing, "proficient": True}
                else:
                    for tool in selected:
                        if tool not in after_proficiencies:
                            after_proficiencies.append(tool)
            if set(choices) != consumed:
                raise ValueError("子职类型化熟练选择必须使用 <类型>:<名称> 格式")
        return after_skills, after_proficiencies

    @staticmethod
    def _ability_score_caps(grants: list[dict[str, Any]]) -> dict[str, int]:
        """Collect typed ability caps already owned by the character."""

        caps: dict[str, int] = {}
        for grant in grants:
            runtime = grant.get("runtime")
            registry = runtime.get("registry") if isinstance(runtime, dict) else None
            advancement = registry.get("advancement") if isinstance(registry, dict) else None
            raw_caps = advancement.get("caps") if isinstance(advancement, dict) else None
            if not isinstance(raw_caps, dict):
                continue
            for ability, raw_cap in raw_caps.items():
                if isinstance(raw_cap, int) and not isinstance(raw_cap, bool):
                    caps[str(ability)] = max(caps.get(str(ability), 20), raw_cap)
        return caps

    @staticmethod
    def _apply_fixed_ability_score_adjustments(
        grants: list[dict[str, Any]],
        *,
        ability_scores: dict[str, int],
    ) -> tuple[dict[str, int], dict[str, int]]:
        """Apply typed fixed adjustments using their declared score caps."""

        after = dict(ability_scores)
        applied: dict[str, int] = {}
        for grant in grants:
            runtime = grant.get("runtime")
            registry = runtime.get("registry") if isinstance(runtime, dict) else None
            advancement = registry.get("advancement") if isinstance(registry, dict) else None
            if not isinstance(advancement, dict):
                continue
            if advancement.get("kind") != "fixed_ability_score_adjustment":
                continue
            adjustments = advancement.get("adjustments")
            caps = advancement.get("caps")
            if not isinstance(adjustments, dict) or not isinstance(caps, dict):
                raise ValueError("固定属性提升缺少调整值或上限合同")
            for ability, raw_delta in adjustments.items():
                if (
                    not isinstance(raw_delta, int)
                    or isinstance(raw_delta, bool)
                    or raw_delta < 1
                    or not isinstance(caps.get(ability), int)
                ):
                    raise ValueError("固定属性提升合同包含非法数值")
                if ability not in after:
                    raise ValueError(f"固定属性提升引用未知属性：{ability}")
                cap = int(caps[ability])
                before = int(after[ability])
                after[ability] = min(cap, before + raw_delta)
                applied[ability] = applied.get(ability, 0) + (after[ability] - before)
        return after, applied

    @staticmethod
    def _replace_class_progression_grants(
        existing: list[Any],
        *,
        class_name: str,
        grants: list[dict[str, Any]],
    ) -> list[Any]:
        """Rebuild one class's derived grants without touching user choices.

        Advancement records written before the runtime registry existed can
        contain only the feature gained on the latest level.  Keeping those
        rows forever makes a level-6 character behave as if its level-1/2
        features were never granted.  Replacing only derived entries lets a
        preview repair that omission while preserving feats, feature choices,
        ability-score grants, DM notes and entries owned by another class.
        """

        derived_kinds = {
            "class_feature",
            "class_scaling",
            "subclass_feature",
            "proficiency_bonus",
        }
        preserved = [
            deepcopy(item)
            for item in existing
            if not (
                isinstance(item, dict)
                and str(item.get("class_name") or "") == class_name
                and str(item.get("kind") or "") in derived_kinds
            )
        ]
        return AdvancementService._merge_feature_grants(preserved, grants)

    @staticmethod
    def _replace_subclass_runtime_actions(
        existing: list[Any],
        *,
        class_name: str,
        additions: list[dict[str, Any]],
    ) -> list[Any]:
        """Replace derived actions for one subclass while retaining custom actions."""

        preserved = [
            deepcopy(item)
            for item in existing
            if not (
                isinstance(item, dict)
                and str(item.get("kind") or "") == "subclass_feature_action"
                and str(item.get("class_name") or "") == class_name
            )
        ]
        return AdvancementService._merge_runtime_actions(preserved, additions)

    def _validate_spell_choices(
        self,
        *,
        class_name: str,
        target_class_level: int,
        enabled_content_packs: object,
        allow_legacy: bool,
        existing_spells: list[dict[str, Any]],
        spell_additions: list[dict[str, Any]],
        spell_removals: set[str],
        after_spells: list[dict[str, Any]],
        target_cantrips: int | None,
        target_prepared: int | None,
        dm_override: bool,
        warnings: list[str],
    ) -> None:
        catalog = self._spell_catalog(
            enabled_content_packs=enabled_content_packs,
            allow_legacy=allow_legacy,
        )
        by_id = {
            str(item.get("source_record_id") or ""): item
            for item in catalog
            if item.get("source_record_id")
        }
        by_name = {str(item.get("name") or ""): item for item in catalog if item.get("name")}
        max_level = maximum_class_spell_level(class_name, target_class_level)
        invalid: list[str] = []
        for addition in spell_additions:
            record = by_id.get(str(addition.get("source_record_id") or "")) or by_name.get(
                str(addition.get("name") or "")
            )
            name = str(addition.get("name") or "(未命名法术)")
            if record is None:
                invalid.append(f"{name}不在本地2024法术目录")
                continue
            record_classes = {
                canonical_class_name(str(item)) for item in list(record.get("classes") or [])
            }
            spell_level = int(record.get("level") or 0)
            granted_spell_access = addition.get("granted_spell_access") is True
            if class_name not in record_classes and not granted_spell_access:
                invalid.append(f"{name}不属于{class_name}法术表")
            elif spell_level > max_level and not granted_spell_access:
                invalid.append(
                    f"{name}为{spell_level}环，{class_name}{target_class_level}级"
                    f"最高只能选择{max_level}环"
                )
            addition.update(
                {
                    **record,
                    **addition,
                    "name": record["name"],
                    "source_record_id": record["source_record_id"],
                    "spell_level": spell_level,
                    "classes": list(record.get("classes") or []),
                    "class_name": class_name,
                }
            )
        if invalid and not dm_override:
            raise ValueError("; ".join(invalid))
        if invalid:
            warnings.append("DM 已覆盖法术目录、职业或环级限制：" + "；".join(invalid))

        existing_names = {str(item.get("name") or "") for item in existing_spells}
        existing_ids = {
            str(item.get("source_record_id") or "")
            for item in existing_spells
            if item.get("source_record_id")
        }
        missing_removals = {
            item
            for item in spell_removals
            if item not in existing_names and item not in existing_ids
        }
        if missing_removals and not dm_override:
            raise ValueError(
                "cannot remove spells not known by the character: "
                + ", ".join(sorted(missing_removals))
            )
        if missing_removals:
            warnings.append("DM 已覆盖不存在的法术移除项。")

        seen: set[str] = set()
        for spell in after_spells:
            identity = str(spell.get("source_record_id") or spell.get("name") or "")
            if not identity:
                continue
            if identity in seen and not dm_override:
                raise ValueError("the resulting spell list contains duplicate spells")
            seen.add(identity)
            level = int(spell.get("spell_level", spell.get("level", 0)) or 0)
            if level == 0 and spell.get("prepared") is False and not dm_override:
                raise ValueError("cantrips are always available and cannot be unprepared")

        class_spells = [
            spell
            for spell in after_spells
            if canonical_class_name(str(spell.get("class_name") or class_name)) == class_name
            and spell.get("does_not_count_toward_level_learning") is not True
        ]
        cantrip_count = sum(
            int(spell.get("spell_level", spell.get("level", 0)) or 0) == 0 for spell in class_spells
        )
        prepared_count = sum(
            int(spell.get("spell_level", spell.get("level", 0)) or 0) > 0
            and spell.get("prepared") is True
            and spell.get("always_prepared") is not True
            for spell in class_spells
        )
        if target_cantrips is not None and cantrip_count != target_cantrips:
            message = (
                f"{class_name}{target_class_level}级必须有{target_cantrips}个戏法，"
                f"当前结果为{cantrip_count}个"
            )
            if not dm_override:
                raise ValueError(message)
            warnings.append("DM 已覆盖：" + message)
        if target_prepared is not None and prepared_count != target_prepared:
            message = (
                f"{class_name}{target_class_level}级必须准备{target_prepared}个有环法术，"
                f"当前结果为{prepared_count}个"
            )
            if not dm_override:
                raise ValueError(message)
            warnings.append("DM 已覆盖：" + message)

        if class_name == "法师" and target_class_level > 1:
            learned = [
                spell
                for spell in spell_additions
                if int(spell.get("spell_level", spell.get("level", 0)) or 0) > 0
                and spell.get("does_not_count_toward_level_learning") is not True
                and str(spell.get("name") or "") not in existing_names
                and str(spell.get("source_record_id") or "") not in existing_ids
            ]
            if len(learned) != 2:
                message = f"法师本级必须向法术书加入2个新法师法术，当前提交{len(learned)}个"
                if not dm_override:
                    raise ValueError(message)
                warnings.append("DM 已覆盖：" + message)

        if class_name in {"吟游诗人", "游侠", "术士", "魔契师"}:
            removed_leveled = [
                spell
                for spell in existing_spells
                if (
                    str(spell.get("name") or "") in spell_removals
                    or str(spell.get("source_record_id") or "") in spell_removals
                )
                and canonical_class_name(str(spell.get("class_name") or class_name)) == class_name
                and int(spell.get("spell_level", spell.get("level", 0)) or 0) > 0
            ]
            if len(removed_leveled) > 1:
                message = f"{class_name}每次获得职业等级至多替换1个有环法术"
                if not dm_override:
                    raise ValueError(message)
                warnings.append("DM 已覆盖：" + message)

    def _preview_in_session(
        self,
        session: Session,
        campaign_id: str,
        character_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        character = self._character(session, campaign_id, character_id)
        return self._preview_for_character(session, campaign_id, character, data)

    def _preview_for_character(
        self,
        session: Session,
        campaign_id: str,
        character: Any,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        expected = int(data["character_version"])
        if character.version != expected:
            raise VersionConflict("character", character.id, expected, character.version)
        if character.level >= 20:
            raise ValueError("character is already level 20")
        override = str(data.get("dm_override_reason") or "").strip()
        required_xp = XP_THRESHOLDS[character.level]
        warnings: list[str] = []
        if character.experience < required_xp:
            if not override:
                raise ValueError(
                    f"character needs {required_xp} XP to reach level {character.level + 1}"
                )
            warnings.append("DM 已覆盖经验门槛。")
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        enabled_extensions = {str(value) for value in (campaign.enabled_rule_extensions or [])}
        enabled_content_packs = tuple(
            str(value) for value in (campaign.enabled_content_packs or [])
        )
        allow_legacy = bool(campaign.allow_legacy)
        requested_class_name = str(data["class_name"])
        rule = self._class_rule(
            requested_class_name,
            enabled_content_packs=enabled_content_packs,
            allow_legacy=allow_legacy,
        )
        class_name = str(rule.name)
        class_levels = dict(character.class_levels or {})
        if not class_levels and character.class_name:
            class_levels[str(character.class_name)] = character.level
        current_class_level = int(class_levels.get(class_name, 0))
        is_multiclass = bool(class_levels) and class_name not in class_levels
        if is_multiclass:
            if "multiclassing" not in enabled_extensions and not override:
                raise ValueError("本战役未启用兼职规则，不能新增多职业")
            if "multiclassing" not in enabled_extensions:
                warnings.append("DM 已覆盖战役未启用兼职规则的限制。")
            failures = validate_multiclass_prerequisites(
                class_name, dict(character.ability_scores or {})
            )
            if failures and not override:
                raise ValueError("multiclass prerequisites not met: " + ", ".join(failures))
            if failures:
                warnings.append("DM 已覆盖多职业属性前置条件。")
        target_class_level = current_class_level + 1
        level_rule = rule.levels[target_class_level - 1]
        requirements = advancement_choice_requirements(rule, target_class_level)
        subclass_choices = dict(character.subclass_choices or {})
        subclass_name = str(
            data.get("subclass_name") or subclass_choices.get(class_name) or ""
        ).strip()
        needs_subclass = any(
            "子职" in feature or "子职业" in feature for feature in level_rule.features
        )
        available_subclasses = {str(item.get("name") or ""): dict(item) for item in rule.subclasses}
        if needs_subclass and not subclass_name:
            if not override:
                raise ValueError("this level requires a subclass choice")
            warnings.append("DM 已覆盖本级子职选择要求。")
        if subclass_name and subclass_name not in available_subclasses:
            if not override:
                raise ValueError("selected subclass is not available for this class")
            warnings.append("DM 已覆盖本地子职目录限制。")
        previous_subclass_name = str(subclass_choices.get(class_name) or "").strip()
        if previous_subclass_name and subclass_name and previous_subclass_name != subclass_name:
            if not override:
                raise ValueError("cannot change an existing subclass without a DM override")
            warnings.append("DM 已覆盖既有子职不可更换限制。")
        selected_subclass = available_subclasses.get(subclass_name)
        if selected_subclass is not None and not selected_subclass.get(
            "selectable_for_automatic_advancement", True
        ):
            if not override:
                raise ValueError(
                    "selected subclass lacks a structured automatic-advancement source; "
                    "provide a DM override to record it manually"
                )
            warnings.append("DM 已覆盖未结构化子职的自动升级限制。")

        constitution = int((character.ability_scores or {}).get("constitution", 10))
        con_modifier = (constitution - 10) // 2
        hp_mode = str(data.get("hp_mode") or "fixed")
        if hp_mode == "fixed":
            hp_gain = average_hp_gain(rule.hit_die, con_modifier)
        elif hp_mode == "roll":
            hp_roll = int(data.get("hp_roll") or 0)
            if not 1 <= hp_roll <= rule.hit_die:
                raise ValueError(f"HP roll must be between 1 and {rule.hit_die}")
            hp_gain = max(1, hp_roll + con_modifier)
        else:
            raise ValueError("hp_mode must be fixed or roll")

        ability_scores = dict(character.ability_scores or {})
        target_core_grants = list(
            core_feature_grants(
                rule,
                target_class_level,
                ability_scores=ability_scores,
            )
        )
        existing_ability_caps = self._ability_score_caps(
            [item for item in character.features or () if isinstance(item, dict)]
        )
        target_ability_caps = self._ability_score_caps(target_core_grants)
        ability_caps = {
            ability: max(existing_ability_caps.get(ability, 20), cap)
            for ability, cap in {**existing_ability_caps, **target_ability_caps}.items()
        }
        ability_increases = {
            str(key): int(value)
            for key, value in dict(data.get("ability_increases") or {}).items()
            if int(value)
        }
        grants_asi = any("属性值提升" in feature for feature in level_rule.features)
        grants_epic_boon = any(
            "传奇恩惠" in feature or "史诗恩惠" in feature for feature in level_rule.features
        )
        feat_choice = str(data.get("feat_choice") or "").strip()
        if (grants_asi or grants_epic_boon) and not ability_increases and not feat_choice:
            raise ValueError("this level requires ability score increases or one feat choice")
        if ability_increases or feat_choice:
            if not grants_asi and not grants_epic_boon:
                raise ValueError("this level does not grant an ability score improvement")
            if grants_epic_boon and ability_increases:
                raise ValueError("an epic boon level requires a feat choice")
            if ability_increases and feat_choice:
                raise ValueError("choose ability increases or one feat, not both")
            if ability_increases:
                if sum(ability_increases.values()) > 2 or any(
                    value not in {1, 2} for value in ability_increases.values()
                ):
                    raise ValueError("ability score increases may total at most 2")
                if sum(ability_increases.values()) != 2:
                    if not override:
                        raise ValueError("ability score increases must total exactly 2")
                    warnings.append("DM 已覆盖属性值提升必须合计 +2 的限制。")
                for ability, increase in ability_increases.items():
                    if ability not in ability_scores:
                        raise ValueError(f"unknown ability score: {ability}")
                    maximum = ability_caps.get(ability, 20)
                    if ability_scores[ability] + increase > maximum and not override:
                        raise ValueError(
                            f"ability score cannot exceed {maximum} without a DM override"
                        )
                    ability_scores[ability] += increase

        ability_scores, fixed_ability_adjustments = self._apply_fixed_ability_score_adjustments(
            target_core_grants,
            ability_scores=ability_scores,
        )

        feat_grant: dict[str, Any] | None = None
        if feat_choice:
            feat_rule = find_feat_rule(
                self._feat_rules(
                    enabled_content_packs=enabled_content_packs,
                    allow_legacy=allow_legacy,
                ),
                feat_choice,
            )
            feat_failures: list[str] = []
            if feat_rule is None:
                feat_failures.append("所选专长不在本地2024核心专长目录")
            else:
                feat_failures.extend(
                    validate_feat_prerequisites(
                        feat_rule,
                        expected_category="传奇恩惠" if grants_epic_boon else "通用",
                        total_level=character.level + 1,
                        ability_scores=ability_scores,
                        class_levels={**class_levels, class_name: target_class_level},
                        proficiencies=list(character.proficiencies or []),
                        features=list(character.features or []),
                    )
                )
                feat_grant = {
                    "name": feat_rule.name,
                    "kind": "feat",
                    "level": character.level + 1,
                    "class_name": class_name,
                    "class_level": target_class_level,
                    "category": feat_rule.category,
                    "source_record_id": feat_rule.source_record_id,
                    "source_path": feat_rule.source_path,
                    "rule_year": feat_rule.rule_year,
                    "content_pack_key": feat_rule.content_pack_key,
                    "runtime": {
                        "automation_status": "dm_only",
                        "requires_dm_adjudication": True,
                        "execution": {
                            "kind": "sheet_feat_grant",
                            "grant_status": "full",
                            "effect_status": "dm_only",
                        },
                        "note": "专长授予和前置条件已执行；专长具体效果保留给 DM 裁定。",
                    },
                }
            if feat_failures and not override:
                raise ValueError("专长前置条件不满足：" + "；".join(feat_failures))
            if feat_failures:
                warnings.append("DM 已覆盖专长限制：" + "；".join(feat_failures))
            if feat_grant is None:
                feat_grant = {
                    "name": feat_choice,
                    "kind": "feat",
                    "level": character.level + 1,
                    "class_name": class_name,
                    "class_level": target_class_level,
                    "rule_year": rule.rule_year,
                    "dm_override": True,
                    "runtime": {
                        "automation_status": "dm_only",
                        "requires_dm_adjudication": True,
                        "execution": {
                            "kind": "sheet_feat_grant",
                            "grant_status": "full",
                            "effect_status": "dm_only",
                        },
                        "note": "这是 DM 覆盖的专长授予记录；效果需由 DM 裁定。",
                    },
                }

        old_con_modifier = con_modifier
        new_constitution = int(ability_scores.get("constitution", constitution))
        new_con_modifier = (new_constitution - 10) // 2
        constitution_hp_adjustment = (new_con_modifier - old_con_modifier) * (character.level + 1)
        hp_gain += constitution_hp_adjustment

        spell_additions = [dict(item) for item in data.get("spell_additions", [])]
        spell_removals = {str(item) for item in data.get("spell_removals", [])}
        raw_core_spell_choices = data.get("feature_choices_by_key") or {}
        if not isinstance(raw_core_spell_choices, dict):
            raise ValueError("feature_choices_by_key must be an object")
        selected_core_spell_choices = {
            str(key): [str(choice).strip() for choice in values if str(choice).strip()]
            for key, values in raw_core_spell_choices.items()
            if isinstance(values, list)
        }
        if len(selected_core_spell_choices) != len(raw_core_spell_choices):
            raise ValueError("each feature choice must be a list of text choices")
        raw_subclass_spell_choices = data.get("subclass_feature_choices") or {}
        if not isinstance(raw_subclass_spell_choices, dict):
            raise ValueError("subclass_feature_choices must be an object keyed by feature id")
        selected_subclass_spell_choices = {
            str(feature_id): [str(choice).strip() for choice in choices if str(choice).strip()]
            for feature_id, choices in raw_subclass_spell_choices.items()
            if isinstance(choices, list)
        }
        if len(selected_subclass_spell_choices) != len(raw_subclass_spell_choices):
            raise ValueError("each subclass feature choice must be a list of text choices")
        for existing in character.features or []:
            if not isinstance(existing, dict):
                continue
            if (
                str(existing.get("kind") or "") != "subclass_feature"
                or str(existing.get("class_name") or "") != class_name
            ):
                continue
            feature_id = str(existing.get("feature_id") or "").strip()
            choices = existing.get("selected_choices")
            if (
                feature_id
                and feature_id not in selected_subclass_spell_choices
                and isinstance(choices, list)
            ):
                selected_subclass_spell_choices[feature_id] = [
                    str(choice).strip() for choice in choices if str(choice).strip()
                ]
        spell_catalog = (
            self._spell_catalog(
                enabled_content_packs=enabled_content_packs,
                allow_legacy=allow_legacy,
            )
            if spell_additions or selected_subclass is not None
            else ()
        )
        automatic_subclass_spells = _fixed_subclass_spell_additions(
            selected_subclass,
            class_name=class_name,
            target_class_level=target_class_level,
            spell_catalog=spell_catalog,
        )
        selected_subclass_grants: list[dict[str, Any]] = []
        if selected_subclass is not None:
            for subclass_level in range(1, target_class_level + 1):
                selected_subclass_grants.extend(
                    subclass_runtime_grants(
                        selected_subclass,
                        class_name=class_name,
                        target_class_level=subclass_level,
                        ability_scores=ability_scores,
                        selected_choices=selected_subclass_spell_choices,
                        current_class_level=target_class_level,
                    )["grants"]
                )
        try:
            automatic_subclass_spells.extend(
                _selected_subclass_spell_additions(
                    selected_subclass_grants,
                    selected_choices=selected_subclass_spell_choices,
                    spell_catalog=spell_catalog,
                    owner_class=class_name,
                    owner_level=target_class_level,
                )
            )
        except ValueError as exc:
            # A matrix/DM override may intentionally omit a newly structured
            # subclass choice while testing a different advancement boundary.
            # Normal requests remain strict; an explicit override preserves
            # the former permissive path without inventing any spell rows.
            if not override:
                raise
            warnings.append(f"DM 已覆盖受控子职法术选择：{exc}")
        automatic_subclass_spells.extend(
            _fixed_subclass_feature_spell_additions(
                selected_subclass_grants,
                spell_catalog=spell_catalog,
                owner_class=class_name,
            )
        )
        automatic_subclass_spells.extend(
            _selected_core_spell_additions(
                selected_core_spell_choices,
                spell_catalog=spell_catalog,
                owner_class=class_name,
            )
        )
        existing_addition_ids = {
            str(item.get("source_record_id") or item.get("name") or "") for item in spell_additions
        }
        for automatic in automatic_subclass_spells:
            identity = str(automatic.get("source_record_id") or automatic.get("name") or "")
            if identity and identity not in existing_addition_ids:
                spell_additions.append(automatic)
                existing_addition_ids.add(identity)
        spell_by_id = {
            str(item.get("source_record_id") or ""): item
            for item in spell_catalog
            if item.get("source_record_id")
        }
        spell_by_name = {
            str(item.get("name") or ""): item for item in spell_catalog if item.get("name")
        }
        for spell in spell_additions:
            canonical = spell_by_id.get(
                str(spell.get("source_record_id") or "")
            ) or spell_by_name.get(str(spell.get("name") or ""))
            if canonical is not None:
                submitted = dict(spell)
                spell.clear()
                spell.update(
                    {
                        **canonical,
                        **submitted,
                        "name": canonical["name"],
                        "source_record_id": canonical["source_record_id"],
                        "spell_level": int(canonical.get("level") or 0),
                        "classes": list(canonical.get("classes") or []),
                        "class_name": class_name,
                    }
                )
        existing_spells = [
            dict(item) if isinstance(item, dict) else {"name": str(item)}
            for item in (character.spells or [])
        ]
        existing_classes = {
            canonical_class_name(str(name)) for name in class_levels if int(class_levels[name])
        }
        for spell in existing_spells:
            if spell.get("class_name"):
                spell["class_name"] = canonical_class_name(str(spell["class_name"]))
                continue
            candidates = {
                canonical_class_name(str(name)) for name in list(spell.get("classes") or [])
            } & existing_classes
            if len(candidates) == 1:
                spell["class_name"] = next(iter(candidates))
            elif len(existing_classes) == 1:
                spell["class_name"] = next(iter(existing_classes))
        after_spells = [
            item
            for item in existing_spells
            if str(item.get("name")) not in spell_removals
            and str(item.get("source_record_id") or "") not in spell_removals
        ]
        existing_by_identity: dict[str, dict[str, Any]] = {}
        for item in after_spells:
            for identity in (
                str(item.get("source_record_id") or ""),
                str(item.get("name") or ""),
            ):
                if identity:
                    existing_by_identity[identity] = item
        for spell in spell_additions:
            name = str(spell.get("name") or "").strip()
            source_id = str(spell.get("source_record_id") or "").strip()
            existing = existing_by_identity.get(source_id) or existing_by_identity.get(name)
            if existing is not None:
                existing.update(spell)
                continue
            if name:
                after_spells.append(spell)
                existing_by_identity[name] = spell
                if source_id:
                    existing_by_identity[source_id] = spell

        target_cantrips = next(
            (item.target_total for item in requirements if item.key == "cantrips"),
            None,
        )
        target_prepared = next(
            (item.target_total for item in requirements if item.key == "prepared_spells"),
            None,
        )
        self._validate_spell_choices(
            class_name=class_name,
            target_class_level=target_class_level,
            enabled_content_packs=enabled_content_packs,
            allow_legacy=allow_legacy,
            existing_spells=existing_spells,
            spell_additions=spell_additions,
            spell_removals=spell_removals,
            after_spells=after_spells,
            target_cantrips=target_cantrips,
            target_prepared=target_prepared,
            dm_override=bool(override),
            warnings=warnings,
        )

        feature_requirements = [item for item in requirements if item.kind == "feature_option"]
        try:
            requested_feature_choices_by_key, used_legacy_choice_adapter = (
                assign_progression_choices(
                    requirements,
                    choices_by_key=data.get("feature_choices_by_key") or {},
                    legacy_choices=data.get("feature_choices") or (),
                )
            )
        except ValueError:
            if not override:
                raise
            requested_feature_choices_by_key = {
                str(key): [str(item).strip() for item in values if str(item).strip()]
                for key, values in dict(data.get("feature_choices_by_key") or {}).items()
            }
            legacy_override_choices = [
                str(item).strip() for item in data.get("feature_choices") or () if str(item).strip()
            ]
            if legacy_override_choices and not requested_feature_choices_by_key:
                cursor = 0
                for requirement in feature_requirements:
                    end = cursor + int(requirement.maximum)
                    selected = legacy_override_choices[cursor:end]
                    if selected:
                        requested_feature_choices_by_key[str(requirement.key)] = selected
                    cursor = end
                if cursor < len(legacy_override_choices):
                    requested_feature_choices_by_key["dm_override"] = legacy_override_choices[
                        cursor:
                    ]
            used_legacy_choice_adapter = bool(data.get("feature_choices"))
            warnings.append("DM 已覆盖职业选项的结构化数量或分类限制。")
        if used_legacy_choice_adapter:
            warnings.append(
                "feature_choices 旧扁平数组已由兼容适配器按 requirement 顺序分配；"
                "新请求应使用 feature_choices_by_key。"
            )
        unresolved_feature_requirements = [item for item in feature_requirements if not item.strict]
        if unresolved_feature_requirements:
            warnings.append(
                "以下职业选项的数量来自2024成长表，但具体选项前置条件仍需"
                "本地规则条目或DM复核："
                + "、".join(item.key for item in unresolved_feature_requirements)
            )

        progression_choice_result = apply_progression_choice_grants(
            choices_by_key=requested_feature_choices_by_key,
            skills=dict(character.skills or {}),
            proficiencies=list(character.proficiencies or []),
            class_name=class_name,
            class_level=target_class_level,
            total_level=character.level + 1,
            source_record_id=rule.source_record_id,
            rule_year=rule.rule_year,
        )

        class_levels[class_name] = target_class_level
        if subclass_name:
            subclass_choices[class_name] = subclass_name
        raw_subclass_choices = data.get("subclass_feature_choices") or {}
        if not isinstance(raw_subclass_choices, dict):
            raise ValueError("subclass_feature_choices must be an object keyed by feature id")
        selected_subclass_choices = {
            str(feature_id): [str(choice).strip() for choice in choices if str(choice).strip()]
            for feature_id, choices in raw_subclass_choices.items()
            if isinstance(choices, list)
        }
        if len(selected_subclass_choices) != len(raw_subclass_choices):
            raise ValueError("each subclass feature choice must be a list of text choices")
        # Recover choices stored by earlier advancement records before merging
        # the current request.  This keeps a later level-up from forgetting a
        # branch selected when the subclass was first granted.
        for existing in character.features or []:
            if not isinstance(existing, dict):
                continue
            if (
                str(existing.get("kind") or "") != "subclass_feature"
                or str(existing.get("class_name") or "") != class_name
            ):
                continue
            feature_id = str(existing.get("feature_id") or "").strip()
            choices = existing.get("selected_choices")
            if (
                feature_id
                and feature_id not in selected_subclass_choices
                and isinstance(choices, list)
            ):
                selected_subclass_choices[feature_id] = [
                    str(choice).strip() for choice in choices if str(choice).strip()
                ]
        subclass_runtime = {
            "grants": [],
            "resources": {},
            "actions": [],
            "prepared_spell_features": [],
            "choice_requirements": [],
        }
        if selected_subclass is not None:
            for subclass_level in range(1, target_class_level + 1):
                level_runtime = subclass_runtime_grants(
                    selected_subclass,
                    class_name=class_name,
                    target_class_level=subclass_level,
                    ability_scores=ability_scores,
                    selected_choices=selected_subclass_choices,
                    current_class_level=target_class_level,
                )
                subclass_runtime["grants"].extend(level_runtime["grants"])
                subclass_runtime["actions"].extend(level_runtime["actions"])
                subclass_runtime["prepared_spell_features"].extend(
                    level_runtime.get("prepared_spell_features", [])
                )
                subclass_runtime["choice_requirements"].extend(level_runtime["choice_requirements"])
                subclass_runtime["resources"].update(level_runtime["resources"])
        # Some subclass features change hit-point maximum retroactively and
        # continue scaling with that class.  Apply only the typed advancement
        # contract emitted by the runtime registry, using the delta from the
        # character's previous class level so repeated previews stay idempotent.
        previous_class_level = int((character.class_levels or {}).get(class_name, 0))
        for grant in subclass_runtime["grants"]:
            runtime = grant.get("runtime") if isinstance(grant, dict) else None
            registry = runtime.get("registry") if isinstance(runtime, dict) else None
            advancement = registry.get("advancement") if isinstance(registry, dict) else None
            if not isinstance(advancement, dict) or advancement.get("kind") != (
                "hit_points_by_class_level"
            ):
                continue
            minimum_level = advancement.get("minimum_class_level")
            initial_bonus = advancement.get("initial_bonus")
            per_level_bonus = advancement.get("per_level_bonus")
            if not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in (minimum_level, initial_bonus, per_level_bonus)
            ) or minimum_level < 1 or initial_bonus < 0 or per_level_bonus < 0:
                raise ValueError("生命值成长合同包含非法数值")

            current_bonus = (
                0
                if target_class_level < minimum_level
                else initial_bonus + (target_class_level - minimum_level) * per_level_bonus
            )
            previous_bonus = (
                0
                if previous_class_level < minimum_level
                else initial_bonus + (previous_class_level - minimum_level) * per_level_bonus
            )
            hp_gain += max(0, current_bonus - previous_bonus)
        known_subclass_choice_ids = {
            str(item.get("feature_id") or "") for item in subclass_runtime["choice_requirements"]
        }
        unknown_subclass_choices = sorted(
            set(selected_subclass_choices) - known_subclass_choice_ids
        )
        if unknown_subclass_choices and not override:
            raise ValueError(
                "submitted subclass feature choices are not granted at this level: "
                + ", ".join(unknown_subclass_choices)
            )
        if unknown_subclass_choices:
            warnings.append("DM 已覆盖不在本级的子职特性选择。")
        for requirement in subclass_runtime["choice_requirements"]:
            feature_id = str(requirement["feature_id"])
            selected = selected_subclass_choices.get(feature_id, [])
            minimum = int(requirement["minimum"])
            maximum = int(requirement["maximum"])
            if not minimum <= len(selected) <= maximum:
                message = (
                    f"子职特性{feature_id}必须选择 {minimum} 至 {maximum} 项，"
                    f"当前为 {len(selected)} 项"
                )
                if not override:
                    raise ValueError(message)
                warnings.append("DM 已覆盖：" + message)

        subclass_skills = self._apply_subclass_proficiency_choices(
            list(subclass_runtime["grants"]),
            selected_choices=selected_subclass_choices,
            skills=dict(progression_choice_result["skills"]),
            allow_missing=bool(override),
        )

        # Fixed typed subclass grants (for example tool proficiencies) are
        # applied to the same authoritative sheet list as class choices.
        # Choice-bound grants remain unresolved until the existing explicit
        # subclass choice request is supplied.
        subclass_proficiencies = list(progression_choice_result["proficiencies"])
        for grant in subclass_runtime["grants"]:
            runtime = grant.get("runtime") if isinstance(grant, dict) else None
            registry = runtime.get("registry") if isinstance(runtime, dict) else None
            entries = registry.get("proficiencies") if isinstance(registry, dict) else None
            for entry in entries if isinstance(entries, list) else ():
                if not isinstance(entry, dict) or entry.get("operation") != "grant":
                    continue
                name = str(entry.get("name") or "").strip()
                if name and name not in subclass_proficiencies:
                    subclass_proficiencies.append(name)
        subclass_skills, subclass_proficiencies = self._apply_subclass_typed_proficiency_choices(
            list(subclass_runtime["grants"]),
            selected_choices=selected_subclass_choices,
            skills=subclass_skills,
            proficiencies=subclass_proficiencies,
        )
        scaling_updates = progression_scaling_updates(rule, target_class_level)
        new_features = list(target_core_grants)
        scaling_features = [
            {
                "name": str(update["label"]),
                "kind": "class_scaling",
                "class_name": class_name,
                "class_level": target_class_level,
                "scaling_key": key,
                "value": update["value"],
                "value_kind": update["value_kind"],
                "source_record_id": rule.source_record_id,
                "source_path": rule.source_path,
                "rule_year": rule.rule_year,
                "runtime": {
                    "automation_status": "partial",
                    "requires_dm_adjudication": True,
                    "note": "成长表数值已写入车卡；其对具体检定或伤害的影响由 DM 裁定。",
                },
            }
            for key, update in scaling_updates.items()
        ]
        # Materialize the complete class progression in the character
        # snapshot.  A character imported at level 5, or one upgraded from a
        # legacy snapshot that stored only the latest grant, must still expose
        # every level-1..5 runtime contract to combat hydration.
        all_core_features = [
            grant
            for class_level in range(1, target_class_level + 1)
            for grant in core_feature_grants(
                rule,
                class_level,
                ability_scores=ability_scores,
            )
        ]
        all_scaling_features = [
            {
                "name": str(update["label"]),
                "kind": "class_scaling",
                "class_name": class_name,
                "class_level": class_level,
                "scaling_key": key,
                "value": update["value"],
                "value_kind": update["value_kind"],
                "source_record_id": rule.source_record_id,
                "source_path": rule.source_path,
                "rule_year": rule.rule_year,
                "runtime": {
                    "automation_status": "partial",
                    "requires_dm_adjudication": True,
                    "note": "成长表数值已写入车卡；其对具体检定或伤害的影响由 DM 裁定。",
                },
            }
            for class_level in range(1, target_class_level + 1)
            for key, update in progression_scaling_updates(rule, class_level).items()
        ]
        ability_score_grant = (
            {
                "name": "属性值提升",
                "kind": "ability_score_increase",
                "class_name": class_name,
                "class_level": target_class_level,
                "level": character.level + 1,
                "ability_increases": dict(ability_increases),
                "source_record_id": rule.source_record_id,
                "source_path": rule.source_path,
                "rule_year": rule.rule_year,
                "runtime": {
                    "automation_status": "full",
                    "requires_dm_adjudication": False,
                    "execution": {
                        "kind": "sheet_ability_score_increase",
                        "delta": dict(ability_increases),
                    },
                    "note": "已在升级事务中原子写入所选属性值提升。",
                },
            }
            if ability_increases
            else None
        )
        chosen_features = list(progression_choice_result["grants"])
        proficiency_bonus_grant = {
            "name": "熟练加值",
            "kind": "proficiency_bonus",
            "class_name": class_name,
            "class_level": target_class_level,
            "level": character.level + 1,
            "value": proficiency_bonus_for_level(character.level + 1),
            "value_kind": "proficiency_bonus",
            "source_record_id": rule.source_record_id,
            "source_path": rule.source_path,
            "rule_year": rule.rule_year,
            "runtime": {
                "automation_status": "full",
                "requires_dm_adjudication": False,
                "execution": {
                    "kind": "sheet_proficiency_bonus",
                    "value": proficiency_bonus_for_level(character.level + 1),
                },
                "note": "熟练加值由总角色等级确定，并可由运行时 registry 直接读取。",
            },
        }
        grants_to_persist = [
            *all_core_features,
            *all_scaling_features,
            *([ability_score_grant] if ability_score_grant is not None else []),
            proficiency_bonus_grant,
            *list(subclass_runtime["grants"]),
            *chosen_features,
        ]
        if feat_grant:
            grants_to_persist.append(dict(feat_grant))
        after_features = self._replace_class_progression_grants(
            list(character.features or []),
            class_name=class_name,
            grants=grants_to_persist,
        )
        all_core_actions = [
            action
            for class_level in range(1, target_class_level + 1)
            for action in core_runtime_actions(rule, class_level)
        ]
        after_actions = self._replace_subclass_runtime_actions(
            list(character.actions or []),
            class_name=class_name,
            additions=list(subclass_runtime["actions"]),
        )
        after_actions = self._merge_runtime_actions(
            after_actions,
            all_core_actions,
        )
        after_resources, all_resource_updates = self._rebuild_multiclass_progression_resources(
            class_levels=class_levels,
            subclass_choices=subclass_choices,
            ability_scores=ability_scores,
            enabled_content_packs=enabled_content_packs,
            allow_legacy=allow_legacy,
            existing_resources=dict(character.resources or {}),
        )
        runtime_scalings = {
            str(item.get("scaling_key")): {"value": item.get("value")}
            for item in after_features
            if isinstance(item, dict)
            and item.get("kind") == "class_scaling"
            and isinstance(item.get("scaling_key"), str)
        }
        runtime_registry = compile_feature_runtime_registry(
            [item for item in after_features if isinstance(item, dict)],
            resources=after_resources,
            scalings=runtime_scalings,
            actions=after_actions,
            class_levels=class_levels,
            total_level=character.level + 1,
        )
        result = {
            "character_id": character.id,
            "character_name": character.name,
            "from_level": character.level,
            "to_level": character.level + 1,
            "class_name": class_name,
            "class_level": target_class_level,
            "subclass_name": subclass_name or None,
            "hit_die": rule.hit_die,
            "hp_mode": hp_mode,
            "hp_gain": hp_gain,
            "constitution_hp_adjustment": constitution_hp_adjustment,
            "before": {
                "hp": character.hp,
                "max_hp": character.max_hp,
                "ability_scores": dict(character.ability_scores or {}),
                "class_levels": dict(character.class_levels or {}),
                "subclass_choices": dict(character.subclass_choices or {}),
                "spells": list(character.spells or []),
                "resources": dict(character.resources or {}),
                "features": list(character.features or []),
                "actions": list(character.actions or []),
                "proficiencies": list(character.proficiencies or []),
                "skills": dict(character.skills or {}),
            },
            "after": {
                "hp": character.hp + hp_gain,
                "max_hp": character.max_hp + hp_gain,
                "ability_scores": ability_scores,
                "class_levels": class_levels,
                "subclass_choices": subclass_choices,
                "spells": after_spells,
                "resources": after_resources,
                "features": after_features,
                "actions": after_actions,
                "proficiencies": subclass_proficiencies,
                "skills": subclass_skills,
                "fixed_ability_adjustments": fixed_ability_adjustments,
                "feature_runtime": runtime_registry,
            },
            "features_gained": [
                *new_features,
                *scaling_features,
                *([ability_score_grant] if ability_score_grant is not None else []),
                proficiency_bonus_grant,
                *list(subclass_runtime["grants"]),
                *chosen_features,
            ],
            "feat_choice": feat_choice or None,
            "feat_grant": feat_grant,
            "choice_requirements": [
                *[item.as_dict() for item in requirements],
                *list(subclass_runtime["choice_requirements"]),
            ],
            "resource_updates": all_resource_updates,
            "scaling_updates": scaling_updates,
            "runtime_registry": runtime_registry,
            "progression_choices": requested_feature_choices_by_key,
            "warnings": warnings,
            "rule_reference": {
                "year": rule.rule_year,
                "source_record_id": rule.source_record_id,
                "source_path": rule.source_path,
                "content_pack_key": rule.content_pack_key,
            },
        }
        token_payload = {
            "request": data,
            "character_version": character.version,
            "character_level": character.level,
            "character_xp": character.experience,
            "result": result,
        }
        result["preview_token"] = hashlib.sha256(
            json.dumps(
                token_payload,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        return result

    def preview(
        self,
        campaign_id: str,
        character_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._preview_in_session(session, campaign_id, character_id, data)

    def _preview_batch_in_session(
        self,
        session: Session,
        campaign_id: str,
        character_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        character = self._character(session, campaign_id, character_id)
        expected = int(data["character_version"])
        if character.version != expected:
            raise VersionConflict("character", character.id, expected, character.version)
        raw_steps = data.get("steps")
        if not isinstance(raw_steps, list) or not 2 <= len(raw_steps) <= 19:
            raise ValueError("batch advancement requires 2 to 19 ordered steps")

        working = self._state_from_character(character)
        steps: list[dict[str, Any]] = []
        resource_updates: dict[str, dict[str, Any]] = {}
        scaling_updates: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        features_gained: list[dict[str, Any]] = []
        for index, raw_step in enumerate(raw_steps, start=1):
            if not isinstance(raw_step, dict):
                raise ValueError(f"batch step {index} must be an object")
            step_data = {
                **dict(raw_step),
                "character_version": working.version,
            }
            step_preview = self._preview_for_character(
                session,
                campaign_id,
                working,
                step_data,
            )
            public_step = {
                key: deepcopy(value)
                for key, value in step_preview.items()
                if key != "preview_token"
            }
            public_step["batch_index"] = index
            steps.append(public_step)
            resource_updates.update(deepcopy(step_preview.get("resource_updates", {})))
            scaling_updates.update(deepcopy(step_preview.get("scaling_updates", {})))
            warnings.extend(str(item) for item in step_preview.get("warnings", []))
            features_gained.extend(deepcopy(step_preview.get("features_gained", [])))
            if step_preview.get("feat_grant"):
                features_gained.append(deepcopy(step_preview["feat_grant"]))
            self._apply_preview_to_state(working, step_preview)

        result = {
            "kind": "batch",
            "character_id": character.id,
            "character_name": character.name,
            "from_level": character.level,
            "to_level": working.level,
            "before": deepcopy(steps[0]["before"]),
            "after": deepcopy(steps[-1]["after"]),
            "steps": steps,
            "features_gained": features_gained,
            "resource_updates": resource_updates,
            "scaling_updates": scaling_updates,
            "warnings": list(dict.fromkeys(warnings)),
            "rule_reference": {
                "year": 2024,
                "source_path": "sequential core-class advancement",
            },
        }
        token_payload = {
            "request": data,
            "character_version": character.version,
            "character_level": character.level,
            "character_xp": character.experience,
            "result": result,
        }
        result["preview_token"] = hashlib.sha256(
            json.dumps(
                token_payload,
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        return result

    def preview_batch(
        self,
        campaign_id: str,
        character_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._preview_batch_in_session(
                session,
                campaign_id,
                character_id,
                data,
            )

    def confirm(
        self,
        campaign_id: str,
        character_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        preview_token = str(data.pop("preview_token"))
        idempotency_key = str(data.pop("idempotency_key"))
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(AdvancementRecord).where(
                    AdvancementRecord.campaign_id == campaign_id,
                    AdvancementRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.character_id != character_id:
                    raise ValueError("idempotency key was already used for a different character")
                return dict(existing.result_json or {})
            preview = self._preview_in_session(session, campaign_id, character_id, data)
            if preview["preview_token"] != preview_token:
                raise VersionConflict("advancement preview", character_id, 1, 2)
            character = self._character(session, campaign_id, character_id)
            now = datetime.now(UTC)
            operation = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="character_advancement",
                idempotency_key=f"advancement:{idempotency_key}",
                status="applied",
                before_snapshot=preview["before"],
                after_snapshot=preview["after"],
                reason="DM confirmed character advancement",
                source="dm",
                confirmed_at=now,
            )
            session.add(operation)
            session.flush()
            self._apply_preview_with_cas(
                session,
                campaign_id=campaign_id,
                character=character,
                preview=preview,
                expected_version=int(data["character_version"]),
                updated_at=now,
            )
            result = {
                **preview,
                "idempotent_replay": False,
                "operation_transaction_id": operation.id,
            }
            record = AdvancementRecord(
                campaign_id=campaign_id,
                character_id=character.id,
                operation_transaction_id=operation.id,
                class_name=str(preview["class_name"]),
                subclass_name=preview["subclass_name"],
                from_level=int(preview["from_level"]),
                to_level=int(preview["to_level"]),
                choices_json=data,
                result_json={},
                preview_token=preview_token,
                idempotency_key=idempotency_key,
                status="confirmed",
                confirmed_at=now,
            )
            session.add(record)
            session.flush()
            result["advancement_record_id"] = record.id
            record.result_json = dict(result)
            session.flush()
            return result

    def confirm_batch(
        self,
        campaign_id: str,
        character_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        payload = dict(data)
        preview_token = str(payload.pop("preview_token"))
        idempotency_key = str(payload.pop("idempotency_key"))
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
        record_key_prefix = f"advancement-batch:{digest}"
        first_record_key = f"{record_key_prefix}:1"
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(AdvancementRecord).where(
                    AdvancementRecord.campaign_id == campaign_id,
                    AdvancementRecord.idempotency_key == first_record_key,
                )
            )
            if existing is not None:
                if existing.character_id != character_id:
                    raise ValueError("idempotency key was already used for a different character")
                return dict(existing.result_json or {})

            preview = self._preview_batch_in_session(
                session,
                campaign_id,
                character_id,
                payload,
            )
            if preview["preview_token"] != preview_token:
                raise VersionConflict("advancement preview", character_id, 1, 2)
            character = self._character(session, campaign_id, character_id)
            now = datetime.now(UTC)
            operation = OperationTransaction(
                campaign_id=campaign_id,
                operation_type="character_advancement_batch",
                idempotency_key=record_key_prefix,
                status="applied",
                before_snapshot=preview["before"],
                after_snapshot=preview["after"],
                reason="DM confirmed sequential character advancement",
                source="dm",
                confirmed_at=now,
            )
            session.add(operation)
            session.flush()
            self._apply_preview_with_cas(
                session,
                campaign_id=campaign_id,
                character=character,
                preview=preview,
                expected_version=int(payload["character_version"]),
                updated_at=now,
            )

            records: list[AdvancementRecord] = []
            submitted_steps = list(payload["steps"])
            for index, step in enumerate(preview["steps"], start=1):
                record = AdvancementRecord(
                    campaign_id=campaign_id,
                    character_id=character.id,
                    operation_transaction_id=operation.id,
                    class_name=str(step["class_name"]),
                    subclass_name=step.get("subclass_name"),
                    from_level=int(step["from_level"]),
                    to_level=int(step["to_level"]),
                    choices_json=dict(submitted_steps[index - 1]),
                    result_json={},
                    preview_token=preview_token,
                    idempotency_key=f"{record_key_prefix}:{index}",
                    status="confirmed",
                    confirmed_at=now,
                )
                session.add(record)
                records.append(record)
            session.flush()
            result = {
                **preview,
                "idempotent_replay": False,
                "operation_transaction_id": operation.id,
                "advancement_record_ids": [record.id for record in records],
            }
            for index, record in enumerate(records, start=1):
                record.result_json = (
                    dict(result)
                    if index == 1
                    else {
                        "batch_operation_transaction_id": operation.id,
                        "batch_index": index,
                        "advancement_record_id": record.id,
                    }
                )
            session.flush()
            return result

    def list_history(self, campaign_id: str, character_id: str) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            self._character(session, campaign_id, character_id)
            rows = session.scalars(
                select(AdvancementRecord)
                .where(AdvancementRecord.character_id == character_id)
                .order_by(AdvancementRecord.to_level, AdvancementRecord.created_at)
            ).all()
            return tuple(serialize(row) for row in rows)

    def list_companions(
        self, campaign_id: str, owner_character_id: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            query = select(CharacterCompanion).where(CharacterCompanion.campaign_id == campaign_id)
            if owner_character_id:
                self._character(session, campaign_id, owner_character_id)
                query = query.where(CharacterCompanion.owner_character_id == owner_character_id)
            rows = session.scalars(query.order_by(CharacterCompanion.created_at)).all()
            return tuple(serialize(row) for row in rows)

    def create_companion(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            campaign = session.get(Campaign, campaign_id)
            if campaign is None:
                raise StateNotFoundError("campaign not found")
            self._character(session, campaign_id, str(data["owner_character_id"]))
            companion = CharacterCompanion(campaign_id=campaign_id, **data)
            session.add(companion)
            session.flush()
            return serialize(companion)

    def update_companion(
        self,
        campaign_id: str,
        companion_id: str,
        data: dict[str, Any],
        expected_version: int,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            companion = session.get(CharacterCompanion, companion_id)
            if companion is None or companion.campaign_id != campaign_id:
                raise StateNotFoundError("companion not found in campaign")
            if companion.version != expected_version:
                raise VersionConflict(
                    "companion",
                    companion.id,
                    expected_version,
                    companion.version,
                )
            for key, value in data.items():
                setattr(companion, key, value)
            companion.version += 1
            companion.updated_at = datetime.now(UTC)
            session.flush()
            return serialize(companion)
