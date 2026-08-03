import { describe, expect, it } from "vitest";

import {
  abilityGenerationIsValid,
  classSkillSelection,
  isPreparedCombatSpell,
  rolledAbilityScore,
  spellChoicesComplete,
  spellIsAvailable,
  spellSelectionRule,
  spellToCharacterAction,
} from "./characterRules";

describe("2024 character creation limits", () => {
  it("validates standard array, point buy, and auditable 4d6 rolls", () => {
    const standard = { strength: 15, dexterity: 14, constitution: 13, intelligence: 12, wisdom: 10, charisma: 8 };
    const pointBuy = { strength: 15, dexterity: 14, constitution: 13, intelligence: 12, wisdom: 10, charisma: 8 };
    const rolls = {
      strength: [6, 6, 6, 1], dexterity: [6, 5, 4, 1], constitution: [5, 5, 4, 1],
      intelligence: [4, 4, 4, 1], wisdom: [4, 4, 3, 1], charisma: [3, 3, 3, 1],
    };
    const rolled = {
      strength: 18, dexterity: 15, constitution: 14, intelligence: 12, wisdom: 11, charisma: 9,
    };

    expect(abilityGenerationIsValid("standard_array", standard, {})).toBe(true);
    expect(abilityGenerationIsValid("point_buy", pointBuy, {})).toBe(true);
    expect(abilityGenerationIsValid("rolled_4d6_drop_lowest", rolled, rolls)).toBe(true);
    expect(rolledAbilityScore([6, 6, 6, 1])).toBe(18);
    expect(abilityGenerationIsValid("rolled_4d6_drop_lowest", { ...rolled, wisdom: 12 }, rolls)).toBe(false);
  });

  it("requires wizard skill choices and removes background duplicates", () => {
    const rule = classSkillSelection("法师", ["奥秘", "历史"]);
    expect(rule.count).toBe(2);
    expect(rule.choices).not.toContain("奥秘");
    expect(rule.choices).not.toContain("历史");
    expect(rule.choices).toContain("调查");
  });

  it("enforces cantrip and leveled-spell limits separately", () => {
    const spells = [
      ...Array.from({ length: 3 }, (_, index) => ({ source_record_id: `c${index}`, level: 0 })),
      ...Array.from({ length: 6 }, (_, index) => ({ source_record_id: `s${index}`, level: 1 })),
    ];
    expect(spellSelectionRule("法师")).toMatchObject({
      cantrips: 3,
      leveled: 6,
      preparedLeveled: 4,
    });
    expect(spellChoicesComplete("法师", spells.map((spell) => spell.source_record_id), spells)).toBe(true);
    expect(spellChoicesComplete("法师", spells.slice(0, 8).map((spell) => spell.source_record_id), spells)).toBe(false);
  });

  it("keeps cantrips and prepared spells in combat but hides unprepared leveled spells", () => {
    expect(isPreparedCombatSpell({ spell_level: 0, prepared: false })).toBe(true);
    expect(isPreparedCombatSpell({ spell_level: 1, prepared: true })).toBe(true);
    expect(isPreparedCombatSpell({ spell_level: 1, prepared: false })).toBe(false);
    expect(isPreparedCombatSpell({ spell_level: 1 })).toBe(true);
  });

  it("keeps only class spells and turns rule metadata into a combat action", () => {
    const fireball = {
      name: "火球术",
      source_record_id: "fireball",
      source_path: "玩家手册2024/法术详述/3环.htm",
      level: 3,
      classes: ["术士", "法师"],
      school: "塑能",
      casting_time: "动作",
      range: "150尺",
      components: "V、S、M",
      duration: "立即",
      concentration: false,
      ritual: false,
      damage_expression: "8d6",
      damage_type: "火焰",
      save_ability: "敏捷",
      half_damage_on_save: true,
      description: "半径20尺球状区域内的每个生物进行敏捷豁免。",
      cost: "动作",
      resource_key: "spell_slots_3",
      resource_cost: 1,
      resolution_kind: "damage" as const,
    };
    expect(spellIsAvailable({ ...fireball, level: 1 }, "法师")).toBe(true);
    expect(spellIsAvailable({ ...fireball, level: 1 }, "牧师")).toBe(false);
    expect(spellToCharacterAction(fireball, 17)).toMatchObject({
      prepared: true,
      damage: "8d6",
      range: "150尺",
      save_ability: "敏捷",
      save_dc: 17,
      half_damage_on_save: true,
      resource_key: "spell_slots_3",
    });
  });
});
