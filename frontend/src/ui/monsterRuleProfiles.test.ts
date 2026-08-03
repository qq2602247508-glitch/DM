import { describe, expect, it } from "vitest";

import { monsterActionsForRules } from "./monsterRuleProfiles";

describe("official monster rule profiles", () => {
  it("uses the compatibility profile only when an old mind flayer snapshot has no actions", () => {
    const actions = monsterActionsForRules("夺心魔B", []);

    expect(actions).toEqual(expect.arrayContaining([
      expect.objectContaining({ name: "触须", damage: "4d8+4", attack_bonus: 7 }),
      expect.objectContaining({ name: "采脑", damage: "10d10", auto_eligible: false }),
      expect.objectContaining({
        name: "心灵震爆",
        damage: "6d8+4",
        save_dc: 15,
        save_ability: "intelligence",
      }),
    ]));
  });

  it("does not overwrite parsed compendium actions with the compatibility profile", () => {
    const recorded = [{ name: "新版触须", damage: "5d8+4", action_type: "action" as const }];
    expect(monsterActionsForRules("夺心魔B", recorded)).toBe(recorded);
  });

  it("keeps recorded actions for unrelated monsters", () => {
    const recorded = [{ name: "啃咬", damage: "1d8+3" }];
    expect(monsterActionsForRules("恐狼", recorded)).toBe(recorded);
  });
});
