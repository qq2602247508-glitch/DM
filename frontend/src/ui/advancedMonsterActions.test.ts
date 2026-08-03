import { describe, expect, it } from "vitest";

import type { Combatant } from "../api/types";
import type { CombatActionLike } from "./combatAutomation";
import {
  BACKEND_THREE_DIMENSIONAL_REVIEW_LABEL,
  advancedActionPhase,
  advancedActionPendingRollSummary,
  evaluateAdvancedAreaTargeting,
  evaluateAdvancedActionAvailability,
  isAdvancedAreaAction,
} from "./advancedMonsterActions";

const NOW = "2026-08-02T00:00:00Z";

function combatant(overrides: Partial<Combatant> = {}): Combatant {
  return {
    id: "monster-1",
    campaign_id: "campaign-1",
    combat_id: "combat-1",
    display_name: "黑龙",
    entity_type: "monster",
    entity_id: "monster-1",
    initiative: 18,
    armor_class: 18,
    hp: 100,
    max_hp: 100,
    temporary_hp: 0,
    max_hp_reduction: 0,
    damage_resistances: [],
    damage_vulnerabilities: [],
    damage_immunities: [],
    condition_immunities: [],
    conditions: [],
    concentration: {},
    speed_ft: 30,
    movement_remaining_ft: 30,
    action_available: true,
    bonus_action_available: true,
    reaction_available: true,
    snapshot_json: {},
    is_active: true,
    created_at: NOW,
    updated_at: NOW,
    version: 1,
    ...overrides,
  };
}

describe("advanced monster action UI gates", () => {
  it("filters an advanced cylinder independently of a two-dimensional target set", () => {
    const actor = combatant({
      snapshot_json: { grid_position: { row: 5, col: 2, elevation_ft: 10 } },
    });
    const low = combatant({
      id: "low-target",
      display_name: "低空目标",
      entity_type: "character",
      snapshot_json: { grid_position: { row: 5, col: 5, elevation_ft: 10 } },
    });
    const high = combatant({
      id: "high-target",
      display_name: "高空目标",
      entity_type: "character",
      snapshot_json: { grid_position: { row: 5, col: 5, elevation_ft: 30 } },
    });
    const action: CombatActionLike = {
      name: "熔火柱",
      action_type: "legendary_action",
      area_shape: "cylinder",
      area_size_ft: 20,
      area_height_ft: 15,
      area_anchor_height_ft: 0,
      save_dc: 15,
      save_ability: "dexterity",
      affects_multiple_targets: true,
      damage: "2d6",
      damage_type: "fire",
    };

    const result = evaluateAdvancedAreaTargeting(action, actor, [low, high], {
      anchorPoint: { row: 5, col: 5 },
      horizontalTargetIds: new Set([low.id, high.id]),
      // Deliberately include the high target here: vertical data, not the
      // existing 2-D candidate set, must keep it out of the action.
      validTargetIds: new Set([low.id, high.id]),
    });

    expect(isAdvancedAreaAction(action)).toBe(true);
    expect(BACKEND_THREE_DIMENSIONAL_REVIEW_LABEL).toBe("后端权威三维复核");
    expect(result.ready).toBe(true);
    expect(result.eligibleTargetIds).toEqual(new Set([low.id]));
    expect(result.excludedTargetIds).toEqual(new Set([high.id]));
    expect(result.verticalSummary).toBe("0–15尺");
  });

  it("blocks advanced area selection when height metadata or a target altitude is missing", () => {
    const actor = combatant({
      snapshot_json: { grid_position: { row: 5, col: 2, elevation_ft: 10 } },
    });
    const unknownHeightTarget = combatant({
      id: "unknown-height",
      display_name: "未标高目标",
      entity_type: "character",
      snapshot_json: { grid_position: { row: 5, col: 5 } },
    });
    const action: CombatActionLike = {
      name: "不完整熔火柱",
      action_type: "lair_action",
      area_shape: "cylinder",
      area_size_ft: 20,
      area_anchor_height_ft: 0,
      save_dc: 15,
      save_ability: "dexterity",
      affects_multiple_targets: true,
    };

    const result = evaluateAdvancedAreaTargeting(action, actor, [unknownHeightTarget], {
      anchorPoint: { row: 5, col: 5 },
      horizontalTargetIds: new Set([unknownHeightTarget.id]),
      validTargetIds: new Set([unknownHeightTarget.id]),
      missingElevationTargetIds: new Set([unknownHeightTarget.id]),
    });

    expect(result.ready).toBe(false);
    expect(result.eligibleTargetIds).toEqual(new Set());
    expect(result.blockingReasons).toEqual(expect.arrayContaining([
      "圆柱区域缺少明确 height，不能自动选择上下层目标",
      "目标缺少 grid_position.elevation_ft：未标高目标",
    ]));
  });

  it("blocks a reaction until its trigger is explicitly supplied", () => {
    const action: CombatActionLike = {
      name: "借机攻击",
      action_type: "reaction",
      damage: "1d8+4",
      damage_type: "slashing",
    };
    const result = evaluateAdvancedActionAvailability(
      combatant(),
      action,
      combatant({ id: "player-1", entity_type: "character" }),
      1,
      0,
      false,
    );

    expect(advancedActionPhase(action)).toBe("reaction");
    expect(result?.available).toBe(false);
    expect(result?.blockingReasons).toContain("资料没有结构化触发条件，执行前必须由 DM 填写实际事件");
    expect(result?.resourceLabel).toBe("反应：可用");
  });

  it("unlocks a reaction only after the DM records the actual triggering event", () => {
    const action: CombatActionLike = {
      name: "借机攻击",
      action_type: "reaction",
      reaction_trigger: "目标离开近战威胁范围",
      damage: "1d8+4",
      damage_type: "slashing",
    };

    const result = evaluateAdvancedActionAvailability(
      combatant(),
      action,
      combatant({ id: "player-1", entity_type: "character" }),
      1,
      0,
      false,
      "玩家离开黑龙的近战威胁范围",
    );

    expect(result?.available).toBe(true);
    expect(result?.triggerLabel).toBe("玩家离开黑龙的近战威胁范围");
  });

  it("labels advanced player rolls as pending instead of a completed resolution", () => {
    expect(advancedActionPendingRollSummary({
      actorName: "黑龙",
      actionName: "尾击",
      actionCost: "legendary_action",
      legendaryCost: 2,
      legendaryPoolMax: 3,
    })).toContain("本次消耗 2 点（动作池上限 3 点）");

    const reaction = advancedActionPendingRollSummary({
      actorName: "黑龙",
      actionName: "借机攻击",
      actionCost: "reaction",
      reactionTrigger: "玩家离开黑龙的近战威胁范围",
    });
    expect(reaction).toContain("实际触发事件：玩家离开黑龙的近战威胁范围");
    expect(reaction).toContain("尚未完成结算");
  });

  it("explains legendary pool, own-turn and window failures", () => {
    const actor = combatant({
      snapshot_json: {
        legendary_actions_remaining: 1,
        legendary_action_window_used: "2:1",
      },
    });
    const action: CombatActionLike = {
      name: "尾击",
      action_type: "legendary_action",
      legendary_cost: 2,
      legendary_pool_max: 3,
      damage: "2d8",
      damage_type: "bludgeoning",
    };
    const result = evaluateAdvancedActionAvailability(actor, action, actor, 2, 1, false);

    expect(result?.available).toBe(false);
    expect(result?.blockingReasons).toEqual(expect.arrayContaining([
      "当前是该怪物自己的回合；传奇动作只能在其他单位回合结束后使用",
      "传奇动作点不足：需要 2 点，剩余 1 点",
      "当前先攻窗口已经使用过传奇动作",
    ]));
    expect(result?.resourceLabel).toContain("1/3 点");
  });

  it("does not refill an explicitly empty legendary pool", () => {
    const actor = combatant({
      snapshot_json: { legendary_actions_remaining: 0 },
    });
    const action: CombatActionLike = {
      name: "尾击",
      action_type: "legendary_action",
      legendary_cost: 1,
      legendary_pool_max: 3,
      damage: "2d8",
      damage_type: "bludgeoning",
    };
    const result = evaluateAdvancedActionAvailability(
      actor,
      action,
      combatant({ id: "player-1", entity_type: "character" }),
      2,
      1,
      false,
    );

    expect(result?.available).toBe(false);
    expect(result?.blockingReasons).toContain("传奇动作点不足：需要 1 点，剩余 0 点");
    expect(result?.resourceLabel).toContain("0/3 点");
  });

  it("never derives an advanced target before the map supplies an anchor", () => {
    const actor = combatant({
      snapshot_json: { grid_position: { row: 2, col: 2, elevation_ft: 0 } },
    });
    const target = combatant({
      id: "player-1",
      entity_type: "character",
      snapshot_json: { grid_position: { row: 2, col: 4, elevation_ft: 0 } },
    });
    const action: CombatActionLike = {
      name: "巢穴震爆",
      action_type: "lair_action",
      area_shape: "circle",
      area_size_ft: 10,
      area_anchor_height_ft: 0,
      save_dc: 14,
      save_ability: "dexterity",
      affects_multiple_targets: true,
    };

    const result = evaluateAdvancedAreaTargeting(action, actor, [target], {
      horizontalTargetIds: new Set([target.id]),
      validTargetIds: new Set([target.id]),
    });

    expect(result.ready).toBe(false);
    expect(result.eligibleTargetIds).toEqual(new Set());
    expect(result.blockingReasons).toContain("请先在战斗地图定位该高级区域，再选择目标");
  });

  it("only opens a lair action at initiative 20 and once per round", () => {
    const actor = combatant();
    const action: CombatActionLike = { name: "地面震动", action_type: "lair_action" };

    expect(evaluateAdvancedActionAvailability(actor, action, combatant({ id: "player-1", entity_type: "character" }), 3, 0, true)?.available).toBe(true);
    const spent = combatant({ snapshot_json: { lair_action_round: 3 } });
    const result = evaluateAdvancedActionAvailability(spent, action, combatant({ id: "player-1", entity_type: "character" }), 3, 0, true);
    expect(result?.available).toBe(false);
    expect(result?.blockingReasons).toContain("该单位本轮已经使用过巢穴动作");
  });
});
