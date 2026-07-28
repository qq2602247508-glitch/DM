import { describe, expect, it } from "vitest";

import { findSceneSpawnCells, generateTacticalSceneGrid } from "./sceneGridGenerator";

describe("generateTacticalSceneGrid", () => {
  it("creates a deterministic church with altar, pews and distinct spawn areas", () => {
    const first = generateTacticalSceneGrid("旧教堂", "祭坛旁有地窖入口");
    const second = generateTacticalSceneGrid("旧教堂", "祭坛旁有地窖入口");
    expect(first).toEqual(second);
    expect(first.theme).toContain("教堂");
    expect(first.cells.some((cell) => cell.label === "主祭坛")).toBe(true);
    expect(first.cells.filter((cell) => cell.label === "长椅").length).toBeGreaterThanOrEqual(16);
    expect(findSceneSpawnCells(first, "player")).toEqual([{ row: 10, col: 9 }]);
    expect(findSceneSpawnCells(first, "enemy")).toEqual([{ row: 3, col: 9 }]);
  });

  it("creates a recognizable tavern rather than the generic room", () => {
    const grid = generateTacticalSceneGrid("醉龙酒馆", "冒险者在大厅遭到伏击", "深水城");
    expect(grid.theme).toContain("酒馆");
    expect(grid.cells.some((cell) => cell.label === "木制吧台")).toBe(true);
    expect(grid.cells.some((cell) => cell.label === "酒桌")).toBe(true);
    expect(grid.cells.some((cell) => cell.label === "壁炉")).toBe(true);
    expect(grid.cells.some((cell) => cell.label === "酒馆正门")).toBe(true);
  });

  it.each([
    ["幽暗洞穴", "岩壁、狭窄通道和地下水", "洞穴", "狭窄岩隙"],
    ["迷雾森林", "林间空地发生遭遇", "森林", "倒木"],
    ["码头街道", "市集旁的小巷", "街道", "市场摊位"],
  ])("creates themed layout for %s", (name, description, theme, expectedFeature) => {
    const grid = generateTacticalSceneGrid(name, description);
    expect(grid.theme).toContain(theme);
    expect(grid.cells.some((cell) => cell.label === expectedFeature)).toBe(true);
    expect(findSceneSpawnCells(grid, "player")).toHaveLength(1);
    expect(findSceneSpawnCells(grid, "enemy")).toHaveLength(1);
  });

  it("uses location text when the scene title is generic", () => {
    const grid = generateTacticalSceneGrid("突然袭击", "敌人从门外冲入", "银鹿旅店酒馆");
    expect(grid.theme).toContain("酒馆");
  });

  it("keeps the SceneGrid dimensions and cell kinds compatible", () => {
    const grid = generateTacticalSceneGrid("遗迹", "多房间遭遇");
    expect(grid).toMatchObject({ width: 18, height: 12, cell_size_ft: 5 });
    expect(grid.theme).toContain("多房间");
    expect(grid.cells.filter((cell) => cell.kind === "door")).toHaveLength(5);
    expect(grid.cells.filter((cell) => (
      cell.kind === "floor" && /侧室|大厅|走廊|储藏室/.test(cell.label)
    )).length).toBeGreaterThanOrEqual(5);
    expect(grid.cells.some((cell) => cell.label === "西侧凸墙")).toBe(true);
    expect(grid.cells.some((cell) => cell.label === "东侧凸墙")).toBe(true);
    expect(grid.cells.filter((cell) => cell.blocks_sight).length).toBeGreaterThanOrEqual(3);
    expect(grid.cells.every((cell) => (
      ["floor", "wall", "cover", "door", "object"].includes(cell.kind)
      && cell.row >= 1 && cell.row <= grid.height
      && cell.col >= 1 && cell.col <= grid.width
    ))).toBe(true);
  });
});
