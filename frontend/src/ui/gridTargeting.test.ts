import { describe, expect, it } from "vitest";

import {
  getTargetingCells,
  gridDistanceFt,
  isAimPointInRange,
  isBlockedCell,
} from "./gridTargeting";

const grid = { width: 18, height: 12, cell_size_ft: 5 as const };

describe("grid targeting helpers", () => {
  it("uses 5e square-grid diagonal distance", () => {
    expect(gridDistanceFt({ row: 2, col: 2 }, { row: 5, col: 5 })).toBe(15);
    expect(isAimPointInRange({ row: 2, col: 2 }, { row: 8, col: 8 }, 30)).toBe(true);
    expect(isAimPointInRange({ row: 2, col: 2 }, { row: 9, col: 8 }, 30)).toBe(false);
  });

  it("returns only the aimed cell for a single-target action", () => {
    expect(getTargetingCells(
      grid,
      { row: 2, col: 2 },
      { row: 7, col: 2 },
      { shape: "single", rangeFt: 30 },
    )).toEqual([{ row: 7, col: 2 }]);
  });

  it("returns an empty template when the aim point is out of casting range", () => {
    expect(getTargetingCells(
      grid,
      { row: 1, col: 1 },
      { row: 10, col: 10 },
      { shape: "circle", rangeFt: 30, sizeFt: 20 },
    )).toEqual([]);
  });

  it("creates a fireball-like radius around the selected impact point", () => {
    const cells = getTargetingCells(
      grid,
      { row: 2, col: 2 },
      { row: 6, col: 6 },
      { shape: "circle", rangeFt: 150, sizeFt: 20 },
    );
    expect(cells).toContainEqual({ row: 6, col: 6 });
    expect(cells).toContainEqual({ row: 6, col: 10 });
    expect(cells).not.toContainEqual({ row: 6, col: 11 });
  });

  it("creates directional cone and line templates", () => {
    const cone = getTargetingCells(
      grid,
      { row: 6, col: 4 },
      { row: 6, col: 8 },
      { shape: "cone", rangeFt: 30, sizeFt: 30 },
    );
    expect(cone).toContainEqual({ row: 6, col: 10 });
    expect(cone).toContainEqual({ row: 8, col: 8 });
    expect(cone).not.toContainEqual({ row: 6, col: 2 });

    const line = getTargetingCells(
      grid,
      { row: 6, col: 4 },
      { row: 6, col: 8 },
      { shape: "line", rangeFt: 120, sizeFt: 30, widthFt: 5 },
    );
    expect(line).toContainEqual({ row: 6, col: 10 });
    expect(line).not.toContainEqual({ row: 8, col: 8 });
  });

  it("detects walls as blocked cells", () => {
    expect(isBlockedCell(
      { ...grid, theme: "test", cells: [{ row: 3, col: 3, kind: "wall", label: "墙" }] },
      { row: 3, col: 3 },
    )).toBe(true);
  });

  it("matches the 12th-level wizard acceptance layout for Fireball and Lightning Bolt", () => {
    const wizard = { row: 6, col: 3 };
    const mindFlayers = [
      { id: "A", point: { row: 6, col: 9 } },
      { id: "B", point: { row: 6, col: 12 } },
      { id: "C", point: { row: 8, col: 10 } },
    ];
    const targetIds = (
      cells: ReturnType<typeof getTargetingCells>,
    ) => {
      const keys = new Set(cells.map((cell) => `${cell.row}:${cell.col}`));
      return mindFlayers
        .filter(({ point }) => keys.has(`${point.row}:${point.col}`))
        .map(({ id }) => id);
    };

    const fireball = getTargetingCells(
      grid,
      wizard,
      { row: 6, col: 10 },
      { shape: "circle", rangeFt: 150, sizeFt: 20 },
    );
    const lightningBolt = getTargetingCells(
      grid,
      wizard,
      { row: 6, col: 16 },
      { shape: "line", rangeFt: 100, sizeFt: 100, widthFt: 5 },
    );

    expect(targetIds(fireball)).toEqual(["A", "B", "C"]);
    expect(targetIds(lightningBolt)).toEqual(["A", "B"]);
  });
});
