from __future__ import annotations

import random
import time
from threading import Lock, RLock
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from dnd_dm_assistant.domain.campaign_state import StateNotFoundError, VersionConflict
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


class _ConcurrentRegionUpdate(RuntimeError):
    """Internal retry signal for an optimistic region-map write."""


_SITE_LOCKS_GUARD = Lock()
_SITE_LOCKS: dict[tuple[str, str], Any] = {}


def _generation_lock(engine: Engine, campaign_id: str) -> Any:
    """Serialize local site writes per campaign without blocking other campaigns."""

    key = (str(engine.url), campaign_id)
    with _SITE_LOCKS_GUARD:
        return _SITE_LOCKS.setdefault(key, RLock())


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
                        "quality": level_data.get("quality", {}),
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
                        "quality": level.generation_json.get("quality", {}),
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
                if point in coordinates or not (
                    0 <= point[0] < height and 0 <= point[1] < width
                ):
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
                if connector_type in {"door", "secret_door"} and sum(
                    cells_by_coordinate.get(point, {}).get("kind") not in {None, "wall", "void"}
                    for point in neighbors
                ) < 2:
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
