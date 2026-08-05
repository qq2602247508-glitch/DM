import { describe, expect, it } from "vitest";

import {
  actionDamageLabel,
  abilityModifier,
  combatantFaction,
  chooseEnemyActionIndex,
  chooseEnemyTarget,
  criticalDamageExpression,
  hasAutomaticCriticalCondition,
  expandMonsterAction,
  executableTargetIds,
  forcedMovementFromAction,
  hasGridPosition,
  isEnemyAiControlledCombatant,
  isPlayerControlledCombatant,
  parseDiceExpression,
  parseRechargeRange,
  parseRangeFeet,
  proficiencyBonus,
  proposeFreeformCheck,
  isRechargeAvailable,
  rollDiceExpression,
  rollStructuredDamage,
} from "./combatAutomation";

describe("criticalDamageExpression", () => {
  it("doubles dice terms without doubling modifiers", () => {
    expect(criticalDamageExpression("1d8+2d6+3")).toBe("2d8+4d6+3");
  });

  it("rolls doubled dice per damage segment without doubling fixed modifiers", () => {
    expect(rollStructuredDamage({
      damage_components: [
        { expression: "1d6+3", damage_type: "fire" },
        { expression: "1d8+2", damage_type: "force" },
      ],
    }, () => 0, true)).toEqual({
      components: [
        { amount: 5, damage_type: "fire" },
        { amount: 4, damage_type: "force" },
      ],
      total: 9,
      damageType: "mixed",
    });
  });
});

describe("hasAutomaticCriticalCondition", () => {
  it("recognizes structured and localized paralyzed/unconscious conditions", () => {
    expect(hasAutomaticCriticalCondition(["麻痹"])).toBe(true);
    expect(hasAutomaticCriticalCondition([{ condition_name: "unconscious" }])).toBe(true);
    expect(hasAutomaticCriticalCondition(["prone"])).toBe(false);
  });
});

describe("actionDamageLabel", () => {
  it("does not request damage dice for a summon with no damage block", () => {
    expect(actionDamageLabel({
      name: "召唤小火元素",
      resolution_kind: "control",
      rule_plan: { blocks: [{ kind: "summon", creature_ref: "小火元素" }] },
    })).toBe("无直接伤害");
  });

  it("keeps an unstructured attacking action visible as a DM review item", () => {
    expect(actionDamageLabel({ name: "未知攻击", cost: "动作" })).toBe("伤害骰未明确");
  });

  it("projects explicit compound damage expressions", () => {
    expect(actionDamageLabel({
      damage_components: [
        { expression: "2d6", damage_type: "fire" },
        { expression: "1d6", damage_type: "force" },
      ],
    })).toBe("2d6+1d6");
  });
});

describe("combat automation helpers", () => {
  it("does not treat an unplaced summon as a map target", () => {
    expect(hasGridPosition({ grid_position: { row: 5, col: 4 } })).toBe(true);
    expect(hasGridPosition({ grid_position: null })).toBe(false);
    expect(hasGridPosition({})).toBe(false);
  });

  it("keeps player summons out of the enemy AI boundary", () => {
    expect(isPlayerControlledCombatant("companion", { controller: "player" })).toBe(true);
    expect(isPlayerControlledCombatant("companion", { controller: "dm" })).toBe(false);
    expect(isPlayerControlledCombatant("monster", { controller: "player" })).toBe(true);
  });

  it("only opts hostile basic-AI summons into the enemy turn", () => {
    expect(isEnemyAiControlledCombatant("monster", { disposition: "enemy" })).toBe(true);
    expect(isEnemyAiControlledCombatant("companion", {
      controller: "dm",
      disposition: "enemy",
      enemy_ai_mode: "basic",
    })).toBe(true);
    expect(isEnemyAiControlledCombatant("companion", {
      controller: "dm",
      disposition: "enemy",
      enemy_ai_mode: "dm_only",
    })).toBe(false);
    expect(isEnemyAiControlledCombatant("companion", {
      controller: "dm",
      disposition: "ally",
      enemy_ai_mode: "basic",
    })).toBe(false);
  });

  it("uses disposition instead of controller to separate combat targets", () => {
    expect(combatantFaction("companion", { controller: "dm", disposition: "ally" })).toBe("ally");
    expect(combatantFaction("companion", { controller: "dm", disposition: "enemy" })).toBe("enemy");
    expect(combatantFaction("monster", {})).toBe("enemy");
  });

  it("uses the map's horizontal coverage for ordinary 2-D actions after movement", () => {
    const staleVertical = new Set<string>();
    const horizontal = new Set(["player"]);
    expect(executableTargetIds(staleVertical, horizontal)).toBe(horizontal);
    expect(executableTargetIds(staleVertical, horizontal, true)).toBe(staleVertical);
  });

  it("carries forced movement from compiled spell blocks into the DM combat path", () => {
    expect(forcedMovementFromAction({
      name: "雷鸣波",
      rule_plan: {
        blocks: [
          { kind: "damage", expression: "2d8", damage_type: "thunder" },
          { kind: "move", movement_type: "forced", distance_ft: 10, direction: "away" },
        ],
      },
    })).toEqual({ distance_ft: 10, direction: "away" });
    expect(forcedMovementFromAction({
      name: "成功即无位移",
      movement: { distance_ft: 10, type: "forced", direction: "toward" },
    })).toEqual({ distance_ft: 10, direction: "toward" });
    expect(forcedMovementFromAction({ name: "没有明确位移" })).toBeNull();
  });

  it("parses and rolls bounded dice expressions", () => {
    expect(parseDiceExpression("8d6+3 火焰")).toEqual({ count: 8, sides: 6, modifier: 3 });
    expect(rollDiceExpression({ count: 2, sides: 6, modifier: 1 }, () => 0)).toEqual({
      rolls: [1, 1],
      total: 3,
    });
  });

  it("rolls every typed damage segment independently", () => {
    expect(rollStructuredDamage({
      name: "寒火爆裂",
      damage_components: [
        { expression: "1d6", damage_type: "fire" },
        { expression: "1d8+1", damage_type: "cold" },
      ],
    }, () => 0)).toEqual({
      components: [
        { amount: 1, damage_type: "fire" },
        { amount: 2, damage_type: "cold" },
      ],
      total: 3,
      damageType: "mixed",
    });
  });

  it("keeps recharge actions available initially, then respects the persisted recharge gate", () => {
    const breath = { name: "火焰吐息", damage: "6d6", recharge: "5–6" };
    expect(parseRechargeRange(breath.recharge)).toEqual({ minimum: 5, maximum: 6 });
    expect(parseRechargeRange({ minimum: 5, maximum: 6 })).toEqual({ minimum: 5, maximum: 6 });
    expect(isRechargeAvailable(breath, undefined)).toBe(true);
    expect(isRechargeAvailable(breath, { 火焰吐息: false })).toBe(false);
    expect(isRechargeAvailable(breath, { 火焰吐息: true })).toBe(true);
    expect(chooseEnemyActionIndex(
      [breath, { name: "爪击", damage: "1d6" }],
      "standard",
      0,
      { 火焰吐息: false },
    )).toBe(1);
  });

  it("expands only fully linked multiattack sequences", () => {
    const actions = [
      {
        name: "多重攻击",
        multiattack: true,
        multiattack_count: 3,
        multiattack_components: [
          { action_name: "啃咬", count: 1 },
          { action_name: "爪击", count: 2 },
        ],
      },
      { name: "啃咬", damage: "1d10+4", auto_eligible: true },
      { name: "爪击", damage: "2d6+4", auto_eligible: true },
    ];
    expect(expandMonsterAction(actions, 0)?.map((step) => step.action.name)).toEqual([
      "啃咬",
      "爪击",
      "爪击",
    ]);
    expect(expandMonsterAction([{ ...actions[0], multiattack_count: 4 }, ...actions.slice(1)], 0)).toBeNull();
  });

  it("never selects reactions, legendary actions, or lair actions as a normal turn action", () => {
    const actions = [
      { name: "反击", action_type: "reaction" as const, damage: "9d6", auto_eligible: true },
      { name: "尾击", action_type: "legendary_action" as const, damage: "8d6", auto_eligible: true },
      { name: "震地", action_type: "lair_action" as const, damage: "7d6", auto_eligible: true },
      { name: "爪击", action_type: "action" as const, damage: "1d6", auto_eligible: true },
    ];
    expect(chooseEnemyActionIndex(actions, "tactical", 0)).toBe(3);
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
      conditionsOnSuccess: [],
      effectLabel: null,
    });
  });

  it("compiles common freeform combat effects into safe rule-block fields", () => {
    expect(proposeFreeformCheck("我撒泡尿让怪物滑倒", { strength: 16 }, 5, ["运动"]))
      .toMatchObject({
        skill: "运动",
        conditionsOnSuccess: ["prone"],
        conditionDuration: "target_turn_end",
        movementOnSuccessFt: null,
        effectLabel: "倒地",
      });
    expect(proposeFreeformCheck("我用盾牌把怪物推开", { strength: 16 }, 5, []))
      .toMatchObject({
        conditionsOnSuccess: [],
        movementOnSuccessFt: 5,
        movementDirection: "away",
        effectLabel: "推离 5 尺",
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

  it("does not auto-select a conditional action before its prerequisite exists", () => {
    const actions = [
      { name: "触须", damage: "4d8+4", range: "5尺" },
      { name: "采脑", damage: "10d10", range: "5尺", auto_eligible: false },
      { name: "心灵震爆", damage: "6d8+4", range: "60尺锥形", save_dc: 15 },
    ];
    expect(chooseEnemyActionIndex(actions, "standard", 1)).toBe(2);
    expect(chooseEnemyActionIndex(actions, "tactical", 0)).toBe(2);
  });
});
