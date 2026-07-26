import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactElement } from "react";

import {
  advanceCombatTurn, confirmCombatAction, confirmCombatEffect,
  confirmCombatSettlement, confirmCombatantDeath, confirmConcentrationCheck,
  confirmDeathSave, createCombat, createCombatant, deleteCombatant, endCombatEffect,
  getDeathSave, listCombatActions, listCombatEffects, listCombatants, listCombats,
  listEncounterAdjustments, listEvents, previewCombatAction,
  previewCombatSettlement, revertEncounterAdjustment, updateCombat, updateCombatant,
} from "../api/entities";
import type {
  CombatActionCommand, CombatEffectCommand, CombatSettlementCommand,
} from "../api/entities";
import { listCharacters, listNpcs, updateCharacter } from "../api/entities";
import { listMonsters, listScenes } from "../api/world";
import type {
  Combat, CombatActionPreview, CombatEffect, CombatSettlementPreview, Combatant,
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
    enabled: fighter.hp === 0,
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
      {fighter.hp === 0 ? (
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

function BattleGrid({ fighters, grid, candidates }: { fighters: Combatant[]; grid: SceneGrid | null; candidates: CombatCandidate[] }): ReactElement {
  const width = grid?.width ?? 12;
  const height = grid?.height ?? 8;
  const [positions, setPositions] = useState<Record<string, [number, number]>>({});
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    setPositions((current) => {
      const next = { ...current };
      fighters.forEach((fighter, index) => {
        if (!next[fighter.id]) next[fighter.id] = [Math.floor(index / 4) + 1, (index % 4) + 1];
      });
      return next;
    });
  }, [fighters]);
  const selectedPosition = selected ? positions[selected] : null;
  const selectedFighter = fighters.find((fighter) => fighter.id === selected);
  const selectedSpeed = candidates.find((candidate) => candidate.entityId === selectedFighter?.entity_id)?.speed ?? 30;
  const distance = (row: number, col: number) => selectedPosition ? (Math.abs(row - selectedPosition[0]) + Math.abs(col - selectedPosition[1])) * 5 : null;
  const tokenAt = (row: number, col: number) => fighters.find((fighter) => {
    const position = positions[fighter.id];
    return position?.[0] === row && position[1] === col;
  });
  return (
    <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/50 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-parchment-100">战斗场景网格</span>
        <span className="text-2xs text-stone-500">每格 5 尺 · 绿色方块为掩体 · 点击单位后点击目标格移动</span>
        {selected ? <span className="ml-auto text-2xs text-ember-300">已选：{fighters.find((fighter) => fighter.id === selected)?.display_name}</span> : null}
      </div>
      <div className="grid max-w-[720px] gap-px overflow-hidden rounded border border-ink-700 bg-ink-700" style={{ gridTemplateColumns: `repeat(${width}, minmax(0, 1fr))` }}>
        {Array.from({ length: height }, (_, row) => Array.from({ length: width }, (_, col) => {
          const rowNumber = row + 1;
          const colNumber = col + 1;
          const fighter = tokenAt(rowNumber, colNumber);
          const sceneCell = grid?.cells.find((cell) => cell.row === rowNumber && cell.col === colNumber);
          const blocked = sceneCell?.kind === "wall";
          const moveDistance = distance(rowNumber, colNumber);
          const canMove = Boolean(selected && !fighter && !blocked && moveDistance !== null && moveDistance <= selectedSpeed);
          const terrainClass = sceneCell?.kind === "wall" ? "bg-stone-700" : sceneCell?.kind === "cover" ? "bg-emerald-900/80" : sceneCell?.kind === "door" ? "bg-amber-800/80" : sceneCell?.kind === "object" ? "bg-violet-900/80" : "bg-ink-950/80";
          return (
            <button
              className={`relative aspect-square min-h-8 text-2xs transition-colors ${terrainClass} ${canMove ? "hover:bg-ember-500/30" : ""}`}
              key={`${rowNumber}-${colNumber}`}
              onClick={() => {
                if (fighter) setSelected(fighter.id);
                else if (canMove && selected) setPositions((current) => ({ ...current, [selected]: [rowNumber, colNumber] }));
              }}
              title={sceneCell?.label ?? (moveDistance === null ? "选择一个单位" : `${moveDistance} 尺`)}
              type="button"
            >
              {fighter ? <span className={`mx-auto flex h-6 w-6 items-center justify-center rounded-full text-2xs font-bold ${selected === fighter.id ? "bg-ember-400 text-ink-950" : "bg-violet-500/80 text-white"}`}>{fighter.display_name.slice(0, 1)}</span> : null}
              {!fighter && sceneCell ? <span className="text-stone-200">{sceneCell.kind === "wall" ? "■" : sceneCell.kind === "door" ? "门" : sceneCell.kind === "cover" ? "▦" : "◆"}</span> : null}
            </button>
          );
        }))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-stone-500">
        <span><i className="mr-1 inline-block h-2 w-2 rounded-full bg-violet-500/80" />单位</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-emerald-900" />掩体</span>
        <span><i className="mr-1 inline-block h-2 w-2 rounded bg-stone-700" />墙体</span>
        <span>当前单位移动上限：{selected ? `${selectedSpeed}尺（${Math.floor(selectedSpeed / 5)}格）` : "选择单位后显示"}</span>
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
  const [xpOverride, setXpOverride] = useState("");
  const [settlementPreview, setSettlementPreview] = useState<{
    preview: CombatSettlementPreview;
    command: CombatSettlementCommand;
  } | null>(null);
  const fighters = useQuery({
    queryKey: ["combatants", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatants(campaignId, combat.id, signal),
  });
  const combatActions = useQuery({
    queryKey: ["combat-actions", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatActions(campaignId, combat.id, signal),
  });
  const combatEffects = useQuery({
    queryKey: ["combat-effects", campaignId, combat.id],
    queryFn: ({ signal }) => listCombatEffects(campaignId, combat.id, signal),
  });
  const invalidate = () => {
    void client.invalidateQueries({ queryKey: ["combats", campaignId] });
    void client.invalidateQueries({ queryKey: ["combatants", campaignId, combat.id] });
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
      } : {},
      is_active: true,
    }),
    onSuccess: () => { setName(""); invalidate(); showToast("参与者已加入战斗"); },
    onError: () => showToast("添加参与者失败", "error"),
  });
  const update = useMutation({
    mutationFn: (payload: { status?: string; round_number?: number; current_turn_index?: number; difficulty?: Difficulty; base_xp?: number; difficulty_adjustments?: unknown[] }) =>
      updateCombat(campaignId, combat.id, payload, combat.version),
    onSuccess: () => { invalidate(); showToast("战斗进度已保存"); },
    onError: () => showToast("战斗进度保存失败", "error"),
  });
  const nextTurn = useMutation({
    mutationFn: () => advanceCombatTurn(campaignId, combat.id, combat.version),
    onSuccess: (result) => {
      invalidate();
      showToast(result.expiration_prompts.length > 0
        ? `回合已推进；有 ${result.expiration_prompts.length} 个效果等待 DM 确认结束`
        : result.active_combatant
          ? `第 ${result.combat.round_number} 轮：轮到 ${result.active_combatant.display_name}`
          : "回合已推进");
    },
    onError: () => showToast("回合推进失败，请刷新战斗状态", "error"),
  });
  const ordered = [...(fighters.data ?? [])].filter((fighter) => fighter.is_active).sort((a, b) => b.initiative - a.initiative || a.display_name.localeCompare(b.display_name));
  const playerCharacters = ordered
    .filter((fighter) => fighter.entity_type === "character" && fighter.entity_id)
    .map((fighter) => candidates.find((candidate) => candidate.entityType === "character" && candidate.entityId === fighter.entity_id)?.character)
    .filter((character): character is Character => Boolean(character));
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
      if (playerCharacters.length === 0 || xpPerCharacter <= 0) throw new Error("没有可发放的参与玩家或经验值");
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
    onSuccess: () => {
      setSettlementPreview(null);
      invalidate();
      void client.invalidateQueries({ queryKey: ["characters", campaignId] });
      showToast(`战斗已原子结算：每名参与玩家 ${xpPerCharacter} XP，并回写所选HP与持续状态`);
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
          <Button disabled={manualAdjustment.isPending} onClick={() => manualAdjustment.mutate(-1)} size="sm">DM 降一级</Button>
          <Button disabled={manualAdjustment.isPending} onClick={() => manualAdjustment.mutate(1)} size="sm">DM 升一级</Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Badge tone={combat.status === "active" ? "danger" : "neutral"}>{COMBAT_STATUS_LABELS[combat.status] ?? combat.status}</Badge>
        <div className="flex gap-2">
          <Button disabled={combat.status !== "active" || ordered.length === 0 || nextTurn.isPending} loading={nextTurn.isPending} onClick={() => nextTurn.mutate()} size="sm" variant="primary">下一回合</Button>
          <Button disabled={combat.status !== "active" || update.isPending} onClick={() => update.mutate({ status: "ended" })} size="sm">结束战斗</Button>
          {combat.status === "ended" && combat.scene_id ? <Button onClick={() => navigate("/game-table")} size="sm" variant="primary">返回游戏推进台</Button> : null}
        </div>
      </div>
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
      <div className="mt-3">
        {fighters.isLoading ? <LoadingBlock label="正在读取先攻列表…" /> : null}
        {fighters.isError ? <ErrorState error={fighters.error} onRetry={() => void fighters.refetch()} /> : null}
        {!fighters.isLoading && ordered.length === 0 ? <EmptyState title="尚无参与者" hint="录入先攻与 HP 后即可开始逐回合追踪。" /> : null}
        {ordered.length > 0 ? <ol className="m-0 flex list-none flex-col gap-1.5 p-0">{ordered.map((fighter, index) => <CombatantRow campaignId={campaignId} character={candidates.find((candidate) => candidate.entityId === fighter.entity_id)?.character} combat={combat} combatants={ordered} current={combat.status === "active" && index === combat.current_turn_index} effects={(combatEffects.data ?? []).filter((effect) => effect.target_combatant_id === fighter.id && effect.status === "active")} fighter={fighter} key={fighter.id} />)}</ol> : null}
      </div>
      {(combatActions.data?.length ?? 0) > 0 ? (
        <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950/50 p-3">
          <strong className="text-xs text-parchment-100">可审计战斗日志</strong>
          <ol className="mb-0 mt-2 max-h-48 space-y-1 overflow-y-auto pl-5 text-2xs text-stone-400">
            {[...(combatActions.data ?? [])].reverse().map((action) => (
              <li key={action.id}>
                <span className="text-stone-600">R{action.round_number} · T{action.turn_index + 1}</span>
                {" "}{action.summary}
                {action.explanation ? <span className="text-stone-600"> — {action.explanation}</span> : null}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {ordered.length > 0 ? <BattleGrid candidates={candidates} fighters={ordered} grid={grid} /> : null}
      {combat.status === "ended" ? (
        <div className="mt-4 rounded-lg border border-amber-800/50 bg-amber-950/10 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="mr-auto text-sm text-parchment-100">战斗原子结算</strong>
            <Badge tone={combat.xp_awarded ? "ok" : "warn"}>{combat.xp_awarded ? "已结算" : "等待预览与 DM 确认"}</Badge>
          </div>
          <p className="mb-2 mt-2 text-xs text-stone-400">参与玩家：{playerCharacters.map((character) => character.name).join("、") || "无"}。一次事务同时分配经验，并把参战实例的 HP 与持续状态回写角色卡；预览不会写入。</p>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-2xs text-stone-500">总 XP<input className={`${inputCls} mt-1 w-32`} disabled={combat.xp_awarded} min="0" onChange={(event) => setXpOverride(event.target.value)} type="number" value={xpOverride || String(combat.base_xp || monsterXp)} /></label>
            <span className="pb-2 text-xs text-ember-300">每名玩家 {xpPerCharacter} XP</span>
            <Button disabled={combat.xp_awarded || playerCharacters.length === 0 || xpPerCharacter <= 0} loading={previewSettlement.isPending} onClick={() => previewSettlement.mutate()}>生成结算预览</Button>
          </div>
          {settlementPreview ? (
            <div className="mt-3 rounded border border-amber-700/50 bg-ink-950/40 p-2">
              <strong className="text-xs text-amber-200">尚未写入：请核对以下变化</strong>
              <ul className="mb-2 mt-1 pl-4 text-2xs text-stone-300">
                {settlementPreview.preview.character_changes.map((change) => <li key={change.character_id}>{change.name}：HP {change.before.hp} → {change.after.hp}；XP +{change.xp_award}{change.conditions_to_add.length > 0 ? `；持续状态 ${change.conditions_to_add.join("、")}` : ""}</li>)}
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
  const combats = useQuery({ queryKey: ["combats", campaignId], queryFn: ({ signal }) => listCombats(campaignId, signal) });
  const scenes = useQuery({ queryKey: ["scenes", campaignId], queryFn: ({ signal }) => listScenes(campaignId, signal) });
  const characters = useQuery({ queryKey: ["characters", campaignId], queryFn: ({ signal }) => listCharacters(campaignId, signal) });
  const npcs = useQuery({ queryKey: ["npcs", campaignId], queryFn: ({ signal }) => listNpcs(campaignId, signal) });
  const monsters = useQuery({ queryKey: ["monsters", campaignId], queryFn: ({ signal }) => listMonsters(campaignId, signal) });
  const events = useQuery({ queryKey: ["events", campaignId], queryFn: ({ signal }) => listEvents(campaignId, signal) });
  const encounterAdjustments = useQuery({ queryKey: ["encounter-adjustments", campaignId], queryFn: ({ signal }) => listEncounterAdjustments(campaignId, undefined, signal) });
  const candidates: CombatCandidate[] = [
    ...(characters.data ?? []).map((entity: Character) => ({ key: `character:${entity.id}`, entityType: "character" as const, entityId: entity.id, name: entity.name, armorClass: entity.armor_class, hp: entity.hp, maxHp: entity.max_hp, dexterity: entity.ability_scores.dexterity ?? 10, speed: entity.speed, character: entity })),
    ...(npcs.data ?? []).map((entity: Npc) => ({ key: `npc:${entity.id}`, entityType: "npc" as const, entityId: entity.id, name: entity.name, armorClass: entity.armor_class, hp: entity.hp, maxHp: entity.max_hp, dexterity: entity.ability_scores.dexterity ?? 10, speed: entity.speed, challengeRating: entity.challenge_rating })),
    ...(monsters.data ?? []).map((entity: Monster) => ({ key: `monster:${entity.id}`, entityType: "monster" as const, entityId: entity.id, name: entity.name, armorClass: entity.armor_class, hp: entity.hp, maxHp: entity.max_hp, dexterity: entity.ability_scores.dexterity ?? 10, speed: entity.speed, challengeRating: entity.challenge_rating })),
  ];
  const create = useMutation({
    mutationFn: () => createCombat(campaignId, { name: name.trim(), scene_id: sceneId || null, status: "active" }),
    onSuccess: () => { setName(""); void client.invalidateQueries({ queryKey: ["combats", campaignId] }); showToast("战斗已创建并加载场景网格"); },
    onError: () => showToast("创建战斗失败", "error"),
  });
  return (
    <div className="mx-auto max-w-[1100px] p-4 lg:p-6">
      <Panel eyebrow="遭遇" title="战斗辅助">
        <form className="grid gap-2 md:grid-cols-[1fr_1fr_auto]" onSubmit={(event) => { event.preventDefault(); if (name.trim()) create.mutate(); }}>
          <input className={inputCls} onChange={(event) => setName(event.target.value)} placeholder="战斗名称，例如：城门伏击" value={name} />
          <select className={inputCls} onChange={(event) => setSceneId(event.target.value)} value={sceneId}><option value="">必须选择战斗场景</option>{scenes.data?.map((scene) => <option key={scene.id} value={scene.id}>{scene.name}{readSceneGrid(scene.notes) ? " · 有网格" : ""}</option>)}</select>
          <Button disabled={!name.trim() || !sceneId} loading={create.isPending} icon="plus" type="submit" variant="primary">创建战斗</Button>
        </form>
      </Panel>
      <div className="mt-4 flex flex-col gap-3">
        {combats.isLoading ? <Panel title="战斗"><LoadingBlock /></Panel> : null}
        {combats.isError ? <Panel title="战斗"><ErrorState error={combats.error} onRetry={() => void combats.refetch()} /></Panel> : null}
        {!combats.isLoading && !combats.isError && combats.data?.length === 0 ? <Panel title="战斗"><EmptyState title="暂无战斗" hint="创建战斗后可以追踪先攻、HP、轮次和当前回合。" /></Panel> : null}
        {combats.data?.map((combat) => {
          const scene = scenes.data?.find((item) => item.id === combat.scene_id);
          const sceneAdjustments = (events.data ?? [])
            .filter((event) => event.metadata_json.scene_id === combat.scene_id && Number(event.metadata_json.encounter_adjustment ?? 0) !== 0)
            .map((event) => {
              const rawReason = event.metadata_json.encounter_reason;
              return {
                shift: Number(event.metadata_json.encounter_adjustment ?? 0),
                reason: typeof rawReason === "string" ? rawReason : (event.description ?? event.title),
              };
            });
          const encounterConsequences = (encounterAdjustments.data ?? [])
            .filter((proposal) => proposal.status === "applied" && proposal.combat_id === combat.id);
          return <CombatCard campaignId={campaignId} combat={combat} candidates={candidates} encounterConsequences={encounterConsequences} grid={scene ? readSceneGrid(scene.notes) : null} key={combat.id} sceneAdjustments={sceneAdjustments} sceneName={scene?.name ?? null} />;
        })}
      </div>
    </div>
  );
}

export function CombatPage(): ReactElement {
  return <RequireCampaign>{(campaignId) => <CombatContent campaignId={campaignId} />}</RequireCampaign>;
}
