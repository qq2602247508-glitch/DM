import { describe, expect, it } from "vitest";

import { resolveAreaSavingThrows } from "./areaSpellResolution";

describe("area spell resolution", () => {
  it("keeps mixed damage segments independent for save halves", () => {
    const result = resolveAreaSavingThrows({
      targets: [
        { id: "failed", name: "失败者", savingThrows: { dexterity: 0 } },
        { id: "saved", name: "成功者", savingThrows: { dexterity: 0 } },
      ],
      damageExpression: "1d6 + 1d8",
      damageType: "mixed",
      saveDc: 12,
      saveAbility: "dexterity",
      halfDamageOnSave: true,
      damageComponents: [
        { amount: 5, damage_type: "fire" },
        { amount: 7, damage_type: "force" },
      ],
      random: (() => {
        let index = 0;
        return () => [0.1, 0.7][index++] ?? 0.1;
      })(),
    });

    expect(result.damageComponents).toEqual([
      { amount: 5, damageType: "fire" },
      { amount: 7, damageType: "force" },
    ]);
    expect(result.targets[0]?.damage).toBe(12);
    expect(result.targets[0]?.damageComponents).toEqual([
      { amount: 5, damageType: "fire" },
      { amount: 7, damageType: "force" },
    ]);
    expect(result.targets[1]?.damage).toBe(5);
    expect(result.targets[1]?.damageComponents).toEqual([
      { amount: 2, damageType: "fire" },
      { amount: 3, damageType: "force" },
    ]);
  });

  it("preserves the legacy single damage input", () => {
    const result = resolveAreaSavingThrows({
      targets: [{ id: "target", name: "目标", abilityScores: { dexterity: 10 } }],
      damageExpression: "8d6",
      damageType: "fire",
      saveDc: 10,
      saveAbility: "dexterity",
      halfDamageOnSave: false,
      sharedDamage: 14,
      random: () => 0,
    });
    expect(result.sharedDamage).toBe(14);
    expect(result.damageType).toBe("fire");
    expect(result.targets[0]?.damage).toBe(14);
  });
});
