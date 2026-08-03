import type { GeneratedAction } from "../api/types";
import type { CombatActionLike } from "./combatAutomation";

export const MIND_FLAYER_2025_ACTIONS: (GeneratedAction & CombatActionLike)[] = [
  {
    name: "触须",
    description: "近战攻击检定 +7，触及5尺。命中造成4d8+4心灵伤害；中型或更小目标被擒抱（逃脱DC14）并在擒抱期间震慑。",
    damage: "4d8+4",
    damage_type: "psychic",
    range: "5尺",
    cost: "动作",
    attack_bonus: 7,
  },
  {
    name: "采脑",
    description: "仅能对正被夺心魔触须擒抱的生物使用。目标进行DC15体质豁免，失败受到10d10穿刺伤害，成功半伤；降至0 HP时死亡。",
    damage: "10d10",
    damage_type: "piercing",
    range: "5尺",
    cost: "动作",
    save_dc: 15,
    save_ability: "constitution",
    half_damage_on_save: true,
    auto_eligible: false,
  },
  {
    name: "心灵震爆",
    description: "60尺锥形区域；范围内生物进行DC15智力豁免，失败受到6d8+4心灵伤害并震慑至夺心魔下个回合结束，成功半伤。",
    damage: "6d8+4",
    damage_type: "psychic",
    range: "60尺锥形",
    cost: "动作",
    save_dc: 15,
    save_ability: "intelligence",
    half_damage_on_save: true,
    recharge: "5–6",
    action_type: "action",
    area_shape: "cone",
    area_size_ft: 60,
    area_origin_self: true,
    affects_multiple_targets: true,
  },
];

export function monsterActionsForRules(
  displayName: string,
  recordedActions: CombatActionLike[],
): CombatActionLike[] {
  // Parsed compendium actions are authoritative.  The small profile remains
  // a compatibility fallback for old snapshots which stored no action list.
  if (recordedActions.length === 0 && /夺心魔|灵吸怪|mind flayer/i.test(displayName)) {
    return MIND_FLAYER_2025_ACTIONS;
  }
  return recordedActions;
}
