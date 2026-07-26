import { describe, expect, it } from "vitest";

import { resolveAreaSavingThrows } from "./areaSpellResolution";

function sequence(values: number[]): () => number {
  let index = 0;
  return () => values[index++] ?? 0;
}

describe("area spell resolution", () => {
  it("rolls 8d6 once and gives every target an independent save", () => {
    const result = resolveAreaSavingThrows({
      targets: [
        { id: "a", name: "夺心魔A", abilityScores: { dexterity: 12 } },
        { id: "b", name: "夺心魔B", abilityScores: { dexterity: 12 } },
        { id: "c", name: "夺心魔C", abilityScores: { dexterity: 12 } },
      ],
      damageExpression: "8d6",
      saveDc: 17,
      saveAbility: "dexterity",
      halfDamageOnSave: true,
      // Eight damage dice = 4 each (32); saves = 20, 10, 17 before +1.
      random: sequence([
        0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5,
        0.95, 0.45, 0.8,
      ]),
    });

    expect(result.damageRolls).toEqual([4, 4, 4, 4, 4, 4, 4, 4]);
    expect(result.sharedDamage).toBe(32);
    expect(result.targets.map((target) => target.saveTotal)).toEqual([21, 11, 18]);
    expect(result.targets.map((target) => target.damage)).toEqual([16, 32, 16]);
  });

  it("uses an explicit monster saving-throw modifier when available", () => {
    const result = resolveAreaSavingThrows({
      targets: [{
        id: "a",
        name: "敏捷熟练怪物",
        abilityScores: { dexterity: 10 },
        savingThrows: { dexterity: 5 },
      }],
      damageExpression: "1d6",
      saveDc: 15,
      saveAbility: "敏捷",
      halfDamageOnSave: false,
      random: sequence([0.5, 0.45]),
    });

    expect(result.targets[0]).toMatchObject({
      modifier: 5,
      saveTotal: 15,
      success: true,
      damage: 0,
    });
  });
});
