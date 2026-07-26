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
};

export type AreaSpellResolution = {
  damageExpression: string;
  damageRolls: number[];
  sharedDamage: number;
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
  random = Math.random,
}: {
  targets: AreaSpellTarget[];
  damageExpression: string;
  saveDc: number;
  saveAbility: string;
  halfDamageOnSave: boolean;
  random?: () => number;
}): AreaSpellResolution {
  const expression = parseDiceExpression(damageExpression);
  if (!expression) throw new Error("区域法术缺少有效伤害骰");
  const damageRoll = rollDiceExpression(expression, random);
  const normalizedSaveAbility = normalizedAbility(saveAbility);
  return {
    damageExpression,
    damageRolls: damageRoll.rolls,
    sharedDamage: damageRoll.total,
    saveAbility: normalizedSaveAbility,
    saveDc,
    targets: targets.map((target) => {
      const d20 = Math.floor(random() * 20) + 1;
      const modifier = savingThrowModifier(target, normalizedSaveAbility);
      const saveTotal = d20 + modifier;
      const success = saveTotal >= saveDc;
      return {
        targetId: target.id,
        targetName: target.name,
        d20,
        modifier,
        saveTotal,
        success,
        damage: success
          ? (halfDamageOnSave ? Math.floor(damageRoll.total / 2) : 0)
          : damageRoll.total,
      };
    }),
  };
}
