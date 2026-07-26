"""Pure, deterministic helpers shared by the scene exploration transaction service."""

from __future__ import annotations

from collections.abc import Iterable
from math import ceil, hypot

Point = tuple[int, int]


def grid_distance_ft(start: Point, end: Point, *, cell_size_ft: int = 5) -> int:
    """5e square-grid distance: each diagonal costs one square."""
    return max(abs(end[0] - start[0]), abs(end[1] - start[1])) * cell_size_ft


def movement_cost_ft(path: Iterable[Point], difficult: set[Point], *, cell_size_ft: int = 5) -> int:
    points = list(path)
    if len(points) < 2:
        return 0
    total = 0
    for previous, current in zip(points, points[1:], strict=False):
        if max(abs(previous[0] - current[0]), abs(previous[1] - current[1])) != 1:
            raise ValueError("path steps must be adjacent grid cells")
        total += cell_size_ft * (2 if current in difficult else 1)
    return total


def line_of_sight(start: Point, end: Point, blockers: set[Point]) -> bool:
    """Bresenham line; endpoints themselves never block sight."""
    x0, y0 = start
    x1, y1 = end
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx - dy
    while (x0, y0) != (x1, y1):
        if (x0, y0) != start and (x0, y0) in blockers:
            return False
        twice = 2 * err
        if twice > -dy:
            err -= dy
            x0 += sx
        if twice < dx:
            err += dx
            y0 += sy
    return True


def cover_between(start: Point, end: Point, cover_cells: set[Point], blockers: set[Point]) -> str:
    if not line_of_sight(start, end, blockers):
        return "total"
    return "half" if any(_near_line(cell, start, end) for cell in cover_cells) else "none"


def _near_line(point: Point, start: Point, end: Point) -> bool:
    # A useful grid approximation: a cover object adjoining the ray grants half cover.
    return hypot(point[0] - end[0], point[1] - end[1]) <= 1.5


def travel_minutes(distance_miles: float, pace: str) -> int:
    mph = {"fast": 4.0, "normal": 3.0, "slow": 2.0}.get(pace)
    if mph is None:
        raise ValueError("pace must be fast, normal, or slow")
    if distance_miles < 0:
        raise ValueError("distance_miles must not be negative")
    return ceil(distance_miles / mph * 60)
