import { describe, expect, it } from "vitest";

import {
  getDoorOrientation,
  isMapVoidCell,
  shouldShowTerrainLabel,
  terrainCellClass,
} from "./mapPresentation";

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

  it("hides repetitive ground labels but keeps meaningful room markers", () => {
    expect(shouldShowTerrainLabel({ row: 1, col: 1, kind: "floor", label: "地板" })).toBe(false);
    expect(shouldShowTerrainLabel({ row: 1, col: 2, kind: "floor", label: "洞窟地面" })).toBe(false);
    expect(shouldShowTerrainLabel({ row: 1, col: 3, kind: "floor", label: "通道" })).toBe(false);
    expect(shouldShowTerrainLabel({ row: 1, col: 4, kind: "floor", label: "旅店木地板" })).toBe(false);
    expect(shouldShowTerrainLabel({ row: 1, col: 5, kind: "floor", label: "林间旧路" })).toBe(false);
    expect(shouldShowTerrainLabel({ row: 2, col: 1, kind: "room", label: "公共大厅" })).toBe(true);
    expect(shouldShowTerrainLabel({ row: 2, col: 2, kind: "stairs", label: "向上楼梯" })).toBe(true);
    expect(shouldShowTerrainLabel({ row: 2, col: 3, kind: "marker", label: "断桥西桥头" })).toBe(true);
  });

  it("uses the persisted dungeon theme instead of the generic scene palette", () => {
    const fungal = terrainCellClass(
      { row: 1, col: 1, kind: "room", label: "母菌核心" },
      "fungal",
    );
    const ocean = terrainCellClass(
      { row: 1, col: 1, kind: "room", label: "潮汐祭坛" },
      "ocean",
    );
    expect(fungal).toContain("purple");
    expect(ocean).toContain("blue");
    expect(fungal).not.toBe(ocean);
  });

  it("gives each Duskbell scene family a semantic palette", () => {
    expect(terrainCellClass(
      { row: 1, col: 1, kind: "water", label: "湍急溪流" },
      "rainy-forest-crossing",
    )).toContain("sky");
    expect(terrainCellClass(
      { row: 1, col: 1, kind: "room", label: "磨坊一层" },
      "dusk-mill-yard",
    )).toContain("amber");
    expect(terrainCellClass(
      { row: 1, col: 1, kind: "floor", label: "地下石地板" },
      "brass-gear-undercroft",
    )).toContain("zinc");
  });
});
