import { describe, expect, it } from "vitest";

import type { SceneGrid } from "../api/types";
import { planApproachPath, shortestMovementPath } from "./combatMovement";

const grid: SceneGrid = {
  width: 8,
  height: 8,
  cell_size_ft: 5,
  theme: "测试战场",
  cells: [{ row: 2, col: 2, kind: "wall", label: "墙" }],
};

describe("combat movement", () => {
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
});
