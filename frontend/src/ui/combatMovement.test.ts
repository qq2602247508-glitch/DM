import { describe, expect, it } from "vitest";

import type { SceneGrid } from "../api/types";
import {
  movementCommitKey,
  planApproachPath,
  planRetreatPath,
  planTargetingPath,
  shortestMovementPath,
} from "./combatMovement";

const grid: SceneGrid = {
  width: 8,
  height: 8,
  cell_size_ft: 5,
  theme: "测试战场",
  cells: [{ row: 2, col: 2, kind: "wall", label: "墙" }],
};

describe("combat movement", () => {
  it("deduplicates the same persisted movement but separates later snapshots", () => {
    const plan = planApproachPath(grid, { row: 1, col: 1 }, { row: 4, col: 4 }, new Set(), 30, 5);
    const first = movementCommitKey("1:0:monster", "monster-1", 7, plan, true, false, false);
    expect(movementCommitKey("1:0:monster", "monster-1", 7, plan, true, false, false)).toBe(first);
    expect(movementCommitKey("1:0:monster", "monster-1", 8, plan, true, false, false)).not.toBe(first);
    expect(movementCommitKey("2:0:monster", "monster-1", 7, plan, true, false, false)).not.toBe(first);
  });

  it("cannot spend more than the remaining movement", () => {
    const plan = planApproachPath(grid, { row: 1, col: 1 }, { row: 8, col: 8 }, new Set(), 15, 5);
    expect(plan.spentFt).toBeLessThanOrEqual(15);
    expect(plan.path).toHaveLength(3);
  });

  it("stops outside the target cell and avoids walls", () => {
    const plan = planApproachPath(grid, { row: 1, col: 1 }, { row: 4, col: 4 }, new Set(), 30, 5);
    expect(plan.destination).not.toEqual({ row: 4, col: 4 });
    expect(plan.path).not.toContainEqual({ row: 2, col: 2 });
    expect(plan.spentFt).toBe(15);
  });

  it("rejects a manual destination beyond the current allowance", () => {
    expect(shortestMovementPath(grid, { row: 1, col: 1 }, { row: 8, col: 8 }, new Set(), 10)).toBeNull();
  });

  it("recalculates the reachable range from the new position after movement", () => {
    const firstMove = shortestMovementPath(
      grid,
      { row: 1, col: 1 },
      { row: 1, col: 3 },
      new Set(),
      30,
    );
    expect(firstMove?.spentFt).toBe(10);
    const remainingFt = 30 - (firstMove?.spentFt ?? 0);
    const secondMove = shortestMovementPath(
      grid,
      firstMove?.destination ?? { row: 1, col: 1 },
      { row: 1, col: 7 },
      new Set(),
      remainingFt,
    );
    expect(secondMove?.spentFt).toBe(20);
    expect(shortestMovementPath(
      grid,
      firstMove?.destination ?? { row: 1, col: 1 },
      { row: 1, col: 8 },
      new Set(),
      remainingFt,
    )).toBeNull();
  });

  it("moves a fleeing NPC away from threats and prefers a map edge", () => {
    const plan = planRetreatPath(
      grid,
      { row: 4, col: 4 },
      [{ row: 4, col: 5 }],
      new Set(),
      15,
    );
    expect(plan.spentFt).toBe(15);
    expect(plan.destination.col).toBeLessThan(4);
    expect(
      Math.min(
        plan.destination.row - 1,
        grid.height - plan.destination.row,
        plan.destination.col - 1,
        grid.width - plan.destination.col,
      ),
    ).toBeLessThanOrEqual(1);
  });

  it("moves into a legal cone position instead of stopping at numeric range", () => {
    const targeting = {
      shape: "cone" as const,
      rangeFt: 15,
      sizeFt: 15,
    };
    const plan = planTargetingPath(
      grid,
      { row: 1, col: 1 },
      { row: 5, col: 1 },
      new Set(),
      30,
      targeting,
    );
    expect(plan.spentFt).toBeGreaterThan(0);
    expect(plan.destination).not.toEqual({ row: 5, col: 1 });
  });
});
