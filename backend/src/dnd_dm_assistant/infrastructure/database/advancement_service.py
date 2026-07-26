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
        if class_name == "邪术师":
            class_name = "魔契师"
        rule = next(
            (item for item in self.catalog.classes() if item.name == class_name),
            None,
        )
        if rule is None:
            raise ValueError("selected 2024 class is unavailable in the local rule catalog")
        return rule

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
        needs_subclass = any("子职" in feature for feature in level_rule.features)
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
        existing_spells = [
            dict(item) if isinstance(item, dict) else {"name": str(item)}
            for item in (character.spells or [])
        ]
        after_spells = [
            item for item in existing_spells if str(item.get("name")) not in spell_removals
        ]
        existing_names = {str(item.get("name")) for item in after_spells}
        for spell in spell_additions:
            if str(spell.get("name") or "").strip() and str(spell["name"]) not in existing_names:
                after_spells.append(spell)
                existing_names.add(str(spell["name"]))

        class_levels[class_name] = target_class_level
        if subclass_name:
            subclass_choices[class_name] = subclass_name
        after_resources = merge_spell_slot_resources(
            dict(character.resources or {}),
            class_levels,
            subclass_choices,
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
            for choice in data.get("feature_choices", [])
            if str(choice).strip()
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
