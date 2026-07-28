from __future__ import annotations

import random
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError
from dnd_dm_assistant.domain.site_generation import generate_site, layout_is_connected
from dnd_dm_assistant.infrastructure.database.campaign_service import serialize
from dnd_dm_assistant.infrastructure.database.models import (
    AdventureSite,
    AuditLog,
    Campaign,
    Location,
    RegionMap,
    Scene,
    SceneGrid,
    SiteConnector,
    SiteLevel,
    SiteRoom,
)


class SiteService:
    def __init__(self, engine: Engine, *, actor: str = "dm") -> None:
        self.engine = engine
        self.actor = actor

    @staticmethod
    def preview(data: dict[str, Any]) -> dict[str, Any]:
        return generate_site(data)

    def confirm(
        self, campaign_id: str, preview: dict[str, Any], *, request_id: str
    ) -> dict[str, Any]:
        self._validate_preview(preview)
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
            region_map.map_json = region_data
            region_map.version += 1
            for level_data in preview["levels"]:
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
                        "reward_plan": level_data["reward_plan"],
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
                            "cells": level_data["layout"]["cells"],
                            "site_id": site.id,
                            "site_level_index": level.level_index,
                            "shared_site_grid": True,
                        },
                    )
                )
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
                            encounter_json={},
                            reward_json={},
                            interactive_objects=list(room_data["interactive_objects"]),
                        )
                    )
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
                        "reward_plan": level.generation_json.get("reward_plan", []),
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
        if preview.get("schema_version") != "1.0":
            raise ValueError("unsupported site preview schema")
        levels = preview.get("levels")
        if not isinstance(levels, list) or not levels:
            raise ValueError("site preview must contain levels")
        previous_difficulty = -1
        previous_reward = -1
        for expected, level in enumerate(levels, 1):
            if int(level["level_index"]) != expected:
                raise ValueError("site levels must be sequential")
            difficulty = ("low", "moderate", "high").index(str(level["difficulty"]))
            if difficulty < previous_difficulty:
                raise ValueError("difficulty curve cannot decrease")
            if int(level["reward_budget_gp"]) < previous_reward:
                raise ValueError("reward curve cannot decrease")
            if not layout_is_connected(dict(level["layout"])):
                raise ValueError(f"level {expected} map is not connected")
            previous_difficulty = difficulty
            previous_reward = int(level["reward_budget_gp"])

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
