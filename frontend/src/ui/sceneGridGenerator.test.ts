import { describe, expect, it } from "vitest";

import { generateTacticalSceneGrid } from "./sceneGridGenerator";

describe("generateTacticalSceneGrid", () => {
  it("creates a deterministic large multi-room church grid", () => {
    const first = generateTacticalSceneGrid("旧教堂", "祭坛旁有地窖入口");
    const second = generateTacticalSceneGrid("旧教堂", "祭坛旁有地窖入口");
    expect(first).toEqual(second);
    expect(first.width).toBe(18);
    expect(first.height).toBe(12);
    expect(first.cells.some((cell) => cell.kind === "door" && cell.row < first.height)).toBe(true);
    expect(first.cells.some((cell) => cell.label === "祭坛")).toBe(true);
  });
});
