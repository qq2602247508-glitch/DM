from __future__ import annotations

import hashlib
from fractions import Fraction
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.official_compendium import OfficialCompendiumCatalog
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    AuditLog,
    Campaign,
    Character,
    CompendiumEntry,
    MonsterInstance,
    Scene,
    SceneParticipant,
    WorldItem,
)

ENTRY_TYPES = {
    "spell",
    "feature",
    "monster",
    "equipment",
    "item",
    "npc",
    "location",
    "scene",
    "rule",
}
SOURCE_KINDS = {"official", "original", "ai_generated", "dm_modified", "third_party"}
CURRENT_EDITIONS = {"2024", "2025"}
RARITY_ORDER = {
    "普通": 0,
    "mundane": 0,
    "common": 1,
    "非普通": 2,
    "uncommon": 2,
    "珍稀": 3,
    "稀有": 3,
    "rare": 3,
    "极珍稀": 4,
    "非常稀有": 4,
    "very_rare": 4,
    "传说": 5,
    "legendary": 5,
    "神器": 6,
}


def _integer(value: object, default: int) -> int:
    return int(value) if isinstance(value, (int, float, str)) else default


def _number(value: object, default: float) -> float:
    return float(value) if isinstance(value, (int, float, str)) else default


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _sequence(value: object) -> list[Any]:
    return list(value) if isinstance(value, list) else []


class CompendiumService:
    """Campaign-scoped reusable atoms and explicit template→instance actions."""

    def __init__(
        self,
        engine: Engine,
        *,
        actor: str = "dm",
        catalog_root: Path | None = None,
    ) -> None:
        self.engine = engine
        self.actor = actor
        self.official = OfficialCompendiumCatalog(catalog_root or Path("__missing_catalog__"))

    def list(
        self,
        campaign_id: str,
        *,
        entry_type: str | None = None,
        source_kind: str | None = None,
        text: str = "",
    ) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            query = select(CompendiumEntry).where(CompendiumEntry.campaign_id == campaign_id)
            if entry_type:
                query = query.where(CompendiumEntry.entry_type == entry_type)
            if source_kind:
                query = query.where(CompendiumEntry.source_kind == source_kind)
            if text.strip():
                query = query.where(CompendiumEntry.name.contains(text.strip()))
            items = session.scalars(
                query.order_by(CompendiumEntry.entry_type, CompendiumEntry.name, CompendiumEntry.id)
            ).all()
            return tuple(serialize(item) for item in items)

    def catalog(
        self,
        campaign_id: str,
        *,
        entry_type: str | None = None,
        source_kind: str | None = None,
        text: str = "",
        page: int = 1,
        page_size: int = 40,
        filters: dict[str, str] | None = None,
        include_legacy: bool = False,
        sort_by: str = "default",
        sort_order: str = "asc",
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            campaign = self._campaign(session, campaign_id)
            enabled_content_packs = list(campaign.enabled_content_packs or [])
        custom_base = list(
            self.list(
                campaign_id,
                entry_type=entry_type,
                source_kind=source_kind if source_kind != "official" else "__none__",
                text=text,
            )
        )
        official_base = (
            []
            if source_kind and source_kind != "official"
            else self.official.search(
                entry_type=entry_type,
                text=text,
                enabled_content_packs=enabled_content_packs,
                allow_legacy=bool(campaign.allow_legacy),
            )
        )
        base_items = [
            *[
                item
                for item in official_base
                if include_legacy
                or str(
                    dict(item.get("filters_json") or {}).get("content_pack_key") or ""
                )
                in set(enabled_content_packs)
                or str(dict(item.get("filters_json") or {}).get("edition") or "")
                in CURRENT_EDITIONS
            ],
            *custom_base,
        ]
        facets: dict[str, list[str]] = {}
        for key in (
            "class_name",
            "spell_level",
            "monster_type",
            "challenge_rating",
            "slot",
            "rarity",
            "category",
            "attunement",
            "edition",
            "content_type",
            "feature_kind",
            "item_function",
            "item_kind",
            "content_pack_key",
        ):
            values: set[str] = set()
            for item in base_items:
                raw = dict(item.get("filters_json") or {}).get(key)
                if key == "class_name":
                    raw_classes = dict(item.get("filters_json") or {}).get("classes", [])
                    if isinstance(raw_classes, list):
                        values.update(str(value) for value in raw_classes if value)
                        continue
                if isinstance(raw, list):
                    values.update(str(value) for value in raw if value)
                elif raw is not None and str(raw):
                    values.add(str(raw))
            facets[key] = sorted(values, key=lambda value: (len(value), value))
        items = [item for item in base_items if self.official.matches_filters(item, filters or {})]
        items.sort(key=lambda item: self._sort_key(item, sort_by), reverse=sort_order == "desc")
        start = (page - 1) * page_size
        counts: dict[str, int] = {}
        for item in base_items:
            key = str(item.get("entry_type") or "")
            counts[key] = counts.get(key, 0) + 1
        return {
            "items": items[start : start + page_size],
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "counts": counts,
            "official_total": sum(
                1 for item in base_items if item.get("source_kind") == "official"
            ),
            "facets": facets,
            "enabled_content_packs": enabled_content_packs,
        }

    def content_packs(self) -> tuple[dict[str, Any], ...]:
        """Metadata and locally importable atom counts for the setup screen."""

        return self.official.content_packs()

    @staticmethod
    def _sort_key(item: dict[str, Any], sort_by: str) -> tuple[Any, ...]:
        filters = dict(item.get("filters_json") or {})
        source = 0 if item.get("source_kind") == "official" else 1
        name = str(item.get("name") or "")
        item_id = str(item.get("id") or "")
        if sort_by == "level":
            level = filters.get("spell_level", filters.get("recommended_level", 99))
            return source, _integer(level, 99), name, item_id
        if sort_by == "strength":
            challenge = str(filters.get("challenge_rating") or "")
            try:
                strength: float = float(Fraction(challenge))
            except (ValueError, ZeroDivisionError):
                strength = float(RARITY_ORDER.get(str(filters.get("rarity") or ""), 99))
            return source, strength, name, item_id
        if sort_by == "class":
            return (
                source,
                str(filters.get("class_name") or "未分类"),
                0 if filters.get("feature_kind") == "class" else 1,
                _integer(filters.get("recommended_level"), 99),
                name,
                item_id,
            )
        if sort_by == "category":
            return (
                source,
                str(filters.get("item_function") or filters.get("category") or ""),
                RARITY_ORDER.get(str(filters.get("rarity") or ""), 99),
                name,
                item_id,
            )
        return source, name, item_id

    def create(
        self,
        campaign_id: str,
        data: dict[str, Any],
        *,
        request_id: str,
    ) -> dict[str, Any]:
        self._validate_entry(data)
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            existing = session.scalar(
                select(CompendiumEntry).where(
                    CompendiumEntry.campaign_id == campaign_id,
                    CompendiumEntry.entry_type == data["entry_type"],
                    CompendiumEntry.name == data["name"],
                    CompendiumEntry.source_kind == data.get("source_kind", "original"),
                )
            )
            if existing is not None:
                return serialize(existing)
            item = CompendiumEntry(
                campaign_id=campaign_id,
                entry_type=str(data["entry_type"]),
                name=str(data["name"]).strip(),
                description=str(data.get("description") or "") or None,
                source_kind=str(data.get("source_kind", "original")),
                source_record_id=data.get("source_record_id"),
                source_name=data.get("source_name"),
                family_key=data.get("family_key"),
                tags=list(data.get("tags", [])),
                filters_json=dict(data.get("filters_json", {})),
                rules_json=dict(data.get("rules_json", {})),
            )
            session.add(item)
            session.flush()
            session.add(
                AuditLog(
                    campaign_id=campaign_id,
                    actor=self.actor,
                    action="create",
                    entity_type="compendium_entry",
                    entity_id=item.id,
                    before_json=None,
                    after_json={"name": item.name, "entry_type": item.entry_type},
                    request_id=request_id,
                )
            )
            return serialize(item)

    @staticmethod
    def generate_preview(data: dict[str, Any]) -> dict[str, Any]:
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("generation prompt is required")
        level = max(1, min(20, int(data.get("applicable_level", 1))))
        mode = str(data.get("mode", "single"))
        family_key = hashlib.sha256(f"{mode}|{prompt}|{level}".encode()).hexdigest()[:16]
        if mode == "equipment_set":
            rarity = (
                "普通"
                if level < 5
                else "非普通"
                if level < 9
                else "稀有"
                if level < 13
                else "非常稀有"
            )
            entries = [
                {
                    "entry_type": "equipment",
                    "name": f"{prompt} · 武器",
                    "description": f"适合约 {level} 级角色的主题武器；最终外观由 DM 描述。",
                    "source_kind": "ai_generated",
                    "family_key": family_key,
                    "tags": ["原创", "AI生成", "套装", rarity],
                    "filters_json": {
                        "slot": "main_hand",
                        "rarity": rarity,
                        "recommended_level": level,
                    },
                    "rules_json": {
                        "damage": "1d8+属性调整值",
                        "weight_lb": 3,
                        "price_cp": max(5000, level * level * 500),
                        "attunement": level >= 5,
                    },
                },
                {
                    "entry_type": "equipment",
                    "name": f"{prompt} · 护甲",
                    "description": f"适合约 {level} 级角色的主题护甲。",
                    "source_kind": "ai_generated",
                    "family_key": family_key,
                    "tags": ["原创", "AI生成", "套装", rarity],
                    "filters_json": {
                        "slot": "armor",
                        "rarity": rarity,
                        "recommended_level": level,
                    },
                    "rules_json": {
                        "armor_class": min(18, 12 + level // 4),
                        "weight_lb": 20,
                        "price_cp": max(7500, level * level * 650),
                        "attunement": level >= 5,
                    },
                },
                {
                    "entry_type": "item",
                    "name": f"{prompt} · 护符",
                    "description": "主题套装的探索性配件；具体叙事效果由 DM 裁定。",
                    "source_kind": "ai_generated",
                    "family_key": family_key,
                    "tags": ["原创", "AI生成", "套装", rarity],
                    "filters_json": {
                        "category": "wondrous",
                        "rarity": rarity,
                        "recommended_level": level,
                    },
                    "rules_json": {
                        "weight_lb": 1,
                        "price_cp": max(2500, level * level * 300),
                        "charges": max(1, level // 4),
                    },
                },
            ]
        elif mode == "monster_family":
            variants = (("幼体", -2), ("猎手", 0), ("施法者", 1), ("首领", 3))
            entries = []
            for label, offset in variants:
                tier = max(1, level + offset)
                entries.append(
                    {
                        "entry_type": "monster",
                        "name": f"{prompt} · {label}",
                        "description": f"{prompt}怪物家族的{label}变体。",
                        "source_kind": "ai_generated",
                        "family_key": family_key,
                        "tags": ["原创", "AI生成", "怪物家族", label],
                        "filters_json": {
                            "challenge_rating": str(max(0.125, round(tier / 3, 2))),
                            "role": label,
                            "recommended_level": level,
                        },
                        "rules_json": {
                            "armor_class": min(21, 11 + tier // 3),
                            "hp": 8 + tier * (5 if label != "首领" else 9),
                            "speed": 30,
                            "ability_scores": {
                                "strength": 10 + tier // 2,
                                "dexterity": 12,
                                "constitution": 10 + tier // 2,
                                "intelligence": 8 + (tier if label == "施法者" else 0),
                                "wisdom": 10,
                                "charisma": 8,
                            },
                            "actions": [
                                {
                                    "name": "主题攻击",
                                    "range_ft": 30 if label == "施法者" else 5,
                                    "damage": f"{1 + tier // 6}d8+{max(1, tier // 4)}",
                                    "action_type": "action",
                                }
                            ],
                        },
                    }
                )
        else:
            entry_type = str(data.get("entry_type", "item"))
            entries = [
                {
                    "entry_type": entry_type,
                    "name": prompt,
                    "description": f"面向约 {level} 级队伍生成的原创图鉴条目。",
                    "source_kind": "ai_generated",
                    "family_key": family_key,
                    "tags": ["原创", "AI生成"],
                    "filters_json": {"recommended_level": level},
                    "rules_json": {},
                }
            ]
        for entry in entries:
            CompendiumService._validate_entry(entry)
        return {
            "schema_version": "1.0",
            "mode": mode,
            "prompt": prompt,
            "applicable_level": level,
            "entries": entries,
            "warnings": [
                "所有条目均标记为原创/AI生成，不冒充官方规则。",
                "确认写入前请复核特殊能力；数值已按适用等级限制在安全范围。",
            ],
        }

    def confirm_generated(
        self,
        campaign_id: str,
        preview: dict[str, Any],
        *,
        request_id: str,
    ) -> tuple[dict[str, Any], ...]:
        entries = preview.get("entries")
        if preview.get("schema_version") != "1.0" or not isinstance(entries, list) or not entries:
            raise ValueError("invalid compendium generation preview")
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            result: list[dict[str, Any]] = []
            for data in entries:
                if not isinstance(data, dict):
                    raise ValueError("invalid compendium entry")
                self._validate_entry(data)
                existing = session.scalar(
                    select(CompendiumEntry).where(
                        CompendiumEntry.campaign_id == campaign_id,
                        CompendiumEntry.entry_type == data["entry_type"],
                        CompendiumEntry.name == data["name"],
                        CompendiumEntry.source_kind == data["source_kind"],
                    )
                )
                if existing is None:
                    existing = CompendiumEntry(
                        campaign_id=campaign_id,
                        entry_type=str(data["entry_type"]),
                        name=str(data["name"]),
                        description=str(data.get("description") or "") or None,
                        source_kind=str(data["source_kind"]),
                        family_key=data.get("family_key"),
                        tags=list(data.get("tags", [])),
                        filters_json=dict(data.get("filters_json", {})),
                        rules_json=dict(data.get("rules_json", {})),
                    )
                    session.add(existing)
                    session.flush()
                result.append(serialize(existing))
            session.add(
                AuditLog(
                    campaign_id=campaign_id,
                    actor=self.actor,
                    action="generate",
                    entity_type="compendium_entry",
                    entity_id=None,
                    before_json=None,
                    after_json={"count": len(result), "prompt": preview.get("prompt")},
                    request_id=request_id,
                )
            )
            return tuple(result)

    def instantiate(
        self,
        campaign_id: str,
        entry_id: str,
        data: dict[str, Any],
        *,
        request_id: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            campaign = self._campaign(session, campaign_id)
            entry: dict[str, Any] | None
            persisted = session.get(CompendiumEntry, entry_id)
            if persisted is not None and persisted.campaign_id == campaign_id:
                entry = serialize(persisted)
            elif entry_id.startswith("official:"):
                entry = self.official.get(
                    entry_id,
                    enabled_content_packs=campaign.enabled_content_packs,
                    allow_legacy=bool(campaign.allow_legacy),
                )
            else:
                entry = None
            if entry is None:
                raise StateNotFoundError("compendium entry not found")
            target_type = str(data.get("target_type") or "")
            target_id = str(data.get("target_id") or "")
            if target_type == "character":
                character = session.get(Character, target_id)
                if character is None or character.campaign_id != campaign_id:
                    raise StateNotFoundError("character not found")
                entry_type = str(entry["entry_type"])
                if entry_type in {"spell", "feature"}:
                    field = "spells" if entry_type == "spell" else "features"
                    values = list(getattr(character, field) or [])
                    values.append(
                        {
                            "name": entry["name"],
                            "description": entry.get("description"),
                            "source_record_id": entry.get("source_record_id"),
                            "source_kind": entry.get("source_kind"),
                            **dict(entry.get("rules_json") or {}),
                        }
                    )
                    setattr(character, field, values)
                    character.version += 1
                    result = {"target_type": "character", "target_id": character.id, "field": field}
                elif entry_type in {"equipment", "item"}:
                    rules = dict(entry.get("rules_json") or {})
                    item = WorldItem(
                        campaign_id=campaign_id,
                        name=str(entry["name"]),
                        description=entry.get("description"),
                        category=entry_type,
                        quantity=1,
                        unit_weight_lb=_number(rules.get("weight_lb"), 0),
                        price_cp=_integer(rules.get("price_cp"), 0),
                        source_record_id=entry.get("source_record_id"),
                        source_label=(
                            "official" if entry.get("source_kind") == "official" else "ai_generated"
                        ),
                        owner_character_id=character.id,
                        metadata_json={
                            "compendium_entry_id": entry["id"],
                            "source_kind": entry.get("source_kind"),
                            **dict(entry.get("filters_json") or {}),
                            **rules,
                        },
                    )
                    session.add(item)
                    session.flush()
                    result = {
                        "target_type": "character",
                        "target_id": character.id,
                        "item_id": item.id,
                    }
                else:
                    raise ValueError("this entry type cannot be given to a character")
            elif target_type == "scene":
                scene = session.get(Scene, target_id)
                if scene is None or scene.campaign_id != campaign_id:
                    raise StateNotFoundError("scene not found")
                rules = dict(entry.get("rules_json") or {})
                entry_type = str(entry["entry_type"])
                if entry_type == "monster":
                    entity: NPC | MonsterInstance = MonsterInstance(
                        campaign_id=campaign_id,
                        name=str(entry["name"]),
                        source_record_id=entry.get("source_record_id"),
                        source_name=entry.get("source_name") or entry.get("source_kind"),
                        armor_class=_integer(rules.get("armor_class"), 12),
                        hp=_integer(rules.get("hp"), 8),
                        max_hp=_integer(rules.get("hp"), 8),
                        speed=_integer(rules.get("speed"), 30),
                        ability_scores=_mapping(rules.get("ability_scores")),
                        challenge_rating=str(
                            dict(entry.get("filters_json") or {}).get("challenge_rating", "1/4")
                        ),
                        actions=_sequence(rules.get("actions")),
                        damage_resistances=_sequence(rules.get("damage_resistances")),
                        damage_vulnerabilities=_sequence(rules.get("damage_vulnerabilities")),
                        damage_immunities=_sequence(rules.get("damage_immunities")),
                        condition_immunities=_sequence(rules.get("condition_immunities")),
                        notes=entry.get("description"),
                    )
                    entity_type = "monster"
                elif entry_type == "npc":
                    entity = NPC(
                        campaign_id=campaign_id,
                        name=str(entry["name"]),
                        description=entry.get("description"),
                        armor_class=_integer(rules.get("armor_class"), 10),
                        hp=_integer(rules.get("hp"), 4),
                        max_hp=_integer(rules.get("hp"), 4),
                        ability_scores=_mapping(rules.get("ability_scores")),
                    )
                    entity_type = "npc"
                else:
                    raise ValueError("only monster or npc templates can enter a scene")
                session.add(entity)
                session.flush()
                participant = SceneParticipant(
                    scene_id=scene.id,
                    entity_type=entity_type,
                    entity_id=entity.id,
                    role="present",
                    visible=True,
                    notes=f"由图鉴模板 {entry['name']} 创建。",
                )
                session.add(participant)
                session.flush()
                result = {
                    "target_type": "scene",
                    "target_id": scene.id,
                    "entity_type": entity_type,
                    "entity_id": entity.id,
                    "participant_id": participant.id,
                }
            else:
                raise ValueError("target_type must be character or scene")
            session.add(
                AuditLog(
                    campaign_id=campaign_id,
                    actor=self.actor,
                    action="instantiate",
                    entity_type="compendium_entry",
                    entity_id=entry_id,
                    before_json=None,
                    after_json=result,
                    request_id=request_id,
                )
            )
            return result

    @staticmethod
    def _validate_entry(data: dict[str, Any]) -> None:
        if str(data.get("entry_type")) not in ENTRY_TYPES:
            raise ValueError("invalid compendium entry type")
        if not str(data.get("name") or "").strip():
            raise ValueError("compendium entry name is required")
        if str(data.get("source_kind", "original")) not in SOURCE_KINDS:
            raise ValueError("invalid compendium source kind")
        if len(list(data.get("tags", []))) > 30:
            raise ValueError("too many compendium tags")

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign
