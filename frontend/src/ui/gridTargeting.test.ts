import { describe, expect, it } from "vitest";

import {
  availableElevationLayers,
  evaluateTargetingElevation,
  explicitElevationFt,
  getTargetingCells,
  gridDistanceFt,
  hasLineOfSight,
  isAimPointInRange,
  isBlockedCell,
} from "./gridTargeting";

const grid = { width: 18, height: 12, cell_size_ft: 5 as const };

describe("grid targeting helpers", () => {
  it("exposes ground and every saved combat elevation as selectable map layers", () => {
    expect(availableElevationLayers([
      { row: 3, col: 4, elevation_ft: 10 },
      { row: 4, col: 4, elevation_ft: 5 },
      { row: 5, col: 4 },
      { row: 6, col: 4, elevation_ft: 10 },
    ])).toEqual([0, 5, 10]);
    expect(explicitElevationFt({ row: 3, col: 4, elevation_ft: 5 })).toBe(5);
    expect(explicitElevationFt({ row: 3, col: 4 })).toBeNull();
  });

  it("filters a three-dimensional cylinder by its anchor height and fails closed for unknown altitude", () => {
    const template = {
      shape: "cylinder" as const,
      rangeFt: 60,
      sizeFt: 20,
      heightFt: 15,
      anchorHeightFt: 0,
      requiresElevation: true,
    };
    const common = [grid, { row: 5, col: 2 }, { row: 5, col: 5 }, { row: 5, col: 5 }, template, 10] as const;

    expect(evaluateTargetingElevation(...common, 10)).toMatchObject({ applies: true, valid: true, status: "within_volume" });
    expect(evaluateTargetingElevation(...common, 30)).toMatchObject({ applies: true, valid: false, status: "outside_volume" });
    expect(evaluateTargetingElevation(...common, null)).toMatchObject({ applies: true, valid: false, status: "missing_target_elevation" });
  });

  it("keeps established two-dimensional area previews when no vertical data was supplied", () => {
    expect(evaluateTargetingElevation(
      grid,
      { row: 2, col: 2 },
      { row: 6, col: 6 },
      { row: 6, col: 6 },
      { shape: "circle", rangeFt: 150, sizeFt: 20 },
      null,
      null,
    )).toEqual({ applies: false, valid: true, status: "not_applicable" });
  });

  it("fails closed for a player area target whose saved elevation is outside the volume", () => {
    const template = {
      shape: "circle" as const,
      rangeFt: 120,
      sizeFt: 20,
      anchorHeightFt: 10,
      requiresElevation: true,
    };
    expect(evaluateTargetingElevation(
      grid,
      { row: 2, col: 2 },
      { row: 6, col: 6 },
      { row: 6, col: 6 },
      template,
      0,
      25,
    )).toMatchObject({ applies: true, valid: true, status: "within_volume" });
    expect(evaluateTargetingElevation(
      grid,
      { row: 2, col: 2 },
      { row: 6, col: 6 },
      { row: 6, col: 6 },
      template,
      0,
      40,
    )).toMatchObject({ applies: true, valid: false, status: "outside_volume" });
  });

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

  it("uses Euclidean membership for a spherical volume, not movement distance", () => {
    const cells = getTargetingCells(
      grid,
      { row: 2, col: 2 },
      { row: 6, col: 6 },
      { shape: "circle", rangeFt: 150, sizeFt: 20 },
    );
    // Three diagonal squares are 15 ft by 15 ft from the centre: outside a
    // 20 ft sphere even though 5e movement distance calls it 15 ft.
    expect(cells).not.toContainEqual({ row: 9, col: 9 });
  });

  it("uses the authoritative one-square diagonal rule for spherical previews", () => {
    const cells = getTargetingCells(
      grid,
      { row: 2, col: 2 },
      { row: 6, col: 6 },
      { shape: "circle", rangeFt: 150, sizeFt: 20 },
    );
    expect(cells).toContainEqual({ row: 8, col: 8 });
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

  it("renders a self-origin 15-foot cube around the caster", () => {
    const cells = getTargetingCells(
      grid,
      { row: 6, col: 6 },
      { row: 6, col: 6 },
      { shape: "cube", rangeFt: 0, sizeFt: 15, originSelf: true },
    );
    expect(cells).toHaveLength(9);
    expect(cells).toContainEqual({ row: 6, col: 6 });
    expect(cells).toContainEqual({ row: 5, col: 5 });
    expect(cells).not.toContainEqual({ row: 4, col: 6 });
  });

  it("orients a self-origin cube toward the selected direction", () => {
    const cells = getTargetingCells(
      grid,
      { row: 6, col: 6 },
      { row: 6, col: 3 },
      { shape: "cube", rangeFt: 0, sizeFt: 15, originSelf: true },
    );
    expect(cells).toContainEqual({ row: 6, col: 3 });
    expect(cells).toContainEqual({ row: 5, col: 4 });
    expect(cells).not.toContainEqual({ row: 6, col: 8 });
  });

  it("detects walls as blocked cells", () => {
    expect(isBlockedCell(
      { ...grid, theme: "test", cells: [{ row: 3, col: 3, kind: "wall", label: "墙" }] },
      { row: 3, col: 3 },
    )).toBe(true);
  });

  it("blocks single targets behind walls but not targets before the wall", () => {
    const walledGrid = {
      ...grid,
      theme: "多房间",
      cells: [{ row: 4, col: 5, kind: "wall" as const, label: "隔墙" }],
    };
    expect(hasLineOfSight(walledGrid, { row: 4, col: 2 }, { row: 4, col: 4 })).toBe(true);
    expect(hasLineOfSight(walledGrid, { row: 4, col: 2 }, { row: 4, col: 8 })).toBe(false);
    expect(getTargetingCells(
      walledGrid,
      { row: 4, col: 2 },
      { row: 4, col: 8 },
      { shape: "single", rangeFt: 60 },
    )).toEqual([]);
  });

  it("treats explicitly tall cover as total sight blocking terrain", () => {
    const coverGrid = {
      ...grid,
      theme: "遗迹",
      cells: [{
        row: 4,
        col: 5,
        kind: "cover" as const,
        label: "落地书架",
        blocks_sight: true,
      }],
    };
    expect(hasLineOfSight(coverGrid, { row: 4, col: 2 }, { row: 4, col: 8 })).toBe(false);
  });

  it("prevents an area effect from reaching cells behind a hard wall", () => {
    const walledGrid = {
      ...grid,
      theme: "分隔房间",
      cells: Array.from({ length: 12 }, (_, index) => ({
        row: index + 1,
        col: 8,
        kind: "wall" as const,
        label: "石墙",
      })),
    };
    const cells = getTargetingCells(
      walledGrid,
      { row: 6, col: 2 },
      { row: 6, col: 6 },
      { shape: "circle", rangeFt: 150, sizeFt: 20 },
    );
    expect(cells).toContainEqual({ row: 6, col: 7 });
    expect(cells).not.toContainEqual({ row: 6, col: 9 });
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
