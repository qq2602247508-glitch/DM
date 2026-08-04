import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactElement } from "react";

import {
  confirmCombatAction,
  confirmPlayerRoll,
  createPlayerRollPrompt,
  previewPlayerRoll,
} from "../../api/entities";
import type {
  CombatAction,
  Combatant,
  PlayerRollResolutionResult,
  PlayerRollResolutionType,
} from "../../api/types";
import { useToast } from "../../hooks/toastContext";
import { Badge, Button } from "../../ui/primitives";
import { inputCls, selectCls, textareaCls } from "../../ui/styles";

const RESOLUTION_LABELS: Record<PlayerRollResolutionType, string> = {
  armor_class: "AC 防御",
  saving_throw: "属性豁免",
  ability_check: "属性检定",
  skill_check: "技能检定",
};

const ABILITY_LABELS: Record<string, string> = {
  strength: "力量",
  dexterity: "敏捷",
  constitution: "体质",
  intelligence: "智力",
  wisdom: "感知",
  charisma: "魅力",
};

function textField(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberField(value: unknown): number {
  return typeof value === "number" ? value : Number(value) || 0;
}

function actionNameOf(raw: unknown): string {
  if (typeof raw === "string") return raw;
  if (raw && typeof raw === "object" && "name" in raw) {
    return textField((raw as { name?: unknown }).name);
  }
  return "";
}

function parseDamageSegments(value: string): Array<{ amount: number; damage_type: string }> {
  return value
    .split(/[\n,;]+/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const match = item.match(/^(.+?)(?:\s*[:=]\s*|\s+)(\d+)$/);
      if (!match) throw new Error(`伤害段格式错误：${item}；请写成 fire:7 或 fire 7`);
      const amount = Number(match[2]);
      if (!Number.isInteger(amount) || amount < 0) throw new Error(`伤害段数值错误：${item}`);
      return { damage_type: (match[1] ?? "").trim(), amount };
    })
    .filter((item) => item.damage_type.length > 0);
}

export function PlayerRollPanel({
  activeEnemy,
  actions,
  automationEnabled = false,
  campaignId,
  combatId,
  fighters,
  onResolved,
}: {
  activeEnemy?: Combatant;
  actions: CombatAction[];
  automationEnabled?: boolean;
  campaignId: string;
  combatId: string;
  fighters: Combatant[];
  onResolved?: (action: CombatAction) => void;
}): ReactElement | null {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [targetId, setTargetId] = useState("");
  const [actionName, setActionName] = useState("基础攻击");
  const [resolutionType, setResolutionType] =
    useState<PlayerRollResolutionType>("saving_throw");
  const [dc, setDc] = useState("12");
  const [ability, setAbility] = useState("dexterity");
  const [skill, setSkill] = useState("");
  const [damageOnSuccess, setDamageOnSuccess] = useState("0");
  const [damageOnFailure, setDamageOnFailure] = useState("0");
  const [damageType, setDamageType] = useState("");
  const [damageSuccessSegments, setDamageSuccessSegments] = useState("");
  const [damageFailureSegments, setDamageFailureSegments] = useState("");
  const [rolls, setRolls] = useState<Record<string, string>>({});
  const [useFeatureReroll, setUseFeatureReroll] = useState<Record<string, boolean>>({});
  const [useLegendaryResistance, setUseLegendaryResistance] = useState<Record<string, boolean>>({});
  const [previews, setPreviews] = useState<Record<string, PlayerRollResolutionResult>>({});

  const pending = useMemo(
    () => actions.filter(
      (action) => action.action_type === "player_roll_prompt" && action.status === "previewed",
    ),
    [actions],
  );
  const enemyActions = useMemo(
    () => ((activeEnemy?.snapshot_json.actions as unknown[] | undefined) ?? [])
      .map(actionNameOf)
      .filter(Boolean),
    [activeEnemy?.snapshot_json.actions],
  );
  useEffect(() => {
    setTargetId("");
    setActionName(enemyActions[0] ?? "基础攻击");
  }, [activeEnemy?.id, enemyActions]);
  const playerTargets = fighters.filter(
    (fighter) => fighter.entity_type === "character" && fighter.hp > 0,
  );
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
    void client.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
    void client.invalidateQueries({ queryKey: ["combat-end-condition", campaignId, combatId] });
  };
  const createPrompt = useMutation({
    mutationFn: () => {
      const target = fighters.find((fighter) => fighter.id === targetId);
      if (!activeEnemy || !target) throw new Error("请选择动作发起者和玩家目标");
      if ((Number(damageOnSuccess) > 0 || Number(damageOnFailure) > 0) && !damageType.trim()
        && !damageSuccessSegments.trim() && !damageFailureSegments.trim()) {
        throw new Error("请填写明确伤害类型，不能默认当作未分类伤害");
      }
      const successSegments = parseDamageSegments(damageSuccessSegments);
      const failureSegments = parseDamageSegments(damageFailureSegments);
      return createPlayerRollPrompt(campaignId, combatId, {
        actor_combatant_id: activeEnemy.id,
        actor_version: activeEnemy.version,
        target_combatant_id: target.id,
        target_version: target.version,
        action_name: actionName.trim(),
        resolution_type: resolutionType,
        dc: Number(dc),
        ability: resolutionType === "saving_throw" || resolutionType === "ability_check"
          ? ability
          : null,
        skill: resolutionType === "skill_check" ? skill : null,
        damage_on_success: Number(damageOnSuccess),
        damage_on_failure: Number(damageOnFailure),
        damage_components_on_success: successSegments,
        damage_components_on_failure: failureSegments,
        damage_type: Number(damageOnSuccess) > 0 || Number(damageOnFailure) > 0
          ? damageType.trim() || successSegments[0]?.damage_type || failureSegments[0]?.damage_type
          : null,
        description: `${activeEnemy.display_name} 使用 ${actionName}，等待玩家亲自掷骰。`,
      });
    },
    onSuccess: () => {
      invalidate();
      showToast("已生成玩家掷骰请求，尚未结算");
    },
    onError: () => showToast("无法生成玩家掷骰请求，请检查动作、DC和伤害类型", "error"),
  });
  const preview = useMutation({
    mutationFn: (action: CombatAction) => {
      const values = (rolls[action.id] ?? "")
        .split(/[\s,;]+/)
        .filter(Boolean)
        .map(Number);
      if (values.some((value) => !Number.isFinite(value))) throw new Error("请输入有效骰值");
      return previewPlayerRoll(campaignId, combatId, action.id, {
        action_version: action.version,
        roll_total: values[0] ?? 0,
        ...(useFeatureReroll[action.id]
          ? { roll_totals: values, use_feature_reroll: true }
          : {}),
        ...(useLegendaryResistance[action.id]
          ? { use_legendary_resistance: true }
          : {}),
      });
    },
    onSuccess: (result) => {
      setPreviews((current) => ({ ...current, [result.action.id]: result }));
    },
    onError: () => showToast("无法预览玩家骰结果", "error"),
  });
  const confirm = useMutation({
    mutationFn: async (action: CombatAction) => {
      const values = (rolls[action.id] ?? "")
        .split(/[\s,;]+/)
        .filter(Boolean)
        .map(Number);
      if (values.some((value) => !Number.isFinite(value))) throw new Error("请输入有效骰值");
      const resolution = await confirmPlayerRoll(campaignId, combatId, action.id, {
        action_version: action.version,
        roll_total: values[0] ?? 0,
        ...(useFeatureReroll[action.id]
          ? { roll_totals: values, use_feature_reroll: true }
          : {}),
        ...(useLegendaryResistance[action.id]
          ? { use_legendary_resistance: true }
          : {}),
      });
      const followUp = resolution.resolution.follow_up_damage;
      if (followUp) {
        await confirmCombatAction(
          campaignId,
          combatId,
          followUp,
          `player-roll-damage-${action.id}`,
        );
      }
      return resolution;
    },
    onSuccess: (result) => {
      invalidate();
      showToast("玩家骰结果已由 DM 确认并写入战斗日志");
      onResolved?.(result.action);
    },
    onError: () => showToast("确认失败：目标状态可能已变化，请重新预览", "error"),
  });

  if (!activeEnemy && pending.length === 0) return null;

  return (
    <section className="mt-3 rounded-lg border border-sky-800/60 bg-sky-950/10 p-3">
      <div className="flex items-center gap-2">
        <Badge tone="neutral">玩家掷骰</Badge>
        <strong className="text-sm text-sky-100">怪物动作与玩家豁免</strong>
      </div>

      {activeEnemy && automationEnabled ? (
        <div className="mt-3 rounded border border-red-900/50 bg-red-950/10 p-2">
          <strong className="text-xs text-red-200">{activeEnemy.display_name} 正在自动行动</strong>
          <p className="mb-0 mt-1 text-2xs leading-5 text-stone-400">
            怪物会自行选择技能、寻路、攻击并结束回合。普通攻击由怪物自动掷攻击骰并与玩家 AC 比较；
            只有属性豁免、检定等确实需要玩家掷骰时，流程才会停在下方等待输入。
          </p>
          {pending.length === 0 ? (
            <p className="mb-0 mt-1 text-2xs text-emerald-300">当前无需玩家掷骰，正在等待怪物动作结算。</p>
          ) : null}
        </div>
      ) : activeEnemy ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <label className="text-2xs text-stone-400">
            谁攻击谁
            <select
              aria-label="玩家骰目标"
              className={`${selectCls} mt-1`}
              onChange={(event) => setTargetId(event.target.value)}
              value={targetId}
            >
              <option value="">选择玩家目标</option>
              {playerTargets.map((fighter) => (
                <option key={fighter.id} value={fighter.id}>
                  {activeEnemy.display_name} → {fighter.display_name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-2xs text-stone-400">
            使用什么
            {enemyActions.length > 0 ? (
              <select
                aria-label="怪物动作名称"
                className={`${selectCls} mt-1`}
                onChange={(event) => setActionName(event.target.value)}
                value={actionName}
              >
                {enemyActions.map((name, index) => (
                  <option key={`${name}-${index}`} value={name}>{name}</option>
                ))}
              </select>
            ) : (
              <input
                aria-label="怪物动作名称"
                className={`${inputCls} mt-1`}
                onChange={(event) => setActionName(event.target.value)}
                value={actionName}
              />
            )}
          </label>
          <label className="text-2xs text-stone-400">
            玩家需要掷
            <select
              aria-label="玩家骰类型"
              className={`${selectCls} mt-1`}
              onChange={(event) =>
                setResolutionType(event.target.value as PlayerRollResolutionType)}
              value={resolutionType}
            >
              {Object.entries(RESOLUTION_LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label className="text-2xs text-stone-400">
            目标 DC
            <input
              aria-label="玩家骰DC"
              className={`${inputCls} mt-1`}
              min="0"
              onChange={(event) => setDc(event.target.value)}
              type="number"
              value={dc}
            />
          </label>
          {resolutionType === "saving_throw" || resolutionType === "ability_check" ? (
            <label className="text-2xs text-stone-400">
              属性
              <select
                aria-label="检定属性"
                className={`${selectCls} mt-1`}
                onChange={(event) => setAbility(event.target.value)}
                value={ability}
              >
                {["strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"]
                  .map((value) => <option key={value} value={value}>{ABILITY_LABELS[value]}</option>)}
              </select>
            </label>
          ) : null}
          {resolutionType === "skill_check" ? (
            <label className="text-2xs text-stone-400">
              技能
              <input
                aria-label="检定技能"
                className={`${inputCls} mt-1`}
                onChange={(event) => setSkill(event.target.value)}
                value={skill}
              />
            </label>
          ) : null}
          <label className="text-2xs text-stone-400">
            成功伤害
            <input className={`${inputCls} mt-1`} min="0" onChange={(event) => setDamageOnSuccess(event.target.value)} type="number" value={damageOnSuccess} />
          </label>
          <label className="text-2xs text-stone-400">
            失败伤害
            <input className={`${inputCls} mt-1`} min="0" onChange={(event) => setDamageOnFailure(event.target.value)} type="number" value={damageOnFailure} />
          </label>
          <label className="text-2xs text-stone-400">
            伤害类型
            <input className={`${inputCls} mt-1`} onChange={(event) => setDamageType(event.target.value)} value={damageType} />
          </label>
          <label className="text-2xs text-stone-400 sm:col-span-2">
            成功时逐段伤害（可选；每行写 fire:7 或 fire 7）
            <textarea
              aria-label="成功时逐段伤害"
              className={`${textareaCls} mt-1 min-h-12`}
              onChange={(event) => setDamageSuccessSegments(event.target.value)}
              placeholder="例如：fire:3\ncold:2"
              value={damageSuccessSegments}
            />
          </label>
          <label className="text-2xs text-stone-400 sm:col-span-2">
            失败时逐段伤害（可选；每段会独立应用抗性/易伤/免疫）
            <textarea
              aria-label="失败时逐段伤害"
              className={`${textareaCls} mt-1 min-h-12`}
              onChange={(event) => setDamageFailureSegments(event.target.value)}
              placeholder="例如：fire:7\ncold:5"
              value={damageFailureSegments}
            />
          </label>
          <div className="flex items-end">
            <Button
              disabled={!targetId || !actionName.trim() || !activeEnemy.action_available || createPrompt.isPending}
              loading={createPrompt.isPending}
              onClick={() => createPrompt.mutate()}
              variant="primary"
            >
              {activeEnemy.action_available ? "要求玩家掷骰" : "本回合动作已使用"}
            </Button>
          </div>
        </div>
      ) : null}

      {pending.map((action) => {
        const request = action.request_json;
        const result = previews[action.id];
        const rollValue = rolls[action.id] ?? "";
        const rollTarget = fighters.find((fighter) => fighter.id === action.target_combatant_ids[0]);
        const featureRerollAvailable = Array.isArray(rollTarget?.snapshot_json.feature_saving_throw_rerolls)
          && rollTarget.snapshot_json.feature_saving_throw_rerolls.some(
            (item) => item && typeof item === "object" && (item as { available?: unknown }).available === true,
          );
        const rawLegendaryResistance = rollTarget?.snapshot_json.advanced_defenses;
        const legendaryResistance = rawLegendaryResistance
          && typeof rawLegendaryResistance === "object"
          && !Array.isArray(rawLegendaryResistance)
          && typeof (rawLegendaryResistance as { legendary_resistance?: unknown }).legendary_resistance === "object"
          && !Array.isArray((rawLegendaryResistance as { legendary_resistance?: unknown }).legendary_resistance)
          ? (rawLegendaryResistance as { legendary_resistance: { remaining?: unknown; maximum?: unknown } }).legendary_resistance
          : null;
        const legendaryResistanceRemaining = legendaryResistance
          ? Number(legendaryResistance.remaining ?? 0)
          : 0;
        const legendaryResistanceAvailable = request.resolution_type === "saving_throw"
          && Number.isFinite(legendaryResistanceRemaining)
          && legendaryResistanceRemaining > 0;
        return (
          <article className="mt-3 rounded border border-sky-800/50 bg-ink-950/70 p-3" key={action.id}>
            <strong className="text-xs text-parchment-100">
              {textField(request.actor_name)} → {textField(request.target_name)}
              {" · "}{textField(request.action_name)}
            </strong>
            <p className="mb-2 mt-1 text-xs text-stone-300">
              玩家掷 {textField(request.roll_formula) || "1d20"}，
              {RESOLUTION_LABELS[request.resolution_type as PlayerRollResolutionType]}，
              DC {numberField(request.dc)}
              {textField(request.ability)
                ? ` · ${ABILITY_LABELS[textField(request.ability)] ?? textField(request.ability)}`
                : ""}
              {textField(request.skill) ? ` · ${textField(request.skill)}` : ""}
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <input
                aria-label={`${textField(request.target_name)}玩家骰结果`}
                className={`${inputCls} w-36`}
                onChange={(event) =>
                  setRolls((current) => ({ ...current, [action.id]: event.target.value }))}
                placeholder={featureRerollAvailable ? "总值；重掷时写 12,18" : "玩家最终总值"}
                type="number"
                value={rollValue}
              />
              {featureRerollAvailable && request.resolution_type === "saving_throw" ? (
                <label className="flex items-center gap-1 text-2xs text-violet-200">
                  <input
                    checked={useFeatureReroll[action.id] === true}
                    onChange={(event) => setUseFeatureReroll((current) => ({ ...current, [action.id]: event.target.checked }))}
                    type="checkbox"
                  />
                  使用职业特性重掷（填两次总值）
                </label>
              ) : null}
              {legendaryResistanceAvailable ? (
                <label className="flex items-center gap-1 text-2xs text-fuchsia-200">
                  <input
                    checked={useLegendaryResistance[action.id] === true}
                    onChange={(event) => setUseLegendaryResistance((current) => ({ ...current, [action.id]: event.target.checked }))}
                    type="checkbox"
                  />
                  失败时使用传奇抗性（剩余 {legendaryResistanceRemaining} 次；将本次豁免视为成功）
                </label>
              ) : null}
              <Button disabled={rollValue === "" || preview.isPending} onClick={() => preview.mutate(action)}>
                预览结果
              </Button>
              <Button
                disabled={!result || confirm.isPending}
                loading={confirm.isPending}
                onClick={() => confirm.mutate(action)}
                variant="primary"
              >
                DM确认
              </Button>
            </div>
            {result ? (
              <p className={`mb-0 mt-2 text-xs ${result.resolution.success ? "text-emerald-300" : "text-amber-300"}`}>
                {textField(request.target_name)} 的结果 {result.resolution.roll_total}
                {" / DC "}{result.resolution.dc}：
                {result.resolution.success ? "成功" : "失败"}
                {result.resolution.damage
                  ? `；将结算 ${result.resolution.damage} 点 ${result.resolution.damage_type ?? ""}伤害`
                  : "；无伤害"}
              </p>
            ) : (
              <p className="mb-0 mt-2 text-2xs text-stone-500">尚未写入。玩家报出骰值后先预览，再由 DM 确认。</p>
            )}
          </article>
        );
      })}
    </section>
  );
}
