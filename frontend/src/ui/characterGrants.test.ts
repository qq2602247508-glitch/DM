import { describe, expect, it } from "vitest";

import type { Character, CharacterOptionsCatalog, RuleDocument } from "../api/types";
import {
  buildFeatureGrantDraft,
  buildItemGrantDraft,
  buildSkillGrantDraft,
  buildSpellGrantDraft,
  detectCharacterGrantIntent,
} from "./characterGrants";

const character: Character = {
  id: "c1", campaign_id: "camp", version: 1, name: "艾琳", race: "精灵",
  background: "贤者", class_name: "法师", level: 5, experience: 6500,
  armor_class: 13, speed: 30, ability_scores: {}, hp: 24, max_hp: 24,
  max_hp_reduction: 0, ability_score_reductions: {}, death_saves: { successes: 0, failures: 0 },
  inventory: [], equipment: [], proficiencies: [], skills: {}, features: [],
  actions: [], resources: {}, spells: [], spellcasting: {}, class_levels: { 法师: 5 },
  subclass_choices: {}, notes: null, created_at: "", updated_at: "",
};

const catalog: CharacterOptionsCatalog = {
  edition: 2024, officiality: "official", species: [], backgrounds: [], feats: [],
  skills: ["隐匿", "洞悉", "奥秘", "调查"], languages: [], tools: [],
  classes: [{
    name: "法师", source_record_id: "wizard", source_path: "玩家手册2024/职业/法师",
    hit_die: 6, subclasses: [],
    levels: [
      { level: 1, proficiency_bonus: 2, features: ["奥术恢复"], progression: {} },
      { level: 5, proficiency_bonus: 3, features: ["记忆法术"], progression: {} },
    ],
  }, {
    name: "战士", source_record_id: "fighter", source_path: "玩家手册2024/职业/战士",
    hit_die: 10, subclasses: [],
    levels: [{ level: 1, proficiency_bonus: 2, features: [], progression: {} }],
  }, {
    name: "游荡者", source_record_id: "rogue", source_path: "玩家手册2024/职业/游荡者",
    hit_die: 8, subclasses: [],
    levels: [
      { level: 1, proficiency_bonus: 2, features: ["专精"], progression: {} },
      { level: 6, proficiency_bonus: 3, features: ["专精"], progression: {} },
    ],
  }],
  spells: [{
    name: "火球术", source_record_id: "fireball", source_path: "玩家手册2024/法术详述/火球术",
    level: 3, classes: ["法师", "术士"], school: "塑能", casting_time: "动作",
    range: "150尺", components: "V、S、M", duration: "立即", concentration: false,
    ritual: false, damage_expression: "8d6", damage_type: "火焰", save_ability: "敏捷",
    half_damage_on_save: true, description: "爆炸范围内目标进行敏捷豁免。", cost: "动作",
    resource_key: "spell_slots_3", resource_cost: 1, resolution_kind: "damage",
  }, {
    name: "异界之门", source_record_id: "gate", source_path: "玩家手册2024/法术详述/异界之门",
    level: 9, classes: ["法师"], school: "咒法", casting_time: "动作", range: "60尺",
    components: "V、S", duration: "专注", concentration: true, ritual: false,
    damage_expression: null, damage_type: null, save_ability: null, half_damage_on_save: false,
    description: "开启传送门。", cost: "动作", resource_key: "spell_slots_9",
    resource_cost: 1, resolution_kind: "narrative",
  }],
};

describe("rule-validated character grants", () => {
  it("detects equipment and spell grants for a named character", () => {
    expect(detectCharacterGrantIntent("给艾琳一把长剑", [character])).toMatchObject({
      kind: "equipment", requestedName: "长剑", characterId: "c1",
    });
    expect(detectCharacterGrantIntent("让艾琳把火球术抄入法术书", [character])).toMatchObject({
      kind: "spell", requestedName: "火球术",
    });
  });

  it("allows a wizard to copy a legal leveled spell but blocks over-level spells", () => {
    const fireball = detectCharacterGrantIntent("让艾琳把火球术抄入法术书", [character]);
    const gate = detectCharacterGrantIntent("让艾琳把异界之门抄入法术书", [character]);
    if (!fireball || !gate) throw new Error("expected intents");
    expect(buildSpellGrantDraft(fireball, character, catalog)).toMatchObject({
      eligible: true, candidateName: "火球术", metadata: { prepared: false },
    });
    expect(buildSpellGrantDraft(gate, character, catalog)).toMatchObject({
      eligible: false,
    });
  });

  it("uses the wizard class level rather than total level for multiclass spell grants", () => {
    const multiclass = {
      ...character,
      class_name: "游荡者8 / 法师4",
      level: 12,
      class_levels: { 游荡者: 8, 法师: 4 },
    };
    const fireball = detectCharacterGrantIntent("让艾琳把火球术抄入法术书", [multiclass]);
    if (!fireball) throw new Error("expected intent");
    expect(buildSpellGrantDraft(fireball, multiclass, catalog).blockingReason).toContain("法师4级最高可用2环");
  });

  it("blocks non-wizard direct spell learning and arbitrary skill proficiency", () => {
    const bard = { ...character, class_name: "吟游诗人", class_levels: { 吟游诗人: 5 } };
    const spell = detectCharacterGrantIntent("让艾琳学会火球术", [bard]);
    const skill = detectCharacterGrantIntent("给艾琳添加隐匿熟练", [character]);
    if (!spell || !skill) throw new Error("expected intents");
    expect(buildSpellGrantDraft(spell, bard, catalog).blockingReason).toContain("不能绕过职业成长");
    expect(buildSkillGrantDraft(skill, character, catalog).blockingReason).toContain("不在法师");
  });

  it("fills only a real unused class or background skill choice", () => {
    const fighter = {
      ...character,
      class_name: "战士",
      class_levels: { 战士: 1 },
      level: 1,
      background: "守卫",
      skills: {
        运动: { proficient: true },
        察觉: { proficient: true },
        生存: { proficient: true },
      },
    };
    const legal = detectCharacterGrantIntent("给艾琳添加洞悉熟练", [fighter]);
    const illegal = detectCharacterGrantIntent("给艾琳添加奥秘熟练", [fighter]);
    if (!legal || !illegal) throw new Error("expected skill intents");
    expect(buildSkillGrantDraft(legal, fighter, catalog)).toMatchObject({
      eligible: true, candidateName: "洞悉",
    });
    expect(buildSkillGrantDraft(illegal, fighter, catalog).blockingReason).toContain("不在战士");
    expect(buildSkillGrantDraft(legal, {
      ...fighter,
      skills: { ...fighter.skills, 洞悉: { proficient: true } },
    }, catalog).eligible).toBe(false);
  });

  it("requires proficiency and an unused class entitlement for expertise", () => {
    const rogue = {
      ...character,
      class_name: "游荡者",
      class_levels: { 游荡者: 6 },
      level: 6,
      skills: {
        隐匿: { proficient: true, expertise: true },
        调查: { proficient: true },
      },
    };
    const expertise = detectCharacterGrantIntent("给艾琳添加调查专精", [rogue]);
    if (!expertise) throw new Error("expected expertise intent");
    expect(buildSkillGrantDraft(expertise, rogue, catalog)).toMatchObject({
      eligible: true, candidateName: "调查",
    });
    expect(buildSkillGrantDraft(expertise, {
      ...rogue,
      skills: {
        ...rogue.skills,
        调查: { proficient: true, expertise: true },
      },
    }, catalog).eligible).toBe(false);
  });

  it("only restores a missing class feature available at the current level", () => {
    const intent = detectCharacterGrantIntent("给艾琳补齐职业特性奥术恢复", [character]);
    if (!intent) throw new Error("expected intent");
    expect(buildFeatureGrantDraft(intent, character, catalog)).toMatchObject({
      eligible: true, candidateName: "奥术恢复",
    });
    expect(buildFeatureGrantDraft(intent, { ...character, features: ["奥术恢复"] }, catalog).eligible).toBe(false);
  });

  it("requires an exact official 2024 item record", () => {
    const intent = detectCharacterGrantIntent("奖励艾琳一瓶治疗药水", [character]);
    if (!intent) throw new Error("expected intent");
    const document = {
      stable_id: "potion", name: "药水", aliases: [], content_type: "items",
      source_url: "https://example.test/potion", canonical_url: "https://example.test/potion",
      repository_url: null, source_revision: null, source_ref: null,
      source_relative_path: "城主指南2024/治疗药水", source_license: "GPL-3.0",
      source_book: "地下城主指南 2024", edition: "2024", officiality: "official",
      heading_path: [], fragment: null,
      content_markdown: "", content_plain_text: "治疗药水（50 GP），重量 1/2磅。饮用后恢复生命值。",
      checksum: "x", fetched_at: "", spell: null, warnings: [],
    } satisfies RuleDocument;
    expect(buildItemGrantDraft(intent, document)).toMatchObject({
      eligible: true, metadata: { price_cp: 5000, unit_weight_lb: 0.5 },
    });
    expect(buildItemGrantDraft(intent, {
      ...document,
      content_markdown: "| 弩矢匣 | 1磅 | 1GP |  | 治疗药水 | 半磅 | 50GP |",
    })).toMatchObject({
      eligible: true, metadata: { price_cp: 5000, unit_weight_lb: 0.5 },
    });
    expect(buildItemGrantDraft(intent, { ...document, officiality: "third_party" }).eligible).toBe(false);
  });
});
