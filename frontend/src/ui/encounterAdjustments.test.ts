import { describe, expect, it } from "vitest";

import type { EncounterOperation } from "../api/types";
import { describeEncounterOperation, difficultyShiftLabel } from "./encounterAdjustments";

describe("encounter adjustment presentation", () => {
  it.each<[EncounterOperation, string]>([
    [
      {
        kind: "remove_entity",
        entity_type: "monster",
        entity_id: "guard",
        reason: "被引走",
      },
      "移出本次战斗：异教守卫",
    ],
    [
      {
        kind: "add_scene_entity",
        entity_type: "npc",
        entity_id: "priest",
        reason: "获救",
      },
      "加入本次战斗：获救牧师",
    ],
    [
      {
        kind: "set_entity_hp",
        entity_type: "monster",
        entity_id: "boss",
        hp: 42,
        reason: "反噬",
      },
      "教团首领 当前生命调整为 42",
    ],
    [
      {
        kind: "add_entity_condition",
        entity_type: "monster",
        entity_id: "boss",
        condition: "无法召唤阴影",
        reason: "法阵被毁",
      },
      "教团首领 获得状态：无法召唤阴影",
    ],
    [
      {
        kind: "schedule_reinforcement",
        entity_type: "monster",
        entity_id: "guard",
        round: 3,
        quantity: 2,
        reason: "迟到",
      },
      "第 3 轮增援：异教守卫 ×2",
    ],
  ])("describes an operation", (operation, expected) => {
    const names: Record<string, string> = {
      guard: "异教守卫",
      priest: "获救牧师",
      boss: "教团首领",
    };
    expect(describeEncounterOperation(operation, names[operation.entity_id])).toBe(expected);
  });

  it("labels bounded difficulty changes", () => {
    expect(difficultyShiftLabel(-1)).toBe("降低一级");
    expect(difficultyShiftLabel(0)).toBe("难度不变");
    expect(difficultyShiftLabel(1)).toBe("提高一级");
  });
});
