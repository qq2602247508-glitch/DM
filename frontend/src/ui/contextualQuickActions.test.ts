import { describe, expect, it } from "vitest";

import { buildContextualQuickActions } from "./contextualQuickActions";
import type { SceneStoryOutline } from "./sceneOutline";

const outline: SceneStoryOutline = {
  chapterTitle: "第一章",
  chapterOrder: 1,
  sceneOrder: 1,
  objective: "让玩家在酒馆相识",
  opening: "介绍喧闹酒馆",
  development: "老板带来委托",
  twist: "地精撞破窗户",
  climax: "保护酒馆客人",
  transition: "追踪逃走的地精",
};

describe("contextual quick actions", () => {
  it("changes choices with the selected story phase and present monsters", () => {
    const opening = buildContextualQuickActions({
      sceneName: "小酒馆",
      outline,
      phase: "opening",
      participants: [],
    });
    const twist = buildContextualQuickActions({
      sceneName: "小酒馆",
      outline,
      phase: "twist",
      participants: [{ entity_type: "monster", name: "地精" }],
    });
    expect(opening.join(" ")).toContain("开场");
    expect(twist.join(" ")).toContain("地精");
    expect(twist).not.toEqual(opening);
  });
});
