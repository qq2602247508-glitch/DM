import { describe, expect, it } from "vitest";

import {
  actionEconomySummary,
  damageModifierLabel,
  deathSaveSummary,
} from "./combatPresentation";

describe("combat presentation", () => {
  it("labels damage modifiers for the DM", () => {
    expect(damageModifierLabel("resistance")).toBe("抗性减半");
    expect(damageModifierLabel("immunity")).toBe("免疫归零");
  });

  it("makes action economy readable", () => {
    expect(actionEconomySummary({
      action_available: true,
      bonus_action_available: false,
      reaction_available: true,
      movement_remaining_ft: 20,
    })).toBe("动作 可用 · 附赠 已用 · 反应 可用 · 移动 20尺");
  });

  it("makes pending death explicit", () => {
    expect(deathSaveSummary({
      successes: 1,
      failures: 3,
      stable: false,
      dead: false,
      pending_death_confirmation: true,
    })).toBe("成功 1/3 · 失败 3/3 · 等待 DM 确认死亡");
  });
});
