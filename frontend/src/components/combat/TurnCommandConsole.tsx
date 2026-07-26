import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactElement } from "react";

import {
  confirmCombatAction,
  previewCombatAction,
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
  parseDiceExpression,
  parseRangeFeet,
  proficiencyBonus,
  proposeFreeformCheck,
  rollDiceExpression,
  type CombatActionLike,
  type EnemyTactics,
} from "../../ui/combatAutomation";
import { Badge, Button } from "../../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../../ui/styles";
import type { TargetingTemplate } from "../../ui/gridTargeting";

export type CombatTargeting = TargetingTemplate & { label: string };

type PendingResolution = {
  command: CombatActionCommand;
  preview: CombatActionPreview;
  explanation: string;
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

export function TurnCommandConsole({
  active,
  activeCharacter,
  campaignId,
  combatId,
  fighters,
  onRangeChange,
  onTargetChange,
  selectedTargetId,
  validTargetIds,
}: {
  active: Combatant;
  activeCharacter?: Character;
  campaignId: string;
  combatId: string;
  fighters: Combatant[];
  onRangeChange: (range: CombatTargeting | null) => void;
  onTargetChange?: (targetId: string) => void;
  selectedTargetId?: string;
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
  const [freeform, setFreeform] = useState("");
  const [checkRoll, setCheckRoll] = useState("");
  const [effectText, setEffectText] = useState("无法行动（1轮）");
  const [tactics, setTactics] = useState<EnemyTactics>("standard");

  const actions = useMemo(
    () => activeCharacter
      ? [...activeCharacter.actions, ...activeCharacter.spells].map(normalizeAction)
      : ((active.snapshot_json.actions as unknown[] | undefined) ?? []).map(normalizeAction),
    [active.snapshot_json.actions, activeCharacter],
  );
  const selectedAction = actions[Number(actionIndex)] ?? actions[0] ?? {
    name: "临时攻击",
    damage: "1d6",
    range: "5尺",
    cost: "动作",
  };
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

  const selectAction = (value: string) => {
    setActionIndex(value);
    const action = actions[Number(value)] ?? selectedAction;
    const summary = actionRangeSummary(action);
    const targetingText = `${action.range ?? ""} ${action.description ?? ""}`;
    const sizeMatch = targetingText.match(/(\d+)\s*尺(?:半径|范围|球形|锥形|直线)/);
    onRangeChange({
      rangeFt: parseRangeFeet(action.range),
      sizeFt: sizeMatch ? Number(sizeMatch[1]) : undefined,
      shape: /锥形/.test(summary) ? "cone" : /直线/.test(summary) ? "line" : /圆形|球形|半径|爆炸/.test(targetingText) ? "circle" : "single",
      label: `${action.name ?? "动作"} · ${summary}`,
    });
  };
  useEffect(() => {
    if (selectedTargetId !== undefined && selectedTargetId !== targetId) {
      setTargetId(selectedTargetId);
    }
  }, [selectedTargetId, targetId]);
  useEffect(() => {
    selectAction("0");
    // The active fighter/action list changed; initialize the map indicator.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active.id]);
  const prepareAttack = (automatic: boolean, forcedTarget?: Combatant) => {
    const chosenTarget = forcedTarget ?? target;
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
    const modifier = activeCharacter ? actionModifier(activeCharacter, selectedAction) : 3;
    const d20 = Math.floor(Math.random() * 20) + 1;
    const finalAttack = automatic ? d20 + modifier : Number(attackTotal);
    const hit = finalAttack >= chosenTarget.armor_class;
    const rolledDamage = rollDiceExpression(expression);
    const finalDamage = automatic ? rolledDamage.total : Number(damageTotal);
    if (!hit) {
      showToast(`未命中：${finalAttack} < AC ${chosenTarget.armor_class}`, "error");
      return;
    }
    if (!Number.isFinite(finalDamage) || finalDamage < 0) {
      showToast("请输入玩家掷出的最终伤害", "error");
      return;
    }
    preview.mutate({
      command: {
        action_type: "damage",
        actor_combatant_id: active.id,
        target_combatant_id: chosenTarget.id,
        target_version: chosenTarget.version,
        amount: finalDamage,
        damage_type: "untyped",
      },
      explanation: automatic
        ? `${active.display_name} → ${chosenTarget.display_name}，使用「${selectedAction.name ?? "攻击"}」：d20(${d20}) + ${modifier} = ${finalAttack}，命中 AC ${chosenTarget.armor_class}；伤害 ${expression.count}d${expression.sides}${expression.modifier ? `+${expression.modifier}` : ""} = ${finalDamage}`
        : `${active.display_name} → ${chosenTarget.display_name}，使用「${selectedAction.name ?? "攻击"}」：玩家报告命中总值 ${finalAttack}，达到 AC ${chosenTarget.armor_class}；玩家报告伤害 ${finalDamage}`,
    });
  };
  const enemyTarget = chooseEnemyTarget(possibleTargets, tactics);
  const enemyReason = tactics === "instinctive"
    ? "本能型会扑向最先发现的目标。"
    : tactics === "standard"
      ? "普通敌人优先攻击当前生命最低的目标。"
      : tactics === "smart"
        ? "聪明敌人会集中攻击最虚弱的目标并利用自身动作。"
        : "战术敌人优先寻找低 AC、低生命目标，并保留撤退与控制空间。";

  return (
    <div className="mt-3 rounded-lg border-2 border-ember-500/50 bg-ember-950/10 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={active.entity_type === "character" ? "ok" : "danger"}>当前回合</Badge>
        <strong className="text-base text-parchment-100">{active.display_name}</strong>
        <span className="text-xs text-stone-400">{active.entity_type === "character" ? "等待玩家声明行动" : "敌人 AI 正在评估行动"}</span>
        <div className="ml-auto flex rounded border border-ink-600 p-0.5">
          <button className={`rounded px-2 py-1 text-2xs ${mode === "assisted" ? "bg-ember-600 text-white" : "text-stone-400"}`} onClick={() => setMode("assisted")} type="button">半自动</button>
          <button className={`rounded px-2 py-1 text-2xs ${mode === "auto" ? "bg-ember-600 text-white" : "text-stone-400"}`} onClick={() => setMode("auto")} type="button">自动</button>
        </div>
      </div>

      {active.entity_type === "character" ? (
        <div className="mt-3 grid gap-3 xl:grid-cols-[1fr_1fr]">
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
                {actions.map((action, index) => <option key={`${action.name}-${index}`} value={index}>{action.name ?? `动作${index + 1}`} · {action.damage ?? "按描述"} · {action.range ?? "5尺"}</option>)}
              </select>
              <select className={selectCls} onChange={(event) => { setTargetId(event.target.value); onTargetChange?.(event.target.value); }} value={targetId}>
                <option value="">选择目标</option>
                {possibleTargets.map((fighter) => <option disabled={Boolean(validTargetIds && !validTargetIds.has(fighter.id))} key={fighter.id} value={fighter.id}>{fighter.display_name} · AC {fighter.armor_class} · HP {fighter.hp}/{fighter.max_hp}{validTargetIds && !validTargetIds.has(fighter.id) ? " · 超出范围" : ""}</option>)}
              </select>
            </div>
            <p className="mb-2 mt-2 text-2xs text-stone-400">{selectedAction.cost ?? "动作"} · {actionRangeSummary(selectedAction)} · {selectedAction.description ?? "以角色卡和规则条目为准"}</p>
            {mode === "assisted" ? (
              <div className="rounded border border-sky-800/50 bg-sky-950/20 p-2">
                <p className="m-0 text-xs text-sky-200">请玩家先掷 d20 命中；命中后再掷 {selectedAction.damage ?? "角色卡所列伤害骰"}。输入最终总值，系统负责对比 AC、抗性与HP。</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <input aria-label="玩家命中总值" className={`${inputCls} w-28`} onChange={(event) => setAttackTotal(event.target.value)} placeholder="命中总值" type="number" value={attackTotal} />
                  <input aria-label="玩家伤害总值" className={`${inputCls} w-28`} onChange={(event) => setDamageTotal(event.target.value)} placeholder="伤害总值" type="number" value={damageTotal} />
                  <Button disabled={!target || preview.isPending} onClick={() => prepareAttack(false)} variant="primary">计算并预览</Button>
                </div>
              </div>
            ) : (
              <Button disabled={!target || preview.isPending} onClick={() => prepareAttack(true)} variant="primary">自动掷命中与伤害</Button>
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
          <p className="mb-2 mt-0 text-2xs text-stone-500">建议动作：{selectedAction.name ?? "基础攻击"} · {selectedAction.damage ?? "1d6"} · {actionRangeSummary(selectedAction)}。右侧日志会保留命中与伤害计算。</p>
          <Button disabled={!enemyTarget || preview.isPending} onClick={() => { if (enemyTarget) { setTargetId(enemyTarget.id); prepareAttack(true, enemyTarget); } }} variant="danger">自动执行敌人回合</Button>
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
    </div>
  );
}
