import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type ReactElement } from "react";

import {
  advanceCombatTurn,
  confirmCombatAction,
  createCombat,
  createCombatant,
  deleteCombatant,
  listCombatActions,
  listCombatants,
  listCombats,
  updateCombat,
  updateCombatant,
  type CombatActionCommand,
  type CombatantInput,
} from "../api/entities";
import { listCampaigns } from "../api/campaigns";
import { runAssistantTurn } from "../api/assistant";
import { listCharacters, listNpcs, listScenes } from "../api/entities";
import type { Combat, CombatAction, Combatant } from "../api/types";
import { RequireCampaign } from "../components/RequireCampaign";
import { SceneMap, type SceneMapToken } from "../components/SceneMap";
import { useCurrentCampaign } from "../hooks/appContexts";
import { useToast } from "../hooks/toastContext";
import { soundboard } from "../ui/soundboard";
import { Badge, Button, EmptyState, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls } from "../ui/styles";
import { formatDateTime } from "../ui/format";

const CONDITIONS_LIST = [
  { key: "prone", label: "倒地", icon: "🛌" },
  { key: "stunned", label: "震慑", icon: "💫" },
  { key: "blinded", label: "目盲", icon: "👁️" },
  { key: "paralyzed", label: "麻痹", icon: "⚡" },
  { key: "poisoned", label: "中毒", icon: "🧪" },
  { key: "unconscious", label: "昏迷", icon: "💤" },
  { key: "frightened", label: "恐惧", icon: "😱" },
  { key: "restrained", label: "束缚", icon: "🕸️" },
  { key: "charmed", label: "魅惑", icon: "💖" },
  { key: "invisible", label: "隐形", icon: "👻" },
  { key: "concentration", label: "专注", icon: "🔮" },
  { key: "dying", label: "濒死", icon: "💀" },
];

function QuickCombatCockpit({ campaignId }: { campaignId: string }): ReactElement {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { selectCampaign } = useCurrentCampaign();

  const [selectedCombatId, setSelectedCombatId] = useState<string>("");
  const [selectedCombatantId, setSelectedCombatantId] = useState<string>("");
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [showAddCombatantModal, setShowAddCombatantModal] = useState<boolean>(false);
  const [showNewCombatModal, setShowNewCombatModal] = useState<boolean>(false);

  // New combatant form
  const [newCombatantName, setNewCombatantName] = useState<string>("");
  const [newCombatantType, setNewCombatantType] = useState<"character" | "monster" | "npc">("monster");
  const [newCombatantHp, setNewCombatantHp] = useState<string>("12");
  const [newCombatantAc, setNewCombatantAc] = useState<string>("14");
  const [newCombatantInit, setNewCombatantInit] = useState<string>("10");

  // New combat form
  const [newCombatName, setNewCombatName] = useState<string>("遭遇战：" + new Date().toLocaleTimeString());

  // Quick Action form states
  const [actionTargetId, setActionTargetId] = useState<string>("");
  const [actionDamageAmount, setActionDamageAmount] = useState<string>("6");
  const [actionDamageType, setActionDamageType] = useState<string>("slashing");
  const [actionAttackRoll, setActionAttackRoll] = useState<string>("15");
  const [actionName, setActionName] = useState<string>("近战武器攻击");
  const [isCritical, setIsCritical] = useState<boolean>(false);

  // Dice Roller
  const [diceHistory, setDiceHistory] = useState<Array<{ id: string; formula: string; result: number; rolls: number[]; isCrit?: boolean; isFumble?: boolean }>>([]);
  const [customDiceMod, setCustomDiceMod] = useState<string>("3");

  // AI Guidance
  const [aiAnalysis, setAiAnalysis] = useState<string>("");
  const [aiNarrative, setAiNarrative] = useState<string>("");

  // Queries
  const campaignsQuery = useQuery({
    queryKey: ["campaigns"],
    queryFn: ({ signal }) => listCampaigns(signal),
  });

  const combatsQuery = useQuery({
    queryKey: ["combats", campaignId],
    queryFn: ({ signal }) => listCombats(campaignId, signal),
  });

  const activeCombat = useMemo(() => {
    const list = combatsQuery.data ?? [];
    if (selectedCombatId) return list.find((c) => c.id === selectedCombatId) ?? list[0] ?? null;
    return list.find((c) => c.status === "active") ?? list[0] ?? null;
  }, [combatsQuery.data, selectedCombatId]);

  const combatId = activeCombat?.id ?? "";

  const combatantsQuery = useQuery({
    queryKey: ["combatants", campaignId, combatId],
    queryFn: ({ signal }) => (combatId ? listCombatants(campaignId, combatId, signal) : Promise.resolve([])),
    enabled: Boolean(combatId),
    refetchInterval: 3000,
  });

  const actionsQuery = useQuery({
    queryKey: ["combat-actions", campaignId, combatId],
    queryFn: ({ signal }) => (combatId ? listCombatActions(campaignId, combatId, signal) : Promise.resolve([])),
    enabled: Boolean(combatId),
    refetchInterval: 3000,
  });

  const charactersQuery = useQuery({
    queryKey: ["characters", campaignId],
    queryFn: ({ signal }) => listCharacters(campaignId, signal),
  });

  const npcsQuery = useQuery({
    queryKey: ["npcs", campaignId],
    queryFn: ({ signal }) => listNpcs(campaignId, signal),
  });

  // Sorted combatants by initiative descending
  const sortedCombatants = useMemo(() => {
    const items = [...(combatantsQuery.data ?? [])];
    return items.sort((a, b) => (b.initiative ?? 0) - (a.initiative ?? 0));
  }, [combatantsQuery.data]);

  // Active turn combatant
  const currentCombatant = useMemo(() => {
    if (!sortedCombatants.length) return null;
    const activeIndex = (activeCombat?.active_combatant_index ?? 0) % sortedCombatants.length;
    return sortedCombatants[activeIndex] ?? sortedCombatants[0] ?? null;
  }, [sortedCombatants, activeCombat?.active_combatant_index]);

  const selectedTargetCombatant = useMemo(() => {
    return sortedCombatants.find((c) => c.id === (actionTargetId || selectedCombatantId)) ?? null;
  }, [sortedCombatants, actionTargetId, selectedCombatantId]);

  // Quick Preset Encounter Launcher
  const createPresetEncounterMutation = useMutation({
    mutationFn: async () => {
      const combat = await createCombat(campaignId, {
        name: "红落避难所前厅突袭",
        round_number: 1,
        status: "active",
      });

      // Add default party & monsters
      await createCombatant(campaignId, combat.id, {
        display_name: "圣骑士 瓦伦丁",
        entity_type: "character",
        hp: 28,
        max_hp: 28,
        armor_class: 18,
        initiative: 17,
        conditions: [],
        snapshot_json: { row: 3, col: 3 },
      });

      await createCombatant(campaignId, combat.id, {
        display_name: "游侠 艾拉",
        entity_type: "character",
        hp: 20,
        max_hp: 20,
        armor_class: 15,
        initiative: 15,
        conditions: [],
        snapshot_json: { row: 4, col: 2 },
      });

      await createCombatant(campaignId, combat.id, {
        display_name: "地精头目·裂齿",
        entity_type: "monster",
        hp: 21,
        max_hp: 21,
        armor_class: 15,
        initiative: 14,
        conditions: [],
        snapshot_json: { row: 3, col: 7 },
      });

      await createCombatant(campaignId, combat.id, {
        display_name: "地精射手 A",
        entity_type: "monster",
        hp: 7,
        max_hp: 7,
        armor_class: 13,
        initiative: 11,
        conditions: [],
        snapshot_json: { row: 2, col: 8 },
      });

      return combat;
    },
    onSuccess: (combat) => {
      soundboard.playNat20();
      setSelectedCombatId(combat.id);
      void queryClient.invalidateQueries({ queryKey: ["combats", campaignId] });
      showToast("🚀 预设遭遇已创建并载入参战人员！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "创建遭遇失败", "error");
    },
  });

  // Mutations
  const advanceTurnMutation = useMutation({
    mutationFn: async () => {
      if (!activeCombat) throw new Error("没有活跃的战斗");
      return advanceCombatTurn(campaignId, activeCombat.id, activeCombat.version);
    },
    onSuccess: () => {
      soundboard.playDiceRoll();
      void queryClient.invalidateQueries({ queryKey: ["combats", campaignId] });
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast("⏭️ 已进入下一战斗员回合！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "推进回合失败", "error");
    },
  });

  const rollInitiativesMutation = useMutation({
    mutationFn: async () => {
      if (!sortedCombatants.length) return;
      for (const combatant of sortedCombatants) {
        const d20 = Math.floor(Math.random() * 20) + 1;
        const dexMod = Math.floor(((combatant.armor_class ?? 10) - 10) / 2);
        const total = d20 + dexMod;
        await updateCombatant(
          campaignId,
          combatId,
          combatant.id,
          { initiative: total },
          combatant.version,
        );
      }
    },
    onSuccess: () => {
      soundboard.playDiceRoll();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast("🎲 全员先攻已重新投掷并排序！", "success");
    },
  });

  const quickHpAdjustMutation = useMutation({
    mutationFn: async ({ combatant, delta }: { combatant: Combatant; delta: number }) => {
      const currentHp = combatant.hp ?? 0;
      const maxHp = combatant.max_hp ?? 10;
      const newHp = Math.max(0, Math.min(maxHp, currentHp + delta));
      return updateCombatant(
        campaignId,
        combatId,
        combatant.id,
        { hp: newHp },
        combatant.version,
      );
    },
    onSuccess: (_data, vars) => {
      if (vars.delta < 0) soundboard.playAttackHit();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast(`生命值已调整: ${vars.delta > 0 ? `+${vars.delta}` : vars.delta}`, "success");
    },
  });

  const toggleConditionMutation = useMutation({
    mutationFn: async ({ combatant, condKey }: { combatant: Combatant; condKey: string }) => {
      const existing = (combatant.conditions ?? []) as Array<string | { name?: string; condition_name?: string }>;
      const exists = existing.some((c) => (typeof c === "string" ? c : c?.name ?? c?.condition_name) === condKey);
      const nextConditions = exists
        ? existing.filter((c) => (typeof c === "string" ? c : c?.name ?? c?.condition_name) !== condKey)
        : [...existing, condKey];

      return updateCombatant(
        campaignId,
        combatId,
        combatant.id,
        { conditions: nextConditions },
        combatant.version,
      );
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
    },
  });

  const executeActionMutation = useMutation({
    mutationFn: async () => {
      if (!selectedTargetCombatant) throw new Error("请选择目标战斗员");
      const dmg = Number(actionDamageAmount) || 0;
      const finalDmg = isCritical ? dmg * 2 : dmg;

      const command: CombatActionCommand = {
        action_type: "damage",
        target_combatant_id: selectedTargetCombatant.id,
        target_version: selectedTargetCombatant.version,
        actor_combatant_id: currentCombatant?.id,
        actor_version: currentCombatant?.version,
        action_cost: "action",
        action_name: actionName,
        amount: finalDmg,
        damage_type: actionDamageType,
        is_attack: true,
        attack_roll_total: Number(actionAttackRoll) || null,
        critical_hit: isCritical,
        resolution_note: `${currentCombatant?.display_name ?? "攻击者"} 对 ${selectedTargetCombatant.display_name} 发动 ${actionName}，造成 ${finalDmg} 点 ${actionDamageType} 伤害${isCritical ? "（💥暴击！）" : ""}`,
      };

      return confirmCombatAction(campaignId, combatId, command);
    },
    onSuccess: () => {
      if (isCritical) {
        soundboard.playNat20();
      } else {
        soundboard.playAttackHit();
      }
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      void queryClient.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
      showToast("⚔️ 动作已执行并写入战斗日志！", "success");
      setIsCritical(false);
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "执行失败", "error");
    },
  });

  const addCombatantMutation = useMutation({
    mutationFn: async () => {
      if (!combatId) throw new Error("请先选择或新建战斗");
      if (!newCombatantName.trim()) throw new Error("请输入战斗员名称");
      return createCombatant(campaignId, combatId, {
        display_name: newCombatantName.trim(),
        entity_type: newCombatantType,
        hp: Number(newCombatantHp) || 10,
        max_hp: Number(newCombatantHp) || 10,
        armor_class: Number(newCombatantAc) || 10,
        initiative: Number(newCombatantInit) || 10,
        conditions: [],
        snapshot_json: {
          row: Math.floor(Math.random() * 5) + 2,
          col: Math.floor(Math.random() * 8) + 2,
        },
      });
    },
    onSuccess: () => {
      setShowAddCombatantModal(false);
      setNewCombatantName("");
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast("👥 战斗员已加入战场！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "添加战斗员失败", "error");
    },
  });

  const aiTacticsMutation = useMutation({
    mutationFn: async () => {
      const summary = sortedCombatants
        .map((c) => `- ${c.display_name} (${c.entity_type}): HP ${c.hp}/${c.max_hp}, AC ${c.armor_class}, 先攻 ${c.initiative}`)
        .join("\n");
      const prompt = `当前战斗第 ${activeCombat?.round_number ?? 1} 轮，轮到 [${currentCombatant?.display_name ?? "当前行动者"}] 行动。\n参战人员状态如下：\n${summary}\n\n请作为资深 D&D 5e 战术军师，给出简明扼要的战术决策建议（包括推荐攻击目标、走位、法术使用与附赠动作搭配，100字左右）。`;
      const res = await runAssistantTurn(campaignId, prompt, { mode: "combat" });
      return res.dm_hint?.text ?? "未能生成战术建议";
    },
    onSuccess: (text) => {
      setAiAnalysis(text);
      soundboard.playHandout();
      showToast("🤖 AI 战术建议已生成！", "success");
    },
  });

  const aiNarrativeMutation = useMutation({
    mutationFn: async () => {
      const recentActions = (actionsQuery.data ?? [])
        .slice(0, 5)
        .map((a: CombatAction) => `- ${a.action_name ?? a.action_type}: ${a.resolution_note ?? ""}`)
        .join("\n");
      const prompt = `请根据以下最近发生的战斗交锋，写一段充满张力、画面感极强的中文战斗旁白（150字左右，用于主持人口述描述）：\n${recentActions || "双方正在近身对峙，伺机发动致命一击"}`;
      const res = await runAssistantTurn(campaignId, prompt, { mode: "narrative" });
      return res.dm_hint?.text ?? "未能生成战斗描述";
    },
    onSuccess: (text) => {
      setAiNarrative(text);
      soundboard.playHandout();
      showToast("🎙️ 战斗生动旁白已生成！", "success");
    },
  });

  // Roll Dice helper
  const rollDice = (sides: number, count = 1) => {
    soundboard.playDiceRoll();
    const mod = Number(customDiceMod) || 0;
    const rolls: number[] = [];
    let sum = 0;
    for (let i = 0; i < count; i++) {
      const r = Math.floor(Math.random() * sides) + 1;
      rolls.push(r);
      sum += r;
    }
    const total = sum + mod;
    const isCrit = sides === 20 && count === 1 && rolls[0] === 20;
    const isFumble = sides === 20 && count === 1 && rolls[0] === 1;

    if (isCrit) soundboard.playNat20();
    if (isFumble) soundboard.playNat1();

    const entry = {
      id: `${Date.now()}-${Math.random()}`,
      formula: `${count}d${sides}${mod !== 0 ? (mod > 0 ? `+${mod}` : `${mod}`) : ""}`,
      result: total,
      rolls,
      isCrit,
      isFumble,
    };
    setDiceHistory((prev) => [entry, ...prev.slice(0, 9)]);
  };

  // Convert combatants to SceneMapToken list
  const sceneTokens: SceneMapToken[] = useMemo(() => {
    return sortedCombatants.map((c, i) => {
      const conditions = (c.conditions ?? []) as Array<string | { name?: string; condition_name?: string }>;
      const isConcentrating = conditions.some((cond) => {
        const name = typeof cond === "string" ? cond : cond?.name ?? cond?.condition_name ?? "";
        return name.toLowerCase().includes("concentrat") || name.includes("专注");
      });
      return {
        id: c.id,
        entity_id: c.entity_id,
        entity_type: c.entity_type ?? "monster",
        label: c.display_name ?? `战斗员 ${i + 1}`,
        row: (c.snapshot_json as Record<string, unknown> | undefined)?.row as number ?? Math.floor(i / 6) + 2,
        col: (c.snapshot_json as Record<string, unknown> | undefined)?.col as number ?? (i % 6) + 2,
        targetKey: `combatant:${c.id}`,
        isOwn: c.entity_type === "character",
        conditions,
        hp: c.hp ?? 10,
        max_hp: c.max_hp ?? 10,
        isConcentrating,
        avatar_url: (c.snapshot_json as Record<string, unknown> | undefined)?.avatar_url as string | null | undefined,
      };
    });
  }, [sortedCombatants]);

  if (combatsQuery.isLoading) {
    return <LoadingBlock label="正在载入战役战斗数据…" />;
  }

  // If no combat exists in current campaign, provide 1-click starter combat creator
  if (!activeCombat || (combatsQuery.data ?? []).length === 0) {
    return (
      <div className="mx-auto max-w-4xl p-6">
        <div className="rounded-2xl border border-amber-500/40 bg-gradient-to-b from-ink-900 via-ink-950 to-ink-950 p-8 shadow-2xl text-center">
          <span className="text-5xl">⚡</span>
          <h2 className="mt-4 font-display text-2xl font-bold text-parchment-100">当前战役尚无活跃战斗遭遇</h2>
          <p className="mt-2 text-sm text-stone-400">
            您可以一键快速发起标准新手遭遇，或手动新建一场遭遇战并导入玩家与怪物。
          </p>

          <div className="mt-8 flex flex-wrap justify-center gap-4">
            <button
              className="rounded-xl border border-amber-500/70 bg-gradient-to-r from-amber-600 to-amber-700 px-6 py-3 text-sm font-bold text-amber-950 shadow-lg shadow-amber-600/30 transition hover:brightness-110 active:scale-95 disabled:opacity-50"
              disabled={createPresetEncounterMutation.isPending}
              onClick={() => createPresetEncounterMutation.mutate()}
              type="button"
            >
              {createPresetEncounterMutation.isPending ? "正在装载战场…" : "🚀 一键发起《红落避难所前厅突袭》（4名参战者）"}
            </button>
            <button
              className="rounded-xl border border-ink-700 bg-ink-900 px-5 py-3 text-sm text-stone-300 hover:border-ink-600 hover:text-white"
              onClick={() => setShowNewCombatModal(true)}
              type="button"
            >
              ➕ 新建自定义遭遇
            </button>
          </div>
        </div>

        {/* New Combat Modal */}
        {showNewCombatModal ? (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
            <div className="w-full max-w-md rounded-xl border border-ink-700 bg-ink-900 p-6 shadow-2xl">
              <h3 className="font-display text-base font-bold text-parchment-100">新建遭遇战斗</h3>
              <div className="mt-4 space-y-3">
                <div>
                  <label className="text-xs text-stone-400">战斗名称</label>
                  <input
                    className={`${inputCls} mt-1`}
                    onChange={(e) => setNewCombatName(e.target.value)}
                    value={newCombatName}
                  />
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-2">
                <Button onClick={() => setShowNewCombatModal(false)} variant="ghost">取消</Button>
                <Button
                  onClick={async () => {
                    if (!newCombatName.trim()) return;
                    const c = await createCombat(campaignId, { name: newCombatName.trim(), status: "active", round_number: 1 });
                    setShowNewCombatModal(false);
                    setSelectedCombatId(c.id);
                    void queryClient.invalidateQueries({ queryKey: ["combats", campaignId] });
                    showToast("遭遇战已创建！", "success");
                  }}
                  variant="primary"
                >
                  创建并进入
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className={`flex flex-col bg-ink-950 text-stone-200 ${isFullscreen ? "fixed inset-0 z-50 overflow-y-auto p-4" : "p-3 lg:p-5"}`}>
      {/* Top Cockpit Header */}
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-ink-700/80 bg-ink-900/90 p-3.5 shadow-xl backdrop-blur-md">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-2xl">⚡</span>
            <div>
              <h1 className="font-display text-lg font-bold text-parchment-100">快捷战斗座舱 (Quick Combat)</h1>
              <p className="text-2xs text-stone-400">独立极速查看与裁定 · 直连实时数据库</p>
            </div>
          </div>

          {/* Campaign Selector */}
          <div className="flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-950/80 px-2 py-1">
            <span className="text-2xs text-stone-400">战役:</span>
            <select
              className="bg-transparent text-xs text-parchment-100 outline-none"
              onChange={(e) => selectCampaign(e.target.value)}
              value={campaignId}
            >
              {(campaignsQuery.data ?? []).map((cp) => (
                <option className="bg-ink-900 text-stone-200" key={cp.id} value={cp.id}>
                  {cp.name}
                </option>
              ))}
            </select>
          </div>

          {/* Combat Selector */}
          <select
            className={`${selectCls} max-w-48 text-xs font-medium`}
            onChange={(e) => setSelectedCombatId(e.target.value)}
            value={combatId}
          >
            {(combatsQuery.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name || `遭遇战斗 #${c.id.slice(0, 6)}`} ({c.status === "active" ? "进行中" : "已结束"})
              </option>
            ))}
          </select>

          {activeCombat ? (
            <div className="flex items-center gap-2 rounded-lg border border-amber-500/40 bg-amber-950/30 px-3 py-1 text-xs">
              <span className="font-bold text-amber-300">第 {activeCombat.round_number} 轮</span>
              <span className="text-stone-500">|</span>
              <span className="text-stone-300">当前回合:</span>
              <strong className="text-amber-200">{currentCombatant?.display_name ?? "未指定"}</strong>
            </div>
          ) : null}
        </div>

        {/* Action Controls */}
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="rounded-lg border border-ink-700 bg-ink-800 px-2.5 py-1.5 text-xs text-stone-300 transition hover:border-amber-500/50 hover:text-amber-200"
            onClick={() => setShowAddCombatantModal(true)}
            type="button"
          >
            👥 添加参战者
          </button>
          <button
            className="rounded-lg border border-ink-700 bg-ink-800 px-2.5 py-1.5 text-xs text-stone-300 transition hover:border-amber-500/50 hover:text-amber-200"
            onClick={() => rollInitiativesMutation.mutate()}
            title="为当前所有参战者重掷 d20 先攻"
            type="button"
          >
            🎲 全员先攻
          </button>
          <button
            className="rounded-lg border border-emerald-600/70 bg-emerald-950/40 px-3 py-1.5 text-xs font-bold text-emerald-200 transition hover:bg-emerald-900/50"
            disabled={advanceTurnMutation.isPending}
            onClick={() => advanceTurnMutation.mutate()}
            type="button"
          >
            ⏭️ 推进下一回合
          </button>
          <button
            className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1.5 text-xs text-stone-400 hover:text-stone-200"
            onClick={() => setIsFullscreen(!isFullscreen)}
            type="button"
          >
            {isFullscreen ? "🗗 退出全屏" : "🗖 全景座舱"}
          </button>
        </div>
      </header>

      {/* Main 3-Column Tactical Cockpit Layout */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-12">
        {/* Left Column: 🎯 先攻与战斗员状态栏 (4 Cols) */}
        <div className="flex flex-col gap-3 lg:col-span-4">
          <div className="flex items-center justify-between rounded-t-xl border-b border-ink-800 bg-ink-900/60 px-3.5 py-2.5">
            <div className="flex items-center gap-2">
              <span className="text-base">🎯</span>
              <strong className="text-xs font-semibold uppercase tracking-wider text-parchment-200">
                先攻顺位与战斗员 ({sortedCombatants.length})
              </strong>
            </div>
            <span className="text-2xs text-stone-500">点击卡片选定目标</span>
          </div>

          <div className="space-y-2.5 overflow-y-auto pr-1" style={{ maxHeight: "calc(100vh - 180px)" }}>
            {sortedCombatants.length === 0 ? (
              <div className="rounded-xl border border-dashed border-ink-800 p-6 text-center text-xs text-stone-500">
                当前遭遇尚无参战者
                <button
                  className="mt-2 block mx-auto text-amber-400 underline hover:text-amber-300"
                  onClick={() => setShowAddCombatantModal(true)}
                >
                  + 添加战斗员 / 怪物
                </button>
              </div>
            ) : null}

            {sortedCombatants.map((c) => {
              const isCurrent = currentCombatant?.id === c.id;
              const isSelected = selectedCombatantId === c.id;
              const hpPct = Math.max(0, Math.min(100, ((c.hp ?? 0) / (c.max_hp ?? 10)) * 100));
              const conditions = (c.conditions ?? []) as Array<string | { name?: string; condition_name?: string }>;

              return (
                <div
                  className={`relative rounded-xl border p-3 transition-all ${
                    isCurrent
                      ? "border-amber-500 bg-gradient-to-r from-amber-950/40 via-ink-900 to-ink-900 shadow-lg shadow-amber-500/10 ring-1 ring-amber-400/50"
                      : isSelected
                        ? "border-sky-500 bg-sky-950/20"
                        : "border-ink-800/80 bg-ink-900/50 hover:border-ink-700"
                  }`}
                  key={c.id}
                  onClick={() => {
                    setSelectedCombatantId(c.id);
                    setActionTargetId(c.id);
                  }}
                >
                  {/* Top line: Avatar / Name / Initiative */}
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <span
                        className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                          c.entity_type === "character"
                            ? "bg-sky-500/20 text-sky-300 border border-sky-500/40"
                            : c.entity_type === "npc"
                              ? "bg-violet-500/20 text-violet-300 border border-violet-500/40"
                              : "bg-red-500/20 text-red-300 border border-red-500/40"
                        }`}
                      >
                        {c.display_name?.slice(0, 1) ?? "战"}
                      </span>
                      <strong className="truncate text-sm text-parchment-100">{c.display_name}</strong>
                      {isCurrent ? (
                        <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-bold text-amber-300 animate-pulse">
                          行动中
                        </span>
                      ) : null}
                    </div>

                    <div className="flex items-center gap-1.5 shrink-0">
                      <span className="rounded border border-ink-700 bg-ink-950 px-2 py-0.5 font-mono text-xs text-amber-200">
                        ⚡ {c.initiative ?? "—"}
                      </span>
                      <span className="rounded border border-ink-800 bg-ink-950/60 px-1.5 py-0.5 font-mono text-2xs text-stone-400">
                        🛡️ AC {c.armor_class ?? 10}
                      </span>
                    </div>
                  </div>

                  {/* HP Progress Bar & Quick Adjustments */}
                  <div className="mt-2.5">
                    <div className="flex items-center justify-between text-2xs">
                      <span className="text-stone-400">生命值 HP</span>
                      <strong className={hpPct > 50 ? "text-emerald-300" : hpPct > 20 ? "text-amber-300" : "text-rose-400"}>
                        {c.hp ?? 0} / {c.max_hp ?? 10}
                      </strong>
                    </div>
                    <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink-950 border border-ink-800">
                      <div
                        className={`h-full transition-all duration-300 ${
                          hpPct > 50 ? "bg-emerald-500" : hpPct > 20 ? "bg-amber-500" : "bg-rose-500"
                        }`}
                        style={{ width: `${hpPct}%` }}
                      />
                    </div>

                    {/* Quick HP Adjustment Buttons */}
                    <div className="mt-2 flex flex-wrap gap-1">
                      <button
                        className="rounded border border-rose-900/80 bg-rose-950/40 px-1.5 py-0.5 text-2xs font-mono text-rose-300 hover:bg-rose-900"
                        onClick={(e) => {
                          e.stopPropagation();
                          quickHpAdjustMutation.mutate({ combatant: c, delta: -10 });
                        }}
                        type="button"
                      >
                        -10
                      </button>
                      <button
                        className="rounded border border-rose-900/80 bg-rose-950/40 px-1.5 py-0.5 text-2xs font-mono text-rose-300 hover:bg-rose-900"
                        onClick={(e) => {
                          e.stopPropagation();
                          quickHpAdjustMutation.mutate({ combatant: c, delta: -5 });
                        }}
                        type="button"
                      >
                        -5
                      </button>
                      <button
                        className="rounded border border-rose-900/80 bg-rose-950/40 px-1.5 py-0.5 text-2xs font-mono text-rose-300 hover:bg-rose-900"
                        onClick={(e) => {
                          e.stopPropagation();
                          quickHpAdjustMutation.mutate({ combatant: c, delta: -1 });
                        }}
                        type="button"
                      >
                        -1
                      </button>
                      <button
                        className="rounded border border-emerald-900/80 bg-emerald-950/40 px-1.5 py-0.5 text-2xs font-mono text-emerald-300 hover:bg-emerald-900"
                        onClick={(e) => {
                          e.stopPropagation();
                          quickHpAdjustMutation.mutate({ combatant: c, delta: 1 });
                        }}
                        type="button"
                      >
                        +1
                      </button>
                      <button
                        className="rounded border border-emerald-900/80 bg-emerald-950/40 px-1.5 py-0.5 text-2xs font-mono text-emerald-300 hover:bg-emerald-900"
                        onClick={(e) => {
                          e.stopPropagation();
                          quickHpAdjustMutation.mutate({ combatant: c, delta: 5 });
                        }}
                        type="button"
                      >
                        +5
                      </button>
                    </div>
                  </div>

                  {/* Conditions Badges */}
                  <div className="mt-2.5 flex flex-wrap items-center gap-1 border-t border-ink-800/60 pt-2">
                    {CONDITIONS_LIST.map((cond) => {
                      const isActive = conditions.some(
                        (item) => (typeof item === "string" ? item : item?.name ?? item?.condition_name) === cond.key,
                      );
                      return (
                        <button
                          className={`rounded border px-1.5 py-0.5 text-2xs transition-colors ${
                            isActive
                              ? "border-amber-500 bg-amber-500/20 font-bold text-amber-200"
                              : "border-ink-800/60 bg-ink-950/40 text-stone-500 hover:border-ink-700 hover:text-stone-300"
                          }`}
                          key={cond.key}
                          onClick={(e) => {
                            e.stopPropagation();
                            toggleConditionMutation.mutate({ combatant: c, condKey: cond.key });
                          }}
                          title={`切换状态: ${cond.label}`}
                          type="button"
                        >
                          {cond.icon} {cond.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Middle Column: 🗺️ 战术地图与极速动作台 (5 Cols) */}
        <div className="flex flex-col gap-3 lg:col-span-5">
          {/* Tactical Scene Map */}
          <div className="rounded-xl border border-ink-800 bg-ink-900/50 p-3 shadow-lg">
            <SceneMap
              grid={{
                width: 12,
                height: 10,
                cell_size_ft: 5,
                theme: "dungeon",
              }}
              objects={[]}
              onPing={(row, col) => {
                showToast(`📍 战术信号已发送至坐标 (${row}, ${col})`, "info");
              }}
              onTargetSelect={(targetKey) => {
                const id = targetKey.replace("combatant:", "");
                setActionTargetId(id);
                setSelectedCombatantId(id);
              }}
              selectedTargetKey={actionTargetId ? `combatant:${actionTargetId}` : undefined}
              title="战术场景地图 (双击网格发送Ping)"
              tokens={sceneTokens}
            />
          </div>

          {/* Quick Action Console */}
          <div className="rounded-xl border border-ink-700/80 bg-ink-900/80 p-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-ink-800 pb-2.5">
              <div className="flex items-center gap-2">
                <span className="text-lg">⚔️</span>
                <div>
                  <h3 className="font-display text-sm font-bold text-parchment-100">极速动作裁定台</h3>
                  <p className="text-2xs text-stone-400">
                    当前行动者: <strong className="text-amber-300">{currentCombatant?.display_name ?? "未选择"}</strong>
                  </p>
                </div>
              </div>
              <span className="rounded bg-sky-950/40 border border-sky-800/40 px-2 py-0.5 text-2xs text-sky-300">
                目标: {selectedTargetCombatant?.display_name ?? "未选定"}
              </span>
            </div>

            {/* Action Form */}
            <div className="mt-3 space-y-3">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-2xs font-semibold uppercase text-stone-400">动作名称</label>
                  <input
                    className={`${inputCls} mt-1`}
                    onChange={(e) => setActionName(e.target.value)}
                    placeholder="如：长剑斩击 / 火球术"
                    value={actionName}
                  />
                </div>
                <div>
                  <label className="text-2xs font-semibold uppercase text-stone-400">受击目标</label>
                  <select
                    className={`${selectCls} mt-1`}
                    onChange={(e) => {
                      setActionTargetId(e.target.value);
                      setSelectedCombatantId(e.target.value);
                    }}
                    value={actionTargetId}
                  >
                    <option value="">选择目标战斗员</option>
                    {sortedCombatants.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.display_name} (HP: {c.hp}/{c.max_hp})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-2xs font-semibold uppercase text-stone-400">命中检定 d20</label>
                  <input
                    className={`${inputCls} mt-1 font-mono`}
                    onChange={(e) => setActionAttackRoll(e.target.value)}
                    type="number"
                    value={actionAttackRoll}
                  />
                </div>
                <div>
                  <label className="text-2xs font-semibold uppercase text-stone-400">基础伤害</label>
                  <input
                    className={`${inputCls} mt-1 font-mono`}
                    onChange={(e) => setActionDamageAmount(e.target.value)}
                    type="number"
                    value={actionDamageAmount}
                  />
                </div>
                <div>
                  <label className="text-2xs font-semibold uppercase text-stone-400">伤害类型</label>
                  <select
                    className={`${selectCls} mt-1`}
                    onChange={(e) => setActionDamageType(e.target.value)}
                    value={actionDamageType}
                  >
                    <option value="slashing">挥砍 (Slashing)</option>
                    <option value="piercing">穿刺 (Piercing)</option>
                    <option value="bludgeoning">钝击 (Bludgeoning)</option>
                    <option value="fire">火焰 (Fire)</option>
                    <option value="radiant">光耀 (Radiant)</option>
                    <option value="necrotic">黯蚀 (Necrotic)</option>
                    <option value="force">力场 (Force)</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center justify-between pt-1">
                <label className="flex items-center gap-2 text-xs font-semibold text-amber-300">
                  <input
                    checked={isCritical}
                    className="accent-amber-500"
                    onChange={(e) => setIsCritical(e.target.checked)}
                    type="checkbox"
                  />
                  <span>💥 致命一击 (暴击伤害双倍)</span>
                </label>

                <button
                  className="rounded-lg border border-amber-600/70 bg-amber-600/20 px-4 py-1.5 text-xs font-bold text-amber-200 shadow-md transition hover:bg-amber-600/30 disabled:opacity-50"
                  disabled={!selectedTargetCombatant || executeActionMutation.isPending}
                  onClick={() => executeActionMutation.mutate()}
                  type="button"
                >
                  {executeActionMutation.isPending ? "结算中…" : "💥 确认执行伤害"}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: 📜 战况流水 & AI 战术副驾 (3 Cols) */}
        <div className="flex flex-col gap-3 lg:col-span-3">
          {/* Quick Dice Roller Arena */}
          <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3.5 shadow-md">
            <div className="flex items-center justify-between border-b border-ink-800 pb-2">
              <span className="text-xs font-bold text-parchment-200">🎲 极速骰盘</span>
              <div className="flex items-center gap-1.5">
                <span className="text-2xs text-stone-400">调整值:</span>
                <input
                  className="w-12 rounded border border-ink-700 bg-ink-950 px-1 py-0.5 text-center font-mono text-xs text-amber-200"
                  onChange={(e) => setCustomDiceMod(e.target.value)}
                  type="number"
                  value={customDiceMod}
                />
              </div>
            </div>
            <div className="mt-2.5 grid grid-cols-4 gap-1.5">
              {[20, 12, 10, 8, 6, 4].map((d) => (
                <button
                  className="rounded border border-ink-700 bg-ink-950/80 py-1.5 text-xs font-bold text-stone-300 transition hover:border-amber-500/60 hover:text-amber-200"
                  key={d}
                  onClick={() => rollDice(d)}
                  type="button"
                >
                  d{d}
                </button>
              ))}
              <button
                className="col-span-2 rounded border border-amber-800/60 bg-amber-950/30 py-1.5 text-xs font-bold text-amber-300 hover:bg-amber-900/40"
                onClick={() => rollDice(6, 2)}
                type="button"
              >
                2d6
              </button>
            </div>

            {/* Latest Rolls */}
            {diceHistory.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5 border-t border-ink-800/60 pt-2">
                {diceHistory.slice(0, 4).map((roll) => (
                  <span
                    className={`rounded border px-2 py-0.5 font-mono text-2xs ${
                      roll.isCrit
                        ? "border-amber-500 bg-amber-500/20 text-amber-200 font-bold"
                        : roll.isFumble
                          ? "border-rose-500 bg-rose-500/20 text-rose-200 font-bold"
                          : "border-ink-800 bg-ink-950 text-stone-300"
                    }`}
                    key={roll.id}
                  >
                    {roll.formula} ➔ <strong>{roll.result}</strong>
                  </span>
                ))}
              </div>
            ) : null}
          </div>

          {/* AI Tactical Copilot */}
          <div className="rounded-xl border border-ink-800 bg-ink-900/60 p-3.5 shadow-md">
            <div className="flex items-center justify-between border-b border-ink-800 pb-2">
              <span className="text-xs font-bold text-parchment-200">🤖 AI 战术副驾</span>
              <div className="flex gap-1.5">
                <button
                  className="rounded border border-amber-700/60 bg-amber-950/30 px-2 py-0.5 text-2xs text-amber-300 hover:bg-amber-900/40 disabled:opacity-50"
                  disabled={aiTacticsMutation.isPending}
                  onClick={() => aiTacticsMutation.mutate()}
                  type="button"
                >
                  {aiTacticsMutation.isPending ? "思考中…" : "战术分析"}
                </button>
                <button
                  className="rounded border border-sky-700/60 bg-sky-950/30 px-2 py-0.5 text-2xs text-sky-300 hover:bg-sky-900/40 disabled:opacity-50"
                  disabled={aiNarrativeMutation.isPending}
                  onClick={() => aiNarrativeMutation.mutate()}
                  type="button"
                >
                  {aiNarrativeMutation.isPending ? "构思中…" : "战况朗读"}
                </button>
              </div>
            </div>

            <div className="mt-2.5 min-h-[80px] max-h-48 overflow-y-auto text-xs leading-relaxed text-stone-300">
              {aiAnalysis ? (
                <div className="rounded border border-amber-900/40 bg-amber-950/15 p-2 font-sans text-amber-200/90">
                  <strong className="block text-2xs uppercase text-amber-400">💡 战术建议</strong>
                  {aiAnalysis}
                </div>
              ) : null}
              {aiNarrative ? (
                <div className="mt-2 rounded border border-sky-900/40 bg-sky-950/15 p-2 font-serif text-sky-200/90 italic">
                  <strong className="block font-sans text-2xs uppercase text-sky-400 not-italic">🎙️ 战斗旁白</strong>
                  {aiNarrative}
                </div>
              ) : null}
              {!aiAnalysis && !aiNarrative ? (
                <p className="py-4 text-center text-2xs text-stone-500">点击上方按钮让 AI 辅助战术裁定与旁白解说</p>
              ) : null}
            </div>
          </div>

          {/* Live Action History Log */}
          <div className="flex-1 rounded-xl border border-ink-800 bg-ink-900/60 p-3.5 shadow-md">
            <div className="border-b border-ink-800 pb-2">
              <span className="text-xs font-bold text-parchment-200">📜 实时战斗记录</span>
            </div>
            <div className="mt-2 max-h-56 space-y-1.5 overflow-y-auto pr-1">
              {(actionsQuery.data ?? []).length > 0 ? (
                (actionsQuery.data ?? []).slice(0, 10).map((act: CombatAction) => (
                  <div className="rounded border border-ink-800/60 bg-ink-950/40 p-2 text-2xs" key={act.id}>
                    <div className="flex items-center justify-between">
                      <strong className="text-stone-300">{act.action_name ?? act.action_type}</strong>
                      <span className="font-mono text-stone-500">{formatDateTime(act.created_at)}</span>
                    </div>
                    {act.resolution_note ? <p className="mt-1 text-stone-400">{act.resolution_note}</p> : null}
                  </div>
                ))
              ) : (
                <p className="py-4 text-center text-2xs text-stone-500">本场战斗尚无动作记录</p>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Add Combatant Modal */}
      {showAddCombatantModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-xl border border-ink-700 bg-ink-900 p-6 shadow-2xl">
            <h3 className="font-display text-base font-bold text-parchment-100">添加参战者 / 怪物</h3>
            <div className="mt-4 space-y-3">
              <div>
                <label className="text-xs text-stone-400">战斗员名称</label>
                <input
                  className={`${inputCls} mt-1`}
                  onChange={(e) => setNewCombatantName(e.target.value)}
                  placeholder="如：地精巫师 / 守卫长"
                  value={newCombatantName}
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-stone-400">阵营类型</label>
                  <select
                    className={`${selectCls} mt-1`}
                    onChange={(e) => setNewCombatantType(e.target.value as "character" | "monster" | "npc")}
                    value={newCombatantType}
                  >
                    <option value="monster">👹 怪物 (Monster)</option>
                    <option value="character">🛡️ 玩家角色 (PC)</option>
                    <option value="npc">👤 NPC / 友军</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs text-stone-400">初始先攻</label>
                  <input
                    className={`${inputCls} mt-1`}
                    onChange={(e) => setNewCombatantInit(e.target.value)}
                    type="number"
                    value={newCombatantInit}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-xs text-stone-400">生命上限 HP</label>
                  <input
                    className={`${inputCls} mt-1`}
                    onChange={(e) => setNewCombatantHp(e.target.value)}
                    type="number"
                    value={newCombatantHp}
                  />
                </div>
                <div>
                  <label className="text-xs text-stone-400">护甲等级 AC</label>
                  <input
                    className={`${inputCls} mt-1`}
                    onChange={(e) => setNewCombatantAc(e.target.value)}
                    type="number"
                    value={newCombatantAc}
                  />
                </div>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button onClick={() => setShowAddCombatantModal(false)} variant="ghost">取消</Button>
              <Button
                disabled={addCombatantMutation.isPending}
                onClick={() => addCombatantMutation.mutate()}
                variant="primary"
              >
                {addCombatantMutation.isPending ? "添加中…" : "加入战场"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function QuickCombatPage(): ReactElement {
  return (
    <RequireCampaign>
      {(campaignId) => <QuickCombatCockpit campaignId={campaignId} />}
    </RequireCampaign>
  );
}
