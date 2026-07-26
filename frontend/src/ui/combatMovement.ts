import type { SceneGrid } from "../api/types";
import { isBlockedCell, type GridPoint } from "./gridTargeting";

export type MovementPlan = {
  path: GridPoint[];
  destination: GridPoint;
  spentFt: number;
};

const pointKey = (point: GridPoint): string => `${point.row}:${point.col}`;

function neighbors(grid: SceneGrid, point: GridPoint): GridPoint[] {
  const result: GridPoint[] = [];
  for (let rowDelta = -1; rowDelta <= 1; rowDelta += 1) {
    for (let colDelta = -1; colDelta <= 1; colDelta += 1) {
      if (rowDelta === 0 && colDelta === 0) continue;
      const next = { row: point.row + rowDelta, col: point.col + colDelta };
      if (next.row < 1 || next.row > grid.height || next.col < 1 || next.col > grid.width) continue;
      result.push(next);
    }
  }
  return result;
}

export function shortestMovementPath(
  grid: SceneGrid,
  origin: GridPoint,
  destination: GridPoint,
  occupied: ReadonlySet<string>,
  movementRemainingFt: number,
): MovementPlan | null {
  if (pointKey(origin) === pointKey(destination)) {
    return { path: [], destination: origin, spentFt: 0 };
  }
  const maximumSteps = Math.max(0, Math.floor(movementRemainingFt / grid.cell_size_ft));
  const queue: GridPoint[] = [origin];
  const previous = new Map<string, GridPoint | null>([[pointKey(origin), null]]);
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) break;
    const distanceFromOrigin = (() => {
      let steps = 0;
      let cursor: GridPoint | null = current;
      while (cursor && pointKey(cursor) !== pointKey(origin)) {
        cursor = previous.get(pointKey(cursor)) ?? null;
        steps += 1;
      }
      return steps;
    })();
    if (distanceFromOrigin >= maximumSteps) continue;
    for (const next of neighbors(grid, current)) {
      const key = pointKey(next);
      if (previous.has(key) || isBlockedCell(grid, next) || occupied.has(key)) continue;
      previous.set(key, current);
      if (key === pointKey(destination)) {
        const path: GridPoint[] = [next];
        let cursor: GridPoint | null = current;
        while (cursor && pointKey(cursor) !== pointKey(origin)) {
          path.unshift(cursor);
          cursor = previous.get(pointKey(cursor)) ?? null;
        }
        return {
          path,
          destination: next,
          spentFt: path.length * grid.cell_size_ft,
        };
      }
      queue.push(next);
    }
  }
  return null;
}

export function planApproachPath(
  grid: SceneGrid,
  origin: GridPoint,
  target: GridPoint,
  occupied: ReadonlySet<string>,
  movementRemainingFt: number,
  desiredRangeFt = 5,
): MovementPlan {
  const maximumSteps = Math.max(0, Math.floor(movementRemainingFt / grid.cell_size_ft));
  const queue: GridPoint[] = [origin];
  const previous = new Map<string, GridPoint | null>([[pointKey(origin), null]]);
  let best = origin;
  const distanceToTarget = (point: GridPoint) => (
    Math.max(Math.abs(point.row - target.row), Math.abs(point.col - target.col))
    * grid.cell_size_ft
  );
  if (distanceToTarget(origin) <= desiredRangeFt) {
    return { path: [], destination: origin, spentFt: 0 };
  }
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) break;
    const depth = (() => {
      let steps = 0;
      let cursor: GridPoint | null = current;
      while (cursor && pointKey(cursor) !== pointKey(origin)) {
        cursor = previous.get(pointKey(cursor)) ?? null;
        steps += 1;
      }
      return steps;
    })();
    if (distanceToTarget(current) < distanceToTarget(best)) best = current;
    if (distanceToTarget(current) <= desiredRangeFt || depth >= maximumSteps) continue;
    for (const next of neighbors(grid, current)) {
      const key = pointKey(next);
      if (
        previous.has(key)
        || pointKey(next) === pointKey(target)
        || isBlockedCell(grid, next)
        || occupied.has(key)
      ) continue;
      previous.set(key, current);
      queue.push(next);
    }
  }
  const path: GridPoint[] = [];
  let cursor: GridPoint | null = best;
  while (cursor && pointKey(cursor) !== pointKey(origin)) {
    path.unshift(cursor);
    cursor = previous.get(pointKey(cursor)) ?? null;
  }
  return {
    path,
    destination: best,
    spentFt: path.length * grid.cell_size_ft,
  };
}
