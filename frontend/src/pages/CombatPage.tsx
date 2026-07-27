import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactElement } from "react";

import {
  advanceCombatTurn, confirmCombatAction, confirmCombatEffect,
  confirmCombatSettlement, confirmCombatantDeath, confirmConcentrationCheck,
  confirmDeathSave, createCombat, createCombatant, deleteCombatant, endCombatEffect,
  createEvent, getCombatEndCondition, getDeathSave, listCombatActions, listCombatEffects, listCombatants, listCombats,
  listEncounterAdjustments, listEvents, previewCombatAction,
  previewCombatSettlement, resetCombat, revertEncounterAdjustment, updateCombat, updateCombatant,
} from "../api/entities";
import type {
  CombatActionCommand, CombatEffectCommand, CombatSettlementCommand,
} from "../api/entities";
import { listCharacters, listLocations, listNpcs, updateCharacter } from "../api/entities";
import { listMonsters, listScenes } from "../api/world";
import { setPlayerRoomLiveState } from "../api/playerRoom";
import type {
  Combat, CombatAction, CombatActionPreview, CombatEffect, CombatSettlementPreview, Combatant,
  Character, EncounterAdjustment, Monster, Npc, SceneGrid,
} from "../api/types";
import { RequireCampaign } from "../components/RequireCampaign";
import { Panel } from "../components/Panel";
import { inputCls } from "../ui/styles";
import { Badge, Button, EmptyState, ErrorState, LoadingBlock } from "../ui/primitives";
import { COMBAT_STATUS_LABELS } from "../ui/styles";
import { HpBar } from "../ui/widgets";
import { useToast } from "../hooks/toastContext";
import { navigate } from "../hooks/useHashRoute";
import { PlayerRollPanel } from "../components/combat/PlayerRollPanel";
import { InitiativeCardStrip } from "../components/combat/InitiativeCardStrip";
import {
  TurnCommandConsole,
  type CombatTargeting,
} from "../components/combat/TurnCommandConsole";
import {
  DIFFICULTY_LABELS, encounterDifficulty, shiftDifficulty, xpForChallengeRating,
  type Difficulty,
} from "../ui/progressionRules";
import {
  describeEncounterOperation, difficultyShiftLabel,
} from "../ui/encounterAdjustments";
import {
  actionEconomySummary, damageModifierLabel, deathSaveSummary,
} from "../ui/combatPresentation";
import {
  planApproachPath,
  shortestMovementPath,
  type MovementPlan,
} from "../ui/combatMovement";
import {
  getTargetingCells,
  gridDistanceFt,
  isAimPointInRange,
  isBlockedCell,
  type GridPoint,
} from "../ui/gridTargeting";
import {
  findSceneSpawnCells,
  generateTacticalSceneGrid,
} from "../ui/sceneGridGenerator";

type CombatCandidate = {
  key: string;
  entityType: "character" | "npc" | "monster";
  entityId: string;
  name: string;
  armorClass: number;
  hp: number;
  maxHp: number;
  dexterity: number;
  speed: number;
  actions: unknown[];
  abilityScores: Record<string, number>;
  character?: Character;
  challengeRating?: string | null;
};

function readSceneGrid(notes: string | null): SceneGrid | null {
  if (!notes) return null;
  try {
    return (JSON.parse(notes) as { scene_grid?: SceneGrid }).scene_grid ?? null;
  } catch {
    return null;
  }
}

function CombatLogPanel({ actions }: { actions: CombatAction[] }): ReactElement {
  const [expanded, setExpanded] = useState(true);
  return (
    <section className="mt-3 rounded-lg border border-ink-700 bg-ink-950/45 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">历史</Badge>
        <strong className="text-sm text-parchment-100">战斗日志</strong>
        <span className="text-2xs text-stone-500">记录攻击者 → 目标 → 技能/法术 → 骰值 → 结果</span>
        <button
          aria-expanded={expanded}
          aria-label={expanded ? "收起战斗日志" : "展开战斗日志"}
          className="ml-auto flex size-7 items-center justify-center rounded border border-ink-600 bg-ink-900 text-base font-bold text-stone-300 hover:border-ember-600 hover:text-ember-200"
          onClick={() => setExpanded((value) => !value)}
          type="button"
        >
          {expanded ? "−" : "+"}
        </button>
      </div>
      {expanded && actions.length > 0 ? (
        <ol className="mb-0 mt-2 grid max-h-56 gap-2 overflow-y-auto p-0 text-2xs text-stone-400 md:grid-cols-2">
          {[...actions].reverse().map((action) => (
            <li className="list-none rounded border border-ink-800 bg-ink-950/70 p-2" key={action.id}>
              <span className="text-stone-600">R{action.round_number} · T{action.turn_index + 1}</span>
              <strong className="mt-0.5 block text-stone-200">{action.summary}</strong>
              {action.explanation ? <span className="mt-1 block leading-5 text-stone-500">{action.explanation}</span> : null}
            </li>
          ))}
        </ol>
      ) : expanded ? (
        <p className="mb-0 mt-2 text-2xs text-stone-600">行动确认后会按时间倒序显示在这里。</p>
      ) : null}
    </section>
  );
}

function displayValue(value: unknown, fallback = "0"): string {
  return typeof value === "string" || typeof value === "number"
    ? String(value)
    : fallback;
}

function CombatantRow({ campaignId, combat, fighter, current, character, effects, combatants }: { campaignId: string; combat: Combat; fighter: Combatant; current: boolean; character?: Character; effects: CombatEffect[]; combatants: Combatant[] }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [amount, setAmount] = useState("1");
  const [damageType, setDamageType] = useState("slashing");
  const [condition, setCondition] = useState("");
  const [effectName, setEffectName] = useState("");
  const [effectRounds, setEffectRounds] = useState("1");
  const [effectConcentration, setEffectConcentration] = useState(false);
  const [deathRoll, setDeathRoll] = useState("10");
  const [concentrationRoll, setConcentrationRoll] = useState("10");
  const [pendingConcentration, setPendingConcentration] = useState<{
    actionId: string;
    dc: number;
  } | null>(null);
  const [pendingAction, setPendingAction] = useState<{
    command: CombatActionCommand;
    preview: CombatActionPreview;
  } | null>(null);
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["combatants", campaignId, combat.id] });
    void client.invalidateQueries({ queryKey: ["combat-actions", campaignId, combat.id] });
    void client.invalidateQueries({ queryKey: ["combat-effects", campaignId, combat.id] });
    void client.invalidateQueries({ queryKey: ["death-save", campaignId, combat.id, fighter.id] });
    void client.invalidateQueries({ queryKey: ["combat-end-condition", campaignId, combat.id] });
    void client.invalidateQueries({ queryKey: ["campaign-state", campaignId] });
  };
  const change = useMutation({
    mutationFn: (payload: { hp?: number; conditions?: unknown[] }) => updateCombatant(campaignId, combat.id, fighter.id, payload, fighter.version),
    onSuccess: () => { invalidate(); showToast("战斗状态已更新"); },
    onError: () => showToast("战斗状态更新失败", "error"),
  });
  const previewAction = useMutation({
    mutationFn: (command: CombatActionCommand) =>
      previewCombatAction(campaignId, combat.id, command),
    onSuccess: (preview, command) => setPendingAction({ command, preview }),
    onError: () => showToast("无法生成结算预览，请刷新战斗状态", "error"),
  });
  const confirmAction = useMutation({
    mutationFn: (command: CombatActionCommand) =>
      confirmCombatAction(campaignId, combat.id, command),
    onSuccess: (result) => {
      setPendingAction(null);
      invalidate();
      const dc = Number(result.action.result_json.concentration_check_dc ?? 0);
      if (dc > 0) setPendingConcentration({ actionId: result.action.id, dc });
      showToast(dc > 0 ? `结算完成；需要专注检定 DC ${dc}` : "结算已确认并写入战斗日志");
    },
    onError: () => showToast("确认失败，目标状态可能已变化，请重新预览", "error"),
  });
  const deathSave = useQuery({
    queryKey: ["death-save", campaignId, combat.id, fighter.id],
    queryFn: ({ signal }) => getDeathSave(campaignId, combat.id, fighter.id, signal),
    enabled: fighter.entity_type === "character" && fighter.hp === 0,
  });
  const rollDeathSave = useMutation({
    mutationFn: () => confirmDeathSave(
      campaignId,
      combat.id,
      fighter.id,
      fighter.version,
      Number(deathRoll),
    ),
    onSuccess: () => {
      invalidate();
      showToast("死亡豁免已由 DM 确认");
    },
    onError: () => showToast("死亡豁免记录失败，请刷新后重试", "error"),
  });
  const confirmDeath = useMutation({
    mutationFn: () => confirmCombatantDeath(
      campaignId,
      combat.id,
      fighter.id,
      fighter.version,
      "三次死亡豁免失败，DM在战斗台确认",
    ),
    onSuccess: () => {
      invalidate();
      showToast("死亡状态已由 DM 最终确认");
    },
    onError: () => showToast("死亡确认失败，请刷新状态", "error"),
  });
  const addEffect = useMutation({
    mutationFn: () => {
      const command: CombatEffectCommand = {
        target_combatant_id: fighter.id,
        target_version: fighter.version,
        source_combatant_id: effectConcentration ? fighter.id : null,
        name: effectName.trim(),
        effect_type: "condition",
        duration_unit: effectConcentration ? "concentration" : "rounds",
        duration_value: effectConcentration ? null : Math.max(0, Number(effectRounds)),
        requires_concentration: effectConcentration,
        trigger_timing: "turn_end",
      };
      return confirmCombatEffect(campaignId, combat.id, command);
    },
    onSuccess: (result) => {
      setEffectName("");
      invalidate();
      showToast(result.ended_effects.length > 0
        ? `效果已建立，并结束 ${result.ended_effects.length} 个旧专注效果`
        : "结构化效果已建立");
    },
    onError: () => showToast("效果建立失败，请刷新战斗员状态", "error"),
  });
  const endEffect = useMutation({
    mutationFn: (effect: CombatEffect) => endCombatEffect(
      campaignId,
      combat.id,
      effect.id,
      fighter.version,
      effect.source_combatant_id && effect.source_combatant_id !== fighter.id
        ? combatants.find((item) => item.id === effect.source_combatant_id)?.version ?? null
        : null,
      "DM在战斗台确认效果结束",
    ),
    onSuccess: () => {
      invalidate();
      showToast("效果已确认结束");
    },
    onError: () => showToast("效果结束失败，请刷新后重试", "error"),
  });
  const resolveConcentration = useMutation({
    mutationFn: () => {
      if (!pendingConcentration) throw new Error("没有待处理专注检定");
      return confirmConcentrationCheck(campaignId, combat.id, {
        combatant_id: fighter.id,
        target_version: fighter.version,
        damage_action_id: pendingConcentration.actionId,
        roll_total: Number(concentrationRoll),
      });
    },
    onSuccess: (result) => {
      setPendingConcentration(null);
      invalidate();
      showToast(result.success ? "专注检定成功" : "专注检定失败，相关效果已结束");
    },
    onError: () => showToast("专注检定确认失败，请刷新状态", "error"),
  });
  const remove = useMutation({
    mutationFn: () => deleteCombatant(campaignId, combat.id, fighter.id, fighter.version),
    onSuccess: () => { invalidate(); showToast("参与者已移除"); },
    onError: () => showToast("参与者移除失败", "error"),
  });
  const spendResource = useMutation({
    mutationFn: (key: string) => {
      if (!character) throw new Error("没有关联角色");
      const resource = character.resources[key] as { current?: number; max?: number; label?: string; recovery?: string } | undefined;
      if (!resource || Number(resource.current ?? 0) <= 0) throw new Error("资源不足");
      return updateCharacter(campaignId, character.id, {
        resources: { ...character.resources, [key]: { ...resource, current: Number(resource.current ?? 0) - 1 } },
      }, character.version);
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      showToast("角色资源已消耗并同步到角色卡");
    },
    onError: () => showToast("资源消耗失败，请刷新角色状态", "error"),
  });
  const requestPreview = (actionType: "damage" | "heal") => {
    const numericAmount = Math.max(0, Number(amount));
    previewAction.mutate({
      action_type: actionType,
      target_combatant_id: fighter.id,
      target_version: fighter.version,
      amount: numericAmount,
      damage_type: actionType === "damage" ? damageType : null,
    });
  };
  const effectiveMaxHp = Math.max(0, fighter.max_hp - fighter.max_hp_reduction);
  return (
    <li className={`grid gap-2 rounded-md border px-3 py-2 md:grid-cols-[3rem_1fr_12rem_auto] md:items-center ${current ? "border-ember-500/50 bg-ember-500/5" : "border-ink-700 bg-ink-950/40"}`}>
      <span className="text-center"><strong className="block font-mono text-sm text-ember-300">{fighter.initiative}</strong><span className="block text-2xs text-stone-600">先攻</span></span>
      <div className="min-w-0">
        <p className="m-0 truncate text-sm text-parchment-100">{fighter.display_name}</p>
        <p className="mb-0 mt-0.5 text-2xs text-stone-500">护甲 AC {fighter.armor_class} · {fighter.entity_type === "character" ? "玩家" : fighter.entity_type === "npc" ? "NPC" : "怪物"} · {actionEconomySummary(fighter)}</p>
        <p className="mb-0 mt-0.5 text-2xs text-stone-600">
          {fighter.temporary_hp > 0 ? `临时生命 ${fighter.temporary_hp} · ` : ""}
          {fighter.max_hp_reduction > 0 ? `有效生命上限 ${effectiveMaxHp}（下降 ${fighter.max_hp_reduction}） · ` : ""}
          {fighter.conditions.length > 0 ? `状态：${fighter.conditions.join("、")} · ` : ""}
          {Object.keys(fighter.concentration).length > 0 ? "正在专注" : "未专注"}
        </p>
        {fighter.damage_resistances.length + fighter.damage_vulnerabilities.length + fighter.damage_immunities.length > 0 ? (
          <p className="mb-0 mt-0.5 text-2xs text-stone-600">
            {fighter.damage_resistances.length > 0 ? `抗性：${fighter.damage_resistances.join("、")} ` : ""}
            {fighter.damage_vulnerabilities.length > 0 ? `易伤：${fighter.damage_vulnerabilities.join("、")} ` : ""}
            {fighter.damage_immunities.length > 0 ? `免疫：${fighter.damage_immunities.join("、")}` : ""}
          </p>
        ) : null}
      </div>
      <div><HpBar hp={fighter.hp} maxHp={effectiveMaxHp} />{fighter.temporary_hp > 0 ? <p className="m-0 text-center text-2xs text-sky-300">+{fighter.temporary_hp} 临时生命</p> : null}</div>
      <div className="flex flex-wrap justify-end gap-1">
        <input aria-label={`${fighter.display_name} 数值`} className="w-14 rounded border border-ink-600 bg-ink-950 px-1.5 py-1 text-xs text-parchment-100" min="1" onChange={(event) => setAmount(event.target.value)} type="number" value={amount} />
        <select aria-label={`${fighter.display_name} 伤害类型`} className="rounded border border-ink-600 bg-ink-950 px-1.5 py-1 text-xs text-parchment-100" onChange={(event) => setDamageType(event.target.value)} value={damageType}>
          <option value="slashing">挥砍</option><option value="piercing">穿刺</option><option value="bludgeoning">钝击</option><option value="fire">火焰</option><option value="cold">寒冷</option><option value="lightning">闪电</option><option value="poison">毒素</option><option value="acid">强酸</option><option value="necrotic">黯蚀</option><option value="radiant">光耀</option><option value="psychic">心灵</option><option value="force">力场</option><option value="thunder">雷鸣</option>
        </select>
        <Button disabled={previewAction.isPending || Number(amount) < 1} onClick={() => requestPreview("damage")} size="sm">预览伤害</Button>
        <Button disabled={previewAction.isPending || fighter.hp >= effectiveMaxHp || Number(amount) < 1} onClick={() => requestPreview("heal")} size="sm">预览治疗</Button>
        <input aria-label={`${fighter.display_name} 条件`} className="w-20 rounded border border-ink-600 bg-ink-950 px-1.5 py-1 text-xs text-parchment-100" onChange={(event) => setCondition(event.target.value)} placeholder="条件" value={condition} />
        <Button disabled={!condition.trim() || change.isPending} onClick={() => { change.mutate({ conditions: [...fighter.conditions, condition.trim()] }); setCondition(""); }} size="sm">加状态</Button>
        <Button disabled={remove.isPending} onClick={() => remove.mutate()} size="sm" variant="danger">移除</Button>
      </div>
      {pendingAction ? (
        <div className="rounded border border-ember-700/60 bg-ember-950/10 p-2 md:col-span-4">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-auto text-xs text-parchment-100">结算预览（尚未写入）</strong>
            {pendingAction.command.action_type === "damage" ? <Badge tone="warn">{damageModifierLabel(pendingAction.preview.result.modifier)}</Badge> : <Badge tone="ok">治疗</Badge>}
          </div>
          <p className="mb-2 mt-1 text-xs text-stone-300">
            {displayValue(
              pendingAction.preview.result.explanation,
              `恢复 ${displayValue(pendingAction.preview.result.hp_gained)} 点生命`,
            )}
            {" · "}HP {String(pendingAction.preview.before.hp)} → {String(pendingAction.preview.after.hp)}
            {Number(pendingAction.preview.before.temporary_hp ?? 0) > 0 ? ` · 临时生命 ${String(pendingAction.preview.before.temporary_hp)} → ${String(pendingAction.preview.after.temporary_hp)}` : ""}
          </p>
          {pendingAction.preview.concentration_check_dc ? <p className="mb-2 mt-0 text-2xs text-amber-300">确认伤害后需要专注检定 DC {pendingAction.preview.concentration_check_dc}</p> : null}
          <div className="flex gap-2">
            <Button loading={confirmAction.isPending} onClick={() => confirmAction.mutate(pendingAction.command)} size="sm" variant="primary">DM 确认结算</Button>
            <Button disabled={confirmAction.isPending} onClick={() => setPendingAction(null)} size="sm">取消</Button>
          </div>
        </div>
      ) : null}
      <div className="rounded border border-violet-900/60 bg-violet-950/10 p-2 md:col-span-4">
        <div className="flex flex-wrap items-center gap-2">
          <strong className="mr-auto text-xs text-violet-200">结构化效果</strong>
          <input aria-label={`${fighter.display_name} 效果名称`} className="w-28 rounded border border-ink-600 bg-ink-950 px-1.5 py-1 text-xs text-parchment-100" onChange={(event) => setEffectName(event.target.value)} placeholder="例如：目盲" value={effectName} />
          {!effectConcentration ? <input aria-label={`${fighter.display_name} 效果轮数`} className="w-14 rounded border border-ink-600 bg-ink-950 px-1.5 py-1 text-xs text-parchment-100" min="0" onChange={(event) => setEffectRounds(event.target.value)} type="number" value={effectRounds} /> : null}
          <label className="flex items-center gap-1 text-2xs text-stone-400"><input checked={effectConcentration} onChange={(event) => setEffectConcentration(event.target.checked)} type="checkbox" />需要专注</label>
          <Button disabled={!effectName.trim() || addEffect.isPending} loading={addEffect.isPending} onClick={() => addEffect.mutate()} size="sm">DM确认添加</Button>
        </div>
        {effects.length > 0 ? <div className="mt-2 flex flex-wrap gap-1.5">{effects.map((effect) => <span className="inline-flex items-center gap-1 rounded border border-violet-800/60 px-2 py-1 text-2xs text-stone-300" key={effect.id}>{effect.name}{effect.requires_concentration ? " · 专注" : effect.ends_round !== null ? ` · 至第${effect.ends_round}轮` : ""}<Button disabled={endEffect.isPending} onClick={() => endEffect.mutate(effect)} size="sm">结束</Button></span>)}</div> : <p className="mb-0 mt-1 text-2xs text-stone-600">当前没有活动效果。</p>}
      </div>
      {pendingConcentration ? (
        <div className="rounded border border-amber-700/60 bg-amber-950/10 p-2 md:col-span-4">
          <strong className="text-xs text-amber-200">待处理专注检定 DC {pendingConcentration.dc}</strong>
          <p className="mb-2 mt-1 text-2xs text-stone-500">输入最终体质豁免总值；DC 来自已确认伤害日志，不能在此修改。</p>
          <div className="flex gap-2">
            <input aria-label={`${fighter.display_name} 专注检定总值`} className="w-16 rounded border border-ink-600 bg-ink-950 px-1.5 py-1 text-xs text-parchment-100" onChange={(event) => setConcentrationRoll(event.target.value)} type="number" value={concentrationRoll} />
            <Button loading={resolveConcentration.isPending} onClick={() => resolveConcentration.mutate()} size="sm" variant="primary">DM确认检定</Button>
          </div>
        </div>
      ) : null}
      {fighter.entity_type === "character" && fighter.hp === 0 ? (
        <div className="rounded border border-red-800/60 bg-red-950/15 p-2 md:col-span-4">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-auto text-xs text-red-200">死亡豁免</strong>
            {deathSave.data ? <Badge tone={deathSave.data.dead ? "danger" : deathSave.data.stable ? "ok" : "warn"}>{deathSaveSummary(deathSave.data)}</Badge> : null}
          </div>
          <p className="mb-2 mt-1 text-2xs text-stone-500">自然 1 计两次失败；自然 20 恢复 1 HP；三次失败后仍需 DM 最终确认死亡。</p>
          <div className="flex flex-wrap items-center gap-2">
            <input aria-label={`${fighter.display_name} 死亡豁免骰`} className="w-16 rounded border border-ink-600 bg-ink-950 px-1.5 py-1 text-xs text-parchment-100" max="20" min="1" onChange={(event) => setDeathRoll(event.target.value)} type="number" value={deathRoll} />
            <Button disabled={deathSave.data?.stable || deathSave.data?.dead || deathSave.data?.pending_death_confirmation || rollDeathSave.isPending} onClick={() => rollDeathSave.mutate()} size="sm" variant="primary">DM 确认骰值</Button>
            {deathSave.data?.pending_death_confirmation ? <Button loading={confirmDeath.isPending} onClick={() => confirmDeath.mutate()} size="sm" variant="danger">最终确认死亡</Button> : null}
          </div>
        </div>
      ) : null}
      {character ? (
        <div className="border-t border-ink-700/70 pt-2 md:col-span-4">
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(character.resources).map(([key, raw]) => {
              const resource = raw as { label?: string; current?: number; max?: number };
              return <Button disabled={Number(resource.current ?? 0) <= 0 || spendResource.isPending} key={key} onClick={() => spendResource.mutate(key)} size="sm">{resource.label ?? key} {resource.current ?? 0}/{resource.max ?? 0} · 消耗1</Button>;
            })}
          </div>
          {character.actions.length > 0 ? <div className="mt-2 grid gap-1 sm:grid-cols-2">{character.actions.map((raw, index) => { const action = raw as { name?: string; damage?: string; range?: string; cost?: string; description?: string }; return <div className="rounded border border-ink-700 bg-ink-950/60 px-2 py-1.5 text-2xs text-stone-400" key={`${action.name ?? "动作"}-${index}`}><strong className="text-parchment-100">{action.name ?? "动作"}</strong>{action.damage ? ` · ${action.damage}` : ""}{action.range ? ` · ${action.range}` : ""}<br />{action.cost ?? "动作"} · {action.description ?? ""}</div>; })}</div> : null}
        </div>
      ) : null}
    </li>
  );
}

function BattleGrid({
  campaignId,
  combatId,
  fighters,
  grid,
  candidates,
  activeFighterId,
  automateEnemies,
  turnKey,
  targeting,
  endingTurn,
  onEndTurn,
  onAutomationMovementChange,
  onTargetSelect,
  onTargetValidityChange,
}: {
  campaignId: string;
  combatId: string;
  fighters: Combatant[];
  grid: SceneGrid | null;
  candidates: CombatCandidate[];
  activeFighterId: string | null;
  automateEnemies: boolean;
  turnKey: string;
  targeting: CombatTargeting | null;
  endingTurn: boolean;
  onEndTurn: () => void;
  onAutomationMovementChange: (moving: boolean) => void;
  onTargetSelect: (fighterId: string) => void;
  onTargetValidityChange: (fighterIds: ReadonlySet<string>) => void;
}): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const tacticalGrid = useMemo(
    () => grid ?? generateTacticalSceneGrid("临时战场", "通用战斗区域"),
    [grid],
  );
  const width = tacticalGrid.width;
  const height = tacticalGrid.height;
  const [positions, setPositions] = useState<Record<string, [number, number]>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [lastAiMove, setLastAiMove] = useState("");
  const [targetingMessage, setTargetingMessage] = useState("");
  const [aimPoint, setAimPoint] = useState<GridPoint | null>(null);
  const [interactionMode, setInteractionMode] = useState<"move" | "target">("move");
  const [movingFighterId, setMovingFighterId] = useState<string | null>(null);
  const processedAiTurn = useRef<string | null>(null);
  useEffect(() => {
    setPositions((current) => {
      const next = { ...current };
      const playerSpawns = findSceneSpawnCells(tacticalGrid, "player");
      const enemySpawns = findSceneSpawnCells(tacticalGrid, "enemy");
      fighters.forEach((fighter, index) => {
        if (next[fighter.id]) return;
        const stored = fighter.snapshot_json.grid_position as { row?: unknown; col?: unknown } | undefined;
        if (
          stored
          && Number.isInteger(stored.row)
          && Number.isInteger(stored.col)
          && Number(stored.row) >= 1
          && Number(stored.row) <= height
          && Number(stored.col) >= 1
          && Number(stored.col) <= width
          && !isBlockedCell(tacticalGrid, { row: Number(stored.row), col: Number(stored.col) })
          && !Object.values(next).some(([placedRow, placedCol]) => (
            placedRow === Number(stored.row) && placedCol === Number(stored.col)
          ))
        ) {
          next[fighter.id] = [Number(stored.row), Number(stored.col)];
          return;
        }
        const preferred = fighter.entity_type === "character"
          ? playerSpawns[index % Math.max(1, playerSpawns.length)]
          : enemySpawns[index % Math.max(1, enemySpawns.length)];
        const fallback = fighter.entity_type === "character"
          ? { row: height - 2, col: 2 + index }
          : { row: 2, col: width - 2 - index };
        const origin = preferred ?? fallback;
        const free = Array.from({ length: height }, (_, row) => (
          Array.from({ length: width }, (_, col) => ({ row: row + 1, col: col + 1 }))
        )).flat().filter((point) => (
          !isBlockedCell(tacticalGrid, point)
          && !Object.values(next).some(([placedRow, placedCol]) => (
            placedRow === point.row && placedCol === point.col
          ))
        )).sort((a, b) => (
          gridDistanceFt(origin, a) - gridDistanceFt(origin, b)
        ))[0];
        if (free) next[fighter.id] = [free.row, free.col];
      });
      return next;
    });
  }, [fighters, height, tacticalGrid, width]);
  useEffect(() => {
    if (activeFighterId) setSelected(activeFighterId);
  }, [activeFighterId]);
  useEffect(() => {
    setAimPoint(null);
    setInteractionMode(targeting ? "target" : "move");
    setTargetingMessage(targeting
      ? `先在地图上选择${targeting.shape === "circle" ? "爆发中心" : "目标或方向"}；浅蓝色是施法距离，紫色是实际影响范围。`
      : "");
  }, [targeting]);
  const commitMove = useCallback(async (
    fighter: Combatant,
    plan: MovementPlan,
    automatic: boolean,
    exhaustMovement = false,
  ) => {
    if ((plan.spentFt <= 0 && !exhaustMovement) || movingFighterId) return;
    setMovingFighterId(fighter.id);
    if (automatic) onAutomationMovementChange(true);
    const remainingMovement = exhaustMovement
      ? 0
      : Math.max(0, fighter.movement_remaining_ft - plan.spentFt);
    try {
      await updateCombatant(
        campaignId,
        combatId,
        fighter.id,
        {
          movement_remaining_ft: remainingMovement,
          snapshot_json: {
            ...fighter.snapshot_json,
            grid_position: plan.destination,
          },
        },
        fighter.version,
      );
      setPositions((current) => ({
        ...current,
        [fighter.id]: [plan.destination.row, plan.destination.col],
      }));
      await client.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      if (!automatic) showToast(`${fighter.display_name}移动 ${plan.spentFt} 尺，剩余 ${remainingMovement} 尺`);
    } catch {
      if (automatic) processedAiTurn.current = null;
      showToast(`${fighter.display_name}移动保存失败，请刷新战斗状态`, "error");
    } finally {
      setMovingFighterId(null);
      if (automatic) onAutomationMovementChange(false);
    }
  }, [
    campaignId,
    client,
    combatId,
    movingFighterId,
    onAutomationMovementChange,
    showToast,
  ]);
  useEffect(() => {
    if (!automateEnemies) return;
    if (!activeFighterId) return;
    if (processedAiTurn.current === turnKey || movingFighterId) return;
    const active = fighters.find((fighter) => fighter.id === activeFighterId);
    if (!active || active.entity_type === "character" || active.hp <= 0) return;
    const from = positions[active.id];
    const target = fighters
      .filter((fighter) => fighter.entity_type === "character" && fighter.hp > 0)
      .map((fighter) => ({ fighter, position: positions[fighter.id] }))
      .filter((item): item is { fighter: Combatant; position: [number, number] } => Boolean(item.position))
      .sort((a, b) => {
        if (!from) return 0;
        return gridDistanceFt(
          { row: from[0], col: from[1] },
          { row: a.position[0], col: a.position[1] },
          tacticalGrid.cell_size_ft,
        ) - gridDistanceFt(
          { row: from[0], col: from[1] },
          { row: b.position[0], col: b.position[1] },
          tacticalGrid.cell_size_ft,
        );
      })[0];
    if (!from || !target) return;
    processedAiTurn.current = turnKey;
    const occupied = new Set(Object.entries(positions)
      .filter(([id]) => id !== active.id)
      .map(([, position]) => `${position[0]}:${position[1]}`));
    const plan = planApproachPath(
      tacticalGrid,
      { row: from[0], col: from[1] },
      { row: target.position[0], col: target.position[1] },
      occupied,
      active.movement_remaining_ft,
      targeting?.rangeFt ?? 5,
    );
    if (plan.spentFt <= 0) {
      const alreadyInRange = gridDistanceFt(
        { row: from[0], col: from[1] },
        { row: target.position[0], col: target.position[1] },
        tacticalGrid.cell_size_ft,
      ) <= (targeting?.rangeFt ?? 5);
      setLastAiMove(alreadyInRange
        ? `${active.display_name}已在${target.fighter.display_name}的攻击范围内，保留剩余移动 ${active.movement_remaining_ft} 尺。`
        : `${active.display_name}本回合没有足够移动力到达合法攻击范围。`);
      if (!alreadyInRange && active.movement_remaining_ft > 0) {
        void commitMove(active, plan, true, true);
      }
      return;
    }
    setLastAiMove(`${active.display_name}按规则向${target.fighter.display_name}寻路移动 ${plan.spentFt} 尺；剩余 ${Math.max(0, active.movement_remaining_ft - plan.spentFt)} 尺。`);
    void commitMove(active, plan, true);
  }, [activeFighterId, automateEnemies, commitMove, fighters, movingFighterId, positions, tacticalGrid, targeting?.rangeFt, turnKey]);
  const selectedPosition = selected ? positions[selected] : null;
  const selectedFighter = fighters.find((fighter) => fighter.id === selected);
  const selectedSpeed = selectedFighter?.speed_ft
    ?? candidates.find((candidate) => candidate.entityId === selectedFighter?.entity_id)?.speed
    ?? 30;
  const selectedRemaining = selectedFighter?.movement_remaining_ft ?? 0;
  const distance = (row: number, col: number) => selectedPosition
    ? gridDistanceFt(
        { row: selectedPosition[0], col: selectedPosition[1] },
        { row, col },
        tacticalGrid.cell_size_ft,
      )
    : null;
  const activePositionTuple = activeFighterId ? positions[activeFighterId] : null;
  const activePosition = useMemo(
    () => activePositionTuple
      ? { row: activePositionTuple[0], col: activePositionTuple[1] }
      : null,
    [activePositionTuple],
  );
  useEffect(() => {
    if (!automateEnemies || !targeting || !activePosition || !activeFighterId) return;
    const active = fighters.find((fighter) => fighter.id === activeFighterId);
    if (!active || active.entity_type === "character") return;
    const target = fighters
      .filter((fighter) => fighter.entity_type === "character" && fighter.hp > 0)
      .map((fighter) => positions[fighter.id])
      .find((position): position is [number, number] => Boolean(position));
    if (!target) return;
    setAimPoint((current) => (
      current?.row === target[0] && current.col === target[1]
        ? current
        : { row: target[0], col: target[1] }
    ));
    setInteractionMode("target");
    setTargetingMessage(
      `${active.display_name} 正在自动瞄准；紫色区域是「${targeting.label}」的实际影响范围。`,
    );
  }, [
    activeFighterId,
    activePosition,
    automateEnemies,
    fighters,
    positions,
    targeting,
    turnKey,
  ]);
  const areaCells = useMemo(
    () => targeting && activePosition && aimPoint
      ? getTargetingCells(tacticalGrid, activePosition, aimPoint, targeting)
      : [],
    [activePosition, aimPoint, tacticalGrid, targeting],
  );
  const areaKeys = useMemo(
    () => new Set(areaCells.map((cell) => `${cell.row}:${cell.col}`)),
    [areaCells],
  );
  useEffect(() => {
    if (!targeting || !activePosition) {
      onTargetValidityChange(new Set());
      return;
    }
    const valid = new Set(fighters.filter((fighter) => {
      if (fighter.id === activeFighterId || fighter.hp <= 0) return false;
      const position = positions[fighter.id];
      if (!position) return false;
      if (targeting.shape === "single") {
        return isAimPointInRange(
          activePosition,
          { row: position[0], col: position[1] },
          targeting.rangeFt,
          tacticalGrid.cell_size_ft,
        );
      }
      return areaKeys.has(`${position[0]}:${position[1]}`);
    }).map((fighter) => fighter.id));
    onTargetValidityChange(valid);
  }, [
    activeFighterId,
    activePosition,
    areaKeys,
    fighters,
    onTargetValidityChange,
    positions,
    tacticalGrid.cell_size_ft,
    targeting,
  ]);
  const tokenAt = (row: number, col: number) => fighters.find((fighter) => {
    const position = positions[fighter.id];
    return position?.[0] === row && position[1] === col;
  });
  return (
    <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/50 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-parchment-100">战斗场景 · {tacticalGrid.theme}</span>
        <span className="text-2xs text-stone-500">每格 5 尺 · 地图直接来自当前场景 · 单位按双方出生区布置</span>
        {interactionMode === "move" && selected === activeFighterId ? (
          <Badge tone="ok">绿色范围：本回合剩余可移动区域</Badge>
        ) : null}
        {targeting ? <Badge tone="ai">施法指示：{targeting.label}</Badge> : null}
        <div className="flex rounded border border-ink-700 p-0.5">
          <button className={`rounded px-2 py-1 text-2xs ${interactionMode === "move" ? "bg-ember-700 text-white" : "text-stone-500"}`} onClick={() => setInteractionMode("move")} type="button">移动</button>
          <button className={`rounded px-2 py-1 text-2xs ${interactionMode === "target" ? "bg-sky-700 text-white" : "text-stone-500"}`} disabled={!targeting} onClick={() => setInteractionMode("target")} type="button">技能范围</button>
        </div>
        <Button disabled={endingTurn || !activeFighterId} loading={endingTurn} onClick={onEndTurn} size="sm" variant="primary">结束回合</Button>
        {selected ? <span className="ml-auto text-2xs text-ember-300">已选：{fighters.find((fighter) => fighter.id === selected)?.display_name}</span> : null}
      </div>
      {lastAiMove ? <p className="mb-2 mt-0 rounded border border-red-900/50 bg-red-950/10 px-2 py-1 text-2xs text-red-200">{lastAiMove}</p> : null}
      {targetingMessage ? <p className="mb-2 mt-0 rounded border border-sky-800/50 bg-sky-950/15 px-2 py-1 text-2xs text-sky-200">{targetingMessage}</p> : null}
      <div className="grid w-full gap-px overflow-hidden rounded border border-ink-700 bg-ink-700" style={{ gridTemplateColumns: `repeat(${width}, minmax(0, 1fr))` }}>
        {Array.from({ length: height }, (_, row) => Array.from({ length: width }, (_, col) => {
          const rowNumber = row + 1;
          const colNumber = col + 1;
          const fighter = tokenAt(rowNumber, colNumber);
          const point = { row: rowNumber, col: colNumber };
          const sceneCell = tacticalGrid.cells.find((cell) => cell.row === rowNumber && cell.col === colNumber);
          const blocked = isBlockedCell(tacticalGrid, point);
          const moveDistance = distance(rowNumber, colNumber);
          const occupied = new Set(Object.entries(positions)
            .filter(([id]) => id !== selected)
            .map(([, position]) => `${position[0]}:${position[1]}`));
          const manualPlan = selectedPosition
            ? shortestMovementPath(
                tacticalGrid,
                { row: selectedPosition[0], col: selectedPosition[1] },
                point,
                occupied,
                selectedRemaining,
              )
            : null;
          const canMove = Boolean(
            selected
            && selected === activeFighterId
            && !fighter
            && !blocked
            && manualPlan
            && !movingFighterId
          );
          const inCastRange = Boolean(targeting && activePosition && isAimPointInRange(
            activePosition,
            point,
            targeting.rangeFt,
            tacticalGrid.cell_size_ft,
          ));
          const affected = areaKeys.has(`${rowNumber}:${colNumber}`);
          const terrainClass = sceneCell?.kind === "wall" ? "bg-stone-700" : sceneCell?.kind === "cover" ? "bg-emerald-900/80" : sceneCell?.kind === "door" ? "bg-amber-800/80" : sceneCell?.kind === "object" ? "bg-violet-900/80" : "bg-ink-950/80";
          const glyph = !sceneCell ? "" : sceneCell.kind === "wall" ? "■" : sceneCell.kind === "door" ? "门" : /吧台/.test(sceneCell.label) ? "吧" : /桌/.test(sceneCell.label) ? "桌" : /椅/.test(sceneCell.label) ? "椅" : sceneCell.kind === "cover" ? "▦" : sceneCell.kind === "floor" ? "" : "◆";
          return (
            <button
              className={`relative aspect-square min-h-7 text-2xs transition-colors ${terrainClass} ${inCastRange && !blocked && interactionMode === "target" ? "ring-1 ring-inset ring-sky-500/50" : ""} ${affected && !blocked && interactionMode === "target" ? "bg-fuchsia-800/45 ring-2 ring-inset ring-fuchsia-400" : ""} ${aimPoint?.row === rowNumber && aimPoint.col === colNumber ? "outline outline-2 outline-amber-300" : ""} ${canMove && interactionMode === "move" ? "bg-emerald-950/65 ring-1 ring-inset ring-emerald-400/80 hover:bg-emerald-700/55" : ""}`}
              key={`${rowNumber}-${colNumber}`}
              onClick={() => {
                if (interactionMode === "target" && targeting && activePosition && activeFighterId) {
                  if (!inCastRange || blocked) {
                    setTargetingMessage(`该格不在「${targeting.label}」的施法距离内，不能作为目标点。`);
                    return;
                  }
                  setAimPoint(point);
                  const affectedNow = getTargetingCells(tacticalGrid, activePosition, point, targeting);
                  if (fighter && fighter.id !== activeFighterId) {
                    if (affectedNow.some((cell) => cell.row === rowNumber && cell.col === colNumber)) {
                      onTargetSelect(fighter.id);
                      setTargetingMessage(`${fighter.display_name}位于合法范围内，已选为目标。`);
                    } else {
                      setTargetingMessage(`${fighter.display_name}不在当前技能的实际影响范围内。`);
                    }
                  } else {
                    setTargetingMessage(`已选择范围中心（${rowNumber}, ${colNumber}）；紫色区域内的单位会受到影响。`);
                  }
                  return;
                }
                if (fighter) {
                  if (fighter.id === activeFighterId) setSelected(fighter.id);
                  else setTargetingMessage("只能移动当前回合单位；要选择攻击目标，请切换到“技能范围”。");
                } else if (canMove && selectedFighter && manualPlan) {
                  void commitMove(selectedFighter, manualPlan, false);
                }
              }}
              title={canMove && manualPlan
                ? `可移动到这里 · 消耗 ${manualPlan.spentFt} 尺（${manualPlan.path.length} 格）`
                : sceneCell?.label ?? (moveDistance === null ? "选择一个单位" : `${moveDistance} 尺`)}
              type="button"
            >
              {fighter ? <span className={`mx-auto flex h-6 w-6 items-center justify-center rounded-full text-2xs font-bold ${selected === fighter.id ? "bg-ember-400 text-ink-950" : "bg-violet-500/80 text-white"}`}>{fighter.display_name.slice(0, 1)}</span> : null}
              {!fighter && glyph ? <span className="text-stone-200">{glyph}</span> : null}
            </button>
          );
        }))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-stone-500">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-violet-500/80" />单位</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-emerald-900" />掩体</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-stone-700" />墙体</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded border border-emerald-400 bg-emerald-900" />本回合可移动范围</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded border border-sky-400" />施法距离</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-fuchsia-700 ring-1 ring-fuchsia-400" />实际影响范围</span>
        <span>速度上限：{selected ? `${selectedSpeed}尺` : "—"} · 本回合剩余：{selected ? `${selectedRemaining}尺（${Math.floor(selectedRemaining / tacticalGrid.cell_size_ft)}格）` : "选择当前单位后显示"}；每次移动后会从新位置重新计算绿色范围</span>
      </div>
    </div>
  );
}

function CombatCard({ campaignId, combat, candidates, encounterConsequences, grid, sceneName, sceneAdjustments }: { campaignId: string; combat: Combat; candidates: CombatCandidate[]; encounterConsequences: EncounterAdjustment[]; grid: SceneGrid | null; sceneName: string | null; sceneAdjustments: { shift: number; reason: string }[] }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [name, setName] = useState("");
  const [initiative, setInitiative] = useState("10");
  const [armorClass, setArmorClass] = useState("10");
  const [hp, setHp] = useState("10");
  const [selectedKey, setSelectedKey] = useState("");
  const autoEnemiesStorageKey = `dnd-dm-auto-enemies:${campaignId}:${combat.id}`;
  const [autoEnemies, setAutoEnemies] = useState(
    () => localStorage.getItem(autoEnemiesStorageKey) !== "false",
  );
  const [xpOverride, setXpOverride] = useState("");
  const [goldPerCharacter, setGoldPerCharacter] = useState("0");
  const [lootRecipientId, setLootRecipientId] = useState("");
  const [lootName, setLootName] = useState("");
  const [lootQuantity, setLootQuantity] = useState("1");
  const [lootWeight, setLootWeight] = useState("0");
  const [lootPriceGp, setLootPriceGp] = useState("0");
  const [targetingRange, setTargetingRange] = useState<CombatTargeting | null>(null);
  const [selectedMapTargetId, setSelectedMapTargetId] = useState("");
  const [targetableFighterIds, setTargetableFighterIds] = useState<ReadonlySet<string>>(new Set());
  const [automaticMovementPending, setAutomaticMovementPending] = useState(false);
  const [expandedFighterId, setExpandedFighterId] = useState<string | null>(null);
  const [resetConfirmation, setResetConfirmation] = useState(false);
  const [archiveConfirmation, setArchiveConfirmation] = useState(false);
  const [resetGeneration, setResetGeneration] = useState(0);
  const updateTargetableFighterIds = useCallback((next: ReadonlySet<string>) => {
    setTargetableFighterIds((current) => {
      const currentKey = [...current].sort().join("|");
      const nextKey = [...next].sort().join("|");
      return currentKey === nextKey ? current : next;
    });
  }, []);
  const [settlementPreview, setSettlementPreview] = useState<{
    preview: CombatSettlementPreview;
    command: CombatSettlementCommand;
  } | null>(null);
  useEffect(() => {
    localStorage.setItem(autoEnemiesStorageKey, String(autoEnemies));
  }, [autoEnemies, autoEnemiesStorageKey]);
  const fighters = useQuery({
    queryKey: ["combatants", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatants(campaignId, combat.id, signal),
    refetchInterval: combat.status === "active" ? 1_000 : false,
  });
  const combatActions = useQuery({
    queryKey: ["combat-actions", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatActions(campaignId, combat.id, signal),
    refetchInterval: combat.status === "active" ? 1_000 : false,
  });
  const combatEffects = useQuery({
    queryKey: ["combat-effects", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatEffects(campaignId, combat.id, signal),
    refetchInterval: combat.status === "active" ? 1_000 : false,
  });
  const endCondition = useQuery({
    queryKey: ["combat-end-condition", campaignId, combat.id],
    queryFn: ({ signal }) => getCombatEndCondition(campaignId, combat.id, signal),
    enabled: combat.status === "active",
    refetchInterval: combat.status === "active" ? 1_000 : false,
  });
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["combats", campaignId] });
    void client.invalidateQueries({ queryKey: ["combatants", campaignId, combat.id] });
    void client.invalidateQueries({ queryKey: ["combat-end-condition", campaignId, combat.id] });
    void client.invalidateQueries({ queryKey: ["campaign-state", campaignId] });
  };
  const selectedCandidate = candidates.find((candidate) => candidate.key === selectedKey);
  const selectCandidate = (key: string) => {
    setSelectedKey(key);
    const candidate = candidates.find((item) => item.key === key);
    if (!candidate) return;
    setName(candidate.name);
    setArmorClass(String(candidate.armorClass));
    setHp(String(candidate.hp || candidate.maxHp));
    const dexterityModifier = Math.floor((candidate.dexterity - 10) / 2);
    setInitiative(String(Math.floor(Math.random() * 20) + 1 + dexterityModifier));
  };
  const add = useMutation({
    mutationFn: () => createCombatant(campaignId, combat.id, {
      display_name: name.trim(), entity_type: selectedCandidate?.entityType ?? "custom",
      entity_id: selectedCandidate?.entityId ?? null,
      initiative: Number(initiative), armor_class: Number(armorClass),
      hp: Number(hp), max_hp: Number(hp),
      speed_ft: selectedCandidate?.speed ?? 30,
      movement_remaining_ft: selectedCandidate?.speed ?? 30,
      snapshot_json: selectedCandidate ? {
        source_name: selectedCandidate.name,
        source_type: selectedCandidate.entityType,
        source_speed: selectedCandidate.speed,
        actions: selectedCandidate.actions,
        ability_scores: selectedCandidate.abilityScores,
      } : {},
      is_active: true,
    }),
    onSuccess: () => { setName(""); invalidate(); showToast("参与者已加入战斗"); },
    onError: () => showToast("添加参与者失败", "error"),
  });
  const update = useMutation({
    mutationFn: (payload: { status?: string; round_number?: number; current_turn_index?: number; difficulty?: Difficulty; base_xp?: number; difficulty_adjustments?: unknown[] }) =>
      updateCombat(campaignId, combat.id, payload, combat.version),
    onSuccess: () => { setArchiveConfirmation(false); invalidate(); showToast("战斗进度已保存"); },
    onError: () => showToast("战斗进度保存失败", "error"),
  });
  const resetCurrentCombat = useMutation({
    mutationFn: () => resetCombat(campaignId, combat.id, combat.version),
    onSuccess: () => {
      setResetConfirmation(false);
      setAutoEnemies(false);
      setResetGeneration((value) => value + 1);
      setSelectedMapTargetId("");
      setTargetableFighterIds(new Set());
      setTargetingRange(null);
      void client.invalidateQueries({ queryKey: ["combats", campaignId] });
      void client.invalidateQueries({ queryKey: ["combatants", campaignId, combat.id] });
      void client.invalidateQueries({ queryKey: ["combat-actions", campaignId, combat.id] });
      void client.invalidateQueries({ queryKey: ["combat-effects", campaignId, combat.id] });
      void client.invalidateQueries({ queryKey: ["combat-end-condition", campaignId, combat.id] });
      showToast("当前战斗已重置：回到第1轮第一位，战斗状态与日志已清空");
    },
    onError: (error) => {
      setResetConfirmation(false);
      showToast(error instanceof Error ? error.message : "当前战斗重置失败", "error");
    },
  });
  const nextTurn = useMutation({
    mutationFn: () => advanceCombatTurn(campaignId, combat.id, combat.version),
    onSuccess: (result) => {
      invalidate();
      showToast(result.expiration_prompts.length > 0
        ? `回合已结束；有 ${result.expiration_prompts.length} 个效果等待 DM 确认结束`
        : result.active_combatant
          ? `第 ${result.combat.round_number} 轮：轮到 ${result.active_combatant.display_name}`
          : "回合已结束");
    },
    onError: () => showToast("回合推进失败，请刷新战斗状态", "error"),
  });
  const ordered = [...(fighters.data ?? [])].filter((fighter) => fighter.is_active).sort((a, b) => b.initiative - a.initiative || a.display_name.localeCompare(b.display_name));
  const activeFighter = combat.status === "active"
    ? ordered[combat.current_turn_index] ?? ordered[0]
    : undefined;
  const activeFighterIdForCard = activeFighter?.id;
  useEffect(() => {
    if (activeFighterIdForCard) setExpandedFighterId(activeFighterIdForCard);
  }, [activeFighterIdForCard]);
  const activeCharacter = activeFighter?.entity_type === "character" && activeFighter.entity_id
    ? candidates.find((candidate) => candidate.entityType === "character" && candidate.entityId === activeFighter.entity_id)?.character
    : undefined;
  const monstersInCombat = ordered.filter((fighter) => fighter.entity_type === "monster");
  const allMonstersDefeated = endCondition.data?.can_end ?? (
    monstersInCombat.length > 0
    && monstersInCombat.every((fighter) => fighter.hp <= 0 || fighter.conditions.includes("死亡") || fighter.conditions.includes("投降") || fighter.conditions.includes("逃跑"))
  );
  const playerCharacters = ordered
    .filter((fighter) => fighter.entity_type === "character" && fighter.entity_id)
    .map((fighter) => candidates.find((candidate) => candidate.entityType === "character" && candidate.entityId === fighter.entity_id)?.character)
    .filter((character): character is Character => Boolean(character));
  useEffect(() => {
    if (!lootRecipientId && playerCharacters[0]) setLootRecipientId(playerCharacters[0].id);
  }, [lootRecipientId, playerCharacters]);
  const monsterXp = ordered
    .filter((fighter) => fighter.entity_type === "monster")
    .reduce((sum, fighter) => {
      const candidate = candidates.find((item) => item.entityType === "monster" && item.entityId === fighter.entity_id);
      return sum + xpForChallengeRating(candidate?.challengeRating);
    }, 0);
  const baseDifficulty = encounterDifficulty(playerCharacters.map((character) => character.level), monsterXp);
  const sceneShift = sceneAdjustments.reduce((sum, adjustment) => sum + adjustment.shift, 0)
    + encounterConsequences.reduce((sum, proposal) => sum + proposal.difficulty_shift, 0);
  const manualShift = combat.difficulty_adjustments.reduce<number>((sum, raw) => {
    const adjustment = raw as { shift?: number };
    return sum + Number(adjustment.shift ?? 0);
  }, 0);
  const finalDifficulty = shiftDifficulty(baseDifficulty, sceneShift + manualShift);
  const distributableXp = Math.max(0, Number(xpOverride || combat.base_xp || monsterXp));
  const xpPerCharacter = playerCharacters.length > 0 ? Math.floor(distributableXp / playerCharacters.length) : 0;
  const manualAdjustment = useMutation({
    mutationFn: (shift: -1 | 1) => updateCombat(campaignId, combat.id, {
      difficulty: shiftDifficulty(finalDifficulty, shift),
      base_xp: combat.base_xp || monsterXp,
      difficulty_adjustments: [...combat.difficulty_adjustments, {
        shift,
        reason: shift < 0 ? "DM手动降低一级" : "DM手动提高一级",
        created_at: new Date().toISOString(),
      }],
    }, combat.version),
    onSuccess: () => { invalidate(); showToast("DM难度修正已保存"); },
    onError: () => showToast("难度修正保存失败，请刷新后重试", "error"),
  });
  const buildSettlementCommand = (): CombatSettlementCommand => ({
    combat_version: combat.version,
    resolution_type: "victory",
    xp_awards: playerCharacters.map((character) => ({
      character_id: character.id,
      xp: xpPerCharacter,
    })),
    currency_awards: playerCharacters.map((character) => ({
      character_id: character.id,
      copper: Math.max(0, Math.round(Number(goldPerCharacter || 0) * 100)),
    })),
    loot_awards: lootName.trim() && lootRecipientId
      ? [{
          character_id: lootRecipientId,
          name: lootName.trim(),
          description: `战斗“${combat.name}”结算战利品`,
          category: "loot",
          quantity: Math.max(1, Number(lootQuantity)),
          unit_weight_lb: Math.max(0, Number(lootWeight)),
          price_cp: Math.max(0, Math.round(Number(lootPriceGp || 0) * 100)),
          source_label: "custom",
          metadata_json: { combat_id: combat.id, dm_confirmed: true },
        }]
      : [],
    writebacks: ordered.flatMap((fighter) => (
      fighter.entity_type === "character" && fighter.entity_id
        ? [{
            combatant_id: fighter.id,
            character_id: fighter.entity_id,
            write_hp: true,
            write_conditions: true,
          }]
        : []
    )),
    notes: "DM在战斗辅助页确认结算",
  });
  const previewSettlement = useMutation({
    mutationFn: () => {
      if (combat.xp_awarded) throw new Error("该战斗已经发放经验");
      if (playerCharacters.length === 0) throw new Error("没有可结算的参与玩家");
      const command = buildSettlementCommand();
      return previewCombatSettlement(campaignId, combat.id, command)
        .then((preview) => ({ preview, command }));
    },
    onSuccess: (value) => setSettlementPreview(value),
    onError: (error) => showToast(error instanceof Error ? error.message : "结算预览失败", "error"),
  });
  const confirmSettlement = useMutation({
    mutationFn: () => {
      if (!settlementPreview) throw new Error("请先生成结算预览");
      return confirmCombatSettlement(
        campaignId,
        combat.id,
        settlementPreview.command,
      );
    },
    onSuccess: async () => {
      setSettlementPreview(null);
      invalidate();
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      void client.invalidateQueries({ queryKey: ["inventory", campaignId] });
      void client.invalidateQueries({ queryKey: ["world-items", campaignId] });
      if (combat.scene_id) {
        await createEvent(campaignId, {
          title: `战斗结算：${combat.name}`,
          event_type: "session_progress",
          description: `战斗结束；每名玩家获得 ${xpPerCharacter} XP、${goldPerCharacter || "0"} GP${lootName.trim() ? `；${lootName.trim()}已加入角色背包` : ""}。`,
          visibility: "dm",
          metadata_json: {
            scene_id: combat.scene_id,
            combat_id: combat.id,
            game_table: true,
            entry_kind: "system",
          },
        });
      }
      showToast("战斗奖励已确认，经验、金币和战利品已写入角色并返回推进台");
      navigate("/game-table");
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "战斗结算失败", "error"),
  });
  const revertConsequence = useMutation({
    mutationFn: (proposal: EncounterAdjustment) =>
      revertEncounterAdjustment(campaignId, proposal.id, proposal.version),
    onSuccess: () => {
      invalidate();
      void client.invalidateQueries({ queryKey: ["encounter-adjustments", campaignId] });
      showToast("情景后果已撤销，战斗员状态已恢复");
    },
    onError: () => showToast("无法撤销；战斗可能已经结算或状态已被后续操作改变", "error"),
  });
  return (
    <Panel eyebrow={`第 ${combat.round_number} 轮 · 回合 ${combat.current_turn_index + 1}`} title={combat.name}>
      <p className="mb-3 mt-0 text-2xs text-stone-500">战斗场景：{sceneName ?? "未绑定场景"}{grid ? ` · 已加载 ${grid.theme} 网格` : " · 使用临时通用网格"}</p>
      <div className="mb-3 grid gap-2 rounded-lg border border-ink-700 bg-ink-950/50 p-3 md:grid-cols-[1fr_auto]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <strong className="text-sm text-parchment-100">遭遇难度：{DIFFICULTY_LABELS[finalDifficulty]}</strong>
            <Badge tone={finalDifficulty === "high" ? "danger" : finalDifficulty === "moderate" ? "warn" : finalDifficulty === "low" || finalDifficulty === "trivial" ? "ok" : "neutral"}>{finalDifficulty}</Badge>
          </div>
          <p className="mb-0 mt-1 text-2xs text-stone-500">队伍：{playerCharacters.length ? playerCharacters.map((character) => `${character.name} Lv${character.level}`).join("、") : "尚无玩家"} · 怪物基础 XP：{monsterXp} · 基础判定：{DIFFICULTY_LABELS[baseDifficulty]}</p>
          {sceneAdjustments.length > 0 ? <ul className="mb-0 mt-2 pl-4 text-2xs text-emerald-300">{sceneAdjustments.map((item, index) => <li key={`${item.reason}-${index}`}>{item.shift < 0 ? "降低" : "提高"}一级：{item.reason}</li>)}</ul> : <p className="mb-0 mt-1 text-2xs text-stone-600">推进台没有记录玩家准备或敌方优势修正。</p>}
          {encounterConsequences.length > 0 ? (
            <div className="mt-2 space-y-2">
              {encounterConsequences.map((proposal) => <div className="rounded border border-emerald-900/60 bg-emerald-950/10 p-2" key={proposal.id}><div className="flex flex-wrap items-center gap-2"><strong className="mr-auto text-xs text-emerald-200">{proposal.title}</strong><Badge tone="ok">{difficultyShiftLabel(proposal.difficulty_shift)}</Badge><Button disabled={combat.xp_awarded || revertConsequence.isPending} onClick={() => revertConsequence.mutate(proposal)} size="sm">撤销</Button></div><p className="mb-1 mt-1 text-2xs text-stone-500">{proposal.reason}</p><ul className="m-0 pl-4 text-2xs text-stone-300">{proposal.operations_json.map((operation, index) => { const candidate = candidates.find((item) => item.entityType === operation.entity_type && item.entityId === operation.entity_id); return <li key={`${operation.kind}-${operation.entity_id}-${index}`}>{describeEncounterOperation(operation, candidate?.name)}</li>; })}</ul></div>)}
            </div>
          ) : null}
          <p className="mb-0 mt-1 text-2xs text-stone-600">难度估算综合角色等级、怪物 CR/XP 与情景修正；行动经济、地形和资源消耗仍由 DM 最终判断。</p>
        </div>
        <div className="flex gap-1.5 md:flex-col">
          <Button disabled={combat.status === "archived" || manualAdjustment.isPending} onClick={() => manualAdjustment.mutate(-1)} size="sm">DM 降一级</Button>
          <Button disabled={combat.status === "archived" || manualAdjustment.isPending} onClick={() => manualAdjustment.mutate(1)} size="sm">DM 升一级</Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Badge tone={combat.status === "active" ? "danger" : "neutral"}>{COMBAT_STATUS_LABELS[combat.status] ?? combat.status}</Badge>
        <div className="flex flex-wrap gap-2">
          <Button disabled={combat.status !== "active"} onClick={() => setAutoEnemies((value) => !value)} size="sm" variant={autoEnemies ? "primary" : "ghost"}>怪物全自动：{autoEnemies ? "开" : "关"}</Button>
          {resetConfirmation ? (
            <>
              <Button
                disabled={resetCurrentCombat.isPending}
                loading={resetCurrentCombat.isPending}
                onClick={() => resetCurrentCombat.mutate()}
                size="sm"
                variant="danger"
              >
                确认重置当前战斗
              </Button>
              <Button disabled={resetCurrentCombat.isPending} onClick={() => setResetConfirmation(false)} size="sm">取消</Button>
            </>
          ) : (
            <Button
              disabled={!["active", "ended"].includes(combat.status)}
              onClick={() => setResetConfirmation(true)}
              size="sm"
              variant="danger"
            >
              重置当前战斗
            </Button>
          )}
          <Button disabled={combat.status !== "active" || update.isPending} onClick={() => update.mutate({ status: "ended" })} size="sm">结束战斗</Button>
          {combat.status === "ended" ? archiveConfirmation ? (
            <>
              <Button disabled={update.isPending} loading={update.isPending} onClick={() => update.mutate({ status: "archived" })} size="sm" variant="danger">确认归档</Button>
              <Button disabled={update.isPending} onClick={() => setArchiveConfirmation(false)} size="sm">取消</Button>
            </>
          ) : <Button onClick={() => setArchiveConfirmation(true)} size="sm">归档战斗</Button> : null}
          {combat.status === "archived" ? <Button disabled={update.isPending} loading={update.isPending} onClick={() => update.mutate({ status: "ended" })} size="sm">恢复归档</Button> : null}
          {combat.status === "ended" && combat.scene_id ? <Button onClick={() => navigate("/game-table")} size="sm" variant="primary">返回游戏推进台</Button> : null}
        </div>
      </div>
      {resetConfirmation ? (
        <p className="mb-0 mt-2 rounded border border-red-900/60 bg-red-950/15 px-3 py-2 text-2xs text-red-200">
          {combat.status === "ended" ? "这场战斗将重新变为进行中。" : ""}
          将清空本场日志、效果、死亡豁免和地图位置，并把所有参战者恢复到开战记录、回到第1轮第一位。
          已经写入角色背包、金币或经验的结算不会被倒扣，也不会再次发放。
        </p>
      ) : null}
      {archiveConfirmation ? (
        <p className="mb-0 mt-2 rounded border border-amber-800/60 bg-amber-950/15 px-3 py-2 text-2xs text-amber-200">
          归档后本场战斗只读，日志、结算和奖励记录都会保留；以后可随时恢复，不会删除任何战役事实。
        </p>
      ) : null}
      {combat.status === "archived" ? (
        <p className="mb-0 mt-2 rounded border border-ink-600 bg-ink-950/60 px-3 py-2 text-2xs text-stone-400">
          这场战斗已归档并处于只读状态。仍可查看先攻卡、战斗地图、日志与既有结算记录；恢复归档后可继续管理。
        </p>
      ) : null}
      {combat.status === "active" && allMonstersDefeated ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded border-2 border-emerald-500/60 bg-emerald-950/20 p-3">
          <Badge tone="ok">结束条件已满足</Badge>
          <strong className="mr-auto text-sm text-emerald-200">所有怪物均已失去战斗力，等待 DM 确认结束。</strong>
          <Button loading={update.isPending} onClick={() => update.mutate({ status: "ended" })} variant="primary">DM确认结束并进入结算</Button>
        </div>
      ) : null}
      {combat.status === "active" ? (
        <>
          <p className="mb-2 mt-3 text-2xs text-stone-500">先攻 = d20 + 敏捷调整值；这里填写最终先攻结果。AC 是护甲等级，HP 是生命值。</p>
          <form className="grid gap-2 md:grid-cols-[1fr_6rem_6rem_6rem_auto]" onSubmit={(event: FormEvent) => { event.preventDefault(); if (name.trim()) add.mutate(); }}>
            <label className="text-2xs text-stone-500">从原子选择（自动填充）<select className={`${inputCls} mt-1`} onChange={(event) => selectCandidate(event.target.value)} value={selectedKey}><option value="">手动录入</option>{candidates.map((candidate) => <option key={candidate.key} value={candidate.key}>{candidate.entityType === "character" ? "玩家" : candidate.entityType === "npc" ? "NPC" : "怪物"} · {candidate.name}</option>)}</select></label>
            <label className="text-2xs text-stone-500">参与者名称<input className={`${inputCls} mt-1`} onChange={(event) => setName(event.target.value)} placeholder="例如：大妞 / 哥布林" value={name} /></label>
            <label className="text-2xs text-stone-500">先攻总值<input className={`${inputCls} mt-1`} min="0" onChange={(event) => setInitiative(event.target.value)} type="number" value={initiative} /></label>
            <label className="text-2xs text-stone-500">护甲 AC<input className={`${inputCls} mt-1`} max="99" min="0" onChange={(event) => setArmorClass(event.target.value)} type="number" value={armorClass} /></label>
            <label className="text-2xs text-stone-500">生命 HP<input className={`${inputCls} mt-1`} min="1" onChange={(event) => setHp(event.target.value)} type="number" value={hp} /></label>
            <Button disabled={!name.trim() || Number(hp) < 1} icon="plus" loading={add.isPending} type="submit">添加</Button>
          </form>
        </>
      ) : null}
      <CombatLogPanel actions={combatActions.data ?? []} />
      {ordered.length > 0 ? (
        <InitiativeCardStrip
          currentIndex={combat.current_turn_index}
          expandedId={expandedFighterId}
          fighters={ordered}
          onToggle={(fighterId) => setExpandedFighterId((current) => current === fighterId ? null : fighterId)}
        />
      ) : null}
      <div className="mt-3 grid items-start gap-3 xl:grid-cols-[minmax(0,1fr)_30rem]">
        <div className="min-w-0">
          {fighters.isLoading ? <LoadingBlock label="正在读取先攻列表…" /> : null}
          {fighters.isError ? <ErrorState error={fighters.error} onRetry={() => void fighters.refetch()} /> : null}
          {!fighters.isLoading && ordered.length === 0 ? <EmptyState title="尚无参与者" hint="录入先攻与 HP 后即可开始逐回合追踪。" /> : null}
          {ordered.length > 0 && combat.status !== "archived" ? (
            <details className="mb-3 rounded-lg border border-ink-700 bg-ink-950/40">
              <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-stone-300">DM状态调整与高级编辑</summary>
              <ol className="m-0 flex list-none flex-col gap-1.5 border-t border-ink-700 p-3">
                {ordered.map((fighter, index) => <CombatantRow campaignId={campaignId} character={candidates.find((candidate) => candidate.entityId === fighter.entity_id)?.character} combat={combat} combatants={ordered} current={combat.status === "active" && index === combat.current_turn_index} effects={(combatEffects.data ?? []).filter((effect) => effect.target_combatant_id === fighter.id && effect.status === "active")} fighter={fighter} key={fighter.id} />)}
              </ol>
            </details>
          ) : null}
          {ordered.length > 0 ? (
            <BattleGrid
              key={`${combat.id}:${resetGeneration}`}
              activeFighterId={activeFighter?.id ?? null}
              automateEnemies={autoEnemies}
              campaignId={campaignId}
              candidates={candidates}
              combatId={combat.id}
              endingTurn={nextTurn.isPending}
              fighters={ordered}
              grid={grid}
              onEndTurn={() => nextTurn.mutate()}
              onAutomationMovementChange={setAutomaticMovementPending}
              onTargetSelect={setSelectedMapTargetId}
              onTargetValidityChange={updateTargetableFighterIds}
              targeting={targetingRange}
              turnKey={`${combat.round_number}:${combat.current_turn_index}:${activeFighter?.id ?? "none"}`}
            />
          ) : null}
        </div>
        <aside className="rounded-lg border-2 border-ember-700/60 bg-ink-950/70 p-3 xl:sticky xl:top-4">
          <div className="mb-3">
            <p className="m-0 text-2xs uppercase tracking-[0.16em] text-ember-400">Current Turn</p>
            <h3 className="mb-0 mt-1 text-sm text-parchment-100">当前回合操作台</h3>
            <p className="mb-0 mt-1 text-2xs text-stone-500">随当前角色自动切换；玩家在这里选择行动，怪物在这里自动执行。</p>
          </div>
          {activeFighter ? (
            <TurnCommandConsole
              key={`${combat.id}:${resetGeneration}:${activeFighter.id}`}
              active={activeFighter}
              activeCharacter={activeCharacter}
              autoEnemies={autoEnemies}
              automationReady={!nextTurn.isPending && !automaticMovementPending}
              campaignId={campaignId}
              combatId={combat.id}
              fighters={ordered}
              onAutoEnemiesChange={setAutoEnemies}
              onEnemyTurnComplete={() => {
                if (!nextTurn.isPending) nextTurn.mutate();
              }}
              onRangeChange={setTargetingRange}
              onTargetChange={setSelectedMapTargetId}
              selectedTargetId={selectedMapTargetId}
              turnKey={`${combat.round_number}:${combat.current_turn_index}:${activeFighter.id}`}
              validTargetIds={targetableFighterIds}
            />
          ) : (
            <p className="text-xs text-stone-500">当前没有可行动单位。</p>
          )}
          <PlayerRollPanel
            actions={combatActions.data ?? []}
            activeEnemy={activeFighter && activeFighter.entity_type !== "character" ? activeFighter : undefined}
            automationEnabled={autoEnemies}
            campaignId={campaignId}
            combatId={combat.id}
            fighters={ordered}
            onResolved={() => {
              if (autoEnemies && activeFighter?.entity_type !== "character" && !nextTurn.isPending) {
                nextTurn.mutate();
              }
            }}
          />
        </aside>
      </div>
      {combat.status === "ended" ? (
        <div className="mt-4 rounded-lg border border-amber-800/50 bg-amber-950/10 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-auto text-sm text-parchment-100">战斗原子结算</strong>
            <Badge tone={combat.xp_awarded ? "ok" : "warn"}>{combat.xp_awarded ? "已结算" : "等待预览与 DM 确认"}</Badge>
          </div>
          <p className="mb-2 mt-2 text-xs text-stone-400">参与玩家：{playerCharacters.map((character) => character.name).join("、") || "无"}。一次事务同时分配经验、金币和战利品，并回写 HP、持续状态与场景结果；预览不会写入。</p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-2xs text-stone-500">总 XP<input className={`${inputCls} mt-1 w-32`} disabled={combat.xp_awarded} min="0" onChange={(event) => setXpOverride(event.target.value)} type="number" value={xpOverride || String(combat.base_xp || monsterXp)} /></label>
            <span className="pb-2 text-xs text-ember-300">每名玩家 {xpPerCharacter} XP</span>
            <label className="text-2xs text-stone-500">每名玩家 GP<input className={`${inputCls} mt-1 w-28`} disabled={combat.xp_awarded} min="0" onChange={(event) => setGoldPerCharacter(event.target.value)} type="number" value={goldPerCharacter} /></label>
            <Button disabled={combat.xp_awarded || playerCharacters.length === 0} loading={previewSettlement.isPending} onClick={() => previewSettlement.mutate()}>生成结算预览</Button>
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-[1fr_10rem_6rem_7rem_7rem]">
            <input className={inputCls} disabled={combat.xp_awarded} onChange={(event) => setLootName(event.target.value)} placeholder="战利品名称（可选）" value={lootName} />
            <select className={inputCls} disabled={combat.xp_awarded} onChange={(event) => setLootRecipientId(event.target.value)} value={lootRecipientId}><option value="">分配给角色</option>{playerCharacters.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}</select>
            <input aria-label="战利品数量" className={inputCls} disabled={combat.xp_awarded} min="1" onChange={(event) => setLootQuantity(event.target.value)} type="number" value={lootQuantity} />
            <input aria-label="战利品重量" className={inputCls} disabled={combat.xp_awarded} min="0" onChange={(event) => setLootWeight(event.target.value)} placeholder="重量 lb" type="number" value={lootWeight} />
            <input aria-label="战利品价格" className={inputCls} disabled={combat.xp_awarded} min="0" onChange={(event) => setLootPriceGp(event.target.value)} placeholder="价值 GP" type="number" value={lootPriceGp} />
          </div>
          {settlementPreview ? (
            <div className="mt-3 rounded border border-amber-700/50 bg-ink-950/40 p-2">
              <strong className="text-xs text-amber-200">尚未写入：请核对以下变化</strong>
              <ul className="mb-2 mt-1 pl-4 text-2xs text-stone-300">
                {settlementPreview.preview.character_changes.map((change) => <li key={change.character_id}>{change.name}：HP {change.before.hp} → {change.after.hp}；XP +{change.xp_award}{change.conditions_to_add.length > 0 ? `；持续状态 ${change.conditions_to_add.join("、")}` : ""}</li>)}
                {settlementPreview.preview.currency_changes.map((change) => <li key={`currency-${change.character_id}`}>{change.name}：金币 +{(change.award_copper / 100).toFixed(2)} GP</li>)}
                {settlementPreview.preview.loot_changes.map((change, index) => <li key={`loot-${change.character_id}-${index}`}>{change.character_name}获得：{change.name} ×{change.quantity}（{change.unit_weight_lb} lb，价值 {(change.price_cp / 100).toFixed(2)} GP）</li>)}
              </ul>
              <div className="flex gap-2">
                <Button loading={confirmSettlement.isPending} onClick={() => confirmSettlement.mutate()} variant="primary">DM确认一次性结算</Button>
                <Button disabled={confirmSettlement.isPending} onClick={() => setSettlementPreview(null)}>取消</Button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}

function CombatContent({ campaignId }: { campaignId: string }): ReactElement {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [name, setName] = useState("");
  const [sceneId, setSceneId] = useState("");
  const [selectedCombatId, setSelectedCombatId] = useState(
    () => sessionStorage.getItem(`dnd-dm-active-combat:${campaignId}`) ?? "",
  );
  const combats = useQuery({ queryKey: ["combats", campaignId], queryFn: ({ signal }) => listCombats(campaignId, signal), refetchInterval: 1_000 });
  const scenes = useQuery({ queryKey: ["scenes", campaignId], queryFn: ({ signal }) => listScenes(campaignId, signal) });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const locations = useQuery({ queryKey: ["locations", campaignId], queryFn: ({ signal }) => listLocations(campaignId, signal) });
  const npcs = useQuery({ queryKey: ["npcs", campaignId], queryFn: ({ signal }) => listNpcs(campaignId, signal) });
  const monsters = useQuery({ queryKey: ["monsters", campaignId], queryFn: ({ signal }) => listMonsters(campaignId, signal) });
  const events = useQuery({ queryKey: ["events", campaignId], queryFn: ({ signal }) => listEvents(campaignId, signal) });
  const encounterAdjustments = useQuery({ queryKey: ["encounter-adjustments", campaignId], queryFn: ({ signal }) => listEncounterAdjustments(campaignId, undefined, signal) });
  const candidates: CombatCandidate[] = [
    ...(characters.data ?? []).map((entity: Character) => ({ key: `character:${entity.id}`, entityType: "character" as const, entityId: entity.id, name: entity.name, armorClass: entity.armor_class, hp: entity.hp, maxHp: entity.max_hp, dexterity: entity.ability_scores.dexterity ?? 10, speed: entity.speed, actions: [...entity.actions, ...entity.spells], abilityScores: entity.ability_scores, character: entity })),
    ...(npcs.data ?? []).map((entity: Npc) => ({ key: `npc:${entity.id}`, entityType: "npc" as const, entityId: entity.id, name: entity.name, armorClass: entity.armor_class, hp: entity.hp, maxHp: entity.max_hp, dexterity: entity.ability_scores.dexterity ?? 10, speed: entity.speed, actions: entity.actions, abilityScores: entity.ability_scores, challengeRating: entity.challenge_rating })),
    ...(monsters.data ?? []).map((entity: Monster) => ({ key: `monster:${entity.id}`, entityType: "monster" as const, entityId: entity.id, name: entity.name, armorClass: entity.armor_class, hp: entity.hp, maxHp: entity.max_hp, dexterity: entity.ability_scores.dexterity ?? 10, speed: entity.speed, actions: entity.actions, abilityScores: entity.ability_scores, challengeRating: entity.challenge_rating })),
  ];
  const create = useMutation({
    mutationFn: () => createCombat(campaignId, { name: name.trim(), scene_id: sceneId || null, status: "active" }),
    onSuccess: (created) => {
      setName("");
      setSelectedCombatId(created.id);
      sessionStorage.setItem(`dnd-dm-active-combat:${campaignId}`, created.id);
      void client.invalidateQueries({ queryKey: ["combats", campaignId] });
      showToast("战斗已创建并加载场景网格");
    },
    onError: () => showToast("创建战斗失败", "error"),
  });
  useEffect(() => {
    const available = combats.data ?? [];
    if (available.length === 0) return;
    if (available.some((combat) => combat.id === selectedCombatId)) return;
    if (selectedCombatId && combats.isFetching) return;
    const newestFirst = [...available].reverse();
    const preferred = newestFirst.find((combat) => combat.status === "active")
      ?? newestFirst.find((combat) => combat.status === "ended")
      ?? newestFirst[0];
    if (!preferred) return;
    setSelectedCombatId(preferred.id);
    sessionStorage.setItem(`dnd-dm-active-combat:${campaignId}`, preferred.id);
  }, [campaignId, combats.data, combats.isFetching, selectedCombatId]);
  const selectedCombat = combats.data?.find((combat) => combat.id === selectedCombatId);
  const selectedCombatSceneId = selectedCombat?.scene_id ?? null;
  const liveCombatId = selectedCombat?.id ?? null;
  useEffect(() => {
    if (!liveCombatId) return;
    void setPlayerRoomLiveState(
      campaignId,
      selectedCombatSceneId,
      liveCombatId,
    ).catch(() => undefined);
  }, [campaignId, liveCombatId, selectedCombatSceneId]);
  return (
    <div className="mx-auto max-w-[1500px] p-4 lg:p-6">
      <Panel eyebrow="遭遇" title="战斗辅助">
        <form className="grid gap-2 md:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => { event.preventDefault(); if (name.trim()) create.mutate(); }}>
          <input className={inputCls} onChange={(event) => setName(event.target.value)} placeholder="战斗名称，例如：城门伏击" value={name} />
          <select className={inputCls} onChange={(event) => setSceneId(event.target.value)} value={sceneId}><option value="">必须选择战斗场景</option>{scenes.data?.map((scene) => <option key={scene.id} value={scene.id}>{scene.name}{readSceneGrid(scene.notes) ? " · 有网格" : ""}</option>)}</select>
          <Button disabled={!name.trim() || !sceneId} loading={create.isPending} icon="plus" type="submit" variant="primary">创建战斗</Button>
        </form>
        {(combats.data?.length ?? 0) > 0 ? (
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded border border-ink-700 bg-ink-950/40 p-2">
            <strong className="text-xs text-parchment-100">当前查看</strong>
            <select
              aria-label="当前战斗"
              className={`${inputCls} min-w-64 flex-1`}
              onChange={(event) => {
                setSelectedCombatId(event.target.value);
                sessionStorage.setItem(`dnd-dm-active-combat:${campaignId}`, event.target.value);
              }}
              value={selectedCombatId}
            >
              {combats.data?.map((combat) => (
                <option key={combat.id} value={combat.id}>
                  {COMBAT_STATUS_LABELS[combat.status] ?? combat.status} · {combat.name}
                </option>
              ))}
            </select>
            <span className="text-2xs text-stone-500">一次只显示一场；从推进台进入时自动打开刚创建的战斗。</span>
          </div>
        ) : null}
      </Panel>
      <div className="mt-4 flex flex-col gap-3">
        {combats.isLoading ? <Panel title="战斗"><LoadingBlock /></Panel> : null}
        {combats.isError ? <Panel title="战斗"><ErrorState error={combats.error} onRetry={() => void combats.refetch()} /></Panel> : null}
        {!combats.isLoading && !combats.isError && combats.data?.length === 0 ? <Panel title="战斗"><EmptyState title="暂无战斗" hint="创建战斗后可以追踪先攻、HP、轮次和当前回合。" /></Panel> : null}
        {selectedCombat ? (() => {
          const scene = scenes.data?.find((item) => item.id === selectedCombat.scene_id);
          const location = locations.data?.find(
            (item) => item.id === scene?.location_id,
          );
          const storedGrid = scene ? readSceneGrid(scene.notes) : null;
          const sceneGrid = storedGrid ?? (scene
            ? generateTacticalSceneGrid(
                scene.name,
                scene.description ?? "",
                `${location?.name ?? ""} ${location?.description ?? ""}`,
              )
            : null);
          const sceneAdjustments = (events.data ?? [])
            .filter((event) => event.metadata_json.scene_id === selectedCombat.scene_id && Number(event.metadata_json.encounter_adjustment ?? 0) !== 0)
            .map((event) => {
              const rawReason = event.metadata_json.encounter_reason;
              return {
                shift: Number(event.metadata_json.encounter_adjustment ?? 0),
                reason: typeof rawReason === "string" ? rawReason : (event.description ?? event.title),
              };
            });
          const encounterConsequences = (encounterAdjustments.data ?? [])
            .filter((proposal) => proposal.status === "applied" && proposal.combat_id === selectedCombat.id);
          return <CombatCard campaignId={campaignId} combat={selectedCombat} candidates={candidates} encounterConsequences={encounterConsequences} grid={sceneGrid} key={selectedCombat.id} sceneAdjustments={sceneAdjustments} sceneName={scene?.name ?? null} />;
        })() : null}
      </div>
    </div>
  );
}

export function CombatPage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <CombatContent campaignId={campaignId} />}</RequireCampaign>;
}
