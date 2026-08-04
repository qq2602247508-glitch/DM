import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactElement } from "react";

import {
  advanceCombatTurn, confirmCombatAction, confirmCombatEffect,
  confirmCombatSettlement, confirmCombatantDeath, confirmConcentrationCheck,
  confirmDeathSave, confirmCombatEffectSave, createCombat, createCombatant, deleteCombatant, endCombatEffect,
  createEvent, endCombatSummon, getCombatEndCondition, getDeathSave, listCombatActions, listCombatEffects, listCombatants, listCombats,
  listEncounterAdjustments, listEvents, previewCombatAction, previewMonsterAI, addCombatSummon,
  previewCombatSettlement, resetCombat, revertEncounterAdjustment, updateCombat, updateCombatant,
} from "../api/entities";
import type {
  CombatActionCommand, CombatEffectCommand, CombatSettlementCommand,
} from "../api/entities";
import { listCharacters, listCompanions, listLocations, listNpcs, updateCharacter } from "../api/entities";
import { getSceneGrid, listMonsters, listScenes } from "../api/world";
import { getPlayerRoom, moveMonsterCombatant, setPlayerRoomLiveState } from "../api/playerRoom";
import { isApiError } from "../api/client";
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
  type CombatTargetingValidity,
} from "../components/combat/TurnCommandConsole";
import {
  DIFFICULTY_LABELS, encounterDifficulty, shiftDifficulty, xpForChallengeRating,
  type Difficulty,
} from "../ui/progressionRules";
import {
  describeEncounterOperation, difficultyShiftLabel,
} from "../ui/encounterAdjustments";
import {
  actionEconomySummary, damageComponentsByTargetSummary, damageComponentsSummary,
  damageModifierLabel, deathSaveSummary,
} from "../ui/combatPresentation";
import {
  chooseEnemyTarget,
  isEnemyAiControlledCombatant,
  isPlayerControlledCombatant,
} from "../ui/combatAutomation";
import { advancedActionPendingRollSummary } from "../ui/advancedMonsterActions";
import {
  movementCommitKey,
  planApproachPath,
  planTargetingPath,
  planRetreatPath,
  shortestMovementPath,
  type MovementPlan,
} from "../ui/combatMovement";
import {
  availableElevationLayers,
  evaluateTargetingElevation,
  explicitElevationFt,
  getTargetingCells,
  gridDistanceFt,
  hasLineOfSight,
  isAimPointInRange,
  isBlockedCell,
  type GridPoint,
  type TargetingElevationResult,
} from "../ui/gridTargeting";
import {
  findSceneSpawnCells,
  generateTacticalSceneGrid,
} from "../ui/sceneGridGenerator";
import {
  getDoorOrientation,
  isMapVoidCell,
  shouldShowTerrainLabel,
  terrainCellClass,
} from "../ui/mapPresentation";

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

type ElevationLayer = number | "unknown";

function combatantGridPosition(fighter: Combatant): Record<string, unknown> | null {
  const position = fighter.snapshot_json.grid_position;
  return position && typeof position === "object" && !Array.isArray(position)
    ? position as Record<string, unknown>
    : null;
}

function combatantElevationFt(fighter: Combatant | undefined): number | null {
  return fighter ? explicitElevationFt(fighter.snapshot_json.grid_position) : null;
}

function elevationLayerLabel(layer: ElevationLayer): string {
  return layer === "unknown" ? "高度未记录" : `${layer}尺`;
}

function targetingElevationMessage(
  fighter: Combatant,
  result: TargetingElevationResult,
): string {
  if (result.status === "missing_target_elevation") {
    return `${fighter.display_name}没有记录 grid_position.elevation_ft，不能自动作为三维区域目标。`;
  }
  if (result.status === "missing_origin_elevation") {
    return "区域来源单位没有记录 grid_position.elevation_ft，不能自动判定上下层目标。";
  }
  if (result.status === "missing_height" || result.status === "missing_size") {
    return "该区域缺少可靠的高度或尺寸数据，不能自动判定上下层目标。";
  }
  return `${fighter.display_name}不在当前技能的垂直影响范围内。`;
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
          {[...actions].reverse().map((action) => {
            const componentSummary = damageComponentsSummary(action.result_json.damage_components);
            const targetComponentSummary = damageComponentsByTargetSummary(action.result_json.damage_components_by_target);
            return (
              <li className="list-none rounded border border-ink-800 bg-ink-950/70 p-2" key={action.id}>
                <span className="text-stone-600">R{action.round_number} · T{action.turn_index + 1}</span>
                <strong className="mt-0.5 block text-stone-200">{action.summary}</strong>
                {componentSummary ? <span className="mt-1 block leading-5 text-amber-200">伤害段：{componentSummary}</span> : null}
                {targetComponentSummary ? <span className="mt-1 block leading-5 text-amber-200">逐目标：{targetComponentSummary}</span> : null}
                {action.explanation ? <span className="mt-1 block leading-5 text-stone-500">{action.explanation}</span> : null}
              </li>
            );
          })}
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

function compiledEffectSummary(effect: CombatEffect): string | null {
  const block = effect.details_json.rule_block;
  if (!block || typeof block !== "object") return null;
  const raw = block as Record<string, unknown>;
  const kind = displayValue(raw.kind, "");
  if (kind === "modifier") {
    const value = raw.value == null ? "" : ` ${displayValue(raw.value)}`;
    return `${displayValue(raw.stat, "修正")} ${displayValue(raw.operation, "")} ${value}`.trim();
  }
  if (kind === "defense") {
    const types = Array.isArray(raw.damage_types)
      ? raw.damage_types.filter((item): item is string | number => typeof item === "string" || typeof item === "number").map(String).join("、")
      : "";
    return `${displayValue(raw.operation, "防御")}：${types}`;
  }
  if (kind === "condition") return `${displayValue(raw.operation, "状态")}：${displayValue(raw.condition, "")}`;
  if (kind === "damage") return `${displayValue(raw.expression, "伤害")} ${displayValue(raw.damage_type, "")}`.trim();
  return null;
}

type EffectSavePrompt = {
  effect_id: string;
  target_combatant_id: string;
  save_dc: number;
  save_ability: string;
  summary?: string;
};

type ConcentrationPrompt = {
  actionId: string;
  damageActionId: string;
  targetCombatantId: string;
  dc: number;
  summary?: string;
};

function readConcentrationPrompts(actions: CombatAction[]): ConcentrationPrompt[] {
  return actions.flatMap((action) => {
    if (action.action_type !== "concentration_check_prompt" || action.status !== "previewed") {
      return [];
    }
    const request = action.request_json;
    return typeof request.damage_action_id === "string"
      && typeof request.target_combatant_id === "string"
      && typeof request.dc === "number"
      ? [{
          actionId: action.id,
          damageActionId: request.damage_action_id,
          targetCombatantId: request.target_combatant_id,
          dc: request.dc,
          summary: typeof request.summary === "string" ? request.summary : undefined,
        }]
      : [];
  });
}

function readEffectSavePrompts(prompts: unknown[]): EffectSavePrompt[] {
  return prompts.flatMap((prompt) => {
    if (typeof prompt !== "object" || prompt === null) return [];
    const candidate = prompt as Record<string, unknown>;
    return typeof candidate.effect_id === "string"
      && typeof candidate.target_combatant_id === "string"
      && typeof candidate.save_dc === "number"
      && typeof candidate.save_ability === "string"
      ? [{
          effect_id: candidate.effect_id,
          target_combatant_id: candidate.target_combatant_id,
          save_dc: candidate.save_dc,
          save_ability: candidate.save_ability,
          summary: typeof candidate.summary === "string" ? candidate.summary : undefined,
        }]
      : [];
  });
}

function isActiveUntilSaveEffect(effect: CombatEffect): boolean {
  return effect.status === "active"
    && effect.duration_unit === "until_save"
    && typeof effect.save_dc === "number"
    && typeof effect.save_ability === "string"
    && Boolean(effect.save_ability.trim());
}

function CombatantRow({ campaignId, combat, fighter, current, character, effects, combatants, concentrationPrompt }: { campaignId: string; combat: Combat; fighter: Combatant; current: boolean; character?: Character; effects: CombatEffect[]; combatants: Combatant[]; concentrationPrompt?: ConcentrationPrompt }): ReactElement {
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
  useEffect(() => {
    setPendingConcentration(
      concentrationPrompt
        ? { actionId: concentrationPrompt.damageActionId, dc: concentrationPrompt.dc }
        : null,
    );
  }, [concentrationPrompt, concentrationPrompt?.actionId, concentrationPrompt?.damageActionId, concentrationPrompt?.dc]);
  const [pendingAction, setPendingAction] = useState<{
    command: CombatActionCommand;
    preview: CombatActionPreview;
  } | null>(null);
  const [monsterPlan, setMonsterPlan] = useState<{
    action_name: string;
    target_ids: string[];
    reason: string;
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
      const prompt = result.action.result_json.concentration_prompt;
      if (dc > 0) {
        setPendingConcentration({
          actionId: typeof prompt === "object" && prompt !== null && typeof (prompt as Record<string, unknown>).damage_action_id === "string"
            ? String((prompt as Record<string, unknown>).damage_action_id)
            : result.action.id,
          dc,
        });
      }
      showToast(dc > 0 ? `结算完成；需要专注检定 DC ${dc}` : "结算已确认并写入战斗日志");
    },
    onError: () => showToast("确认失败，目标状态可能已变化，请重新预览", "error"),
  });
  const previewMonsterPlan = useMutation({
    mutationFn: () => {
      const raw = fighter.snapshot_json.recharge_available;
      const rechargeAvailable = raw && typeof raw === "object" && !Array.isArray(raw)
        ? Object.fromEntries(
            Object.entries(raw).filter(([, value]) => typeof value === "boolean"),
          ) as Record<string, boolean>
        : undefined;
      return previewMonsterAI(
        campaignId,
        combat.id,
        fighter.id,
        {
          actorVersion: fighter.version,
          rechargeAvailable,
        },
      );
    },
    onSuccess: (result) => {
      setMonsterPlan(result.plan);
      showToast(result.plan ? "怪物行动计划已生成，仍需 DM 确认" : "当前没有可用的怪物行动");
    },
    onError: () => showToast("怪物行动计划生成失败，请刷新战斗状态", "error"),
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
  const endSummon = useMutation({
    mutationFn: () => endCombatSummon(
      campaignId,
      combat.id,
      fighter.id,
      fighter.version,
      "DM在战斗台确认召唤物离场",
    ),
    onSuccess: (result) => {
      invalidate();
      showToast(result.ended_effects.length > 0
        ? `召唤物已离场，并结束 ${result.ended_effects.length} 个关联效果`
        : "召唤物已离开战斗轮");
    },
    onError: () => showToast("召唤物结束失败，请刷新后重试", "error"),
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
        <p className="mb-0 mt-0.5 text-2xs text-stone-500">护甲 AC {fighter.armor_class} · {isPlayerControlledCombatant(fighter.entity_type, fighter.snapshot_json) ? (fighter.entity_type === "companion" ? "玩家召唤物" : "玩家") : fighter.entity_type === "npc" ? "NPC" : fighter.entity_type === "companion" ? "敌方召唤物" : "怪物"} · {actionEconomySummary(fighter)}</p>
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
        {fighter.entity_type === "companion" && typeof fighter.snapshot_json.summon_source === "object" ? <Button disabled={endSummon.isPending} loading={endSummon.isPending} onClick={() => endSummon.mutate()} size="sm" variant="danger">结束召唤</Button> : null}
        <Button disabled={remove.isPending} onClick={() => remove.mutate()} size="sm" variant="danger">移除</Button>
      </div>
      {fighter.entity_type === "monster" ? (
        <div className="rounded border border-cyan-900/60 bg-cyan-950/10 p-2 md:col-span-4">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-auto text-xs text-cyan-200">怪物行动计划</strong>
            <Button
              disabled={previewMonsterPlan.isPending || !current || !fighter.is_active}
              loading={previewMonsterPlan.isPending}
              onClick={() => previewMonsterPlan.mutate()}
              size="sm"
            >
              生成 DM 预览
            </Button>
          </div>
          {monsterPlan ? (
            <p className="mb-0 mt-1 text-2xs text-stone-300">
              建议「{monsterPlan.action_name}」→ {monsterPlan.target_ids.map((id) => combatants.find((item) => item.id === id)?.display_name ?? id).join("、")}
              <span className="ml-2 text-stone-500">{monsterPlan.reason}</span>
            </p>
          ) : <p className="mb-0 mt-1 text-2xs text-stone-600">计划只选择目标与动作，不会自动掷骰或写入伤害。</p>}
        </div>
      ) : null}
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
          {damageComponentsSummary(pendingAction.preview.result.damage_components) ? <p className="mb-2 mt-0 text-2xs text-amber-200">逐段结算：{damageComponentsSummary(pendingAction.preview.result.damage_components)}</p> : null}
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
        {effects.length > 0 ? <div className="mt-2 flex flex-wrap gap-1.5">{effects.map((effect) => <span className="inline-flex items-center gap-1 rounded border border-violet-800/60 px-2 py-1 text-2xs text-stone-300" key={effect.id}>{effect.name}{compiledEffectSummary(effect) ? ` · ${compiledEffectSummary(effect)}` : ""}{effect.requires_concentration ? " · 专注" : effect.ends_round !== null ? ` · 至第${effect.ends_round}轮` : ""}<Button disabled={endEffect.isPending} onClick={() => endEffect.mutate(effect)} size="sm">结束</Button></span>)}</div> : <p className="mb-0 mt-1 text-2xs text-stone-600">当前没有活动效果。</p>}
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
  targetingActorId,
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
  onTargetValidityChange: (validity: CombatTargetingValidity) => void;
  targetingActorId: string | null;
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
  const [fogPreview, setFogPreview] = useState(false);
  const [movingFighterId, setMovingFighterId] = useState<string | null>(null);
  const movementRequestInFlight = useRef<string | null>(null);
  const [impactFighterId, setImpactFighterId] = useState<string | null>(null);
  const [elevationLayer, setElevationLayer] = useState<ElevationLayer>(0);
  const processedAiTurn = useRef<string | null>(null);
  const previousHp = useRef<Record<string, number>>({});
  const targetingSourceId = targeting ? targetingActorId ?? activeFighterId : activeFighterId;
  const targetingSource = fighters.find((fighter) => fighter.id === targetingSourceId);
  const targetingOriginElevationFt = combatantElevationFt(targetingSource);
  const elevationLayers = useMemo(
    () => availableElevationLayers(fighters.map((fighter) => fighter.snapshot_json.grid_position)),
    [fighters],
  );
  const hasUnknownElevation = fighters.some((fighter) => combatantElevationFt(fighter) === null);
  const targetingSignature = targeting
    ? `${targeting.shape}:${targeting.rangeFt}:${targeting.sizeFt ?? ""}:${targeting.widthFt ?? ""}:${targeting.heightFt ?? ""}:${targeting.anchorHeightFt ?? ""}:${targeting.requiresElevation ? "3d" : "2d"}:${targeting.originSelf ? "self" : "point"}`
    : "awaiting-targeting";
  const automationPlanKey = `${turnKey}:${targetingSignature}`;
  useEffect(() => {
    setPositions((current) => {
      const next: Record<string, [number, number]> = {};
      const playerSpawns = findSceneSpawnCells(tacticalGrid, "player");
      const enemySpawns = findSceneSpawnCells(tacticalGrid, "enemy");
      const occupied = new Set<string>();
      fighters.forEach((fighter) => {
        const stored = combatantGridPosition(fighter);
        const local = current[fighter.id];
        const row = movingFighterId === fighter.id && local ? local[0] : Number(stored?.row);
        const col = movingFighterId === fighter.id && local ? local[1] : Number(stored?.col);
        if (
          Number.isInteger(row)
          && Number.isInteger(col)
          && row >= 1
          && row <= height
          && col >= 1
          && col <= width
          && !isBlockedCell(tacticalGrid, { row, col })
        ) {
          next[fighter.id] = [row, col];
          occupied.add(`${row}:${col}`);
        }
      });
      fighters.forEach((fighter, index) => {
        if (next[fighter.id]) return;
        const local = current[fighter.id];
        if (
          local
          && !isBlockedCell(tacticalGrid, { row: local[0], col: local[1] })
          && !occupied.has(`${local[0]}:${local[1]}`)
        ) {
          next[fighter.id] = local;
          occupied.add(`${local[0]}:${local[1]}`);
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
          && !occupied.has(`${point.row}:${point.col}`)
        )).sort((a, b) => (
          gridDistanceFt(origin, a) - gridDistanceFt(origin, b)
        ))[0];
        if (free) {
          next[fighter.id] = [free.row, free.col];
          occupied.add(`${free.row}:${free.col}`);
        }
      });
      const currentIds = Object.keys(current);
      const nextIds = Object.keys(next);
      const unchanged = currentIds.length === nextIds.length
        && nextIds.every((id) => (
          current[id]?.[0] === next[id]?.[0]
          && current[id]?.[1] === next[id]?.[1]
        ));
      return unchanged ? current : next;
    });
  }, [fighters, height, movingFighterId, tacticalGrid, width]);
  useEffect(() => {
    if (activeFighterId) setSelected(activeFighterId);
  }, [activeFighterId]);
  useEffect(() => {
    const sourceElevationFt = combatantElevationFt(targetingSource);
    if (sourceElevationFt !== null) setElevationLayer(sourceElevationFt);
  }, [targetingSource]);
  useEffect(() => {
    if (elevationLayer !== "unknown" && !elevationLayers.includes(elevationLayer)) {
      setElevationLayer(elevationLayers[0] ?? 0);
    }
    if (elevationLayer === "unknown" && !hasUnknownElevation) {
      setElevationLayer(elevationLayers[0] ?? 0);
    }
  }, [elevationLayer, elevationLayers, hasUnknownElevation]);
  useEffect(() => {
    const changed = fighters.find((fighter) => (
      previousHp.current[fighter.id] !== undefined
      && previousHp.current[fighter.id] !== fighter.hp
    ));
    previousHp.current = Object.fromEntries(fighters.map((fighter) => [fighter.id, fighter.hp]));
    if (!changed) return;
    setImpactFighterId(changed.id);
    const timeout = window.setTimeout(() => setImpactFighterId(null), 900);
    return () => window.clearTimeout(timeout);
  }, [fighters]);
  useEffect(() => {
    setAimPoint(null);
    setInteractionMode(targeting ? "target" : "move");
    setTargetingMessage(targeting
      ? targeting.originSelf
        ? "自身为区域起点；蓝色表示可选施法范围，紫色表示以自身为中心的实际影响范围。"
        : `先在地图上选择${targeting.shape === "circle" ? "爆发中心" : "目标或方向"}；浅蓝色是施法距离，紫色是实际影响范围。`
      : "");
  }, [targeting]);
  const commitMove = useCallback(async (
    fighter: Combatant,
    plan: MovementPlan,
    automatic: boolean,
    exhaustMovement = false,
    fleeing = false,
  ) => {
    if ((plan.spentFt <= 0 && !exhaustMovement) || movingFighterId) return;
    const requestKey = movementCommitKey(
      turnKey,
      fighter.id,
      fighter.version,
      plan,
      automatic,
      exhaustMovement,
      fleeing,
    );
    // `setMovingFighterId` is asynchronous.  This ref closes the window in
    // which StrictMode or two dependent effects can submit the same version
    // twice before React renders the first state update.
    if (movementRequestInFlight.current === requestKey) return;
    movementRequestInFlight.current = requestKey;
    setMovingFighterId(fighter.id);
    if (automatic) onAutomationMovementChange(true);
    const remainingMovement = exhaustMovement
      ? 0
      : Math.max(0, fighter.movement_remaining_ft - plan.spentFt);
    const startPosition = positions[fighter.id];
    try {
      for (const point of plan.path) {
        setPositions((current) => ({
          ...current,
          [fighter.id]: [point.row, point.col],
        }));
        await new Promise((resolve) => window.setTimeout(resolve, automatic ? 220 : 140));
      }
      if (automatic && plan.path.length > 0) {
        await new Promise((resolve) => window.setTimeout(resolve, 350));
      }
      if (automatic && fighter.entity_type === "monster") {
        await moveMonsterCombatant(
          campaignId,
          combatId,
          fighter.id,
          plan.destination.row,
          plan.destination.col,
          fighter.version,
          remainingMovement,
        );
      } else {
        await updateCombatant(
          campaignId,
          combatId,
          fighter.id,
          {
            conditions: fleeing
              ? [...new Set([...fighter.conditions, "撤退中"])]
              : fighter.conditions,
            movement_remaining_ft: remainingMovement,
            snapshot_json: {
              ...fighter.snapshot_json,
              // Moving on the horizontal grid must not erase the combatant's
              // saved altitude; otherwise a later three-dimensional area
              // preview would silently put a flying unit back on the ground.
              grid_position: {
                ...(combatantGridPosition(fighter) ?? {}),
                ...plan.destination,
              },
            },
          },
          fighter.version,
        );
      }
      setPositions((current) => ({
        ...current,
        [fighter.id]: [plan.destination.row, plan.destination.col],
      }));
      // Automatic movement is only the first stage of an enemy turn.  Let the
      // next render hand the now-positioned unit to the attack executor.
      if (automatic) processedAiTurn.current = null;
      await client.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      if (!automatic) showToast(`${fighter.display_name}移动 ${plan.spentFt} 尺，剩余 ${remainingMovement} 尺`);
      if (fleeing) {
        setLastAiMove(`${fighter.display_name}选择撤退，本回合只远离威胁并结束行动。`);
        onEndTurn();
      }
    } catch {
      // Enemy automation can publish a fresh combatant snapshot while the
      // movement animation is still settling.  If another invocation already
      // wrote this exact destination, the version conflict means the move is
      // complete rather than failed; refresh the authoritative position and
      // avoid showing a misleading error to the DM.
      try {
        const latestCombatants = await client.fetchQuery({
          queryKey: ["combatants", campaignId, combatId],
          queryFn: ({ signal }) => listCombatants(campaignId, combatId, signal),
          staleTime: 0,
        });
        const latest = latestCombatants.find((item) => item.id === fighter.id);
        const latestPosition = latest?.snapshot_json.grid_position;
        const latestPositionRecord = latestPosition && typeof latestPosition === "object"
          ? latestPosition as { row?: unknown; col?: unknown }
          : null;
        if (
          latestPositionRecord
          && Number(latestPositionRecord.row) === plan.destination.row
          && Number(latestPositionRecord.col) === plan.destination.col
        ) {
          setPositions((current) => ({
            ...current,
            [fighter.id]: [plan.destination.row, plan.destination.col],
          }));
          // The authoritative write already exists.  Keep the current turn
          // eligible for the next action, but do not release a second write
          // for this same movement request.
          if (automatic) processedAiTurn.current = null;
          return;
        }
      } catch {
        // Preserve the original movement error below when the refresh itself
        // is unavailable.
      }
      if (startPosition) {
        setPositions((current) => ({ ...current, [fighter.id]: startPosition }));
      }
      if (automatic) processedAiTurn.current = null;
      showToast(`${fighter.display_name}移动保存失败，请刷新战斗状态`, "error");
    } finally {
      if (movementRequestInFlight.current === requestKey) {
        movementRequestInFlight.current = null;
      }
      setMovingFighterId(null);
      if (automatic) onAutomationMovementChange(false);
    }
  }, [
    campaignId,
    client,
    combatId,
    movingFighterId,
    movementRequestInFlight,
    onAutomationMovementChange,
    onEndTurn,
    positions,
    showToast,
    turnKey,
  ]);
  useEffect(() => {
    if (!automateEnemies) return;
    if (!activeFighterId) return;
    // A legendary/reaction area can temporarily use another monster as the
    // map's targeting source.  It is a DM-directed preview, not permission
    // for the current monster's automatic movement loop to run against it.
    if (targetingActorId && targetingActorId !== activeFighterId) return;
    // Wait for the command console to publish the current action's targeting
    // template.  Running the movement planner once against the previous
    // action's range is what allowed a later action to leave the AI stranded.
    if (!targeting || (!targeting.originSelf && targeting.rangeFt <= 0)) return;
    if (processedAiTurn.current === automationPlanKey || movingFighterId) return;
    const active = fighters.find((fighter) => fighter.id === activeFighterId);
    if (!active || isPlayerControlledCombatant(active.entity_type, active.snapshot_json) || active.hp <= 0) return;
    const from = positions[active.id];
    if (!from) return;
    if (active.entity_type === "npc") {
      processedAiTurn.current = turnKey;
      const occupied = new Set(Object.entries(positions)
        .filter(([id]) => id !== active.id)
        .map(([, position]) => `${position[0]}:${position[1]}`));
      const threats = fighters
        .filter((fighter) => fighter.entity_type === "monster" && fighter.hp > 0)
        .map((fighter) => positions[fighter.id])
        .filter((position): position is [number, number] => Boolean(position))
        .map((position) => ({ row: position[0], col: position[1] }));
      const plan = planRetreatPath(
        tacticalGrid,
        { row: from[0], col: from[1] },
        threats,
        occupied,
        active.movement_remaining_ft,
      );
      if (plan.spentFt <= 0) {
        setLastAiMove(`${active.display_name}无法继续撤退，选择原地防守并结束回合。`);
        onEndTurn();
      } else {
        setLastAiMove(`${active.display_name}不进行攻击，正远离${threats.length ? "最近的怪物" : "当前冲突区域"}。`);
        void commitMove(active, plan, true, false, true);
      }
      return;
    }
    if (!isEnemyAiControlledCombatant(active.entity_type, active.snapshot_json)) return;
    // The movement planner must pursue the same player-controlled target that
    // the command console will attack.  Previously movement only considered
    // characters while the console could select a lower-HP companion, leaving
    // the monster beside one unit and waiting forever for a different unit.
    const playerTargets = fighters.filter((fighter) => (
      fighter.hp > 0
      && (
        fighter.entity_type === "character"
        || fighter.snapshot_json.controller === "player"
      )
      && positions[fighter.id]
    ));
    const selectedTarget = chooseEnemyTarget(playerTargets, "standard");
    const targetPosition = selectedTarget ? positions[selectedTarget.id] : undefined;
    if (!selectedTarget || !targetPosition) return;
    const target = { fighter: selectedTarget, position: targetPosition };
    processedAiTurn.current = automationPlanKey;
    const occupied = new Set(Object.entries(positions)
      .filter(([id]) => id !== active.id)
      .map(([, position]) => `${position[0]}:${position[1]}`));
    const plan = planApproachPath(
      tacticalGrid,
      { row: from[0], col: from[1] },
      { row: target.position[0], col: target.position[1] },
      occupied,
      active.movement_remaining_ft,
      targeting.rangeFt,
    );
    const targetPoint = { row: target.position[0], col: target.position[1] };
    const targetCoveredByAction = getTargetingCells(
      tacticalGrid,
      { row: from[0], col: from[1] },
      targetPoint,
      targeting,
    ).some((cell) => cell.row === targetPoint.row && cell.col === targetPoint.col);
    if (plan.spentFt <= 0) {
      if (targetCoveredByAction) {
        setLastAiMove(`${active.display_name}已在${target.fighter.display_name}的合法技能范围内，保留剩余移动 ${active.movement_remaining_ft} 尺。`);
      } else if (active.movement_remaining_ft > 0) {
        // Being inside the numeric range is not enough for a cone, line, cube,
        // or a target behind a wall. Search for a destination where the exact
        // action template covers the target, then spend movement toward it.
        const approachPlan = planTargetingPath(
          tacticalGrid,
          { row: from[0], col: from[1] },
          targetPoint,
          occupied,
          active.movement_remaining_ft,
          targeting,
        );
        if (approachPlan.spentFt > 0) {
          setLastAiMove(`${active.display_name}当前距离虽在数值范围内，但尚未覆盖合法技能模板；正寻找视线/范围位置，移动 ${approachPlan.spentFt} 尺。`);
          void commitMove(active, approachPlan, true);
        } else {
          setLastAiMove(`${active.display_name}无法在当前地图上建立该技能的合法范围或视线，结束本回合。`);
          void commitMove(active, plan, true, true);
        }
      }
      return;
    }
    setLastAiMove(`${active.display_name}按规则向${target.fighter.display_name}寻路移动 ${plan.spentFt} 尺；剩余 ${Math.max(0, active.movement_remaining_ft - plan.spentFt)} 尺。`);
    void commitMove(active, plan, true);
  }, [activeFighterId, automateEnemies, automationPlanKey, commitMove, fighters, movingFighterId, onEndTurn, positions, tacticalGrid, targeting, targetingActorId, turnKey]);
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
  const activePositionTuple = targetingSourceId ? positions[targetingSourceId] : null;
  const activePosition = useMemo(
    () => activePositionTuple
      ? { row: activePositionTuple[0], col: activePositionTuple[1] }
      : null,
    [activePositionTuple],
  );
  useEffect(() => {
    if (!automateEnemies || !targeting || (!targeting.originSelf && targeting.rangeFt <= 0) || !activePosition || !activeFighterId) return;
    if (targetingActorId && targetingActorId !== activeFighterId) return;
    const active = fighters.find((fighter) => fighter.id === activeFighterId);
    if (
      !active
      || !isEnemyAiControlledCombatant(active.entity_type, active.snapshot_json)
    ) return;
    // Keep the visual aim point in lockstep with the command console's AI
    // target selection.  Player-controlled summons are valid enemy targets
    // too; limiting this to entity_type=character makes the AI choose a
    // summon while the grid still paints the player, leaving validTargetIds
    // without the chosen target and the turn waiting forever.
    const playerTargets = fighters.filter((fighter) => (
      fighter.hp > 0
      && (
        fighter.entity_type === "character"
        || fighter.snapshot_json.controller === "player"
      )
      && positions[fighter.id]
    ));
    const selectedTarget = chooseEnemyTarget(playerTargets, "standard");
    const target = selectedTarget ? positions[selectedTarget.id] : undefined;
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
    targetingActorId,
    turnKey,
  ]);
  const areaCells = useMemo(
    () => targeting && activePosition && (aimPoint || targeting.originSelf)
      ? getTargetingCells(tacticalGrid, activePosition, aimPoint ?? activePosition, targeting)
      : [],
    [activePosition, aimPoint, tacticalGrid, targeting],
  );
  const areaKeys = useMemo(
    () => new Set(areaCells.map((cell) => `${cell.row}:${cell.col}`)),
    [areaCells],
  );
  const elevationAtPoint = useCallback((point: GridPoint, targetElevationFt: number | null): TargetingElevationResult => {
    if (!targeting || !activePosition) {
      return { applies: false, valid: true, status: "not_applicable" };
    }
    return evaluateTargetingElevation(
      tacticalGrid,
      activePosition,
      targeting.shape === "single" ? point : aimPoint ?? activePosition,
      point,
      targeting,
      targetingOriginElevationFt,
      targetElevationFt,
    );
  }, [activePosition, aimPoint, tacticalGrid, targeting, targetingOriginElevationFt]);
  const fogPreviewKeys = useMemo(() => {
    if (!fogPreview) return new Set<string>();
    const playerPositions = fighters
      .filter((fighter) => fighter.entity_type === "character")
      .map((fighter) => positions[fighter.id])
      .filter((position): position is [number, number] => Boolean(position));
    if (!playerPositions.length) {
      return new Set(
        Array.from({ length: width * height }, (_, index) => {
          const row = Math.floor(index / width) + 1;
          const col = index % width + 1;
          return `${row}:${col}`;
        }),
      );
    }
    return new Set(
      Array.from({ length: width * height }, (_, index) => {
        const row = Math.floor(index / width) + 1;
        const col = index % width + 1;
        const visible = playerPositions.some(([anchorRow, anchorCol]) => (
          gridDistanceFt(
            { row: anchorRow, col: anchorCol },
            { row, col },
            tacticalGrid.cell_size_ft,
          ) <= 8 * tacticalGrid.cell_size_ft
          && hasLineOfSight(tacticalGrid, { row: anchorRow, col: anchorCol }, { row, col })
        ));
        return visible ? null : `${row}:${col}`;
      }).filter((key): key is string => key !== null),
    );
  }, [fighters, fogPreview, height, positions, tacticalGrid, width]);
  useEffect(() => {
    if (!targeting || !activePosition) {
      onTargetValidityChange({
        anchorPoint: null,
        horizontalTargetIds: new Set(),
        validTargetIds: new Set(),
        missingElevationTargetIds: new Set(),
      });
      return;
    }
    const horizontalTargetIds = new Set<string>();
    const validTargetIds = new Set<string>();
    const missingElevationTargetIds = new Set<string>();
    fighters.forEach((fighter) => {
      if (fighter.id === targetingSourceId || fighter.hp <= 0) return;
      const position = positions[fighter.id];
      if (!position) return;
      const horizontallyCovered = targeting.shape === "single"
        ? isAimPointInRange(
          activePosition,
          { row: position[0], col: position[1] },
          targeting.rangeFt,
          tacticalGrid.cell_size_ft,
        ) && hasLineOfSight(
          tacticalGrid,
          activePosition,
          { row: position[0], col: position[1] },
        )
        : areaKeys.has(`${position[0]}:${position[1]}`);
      if (!horizontallyCovered) return;
      horizontalTargetIds.add(fighter.id);
      const elevation = elevationAtPoint(
        { row: position[0], col: position[1] },
        combatantElevationFt(fighter),
      );
      if (elevation.valid) {
        validTargetIds.add(fighter.id);
      } else if (
        elevation.status === "missing_target_elevation"
        || elevation.status === "missing_origin_elevation"
      ) {
        missingElevationTargetIds.add(fighter.id);
      }
    });
    onTargetValidityChange({
      anchorPoint: aimPoint ?? (targeting.originSelf ? activePosition : null),
      horizontalTargetIds,
      validTargetIds,
      missingElevationTargetIds,
    });
  }, [
    activePosition,
    aimPoint,
    areaKeys,
    fighters,
    onTargetValidityChange,
    positions,
    tacticalGrid,
    targeting,
    elevationAtPoint,
    targetingOriginElevationFt,
    targetingSourceId,
  ]);
  const tokenAt = (row: number, col: number) => fighters.find((fighter) => {
    const position = positions[fighter.id];
    const elevationFt = combatantElevationFt(fighter);
    return position?.[0] === row
      && position[1] === col
      && (elevationLayer === "unknown" ? elevationFt === null : elevationFt === elevationLayer);
  });
  if (!grid) {
    return (
      <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/50 p-4 text-sm text-stone-400">
        正在读取当前 Scene 的持久化地图；地图加载完成后才会显示战斗网格。
      </div>
    );
  }
  return (
    <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/50 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-parchment-100">战斗场景 · {tacticalGrid.theme}</span>
        <span className="text-2xs text-stone-500">每格 {tacticalGrid.cell_size_ft} 尺 · 地图直接来自当前场景 · 单位按双方出生区布置</span>
        {interactionMode === "move" && selected === activeFighterId ? (
          <Badge tone="ok">绿色范围：本回合剩余可移动区域</Badge>
        ) : null}
        {targeting ? <Badge tone="ai">施法指示：{targeting.label}{targeting.heightFt ? ` · 高度 ${targeting.heightFt}尺` : ""}{targeting.anchorHeightFt !== undefined ? ` · 锚点 ${targeting.anchorHeightFt}尺` : ""}</Badge> : null}
        <div aria-label="地图高度层" className="flex flex-wrap items-center gap-1 rounded border border-ink-700 bg-ink-950/60 p-1">
          <span className="px-1 text-2xs text-stone-500">高度层</span>
          {elevationLayers.map((layer) => (
            <button
              aria-pressed={elevationLayer === layer}
              className={`rounded px-1.5 py-0.5 text-2xs ${elevationLayer === layer ? "bg-violet-700 text-white" : "text-stone-400 hover:bg-ink-800"}`}
              key={layer}
              onClick={() => setElevationLayer(layer)}
              type="button"
            >
              {layer}尺
            </button>
          ))}
          {hasUnknownElevation ? (
            <button
              aria-pressed={elevationLayer === "unknown"}
              className={`rounded px-1.5 py-0.5 text-2xs ${elevationLayer === "unknown" ? "bg-amber-700 text-white" : "text-stone-400 hover:bg-ink-800"}`}
              onClick={() => setElevationLayer("unknown")}
              type="button"
            >
              未记录
            </button>
          ) : null}
        </div>
        <button
          className={`rounded border px-2 py-1 text-2xs ${fogPreview ? "border-violet-500 bg-violet-950/70 text-violet-100" : "border-ink-700 text-stone-400"}`}
          onClick={() => setFogPreview((current) => !current)}
          type="button"
        >
          战争迷雾：预览{fogPreview ? "开启" : "关闭"}
        </button>
        <div className="flex rounded border border-ink-700 p-0.5">
          <button className={`rounded px-2 py-1 text-2xs ${interactionMode === "move" ? "bg-ember-700 text-white" : "text-stone-500"}`} onClick={() => setInteractionMode("move")} type="button">移动</button>
          <button className={`rounded px-2 py-1 text-2xs ${interactionMode === "target" ? "bg-sky-700 text-white" : "text-stone-500"}`} disabled={!targeting} onClick={() => setInteractionMode("target")} type="button">技能范围</button>
        </div>
        <Button disabled={endingTurn || !activeFighterId} loading={endingTurn} onClick={onEndTurn} size="sm" variant="primary">结束回合</Button>
        {selected ? <span className="ml-auto text-2xs text-ember-300">已选：{fighters.find((fighter) => fighter.id === selected)?.display_name}</span> : null}
      </div>
      {lastAiMove ? <p className="mb-2 mt-0 rounded border border-red-900/50 bg-red-950/10 px-2 py-1 text-2xs text-red-200">{lastAiMove}</p> : null}
      {targetingMessage ? <p className="mb-2 mt-0 rounded border border-sky-800/50 bg-sky-950/15 px-2 py-1 text-2xs text-sky-200">{targetingMessage}</p> : null}
      <div className="overflow-auto rounded border border-ink-700 bg-ink-950 p-2">
      <div className="grid w-max gap-px bg-ink-700" style={{ gridTemplateColumns: `repeat(${width}, minmax(28px, 48px))` }}>
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
            targeting.originSelf ? (targeting.sizeFt ?? tacticalGrid.cell_size_ft) : targeting.rangeFt,
            tacticalGrid.cell_size_ft,
          ) && hasLineOfSight(tacticalGrid, activePosition, point));
          const horizontallyAffected = areaKeys.has(`${rowNumber}:${colNumber}`);
          const layerElevation = elevationLayer === "unknown" ? null : elevationLayer;
          const layerElevationResult = elevationAtPoint(point, layerElevation);
          const affected = horizontallyAffected && layerElevationResult.valid;
          const fogged = fogPreviewKeys.has(`${rowNumber}:${colNumber}`);
          const terrainClass = fogged
            ? "bg-black border-black/90"
            : terrainCellClass(sceneCell, tacticalGrid.theme);
          const isVoid = isMapVoidCell(sceneCell);
          const isDoor = sceneCell?.kind === "door";
          const doorOrientation = isDoor
            ? getDoorOrientation(tacticalGrid.cells, rowNumber, colNumber)
            : null;
          return (
            <button
              className={`relative aspect-square border border-ink-800 text-[9px] transition duration-200 ${terrainClass} ${inCastRange && !blocked && interactionMode === "target" ? "bg-sky-950/60 ring-1 ring-inset ring-sky-500/50" : ""} ${affected && !blocked && interactionMode === "target" ? "!bg-fuchsia-900/70 !ring-2 !ring-inset !ring-fuchsia-400/80" : ""} ${aimPoint?.row === rowNumber && aimPoint.col === colNumber ? "outline outline-2 outline-amber-300" : ""} ${canMove && interactionMode === "move" ? "bg-emerald-950/75 ring-1 ring-inset ring-emerald-400/75 hover:bg-emerald-950/60" : ""}`}
              data-grid-col={colNumber}
              data-grid-row={rowNumber}
              data-token-id={fighter?.id}
              disabled={fogged}
              key={`${rowNumber}-${colNumber}`}
              onClick={() => {
                if (interactionMode === "target" && targeting && activePosition && activeFighterId) {
                  if (!inCastRange || blocked) {
                    setTargetingMessage(
                      !hasLineOfSight(tacticalGrid, activePosition, point)
                        ? `该格被墙体或硬遮挡阻断，无法建立视线。`
                        : `该格不在「${targeting.label}」的施法距离内，不能作为目标点。`,
                    );
                    return;
                  }
                  setAimPoint(point);
                  const affectedNow = getTargetingCells(tacticalGrid, activePosition, point, targeting);
                  const verticalNow = evaluateTargetingElevation(
                    tacticalGrid,
                    activePosition,
                    point,
                    point,
                    targeting,
                    targetingOriginElevationFt,
                    combatantElevationFt(fighter),
                  );
                  if (fighter && fighter.id !== targetingSourceId) {
                    if (!verticalNow.valid) {
                      setTargetingMessage(targetingElevationMessage(fighter, verticalNow));
                    } else if (affectedNow.some((cell) => cell.row === rowNumber && cell.col === colNumber)) {
                      onTargetSelect(fighter.id);
                      setSelected(fighter.id);
                      setTargetingMessage(`${fighter.display_name}位于合法范围内，已选为目标（高度层 ${elevationLayerLabel(elevationLayer)}）。`);
                    } else {
                      setTargetingMessage(`${fighter.display_name}不在当前技能的实际影响范围内。`);
                    }
                  } else {
                    setTargetingMessage(`已选择范围中心（${rowNumber}, ${colNumber}）；紫色区域会按当前 ${elevationLayerLabel(elevationLayer)} 与动作高度显示。`);
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
              title={fogged
                ? "战争迷雾：玩家尚未探索"
                : canMove && manualPlan
                ? `可移动到这里 · 消耗 ${manualPlan.spentFt} 尺（${manualPlan.path.length} 格）`
                : sceneCell?.label ?? (moveDistance === null ? "选择一个单位" : `${moveDistance} 尺`)}
              type="button"
            >
              {isDoor ? (
                <>
                  <span
                    aria-hidden
                    className={`absolute rounded bg-amber-400 shadow-[0_0_6px_rgba(251,191,36,.85)] ${
                      doorOrientation === "vertical"
                        ? "inset-y-1 left-1/2 w-1 -translate-x-1/2"
                        : "inset-x-1 top-1/2 h-1 -translate-y-1/2"
                    }`}
                  />
                  <span className="absolute right-0 top-0 rounded-bl bg-amber-500 px-0.5 font-bold text-ink-950">门</span>
                </>
              ) : null}
              {!fighter && shouldShowTerrainLabel(sceneCell) && !isVoid && !isDoor ? <span className="absolute inset-x-0 bottom-0 truncate px-0.5 text-[8px] text-stone-500">{sceneCell?.label?.slice(0, 5)}</span> : null}
              {fighter ? <span className={`flex h-full flex-col items-center justify-center rounded-full px-1 text-center leading-none transition duration-300 ${impactFighterId === fighter.id ? "scale-110 bg-red-500 text-white ring-4 ring-red-300/80" : selected === fighter.id && fighter.id !== activeFighterId ? "bg-emerald-400 text-ink-950 ring-4 ring-emerald-300/70" : fighter.entity_type === "monster" ? "bg-red-500/30 text-red-100" : fighter.entity_type === "npc" ? "bg-violet-500/25 text-violet-100" : "bg-amber-500/35 text-amber-100"}`}><span>{fighter.display_name.slice(0, 4)}</span><span className="mt-0.5 text-[7px] opacity-80">{elevationLayerLabel(elevationLayer)}</span></span> : null}
              {fogged ? <span aria-hidden className="pointer-events-none absolute inset-0 bg-black/95 shadow-[inset_0_0_10px_rgba(0,0,0,.95)]" /> : null}
            </button>
          );
        }))}
      </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-stone-500">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-violet-500/80" />单位</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-emerald-900" />掩体</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-stone-700" />墙体</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded border border-emerald-400 bg-emerald-900" />本回合可移动范围</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded border border-sky-400" />施法距离</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-fuchsia-700 ring-1 ring-fuchsia-400" />实际影响范围</span>
        <span>当前显示高度层：{elevationLayerLabel(elevationLayer)}；切换层可查看同一格的不同单位，带高度的区域会在不相交楼层隐藏紫色预览。</span>
        {fogPreview ? <span><i className="mr-1 inline-block h-2 w-2 rounded bg-black ring-1 ring-violet-400" />战争迷雾预览：玩家视野外</span> : null}
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
    // Automatic enemy turns are opt-in until the action has passed the
    // compiler quality gate. A missing preference must never imply consent
    // to guessed monster values or ranges.
    () => localStorage.getItem(autoEnemiesStorageKey) === "true",
  );
  const [xpOverride, setXpOverride] = useState("");
  const [goldPerCharacter, setGoldPerCharacter] = useState("0");
  const [lootRecipientId, setLootRecipientId] = useState("");
  const [lootName, setLootName] = useState("");
  const [lootQuantity, setLootQuantity] = useState("1");
  const [lootWeight, setLootWeight] = useState("0");
  const [lootPriceGp, setLootPriceGp] = useState("0");
  const [targetingRange, setTargetingRange] = useState<CombatTargeting | null>(null);
  const [targetingActorId, setTargetingActorId] = useState<string | null>(null);
  const [selectedMapTargetId, setSelectedMapTargetId] = useState("");
  const [targetingValidity, setTargetingValidity] = useState<CombatTargetingValidity>({
    anchorPoint: null,
    horizontalTargetIds: new Set(),
    validTargetIds: new Set(),
    missingElevationTargetIds: new Set(),
  });
  const [automaticMovementPending, setAutomaticMovementPending] = useState(false);
  const [expandedFighterId, setExpandedFighterId] = useState<string | null>(null);
  const [resetConfirmation, setResetConfirmation] = useState(false);
  const [archiveConfirmation, setArchiveConfirmation] = useState(false);
  const [summonCompanionId, setSummonCompanionId] = useState("");
  const [summonCount, setSummonCount] = useState("1");
  const [summonController, setSummonController] = useState<"dm" | "player">("dm");
  const [summonDisposition, setSummonDisposition] = useState<"enemy" | "ally">("enemy");
  const [summonEnemyAiMode, setSummonEnemyAiMode] = useState<"dm_only" | "basic">("basic");
  const [resetGeneration, setResetGeneration] = useState(0);
  const [effectSavePrompts, setEffectSavePrompts] = useState<EffectSavePrompt[]>([]);
  const [effectSaveRolls, setEffectSaveRolls] = useState<Record<string, string>>({});
  const [resumeMonsterSequence, setResumeMonsterSequence] = useState<{
    sequenceId: string;
    nextStep: number;
  } | null>(null);
  const nextTurnInFlight = useRef(false);
  const updateTargetingValidity = useCallback((next: CombatTargetingValidity) => {
    setTargetingValidity((current) => {
      const keyFor = (value: CombatTargetingValidity) => [
        value.anchorPoint ? `${value.anchorPoint.row}:${value.anchorPoint.col}` : "",
        [...value.horizontalTargetIds].sort().join("|"),
        [...value.validTargetIds].sort().join("|"),
        [...value.missingElevationTargetIds].sort().join("|"),
      ].join("/");
      return keyFor(current) === keyFor(next) ? current : next;
    });
  }, []);
  const [settlementPreview, setSettlementPreview] = useState<{
    preview: CombatSettlementPreview;
    command: CombatSettlementCommand;
  } | null>(null);
  useEffect(() => {
    localStorage.setItem(autoEnemiesStorageKey, String(autoEnemies));
  }, [autoEnemies, autoEnemiesStorageKey]);
  useEffect(() => {
    setResumeMonsterSequence(null);
  }, [combat.id, combat.current_turn_index]);
  const fighters = useQuery({
    queryKey: ["combatants", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatants(campaignId, combat.id, signal),
    refetchInterval: combat.status === "active" ? 15_000 : false,
  });
  const combatActions = useQuery({
    queryKey: ["combat-actions", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatActions(campaignId, combat.id, signal),
    refetchInterval: combat.status === "active" ? 15_000 : false,
  });
  const pendingPlayerRolls = (combatActions.data ?? []).filter(
    (action) => action.action_type === "player_roll_prompt" && action.status === "previewed",
  );
  const hasPendingPlayerRoll = pendingPlayerRolls.length > 0;
  const pendingConcentrationPrompts = useMemo(
    () => readConcentrationPrompts(combatActions.data ?? []),
    [combatActions.data],
  );
  const hasPendingConcentrationPrompt = pendingConcentrationPrompts.length > 0;
  const concentrationPromptByTarget = useMemo(
    () => new Map(
      pendingConcentrationPrompts.map((prompt) => [prompt.targetCombatantId, prompt]),
    ),
    [pendingConcentrationPrompts],
  );
  const persistedEffectSavePrompts = useMemo(
    () => readEffectSavePrompts(
      (combatActions.data ?? [])
        .filter((action) => action.action_type === "effect_save_prompt" && action.status === "previewed")
        .map((action) => action.request_json),
    ),
    [combatActions.data],
  );
  const combatEffects = useQuery({
    queryKey: ["combat-effects", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatEffects(campaignId, combat.id, signal),
    refetchInterval: combat.status === "active" ? 15_000 : false,
  });
  const activeUntilSaveEffects = useMemo(
    () => (combatEffects.data ?? []).filter(isActiveUntilSaveEffect),
    [combatEffects.data],
  );
  // A turn-boundary prompt is ephemeral, but the underlying until-save effect
  // is persisted.  Keep a local prompt only while it is still active; after a
  // reload/poll the separate persisted-status panel below can explain the
  // state without inventing a new, out-of-window roll request.
  useEffect(() => {
    const activeEffectIds = new Set(activeUntilSaveEffects.map((effect) => effect.id));
    setEffectSavePrompts((current) => {
      const next = [...current, ...persistedEffectSavePrompts].filter((prompt, index, all) => (
        activeEffectIds.has(prompt.effect_id)
        && all.findIndex((candidate) => candidate.effect_id === prompt.effect_id) === index
      ));
      return next.length === current.length ? current : next;
    });
    setEffectSaveRolls((current) => {
      const entries = Object.entries(current).filter(([effectId]) => activeEffectIds.has(effectId));
      return entries.length === Object.keys(current).length ? current : Object.fromEntries(entries);
    });
  }, [activeUntilSaveEffects, persistedEffectSavePrompts]);
  const companions = useQuery({
    queryKey: ["companions", campaignId],
    queryFn: ({ signal }) => listCompanions(campaignId, undefined, signal),
  });
  const endCondition = useQuery({
    queryKey: ["combat-end-condition", campaignId, combat.id],
    queryFn: ({ signal }) => getCombatEndCondition(campaignId, combat.id, signal),
    enabled: combat.status === "active",
    refetchInterval: combat.status === "active" ? 15_000 : false,
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
      setTargetingValidity({
        anchorPoint: null,
        horizontalTargetIds: new Set(),
        validTargetIds: new Set(),
        missingElevationTargetIds: new Set(),
      });
      setTargetingRange(null);
      setTargetingActorId(null);
      setEffectSavePrompts([]);
      setEffectSaveRolls({});
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
    onSuccess: async (result) => {
      setEffectSavePrompts(readEffectSavePrompts(result.effect_prompts));
      invalidate();
      // Keep the AI gate closed until both the turn cursor and the newly
      // active combatant snapshot have been refetched.  Without this barrier
      // the console can see the new active unit while still holding its old
      // combatant version, producing an immediate version conflict.
      await Promise.all([
        client.refetchQueries({ queryKey: ["combats", campaignId], type: "active" }),
        client.refetchQueries({ queryKey: ["combatants", campaignId, combat.id], type: "active" }),
      ]);
      showToast(result.expiration_prompts.length > 0
        ? `回合已结束；有 ${result.expiration_prompts.length} 个效果等待 DM 确认结束`
        : result.active_combatant
          ? `第 ${result.combat.round_number} 轮：轮到 ${result.active_combatant.display_name}`
          : "回合已结束");
    },
    onError: (error) => showToast(
      error instanceof Error ? error.message : "回合推进失败，请刷新战斗状态",
      "error",
    ),
  });
  const confirmEffectSave = useMutation({
    mutationFn: (prompt: { effect_id: string; target_combatant_id: string; target_version: number; roll_total: number }) =>
      confirmCombatEffectSave(campaignId, combat.id, prompt.effect_id, {
        target_combatant_id: prompt.target_combatant_id,
        target_version: prompt.target_version,
        roll_total: prompt.roll_total,
      }),
    onSuccess: (result) => {
      setEffectSavePrompts((current) => current.filter((prompt) => prompt.effect_id !== result.effect.id));
      invalidate();
      showToast(result.success ? "重复豁免成功，状态已结束" : "重复豁免失败，状态继续");
    },
    onError: () => showToast("状态重复豁免确认失败，请刷新战斗状态", "error"),
  });
  const advanceTurnIfIdle = useCallback(() => {
    if (hasPendingPlayerRoll || hasPendingConcentrationPrompt || nextTurn.isPending || nextTurnInFlight.current) return;
    nextTurnInFlight.current = true;
    nextTurn.mutate(undefined, {
      onSettled: () => {
        nextTurnInFlight.current = false;
      },
    });
  }, [hasPendingConcentrationPrompt, hasPendingPlayerRoll, nextTurn]);
  const ordered = [...(fighters.data ?? [])].filter((fighter) => fighter.is_active).sort((a, b) => b.initiative - a.initiative || a.display_name.localeCompare(b.display_name));
  const pendingAdvancedPlayerRolls = pendingPlayerRolls.flatMap((action) => {
    const request = action.request_json;
    const summary = advancedActionPendingRollSummary({
      actorName: ordered.find((fighter) => fighter.id === action.actor_combatant_id)?.display_name,
      actionName: request.action_name,
      actionCost: request.action_cost,
      legendaryCost: request.legendary_cost,
      legendaryPoolMax: request.legendary_pool_max,
      reactionTrigger: request.reaction_trigger,
    });
    return summary ? [{ id: action.id, summary }] : [];
  });
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
  const addSummon = useMutation({
    mutationFn: () => {
      const companion = (companions.data ?? []).find((item) => item.id === summonCompanionId);
      if (!companion) throw new Error("请选择召唤物模板");
      return addCombatSummon(campaignId, combat.id, {
        companion_id: companion.id,
        count: Math.max(1, Math.min(20, Number(summonCount) || 1)),
        controller: summonController,
        owner_character_id: summonController === "player" ? companion.owner_character_id : undefined,
        disposition: summonDisposition,
        enemy_ai_mode: summonController === "dm" && summonDisposition === "enemy"
          ? summonEnemyAiMode
          : "dm_only",
        source_combatant_id: summonController === "player" ? activeFighter?.id : undefined,
      });
    },
    onSuccess: (result) => {
      invalidate();
      setSummonCompanionId("");
      showToast(`${result.combatants?.length ?? 1} 个召唤单位已加入先攻轨道`);
    },
    onError: (error) => showToast(error instanceof Error ? error.message : "召唤物加入战斗失败", "error"),
  });
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
          <div className="mt-3 rounded border border-violet-800/60 bg-violet-950/15 p-3">
            <strong className="text-xs text-violet-100">召唤物：使用已有战斗模板加入先攻</strong>
            <p className="mb-2 mt-1 text-2xs text-stone-500">法师之手等非生物效果只显示召唤积木，不会凭空生成 HP/先攻；选择有完整模板的伙伴后才会建立战斗单位。</p>
            <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_8rem_8rem_8rem_auto]">
              {(companions.data ?? []).length > 0 ? (
                <select aria-label="召唤物模板" className={inputCls} onChange={(event) => setSummonCompanionId(event.target.value)} value={summonCompanionId}>
                  <option value="">选择伙伴 / 召唤物模板</option>
                  {(companions.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.name} · HP {item.hp}/{item.max_hp} · AC {item.armor_class}</option>)}
                </select>
              ) : (
                <p className="mb-0 rounded border border-amber-800/50 bg-amber-950/15 px-3 py-2 text-2xs leading-5 text-amber-200 md:col-span-4">
                  当前战役还没有伙伴模板。请先在角色 / 伙伴管理中建立明确的 HP、AC、速度和动作模板；系统不会根据法术名称猜战斗数据。
                </p>
              )}
              <label className="text-2xs text-stone-500">数量<input aria-label="DM召唤数量" className={`${inputCls} mt-1`} max="20" min="1" onChange={(event) => setSummonCount(event.target.value)} type="number" value={summonCount} /></label>
              <select aria-label="召唤物控制方" className={inputCls} onChange={(event) => setSummonController(event.target.value as "dm" | "player")} value={summonController}>
                <option value="dm">DM / 敌方控制</option>
                <option value="player">玩家控制</option>
              </select>
              <select aria-label="召唤物阵营" className={inputCls} onChange={(event) => setSummonDisposition(event.target.value as "enemy" | "ally")} value={summonDisposition}>
                <option value="enemy">敌对</option>
                <option value="ally">友方</option>
              </select>
              <select
                aria-label="敌方召唤物 AI"
                className={inputCls}
                disabled={summonController !== "dm" || summonDisposition !== "enemy"}
                onChange={(event) => setSummonEnemyAiMode(event.target.value as "dm_only" | "basic")}
                value={summonEnemyAiMode}
              >
                <option value="basic">基础 AI</option>
                <option value="dm_only">DM 手动</option>
              </select>
              <Button disabled={!summonCompanionId || (summonController === "player" && !activeFighter)} loading={addSummon.isPending} onClick={() => addSummon.mutate()} type="button" variant="primary">加入战斗轮</Button>
            </div>
          </div>
        </>
      ) : null}
      <CombatLogPanel actions={combatActions.data ?? []} />
      {activeUntilSaveEffects.length > 0 ? (
        <section className="mt-3 rounded-lg border border-amber-800/60 bg-amber-950/10 p-3" data-testid="combat-until-save-status">
          <strong className="text-xs text-amber-200">持续状态 · 等待重复豁免</strong>
          <p className="mb-2 mt-1 text-2xs leading-5 text-stone-400">这些效果从持久化战斗状态恢复，因此刷新或轮询后仍会显示。它们只说明状态仍生效；只有目标回合边界返回具体豁免请求时，才会在下方开放确认输入。</p>
          <div className="grid gap-2 md:grid-cols-2">
            {activeUntilSaveEffects.map((effect) => {
              const target = ordered.find((fighter) => fighter.id === effect.target_combatant_id);
              return (
                <p className="m-0 rounded border border-amber-900/60 bg-ink-950/40 px-2 py-1.5 text-2xs text-stone-300" key={effect.id}>
                  <strong>{target?.display_name ?? "目标已离场"}</strong> · {effect.name} · {effect.save_ability} 豁免 DC {effect.save_dc} · 状态仍生效
                </p>
              );
            })}
          </div>
        </section>
      ) : null}
      {effectSavePrompts.length > 0 ? (
        <div className="mt-3 rounded-lg border border-amber-700/60 bg-amber-950/15 p-3">
          <strong className="text-xs text-amber-200">回合末重复豁免 · DM确认</strong>
          <p className="mb-2 mt-1 text-2xs text-stone-400">本轮已收到目标回合末的具体豁免请求。填写玩家实际总值；失败时状态继续生效，成功后才会结束。请求已写入战斗日志，刷新后仍会恢复，未结算前不能继续推进回合。</p>
          <div className="grid gap-2">
            {effectSavePrompts.map((prompt) => {
              const target = ordered.find((fighter) => fighter.id === prompt.target_combatant_id);
              const roll = effectSaveRolls[prompt.effect_id] ?? "";
              return (
                <div className="flex flex-wrap items-center gap-2 rounded border border-amber-900/60 bg-ink-950/40 px-2 py-1.5 text-2xs" key={prompt.effect_id}>
                  <span className="mr-auto text-stone-300">{prompt.summary ?? "状态重复豁免"} · {prompt.save_ability} DC {prompt.save_dc}{target ? ` · ${target.display_name}` : " · 目标已离场"}</span>
                  <input aria-label={`${prompt.effect_id} 回合末豁免`} className={`${inputCls} w-20`} min="-100" onChange={(event) => setEffectSaveRolls((current) => ({ ...current, [prompt.effect_id]: event.target.value }))} type="number" value={roll} />
                  <Button disabled={!target || !roll.trim() || !Number.isFinite(Number(roll)) || confirmEffectSave.isPending} loading={confirmEffectSave.isPending} onClick={() => { if (target) confirmEffectSave.mutate({ effect_id: prompt.effect_id, target_combatant_id: target.id, target_version: target.version, roll_total: Number(roll) }); }} size="sm" variant="primary">确认玩家实际豁免</Button>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
      {hasPendingConcentrationPrompt ? (
        <div className="mt-3 rounded-lg border border-amber-700/60 bg-amber-950/15 p-3" data-testid="combat-pending-concentration">
          <strong className="text-xs text-amber-200">专注豁免 · 战斗暂停</strong>
          <p className="mb-0 mt-1 text-2xs leading-5 text-stone-400">
            伤害已经写入战斗日志，但对应单位必须提交体质豁免后才能继续推进；请求已持久化，刷新页面不会丢失。
          </p>
          <ul className="mb-0 mt-2 grid gap-1 pl-4 text-2xs text-amber-100">
            {pendingConcentrationPrompts.map((prompt) => {
              const target = ordered.find((fighter) => fighter.id === prompt.targetCombatantId);
              return <li key={prompt.actionId}>{target?.display_name ?? "目标"} · 体质 DC {prompt.dc} · 请在对应先攻卡中输入最终豁免总值</li>;
            })}
          </ul>
        </div>
      ) : null}
      {hasPendingPlayerRoll ? (
        <div className="mt-3 rounded-lg border border-sky-700/60 bg-sky-950/20 px-3 py-2 text-xs text-sky-100" data-testid="combat-pending-player-rolls">
          <strong>玩家待掷骰 · 战斗暂停</strong>
          <p className="mb-0 mt-1 leading-5">请求已经创建，但玩家提交前不表示伤害、状态或后续回合已经完成；怪物行动队列会保持暂停。</p>
          {pendingAdvancedPlayerRolls.length > 0 ? (
            <ul className="mb-0 mt-2 grid gap-1 pl-4 text-2xs text-sky-50">
              {pendingAdvancedPlayerRolls.map((item) => <li key={item.id}>{item.summary}</li>)}
            </ul>
          ) : null}
        </div>
      ) : null}
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
            <details className="mb-3 rounded-lg border border-ink-700 bg-ink-950/40" open={hasPendingConcentrationPrompt || undefined}>
              <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-stone-300">DM状态调整与高级编辑</summary>
              <ol className="m-0 flex list-none flex-col gap-1.5 border-t border-ink-700 p-3">
                {ordered.map((fighter, index) => <CombatantRow campaignId={campaignId} character={candidates.find((candidate) => candidate.entityId === fighter.entity_id)?.character} concentrationPrompt={concentrationPromptByTarget.get(fighter.id)} combat={combat} combatants={ordered} current={combat.status === "active" && index === combat.current_turn_index} effects={(combatEffects.data ?? []).filter((effect) => effect.target_combatant_id === fighter.id && effect.status === "active")} fighter={fighter} key={fighter.id} />)}
              </ol>
            </details>
          ) : null}
          {ordered.length > 0 ? (
            <BattleGrid
              key={`${combat.id}:${resetGeneration}`}
              activeFighterId={activeFighter?.id ?? null}
              automateEnemies={autoEnemies && !hasPendingPlayerRoll && !hasPendingConcentrationPrompt}
              campaignId={campaignId}
              candidates={candidates}
              combatId={combat.id}
              endingTurn={nextTurn.isPending}
              fighters={ordered}
              grid={grid}
              onEndTurn={() => {
                advanceTurnIfIdle();
              }}
              onAutomationMovementChange={setAutomaticMovementPending}
              onTargetSelect={setSelectedMapTargetId}
              onTargetValidityChange={updateTargetingValidity}
              targetingActorId={targetingActorId}
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
              automationReady={
                !hasPendingPlayerRoll
                && !hasPendingConcentrationPrompt
                && !nextTurn.isPending
                && !automaticMovementPending
              }
              campaignId={campaignId}
              combatId={combat.id}
              fighters={ordered}
              onAutoEnemiesChange={setAutoEnemies}
              onEnemyTurnComplete={() => {
                advanceTurnIfIdle();
              }}
              resumeMonsterSequence={resumeMonsterSequence}
              onRangeChange={(range, actorId) => {
                setTargetingRange(range);
                setTargetingActorId(range ? actorId ?? activeFighter.id : null);
                setSelectedMapTargetId("");
              }}
              onTargetChange={setSelectedMapTargetId}
              selectedTargetId={selectedMapTargetId}
              targetingValidity={targetingValidity}
              turnKey={`${combat.round_number}:${combat.current_turn_index}:${activeFighter.id}`}
            />
          ) : (
            <p className="text-xs text-stone-500">当前没有可行动单位。</p>
          )}
          <PlayerRollPanel
            actions={combatActions.data ?? []}
            activeEnemy={activeFighter?.entity_type === "monster" ? activeFighter : undefined}
            automationEnabled={autoEnemies}
            campaignId={campaignId}
            combatId={combat.id}
            fighters={ordered}
            onResolved={(action) => {
              const request = action?.request_json ?? {};
              const sequenceId = typeof request.sequence_id === "string"
                ? request.sequence_id
                : null;
              const sequenceStep = Number(request.sequence_step);
              const sequenceSize = Number(request.sequence_size);
              if (
                autoEnemies
                && activeFighter?.entity_type !== "character"
                && sequenceId
                && Number.isInteger(sequenceStep)
                && Number.isInteger(sequenceSize)
                && sequenceStep + 1 < sequenceSize
              ) {
                setResumeMonsterSequence({ sequenceId, nextStep: sequenceStep + 1 });
                return;
              }
              setResumeMonsterSequence(null);
              if (autoEnemies && activeFighter?.entity_type !== "character") {
                advanceTurnIfIdle();
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
  const combats = useQuery({ queryKey: ["combats", campaignId], queryFn: ({ signal }) => listCombats(campaignId, signal), refetchInterval: 15_000 });
  const playerRoom = useQuery({
    queryKey: ["player-room-admin", campaignId],
    queryFn: ({ signal }) => getPlayerRoom(campaignId, signal),
    retry: false,
  });
  const scenes = useQuery({ queryKey: ["scenes", campaignId], queryFn: ({ signal }) => listScenes(campaignId, signal) });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const locations = useQuery({ queryKey: ["locations", campaignId], queryFn: ({ signal }) => listLocations(campaignId, signal) });
  const npcs = useQuery({ queryKey: ["npcs", campaignId], queryFn: ({ signal }) => listNpcs(campaignId, signal) });
  const monsters = useQuery({ queryKey: ["monsters", campaignId], queryFn: ({ signal }) => listMonsters(campaignId, signal) });
  const events = useQuery({ queryKey: ["events", campaignId], queryFn: ({ signal }) => listEvents(campaignId, signal) });
  const encounterAdjustments = useQuery({ queryKey: ["encounter-adjustments", campaignId], queryFn: ({ signal }) => listEncounterAdjustments(campaignId, undefined, signal) });
  const syncPlayerRoomToCombat = (combat: Combat | undefined): void => {
    if (!combat?.scene_id) return;
    void (async () => {
      let room = playerRoom.data;
      for (let attempt = 0; attempt < 2; attempt += 1) {
        try {
          room ??= await getPlayerRoom(campaignId);
          if (room.status !== "active") return;
          const result = await setPlayerRoomLiveState(
            campaignId,
            combat.scene_id,
            combat.id,
            room.version,
          );
          client.setQueryData(["player-room-admin", campaignId], result);
          return;
        } catch (error: unknown) {
          if (!isApiError(error, 409) || attempt === 1) return;
          room = undefined;
        }
      }
    })();
  };
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
      syncPlayerRoomToCombat(created);
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
  const persistentSceneGrid = useQuery({
    queryKey: ["scene-grid", campaignId, selectedCombatSceneId],
    queryFn: ({ signal }) => getSceneGrid(campaignId, selectedCombatSceneId ?? "", signal),
    enabled: Boolean(selectedCombatSceneId),
  });
  return (
    <div className="mx-auto max-w-[1500px] p-4 lg:p-6">
      <Panel eyebrow="遭遇" title="战斗辅助">
        <form className="grid gap-2 md:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => { event.preventDefault(); if (name.trim()) create.mutate(); }}>
          <input className={inputCls} onChange={(event) => setName(event.target.value)} placeholder="战斗名称，例如：城门伏击" value={name} />
          <select className={inputCls} onChange={(event) => setSceneId(event.target.value)} value={sceneId}><option value="">必须选择战斗场景</option>{scenes.data?.map((scene) => <option key={scene.id} value={scene.id}>{scene.name} · 共用 Scene 网格</option>)}</select>
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
                syncPlayerRoomToCombat(combats.data?.find((combat) => combat.id === event.target.value));
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
          const layers = persistentSceneGrid.data?.grid.layers_json as {
            theme?: string;
            cells?: SceneGrid["cells"];
          } | undefined;
          const layerCells = layers?.cells ?? [];
          const occupiedLayerCells = new Set(
            layerCells.map((cell) => `${cell.row}:${cell.col}`),
          );
          const objectCells: SceneGrid["cells"] = (persistentSceneGrid.data?.objects ?? [])
            .filter((item) => !occupiedLayerCells.has(`${item.row}:${item.col}`))
            .map((item) => ({
              row: item.row,
              col: item.col,
              kind: (
                item.object_type === "wall"
                  ? "wall"
                  : item.object_type === "door"
                    ? "door"
                    : item.object_type === "cover"
                      ? "cover"
                      : item.object_type === "trap"
                        ? "trap"
                        : item.object_type === "treasure"
                          ? "treasure"
                          : item.object_type === "portal"
                            ? "portal"
                            : item.object_type === "terrain"
                              ? "terrain"
                              : item.object_type === "light"
                                ? "light"
                                : "object"
              ),
              label: item.label,
            }));
          const serviceGrid: SceneGrid | null = persistentSceneGrid.data ? {
            width: persistentSceneGrid.data.grid.width,
            height: persistentSceneGrid.data.grid.height,
            cell_size_ft: persistentSceneGrid.data.grid.cell_size_ft,
            theme: layers?.theme ?? persistentSceneGrid.data.grid.public_description ?? scene?.name ?? "当前 Scene",
            cells: [...layerCells, ...objectCells],
          } : null;
          const storedGrid = scene ? readSceneGrid(scene.notes) : null;
          const sceneGrid = persistentSceneGrid.data
            ? serviceGrid
            : persistentSceneGrid.isLoading
              ? null
              : storedGrid ?? (scene
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
