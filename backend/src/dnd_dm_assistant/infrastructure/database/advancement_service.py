from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.character_catalog import CharacterCatalog
from dnd_dm_assistant.domain.advancement import (
    average_hp_gain,
    merge_spell_slot_resources,
    validate_multiclass_prerequisites,
)
from dnd_dm_assistant.domain.advancement_choices import (
    advancement_choice_requirements,
    canonical_class_name,
    maximum_class_spell_level,
    progression_resource_updates,
)
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
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

    def _class_rule(self, class_name: str) -> Any:
        class_name = canonical_class_name(class_name)
        rule = next(
            (item for item in self.catalog.classes() if item.name == class_name),
            None,
        )
        if rule is None:
            raise ValueError("selected 2024 class is unavailable in the local rule catalog")
        return rule

    def _spell_catalog(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self.catalog.options().get("spells", []))

    @staticmethod
    def _merge_progression_resources(
        resources: dict[str, Any],
        updates: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        merged = dict(resources)
        for key, update in updates.items():
            old = merged.get(key)
            old_max = int(old.get("max", 0)) if isinstance(old, dict) else 0
            old_current = (
                int(old.get("current", old_max)) if isinstance(old, dict) else 0
            )
            new_max = int(update["max"])
            merged[key] = {
                **(old if isinstance(old, dict) else {}),
                **update,
                "current": min(new_max, old_current + max(0, new_max - old_max)),
            }
        return merged

    def _validate_spell_choices(
        self,
        *,
        class_name: str,
        target_class_level: int,
        existing_spells: list[dict[str, Any]],
        spell_additions: list[dict[str, Any]],
        spell_removals: set[str],
        after_spells: list[dict[str, Any]],
        target_cantrips: int | None,
        target_prepared: int | None,
        dm_override: bool,
        warnings: list[str],
    ) -> None:
        if not spell_additions and not spell_removals:
            if target_cantrips is not None or target_prepared is not None:
                warnings.append(
                    "本次没有提交法术变更；后端保留原法术表，"
                    "升级界面仍需完成本级法术选择/准备后再用于严格规则战斗。"
                )
            return

        catalog = self._spell_catalog()
        by_id = {
            str(item.get("source_record_id") or ""): item
            for item in catalog
            if item.get("source_record_id")
        }
        by_name = {
            str(item.get("name") or ""): item for item in catalog if item.get("name")
        }
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
                canonical_class_name(str(item))
                for item in list(record.get("classes") or [])
            }
            spell_level = int(record.get("level") or 0)
            if class_name not in record_classes:
                invalid.append(f"{name}不属于{class_name}法术表")
            elif spell_level > max_level:
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
            if canonical_class_name(str(spell.get("class_name") or class_name))
            == class_name
        ]
        cantrip_count = sum(
            int(spell.get("spell_level", spell.get("level", 0)) or 0) == 0
            for spell in class_spells
        )
        prepared_count = sum(
            int(spell.get("spell_level", spell.get("level", 0)) or 0) > 0
            and spell.get("prepared") is True
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
                and str(spell.get("name") or "") not in existing_names
                and str(spell.get("source_record_id") or "") not in existing_ids
            ]
            if len(learned) != 2:
                message = (
                    f"法师本级必须向法术书加入2个新法师法术，当前提交{len(learned)}个"
                )
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
        expected = int(data["character_version"])
        if character.version != expected:
            raise VersionConflict(
                "character", character.id, expected, character.version
            )
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
        requested_class_name = str(data["class_name"])
        rule = self._class_rule(requested_class_name)
        class_name = str(rule.name)
        class_levels = dict(character.class_levels or {})
        if not class_levels and character.class_name:
            class_levels[str(character.class_name)] = character.level
        current_class_level = int(class_levels.get(class_name, 0))
        is_multiclass = bool(class_levels) and class_name not in class_levels
        if is_multiclass:
            failures = validate_multiclass_prerequisites(
                class_name, dict(character.ability_scores or {})
            )
            if failures and not override:
                raise ValueError(
                    "multiclass prerequisites not met: " + ", ".join(failures)
                )
            if failures:
                warnings.append("DM 已覆盖多职业属性前置条件。")
        target_class_level = current_class_level + 1
        level_rule = rule.levels[target_class_level - 1]
        subclass_choices = dict(character.subclass_choices or {})
        subclass_name = str(
            data.get("subclass_name")
            or subclass_choices.get(class_name)
            or ""
        ).strip()
        needs_subclass = any(
            "子职" in feature or "子职业" in feature
            for feature in level_rule.features
        )
        available_subclasses = {item["name"] for item in rule.subclasses}
        if needs_subclass and not subclass_name:
            raise ValueError("this level requires a subclass choice")
        if subclass_name and subclass_name not in available_subclasses:
            raise ValueError("selected subclass is not available for this class")

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
        ability_increases = {
            str(key): int(value)
            for key, value in dict(data.get("ability_increases") or {}).items()
            if int(value)
        }
        grants_asi = any("属性值提升" in feature for feature in level_rule.features)
        feat_choice = str(data.get("feat_choice") or "").strip()
        if grants_asi and not ability_increases and not feat_choice:
            raise ValueError(
                "this level requires ability score increases or one feat choice"
            )
        if ability_increases or feat_choice:
            if not grants_asi:
                raise ValueError("this level does not grant an ability score improvement")
            if ability_increases and feat_choice:
                raise ValueError("choose ability increases or one feat, not both")
            if sum(ability_increases.values()) > 2 or any(
                value not in {1, 2} for value in ability_increases.values()
            ):
                raise ValueError("ability score increases may total at most 2")
            for ability, increase in ability_increases.items():
                if ability not in ability_scores:
                    raise ValueError(f"unknown ability score: {ability}")
                if ability_scores[ability] + increase > 20 and not override:
                    raise ValueError("ability score cannot exceed 20 without a DM override")
                ability_scores[ability] += increase

        spell_additions = [dict(item) for item in data.get("spell_additions", [])]
        spell_removals = {str(item) for item in data.get("spell_removals", [])}
        spell_catalog = self._spell_catalog() if spell_additions else ()
        spell_by_id = {
            str(item.get("source_record_id") or ""): item
            for item in spell_catalog
            if item.get("source_record_id")
        }
        spell_by_name = {
            str(item.get("name") or ""): item
            for item in spell_catalog
            if item.get("name")
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
            existing = existing_by_identity.get(source_id) or existing_by_identity.get(
                name
            )
            if existing is not None:
                existing.update(spell)
                continue
            if name:
                after_spells.append(spell)
                existing_by_identity[name] = spell
                if source_id:
                    existing_by_identity[source_id] = spell

        requirements = advancement_choice_requirements(rule, target_class_level)
        target_cantrips = next(
            (
                item.target_total
                for item in requirements
                if item.key == "cantrips"
            ),
            None,
        )
        target_prepared = next(
            (
                item.target_total
                for item in requirements
                if item.key == "prepared_spells"
            ),
            None,
        )
        self._validate_spell_choices(
            class_name=class_name,
            target_class_level=target_class_level,
            existing_spells=existing_spells,
            spell_additions=spell_additions,
            spell_removals=spell_removals,
            after_spells=after_spells,
            target_cantrips=target_cantrips,
            target_prepared=target_prepared,
            dm_override=bool(override),
            warnings=warnings,
        )

        requested_feature_choices = [
            str(item).strip()
            for item in data.get("feature_choices", [])
            if str(item).strip()
        ]
        feature_requirements = [
            item for item in requirements if item.kind == "feature_option"
        ]
        maximum_feature_choices = sum(item.maximum for item in feature_requirements)
        if requested_feature_choices and not feature_requirements and not override:
            raise ValueError("this level does not grant a class feature option")
        if len(requested_feature_choices) > maximum_feature_choices and not override:
            raise ValueError(
                f"this level allows at most {maximum_feature_choices} feature choices"
            )
        unresolved_feature_requirements = [
            item for item in feature_requirements if not item.strict
        ]
        if unresolved_feature_requirements:
            warnings.append(
                "以下职业选项的数量来自2024成长表，但具体选项前置条件仍需"
                "本地规则条目或DM复核："
                + "、".join(item.key for item in unresolved_feature_requirements)
            )

        class_levels[class_name] = target_class_level
        if subclass_name:
            subclass_choices[class_name] = subclass_name
        after_resources = merge_spell_slot_resources(
            dict(character.resources or {}),
            class_levels,
            subclass_choices,
        )
        resource_updates = progression_resource_updates(rule, target_class_level)
        after_resources = self._merge_progression_resources(
            after_resources,
            resource_updates,
        )
        new_features = [
            {
                "name": feature,
                "class_name": class_name,
                "class_level": target_class_level,
                "source_record_id": rule.source_record_id,
                "rule_year": 2024,
            }
            for feature in level_rule.features
        ]
        chosen_features = [
            {
                "name": str(choice),
                "kind": "feature_choice",
                "class_name": class_name,
                "class_level": target_class_level,
                "source_record_id": rule.source_record_id,
                "rule_year": 2024,
            }
            for choice in requested_feature_choices
        ]
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
            "before": {
                "hp": character.hp,
                "max_hp": character.max_hp,
                "ability_scores": dict(character.ability_scores or {}),
                "class_levels": dict(character.class_levels or {}),
                "spells": list(character.spells or []),
                "resources": dict(character.resources or {}),
            },
            "after": {
                "hp": character.hp + hp_gain,
                "max_hp": character.max_hp + hp_gain,
                "ability_scores": ability_scores,
                "class_levels": class_levels,
                "subclass_choices": subclass_choices,
                "spells": after_spells,
                "resources": after_resources,
            },
            "features_gained": [*new_features, *chosen_features],
            "feat_choice": feat_choice or None,
            "choice_requirements": [item.as_dict() for item in requirements],
            "resource_updates": resource_updates,
            "warnings": warnings,
            "rule_reference": {
                "year": 2024,
                "source_record_id": rule.source_record_id,
                "source_path": rule.source_path,
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
                return dict(existing.result_json or {})
            preview = self._preview_in_session(
                session, campaign_id, character_id, data
            )
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
            character.level = int(preview["to_level"])
            character.hp = int(preview["after"]["hp"])
            character.max_hp = int(preview["after"]["max_hp"])
            character.ability_scores = dict(preview["after"]["ability_scores"])
            character.class_levels = dict(preview["after"]["class_levels"])
            character.subclass_choices = dict(preview["after"]["subclass_choices"])
            character.spells = list(preview["after"]["spells"])
            character.resources = dict(preview["after"]["resources"])
            features = list(character.features or [])
            features.extend(preview["features_gained"])
            if preview["feat_choice"]:
                features.append(
                    {
                        "name": preview["feat_choice"],
                        "kind": "feat",
                        "level": preview["to_level"],
                        "rule_year": 2024,
                    }
                )
            character.features = features
            character.version += 1
            character.updated_at = now
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

    def list_history(
        self, campaign_id: str, character_id: str
    ) -> tuple[dict[str, Any], ...]:
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
            query = select(CharacterCompanion).where(
                CharacterCompanion.campaign_id == campaign_id
            )
            if owner_character_id:
                self._character(session, campaign_id, owner_character_id)
                query = query.where(
                    CharacterCompanion.owner_character_id == owner_character_id
                )
            rows = session.scalars(query.order_by(CharacterCompanion.created_at)).all()
            return tuple(serialize(row) for row in rows)

    def create_companion(
        self, campaign_id: str, data: dict[str, Any]
    ) -> dict[str, Any]:
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
