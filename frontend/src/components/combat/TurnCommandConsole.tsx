import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactElement } from "react";

import {
  confirmCombatAction,
  createPlayerRollPrompt,
  previewCombatAction,
  updateCharacter,
  updateCombatant,
  type CombatActionCommand,
} from "../../api/entities";
import type { Character, CombatActionPreview, Combatant } from "../../api/types";
import { useToast } from "../../hooks/toastContext";
import {
  ENEMY_TACTICS_LABELS,
  abilityModifier,
  actionRangeSummary,
  chooseEnemyTarget,
  chooseEnemyActionIndex,
  parseDiceExpression,
  parseRangeFeet,
  proficiencyBonus,
  proposeFreeformCheck,
  rollDiceExpression,
  type CombatActionLike,
  type EnemyTactics,
} from "../../ui/combatAutomation";
import { isPreparedCombatSpell } from "../../ui/characterRules";
import { targetingFromRulePlan } from "../../ui/ruleBlocks";
import {
  resolveAreaSavingThrows,
  type AreaSpellResolution,
} from "../../ui/areaSpellResolution";
import { Badge, Button } from "../../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../../ui/styles";
import type { TargetingTemplate } from "../../ui/gridTargeting";
import { monsterActionsForRules } from "../../ui/monsterRuleProfiles";
import { RuleBlockPlan } from "../RuleBlockPlan";

export type CombatTargeting = TargetingTemplate & { label: string };

type PendingResolution = {
  command: CombatActionCommand;
  preview: CombatActionPreview;
  explanation: string;
};

type PendingAreaResolution = {
  resolution: AreaSpellResolution;
  actionName: string;
  actionCost: ActionCost;
  damageType: string;
};

function normalizeAction(raw: unknown, index: number): CombatActionLike {
  if (typeof raw === "string") return { name: raw, description: "角色卡记录", cost: "动作" };
  if (raw && typeof raw === "object") return raw;
  return { name: `动作 ${index + 1}` };
}

function actionModifier(character: Character, action: CombatActionLike): number {
  const text = `${action.name ?? ""} ${action.description ?? ""}`;
  const rawSpellAbility = character.spellcasting.ability;
  const spellAbility = typeof rawSpellAbility === "string"
    ? ({ 力量: "strength", 敏捷: "dexterity", 体质: "constitution", 智力: "intelligence", 感知: "wisdom", 魅力: "charisma" }[rawSpellAbility] ?? rawSpellAbility)
    : "intelligence";
  const ability = /法术|魔能|火焰|奥术/.test(text)
    ? spellAbility
    : /远程|弓|弩|灵巧/.test(text)
      ? "dexterity"
      : "strength";
  return abilityModifier(character.ability_scores[ability])
    + proficiencyBonus(character.level);
}

type ActionCost = "action" | "bonus_action" | "reaction" | "none";

function actionCost(action: CombatActionLike): ActionCost {
  const cost = `${action.cost ?? "动作"} ${action.description ?? ""}`;
  if (/附赠|bonus/i.test(cost)) return "bonus_action";
  if (/反应|reaction/i.test(cost)) return "reaction";
  if (/无需动作|不消耗动作|free action/i.test(cost)) return "none";
  return "action";
}

function hasActionEconomy(active: Combatant, cost: ActionCost): boolean {
  if (cost === "none") return true;
  if (cost === "bonus_action") return active.bonus_action_available;
  if (cost === "reaction") return active.reaction_available;
  return active.action_available;
}

function targetingForAction(action: CombatActionLike): CombatTargeting {
  const compiled = targetingFromRulePlan(action);
  if (compiled) {
    return {
      ...compiled,
      label: `${action.name ?? "动作"} · 已编译规则范围`,
    };
  }
  const summary = actionRangeSummary(action);
  const targetingText = `${action.range ?? ""} ${action.description ?? ""}`;
  const radiusMatch = targetingText.match(/(\d+)\s*尺(?:半径|范围|球形|爆发)/);
  const lengthMatch = targetingText.match(/(\d+)\s*尺(?:长|锥形|直线)/);
  const widthMatch = targetingText.match(/(\d+)\s*尺(?:宽|宽度)/);
  const shape = /锥形/.test(summary)
    ? "cone"
    : /直线/.test(summary)
      ? "line"
      : /圆形|球形|半径|爆炸|爆发/.test(`${summary} ${targetingText}`)
        ? "circle"
        : "single";
  return {
    rangeFt: parseRangeFeet(action.range),
    sizeFt: shape === "circle"
      ? (radiusMatch ? Number(radiusMatch[1]) : undefined)
      : (lengthMatch ? Number(lengthMatch[1]) : undefined),
    widthFt: widthMatch ? Number(widthMatch[1]) : undefined,
    shape,
    label: `${action.name ?? "动作"} · ${summary}`,
  };
}

export function TurnCommandConsole({
  active,
  activeCharacter,
  campaignId,
  combatId,
  fighters,
  autoEnemies,
  automationReady,
  onAutoEnemiesChange,
  onEnemyTurnComplete,
  onRangeChange,
  onTargetChange,
  selectedTargetId,
  turnKey,
  validTargetIds,
}: {
  active: Combatant;
  activeCharacter?: Character;
  campaignId: string;
  combatId: string;
  fighters: Combatant[];
  autoEnemies: boolean;
  automationReady: boolean;
  onAutoEnemiesChange: (enabled: boolean) => void;
  onEnemyTurnComplete: () => void;
  onRangeChange: (range: CombatTargeting | null) => void;
  onTargetChange?: (targetId: string) => void;
  selectedTargetId?: string;
  turnKey: string;
  validTargetIds?: ReadonlySet<string>;
}): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [mode, setMode] = useState<"auto" | "assisted">("assisted");
  const [actionIndex, setActionIndex] = useState("0");
  const [targetId, setTargetId] = useState("");
  const [attackTotal, setAttackTotal] = useState("");
  const [damageTotal, setDamageTotal] = useState("");
  const [pending, setPending] = useState<PendingResolution | null>(null);
  const [pendingArea, setPendingArea] = useState<PendingAreaResolution | null>(null);
  const [freeform, setFreeform] = useState("");
  const [checkRoll, setCheckRoll] = useState("");
  const [effectText, setEffectText] = useState("无法行动（1轮）");
  const [tactics, setTactics] = useState<EnemyTactics>("standard");
  const processedAutomaticTurn = useRef<string | null>(null);

  const actions = useMemo(
    () => activeCharacter
      ? [
          ...activeCharacter.actions,
          ...activeCharacter.spells.filter(isPreparedCombatSpell),
        ].map(normalizeAction)
      : monsterActionsForRules(
          active.display_name,
          ((active.snapshot_json.actions as unknown[] | undefined) ?? [])
            .map(normalizeAction),
        ),
    [active.display_name, active.snapshot_json.actions, activeCharacter],
  );
  const selectedAction = actions[Number(actionIndex)] ?? actions[0] ?? {
    name: "临时攻击",
    damage: "1d6",
    range: "5尺",
    cost: "动作",
  };
  const selectedActionCost = actionCost(selectedAction);
  const selectedResourceKey = selectedAction.resource_key;
  const selectedResource = selectedResourceKey && activeCharacter
    ? activeCharacter.resources[selectedResourceKey] as {
        label?: string;
        current?: number;
        max?: number;
      } | undefined
    : undefined;
  const selectedResourceCost = Math.max(1, Number(selectedAction.resource_cost ?? 1));
  const selectedResourceAvailable = !selectedResourceKey
    || Number(selectedResource?.current ?? 0) >= selectedResourceCost;
  const selectedActionAvailable = hasActionEconomy(active, selectedActionCost)
    && selectedResourceAvailable;
  const selectedTargeting = targetingForAction(selectedAction);
  const isAreaSaveAction = Boolean(
    active.entity_type === "character"
    && selectedAction.save_dc
    && selectedAction.save_ability
    && selectedTargeting.shape !== "single",
  );
  const isNarrativeAction = selectedAction.resolution_kind === "narrative";
  const possibleTargets = fighters.filter((fighter) =>
    fighter.id !== active.id
    && fighter.hp > 0
    && (active.entity_type === "character"
      ? fighter.entity_type !== "character"
      : fighter.entity_type === "character"),
  );
  const target = fighters.find((fighter) => fighter.id === targetId);
  const skills = activeCharacter
    ? Object.keys(activeCharacter.skills).filter((name) => Boolean(activeCharacter.skills[name]))
    : [];
  const check = activeCharacter && freeform.trim()
    ? proposeFreeformCheck(
        freeform,
        activeCharacter.ability_scores,
        activeCharacter.level,
        skills,
      )
    : null;
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
    void client.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
    void client.invalidateQueries({ queryKey: ["combat-end-condition", campaignId, combatId] });
  };
  const preview = useMutation({
    mutationFn: ({ command, explanation }: { command: CombatActionCommand; explanation: string }) =>
      previewCombatAction(campaignId, combatId, command)
        .then((result) => ({ command, explanation, preview: result })),
    onSuccess: setPending,
    onError: () => showToast("无法生成动作结算预览", "error"),
  });
  const confirm = useMutation({
    mutationFn: () => {
      if (!pending) throw new Error("没有待确认动作");
      return confirmCombatAction(campaignId, combatId, pending.command);
    },
    onSuccess: () => {
      setPending(null);
      invalidate();
      showToast("动作已由 DM 确认并写入战斗日志");
    },
    onError: () => showToast("动作确认失败，目标状态可能已改变", "error"),
  });
  const confirmArea = useMutation({
    mutationFn: async () => {
      if (!pendingArea) throw new Error("没有待确认的区域法术");
      for (const [index, result] of pendingArea.resolution.targets.entries()) {
        const currentTarget = fighters.find((fighter) => fighter.id === result.targetId);
        if (!currentTarget) throw new Error(`${result.targetName}已不在本场战斗`);
        await confirmCombatAction(campaignId, combatId, {
          action_type: "damage",
          actor_combatant_id: index === 0 ? active.id : null,
          actor_version: index === 0 ? active.version : null,
          action_cost: index === 0 ? pendingArea.actionCost : "none",
          action_name: pendingArea.actionName,
          resolution_note: `${result.targetName}：${pendingArea.resolution.saveAbility}豁免 d20(${result.d20}) ${result.modifier >= 0 ? "+" : ""}${result.modifier} = ${result.saveTotal}，对 DC ${pendingArea.resolution.saveDc} ${result.success ? "成功" : "失败"}；承受 ${result.damage} 点${pendingArea.damageType}伤害`,
          target_combatant_id: result.targetId,
          target_version: currentTarget.version,
          amount: result.damage,
          damage_type: pendingArea.damageType,
        });
      }
      if (selectedResourceKey && activeCharacter && selectedResource) {
        await updateCharacter(
          campaignId,
          activeCharacter.id,
          {
            resources: {
              ...activeCharacter.resources,
              [selectedResourceKey]: {
                ...selectedResource,
                current: Math.max(
                  0,
                  Number(selectedResource.current ?? 0) - selectedResourceCost,
                ),
              },
            },
          },
          activeCharacter.version,
        );
      }
    },
    onSuccess: () => {
      setPendingArea(null);
      invalidate();
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      showToast(
        selectedResourceKey
          ? `区域法术已对全部目标结算；只消耗一次动作和 ${selectedResourceCost} 点${selectedResource?.label ?? selectedResourceKey}`
          : "区域法术已对范围内全部目标结算；动作只消耗一次",
      );
    },
    onError: (error) => showToast(
      error instanceof Error ? error.message : "区域法术结算失败，目标状态可能已改变",
      "error",
    ),
  });
  const applyFreeform = useMutation({
    mutationFn: () => {
      if (!target || !effectText.trim()) throw new Error("请选择受影响目标");
      return updateCombatant(
        campaignId,
        combatId,
        target.id,
        { conditions: [...target.conditions, effectText.trim()] },
        target.version,
      );
    },
    onSuccess: () => {
      invalidate();
      showToast("临场裁定效果已由 DM 确认");
    },
    onError: () => showToast("临场效果写入失败", "error"),
  });
  const requestPlayerSave = useMutation({
    mutationFn: ({
      chosenTarget,
      failureDamage,
      successDamage,
    }: {
      chosenTarget: Combatant;
      failureDamage: number;
      successDamage: number;
    }) => createPlayerRollPrompt(campaignId, combatId, {
      actor_combatant_id: active.id,
      actor_version: active.version,
      target_combatant_id: chosenTarget.id,
      target_version: chosenTarget.version,
      action_name: selectedAction.name ?? "怪物能力",
      action_cost: selectedActionCost,
      resolution_type: "saving_throw",
      dc: selectedAction.save_dc ?? 10,
      ability: selectedAction.save_ability ?? "dexterity",
      skill: null,
      damage_on_success: successDamage,
      damage_on_failure: failureDamage,
      damage_type: selectedAction.damage_type ?? "untyped",
      description: `${active.display_name} 对 ${chosenTarget.display_name} 使用「${selectedAction.name ?? "怪物能力"}」，等待玩家进行${selectedAction.save_ability ?? "敏捷"}豁免。`,
    }),
    onSuccess: () => {
      invalidate();
      showToast("已在右侧战斗面板生成玩家豁免请求");
    },
    onError: () => {
      processedAutomaticTurn.current = null;
      showToast("无法生成玩家豁免请求", "error");
    },
  });
  const autoResolve = useMutation({
    mutationFn: (command: CombatActionCommand) =>
      confirmCombatAction(campaignId, combatId, command),
    onSuccess: async () => {
      invalidate();
      showToast(`${active.display_name}已完成攻击；正在展示命中与伤害效果`);
      await new Promise((resolve) => window.setTimeout(resolve, 900));
      onEnemyTurnComplete();
    },
    onError: () => {
      processedAutomaticTurn.current = null;
      showToast("怪物自动动作失败，已暂停在当前回合供 DM 检查", "error");
    },
  });

  const selectAction = (value: string) => {
    setActionIndex(value);
    const action = actions[Number(value)] ?? selectedAction;
    setPending(null);
    setPendingArea(null);
    onRangeChange(targetingForAction(action));
  };
  useEffect(() => {
    if (selectedTargetId !== undefined && selectedTargetId !== targetId) {
      setTargetId(selectedTargetId);
    }
  }, [selectedTargetId, targetId]);
  useEffect(() => {
    const nextIndex = active.entity_type === "character"
      ? 0
      : chooseEnemyActionIndex(actions, tactics, Number(turnKey.split(":")[0] ?? 0));
    selectAction(String(nextIndex));
    // The active fighter/action list changed; initialize the map indicator.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active.id, tactics, turnKey]);
  const prepareAttack = (
    automatic: boolean,
    forcedTarget?: Combatant,
    fullyAutomaticEnemy = false,
  ) => {
    const chosenTarget = forcedTarget ?? target;
    if (!selectedActionAvailable) {
      showToast(
        selectedActionCost === "bonus_action"
          ? "本回合附赠动作已经使用"
          : selectedActionCost === "reaction"
            ? "本轮反应已经使用"
            : "本回合动作已经使用，请结束回合",
        "error",
      );
      return;
    }
    if (!chosenTarget) {
      showToast("请先选择目标", "error");
      return;
    }
    if (validTargetIds && !validTargetIds.has(chosenTarget.id)) {
      showToast("目标不在当前技能的合法距离或范围内，请先在战斗地图上选择有效目标", "error");
      return;
    }
    const expression = parseDiceExpression(selectedAction.damage) ?? {
      count: 1,
      sides: 6,
      modifier: 0,
    };
    if (
      active.entity_type !== "character"
      && selectedAction.save_dc
      && selectedAction.save_ability
    ) {
      const damageRoll = rollDiceExpression(expression);
      const successDamage = selectedAction.half_damage_on_save
        ? Math.floor(damageRoll.total / 2)
        : 0;
      requestPlayerSave.mutate({
        chosenTarget,
        failureDamage: damageRoll.total,
        successDamage,
      });
      return;
    }
    const modifier = activeCharacter
      ? actionModifier(activeCharacter, selectedAction)
      : selectedAction.attack_bonus ?? 3;
    const d20 = Math.floor(Math.random() * 20) + 1;
    const finalAttack = automatic ? d20 + modifier : Number(attackTotal);
    const hit = finalAttack >= chosenTarget.armor_class;
    const rolledDamage = rollDiceExpression(expression);
    const finalDamage = automatic ? rolledDamage.total : Number(damageTotal);
    if (!Number.isFinite(finalDamage) || finalDamage < 0) {
      showToast("请输入玩家掷出的最终伤害", "error");
      return;
    }
    const explanation = hit
      ? automatic
        ? `${active.display_name} → ${chosenTarget.display_name}，使用「${selectedAction.name ?? "攻击"}」：d20(${d20}) + ${modifier} = ${finalAttack}，命中 AC ${chosenTarget.armor_class}；伤害 ${expression.count}d${expression.sides}${expression.modifier ? `+${expression.modifier}` : ""} = ${finalDamage}`
        : `${active.display_name} → ${chosenTarget.display_name}，使用「${selectedAction.name ?? "攻击"}」：玩家报告命中总值 ${finalAttack}，达到 AC ${chosenTarget.armor_class}；玩家报告伤害 ${finalDamage}`
      : `${active.display_name} → ${chosenTarget.display_name}，使用「${selectedAction.name ?? "攻击"}」：命中总值 ${finalAttack}，未达到 AC ${chosenTarget.armor_class}；攻击落空但仍消耗${selectedAction.cost ?? "动作"}`;
    const command: CombatActionCommand = {
      action_type: "damage",
      actor_combatant_id: active.id,
      actor_version: active.version,
      action_cost: selectedActionCost,
      action_name: selectedAction.name ?? "攻击",
      resolution_note: hit
        ? `命中并造成 ${finalDamage} 点${selectedAction.damage_type ?? "未分类"}伤害`
        : `命中总值 ${finalAttack} 未达到 AC ${chosenTarget.armor_class}，攻击未命中`,
      target_combatant_id: chosenTarget.id,
      target_version: chosenTarget.version,
      amount: hit ? finalDamage : 0,
      damage_type: selectedAction.damage_type ?? "untyped",
    };
    if (fullyAutomaticEnemy) {
      autoResolve.mutate(command);
    } else {
      preview.mutate({ command, explanation });
    }
  };
  const prepareAreaSpell = () => {
    if (!selectedActionAvailable) {
      showToast(
        selectedResourceAvailable
          ? "本回合动作已经使用，请结束回合"
          : `${selectedResource?.label ?? "所需资源"}不足，无法施放`,
        "error",
      );
      return;
    }
    const affectedTargets = possibleTargets.filter((fighter) => validTargetIds?.has(fighter.id));
    if (affectedTargets.length === 0) {
      showToast("请先在战斗地图上选择范围中心或直线方向，并确保至少覆盖一个敌人", "error");
      return;
    }
    const reportedDamage = Number(damageTotal);
    if (!damageTotal || !Number.isFinite(reportedDamage) || reportedDamage < 0) {
      showToast(`请先让玩家掷 ${selectedAction.damage ?? "伤害骰"}，并输入最终伤害总值`, "error");
      return;
    }
    try {
      const resolution = resolveAreaSavingThrows({
        targets: affectedTargets.map((fighter) => ({
          id: fighter.id,
          name: fighter.display_name,
          abilityScores: fighter.snapshot_json.ability_scores as Record<string, number> | undefined,
          savingThrows: fighter.snapshot_json.saving_throws as Record<string, number> | undefined,
        })),
        damageExpression: selectedAction.damage ?? "",
        saveDc: Number(selectedAction.save_dc),
        saveAbility: String(selectedAction.save_ability),
        halfDamageOnSave: Boolean(selectedAction.half_damage_on_save),
        sharedDamage: reportedDamage,
      });
      setPending(null);
      setPendingArea({
        resolution,
        actionName: selectedAction.name ?? "区域法术",
        actionCost: selectedActionCost,
        damageType: selectedAction.damage_type ?? "untyped",
      });
    } catch (error) {
      showToast(error instanceof Error ? error.message : "无法计算区域法术", "error");
    }
  };
  const enemyTarget = chooseEnemyTarget(possibleTargets, tactics);
  const enemyReason = tactics === "instinctive"
    ? "本能型会扑向最先发现的目标。"
    : tactics === "standard"
      ? "普通敌人优先攻击当前生命最低的目标。"
      : tactics === "smart"
        ? "聪明敌人会集中攻击最虚弱的目标并利用自身动作。"
        : "战术敌人优先寻找低 AC、低生命目标，并保留撤退与控制空间。";
  useEffect(() => {
    if (!autoEnemies || !automationReady || active.entity_type === "character") return;
    if (processedAutomaticTurn.current === turnKey) return;
    if (!selectedActionAvailable) {
      processedAutomaticTurn.current = turnKey;
      onEnemyTurnComplete();
      return;
    }
    if (!enemyTarget) {
      processedAutomaticTurn.current = turnKey;
      onEnemyTurnComplete();
      return;
    }
    if (validTargetIds?.has(enemyTarget.id)) {
      processedAutomaticTurn.current = turnKey;
      setTargetId(enemyTarget.id);
      prepareAttack(true, enemyTarget, true);
      return;
    }
    if (active.movement_remaining_ft === 0) {
      processedAutomaticTurn.current = turnKey;
      onEnemyTurnComplete();
    }
    // React when pathfinding updates the combatant position/range.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    active.movement_remaining_ft,
    autoEnemies,
    automationReady,
    enemyTarget?.id,
    selectedActionAvailable,
    turnKey,
    validTargetIds,
  ]);

  return (
    <div className="mt-3 rounded-lg border-2 border-ember-500/50 bg-ember-950/10 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={active.entity_type === "character" ? "ok" : "danger"}>当前回合</Badge>
        <strong className="text-base text-parchment-100">{active.display_name}</strong>
        <span className="text-xs text-stone-400">{active.entity_type === "character" ? "等待玩家声明行动" : "敌人 AI 正在评估行动"}</span>
        <Badge tone={active.action_available ? "ok" : "neutral"}>动作：{active.action_available ? "可用" : "已用"}</Badge>
        <Badge tone={active.bonus_action_available ? "ok" : "neutral"}>附赠：{active.bonus_action_available ? "可用" : "已用"}</Badge>
        <Badge tone={active.reaction_available ? "ok" : "neutral"}>反应：{active.reaction_available ? "可用" : "已用"}</Badge>
        {active.entity_type === "character" ? (
          <div className="ml-auto">
            <span className="mb-1 block text-right text-2xs text-stone-500">玩家攻击结算</span>
            <div className="flex rounded border border-ink-600 p-0.5">
              <button className={`rounded px-2 py-1 text-2xs ${mode === "assisted" ? "bg-ember-600 text-white" : "text-stone-400"}`} onClick={() => setMode("assisted")} type="button">玩家报骰</button>
              <button className={`rounded px-2 py-1 text-2xs ${mode === "auto" ? "bg-ember-600 text-white" : "text-stone-400"}`} onClick={() => setMode("auto")} type="button">系统掷骰</button>
            </div>
          </div>
        ) : (
          <div className="ml-auto">
            <span className="mb-1 block text-right text-2xs text-stone-500">怪物回合控制</span>
            <div className="flex rounded border border-ink-600 p-0.5">
              <button className={`rounded px-2 py-1 text-2xs ${!autoEnemies ? "bg-stone-700 text-white" : "text-stone-400"}`} onClick={() => onAutoEnemiesChange(false)} type="button">DM手动</button>
              <button className={`rounded px-2 py-1 text-2xs ${autoEnemies ? "bg-ember-600 text-white" : "text-stone-400"}`} onClick={() => onAutoEnemiesChange(true)} type="button">怪物全自动</button>
            </div>
          </div>
        )}
      </div>

      {active.entity_type === "character" ? (
        <div className="mt-3 grid gap-3">
          <div className="rounded border border-ink-700 bg-ink-950/60 p-3">
            <strong className="text-xs text-parchment-100">角色卡动作与施法指示</strong>
            {activeCharacter && Object.keys(activeCharacter.skills).length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1">
                {Object.keys(activeCharacter.skills).map((skill) => (
                  <span className="rounded border border-sky-800/60 bg-sky-950/20 px-2 py-1 text-2xs text-sky-200" key={skill} title={`${skill}已熟练：相关检定使用 d20 + 对应属性调整值 + 熟练加值。`}>
                    {skill} · 熟练
                  </span>
                ))}
              </div>
            ) : null}
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <select className={selectCls} onChange={(event) => selectAction(event.target.value)} value={actionIndex}>
                {actions.length === 0 ? <option value="0">临时攻击 · 1d6 · 5尺</option> : null}
                {actions.map((action, index) => <option disabled={!hasActionEconomy(active, actionCost(action))} key={`${action.name}-${index}`} value={index}>{action.name ?? `动作${index + 1}`} · {action.damage ?? "按描述"} · {action.range ?? "5尺"}{!hasActionEconomy(active, actionCost(action)) ? " · 本回合已用" : ""}</option>)}
              </select>
              <select className={selectCls} onChange={(event) => { setTargetId(event.target.value); onTargetChange?.(event.target.value); }} value={targetId}>
                <option value="">选择目标</option>
                {possibleTargets.map((fighter) => <option disabled={Boolean(validTargetIds && !validTargetIds.has(fighter.id))} key={fighter.id} value={fighter.id}>{fighter.display_name} · AC {fighter.armor_class} · HP {fighter.hp}/{fighter.max_hp}{validTargetIds && !validTargetIds.has(fighter.id) ? " · 超出范围" : ""}</option>)}
              </select>
            </div>
            <p className="mb-2 mt-2 text-2xs text-stone-400">{selectedAction.cost ?? "动作"} · {actionRangeSummary(selectedAction)} · {selectedAction.description ?? "以角色卡和规则条目为准"}</p>
            <RuleBlockPlan source={selectedAction} title="当前动作执行积木" />
            {isNarrativeAction ? (
              <div className="rounded border border-violet-800/50 bg-violet-950/20 p-2">
                <p className="m-0 text-xs leading-5 text-violet-100">
                  这是叙事、辅助或持续效果法术，没有可直接套用的即时伤害公式。系统会显示规则描述、距离、持续时间与资源消耗，但不会虚构伤害；请在下方“自由行动裁定”记录具体目标和效果。
                </p>
                {selectedResourceKey ? <p className="mb-0 mt-1 text-2xs text-stone-400">施放时消耗 {selectedResourceCost} 点{selectedResource?.label ?? selectedResourceKey}；当前剩余 {Number(selectedResource?.current ?? 0)}。</p> : null}
              </div>
            ) : isAreaSaveAction ? (
              <div className="rounded border border-fuchsia-800/60 bg-fuchsia-950/20 p-2">
                <p className="m-0 text-xs text-fuchsia-100">
                  这是区域豁免法术，不进行攻击检定。先在地图选择
                  {selectedTargeting.shape === "circle" ? "爆发中心" : "直线方向"}；
                  当前覆盖 <strong>{possibleTargets.filter((fighter) => validTargetIds?.has(fighter.id)).length}</strong> 个敌人。
                  按 D&D 5e 规则，本次施法共用一次 {selectedAction.damage} 伤害骰；每个目标分别进行
                  {selectedAction.save_ability}豁免（DC {selectedAction.save_dc}），成功
                  {selectedAction.half_damage_on_save ? "伤害减半" : "不受伤害"}，再分别应用各自的抗性、易伤或免疫，因此最终扣血可以不同。
                </p>
                <p className="mb-2 mt-1 text-2xs text-stone-400">
                  范围内：{possibleTargets.filter((fighter) => validTargetIds?.has(fighter.id)).map((fighter) => fighter.display_name).join("、") || "尚未覆盖目标"}
                  {selectedResourceKey
                    ? ` · 消耗 ${selectedResourceCost} 点${selectedResource?.label ?? selectedResourceKey}（剩余 ${Number(selectedResource?.current ?? 0)}）`
                    : ""}
                </p>
                <div className="flex flex-wrap gap-2">
                  <input
                    aria-label="区域法术玩家伤害总值"
                    className={`${inputCls} w-36`}
                    min="0"
                    onChange={(event) => setDamageTotal(event.target.value)}
                    placeholder={`玩家掷 ${selectedAction.damage ?? "伤害骰"}`}
                    type="number"
                    value={damageTotal}
                  />
                  <Button
                    disabled={!selectedActionAvailable || !validTargetIds?.size || !damageTotal || confirmArea.isPending}
                    onClick={prepareAreaSpell}
                    variant="primary"
                  >
                    使用玩家伤害骰并预览豁免
                  </Button>
                </div>
              </div>
            ) : mode === "assisted" ? (
              <div className="rounded border border-sky-800/50 bg-sky-950/20 p-2">
                <p className="m-0 text-xs text-sky-200">
                  请玩家掷 d20 并加入角色卡命中调整值。
                  {target
                    ? <>最终命中总值至少需要达到 <strong>AC {target.armor_class}</strong>（即 ≥ {target.armor_class}）</>
                    : <>选择目标后，这里会明确显示需要达到的 AC</>}。
                  命中后再掷 {selectedAction.damage ?? "角色卡所列伤害骰"}；请输入最终总值，系统负责对比 AC、抗性与 HP。
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <input aria-label="玩家命中总值" className={`${inputCls} w-28`} onChange={(event) => setAttackTotal(event.target.value)} placeholder="命中总值" type="number" value={attackTotal} />
                  <input aria-label="玩家伤害总值" className={`${inputCls} w-28`} onChange={(event) => setDamageTotal(event.target.value)} placeholder="伤害总值" type="number" value={damageTotal} />
                  <Button disabled={!target || !selectedActionAvailable || preview.isPending} onClick={() => prepareAttack(false)} variant="primary">计算并预览</Button>
                </div>
              </div>
            ) : (
              <Button disabled={!target || !selectedActionAvailable || preview.isPending} onClick={() => prepareAttack(true)} variant="primary">自动掷命中与伤害</Button>
            )}
          </div>

          <div className="rounded border border-violet-800/50 bg-violet-950/10 p-3">
            <strong className="text-xs text-violet-200">自由行动裁定</strong>
            <textarea className={`${textareaCls} mt-2 min-h-20`} onChange={(event) => setFreeform(event.target.value)} placeholder="例如：我拿出怪物最害怕的圣徽，试图让它退缩。" value={freeform} />
            {check ? (
              <div className="mt-2 rounded border border-violet-800/50 p-2 text-xs text-stone-300">
                建议进行 <strong>{check.skill}（{check.abilityLabel}）</strong>检定：d20 {check.modifier >= 0 ? "+" : ""}{check.modifier}，目标 DC {check.dc}。{check.explanation}。
                <div className="mt-2 flex flex-wrap gap-2">
                  <input aria-label="自由行动检定总值" className={`${inputCls} w-32`} onChange={(event) => setCheckRoll(event.target.value)} placeholder="玩家最终总值" type="number" value={checkRoll} />
                  <select className={selectCls} onChange={(event) => setTargetId(event.target.value)} value={targetId}><option value="">效果目标</option>{possibleTargets.map((fighter) => <option key={fighter.id} value={fighter.id}>{fighter.display_name}</option>)}</select>
                  <input className={`${inputCls} min-w-48`} onChange={(event) => setEffectText(event.target.value)} value={effectText} />
                </div>
                <p className={`mb-0 mt-2 ${Number(checkRoll) >= check.dc ? "text-emerald-300" : "text-amber-300"}`}>{checkRoll ? (Number(checkRoll) >= check.dc ? "检定成功：可以预览并应用效果。" : "检定失败：记录叙事结果，不写入有利状态。") : "等待玩家骰点。"}</p>
                <Button className="mt-2" disabled={!target || Number(checkRoll) < check.dc || applyFreeform.isPending} onClick={() => applyFreeform.mutate()} size="sm" variant="primary">DM确认成功效果</Button>
              </div>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="mt-3 rounded border border-red-900/60 bg-red-950/10 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-auto text-xs text-red-200">敌人战斗 AI</strong>
            <select className={selectCls} onChange={(event) => setTactics(event.target.value as EnemyTactics)} value={tactics}>
              {Object.entries(ENEMY_TACTICS_LABELS).map(([value, label]) => <option key={value} value={value}>{label}智商</option>)}
            </select>
          </div>
          <p className="mb-2 mt-2 text-xs text-stone-300">建议目标：<strong>{enemyTarget?.display_name ?? "无有效玩家目标"}</strong>。{enemyReason}</p>
          <label className="mb-2 block text-2xs text-stone-400">
            本回合怪物动作
            <select className={`${selectCls} mt-1`} onChange={(event) => selectAction(event.target.value)} value={actionIndex}>
              {actions.length === 0 ? <option value="0">临时攻击 · 1d6 · 5尺</option> : null}
              {actions.map((action, index) => (
                <option disabled={!hasActionEconomy(active, actionCost(action))} key={`${action.name}-${index}`} value={index}>
                  {action.name ?? `动作${index + 1}`} · {action.damage ?? "按规则描述"} · {actionRangeSummary(action)}
                </option>
              ))}
            </select>
          </label>
          <p className="mb-2 mt-0 text-2xs text-stone-500">建议动作：{selectedAction.name ?? "基础攻击"} · {selectedAction.damage ?? "1d6"} · {actionRangeSummary(selectedAction)}。地图会先按剩余速度寻路；攻击检定由怪物自动掷，怪物能力要求豁免时会在右侧等待玩家输入骰值。</p>
          {autoEnemies ? (
            <div className="rounded border border-red-900/60 bg-red-950/20 p-2 text-xs text-red-100">
              全自动处理中：{active.display_name}会先移动到合法位置，再使用
              「{selectedAction.name ?? "基础攻击"}」攻击{enemyTarget?.display_name ?? "有效目标"}。
              若无需玩家掷骰，结算后会自动结束回合。
            </div>
          ) : (
            <div className="rounded border border-amber-800/60 bg-amber-950/15 p-2">
              <p className="mb-2 mt-0 text-xs text-amber-200">
                当前是 DM 手动模式，所以系统不会自行攻击。切换右上角“怪物全自动”后，怪物会立即自行选目标、移动、攻击并结束回合。
              </p>
              <Button disabled={!enemyTarget || !selectedActionAvailable || preview.isPending || requestPlayerSave.isPending || autoResolve.isPending} onClick={() => { if (enemyTarget) { setTargetId(enemyTarget.id); prepareAttack(true, enemyTarget); } }} variant="danger">手动执行怪物动作</Button>
            </div>
          )}
        </div>
      )}

      {pending ? (
        <div className="mt-3 rounded border border-amber-600/60 bg-amber-950/20 p-3">
          <strong className="text-xs text-amber-200">待 DM 确认的战斗结果</strong>
          <p className="mb-1 mt-1 text-xs text-stone-300">{pending.explanation}</p>
          <p className="mb-2 mt-0 text-2xs text-stone-500">HP {String(pending.preview.before.hp)} → {String(pending.preview.after.hp)}；尚未写入。</p>
          <div className="flex gap-2"><Button loading={confirm.isPending} onClick={() => confirm.mutate()} variant="primary">DM确认写入</Button><Button onClick={() => setPending(null)}>取消</Button></div>
        </div>
      ) : null}
      {pendingArea ? (
        <div className="mt-3 rounded border-2 border-fuchsia-600/60 bg-fuchsia-950/20 p-3">
          <strong className="text-xs text-fuchsia-100">
            {pendingArea.actionName} · 区域结算预览（尚未写入）
          </strong>
          <p className="mb-2 mt-1 text-xs text-stone-300">
            共用伤害骰 {pendingArea.resolution.damageExpression}：
            {pendingArea.resolution.damageRolls.length
              ? <>[{pendingArea.resolution.damageRolls.join(" + ")}] = </>
              : <>玩家报告最终总值 = </>}
            <strong>{pendingArea.resolution.sharedDamage}</strong>。
            下列每个目标独立豁免。
          </p>
          <ul className="m-0 space-y-1 pl-4 text-xs text-stone-300">
            {pendingArea.resolution.targets.map((result) => (
              <li key={result.targetId}>
                <strong>{result.targetName}</strong>：d20({result.d20}) {result.modifier >= 0 ? "+" : ""}{result.modifier}
                {" = "}{result.saveTotal} vs DC {pendingArea.resolution.saveDc}，
                <span className={result.success ? "text-emerald-300" : "text-red-300"}>
                  {result.success ? "成功" : "失败"}
                </span>
                ，预计 {result.damage} 点{pendingArea.damageType}伤害
              </li>
            ))}
          </ul>
          <div className="mt-3 flex gap-2">
            <Button loading={confirmArea.isPending} onClick={() => confirmArea.mutate()} variant="primary">
              DM确认对全部目标结算
            </Button>
            <Button disabled={confirmArea.isPending} onClick={() => setPendingArea(null)}>取消</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
