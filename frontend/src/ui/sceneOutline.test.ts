import { describe, expect, it } from "vitest";

import type { Scene } from "../api/types";
import {
  buildSceneNotes, chapterOrderFromTitle, readSceneStoryOutline, sortScenesByOutline,
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
});
