"""Pure, deterministic helpers shared by the scene exploration transaction service."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil, hypot

Point = tuple[int, int]

_SOCIAL_ATTITUDE_VALUES = {"hostile": -1, "indifferent": 0, "friendly": 1}
_SOCIAL_ATTITUDE_ALIASES = {
    "hostile": "hostile",
    "敌对": "hostile",
    "敌意": "hostile",
    "indifferent": "indifferent",
    "neutral": "indifferent",
    "中立": "indifferent",
    "冷漠": "indifferent",
    "friendly": "friendly",
    "友善": "friendly",
    "友好": "friendly",
}
_SOCIAL_OUTCOME_DELTAS = {"improve": 1, "unchanged": 0, "worsen": -1}


@dataclass(frozen=True, slots=True)
class SocialAttitudeTransition:
    """A bounded three-step attitude change for a DM-adjudicated interaction."""

    before: str
    after: str
    requested_delta: int
    effective_delta: int
    normalized_from_nonstandard: bool


@dataclass(frozen=True, slots=True)
class ChaseProgress:
    """The durable, numeric part of a DM-adjudicated chase."""

    successes: int
    failures: int
    target_successes: int
    target_failures: int
    status: str


@dataclass(frozen=True, slots=True)
class CharacterEffectResolution:
    """A bounded HP/max-HP change supplied explicitly by the DM."""

    hp_before: int
    hp_after: int
    max_hp_reduction_before: int
    max_hp_reduction_after: int
    effective_max_hp_after: int


@dataclass(frozen=True, slots=True)
class DowntimeProgress:
    """A deterministic day/cost calculation; rewards remain DM supplied."""

    progress_before: int
    progress_after: int
    duration_days: int
    status: str
    charged_days: int
    cost_copper: int


def resolve_social_attitude(current_attitude: str | None, outcome: str) -> SocialAttitudeTransition:
    """Resolve a DM outcome without allowing attitude to move beyond the 5e bands.

    Existing campaigns may contain free-form NPC attitude labels.  A blank or
    non-standard label is treated as indifferent for the first governed social
    interaction, then persisted as one of the canonical labels.
    """

    raw = str(current_attitude or "").strip()
    normalized = _SOCIAL_ATTITUDE_ALIASES.get(raw.casefold())
    before = normalized or "indifferent"
    try:
        requested_delta = _SOCIAL_OUTCOME_DELTAS[outcome]
    except KeyError as exc:
        raise ValueError("social outcome must be improve, unchanged, or worsen") from exc
    before_value = _SOCIAL_ATTITUDE_VALUES[before]
    after_value = max(-1, min(1, before_value + requested_delta))
    after = next(
        attitude for attitude, value in _SOCIAL_ATTITUDE_VALUES.items() if value == after_value
    )
    return SocialAttitudeTransition(
        before=before,
        after=after,
        requested_delta=requested_delta,
        effective_delta=after_value - before_value,
        normalized_from_nonstandard=normalized is None and raw != "",
    )


def resolve_chase_progress(
    *,
    successes: int,
    failures: int,
    target_successes: int,
    target_failures: int,
    outcome: str,
) -> ChaseProgress:
    """Advance one confirmed chase beat without inventing narrative consequences."""

    if target_successes < 1 or target_failures < 1:
        raise ValueError("chase targets must be positive")
    if successes < 0 or failures < 0:
        raise ValueError("chase counters must not be negative")
    if outcome not in {"success", "failure"}:
        raise ValueError("chase outcome must be success or failure")
    next_successes = successes + (1 if outcome == "success" else 0)
    next_failures = failures + (1 if outcome == "failure" else 0)
    status = (
        "escaped"
        if next_successes >= target_successes
        else "caught"
        if next_failures >= target_failures
        else "active"
    )
    return ChaseProgress(
        successes=next_successes,
        failures=next_failures,
        target_successes=target_successes,
        target_failures=target_failures,
        status=status,
    )


def resolve_character_effect(
    *,
    hp: int,
    max_hp: int,
    max_hp_reduction: int,
    damage: int = 0,
    max_hp_reduction_delta: int = 0,
) -> CharacterEffectResolution:
    """Apply explicit exploration damage without making a hidden saving throw."""

    if min(hp, max_hp, max_hp_reduction, damage, max_hp_reduction_delta) < 0:
        raise ValueError("character effect values must not be negative")
    if hp + max_hp_reduction > max_hp:
        raise ValueError("character HP state is invalid")
    next_reduction = min(max_hp, max_hp_reduction + max_hp_reduction_delta)
    effective_max = max_hp - next_reduction
    next_hp = min(effective_max, max(0, hp - damage))
    return CharacterEffectResolution(
        hp_before=hp,
        hp_after=next_hp,
        max_hp_reduction_before=max_hp_reduction,
        max_hp_reduction_after=next_reduction,
        effective_max_hp_after=effective_max,
    )


def resolve_downtime_progress(
    *,
    progress_days: int,
    duration_days: int,
    requested_days: int,
    daily_cost_cp: int,
) -> DowntimeProgress:
    """Advance only remaining downtime days and charge exactly those days."""

    if min(progress_days, duration_days, requested_days, daily_cost_cp) < 0:
        raise ValueError("downtime values must not be negative")
    if duration_days < 1 or progress_days > duration_days:
        raise ValueError("downtime progress is invalid")
    if requested_days < 1:
        raise ValueError("downtime needs at least one day")
    charged_days = min(requested_days, duration_days - progress_days)
    progress_after = progress_days + charged_days
    return DowntimeProgress(
        progress_before=progress_days,
        progress_after=progress_after,
        duration_days=duration_days,
        status="completed" if progress_after >= duration_days else "active",
        charged_days=charged_days,
        cost_copper=charged_days * daily_cost_cp,
    )
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
    return not any(point in blockers for point in line_cells(start, end))


def line_cells(start: Point, end: Point) -> tuple[Point, ...]:
    """Return the Bresenham cells strictly between two endpoints."""
    x0, y0 = start
    x1, y1 = end
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx - dy
    cells: list[Point] = []
    while (x0, y0) != (x1, y1):
        if (x0, y0) != start:
            cells.append((x0, y0))
        twice = 2 * err
        if twice > -dy:
            err -= dy
            x0 += sx
        if twice < dx:
            err += dx
            y0 += sy
    return tuple(cells)


def line_of_sight_3d(
    start: Point,
    end: Point,
    blockers: set[Point],
    obstacle_heights: dict[Point, tuple[tuple[int, int], ...]],
    *,
    start_height_ft: int,
    end_height_ft: int,
) -> bool:
    """Check a grid ray against explicitly measured vertical blocker spans.

    ``obstacle_heights`` must already be complete for every blocker on the
    ray. Each span is ``(base_ft, top_ft)`` and represents a solid blocker
    from its base up to, but not including, its top. Callers should fall back
    to the conservative 2-D result when a blocker has no authoritative height.
    """

    cells = line_cells(start, end)
    steps = max(abs(end[0] - start[0]), abs(end[1] - start[1]))
    if steps == 0:
        return True
    for index, point in enumerate(cells, start=1):
        if point not in blockers:
            continue
        ray_height_ft = start_height_ft + (
            (end_height_ft - start_height_ft) * index / steps
        )
        for base_ft, top_ft in obstacle_heights[point]:
            if base_ft <= ray_height_ft < top_ft:
                return False
    return True


def cover_between(start: Point, end: Point, cover_cells: set[Point], blockers: set[Point]) -> str:
    if not line_of_sight(start, end, blockers):
        return "total"
    return "half" if any(_near_line(cell, start, end) for cell in cover_cells) else "none"


def _near_line(point: Point, start: Point, end: Point) -> bool:
    # A cover object on the ray, or adjoining the target-facing end of it,
    # grants half cover. Cells behind the target must not affect the attack.
    vector_row = end[0] - start[0]
    vector_col = end[1] - start[1]
    length_squared = vector_row**2 + vector_col**2
    if length_squared == 0:
        return False
    point_row = point[0] - start[0]
    point_col = point[1] - start[1]
    projection = (point_row * vector_row + point_col * vector_col) / length_squared
    if not 0 < projection <= 1.1:
        return False
    closest_row = start[0] + projection * vector_row
    closest_col = start[1] + projection * vector_col
    return hypot(point[0] - closest_row, point[1] - closest_col) <= 1.0


def travel_minutes(distance_miles: float, pace: str) -> int:
    mph = {"fast": 4.0, "normal": 3.0, "slow": 2.0}.get(pace)
    if mph is None:
        raise ValueError("pace must be fast, normal, or slow")
    if distance_miles < 0:
        raise ValueError("distance_miles must not be negative")
    return ceil(distance_miles / mph * 60)
