import { describe, expect, it } from "vitest";

import {
  abilityModifier,
  chooseEnemyActionIndex,
  chooseEnemyTarget,
  parseDiceExpression,
  parseRangeFeet,
  proficiencyBonus,
  proposeFreeformCheck,
  rollDiceExpression,
} from "./combatAutomation";

describe("combat automation helpers", () => {
  it("parses and rolls bounded dice expressions", () => {
    expect(parseDiceExpression("8d6+3 火焰")).toEqual({ count: 8, sides: 6, modifier: 3 });
    expect(rollDiceExpression({ count: 2, sides: 6, modifier: 1 }, () => 0)).toEqual({
      rolls: [1, 1],
      total: 3,
    });
  });

  it("derives range and modifiers", () => {
    expect(parseRangeFeet("150/600尺")).toBe(150);
    expect(abilityModifier(15)).toBe(2);
    expect(proficiencyBonus(5)).toBe(3);
  });

  it("proposes a transparent freeform check from the character sheet", () => {
    expect(proposeFreeformCheck("我试图说服守卫", { charisma: 16 }, 5, ["游说"])).toMatchObject({
      skill: "游说",
      modifier: 6,
      dc: 12,
    });
  });

  it("changes enemy target priorities by tactics", () => {
    const sturdy = { hp: 20, max_hp: 20, armor_class: 18 };
    const wounded = { hp: 3, max_hp: 10, armor_class: 14 };
    expect(chooseEnemyTarget([sturdy, wounded], "instinctive")).toBe(sturdy);
    expect(chooseEnemyTarget([sturdy, wounded], "smart")).toBe(wounded);
  });

  it("rotates real enemy actions and lets tactical enemies favor control damage", () => {
    const actions = [
      { name: "触须", damage: "2d10+4", range: "5尺" },
      { name: "心灵震爆", damage: "4d8+4", range: "60尺锥形", save_dc: 15 },
    ];
    expect(chooseEnemyActionIndex(actions, "standard", 0)).toBe(0);
    expect(chooseEnemyActionIndex(actions, "standard", 1)).toBe(1);
    expect(chooseEnemyActionIndex(actions, "tactical", 0)).toBe(1);
  });
});
