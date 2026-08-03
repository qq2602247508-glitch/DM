export type CombatActionLike = {
  name?: string;
  description?: string;
  damage?: string;
  healing?: string;
  damage_type?: string;
  damage_components?: Array<{
    expression?: string;
    damage?: string;
    amount?: number;
    damage_type?: string;
    damage_tags?: string[];
  }>;
  range?: string;
  cost?: string;
  attack_bonus?: number;
  save_dc?: number;
  save_ability?: string;
  half_damage_on_save?: boolean;
  recharge?: string | { minimum?: number; maximum?: number };
  action_type?: "action" | "bonus_action" | "reaction" | "legendary_action" | "lair_action" | "spellcasting";
  range_ft?: number;
  area_shape?: "single" | "circle" | "sphere" | "cone" | "line" | "cube" | "cylinder" | null;
  area_size_ft?: number | null;
  area_width_ft?: number | null;
  area_height_ft?: number | null;
  area_anchor_height_ft?: number | null;
  area_origin_self?: boolean;
  affects_multiple_targets?: boolean;
  conditions_on_hit?: string[];
  conditions_on_success?: string[];
  conditions_on_failure?: string[];
  condition_duration?: "actor_turn_start" | "actor_turn_end" | "target_turn_start" | "target_turn_end" | "rounds" | "minutes" | "until_save" | "until_removed" | null;
  condition_duration_value?: number | null;
  condition_save_dc?: number | null;
  condition_save_ability?: string | null;
  movement?: { distance_ft?: number; type?: string; direction?: "away" | "toward" } | null;
  multiattack?: boolean;
  multiattack_count?: number | null;
  multiattack_components?: { action_name?: string; count?: number }[];
  legendary_cost?: number | null;
  legendary_pool_max?: number | null;
  reaction_trigger?: string | null;
  resource_key?: string;
  resource_cost?: number;
  auto_eligible?: boolean;
  resolution_kind?: "damage" | "heal" | "healing" | "control" | "area_condition" | "ability_check" | "narrative";
  rule_plan?: Record<string, unknown>;
  spell_level?: number;
  upcast_damage_dice?: number;
  upcast_healing_dice?: number;
};

export type RolledDamageComponent = { amount: number; damage_type: string; damage_tags?: string[] };

/** A grid-backed combat action cannot target a unit with no map coordinate. */
export function hasGridPosition(snapshot: unknown): boolean {
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return false;
  const position = (snapshot as Record<string, unknown>).grid_position;
  if (!position || typeof position !== "object" || Array.isArray(position)) return false;
  const raw = position as Record<string, unknown>;
  return Number.isInteger(raw.row) && Number.isInteger(raw.col);
}

/** Player summons stay on the player action path; enemy summons stay on AI. */
export function isPlayerControlledCombatant(entityType: unknown, snapshot: unknown): boolean {
  if (entityType === "character") return true;
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return false;
  return (snapshot as Record<string, unknown>).controller === "player";
}

/**
 * Resolve every explicitly structured damage segment once.  A mixed action
 * must not share one d20/damage total across fire, cold, weapon, and similar
 * segments because each segment can have a different defense.
 */
export function rollStructuredDamage(
  action: CombatActionLike,
  random: () => number = Math.random,
): { components: RolledDamageComponent[]; total: number; damageType: string } | null {
  const direct = Array.isArray(action.damage_components) ? action.damage_components : [];
  const planBlocks = action.rule_plan && typeof action.rule_plan === "object"
    && Array.isArray(action.rule_plan.blocks)
    ? action.rule_plan.blocks
    : [];
  const planned = planBlocks.filter((item): item is Record<string, unknown> => (
    item !== null
    && typeof item === "object"
    && (item as Record<string, unknown>).kind === "damage"
  ));
  const rawSegments = direct.length > 0
    ? direct
    : planned.map((item) => ({
      expression: typeof item.expression === "string" ? item.expression : undefined,
      damage: typeof item.damage === "string" ? item.damage : undefined,
      amount: typeof item.amount === "number" ? item.amount : undefined,
      damage_type: typeof item.damage_type === "string" ? item.damage_type : undefined,
      damage_tags: Array.isArray(item.damage_tags)
        ? item.damage_tags.filter((tag): tag is string => typeof tag === "string")
        : undefined,
    }));
  if (rawSegments.length === 0) {
    const expression = parseDiceExpression(action.damage);
    const damageType = String(action.damage_type ?? "").trim();
    if (!expression || !damageType) return null;
    const rolled = rollDiceExpression(expression, random).total;
    return { components: [{ amount: rolled, damage_type: damageType }], total: rolled, damageType };
  }
  const components: RolledDamageComponent[] = [];
  for (const segment of rawSegments) {
    const expression = typeof segment.expression === "string"
      ? segment.expression
      : typeof segment.damage === "string"
        ? segment.damage
        : typeof segment.amount === "number"
          ? String(segment.amount)
          : "";
    const damageType = String(segment.damage_type ?? "").trim();
    const parsed = parseDiceExpression(expression);
    if (!parsed || !damageType) return null;
    components.push({
      amount: rollDiceExpression(parsed, random).total,
      damage_type: damageType,
      damage_tags: Array.isArray(segment.damage_tags)
        ? segment.damage_tags.filter((tag): tag is string => typeof tag === "string" && tag.trim().length > 0)
        : undefined,
    });
  }
  return {
    components,
    total: components.reduce((sum, component) => sum + component.amount, 0),
    damageType: components.length === 1 ? components[0]!.damage_type : "mixed",
  };
}

export type ForcedMovement = {
  distance_ft: number;
  direction: "away" | "toward";
};

/**
 * Read a forced-movement block without guessing from the action name or prose.
 * The DM combat page uses the generic combat endpoint, so it must carry the
 * same structured movement that the player-room compiler already executes.
 */
export function forcedMovementFromAction(action: CombatActionLike): ForcedMovement | null {
  const direct = action.movement;
  if (
    direct
    && Number.isInteger(direct.distance_ft)
    && Number(direct.distance_ft) > 0
    && (direct.direction === "away" || direct.direction === "toward")
  ) {
    return { distance_ft: Number(direct.distance_ft), direction: direct.direction };
  }
  const plan = action.rule_plan;
  const blocks = plan && typeof plan === "object" && Array.isArray(plan.blocks)
    ? plan.blocks
    : [];
  const block = blocks.find((item): item is Record<string, unknown> => (
    item !== null
    && typeof item === "object"
    && (item as Record<string, unknown>).kind === "move"
    && (item as Record<string, unknown>).movement_type === "forced"
  ));
  const distance = Number(block?.distance_ft);
  const direction = block?.direction;
  if (
    Number.isInteger(distance)
    && distance > 0
    && (direction === "away" || direction === "toward")
  ) {
    return { distance_ft: distance, direction };
  }
  return null;
}

export type RechargeRange = { minimum: number; maximum: number };

export function parseRechargeRange(
  value: CombatActionLike["recharge"] | null | undefined,
): RechargeRange | null {
  if (value && typeof value === "object") {
    const minimum = Number(value.minimum);
    const maximum = Number(value.maximum ?? value.minimum);
    return minimum >= 1 && maximum <= 6 && minimum <= maximum
      ? { minimum, maximum }
      : null;
  }
  const text = String(value ?? "").trim();
  if (!text) return null;
  const match = text.match(/(\d+)\s*[–—-]\s*(\d+)/);
  if (match) {
    const minimum = Number(match[1]);
    const maximum = Number(match[2]);
    return minimum >= 1 && maximum <= 6 && minimum <= maximum
      ? { minimum, maximum }
      : null;
  }
  const single = text.match(/\b([1-6])\b/);
  return single ? { minimum: Number(single[1]), maximum: Number(single[1]) } : null;
}

export function rechargeActionKey(action: CombatActionLike, index = 0): string {
  return action.name?.trim() || `action-${index + 1}`;
}

export function isRechargeAvailable(
  action: CombatActionLike,
  state: Record<string, boolean> | undefined,
  index = 0,
): boolean {
  if (!parseRechargeRange(action.recharge)) return true;
  // No map means this is the monster's initial charge state. Once the map is
  // created, missing keys are unavailable until the DM rolls recharge.
  if (!state) return true;
  return state[rechargeActionKey(action, index)] === true;
}

export function upcastExpression(
  expression: string | null | undefined,
  slotLevel: number,
  baseLevel: number,
  extraDice: number,
): string | undefined {
  if (!expression || slotLevel <= baseLevel || extraDice <= 0) return expression ?? undefined;
  const match = expression.match(/^(\d+)d(\d+)(.*)$/i);
  if (!match) return expression;
  return `${Number(match[1]) + (slotLevel - baseLevel) * extraDice}d${match[2]}${match[3]}`;
}

export type DiceExpression = {
  count: number;
  sides: number;
  modifier: number;
};

export function parseDiceExpression(value: string | null | undefined): DiceExpression | null {
  const match = String(value ?? "").match(/(\d+)d(\d+)(?:\s*([+-])\s*(\d+))?/i);
  if (!match) return null;
  const count = Number(match[1]);
  const sides = Number(match[2]);
  const modifier = match[3] && match[4]
    ? Number(match[4]) * (match[3] === "-" ? -1 : 1)
    : 0;
  if (count < 1 || count > 100 || sides < 2 || sides > 1_000) return null;
  return { count, sides, modifier };
}

export function rollDiceExpression(
  expression: DiceExpression,
  random: () => number = Math.random,
): { rolls: number[]; total: number } {
  const rolls = Array.from(
    { length: expression.count },
    () => Math.floor(random() * expression.sides) + 1,
  );
  return {
    rolls,
    total: Math.max(0, rolls.reduce((sum, roll) => sum + roll, 0) + expression.modifier),
  };
}

export function parseRangeFeet(value: string | null | undefined): number | null {
  const text = String(value ?? "");
  if (/自身|self/i.test(text)) return 0;
  const feet = text.match(/(\d+)(?:\s*\/\s*\d+)?\s*(?:尺|feet|ft)/i);
  return feet ? Number(feet[1]) : null;
}

export type MonsterActionCost = "action" | "bonus_action" | "reaction" | "legendary_action" | "lair_action" | "none";

/**
 * The map computes horizontal coverage before the optional elevation check.
 * For ordinary two-dimensional actions that horizontal set is authoritative;
 * preferring a stale/empty vertical set here can leave an AI turn waiting
 * forever after movement even though the map already shows the target in
 * range. Three-dimensional actions must continue to fail closed.
 */
export function executableTargetIds(
  validTargetIds: ReadonlySet<string> | undefined,
  horizontalTargetIds: ReadonlySet<string> | undefined,
  requiresElevation = false,
): ReadonlySet<string> | undefined {
  if (!requiresElevation && horizontalTargetIds && horizontalTargetIds.size > 0) {
    return horizontalTargetIds;
  }
  return validTargetIds;
}

export function monsterActionCost(action: CombatActionLike): MonsterActionCost {
  if (action.action_type === "legendary_action") return "legendary_action";
  if (action.action_type === "lair_action") return "lair_action";
  if (action.action_type === "reaction") return "reaction";
  if (action.action_type === "bonus_action") return "bonus_action";
  const cost = `${action.cost ?? "动作"} ${action.description ?? ""}`;
  if (/附赠|bonus/i.test(cost)) return "bonus_action";
  if (/反应|reaction/i.test(cost)) return "reaction";
  if (/无需动作|不消耗动作|free action/i.test(cost)) return "none";
  return "action";
}

export function isMonsterTurnAction(action: CombatActionLike): boolean {
  return !action.action_type
    || action.action_type === "action"
    || action.action_type === "bonus_action"
    || action.action_type === "spellcasting";
}

export type MonsterActionStep = {
  action: CombatActionLike;
  actionIndex: number;
  repetition: number;
};

export function expandMonsterAction(
  actions: CombatActionLike[],
  selectedIndex: number,
): MonsterActionStep[] | null {
  const selected = actions[selectedIndex];
  if (!selected) return null;
  if (!selected.multiattack) {
    return [{ action: selected, actionIndex: selectedIndex, repetition: 0 }];
  }
  if (!selected.multiattack_components?.length || !selected.multiattack_count) return null;
  const result: MonsterActionStep[] = [];
  for (const component of selected.multiattack_components) {
    const childIndex = actions.findIndex((action) => action.name === component.action_name);
    const count = Number(component.count ?? 0);
    if (childIndex < 0 || count < 1) return null;
    for (let repetition = 0; repetition < count; repetition += 1) {
      result.push({ action: actions[childIndex]!, actionIndex: childIndex, repetition });
    }
  }
  return result.length === selected.multiattack_count ? result : null;
}

export function abilityModifier(score: number | null | undefined): number {
  return Math.floor((Number(score ?? 10) - 10) / 2);
}

export function proficiencyBonus(level: number): number {
  return 2 + Math.floor((Math.max(1, level) - 1) / 4);
}

const CHECK_RULES = [
  { pattern: /说服|劝说|谈判|安抚/, skill: "游说", ability: "charisma", label: "魅力" },
  { pattern: /威吓|恐吓|震慑/, skill: "威吓", ability: "charisma", label: "魅力" },
  { pattern: /欺骗|撒谎|伪装/, skill: "欺瞒", ability: "charisma", label: "魅力" },
  { pattern: /观察|寻找|察觉|发现/, skill: "察觉", ability: "wisdom", label: "感知" },
  { pattern: /分析|调查|机关/, skill: "调查", ability: "intelligence", label: "智力" },
  { pattern: /躲避|翻滚|平衡|杂技/, skill: "杂技", ability: "dexterity", label: "敏捷" },
  { pattern: /攀爬|推开|抓住|破坏/, skill: "运动", ability: "strength", label: "力量" },
  { pattern: /滑倒|摔倒|绊倒|失去平衡/, skill: "运动", ability: "strength", label: "力量" },
] as const;

export function proposeFreeformCheck(
  text: string,
  abilityScores: Record<string, number>,
  level: number,
  proficientSkills: string[],
): {
  skill: string;
  ability: string;
  abilityLabel: string;
  modifier: number;
  dc: number;
  explanation: string;
} {
  const rule = CHECK_RULES.find((item) => item.pattern.test(text)) ?? {
    skill: "临场判断",
    ability: "wisdom",
    label: "感知",
  };
  const proficient = proficientSkills.some((skill) => skill.includes(rule.skill));
  const modifier = abilityModifier(abilityScores[rule.ability])
    + (proficient ? proficiencyBonus(level) : 0);
  const dc = /几乎不可能|极难|传奇/.test(text)
    ? 20
    : /困难|冒险|强行|战斗中/.test(text)
      ? 15
      : /容易|简单|熟悉/.test(text)
        ? 10
        : 12;
  return {
    skill: rule.skill,
    ability: rule.ability,
    abilityLabel: rule.label,
    modifier,
    dc,
    explanation: proficient
      ? `${rule.label}调整值并加入熟练加值`
      : `${rule.label}调整值；角色卡未标记该技能熟练`,
  };
}

export type EnemyTactics = "instinctive" | "standard" | "smart" | "tactical";

export const ENEMY_TACTICS_LABELS: Record<EnemyTactics, string> = {
  instinctive: "本能",
  standard: "普通",
  smart: "聪明",
  tactical: "战术",
};

export function chooseEnemyTarget<T extends { hp: number; max_hp: number; armor_class: number }>(
  targets: T[],
  tactics: EnemyTactics,
): T | null {
  if (targets.length === 0) return null;
  if (tactics === "instinctive") return targets[0] ?? null;
  if (tactics === "standard") {
    return [...targets].sort((a, b) => a.hp - b.hp)[0] ?? null;
  }
  if (tactics === "smart") {
    return [...targets].sort((a, b) => (a.hp / Math.max(1, a.max_hp)) - (b.hp / Math.max(1, b.max_hp)))[0] ?? null;
  }
  return [...targets].sort((a, b) => a.armor_class - b.armor_class || a.hp - b.hp)[0] ?? null;
}

function expectedDamage(action: CombatActionLike, actions: CombatActionLike[] = []): number {
  if (action.multiattack) {
    const selectedIndex = actions.indexOf(action);
    const steps = expandMonsterAction(actions, selectedIndex);
    return steps?.reduce((sum, step) => sum + expectedDamage(step.action), 0) ?? 0;
  }
  const dice = parseDiceExpression(action.damage);
  return dice
    ? dice.count * ((dice.sides + 1) / 2) + dice.modifier
    : 0;
}

export function chooseEnemyActionIndex(
  actions: CombatActionLike[],
  tactics: EnemyTactics,
  turnSeed = 0,
  rechargeAvailable?: Record<string, boolean>,
): number {
  if (actions.length === 0) return 0;
  const damaging = actions
    .map((action, index) => ({ action, index }))
    .filter(({ action }) => (
      action.auto_eligible !== false
      && isMonsterTurnAction(action)
      && (Boolean(parseDiceExpression(action.damage)) || Boolean(action.multiattack))
    ))
    .filter(({ action, index }) => isRechargeAvailable(action, rechargeAvailable, index));
  if (damaging.length === 0) return 0;
  if (tactics === "instinctive") return damaging[0]?.index ?? 0;
  if (tactics === "standard") {
    return damaging[Math.abs(turnSeed) % damaging.length]?.index ?? 0;
  }
  return [...damaging].sort((left, right) => {
    const leftControl = left.action.save_dc ? 4 : 0;
    const rightControl = right.action.save_dc ? 4 : 0;
    const leftRange = (parseRangeFeet(left.action.range) ?? 0) / 30;
    const rightRange = (parseRangeFeet(right.action.range) ?? 0) / 30;
    const tacticalWeight = tactics === "tactical" ? 1.5 : 1;
    return (
      expectedDamage(right.action, actions) + rightControl * tacticalWeight + rightRange
      - expectedDamage(left.action, actions) - leftControl * tacticalWeight - leftRange
    );
  })[0]?.index ?? 0;
}

export function actionRangeSummary(action: CombatActionLike): string {
  const range = action.range_ft ?? parseRangeFeet(action.range);
  const lower = `${action.name ?? ""} ${action.description ?? ""}`.toLowerCase();
  const sizeMatch = lower.match(/(\d+)\s*(?:尺|ft)\s*(?:立方|锥形|锥状|直线|线状|球形|半径|cube|cone|line|sphere|radius)/);
  const size = action.area_size_ft ?? (sizeMatch?.[1] ? Number(sizeMatch[1]) : null);
  const shape = action.area_shape;
  if (shape === "cube" || /立方|cube/.test(lower)) return `${size ? `${size}尺` : "尺寸未明确"}立方区域`;
  if (shape === "cone" || /锥形|cone/.test(lower)) return `${size ? `${size}尺` : "尺寸未明确"}锥形`;
  if (shape === "line" || /直线|线状|line/.test(lower)) return `${size ? `${size}尺` : "尺寸未明确"}直线`;
  if (shape === "cylinder" || /圆柱|柱状|cylinder/.test(lower)) {
    const height = action.area_height_ft;
    return `${size ? `${size}尺` : "尺寸未明确"}圆柱区域${height ? ` · 高 ${height}尺` : " · 高度未明确"}`;
  }
  if (shape === "circle" || /球形|半径|sphere|radius/.test(lower)) return `${size ? `${size}尺` : "尺寸未明确"}区域`;
  return range === 0 ? "以自身为中心" : range == null ? "距离未明确 · DM裁定" : `${range}尺射程`;
}
