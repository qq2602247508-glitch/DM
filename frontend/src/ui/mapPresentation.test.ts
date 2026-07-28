import { describe, expect, it } from "vitest";

import { getDoorOrientation, isMapVoidCell, terrainCellClass } from "./mapPresentation";

describe("mapPresentation", () => {
  it("orients a door along the wall it interrupts", () => {
    expect(getDoorOrientation([
      { row: 1, col: 2, kind: "wall" },
      { row: 2, col: 2, kind: "door" },
      { row: 3, col: 2, kind: "wall" },
    ], 2, 2)).toBe("vertical");
    expect(getDoorOrientation([
      { row: 2, col: 1, kind: "wall" },
      { row: 2, col: 2, kind: "door" },
      { row: 2, col: 3, kind: "wall" },
    ], 2, 2)).toBe("horizontal");
  });

  it("renders out-of-map cells as dark blocked space", () => {
    const cell = { row: 1, col: 1, kind: "wall", label: "地图外区域" };
    expect(isMapVoidCell(cell)).toBe(true);
    expect(terrainCellClass(cell)).toContain("bg-black");
  });
});
