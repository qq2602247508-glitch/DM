import {
  abilityModifier,
  parseDiceExpression,
  rollDiceExpression,
} from "./combatAutomation";

export type AreaSpellTarget = {
  id: string;
  name: string;
  abilityScores?: Record<string, number>;
  savingThrows?: Record<string, number>;
};

export type AreaSpellTargetResolution = {
  targetId: string;
  targetName: string;
  d20: number;
  modifier: number;
  saveTotal: number;
  success: boolean;
  damage: number;
  damageComponents: Array<{
    amount: number;
    damageType: string;
    damageTags?: string[];
  }>;
};

export type AreaSpellDamageComponent = {
  amount?: number;
  expression?: string;
  damage_type: string;
  damage_tags?: string[];
};

export type AreaSpellResolution = {
  damageExpression: string;
  damageRolls: number[];
  sharedDamage: number;
  damageComponents: Array<{
    amount: number;
    damageType: string;
    damageTags?: string[];
  }>;
  damageType: string;
  saveAbility: string;
  saveDc: number;
  targets: AreaSpellTargetResolution[];
};

function normalizedAbility(value: string): string {
  const aliases: Record<string, string> = {
    力量: "strength",
    敏捷: "dexterity",
    体质: "constitution",
    智力: "intelligence",
    感知: "wisdom",
    魅力: "charisma",
    str: "strength",
    dex: "dexterity",
    con: "constitution",
    int: "intelligence",
    wis: "wisdom",
    cha: "charisma",
  };
  return aliases[value.toLowerCase()] ?? aliases[value] ?? value.toLowerCase();
}

function savingThrowModifier(target: AreaSpellTarget, ability: string): number {
  const normalized = normalizedAbility(ability);
  const explicit = target.savingThrows?.[normalized]
    ?? target.savingThrows?.[ability]
    ?? target.savingThrows?.[normalized.slice(0, 3)];
  if (Number.isFinite(explicit)) return Number(explicit);
  return abilityModifier(target.abilityScores?.[normalized]);
}

export function resolveAreaSavingThrows({
  targets,
  damageExpression,
  saveDc,
  saveAbility,
  halfDamageOnSave,
  sharedDamage,
  damageComponents,
  damageType,
  random = Math.random,
}: {
  targets: AreaSpellTarget[];
  damageExpression: string;
  saveDc: number;
  saveAbility: string;
  halfDamageOnSave: boolean;
  sharedDamage?: number;
  damageComponents?: AreaSpellDamageComponent[];
  damageType?: string;
  random?: () => number;
}): AreaSpellResolution {
  const rawComponents = damageComponents?.length
    ? damageComponents
    : [{ expression: damageExpression, damage_type: damageType ?? "" }];
  const resolvedComponents: AreaSpellResolution["damageComponents"] = [];
  const damageRolls: number[] = [];
  const usesReportedSharedDamage = !damageComponents?.length && sharedDamage !== undefined;
  for (const component of rawComponents) {
    const type = component.damage_type.trim();
    if (!type) throw new Error("区域法术的每段伤害都必须有明确伤害类型");
    const amount = component.amount;
    const hasExplicitAmount = Number.isFinite(amount) && Number(amount) >= 0;
    const expression = hasExplicitAmount
      ? null
      : component.expression ? parseDiceExpression(component.expression) : null;
    if (!usesReportedSharedDamage && !expression && !hasExplicitAmount) {
      throw new Error(`区域法术缺少有效的${type}伤害骰或最终数值`);
    }
    const roll = usesReportedSharedDamage
      ? { rolls: [], total: Number(sharedDamage) }
      : hasExplicitAmount
      ? { rolls: [], total: Number(amount) }
      : expression
      ? rollDiceExpression(expression, random)
      : { rolls: [], total: Number(amount) };
    damageRolls.push(...roll.rolls);
    resolvedComponents.push({
      amount: roll.total,
      damageType: type,
      ...(component.damage_tags?.length ? { damageTags: component.damage_tags } : {}),
    });
  }
  if (sharedDamage !== undefined && (!Number.isFinite(sharedDamage) || sharedDamage < 0)) {
    throw new Error("玩家伤害骰总值必须是非负数字");
  }
  const resolvedTotal = resolvedComponents.reduce((sum, component) => sum + component.amount, 0);
  const normalizedSaveAbility = normalizedAbility(saveAbility);
  return {
    damageExpression,
    damageRolls,
    sharedDamage: resolvedTotal,
    damageComponents: resolvedComponents,
    damageType: resolvedComponents.length === 1
      ? resolvedComponents[0]!.damageType
      : "mixed",
    saveAbility: normalizedSaveAbility,
    saveDc,
    targets: targets.map((target) => {
      const d20 = Math.floor(random() * 20) + 1;
      const modifier = savingThrowModifier(target, normalizedSaveAbility);
      const saveTotal = d20 + modifier;
      const success = saveTotal >= saveDc;
      const targetComponents = resolvedComponents.map((component) => ({
        ...component,
        amount: success && halfDamageOnSave ? Math.floor(component.amount / 2) : success ? 0 : component.amount,
      }));
      return {
        targetId: target.id,
        targetName: target.name,
        d20,
        modifier,
        saveTotal,
        success,
        damage: targetComponents.reduce((sum, component) => sum + component.amount, 0),
        damageComponents: targetComponents,
      };
    }),
  };
}
