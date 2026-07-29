from __future__ import annotations

import builtins
import hashlib
import random
import secrets
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.official_compendium import OfficialCompendiumCatalog
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    Campaign,
    Character,
    CompendiumEntry,
    Location,
    Scene,
    SceneGrid,
    SceneParticipant,
    SceneToken,
    ShopInventory,
)

TIER_RANK = {
    "mundane": 0,
    "common": 1,
    "uncommon": 2,
    "rare": 3,
    "very_rare": 4,
    "legendary": 5,
}
RARITY_RANK = {
    "普通": 1,
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
MAGIC_PRICE_RANGES_CP = {
    1: (5_000, 10_000),
    2: (10_000, 50_000),
    3: (50_000, 500_000),
    4: (500_000, 5_000_000),
    5: (5_000_000, 20_000_000),
    6: (20_000_000, 50_000_000),
}


class MerchantService:
    """Create campaign shop instances from reusable official or original atoms."""

    def __init__(self, engine: Engine, catalog_root: Path) -> None:
        self.engine = engine
        self.catalog = OfficialCompendiumCatalog(catalog_root)

    def preview(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        categories = [str(item) for item in data.get("categories", []) if str(item)]
        character_ids = [str(item) for item in data.get("character_ids", []) if str(item)]
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            location = self._optional_owned(session, Location, campaign_id, data.get("location_id"))
            scene = self._optional_owned(session, Scene, campaign_id, data.get("scene_id"))
            characters = (
                list(
                    session.scalars(
                        select(Character).where(
                            Character.campaign_id == campaign_id,
                            Character.id.in_(character_ids),
                        )
                    )
                )
                if character_ids
                else []
            )
            if len(characters) != len(set(character_ids)):
                raise ValueError("selected character is outside the current campaign")
        stock_size = max(1, min(40, int(data.get("stock_size", 12))))
        tier = str(data.get("item_tier", "common"))
        tier_rank = TIER_RANK.get(tier, 1)
        seed = int(data.get("seed") or secrets.randbits(63))
        rng = random.Random(seed)
        class_text = " ".join((item.class_name or "").lower() for item in characters)
        preferred = self._preferred_categories(class_text)
        candidates = [
            entry
            for entry in self.catalog.entries
            if entry["entry_type"] in {"equipment", "item"}
            and bool(entry.get("filters_json", {}).get("atomic_item"))
            and str(entry.get("filters_json", {}).get("edition") or "") in {"2024", "2025"}
            and self._matches_categories(entry, categories)
            and self._within_tier(entry, tier_rank)
        ]
        rng.shuffle(candidates)
        candidates.sort(
            key=lambda entry: (
                str(entry.get("filters_json", {}).get("category", "")) not in preferred,
                abs(self._rarity_rank(entry) - tier_rank),
                rng.random(),
            )
        )
        selected = self._diverse_selection(candidates, stock_size)
        generation_data = {**data, "seed": seed}
        rows = [self._stock_from_atom(entry, generation_data, rng) for entry in selected]
        party_level = (
            round(sum(item.level for item in characters) / len(characters))
            if characters
            else None
        )
        if bool(data.get("allow_original", True)) and len(rows) < stock_size:
            generation_data = {**generation_data, "party_level": party_level}
            rows.extend(
                self._original_stock(generation_data, index)
                for index in range(len(rows), stock_size)
            )
        return {
            "schema_version": "1.0",
            "merchant": {
                "name": str(data.get("name") or "旅行商人"),
                "brief": str(data.get("brief") or "由规则图鉴选货的商人。"),
                "location_id": location.id if location else None,
                "location_name": location.name if location else None,
                "scene_id": scene.id if scene else None,
                "scene_name": scene.name if scene else None,
                "categories": categories,
                "item_tier": tier,
                "character_ids": character_ids,
                "character_names": [item.name for item in characters],
                "price_modifier_bps": int(data.get("price_modifier_bps", 10_000)),
            },
            "stock": rows,
            "summary": {
                "official_atoms": sum(row["source_kind"] == "official" for row in rows),
                "original_atoms": sum(row["source_kind"] == "original" for row in rows),
                "party_level": party_level,
                "seed": seed,
                "categories": {
                    category: sum(row["category"] == category for row in rows)
                    for category in sorted({str(row["category"]) for row in rows})
                },
            },
        }

    def confirm(
        self, campaign_id: str, preview: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        merchant_data = dict(preview.get("merchant") or {})
        stock = list(preview.get("stock") or [])
        if not stock:
            raise ValueError("merchant preview has no stock")
        merchant_id = str(uuid4())
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            location = self._optional_owned(
                session, Location, campaign_id, merchant_data.get("location_id")
            )
            scene = self._optional_owned(session, Scene, campaign_id, merchant_data.get("scene_id"))
            npc = NPC(
                campaign_id=campaign_id,
                name=str(merchant_data.get("name") or "旅行商人"),
                description=str(merchant_data.get("brief") or "经营规则合法商品。"),
                attitude="neutral",
                location_id=location.id if location else (scene.location_id if scene else None),
                hp=9,
                max_hp=9,
                armor_class=10,
            )
            session.add(npc)
            session.flush()
            if scene is not None:
                session.add(
                    SceneParticipant(
                        scene_id=scene.id,
                        entity_type="npc",
                        entity_id=npc.id,
                        role="merchant",
                        visible=True,
                        notes="商店创建时自动加入。",
                    )
                )
                row, col = self._scene_spawn(session, scene.id)
                session.add(
                    SceneToken(
                        scene_id=scene.id,
                        entity_type="npc",
                        entity_id=npc.id,
                        label=npc.name,
                        row=row,
                        col=col,
                        visible=True,
                        metadata_json={"merchant_id": merchant_id},
                    )
                )
            created_stock: list[ShopInventory] = []
            for raw in stock:
                item = dict(raw)
                compendium_id = item.get("compendium_entry_id")
                if item.get("source_kind") == "original":
                    entry = CompendiumEntry(
                        campaign_id=campaign_id,
                        entry_type=str(item.get("entry_type", "item")),
                        name=str(item["name"]),
                        description=str(item.get("description") or ""),
                        source_kind="original",
                        source_name="商店生成器",
                        tags=["原创", "商店生成"],
                        filters_json=dict(item.get("filters_json") or {}),
                        rules_json=dict(item.get("rules_json") or {}),
                    )
                    session.add(entry)
                    session.flush()
                    compendium_id = entry.id
                inventory = ShopInventory(
                    campaign_id=campaign_id,
                    name=str(item["name"]),
                    quantity=max(0, int(item.get("quantity", 1))),
                    price_copper=max(0, int(item.get("price_copper", 0))),
                    metadata_json={
                        "merchant_id": merchant_id,
                        "merchant_name": npc.name,
                        "merchant_npc_id": npc.id,
                        "location_id": merchant_data.get("location_id"),
                        "scene_id": merchant_data.get("scene_id"),
                        "category": item.get("category"),
                        "item_tier": merchant_data.get("item_tier"),
                        "source_kind": item.get("source_kind"),
                        "source_record_id": item.get("source_record_id"),
                        "compendium_entry_id": compendium_id,
                        "request_id": request_id,
                    },
                )
                session.add(inventory)
                created_stock.append(inventory)
            session.flush()
            result = {
                "merchant_id": merchant_id,
                "merchant_npc": serialize(npc),
                "merchant": merchant_data,
                "stock": [serialize(item) for item in created_stock],
            }
        return result

    def list(self, campaign_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            rows = list(
                session.scalars(
                    select(ShopInventory)
                    .where(ShopInventory.campaign_id == campaign_id)
                    .order_by(ShopInventory.created_at.desc(), ShopInventory.name)
                )
            )
            grouped: dict[str, dict[str, Any]] = {}
            for row in rows:
                metadata = dict(row.metadata_json)
                merchant_id = str(metadata.get("merchant_id") or "")
                if not merchant_id:
                    continue
                group = grouped.setdefault(
                    merchant_id,
                    {
                        "merchant_id": merchant_id,
                        "name": metadata.get("merchant_name") or "商店",
                        "npc_id": metadata.get("merchant_npc_id"),
                        "location_id": metadata.get("location_id"),
                        "scene_id": metadata.get("scene_id"),
                        "item_tier": metadata.get("item_tier"),
                        "stock": [],
                    },
                )
                group["stock"].append(serialize(row))
            return list(grouped.values())

    @staticmethod
    def _preferred_categories(class_text: str) -> set[str]:
        preferred = {"adventuring_gear", "potion"}
        if any(value in class_text for value in ("fighter", "战士", "paladin", "圣武士")):
            preferred.update({"weapon", "armor", "shield"})
        if any(value in class_text for value in ("wizard", "法师", "sorcerer", "术士")):
            preferred.update({"scroll", "wand", "staff", "ring", "wondrous"})
        if any(value in class_text for value in ("rogue", "游荡者", "ranger", "游侠")):
            preferred.update({"weapon", "adventuring_gear"})
        return preferred

    @staticmethod
    def _rarity_rank(entry: dict[str, Any]) -> int:
        filters = dict(entry.get("filters_json") or {})
        if filters.get("item_kind") in {"mundane_item", "mundane_equipment"}:
            return 0
        return RARITY_RANK.get(str(filters.get("rarity") or ""), 1)

    @classmethod
    def _within_tier(cls, entry: dict[str, Any], tier_rank: int) -> bool:
        rank = cls._rarity_rank(entry)
        return rank == 0 if tier_rank == 0 else rank <= tier_rank

    @staticmethod
    def _matches_categories(
        entry: dict[str, Any], categories: builtins.list[str]
    ) -> bool:
        if not categories:
            return True
        filters = dict(entry.get("filters_json") or {})
        category = str(filters.get("category") or "")
        kind = str(filters.get("item_kind") or "")
        item_function = str(filters.get("item_function") or "")
        for requested in categories:
            if requested in {"weapon", "armor", "shield"} and category == requested:
                return True
            if requested == "adventuring_gear" and kind == "mundane_item":
                return True
            if requested == "consumable" and (
                category in {"potion", "scroll"} or item_function == "consumable"
            ):
                return True
            if requested == "magic" and kind in {"magic_equipment", "magic_consumable"}:
                return True
        return False

    @staticmethod
    def _diverse_selection(
        candidates: builtins.list[dict[str, Any]], stock_size: int
    ) -> builtins.list[dict[str, Any]]:
        selected: builtins.list[dict[str, Any]] = []
        remaining: builtins.list[dict[str, Any]] = candidates.copy()
        seen_categories: set[str] = set()
        while remaining and len(selected) < stock_size:
            index = next(
                (
                    position
                    for position, entry in enumerate(remaining)
                    if str(entry.get("filters_json", {}).get("category", ""))
                    not in seen_categories
                ),
                0,
            )
            entry = remaining.pop(index)
            selected.append(entry)
            seen_categories.add(str(entry.get("filters_json", {}).get("category", "")))
        return selected

    @classmethod
    def _stock_from_atom(
        cls, entry: dict[str, Any], data: dict[str, Any], rng: random.Random
    ) -> dict[str, Any]:
        rules = dict(entry.get("rules_json") or {})
        filters = dict(entry.get("filters_json") or {})
        modifier = max(5_000, min(20_000, int(data.get("price_modifier_bps", 10_000))))
        base_price = int(rules.get("price_cp", 0))
        rank = cls._rarity_rank(entry)
        if base_price <= 0:
            low, high = MAGIC_PRICE_RANGES_CP.get(rank, MAGIC_PRICE_RANGES_CP[1])
            identity = f"{entry.get('id')}|{data.get('seed', '')}"
            stable = int(hashlib.sha256(identity.encode()).hexdigest()[:8], 16)
            base_price = low + stable % max(1, high - low + 1)
        category = str(filters.get("category", "misc"))
        quantity = (
            rng.randint(1, 4)
            if category in {"potion", "scroll"} or filters.get("item_function") == "consumable"
            else rng.randint(1, 3)
            if rank == 0
            else 1
        )
        return {
            "name": entry["name"],
            "description": entry.get("description"),
            "entry_type": entry["entry_type"],
            "category": category,
            "quantity": quantity,
            "price_copper": max(1, base_price * modifier // 10_000),
            "source_kind": "official",
            "source_record_id": entry.get("source_record_id"),
            "compendium_entry_id": entry["id"],
            "filters_json": filters,
            "rules_json": {**rules, "price_cp": base_price},
        }

    @staticmethod
    def _original_stock(data: dict[str, Any], index: int) -> dict[str, Any]:
        categories = list(data.get("categories") or ["adventuring_gear"])
        category = str(categories[index % len(categories)])
        tier = str(data.get("item_tier", "common"))
        base = {
            "mundane": 500,
            "common": 5_000,
            "uncommon": 30_000,
            "rare": 200_000,
            "very_rare": 1_000_000,
            "legendary": 5_000_000,
        }.get(tier, 5_000)
        style = str(data.get("brief") or "本地风格").strip()
        names = {
            "weapon": ("余烬淬火短剑", "巡路者折叠长矛", "守夜人银纹短弓"),
            "armor": ("烟痕鳞甲", "远行者夹层皮甲", "月灯守卫胸甲"),
            "shield": ("铜缘折光盾", "远行者圆盾", "月纹护卫盾"),
            "adventuring_gear": ("无烟引火盒", "防水地图匣", "静音滑轮组"),
            "consumable": ("清醒薄荷剂", "烟幕蜡丸", "止血树脂包"),
            "magic": ("余烬回响护符", "月灯储能戒指", "折光旅法杖"),
        }
        pool = names.get(category, names["adventuring_gear"])
        name = pool[index % len(pool)]
        return {
            "name": name,
            "description": (
                f"根据“{style[:40]}”生成的具名原创候选；效果、价格与适用等级已经规则预算，"
                "仍需 DM 在确认商店时批准。"
            ),
            "entry_type": (
                "item" if category == "adventuring_gear" else "equipment"
            ),
            "category": category,
            "quantity": 1,
            "price_copper": base,
            "source_kind": "original",
            "source_record_id": None,
            "compendium_entry_id": None,
            "filters_json": {
                "category": category,
                "rarity": tier,
                "recommended_level": int(data.get("party_level") or 1),
                "atomic_item": True,
            },
            "rules_json": {"price_cp": base, "rules_validated_budget": True},
        }

    @staticmethod
    def _scene_spawn(session: Session, scene_id: str) -> tuple[int, int]:
        grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))
        if grid is None:
            return 1, 1
        raw_cells = grid.layers_json.get("cells", [])
        cells = raw_cells if isinstance(raw_cells, list) else []
        for cell in cells:
            if not isinstance(cell, dict):
                continue
            if cell.get("kind") in {"floor", "room"}:
                return int(cell.get("row", 1)), int(cell.get("col", 1))
        return 1, 1

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign

    @staticmethod
    def _optional_owned(
        session: Session, model: type[Any], campaign_id: str, entity_id: Any
    ) -> Any | None:
        if not entity_id:
            return None
        entity = session.get(model, str(entity_id))
        if entity is None or getattr(entity, "campaign_id", None) != campaign_id:
            raise ValueError("selected location or scene is outside the current campaign")
        return entity
