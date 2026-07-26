export type CombatActionLike = {
  name?: string;
  description?: string;
  damage?: string;
  damage_type?: string;
  range?: string;
  cost?: string;
  attack_bonus?: number;
  save_dc?: number;
  save_ability?: string;
  half_damage_on_save?: boolean;
  recharge?: string;
  resource_key?: string;
  resource_cost?: number;
};

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

export function parseRangeFeet(value: string | null | undefined): number {
  const text = String(value ?? "");
  if (/自身|self/i.test(text)) return 0;
  const feet = text.match(/(\d+)(?:\s*\/\s*\d+)?\s*(?:尺|feet|ft)/i);
  return feet ? Number(feet[1]) : 5;
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

function expectedDamage(action: CombatActionLike): number {
  const dice = parseDiceExpression(action.damage);
  return dice
    ? dice.count * ((dice.sides + 1) / 2) + dice.modifier
    : 0;
}

export function chooseEnemyActionIndex(
  actions: CombatActionLike[],
  tactics: EnemyTactics,
  turnSeed = 0,
): number {
  if (actions.length === 0) return 0;
  const damaging = actions
    .map((action, index) => ({ action, index }))
    .filter(({ action }) => Boolean(parseDiceExpression(action.damage)));
  if (damaging.length === 0) return 0;
  if (tactics === "instinctive") return damaging[0]?.index ?? 0;
  if (tactics === "standard") {
    return damaging[Math.abs(turnSeed) % damaging.length]?.index ?? 0;
  }
  return [...damaging].sort((left, right) => {
    const leftControl = left.action.save_dc ? 4 : 0;
    const rightControl = right.action.save_dc ? 4 : 0;
    const leftRange = parseRangeFeet(left.action.range) / 30;
    const rightRange = parseRangeFeet(right.action.range) / 30;
    const tacticalWeight = tactics === "tactical" ? 1.5 : 1;
    return (
      expectedDamage(right.action) + rightControl * tacticalWeight + rightRange
      - expectedDamage(left.action) - leftControl * tacticalWeight - leftRange
    );
  })[0]?.index ?? 0;
}

export function actionRangeSummary(action: CombatActionLike): string {
  const range = parseRangeFeet(action.range);
  const lower = `${action.name ?? ""} ${action.description ?? ""}`.toLowerCase();
  if (/锥形|cone/.test(lower)) return `${range || 15}尺锥形`;
  if (/直线|line/.test(lower)) return `${range || 30}尺直线`;
  if (/球形|半径|sphere|radius|火球/.test(lower)) return `${range || 20}尺圆形区域`;
  return range === 0 ? "以自身为中心" : `${range}尺射程`;
}
