import { describe, expect, it } from "vitest";

import type { Scene } from "../api/types";
import {
  buildSceneFlow, buildSceneNotes, chapterOrderFromTitle, readSceneStoryOutline, sortScenesByOutline,
  type SceneStoryOutline,
} from "./sceneOutline";
import { generateTacticalSceneGrid } from "./sceneGridGenerator";

function scene(name: string, notes: string | null, createdAt: string): Scene {
  return {
    id: crypto.randomUUID(), campaign_id: "campaign", location_id: null,
    name, description: null, status: "active", notes, version: 1,
    created_at: createdAt, updated_at: createdAt,
  };
}

describe("scene outlines", () => {
  it("stores the story outline without losing the tactical grid", () => {
    const outline: SceneStoryOutline = {
      chapterTitle: "第一章", chapterOrder: 1, sceneOrder: 2,
      objective: "找到失踪者", opening: "雨夜抵达", development: "调查足迹",
      twist: "守卫说谎", climax: "发现暗门", transition: "前往地窖",
    };
    const notes = buildSceneNotes(generateTacticalSceneGrid("酒馆", "大厅"), outline);
    expect(readSceneStoryOutline(scene("酒馆", notes, "2026-01-01"), 1)).toEqual(outline);
    const parsed = JSON.parse(notes) as { scene_grid: { cells: unknown[] } };
    expect(parsed.scene_grid.cells.length).toBeGreaterThan(0);
  });

  it("sorts scenes by chapter and scene order", () => {
    const makeNotes = (chapterTitle: string, sceneOrder: number) => buildSceneNotes(
      generateTacticalSceneGrid("测试", "测试"),
      {
        chapterTitle, chapterOrder: chapterOrderFromTitle(chapterTitle), sceneOrder,
        objective: "", opening: "", development: "", twist: "", climax: "", transition: "",
      },
    );
    const ordered = sortScenesByOutline([
      scene("Scene 2", makeNotes("第一章", 2), "2026-01-02"),
      scene("Scene 1", makeNotes("第一章", 1), "2026-01-01"),
      scene("Scene 3", makeNotes("第二章", 1), "2026-01-03"),
    ]);
    expect(ordered.map((item) => item.name)).toEqual(["Scene 1", "Scene 2", "Scene 3"]);
  });

  it("compiles a detailed flow without exposing a fixed five-act UI", () => {
    const target = scene("酒馆", buildSceneNotes(
      generateTacticalSceneGrid("酒馆", "大厅"),
      {
        chapterTitle: "第一章", chapterOrder: 1, sceneOrder: 1,
        objective: "接受磨坊委托", opening: "雨夜进入酒馆",
        development: "老板展示失踪账本", twist: "钟声突然响起",
        climax: "决定是否出发", transition: "前往旧磨坊",
      },
    ), "2026-01-01");
    const flow = buildSceneFlow(target, 1);
    expect(flow.length).toBeGreaterThanOrEqual(5);
    expect(flow.map((step) => step.kind)).toContain("choice");
    expect(flow.length).toBeLessThan(9);
    expect(flow.at(-1)?.instruction).toBe("前往旧磨坊");

    const simple = scene("安静谈话", buildSceneNotes(
      generateTacticalSceneGrid("书房", "书房"),
      {
        chapterTitle: "第一章", chapterOrder: 1, sceneOrder: 2,
        objective: "确认是否同行", opening: "朋友前来道别",
        development: "由 DM 自由推进。", twist: "可选转折。",
        climax: "记录玩家决定", transition: "结束谈话",
      },
    ), "2026-01-02");
    expect(buildSceneFlow(simple, 2).length).not.toBe(flow.length);
  });
});
