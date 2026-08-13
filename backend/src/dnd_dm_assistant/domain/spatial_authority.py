# ruff: noqa: E501
"""Engine-neutral spatial authority ports and deterministic adapters."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from dnd_dm_assistant.domain.exploration import (
    Point,
    cover_between,
    grid_distance_ft,
    line_of_sight,
    movement_cost_ft,
)
from dnd_dm_assistant.domain.rules_kernel_protocol import KernelPosition


@dataclass(frozen=True)
class SpatialEntity:
    entity_id: str
    position: KernelPosition
    size_cells: int = 1
    active: bool = True

    @property
    def footprint(self) -> tuple[Point, ...]:
        return tuple(
            (self.position.row + row, self.position.col + col)
            for row in range(self.size_cells)
            for col in range(self.size_cells)
        )


@dataclass(frozen=True)
class SpatialPathResult:
    legal: bool
    cost_ft: int
    reason: str | None = None


@runtime_checkable
class SpatialAuthority(Protocol):
    """Facts the rules kernel may ask from a scene, never renderer objects."""

    def get_entity_position(self, entity_id: str) -> KernelPosition: ...

    def get_entity_size(self, entity_id: str) -> int: ...

    def get_entity_bounds(self, entity_id: str) -> dict[str, int]: ...

    def distance_between(self, first_id: str, second_id: str) -> int: ...

    def has_line_of_sight(self, first_id: str, second_id: str) -> bool: ...

    def get_cover(self, first_id: str, second_id: str) -> str: ...

    def is_space_occupied(
        self,
        position: KernelPosition,
        *,
        size_cells: int = 1,
        ignore_entity_id: str | None = None,
    ) -> bool: ...

    def find_nearest_unoccupied_space(
        self,
        position: KernelPosition,
        *,
        size_cells: int = 1,
        ignore_entity_id: str | None = None,
    ) -> KernelPosition: ...

    def validate_target_range(self, source_id: str, target_id: str, maximum_distance_ft: int) -> None: ...

    def validate_area_origin(self, origin: KernelPosition) -> None: ...

    def resolve_area_targets(
        self,
        origin: KernelPosition,
        shape: str,
        size_ft: int,
        *,
        include_ids: Sequence[str] = (),
    ) -> tuple[str, ...]: ...

    def validate_path(
        self,
        entity_id: str,
        path: Sequence[KernelPosition],
        *,
        maximum_distance_ft: int | None = None,
    ) -> SpatialPathResult: ...

    def validate_intangible_entity_path(
        self,
        entity_id: str,
        path: Sequence[KernelPosition],
        *,
        maximum_distance_ft: int | None = None,
    ) -> SpatialPathResult: ...

    def shortest_path(
        self,
        entity_id: str,
        destination: KernelPosition,
    ) -> tuple[KernelPosition, ...]: ...

    def validate_forced_movement(
        self,
        entity_id: str,
        destination: KernelPosition,
        *,
        source_id: str | None = None,
    ) -> SpatialPathResult: ...

    def validate_teleport_destination(
        self,
        entity_id: str,
        destination: KernelPosition,
        *,
        maximum_distance_ft: int | None = None,
    ) -> None: ...

    def snapshot(self) -> dict[str, object]: ...


@dataclass
class DeterministicTestSpatialAuthority:
    """Fixed grid adapter used by unit/integration tests and protocol examples."""

    width: int = 20
    height: int = 20
    cell_size_ft: int = 5
    entities: dict[str, SpatialEntity] = field(default_factory=dict)
    blocked: set[Point] = field(default_factory=set)
    cover_cells: set[Point] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1 or self.cell_size_ft < 1:
            raise ValueError("spatial grid dimensions must be positive")

    def add_entity(
        self,
        entity_id: str,
        position: KernelPosition,
        *,
        size_cells: int = 1,
    ) -> None:
        if not 1 <= size_cells <= 4:
            raise ValueError("size_cells must be between 1 and 4")
        self._validate_position(position, size_cells=size_cells)
        self.entities[entity_id] = SpatialEntity(entity_id, position, size_cells)

    def _validate_position(self, position: KernelPosition, *, size_cells: int = 1) -> None:
        if not (
            1 <= position.row <= self.height - size_cells + 1
            and 1 <= position.col <= self.width - size_cells + 1
        ):
            raise ValueError("position is outside the authoritative scene grid")

    def _entity(self, entity_id: str) -> SpatialEntity:
        entity = self.entities.get(entity_id)
        if entity is None or not entity.active:
            raise ValueError(f"spatial entity not found: {entity_id}")
        return entity

    def get_entity_position(self, entity_id: str) -> KernelPosition:
        return self._entity(entity_id).position

    def get_entity_size(self, entity_id: str) -> int:
        return self._entity(entity_id).size_cells

    def get_entity_bounds(self, entity_id: str) -> dict[str, int]:
        entity = self._entity(entity_id)
        return {
            "row_min": entity.position.row,
            "col_min": entity.position.col,
            "row_max": entity.position.row + entity.size_cells - 1,
            "col_max": entity.position.col + entity.size_cells - 1,
            "elevation_ft": entity.position.elevation_ft,
        }

    def distance_between(self, first_id: str, second_id: str) -> int:
        first = self._entity(first_id)
        second = self._entity(second_id)
        horizontal = min(
            grid_distance_ft(a, b, cell_size_ft=self.cell_size_ft)
            for a in first.footprint
            for b in second.footprint
        )
        return max(horizontal, abs(first.position.elevation_ft - second.position.elevation_ft))

    def has_line_of_sight(self, first_id: str, second_id: str) -> bool:
        first = self._entity(first_id)
        second = self._entity(second_id)
        return any(
            line_of_sight(a, b, self.blocked)
            for a in first.footprint
            for b in second.footprint
        )

    def get_cover(self, first_id: str, second_id: str) -> str:
        first = self._entity(first_id)
        second = self._entity(second_id)
        if not self.has_line_of_sight(first_id, second_id):
            return "total"
        return min(
            (
                cover_between(a, b, self.cover_cells, self.blocked)
                for a in first.footprint
                for b in second.footprint
            ),
            key={"none": 0, "half": 1, "total": 2}.get,
        )

    def is_space_occupied(
        self,
        position: KernelPosition,
        *,
        size_cells: int = 1,
        ignore_entity_id: str | None = None,
    ) -> bool:
        self._validate_position(position, size_cells=size_cells)
        desired = {
            (position.row + row, position.col + col)
            for row in range(size_cells)
            for col in range(size_cells)
        }
        if desired & self.blocked:
            return True
        return any(
            entity.entity_id != ignore_entity_id
            and entity.active
            and desired.intersection(entity.footprint)
            for entity in self.entities.values()
        )

    def find_nearest_unoccupied_space(
        self,
        position: KernelPosition,
        *,
        size_cells: int = 1,
        ignore_entity_id: str | None = None,
    ) -> KernelPosition:
        self._validate_position(position, size_cells=size_cells)
        queue: deque[tuple[int, int]] = deque([(position.row, position.col)])
        visited = {(position.row, position.col)}
        while queue:
            row, col = queue.popleft()
            candidate = KernelPosition(row=row, col=col, elevation_ft=position.elevation_ft)
            if not self.is_space_occupied(
                candidate,
                size_cells=size_cells,
                ignore_entity_id=ignore_entity_id,
            ):
                return candidate
            for next_row, next_col in (
                (row - 1, col),
                (row, col - 1),
                (row, col + 1),
                (row + 1, col),
            ):
                if (next_row, next_col) in visited:
                    continue
                if 1 <= next_row <= self.height - size_cells + 1 and 1 <= next_col <= self.width - size_cells + 1:
                    visited.add((next_row, next_col))
                    queue.append((next_row, next_col))
        raise ValueError("no unoccupied space exists in the authoritative scene")

    def validate_target_range(self, source_id: str, target_id: str, maximum_distance_ft: int) -> None:
        if self.distance_between(source_id, target_id) > maximum_distance_ft:
            raise ValueError("target is outside the authoritative range")

    def validate_area_origin(self, origin: KernelPosition) -> None:
        self._validate_position(origin)
        if origin.row > self.height or origin.col > self.width:
            raise ValueError("area origin is outside the authoritative scene")

    def resolve_area_targets(
        self,
        origin: KernelPosition,
        shape: str,
        size_ft: int,
        *,
        include_ids: Sequence[str] = (),
    ) -> tuple[str, ...]:
        self.validate_area_origin(origin)
        radius = max(1, size_ft // self.cell_size_ft)
        result: list[str] = []
        for entity_id, entity in sorted(self.entities.items()):
            if not entity.active:
                continue
            distance = grid_distance_ft(
                (origin.row, origin.col),
                (entity.position.row, entity.position.col),
                cell_size_ft=self.cell_size_ft,
            )
            in_area = distance <= size_ft
            if shape == "line":
                in_area = (
                    entity.position.row == origin.row
                    and abs(entity.position.col - origin.col) <= radius
                ) or (
                    entity.position.col == origin.col
                    and abs(entity.position.row - origin.row) <= radius
                )
            elif shape == "point":
                in_area = distance == 0
            elif shape in {"sphere", "cylinder"}:
                in_area = distance <= size_ft
            elif shape in {"cone", "cube"}:
                in_area = (
                    abs(entity.position.row - origin.row) <= radius
                    and abs(entity.position.col - origin.col) <= radius
                )
            if in_area or entity_id in include_ids:
                result.append(entity_id)
        return tuple(result)

    def validate_path(
        self,
        entity_id: str,
        path: Sequence[KernelPosition],
        *,
        maximum_distance_ft: int | None = None,
    ) -> SpatialPathResult:
        entity = self._entity(entity_id)
        if not path:
            return SpatialPathResult(True, 0)
        if path[0] != entity.position:
            return SpatialPathResult(False, 0, "path must start at the current position")
        cost = movement_cost_ft(
            [(position.row, position.col) for position in path],
            self.blocked,
            cell_size_ft=self.cell_size_ft,
        )
        for position in path[1:]:
            if self.is_space_occupied(position, size_cells=entity.size_cells, ignore_entity_id=entity_id):
                return SpatialPathResult(False, cost, "path enters occupied or blocked space")
        if maximum_distance_ft is not None and cost > maximum_distance_ft:
            return SpatialPathResult(False, cost, "path exceeds the movement budget")
        return SpatialPathResult(True, cost)

    def validate_intangible_entity_path(
        self,
        entity_id: str,
        path: Sequence[KernelPosition],
        *,
        maximum_distance_ft: int | None = None,
    ) -> SpatialPathResult:
        """Validate a spectral entity path: objects block, creatures do not."""

        entity = self._entity(entity_id)
        if not path:
            return SpatialPathResult(True, 0)
        if path[0] != entity.position:
            return SpatialPathResult(False, 0, "path must start at the current position")
        try:
            self._validate_position(path[-1], size_cells=entity.size_cells)
        except ValueError as exc:
            return SpatialPathResult(False, 0, str(exc))
        cost = movement_cost_ft(
            [(position.row, position.col) for position in path],
            self.blocked,
            cell_size_ft=self.cell_size_ft,
        )
        if maximum_distance_ft is not None and cost > maximum_distance_ft:
            return SpatialPathResult(False, cost, "path exceeds the movement budget")
        return SpatialPathResult(True, cost)

    def shortest_path(
        self,
        entity_id: str,
        destination: KernelPosition,
    ) -> tuple[KernelPosition, ...]:
        """Return a deterministic object-clear path; creatures are traversable."""

        entity = self._entity(entity_id)
        self._validate_position(destination, size_cells=entity.size_cells)
        start = (entity.position.row, entity.position.col)
        goal = (destination.row, destination.col)
        queue: deque[tuple[int, int]] = deque([start])
        previous: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        while queue:
            row, col = queue.popleft()
            if (row, col) == goal:
                points: list[KernelPosition] = []
                current: tuple[int, int] | None = goal
                while current is not None:
                    points.append(
                        KernelPosition(
                            row=current[0],
                            col=current[1],
                            elevation_ft=destination.elevation_ft
                            if current == goal
                            else entity.position.elevation_ft,
                        )
                    )
                    current = previous[current]
                return tuple(reversed(points))
            for next_row, next_col in (
                (row - 1, col),
                (row, col - 1),
                (row, col + 1),
                (row + 1, col),
            ):
                point = (next_row, next_col)
                if point in previous:
                    continue
                if not (
                    1 <= next_row <= self.height - entity.size_cells + 1
                    and 1 <= next_col <= self.width - entity.size_cells + 1
                ):
                    continue
                footprint = {
                    (next_row + r, next_col + c)
                    for r in range(entity.size_cells)
                    for c in range(entity.size_cells)
                }
                if footprint & self.blocked:
                    continue
                previous[point] = (row, col)
                queue.append(point)
        raise ValueError("no object-clear path exists in the authoritative scene")

    def validate_forced_movement(
        self,
        entity_id: str,
        destination: KernelPosition,
        *,
        source_id: str | None = None,
    ) -> SpatialPathResult:
        entity = self._entity(entity_id)
        source = self._entity(source_id) if source_id else None
        if source is None:
            path = (entity.position, destination)
        else:
            row_delta = entity.position.row - source.position.row
            col_delta = entity.position.col - source.position.col
            step = KernelPosition(
                row=entity.position.row + (1 if row_delta > 0 else -1 if row_delta < 0 else 0),
                col=entity.position.col + (1 if col_delta > 0 else -1 if col_delta < 0 else 0),
                elevation_ft=destination.elevation_ft,
            )
            path = (entity.position, step, destination)
        try:
            result = self.validate_path(entity_id, path)
        except ValueError as exc:
            return SpatialPathResult(False, 0, str(exc))
        return result

    def validate_teleport_destination(
        self,
        entity_id: str,
        destination: KernelPosition,
        *,
        maximum_distance_ft: int | None = None,
    ) -> None:
        entity = self._entity(entity_id)
        self._validate_position(destination, size_cells=entity.size_cells)
        if self.is_space_occupied(destination, size_cells=entity.size_cells, ignore_entity_id=entity_id):
            raise ValueError("teleport destination is occupied")
        if maximum_distance_ft is not None:
            distance = max(
                grid_distance_ft(a, b, cell_size_ft=self.cell_size_ft)
                for a in entity.footprint
                for b in ((destination.row, destination.col),)
            )
            if distance > maximum_distance_ft:
                raise ValueError("teleport destination exceeds maximum distance")

    def snapshot(self) -> dict[str, object]:
        return {
            "rules_distance_unit": "feet",
            "scene_coordinate_unit": "grid_cell",
            "grid_width": self.width,
            "grid_height": self.height,
            "grid_cell_size_ft": self.cell_size_ft,
            "blocked": [list(point) for point in sorted(self.blocked)],
            "cover": [list(point) for point in sorted(self.cover_cells)],
            "entities": {
                entity_id: {
                    "position": entity.position.model_dump(mode="json"),
                    "size_cells": entity.size_cells,
                }
                for entity_id, entity in sorted(self.entities.items())
                if entity.active
            },
        }


class SceneGridSpatialAuthority(DeterministicTestSpatialAuthority):
    """Adapter over the existing SceneGrid/SceneObject/Combatant records."""

    def __init__(self, session: object, scene_id: str, *, combat_id: str | None = None) -> None:
        from sqlalchemy import select

        from dnd_dm_assistant.infrastructure.database.models import (
            Combatant,
            SceneGrid,
            SceneObject,
            SceneToken,
        )

        grid = session.scalar(select(SceneGrid).where(SceneGrid.scene_id == scene_id))  # type: ignore[attr-defined]
        if grid is None:
            raise ValueError("scene has no authoritative grid")
        super().__init__(width=grid.width, height=grid.height, cell_size_ft=grid.cell_size_ft)
        raw_cells = (grid.layers_json or {}).get("cells", [])
        for cell in raw_cells if isinstance(raw_cells, list) else []:
            if not isinstance(cell, Mapping):
                continue
            point = (cell.get("row"), cell.get("col"))
            if not all(isinstance(value, int) for value in point):
                continue
            if cell.get("kind") in {"wall", "void"} or cell.get("blocks_movement") is True:
                self.blocked.add(point)  # type: ignore[arg-type]
            if cell.get("kind") == "cover":
                self.cover_cells.add(point)  # type: ignore[arg-type]
        for scene_object in session.scalars(  # type: ignore[attr-defined]
            select(SceneObject).where(SceneObject.scene_id == scene_id)
        ).all():
            if scene_object.state in {"destroyed", "picked_up"}:
                continue
            cells = {
                (row, col)
                for row in range(scene_object.row, scene_object.row + scene_object.height_cells)
                for col in range(scene_object.col, scene_object.col + scene_object.width_cells)
            }
            if scene_object.object_type == "wall" or (
                scene_object.object_type == "door" and scene_object.state in {"active", "closed"}
            ):
                self.blocked.update(cells)
            if scene_object.object_type == "cover":
                self.cover_cells.update(cells)
        combatants = session.scalars(  # type: ignore[attr-defined]
            select(Combatant).where(
                Combatant.combat_id == combat_id,
                Combatant.is_active.is_(True),
            )
        ).all() if combat_id else []
        for combatant in combatants:
            raw = (combatant.snapshot_json or {}).get("grid_position")
            if not isinstance(raw, Mapping):
                continue
            row, col = raw.get("row"), raw.get("col")
            if isinstance(row, int) and isinstance(col, int):
                size = (combatant.snapshot_json or {}).get("size_cells", 1)
                self.add_entity(combatant.id, KernelPosition(row=row, col=col, elevation_ft=int(raw.get("elevation_ft", 0))), size_cells=int(size) if isinstance(size, int) else 1)
        if not combatants:
            for token in session.scalars(  # type: ignore[attr-defined]
                select(SceneToken).where(SceneToken.scene_id == scene_id, SceneToken.visible.is_(True))
            ).all():
                self.add_entity(token.id, KernelPosition(row=token.row, col=token.col, elevation_ft=token.elevation_ft), size_cells=token.size_cells)
