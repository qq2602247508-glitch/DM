import type { SceneGrid } from "../api/types";
import {
  getTargetingCells,
  gridDistanceFt,
  isBlockedCell,
  type GridPoint,
  type TargetingTemplate,
} from "./gridTargeting";

export type MovementPlan = {
  path: GridPoint[];
  destination: GridPoint;
  spentFt: number;
};

/**
 * Stable identity for one persisted movement request.
 *
 * React state is intentionally not used for this identity: an effect can run
 * twice before the state update from the first animation is rendered.  The
 * combatant version and initiative slot make a request from a later snapshot
 * a new request, while duplicate effects for the same snapshot collapse to
 * one write.
 */
export function movementCommitKey(
  turnKey: string,
  fighterId: string,
  fighterVersion: number,
  plan: MovementPlan,
  automatic: boolean,
  exhaustMovement: boolean,
  fleeing: boolean,
): string {
  return [
    turnKey,
    fighterId,
    fighterVersion,
    plan.destination.row,
    plan.destination.col,
    plan.spentFt,
    automatic ? "auto" : "manual",
    exhaustMovement ? "exhaust" : "preserve",
    fleeing ? "flee" : "fight",
  ].join(":");
}

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

/**
 * Find a legal attack position for an area or directional action.
 *
 * Numeric range alone is not enough for cones, lines, cubes, and line-of-sight
 * checks.  The old AI stopped at the numeric range boundary, then the command
 * console rejected the target because the actual shape did not cover it.  This
 * planner searches the same targeting template used by the map and console,
 * so movement and attack resolve against one authoritative predicate.
 */
export function planTargetingPath(
  grid: SceneGrid,
  origin: GridPoint,
  target: GridPoint,
  occupied: ReadonlySet<string>,
  movementRemainingFt: number,
  targeting: TargetingTemplate,
): MovementPlan {
  const maximumSteps = Math.max(0, Math.floor(movementRemainingFt / grid.cell_size_ft));
  const queue: GridPoint[] = [origin];
  const previous = new Map<string, GridPoint | null>([[pointKey(origin), null]]);
  const depth = new Map<string, number>([[pointKey(origin), 0]]);
  let best = origin;
  const targetCovered = (point: GridPoint) => getTargetingCells(
    grid,
    point,
    target,
    targeting,
  ).some((cell) => cell.row === target.row && cell.col === target.col);
  const isCloser = (candidate: GridPoint, current: GridPoint) => (
    gridDistanceFt(candidate, target, grid.cell_size_ft)
      < gridDistanceFt(current, target, grid.cell_size_ft)
  );

  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) break;
    const currentDepth = depth.get(pointKey(current)) ?? 0;
    if (targetCovered(current)) {
      let cursor: GridPoint | null = current;
      const path: GridPoint[] = [];
      while (cursor && pointKey(cursor) !== pointKey(origin)) {
        path.unshift(cursor);
        cursor = previous.get(pointKey(cursor)) ?? null;
      }
      return {
        path,
        destination: current,
        spentFt: path.length * grid.cell_size_ft,
      };
    }
    if (isCloser(current, best)) best = current;
    if (currentDepth >= maximumSteps) continue;
    for (const next of neighbors(grid, current)) {
      const key = pointKey(next);
      if (
        previous.has(key)
        || key === pointKey(target)
        || isBlockedCell(grid, next)
        || occupied.has(key)
      ) continue;
      previous.set(key, current);
      depth.set(key, currentDepth + 1);
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

export function planRetreatPath(
  grid: SceneGrid,
  origin: GridPoint,
  threats: GridPoint[],
  occupied: ReadonlySet<string>,
  movementRemainingFt: number,
): MovementPlan {
  const maximumSteps = Math.max(0, Math.floor(movementRemainingFt / grid.cell_size_ft));
  const queue: GridPoint[] = [origin];
  const previous = new Map<string, GridPoint | null>([[pointKey(origin), null]]);
  const depth = new Map<string, number>([[pointKey(origin), 0]]);
  const threatDistance = (point: GridPoint) => threats.length === 0
    ? 0
    : Math.min(...threats.map((threat) => (
        Math.max(Math.abs(point.row - threat.row), Math.abs(point.col - threat.col))
      )));
  const edgeDistance = (point: GridPoint) => Math.min(
    point.row - 1,
    grid.height - point.row,
    point.col - 1,
    grid.width - point.col,
  );
  const score = (point: GridPoint): [number, number, number] => [
    threatDistance(point),
    -edgeDistance(point),
    depth.get(pointKey(point)) ?? 0,
  ];
  const isBetter = (candidate: GridPoint, current: GridPoint) => {
    const candidateScore = score(candidate);
    const currentScore = score(current);
    return candidateScore[0] > currentScore[0]
      || (candidateScore[0] === currentScore[0] && candidateScore[1] > currentScore[1])
      || (
        candidateScore[0] === currentScore[0]
        && candidateScore[1] === currentScore[1]
        && candidateScore[2] > currentScore[2]
      );
  };
  let best = origin;
  while (queue.length > 0) {
    const current = queue.shift();
    if (!current) break;
    const currentDepth = depth.get(pointKey(current)) ?? 0;
    if (isBetter(current, best)) best = current;
    if (currentDepth >= maximumSteps) continue;
    for (const next of neighbors(grid, current)) {
      const key = pointKey(next);
      if (previous.has(key) || isBlockedCell(grid, next) || occupied.has(key)) continue;
      previous.set(key, current);
      depth.set(key, currentDepth + 1);
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
