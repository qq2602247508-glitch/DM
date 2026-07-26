import type { EncounterOperation } from "../api/types";

export function describeEncounterOperation(
  operation: EncounterOperation,
  entityName = operation.entity_id,
): string {
  switch (operation.kind) {
    case "remove_entity":
      return `移出本次战斗：${entityName}`;
    case "add_scene_entity":
      return `加入本次战斗：${entityName}`;
    case "set_entity_hp":
      return `${entityName} 当前生命调整为 ${operation.hp}`;
    case "add_entity_condition":
      return `${entityName} 获得状态：${operation.condition}`;
    case "schedule_reinforcement":
      return `第 ${operation.round} 轮增援：${entityName} ×${operation.quantity}`;
  }
}

export function difficultyShiftLabel(shift: -1 | 0 | 1): string {
  if (shift < 0) return "降低一级";
  if (shift > 0) return "提高一级";
  return "难度不变";
}
