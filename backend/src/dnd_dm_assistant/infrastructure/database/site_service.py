from __future__ import annotations

import hashlib
import random
import re
import time
from pathlib import Path
from threading import Lock, RLock
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from dnd_dm_assistant.application.official_compendium import OfficialCompendiumCatalog
from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
from dnd_dm_assistant.domain.site_generation import generate_site, layout_is_connected
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    NPC,
    AdventureSite,
    AuditLog,
    Campaign,
    Character,
    Location,
    MonsterInstance,
    RegionMap,
    Scene,
    SceneGrid,
    SceneObject,
    SceneParticipant,
    SceneToken,
    SiteConnector,
    SiteLevel,
    SiteRoom,
    WorldItem,
)


class _ConcurrentRegionUpdate(RuntimeError):
    """Internal retry signal for an optimistic region-map write."""


_SITE_LOCKS_GUARD = Lock()
_SITE_LOCKS: dict[tuple[str, str], Any] = {}


def _generation_lock(engine: Engine, campaign_id: str) -> Any:
    """Serialize local site writes per campaign without blocking other campaigns."""

    key = (str(engine.url), campaign_id)
    with _SITE_LOCKS_GUARD:
        return _SITE_LOCKS.setdefault(key, RLock())


def _next_spawn(
    room_index: int,
    room_spawn_cells: dict[int, list[tuple[int, int]]],
    occupied_cells: set[tuple[int, int]],
    scene_cells: list[dict[str, Any]],
) -> tuple[int, int]:
    for candidate in room_spawn_cells.get(room_index, []):
        if candidate not in occupied_cells:
            occupied_cells.add(candidate)
            return candidate
    fallback = next(
        (
            (int(cell["row"]), int(cell["col"]))
            for cell in scene_cells
            if cell.get("kind") in {"floor", "room"}
            and (int(cell["row"]), int(cell["col"])) not in occupied_cells
        ),
        (1, 1),
    )
    occupied_cells.add(fallback)
    return fallback


def _safe_int(value: object, default: int) -> int:
    return int(value) if isinstance(value, (int, float, str)) else default


class SiteService:
    def __init__(
        self,
        engine: Engine,
        *,
        actor: str = "dm",
        catalog_root: Path | None = None,
    ) -> None:
        self.engine = engine
        self.actor = actor
        self.official_catalog = OfficialCompendiumCatalog(
            catalog_root or Path("__missing_catalog__")
        )

    def preview(self, campaign_id: str, data: dict[str, Any]) -> dict[str, Any]:
        character_ids = [str(item) for item in data.get("character_ids", []) if str(item)]
        if character_ids:
            with Session(self.engine) as session:
                characters = session.scalars(
                    select(Character).where(
                        Character.campaign_id == campaign_id,
                        Character.id.in_(character_ids),
                    )
                ).all()
                found = {item.id for item in characters}
                missing = [item for item in character_ids if item not in found]
                if missing:
                    raise ValueError("selected character is outside the current campaign")
                data = {
                    **data,
                    "party_profiles": [
                        {
                            "id": item.id,
                            "name": item.name,
                            "level": item.level,
                            "class_name": item.class_name,
                            "armor_class": item.armor_class,
                            "hp": item.hp,
                            "max_hp": item.max_hp,
                            "skills": item.skills,
                            "features": item.features,
                            "spells": item.spells,
                        }
                        for item in characters
                    ],
                }
        preview = generate_site(data)
        self._bind_official_reward_atoms(preview)
        return preview

    def _bind_official_reward_atoms(self, preview: dict[str, Any]) -> None:
        """Replace abstract reward placeholders with reusable official atoms."""

        site = dict(preview.get("site") or {})
        parameters = dict(site.get("generation_parameters") or {})
        profiles = [
            item for item in parameters.get("party_profiles", []) if isinstance(item, dict)
        ]
        class_text = " ".join(str(item.get("class_name") or "") for item in profiles)
        theme = str(site.get("theme") or "default")
        seed = int(site.get("seed") or 0)
        candidates = [
            entry
            for entry in self.official_catalog.entries
            if entry.get("entry_type") in {"equipment", "item"}
            and bool(dict(entry.get("filters_json") or {}).get("atomic_item"))
            and str(dict(entry.get("filters_json") or {}).get("edition") or "")
            in {"2024", "2025"}
        ]
        used: set[str] = set()
        for level in preview.get("levels", []):
            if not isinstance(level, dict):
                continue
            rewards = level.get("reward_plan", [])
            if not isinstance(rewards, list):
                continue
            for index, raw in enumerate(rewards):
                if not isinstance(raw, dict) or raw.get("category") == "treasure":
                    continue
                matches = [
                    entry
                    for entry in candidates
                    if str(entry.get("id")) not in used
                    and self._reward_atom_matches(
                        entry, str(raw.get("category") or ""), class_text
                    )
                ]
                if not matches:
                    continue
                matches.sort(
                    key=lambda entry: (
                        -self._reward_theme_score(entry, theme),
                        hashlib.sha256(
                            f"{seed}|{level.get('level_index')}|{index}|{entry['id']}".encode()
                        ).hexdigest(),
                    )
                )
                selected = matches[0]
                used.add(str(selected["id"]))
                filters = dict(selected.get("filters_json") or {})
                rules = dict(selected.get("rules_json") or {})
                raw.update(
                    {
                        "name": selected["name"],
                        "category": filters.get("category", raw.get("category")),
                        "source_kind": "official",
                        "source_record_id": selected.get("source_record_id"),
                        "compendium_entry_id": selected["id"],
                        "rarity": filters.get("rarity"),
                        "description": selected.get("description"),
                        "value_gp": max(
                            1,
                            int(rules.get("price_cp", 0)) // 100
                            or int(raw.get("value_gp", 1)),
                        ),
                    }
                )

    @staticmethod
    def _reward_theme_score(entry: dict[str, Any], theme: str) -> int:
        """Prefer official atoms that reinforce the generated site's theme."""

        keywords = {
            "sahuagin": (
                "水下",
                "水上",
                "水手",
                "水元素",
                "净水",
                "无尽水",
                "水袋",
                "海",
                "鱼",
                "珍珠",
                "三叉戟",
                "潮",
                "珊瑚",
                "游泳",
            ),
            "fire": ("火", "炎", "焰", "熔", "岩浆", "灰烬"),
            "frost": ("冰", "霜", "寒", "雪", "极地"),
            "undead": ("亡灵", "死灵", "骸骨", "幽魂", "坟", "墓"),
            "aberration": ("心灵", "异界", "触须", "星界", "畸变"),
            "cult": ("邪教", "仪式", "圣徽", "祭", "诅咒"),
            "goblin": ("地精", "陷阱", "伏击", "洞穴"),
        }.get(theme, ())
        if not keywords:
            return 0
        text = " ".join(
            (
                str(entry.get("name") or ""),
                str(entry.get("description") or ""),
                " ".join(str(tag) for tag in entry.get("tags", [])),
            )
        )
        name = str(entry.get("name") or "")
        return sum(5 if keyword in name else 1 for keyword in keywords if keyword in text)

    @staticmethod
    def _reward_atom_matches(
        entry: dict[str, Any], planned_category: str, class_text: str
    ) -> bool:
        filters = dict(entry.get("filters_json") or {})
        category = str(filters.get("category") or "")
        item_function = str(filters.get("item_function") or "")
        if planned_category == "spell_scroll":
            return category == "scroll" or "卷轴" in str(entry.get("name") or "")
        if planned_category == "consumable":
            return category == "potion" or item_function == "consumable"
        if planned_category == "adventuring_gear":
            return entry.get("entry_type") == "item"
        if planned_category == "wondrous":
            return category in {"wondrous", "ring", "rod", "staff", "wand"}
        if planned_category == "equipment":
            if any(name in class_text for name in ("法师", "术士", "魔契师")):
                return category in {"wand", "staff", "ring", "wondrous", "scroll"}
            return category in {"weapon", "armor", "shield", "wondrous"}
        return False

    def confirm(
        self, campaign_id: str, preview: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        self._validate_preview(preview)
        # A generation request is intentionally idempotent.  The unique
        # constraint is the final arbiter when two DM tabs submit the same
        # request at once; retry the losing transaction and return the row
        # created by the winner instead of surfacing an IntegrityError.
        # The app is local-first and normally runs as one process.  A
        # per-campaign lock prevents duplicate path/RegionMap nodes when two
        # browser tabs create distinct sites simultaneously.  Optimistic SQL
        # checks below remain the cross-process safety net.
        with _generation_lock(self.engine, campaign_id):
            for attempt in range(5):
                try:
                    return self._confirm_once(campaign_id, preview, request_id=request_id)
                except _ConcurrentRegionUpdate:
                    time.sleep(0.01 * (attempt + 1))
                    continue
                except IntegrityError:
                    existing = self._get_by_request_id(campaign_id, request_id)
                    if existing is not None:
                        return self.get(campaign_id, existing.id)
                    if attempt == 4:
                        raise
                    time.sleep(0.01 * (attempt + 1))
                except OperationalError as exc:
                    message = str(exc).lower()
                    if "locked" not in message and "busy" not in message:
                        raise
                    existing = self._get_by_request_id(campaign_id, request_id)
                    if existing is not None:
                        return self.get(campaign_id, existing.id)
                    if attempt == 4:
                        raise
                    time.sleep(0.01 * (attempt + 1))
        raise ValueError("region map changed while generating site; please retry")

    def _confirm_once(
        self, campaign_id: str, preview: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            existing = session.scalar(
                select(AdventureSite).where(
                    AdventureSite.campaign_id == campaign_id,
                    AdventureSite.generation_request_id == request_id,
                )
            )
            if existing is not None:
                existing_id = existing.id
                session.rollback()
                return self.get(campaign_id, existing_id)
            parent: Location | None = None
            for depth, name in enumerate(preview["region"]["path"], 1):
                parent = self._find_or_create_location(
                    session, campaign_id, str(name), parent, min(depth, 10)
                )
            assert parent is not None
            region_map = session.scalar(
                select(RegionMap).where(
                    RegionMap.campaign_id == campaign_id,
                    RegionMap.location_id == parent.id,
                )
            )
            if region_map is None:
                seed = int(preview["site"]["seed"])
                region_map = RegionMap(
                    campaign_id=campaign_id,
                    location_id=parent.id,
                    name=f"{parent.name}区域地图",
                    seed=seed,
                    map_json={"pois": [], "roads": [], "schema_version": "1.0"},
                )
                session.add(region_map)
                session.flush()
            site_location = Location(
                campaign_id=campaign_id,
                name=str(preview["site"]["name"]),
                parent_location_id=parent.id,
                depth=min(int(parent.depth) + 1, 10),
                description=str(preview["site"]["brief"]),
            )
            session.add(site_location)
            session.flush()
            position = self._next_position(region_map, int(preview["site"]["seed"]))
            site = AdventureSite(
                campaign_id=campaign_id,
                region_map_id=region_map.id,
                location_id=site_location.id,
                site_type=str(preview["site"]["site_type"]),
                name=str(preview["site"]["name"]),
                brief=str(preview["site"]["brief"]),
                theme=str(preview["site"]["theme"]),
                seed=int(preview["site"]["seed"]),
                maximum_levels=int(preview["site"]["maximum_levels"]),
                party_level=int(preview["site"]["party_level"]),
                party_size=int(preview["site"]["party_size"]),
                generation_parameters=dict(preview["site"]["generation_parameters"]),
                map_position=position,
                generation_request_id=request_id,
            )
            session.add(site)
            session.flush()
            region_data = dict(region_map.map_json)
            raw_pois = region_data.get("pois", [])
            raw_roads = region_data.get("roads", [])
            pois = list(raw_pois) if isinstance(raw_pois, list) else []
            roads = list(raw_roads) if isinstance(raw_roads, list) else []
            if pois:
                previous = pois[-1]
                roads.append(
                    {
                        "from": {"row": previous["row"], "col": previous["col"]},
                        "to": position,
                        "kind": "district_road",
                    }
                )
            pois.append(
                {
                    "site_id": site.id,
                    "location_id": site_location.id,
                    "name": site.name,
                    "site_type": site.site_type,
                    **position,
                }
            )
            region_data["pois"] = pois
            region_data["roads"] = roads
            # Avoid a silent lost update when two site generations target the
            # same region map.  SQLite serializes the write, while the
            # version predicate also protects other SQL backends.
            result = session.execute(
                update(RegionMap)
                .where(
                    RegionMap.id == region_map.id,
                    RegionMap.version == int(region_map.version),
                )
                .values(map_json=region_data, version=int(region_map.version) + 1)
            )
            if getattr(result, "rowcount", 0) != 1:
                raise _ConcurrentRegionUpdate
            for level_data in preview["levels"]:
                raw_cells = list(level_data["layout"]["cells"])
                scene_cells = [
                    {
                        **dict(cell),
                        "row": int(cell["row"]) + 1,
                        "col": int(cell["col"]) + 1,
                    }
                    for cell in raw_cells
                ]
                cell_lookup = {(int(cell["row"]), int(cell["col"])): cell for cell in raw_cells}
                level_location = Location(
                    campaign_id=campaign_id,
                    name=str(level_data["name"]),
                    parent_location_id=site_location.id,
                    depth=min(int(site_location.depth) + 1, 10),
                    description=str(level_data["description"]),
                )
                session.add(level_location)
                session.flush()
                level = SiteLevel(
                    site_id=site.id,
                    location_id=level_location.id,
                    level_index=int(level_data["level_index"]),
                    name=str(level_data["name"]),
                    description=str(level_data["description"]),
                    difficulty=str(level_data["difficulty"]),
                    encounter_budget_xp=int(level_data["encounter_budget_xp"]),
                    reward_budget_gp=int(level_data["reward_budget_gp"]),
                    layout_json=dict(level_data["layout"]),
                    generation_json={
                        "monster_plan": level_data["monster_plan"],
                        "npc_plan": level_data.get("npc_plan", []),
                        "reward_plan": level_data["reward_plan"],
                        "quality": level_data.get("quality", {}),
                        "visual_theme": level_data.get("visual_theme", {}),
                    },
                )
                session.add(level)
                session.flush()
                scene = Scene(
                    campaign_id=campaign_id,
                    name=f"{site.name} · {level.name}",
                    location_id=level_location.id,
                    description=level.description,
                    status="draft",
                    notes=f"由{site.name}楼层地图自动生成；与站点楼层共享同一网格。",
                )
                session.add(scene)
                session.flush()
                session.add(
                    SceneGrid(
                        scene_id=scene.id,
                        width=int(level_data["layout"]["width"]),
                        height=int(level_data["layout"]["height"]),
                        cell_size_ft=int(level_data["layout"]["cell_size_ft"]),
                        mode="exploration",
                        public_description=str(level_data["description"]),
                        dm_description=(
                            f"{level.name}；遭遇预算 {level.encounter_budget_xp} XP；"
                            f"奖励规划 {level.reward_budget_gp} gp。"
                        ),
                        layers_json={
                            "cells": scene_cells,
                            "site_id": site.id,
                            "site_level_index": level.level_index,
                            "shared_site_grid": True,
                            "coordinate_system": "one_based",
                        },
                    )
                )
                room_locations: dict[int, Location] = {}
                room_spawn_cells: dict[int, list[tuple[int, int]]] = {}
                for room_data in level_data["rooms"]:
                    room_location = Location(
                        campaign_id=campaign_id,
                        name=str(room_data["name"]),
                        parent_location_id=level_location.id,
                        depth=min(int(level_location.depth) + 1, 10),
                        description=str(room_data["description"]),
                        interactive_objects=list(room_data["interactive_objects"]),
                    )
                    session.add(room_location)
                    session.flush()
                    session.add(
                        SiteRoom(
                            site_level_id=level.id,
                            location_id=room_location.id,
                            room_index=int(room_data["room_index"]),
                            name=str(room_data["name"]),
                            room_type=str(room_data["room_type"]),
                            description=str(room_data["description"]),
                            bounds_json=dict(room_data["bounds"]),
                            encounter_json={
                                "monsters": [
                                    item
                                    for item in level_data.get("monster_plan", [])
                                    if int(item.get("room_index", 0))
                                    == int(room_data["room_index"])
                                ],
                                "npcs": [
                                    item
                                    for item in level_data.get("npc_plan", [])
                                    if int(item.get("room_index", 0))
                                    == int(room_data["room_index"])
                                ],
                            },
                            reward_json={
                                "items": [
                                    item
                                    for item in level_data.get("reward_plan", [])
                                    if int(item.get("room_index", 0))
                                    == int(room_data["room_index"])
                                ]
                            },
                            interactive_objects=list(room_data["interactive_objects"]),
                        )
                    )
                    room_locations[int(room_data["room_index"])] = room_location
                    bounds = dict(room_data["bounds"])
                    room_spawn_cells[int(room_data["room_index"])] = [
                        (row + 1, col + 1)
                        for row in range(
                            int(bounds["row"]),
                            int(bounds["row"]) + int(bounds["height"]),
                        )
                        for col in range(
                            int(bounds["col"]),
                            int(bounds["col"]) + int(bounds["width"]),
                        )
                        if cell_lookup.get((row, col), {}).get("kind") in {"floor", "room"}
                    ]
                occupied_cells: set[tuple[int, int]] = set()
                for connector in level_data["connectors"]:
                    session.add(
                        SiteConnector(
                            site_id=site.id,
                            from_level_index=int(level_data["level_index"]),
                            from_room_index=connector.get("from_room_index"),
                            to_level_index=int(
                                connector.get("to_level_index", level_data["level_index"])
                            ),
                            to_room_index=connector.get("to_room_index"),
                            connector_type=str(connector["connector_type"]),
                            label=str(connector["label"]),
                            state=str(connector["state"]),
                            position_json=dict(connector["position"]),
                        )
                    )
                for monster_data in level_data.get("monster_plan", []):
                    room_index = int(monster_data.get("room_index", 1))
                    target_location = room_locations.get(room_index, level_location)
                    xp_each = max(25, int(monster_data.get("xp_each", 25)))
                    quantity = max(1, min(12, int(monster_data.get("quantity", 1))))
                    monster_name = str(monster_data["name"])
                    official_template = next(
                        (
                            entry
                            for entry in self.official_catalog.search(
                                entry_type="monster", text=monster_name
                            )
                            if monster_name.lower() in str(entry["name"]).lower()
                        ),
                        None,
                    )
                    official_rules = (
                        dict(official_template.get("rules_json") or {}) if official_template else {}
                    )
                    for copy_index in range(quantity):
                        hp = max(
                            5,
                            int(official_rules.get("hp", round((xp_each**0.5) * 1.3))),
                        )
                        monster = MonsterInstance(
                            campaign_id=campaign_id,
                            name=(
                                str(monster_data["name"])
                                if quantity == 1
                                else f"{monster_data['name']} {copy_index + 1}"
                            ),
                            source_name=(
                                str(official_template.get("source_name"))
                                if official_template
                                else str(monster_data.get("source", "generated_plan"))
                            ),
                            armor_class=int(
                                official_rules.get(
                                    "armor_class",
                                    min(22, 12 + int(site.party_level) // 4),
                                )
                            ),
                            hp=hp,
                            max_hp=hp,
                            speed=int(official_rules.get("speed", 30)),
                            ability_scores=dict(
                                official_rules.get("ability_scores")
                                or {
                                    "strength": 12,
                                    "dexterity": 12,
                                    "constitution": 12,
                                    "intelligence": 10,
                                    "wisdom": 10,
                                    "charisma": 8,
                                }
                            ),
                            actions=list(
                                official_rules.get("actions")
                                or [
                                    {
                                        "name": "基础攻击",
                                        "action_type": "action",
                                        "range_ft": 5,
                                        "damage": (f"1d8+{max(1, int(site.party_level) // 4)}"),
                                        "damage_type": "由图鉴模板决定",
                                    }
                                ]
                            ),
                            notes=(
                                f"由站点生成器分配至房间 {room_index}：{target_location.name}。"
                                + (
                                    f"已绑定官方图鉴：{official_template['name']}。"
                                    if official_template
                                    else "未检索到同名官方模板，使用受控后备数值。"
                                )
                            ),
                        )
                        session.add(monster)
                        session.flush()
                        session.add(
                            SceneParticipant(
                                scene_id=scene.id,
                                entity_type="monster",
                                entity_id=monster.id,
                                role="present",
                                visible=False,
                                notes=f"初始位于{target_location.name}；探索到房间后揭示。",
                            )
                        )
                        token_row, token_col = _next_spawn(
                            room_index, room_spawn_cells, occupied_cells, scene_cells
                        )
                        session.add(
                            SceneToken(
                                scene_id=scene.id,
                                entity_type="monster",
                                entity_id=monster.id,
                                label=monster.name,
                                row=token_row,
                                col=token_col,
                                visible=False,
                                metadata_json={
                                    "site_id": site.id,
                                    "site_level": level.level_index,
                                    "room_index": room_index,
                                    "generated_from": "site_generation",
                                },
                            )
                        )
                for npc_data in level_data.get("npc_plan", []):
                    room_index = int(npc_data.get("room_index", 1))
                    target_location = room_locations.get(room_index, level_location)
                    npc = NPC(
                        campaign_id=campaign_id,
                        name=str(npc_data["name"]),
                        description=f"{site.name}中的{npc_data.get('role', '地点人物')}。",
                        attitude=str(npc_data.get("attitude", "neutral")),
                        location_id=target_location.id,
                        hp=max(4, 4 + int(site.party_level)),
                        max_hp=max(4, 4 + int(site.party_level)),
                        armor_class=10,
                    )
                    session.add(npc)
                    session.flush()
                    session.add(
                        SceneParticipant(
                            scene_id=scene.id,
                            entity_type="npc",
                            entity_id=npc.id,
                            role="present",
                            visible=False,
                            notes=f"初始位于{target_location.name}；探索到房间后揭示。",
                        )
                    )
                    token_row, token_col = _next_spawn(
                        room_index, room_spawn_cells, occupied_cells, scene_cells
                    )
                    session.add(
                        SceneToken(
                            scene_id=scene.id,
                            entity_type="npc",
                            entity_id=npc.id,
                            label=npc.name,
                            row=token_row,
                            col=token_col,
                            visible=False,
                            metadata_json={
                                "site_id": site.id,
                                "site_level": level.level_index,
                                "room_index": room_index,
                                "generated_from": "site_generation",
                            },
                        )
                    )
                for reward_data in level_data.get("reward_plan", []):
                    room_index = int(reward_data.get("room_index", 1))
                    target_location = room_locations.get(room_index, level_location)
                    value_gp = max(0, int(reward_data.get("value_gp", 0)))
                    world_item = WorldItem(
                        campaign_id=campaign_id,
                        name=str(reward_data["name"]),
                        description=(
                            str(reward_data.get("description") or "")
                            or f"由地下城奖励预算生成，推荐队伍等级 {site.party_level}。"
                        ),
                        category=str(reward_data.get("category", "treasure")),
                        quantity=max(1, int(reward_data.get("quantity", 1))),
                        unit_weight_lb=0,
                        price_cp=value_gp * 100,
                        source_label=(
                            "official"
                            if reward_data.get("source_kind") == "official"
                            else "ai_generated"
                        ),
                        location_id=target_location.id,
                        is_hidden=True,
                        metadata_json={
                            "site_id": site.id,
                            "site_level": level.level_index,
                            "room_index": room_index,
                            "original": reward_data.get("source_kind") != "official",
                            "source_kind": reward_data.get("source_kind"),
                            "source_record_id": reward_data.get("source_record_id"),
                            "compendium_entry_id": reward_data.get(
                                "compendium_entry_id"
                            ),
                            "rules_validated_budget": True,
                        },
                    )
                    session.add(world_item)
                    session.flush()
                    object_row, object_col = _next_spawn(
                        room_index, room_spawn_cells, occupied_cells, scene_cells
                    )
                    session.add(
                        SceneObject(
                            scene_id=scene.id,
                            object_type="treasure",
                            label=world_item.name,
                            row=object_row,
                            col=object_col,
                            visibility="hidden",
                            interaction_json={
                                "action": "collect_world_item",
                                "world_item_id": world_item.id,
                            },
                            metadata_json={
                                "world_item_id": world_item.id,
                                "site_id": site.id,
                                "site_level": level.level_index,
                                "room_index": room_index,
                                "generated_from": "site_generation",
                            },
                        )
                    )
            session.add(
                AuditLog(
                    campaign_id=campaign_id,
                    actor=self.actor,
                    action="generate",
                    entity_type="adventure_site",
                    entity_id=site.id,
                    before_json=None,
                    after_json={"name": site.name, "levels": len(preview["levels"])},
                    request_id=request_id,
                )
            )
            session.flush()
            site_id = site.id
        return self.get(campaign_id, site_id)

    def delete(
        self,
        campaign_id: str,
        site_id: str,
        *,
        expected_version: int,
        request_id: str = "unknown",
    ) -> dict[str, int]:
        """Delete a generated site and all of its managed hierarchy atomically.

        Generic Location deletion uses ``SET NULL`` for parent links, which is
        correct for ordinary world locations but would orphan generated floor
        and room nodes.  This operation therefore collects the complete
        descendant tree first, removes generated scenes/grids and site rows,
        then removes all managed Locations in one transaction.
        """

        with Session(self.engine) as session, session.begin():
            site = session.scalar(
                select(AdventureSite).where(
                    AdventureSite.id == site_id,
                    AdventureSite.campaign_id == campaign_id,
                )
            )
            if site is None:
                raise StateNotFoundError("adventure site not found")
            if int(site.version) != expected_version:
                raise VersionConflict(
                    "adventure_site", site_id, expected_version, int(site.version)
                )
            region = session.get(RegionMap, site.region_map_id)
            if region is not None:
                region_data = dict(region.map_json or {})
                raw_pois = region_data.get("pois", [])
                raw_roads = region_data.get("roads", [])
                if not isinstance(raw_pois, list):
                    raw_pois = []
                if not isinstance(raw_roads, list):
                    raw_roads = []
                pois = [poi for poi in raw_pois if isinstance(poi, dict)]
                removed_points = {
                    (int(poi["row"]), int(poi["col"]))
                    for poi in pois
                    if poi.get("site_id") == site.id and "row" in poi and "col" in poi
                }
                pois = [poi for poi in pois if poi.get("site_id") != site.id]
                roads = [road for road in raw_roads if isinstance(road, dict)]

                def endpoint(road: dict[str, Any], key: str) -> tuple[int, int] | None:
                    point = road.get(key)
                    if not isinstance(point, dict) or "row" not in point or "col" not in point:
                        return None
                    return int(point["row"]), int(point["col"])

                roads = [
                    road
                    for road in roads
                    if endpoint(road, "from") not in removed_points
                    and endpoint(road, "to") not in removed_points
                ]
                region_data["pois"] = pois
                region_data["roads"] = roads
                result = session.execute(
                    update(RegionMap)
                    .where(RegionMap.id == region.id, RegionMap.version == int(region.version))
                    .values(map_json=region_data, version=int(region.version) + 1)
                )
                if getattr(result, "rowcount", 0) != 1:
                    raise VersionConflict(
                        "region_map", region.id, int(region.version), int(region.version) + 1
                    )

            level_ids = list(
                session.scalars(select(SiteLevel.id).where(SiteLevel.site_id == site.id))
            )
            managed_location_ids = {site.location_id}
            if level_ids:
                managed_location_ids.update(
                    session.scalars(
                        select(SiteLevel.location_id).where(SiteLevel.id.in_(level_ids))
                    )
                )
                managed_location_ids.update(
                    session.scalars(
                        select(SiteRoom.location_id).where(SiteRoom.site_level_id.in_(level_ids))
                    )
                )

            # Include any user-created descendants below a generated room or
            # floor so that deleting the site cannot leave a detached subtree.
            pending = list(managed_location_ids)
            while pending:
                descendants = list(
                    session.scalars(
                        select(Location.id).where(
                            Location.campaign_id == campaign_id,
                            Location.parent_location_id.in_(pending),
                        )
                    )
                )
                fresh = [item for item in descendants if item not in managed_location_ids]
                if not fresh:
                    break
                managed_location_ids.update(fresh)
                pending = fresh

            scene_ids = list(
                session.scalars(
                    select(Scene.id).where(
                        Scene.campaign_id == campaign_id,
                        Scene.location_id.in_(managed_location_ids),
                    )
                )
            )
            if scene_ids:
                session.execute(sa_delete(Scene).where(Scene.id.in_(scene_ids)))
            # SiteLevel/SiteRoom/SiteConnector rows cascade from the site.
            session.delete(site)
            session.flush()
            session.execute(
                sa_delete(Location).where(
                    Location.campaign_id == campaign_id,
                    Location.id.in_(managed_location_ids),
                )
            )
            session.add(
                AuditLog(
                    campaign_id=campaign_id,
                    actor=self.actor,
                    action="delete",
                    entity_type="adventure_site",
                    entity_id=site_id,
                    before_json={
                        "name": site.name,
                        "levels": len(level_ids),
                        "locations": len(managed_location_ids),
                        "scenes": len(scene_ids),
                    },
                    after_json=None,
                    request_id=request_id,
                )
            )
            return {
                "levels": len(level_ids),
                "locations": len(managed_location_ids),
                "scenes": len(scene_ids),
            }

    def list_region_maps(self, campaign_id: str) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            rows = session.scalars(
                select(RegionMap)
                .where(RegionMap.campaign_id == campaign_id)
                .order_by(RegionMap.created_at, RegionMap.id)
            )
            return tuple(serialize(row) for row in rows)

    def list_sites(self, campaign_id: str) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            self._campaign(session, campaign_id)
            rows = session.scalars(
                select(AdventureSite)
                .where(AdventureSite.campaign_id == campaign_id)
                .order_by(AdventureSite.created_at, AdventureSite.id)
            )
            return tuple(serialize(row) for row in rows)

    def repair_generated_scene_atoms(self, campaign_id: str) -> dict[str, int]:
        """Idempotently upgrade sites created before scene tokens were persisted."""

        repaired = {"grids": 0, "tokens": 0, "treasures": 0}
        with Session(self.engine) as session, session.begin():
            self._campaign(session, campaign_id)
            levels = list(
                session.execute(
                    select(SiteLevel, AdventureSite)
                    .join(AdventureSite, SiteLevel.site_id == AdventureSite.id)
                    .where(AdventureSite.campaign_id == campaign_id)
                )
            )
            for level, site in levels:
                scene = session.scalar(
                    select(Scene).where(
                        Scene.campaign_id == campaign_id,
                        Scene.location_id == level.location_id,
                    )
                )
                if scene is None:
                    continue
                grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene.id))
                if grid is None:
                    continue
                layers = dict(grid.layers_json or {})
                raw_cells = layers.get("cells", [])
                cells = (
                    [dict(cell) for cell in raw_cells if isinstance(cell, dict)]
                    if isinstance(raw_cells, list)
                    else []
                )
                if cells and layers.get("coordinate_system") != "one_based":
                    cells = [
                        {
                            **cell,
                            "row": int(cell.get("row", 0)) + 1,
                            "col": int(cell.get("col", 0)) + 1,
                        }
                        for cell in cells
                    ]
                    layers["cells"] = cells
                    layers["coordinate_system"] = "one_based"
                    grid.layers_json = layers
                    grid.version += 1
                    repaired["grids"] += 1
                rooms = list(
                    session.scalars(select(SiteRoom).where(SiteRoom.site_level_id == level.id))
                )
                room_by_index = {room.room_index: room for room in rooms}
                room_by_location = {room.location_id: room.room_index for room in rooms}
                room_spawn_cells: dict[int, list[tuple[int, int]]] = {}
                cell_lookup = {
                    (int(cell.get("row", 0)), int(cell.get("col", 0))): cell for cell in cells
                }
                for room in rooms:
                    bounds = dict(room.bounds_json)
                    room_spawn_cells[room.room_index] = [
                        (row, col)
                        for row in range(
                            int(bounds["row"]) + 1,
                            int(bounds["row"]) + int(bounds["height"]) + 1,
                        )
                        for col in range(
                            int(bounds["col"]) + 1,
                            int(bounds["col"]) + int(bounds["width"]) + 1,
                        )
                        if cell_lookup.get((row, col), {}).get("kind") in {"floor", "room"}
                    ]
                tokens = list(
                    session.scalars(select(SceneToken).where(SceneToken.scene_id == scene.id))
                )
                occupied = {(token.row, token.col) for token in tokens}
                token_entities = {(token.entity_type, token.entity_id) for token in tokens}
                participants = list(
                    session.scalars(
                        select(SceneParticipant).where(SceneParticipant.scene_id == scene.id)
                    )
                )
                if not participants:
                    generation = dict(level.generation_json or {})
                    raw_plan = generation.get("monster_plan", [])
                    monster_plan = raw_plan if isinstance(raw_plan, list) else []
                    for raw_monster in monster_plan:
                        if not isinstance(raw_monster, dict):
                            continue
                        room_index = _safe_int(raw_monster.get("room_index"), 1)
                        target_room = room_by_index.get(room_index)
                        xp_each = max(25, _safe_int(raw_monster.get("xp_each"), 25))
                        quantity = max(1, min(12, _safe_int(raw_monster.get("quantity"), 1)))
                        for copy_index in range(quantity):
                            hp = max(5, round((xp_each**0.5) * 1.3))
                            base_name = str(raw_monster.get("name") or "未命名怪物")
                            monster = MonsterInstance(
                                campaign_id=campaign_id,
                                name=(
                                    base_name if quantity == 1 else f"{base_name} {copy_index + 1}"
                                ),
                                source_name=str(raw_monster.get("source") or "generated_plan"),
                                armor_class=min(22, 12 + int(site.party_level) // 4),
                                hp=hp,
                                max_hp=hp,
                                speed=30,
                                ability_scores={
                                    "strength": 12,
                                    "dexterity": 12,
                                    "constitution": 12,
                                    "intelligence": 10,
                                    "wisdom": 10,
                                    "charisma": 8,
                                },
                                actions=[
                                    {
                                        "name": "基础攻击",
                                        "action_type": "action",
                                        "range_ft": 5,
                                        "damage": (f"1d8+{max(1, int(site.party_level) // 4)}"),
                                    }
                                ],
                                notes=(
                                    f"由旧版站点计划回填；房间 {room_index}："
                                    f"{target_room.name if target_room else level.name}。"
                                ),
                            )
                            session.add(monster)
                            session.flush()
                            participant = SceneParticipant(
                                scene_id=scene.id,
                                entity_type="monster",
                                entity_id=monster.id,
                                role="present",
                                visible=False,
                                notes="由旧版站点计划幂等回填；探索后揭示。",
                            )
                            session.add(participant)
                            participants.append(participant)
                for participant in participants:
                    key = (participant.entity_type, participant.entity_id)
                    if key in token_entities or participant.entity_id is None:
                        continue
                    room_index = min(room_by_index, default=1)
                    label = participant.entity_type
                    if participant.entity_type == "monster":
                        monster_entity = session.get(MonsterInstance, participant.entity_id)
                        if monster_entity is None:
                            continue
                        label = monster_entity.name
                        match = re.search(r"房间\s*(\d+)", monster_entity.notes or "")
                        if match:
                            room_index = int(match.group(1))
                    elif participant.entity_type == "npc":
                        npc_entity = session.get(NPC, participant.entity_id)
                        if npc_entity is None:
                            continue
                        label = npc_entity.name
                        room_index = room_by_location.get(npc_entity.location_id or "", room_index)
                    else:
                        continue
                    row, col = _next_spawn(room_index, room_spawn_cells, occupied, cells)
                    session.add(
                        SceneToken(
                            scene_id=scene.id,
                            entity_type=participant.entity_type,
                            entity_id=participant.entity_id,
                            label=label,
                            row=row,
                            col=col,
                            visible=participant.visible,
                            metadata_json={
                                "site_id": site.id,
                                "site_level": level.level_index,
                                "room_index": room_index,
                                "generated_from": "site_generation",
                                "backfilled": True,
                            },
                        )
                    )
                    repaired["tokens"] += 1
                existing_item_ids = {
                    str(obj.metadata_json.get("world_item_id"))
                    for obj in session.scalars(
                        select(SceneObject).where(SceneObject.scene_id == scene.id)
                    )
                    if obj.metadata_json.get("world_item_id")
                }
                room_location_ids = set(room_by_location)
                rewards = list(
                    session.scalars(
                        select(WorldItem).where(
                            WorldItem.campaign_id == campaign_id,
                            WorldItem.location_id.in_(room_location_ids),
                        )
                    )
                )
                if not rewards:
                    generation = dict(level.generation_json or {})
                    raw_rewards = generation.get("reward_plan", [])
                    reward_plan = raw_rewards if isinstance(raw_rewards, list) else []
                    for raw_reward in reward_plan:
                        if not isinstance(raw_reward, dict):
                            continue
                        room_index = _safe_int(raw_reward.get("room_index"), 1)
                        target_room = room_by_index.get(room_index)
                        item = WorldItem(
                            campaign_id=campaign_id,
                            name=str(raw_reward.get("name") or "未命名战利品"),
                            description="由旧版地下城奖励计划回填。",
                            category=str(raw_reward.get("category") or "treasure"),
                            quantity=max(1, _safe_int(raw_reward.get("quantity"), 1)),
                            unit_weight_lb=0,
                            price_cp=max(0, _safe_int(raw_reward.get("value_gp"), 0) * 100),
                            source_label="ai_generated",
                            location_id=(
                                target_room.location_id
                                if target_room is not None
                                else level.location_id
                            ),
                            is_hidden=True,
                            metadata_json={
                                "site_id": site.id,
                                "site_level": level.level_index,
                                "room_index": room_index,
                                "original": True,
                                "backfilled": True,
                            },
                        )
                        session.add(item)
                        session.flush()
                        rewards.append(item)
                for item in rewards:
                    metadata = dict(item.metadata_json or {})
                    if (
                        item.id in existing_item_ids
                        or metadata.get("site_id") != site.id
                        or _safe_int(metadata.get("site_level"), -1) != level.level_index
                    ):
                        continue
                    room_index = _safe_int(
                        metadata.get("room_index"),
                        room_by_location.get(item.location_id or "", 1),
                    )
                    row, col = _next_spawn(room_index, room_spawn_cells, occupied, cells)
                    session.add(
                        SceneObject(
                            scene_id=scene.id,
                            object_type="treasure",
                            label=item.name,
                            row=row,
                            col=col,
                            visibility="hidden",
                            interaction_json={
                                "action": "collect_world_item",
                                "world_item_id": item.id,
                            },
                            metadata_json={
                                **metadata,
                                "world_item_id": item.id,
                                "generated_from": "site_generation",
                                "backfilled": True,
                            },
                        )
                    )
                    repaired["treasures"] += 1
            session.add(
                AuditLog(
                    campaign_id=campaign_id,
                    actor=self.actor,
                    action="repair",
                    entity_type="adventure_site",
                    entity_id=None,
                    before_json=None,
                    after_json=repaired,
                    request_id="site-scene-atom-backfill-v1",
                )
            )
        return repaired

    def get(self, campaign_id: str, site_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            site = session.get(AdventureSite, site_id)
            if site is None or site.campaign_id != campaign_id:
                raise StateNotFoundError("adventure site not found")
            region = session.get(RegionMap, site.region_map_id)
            levels = list(
                session.scalars(
                    select(SiteLevel)
                    .where(SiteLevel.site_id == site.id)
                    .order_by(SiteLevel.level_index)
                )
            )
            connectors = list(
                session.scalars(
                    select(SiteConnector)
                    .where(SiteConnector.site_id == site.id)
                    .order_by(SiteConnector.from_level_index, SiteConnector.created_at)
                )
            )
            return {
                **serialize(site),
                "region_map": serialize(region) if region else None,
                "levels": [
                    {
                        **serialize(level),
                        "layout": level.layout_json,
                        "monster_plan": level.generation_json.get("monster_plan", []),
                        "npc_plan": level.generation_json.get("npc_plan", []),
                        "reward_plan": level.generation_json.get("reward_plan", []),
                        "quality": level.generation_json.get("quality", {}),
                        "visual_theme": level.generation_json.get("visual_theme", {}),
                        "rooms": [
                            serialize(room)
                            for room in session.scalars(
                                select(SiteRoom)
                                .where(SiteRoom.site_level_id == level.id)
                                .order_by(SiteRoom.room_index)
                            )
                        ],
                        "connectors": [
                            serialize(connector)
                            for connector in connectors
                            if connector.from_level_index == level.level_index
                        ],
                    }
                    for level in levels
                ],
            }

    @staticmethod
    def _validate_preview(preview: dict[str, Any]) -> None:
        if not isinstance(preview, dict) or preview.get("schema_version") != "1.0":
            raise ValueError("unsupported site preview schema")
        site = preview.get("site")
        if not isinstance(site, dict):
            raise ValueError("site preview must contain site metadata")
        levels = preview.get("levels")
        if not isinstance(levels, list) or not levels:
            raise ValueError("site preview must contain levels")
        try:
            maximum_levels = int(site["maximum_levels"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("site maximum_levels is invalid") from exc
        if maximum_levels != len(levels):
            raise ValueError("site maximum_levels must match generated levels")
        if not 1 <= maximum_levels <= 20:
            raise ValueError("site maximum_levels must be between 1 and 20")
        previous_difficulty = -1
        previous_reward = -1
        level_indexes: set[int] = set()
        room_indexes_by_level: dict[int, set[int]] = {}
        for expected, level in enumerate(levels, 1):
            if not isinstance(level, dict):
                raise ValueError(f"level {expected} is invalid")
            try:
                level_index = int(level["level_index"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"level {expected} index is invalid") from exc
            if level_index != expected or level_index in level_indexes:
                raise ValueError("site levels must be sequential")
            level_indexes.add(level_index)
            try:
                difficulty = ("low", "moderate", "high").index(str(level["difficulty"]))
                reward = int(level["reward_budget_gp"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"level {expected} difficulty or reward is invalid") from exc
            if difficulty < previous_difficulty:
                raise ValueError("difficulty curve cannot decrease")
            if reward < previous_reward:
                raise ValueError("reward curve cannot decrease")
            layout = level.get("layout")
            if not isinstance(layout, dict):
                raise ValueError(f"level {expected} layout is invalid")
            try:
                width = int(layout["width"])
                height = int(layout["height"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"level {expected} layout dimensions are invalid") from exc
            if not 1 <= width <= 100 or not 1 <= height <= 100:
                raise ValueError(f"level {expected} layout dimensions are out of bounds")
            cells = layout.get("cells")
            if not isinstance(cells, list) or not cells:
                raise ValueError(f"level {expected} layout must contain cells")
            coordinates: set[tuple[int, int]] = set()
            cells_by_coordinate: dict[tuple[int, int], dict[str, Any]] = {}
            for cell in cells:
                if not isinstance(cell, dict):
                    raise ValueError(f"level {expected} contains an invalid cell")
                try:
                    point = (int(cell["row"]), int(cell["col"]))
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        f"level {expected} contains an invalid cell coordinate"
                    ) from exc
                if point in coordinates or not (0 <= point[0] < height and 0 <= point[1] < width):
                    raise ValueError(f"level {expected} contains duplicate or out-of-bounds cells")
                coordinates.add(point)
                cells_by_coordinate[point] = cell
            if len(coordinates) != width * height:
                raise ValueError(f"level {expected} layout must define every grid cell")
            rooms = level.get("rooms")
            if not isinstance(rooms, list) or not rooms:
                raise ValueError(f"level {expected} must contain rooms")
            room_indexes: set[int] = set()
            rectangles: list[tuple[int, int, int, int, int]] = []
            for room in rooms:
                if not isinstance(room, dict):
                    raise ValueError(f"level {expected} contains an invalid room")
                try:
                    room_index = int(room["room_index"])
                    bounds = room["bounds"]
                    top, left = int(bounds["row"]), int(bounds["col"])
                    room_width, room_height = int(bounds["width"]), int(bounds["height"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"level {expected} contains an invalid room bounds") from exc
                if room_index in room_indexes or room_index < 1:
                    raise ValueError(f"level {expected} room indexes must be unique and positive")
                if room_width < 1 or room_height < 1:
                    raise ValueError(f"level {expected} room dimensions must be positive")
                bottom, right = top + room_height - 1, left + room_width - 1
                if top < 0 or left < 0 or bottom >= height or right >= width:
                    raise ValueError(f"level {expected} room bounds exceed layout")
                if not any(
                    cells_by_coordinate[(row, col)].get("kind") not in {"wall", "void"}
                    for row in range(top, bottom + 1)
                    for col in range(left, right + 1)
                ):
                    raise ValueError(f"level {expected} room has no walkable cells")
                for old_top, old_left, old_bottom, old_right, _ in rectangles:
                    if (
                        top <= old_bottom
                        and bottom >= old_top
                        and left <= old_right
                        and right >= old_left
                    ):
                        raise ValueError(f"level {expected} rooms must not overlap")
                room_indexes.add(room_index)
                rectangles.append((top, left, bottom, right, room_index))
            room_indexes_by_level[level_index] = room_indexes
            for plan_key in ("monster_plan", "npc_plan", "reward_plan"):
                plan = level.get(plan_key, [])
                if not isinstance(plan, list):
                    raise ValueError(f"level {expected} {plan_key} is invalid")
                for item in plan:
                    if not isinstance(item, dict):
                        raise ValueError(f"level {expected} {plan_key} contains an invalid item")
                    try:
                        target_room = int(item["room_index"])
                        item_name = str(item["name"]).strip()
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ValueError(f"level {expected} {plan_key} item is incomplete") from exc
                    if target_room not in room_indexes or not item_name:
                        raise ValueError(f"level {expected} {plan_key} references an unknown room")
            if not layout_is_connected(dict(layout)):
                raise ValueError(f"level {expected} map is not connected")
            connectors = level.get("connectors")
            if not isinstance(connectors, list):
                raise ValueError(f"level {expected} connectors are invalid")
            for connector in connectors:
                if not isinstance(connector, dict):
                    raise ValueError(f"level {expected} contains an invalid connector")
                try:
                    from_room = int(connector["from_room_index"])
                    to_level = int(connector.get("to_level_index", level_index))
                    _to_room = int(connector["to_room_index"])
                    position = connector["position"]
                    position_point = (int(position["row"]), int(position["col"]))
                    connector_type = str(connector["connector_type"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"level {expected} contains an invalid connector") from exc
                if from_room not in room_indexes:
                    raise ValueError(
                        f"level {expected} connector references an unknown room or level"
                    )
                # Target level may appear later in the preview; defer its room
                # check until all level indexes are known below.
                if not (0 <= position_point[0] < height and 0 <= position_point[1] < width):
                    raise ValueError(f"level {expected} connector position is out of bounds")
                cell = cells_by_coordinate.get(position_point)
                kind = str(cell.get("kind")) if isinstance(cell, dict) else ""
                allowed_kinds = {
                    "door": {"door"},
                    "secret_door": {"door"},
                    "stairs_up": {"stairs"},
                    "stairs_down": {"stairs"},
                    "portal": {"portal", "door"},
                }.get(connector_type)
                if allowed_kinds is None:
                    raise ValueError(f"level {expected} connector type is invalid")
                if kind not in allowed_kinds:
                    raise ValueError(
                        f"level {expected} connector position must point to a {connector_type} cell"
                    )
                if connector_type in {"door", "secret_door"} and to_level != level_index:
                    raise ValueError("doors must connect rooms on the same level")
                if connector_type == "stairs_down" and to_level != level_index + 1:
                    raise ValueError("stairs_down must connect to the next level")
                if connector_type == "stairs_up" and to_level != level_index - 1:
                    raise ValueError("stairs_up must connect to the previous level")
                neighbors = (
                    (position_point[0] + 1, position_point[1]),
                    (position_point[0] - 1, position_point[1]),
                    (position_point[0], position_point[1] + 1),
                    (position_point[0], position_point[1] - 1),
                )
                if (
                    connector_type in {"door", "secret_door"}
                    and sum(
                        cells_by_coordinate.get(point, {}).get("kind") not in {None, "wall", "void"}
                        for point in neighbors
                    )
                    < 2
                ):
                    raise ValueError("door connector must join at least two walkable cells")
            previous_difficulty = difficulty
            previous_reward = reward
        for level in levels:
            level_index = int(level["level_index"])
            for connector in level.get("connectors", []):
                to_level = int(connector.get("to_level_index", level_index))
                to_room = int(connector["to_room_index"])
                if to_level not in room_indexes_by_level:
                    raise ValueError("connector references an unknown target level")
                if to_room not in room_indexes_by_level[to_level]:
                    raise ValueError("connector references an unknown target room")

    def _get_by_request_id(self, campaign_id: str, request_id: str) -> AdventureSite | None:
        with Session(self.engine) as session:
            return session.scalar(
                select(AdventureSite).where(
                    AdventureSite.campaign_id == campaign_id,
                    AdventureSite.generation_request_id == request_id,
                )
            )

    @staticmethod
    def _next_position(region: RegionMap, seed: int) -> dict[str, int]:
        raw_pois = region.map_json.get("pois", [])
        pois = raw_pois if isinstance(raw_pois, list) else []
        occupied = {
            (int(poi["row"]), int(poi["col"]))
            for poi in pois
            if isinstance(poi, dict) and "row" in poi and "col" in poi
        }
        rng = random.Random(seed)
        for _ in range(500):
            point = (rng.randrange(1, region.height - 1), rng.randrange(1, region.width - 1))
            if point not in occupied:
                return {"row": point[0], "col": point[1]}
        raise ValueError("region map has no available point")

    @staticmethod
    def _find_or_create_location(
        session: Session,
        campaign_id: str,
        name: str,
        parent: Location | None,
        depth: int,
    ) -> Location:
        query = select(Location).where(
            Location.campaign_id == campaign_id,
            Location.name == name,
        )
        if parent is None:
            query = query.where(Location.parent_location_id.is_(None))
        else:
            query = query.where(Location.parent_location_id == parent.id)
        location = session.scalar(query)
        if location is None:
            location = Location(
                campaign_id=campaign_id,
                name=name,
                parent_location_id=parent.id if parent else None,
                depth=depth,
                description="区域地图节点",
            )
            session.add(location)
            session.flush()
        return location

    @staticmethod
    def _campaign(session: Session, campaign_id: str) -> Campaign:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            raise StateNotFoundError("campaign not found")
        return campaign
