import { describe, expect, it } from "vitest";

import {
  actionEconomySummary,
  damageComponentsByTargetSummary,
  damageComponentsSummary,
  damageModifierLabel,
  deathSaveSummary,
} from "./combatPresentation";

describe("combat presentation", () => {
  it("labels damage modifiers for the DM", () => {
    expect(damageModifierLabel("resistance")).toBe("抗性减半");
    expect(damageModifierLabel("immunity")).toBe("免疫归零");
  });

  it("keeps each mixed-damage segment and its defense result visible", () => {
    expect(damageComponentsSummary([
      { damage_type: "fire", original_damage: 5, adjusted_damage: 2, modifier: "resistance" },
      { damage_type: "force", original_damage: 6, adjusted_damage: 6, modifier: "normal" },
    ])).toBe("火焰 5→2（抗性减半）；力场 6；合计 8");
    expect(damageComponentsByTargetSummary([
      { target_name: "目标甲", damage_components: [{ damage_type: "cold", original_damage: 4, adjusted_damage: 0, modifier: "immunity" }] },
    ])).toBe("目标甲：寒冷 4→0（免疫归零）；合计 0");
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
