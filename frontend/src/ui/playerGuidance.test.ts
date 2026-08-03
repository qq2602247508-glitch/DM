import { describe, expect, it } from "vitest";

import { buildPlayerGuidance } from "./playerGuidance";

describe("buildPlayerGuidance", () => {
  it("creates player-safe opening guidance without private DM details", () => {
    const guidance = buildPlayerGuidance({
      sceneName: "提灯旅店",
      phase: "opening",
      reason: "scene_entered",
    });
    expect(guidance.title).toBe("已进入「提灯旅店」 · 轮到你们回应");
    expect(guidance.suggestions).toHaveLength(3);
    expect(guidance.suggestions.join(" ")).not.toMatch(/秘密|DM提示|副 DM/);
  });

  it("changes suggestions with the current scene phase", () => {
    const twist = buildPlayerGuidance({
      sceneName: "钟楼",
      phase: "twist",
      reason: "flow_advanced",
    });
    const transition = buildPlayerGuidance({
      sceneName: "钟楼",
      phase: "transition",
      reason: "flow_advanced",
    });
    expect(twist.suggestions).not.toEqual(transition.suggestions);
    expect(transition.suggestions.join(" ")).toContain("离开前");
  });
});
