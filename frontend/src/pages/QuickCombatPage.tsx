import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState, type ReactElement } from "react";

import {
  advanceCombatTurn,
  confirmCombatAction,
  createCombat,
  createCombatant,
  listCombatActions,
  listCombatants,
  listCombats,
  updateCombatant,
  type CombatActionCommand,
} from "../api/entities";
import { listCampaigns } from "../api/campaigns";
import { runAssistantTurn } from "../api/assistant";
import { listCharacters } from "../api/entities";
import type { Combat, CombatAction, Combatant, SceneGrid } from "../api/types";
import { RequireCampaign } from "../components/RequireCampaign";
import {
  TurnCommandConsole,
  type CombatTargeting,
  type CombatTargetingValidity,
} from "../components/combat/TurnCommandConsole";
import { useCurrentCampaign } from "../hooks/appContexts";
import { useToast } from "../hooks/toastContext";
import { soundboard } from "../ui/soundboard";
import { Badge, Button, LoadingBlock } from "../ui/primitives";
import { inputCls, selectCls } from "../ui/styles";
import {
  getTargetingCells,
  gridDistanceFt,
  isAimPointInRange,
  type GridPoint,
} from "../ui/gridTargeting";
import {
  DND_CONDITIONS,
  DND_SKILLS,
  DND_TEST_SPELLS,
  getSpellUpcastPreview,
  type CombatSpellOption,
} from "../ui/combatConstants";

export type VfxEvent = {
  id: string;
  row: number;
  col: number;
  type: "slash" | "arcane" | "shockwave" | "smite" | "fire" | "dust";
  text?: string;
  isCrit?: boolean;
  isMiss?: boolean;
};

function combatantElevationFt(fighter: Combatant): number {
  const snap = fighter.snapshot_json as Record<string, unknown> | undefined;
  if (!snap) return 0;
  const pos = snap.grid_position as { elevation_ft?: number } | undefined;
  if (pos && typeof pos.elevation_ft === "number") return pos.elevation_ft;
  if (typeof snap.elevation_ft === "number") return snap.elevation_ft;
  if (typeof snap.elevation === "number") return snap.elevation;
  return 0;
}

function combatantGridPosition(fighter: Combatant): [number, number] | null {
  const snap = fighter.snapshot_json as Record<string, unknown> | undefined;
  if (!snap) return null;
  const pos = snap.grid_position as { row?: number; col?: number } | undefined;
  if (pos && typeof pos.row === "number" && typeof pos.col === "number") {
    return [pos.row, pos.col];
  }
  if (typeof snap.row === "number" && typeof snap.col === "number") {
    return [snap.row, snap.col];
  }
  return null;
}

function getCombatantSpellSlots(fighter: Combatant | null): Record<number, number> {
  if (!fighter) return { 1: 4, 2: 3, 3: 2 };
  const snap = fighter.snapshot_json as Record<string, unknown> | undefined;
  const slots = snap?.spell_slots as Record<string, number> | undefined;
  if (slots) {
    return {
      1: typeof slots["1"] === "number" ? slots["1"] : 4,
      2: typeof slots["2"] === "number" ? slots["2"] : 3,
      3: typeof slots["3"] === "number" ? slots["3"] : 2,
    };
  }
  return { 1: 4, 2: 3, 3: 2 };
}

function getCombatantTurnResources(fighter: Combatant | null): { action: boolean; bonus_action: boolean; reaction: boolean } {
  if (!fighter) return { action: true, bonus_action: true, reaction: true };
  const snap = fighter.snapshot_json as Record<string, unknown> | undefined;
  const res = snap?.turn_resources as { action?: boolean; bonus_action?: boolean; reaction?: boolean } | undefined;
  return {
    action: res?.action !== false,
    bonus_action: res?.bonus_action !== false,
    reaction: res?.reaction !== false,
  };
}

// ---------------------------------------------------------------------------
// 1. BG3 Top Floating Initiative Timeline Carousel
// ---------------------------------------------------------------------------
function BG3InitiativeTrack({
  fighters,
  activeFighterId,
  selectedTargetId,
  onSelectCombatant,
  roundNumber,
  onRollInitiatives,
  onAddCombatant,
  campaignId,
  campaigns,
  onSelectCampaign,
  combatId,
  combats,
  onSelectCombat,
  isFullscreen,
  onToggleFullscreen,
  autoEnemies,
  onToggleAutoEnemies,
}: {
  fighters: Combatant[];
  activeFighterId: string | null;
  selectedTargetId: string;
  onSelectCombatant: (id: string) => void;
  roundNumber: number;
  onRollInitiatives: () => void;
  onAddCombatant: () => void;
  campaignId: string;
  campaigns: Array<{ id: string; name: string }>;
  onSelectCampaign: (id: string) => void;
  combatId: string;
  combats: Combat[];
  onSelectCombat: (id: string) => void;
  isFullscreen: boolean;
  onToggleFullscreen: () => void;
  autoEnemies: boolean;
  onToggleAutoEnemies: () => void;
}): ReactElement {
  return (
    <div className="bg3-panel flex flex-wrap items-center justify-between gap-3 rounded-2xl px-4 py-2 text-xs shadow-2xl">
      {/* Left Badge: Title & Round & Encounter Meta */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1.5 mr-1">
          <span className="text-amber-400 text-base">⚡</span>
          <div>
            <h1 className="font-display text-xs font-bold text-parchment-100 leading-tight">
              快捷战斗座舱 (Quick Combat)
            </h1>
            <span className="text-[9px] text-stone-400">博德之门 3 战术 HUD</span>
          </div>
        </div>

        {/* Campaign Selector */}
        <select
          className="rounded-lg border border-ink-700 bg-ink-950 px-2 py-1 text-2xs text-stone-200 outline-none"
          onChange={(e) => onSelectCampaign(e.target.value)}
          value={campaignId}
        >
          {campaigns.map((cp) => (
            <option className="bg-ink-900 text-stone-200" key={cp.id} value={cp.id}>
              {cp.name}
            </option>
          ))}
        </select>

        {/* Combat Selector */}
        <select
          className="max-w-36 rounded-lg border border-ink-700 bg-ink-950 px-2 py-1 text-2xs font-medium text-stone-200 outline-none truncate"
          onChange={(e) => onSelectCombat(e.target.value)}
          value={combatId}
        >
          {combats.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name || `遭遇 #${c.id.slice(0, 5)}`}
            </option>
          ))}
        </select>

        <div className="flex items-center gap-1 rounded-xl border border-amber-500/40 bg-gradient-to-r from-amber-950/80 to-ink-950 px-2.5 py-1 font-bold text-amber-200 shadow-inner">
          <span>第 {roundNumber} 轮</span>
        </div>

        <button
          className="rounded-lg border border-ink-700 bg-ink-900/90 px-2 py-1 text-2xs font-semibold text-stone-300 transition hover:border-amber-500 hover:text-amber-200"
          onClick={onRollInitiatives}
          title="重新投掷全员先攻值"
          type="button"
        >
          🎲 投先攻
        </button>
        <button
          className="rounded-lg border border-ink-700 bg-ink-900/90 px-2 py-1 text-2xs font-semibold text-stone-300 transition hover:border-amber-500 hover:text-amber-200"
          onClick={onAddCombatant}
          title="添加新角色或怪物"
          type="button"
        >
          👥 加人
        </button>

        {/* Auto Enemy Turns Toggle */}
        <button
          className={`rounded-lg border px-2 py-1 text-2xs font-bold transition ${
            autoEnemies
              ? "border-rose-500 bg-rose-950/80 text-rose-200 shadow-[0_0_8px_rgba(244,63,94,0.4)]"
              : "border-ink-700 bg-ink-900/90 text-stone-400 hover:text-stone-200"
          }`}
          onClick={onToggleAutoEnemies}
          title="启用后轮到怪物时将自动触发 AI 决策并攻击"
          type="button"
        >
          🤖 怪物自动回合: {autoEnemies ? "开" : "关"}
        </button>
      </div>

      {/* Center Carousel: Initiative Order Cards */}
      <div className="flex items-center gap-2 overflow-x-auto py-1 max-w-xl no-scrollbar">
        {fighters.map((f, idx) => {
          const isActive = f.id === activeFighterId;
          const isTarget = f.id === selectedTargetId;
          const isPc = f.entity_type === "character";
          const isMonster = f.entity_type === "monster";
          const hpPercent = Math.max(0, Math.min(100, ((f.hp ?? 0) / (f.max_hp || 1)) * 100));

          return (
            <button
              className={`group relative flex items-center gap-2 rounded-xl border px-2.5 py-1.5 transition-all ${
                isActive
                  ? "bg3-panel-gold scale-105 ring-2 ring-amber-400 shadow-[0_0_16px_rgba(245,158,11,0.5)] z-10"
                  : isTarget
                    ? "border-emerald-400 bg-emerald-950/70 ring-1 ring-emerald-400"
                    : isPc
                      ? "border-sky-700/60 bg-sky-950/40 hover:border-sky-400"
                      : isMonster
                        ? "border-rose-800/60 bg-rose-950/40 hover:border-rose-500"
                        : "border-violet-800/60 bg-violet-950/40 hover:border-violet-500"
              }`}
              key={f.id}
              onClick={() => onSelectCombatant(f.id)}
              type="button"
            >
              <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[9px] font-bold ${
                isActive ? "bg-amber-400 text-amber-950" : "bg-ink-800 text-stone-300"
              }`}>
                {idx + 1}
              </span>

              <div className="flex flex-col items-start min-w-[65px] max-w-[95px] text-left">
                <div className="flex w-full items-center justify-between gap-1">
                  <span className={`truncate text-2xs font-bold ${isActive ? "text-amber-200" : "text-stone-200"}`}>
                    {f.display_name}
                  </span>
                  {isActive ? <span className="text-[10px]">👑</span> : null}
                </div>

                <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-ink-950 border border-ink-800">
                  <div
                    className={`h-full transition-all duration-300 ${
                      hpPercent > 50 ? "bg-emerald-500" : hpPercent > 20 ? "bg-amber-500" : "bg-rose-500"
                    }`}
                    style={{ width: `${hpPercent}%` }}
                  />
                </div>

                <div className="mt-0.5 flex w-full justify-between text-[8px] font-mono text-stone-400">
                  <span>🛡️{f.armor_class ?? 10}</span>
                  <span>{f.hp}/{f.max_hp}</span>
                </div>
              </div>
            </button>
          );
        })}
      </div>

      {/* Fullscreen Button */}
      <div className="flex items-center gap-1.5">
        <button
          className="rounded-lg border border-ink-700 bg-ink-900 px-2.5 py-1 text-xs text-stone-400 hover:text-stone-200"
          onClick={onToggleFullscreen}
          type="button"
        >
          {isFullscreen ? "🗗 退出全屏" : "🗖 全景"}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 2. BG3 Center 3D Isometric Battlefield Component
// ---------------------------------------------------------------------------
function BG3BattleGrid({
  campaignId,
  combatId,
  fighters,
  activeFighterId,
  targeting,
  positions,
  onTargetSelect,
  selectedTargetId,
  vfxEvents,
  onSpawnVfx,
  interactionMode,
  onInteractionModeChange,
  aimPoint,
  onAimPointChange,
  areaKeys,
}: {
  campaignId: string;
  combatId: string;
  fighters: Combatant[];
  activeFighterId: string | null;
  targeting: CombatTargeting | null;
  positions: Record<string, [number, number]>;
  onTargetSelect: (targetId: string) => void;
  selectedTargetId: string;
  vfxEvents: VfxEvent[];
  onSpawnVfx: (event: Omit<VfxEvent, "id">) => void;
  interactionMode: "move" | "target";
  onInteractionModeChange: (mode: "move" | "target") => void;
  aimPoint: GridPoint | null;
  onAimPointChange: (point: GridPoint | null) => void;
  areaKeys: Set<string>;
}): ReactElement {
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const width = 12;
  const height = 10;
  const cellSizeFt = 5;

  const [viewPerspective, setViewPerspective] = useState<"iso-3d" | "high-3d" | "flat-2d">("iso-3d");
  const [selectedTokenId, setSelectedTokenId] = useState<string>(activeFighterId ?? "");
  const [showEnemyThreat, setShowEnemyThreat] = useState<boolean>(true);
  const [pings, setPings] = useState<Array<{ id: string; row: number; col: number }>>([]);

  const activeFighter = useMemo(() => fighters.find((f) => f.id === activeFighterId) ?? fighters[0] ?? null, [fighters, activeFighterId]);
  const activePos = activeFighter ? positions[activeFighter.id] : null;
  const activePosition: GridPoint | null = activePos ? { row: activePos[0], col: activePos[1] } : null;

  const selectedFighter = useMemo(() => fighters.find((f) => f.id === (selectedTokenId || activeFighterId)) ?? activeFighter, [fighters, selectedTokenId, activeFighterId, activeFighter]);
  const selectedPos = selectedFighter ? positions[selectedFighter.id] : activePos;
  
  // Strict movement remaining: 0 means no more movement allowed this turn
  const selectedRemaining = (selectedFighter?.movement_remaining_ft !== undefined && selectedFighter?.movement_remaining_ft !== null)
    ? selectedFighter.movement_remaining_ft
    : (selectedFighter?.speed_ft ?? 30);

  // Calculate Enemy Threat Ranges
  const enemyThreatCells = useMemo(() => {
    if (!showEnemyThreat) return { meleeKeys: new Set<string>(), rangedKeys: new Set<string>() };
    const meleeKeys = new Set<string>();
    const rangedKeys = new Set<string>();

    const enemies = fighters.filter((f) => f.entity_type === "monster" && (f.hp ?? 0) > 0);
    enemies.forEach((enemy) => {
      const pos = positions[enemy.id];
      if (!pos) return;

      for (let r = 1; r <= height; r++) {
        for (let c = 1; c <= width; c++) {
          const dist = gridDistanceFt({ row: pos[0], col: pos[1] }, { row: r, col: c }, cellSizeFt);
          if (dist <= 5) {
            meleeKeys.add(`${r}:${c}`);
          } else if (dist <= 30) {
            rangedKeys.add(`${r}:${c}`);
          }
        }
      }
    });

    return { meleeKeys, rangedKeys };
  }, [fighters, positions, showEnemyThreat, height, width, cellSizeFt]);

  // Move token mutation with movement dust VFX
  const moveMutation = useMutation({
    mutationFn: async ({ fighter, newRow, newCol, spentFt }: { fighter: Combatant; newRow: number; newCol: number; spentFt: number }) => {
      const curRemaining = fighter.movement_remaining_ft !== undefined && fighter.movement_remaining_ft !== null
        ? fighter.movement_remaining_ft
        : (fighter.speed_ft ?? 30);
      
      if (curRemaining < spentFt) {
        throw new Error("⚠️ 剩余移动力不足！");
      }

      const nextRemaining = Math.max(0, curRemaining - spentFt);
      const snapshot = {
        ...(fighter.snapshot_json as Record<string, unknown> | undefined),
        grid_position: {
          ...((fighter.snapshot_json as Record<string, unknown> | undefined)?.grid_position as Record<string, unknown> | undefined),
          row: newRow,
          col: newCol,
        },
        row: newRow,
        col: newCol,
      };

      onSpawnVfx({ row: newRow, col: newCol, type: "dust", text: `-${spentFt}尺` });

      return updateCombatant(
        campaignId,
        combatId,
        fighter.id,
        {
          movement_remaining_ft: nextRemaining,
          snapshot_json: snapshot,
        },
        fighter.version,
      );
    },
    onSuccess: () => {
      soundboard.playDiceRoll();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast("🏃 单位已移动并扣减移动力！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "移动失败", "error");
    },
  });

  // Step Move helper (5ft in cardinal direction)
  const handleStepMove = (dRow: number, dCol: number) => {
    if (!selectedFighter || !selectedPos) return;
    if (selectedRemaining < 5) {
      showToast("⚠️ 剩余移动力不足 5 尺！", "warn");
      return;
    }
    const targetRow = Math.max(1, Math.min(height, selectedPos[0] + dRow));
    const targetCol = Math.max(1, Math.min(width, selectedPos[1] + dCol));
    if (targetRow === selectedPos[0] && targetCol === selectedPos[1]) return;

    const occupied = fighters.find((f) => positions[f.id]?.[0] === targetRow && positions[f.id]?.[1] === targetCol);
    if (occupied) {
      showToast(`⚠️ 该位置已被 ${occupied.display_name} 占据！`, "warn");
      return;
    }

    moveMutation.mutate({
      fighter: selectedFighter,
      newRow: targetRow,
      newCol: targetCol,
      spentFt: 5,
    });
  };

  const triggerPing = (row: number, col: number) => {
    soundboard.playPing();
    const id = `${Date.now()}-${Math.random()}`;
    setPings((prev) => [...prev, { id, row, col }]);
    showToast(`📍 战术信号已发送至 (${row}, ${col})`, "info");
    setTimeout(() => {
      setPings((prev) => prev.filter((p) => p.id !== id));
    }, 2400);
  };

  return (
    <div className="relative flex flex-col justify-between rounded-2xl border border-ink-800 bg-gradient-to-b from-ink-950 via-[#07090e] to-ink-950 p-3 shadow-2xl">
      {/* Viewport Floating Top Bar */}
      <div className="z-20 mb-2 flex flex-wrap items-center justify-between gap-2 text-2xs">
        <div className="flex items-center gap-2">
          <div className="flex rounded-xl border border-ink-700 bg-ink-900/90 p-0.5">
            <button
              className={`rounded-lg px-3 py-1 font-bold transition ${interactionMode === "move" ? "bg-emerald-600 text-emerald-950 shadow ring-1 ring-emerald-400" : "text-stone-300 hover:text-white"}`}
              onClick={() => onInteractionModeChange("move")}
              type="button"
            >
              🏃 移动走位
            </button>
            <button
              className={`rounded-lg px-3 py-1 font-bold transition ${interactionMode === "target" ? "bg-fuchsia-600 text-fuchsia-950 shadow ring-1 ring-fuchsia-400" : "text-stone-300 hover:text-white"}`}
              onClick={() => onInteractionModeChange("target")}
              type="button"
            >
              🔮 施法瞄准
            </button>
          </div>

          {/* Quick Step Buttons */}
          {interactionMode === "move" ? (
            <div className="flex items-center gap-1 rounded-xl border border-emerald-800/60 bg-emerald-950/40 px-2 py-0.5">
              <span className="text-emerald-300 text-[10px]">微调:</span>
              <button className="h-5 w-5 rounded bg-ink-950 text-emerald-300 hover:bg-emerald-900" onClick={() => handleStepMove(-1, 0)} type="button">⬆️</button>
              <button className="h-5 w-5 rounded bg-ink-950 text-emerald-300 hover:bg-emerald-900" onClick={() => handleStepMove(1, 0)} type="button">⬇️</button>
              <button className="h-5 w-5 rounded bg-ink-950 text-emerald-300 hover:bg-emerald-900" onClick={() => handleStepMove(0, -1)} type="button">⬅️</button>
              <button className="h-5 w-5 rounded bg-ink-950 text-emerald-300 hover:bg-emerald-900" onClick={() => handleStepMove(0, 1)} type="button">➡️</button>
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5">
          {/* Camera View Switcher */}
          <div className="flex rounded-xl border border-ink-700 bg-ink-900/90 p-0.5">
            <button
              className={`rounded-lg px-2.5 py-0.5 transition ${viewPerspective === "iso-3d" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setViewPerspective("iso-3d")}
              type="button"
            >
              📐 45° 3D
            </button>
            <button
              className={`rounded-lg px-2.5 py-0.5 transition ${viewPerspective === "high-3d" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setViewPerspective("high-3d")}
              type="button"
            >
              🦅 俯角 3D
            </button>
            <button
              className={`rounded-lg px-2.5 py-0.5 transition ${viewPerspective === "flat-2d" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"}`}
              onClick={() => setViewPerspective("flat-2d")}
              type="button"
            >
              🗺️ 2D 平面
            </button>
          </div>

          <button
            className={`rounded-xl border px-2.5 py-0.5 transition ${
              showEnemyThreat
                ? "border-rose-600 bg-rose-950/60 text-rose-200 font-bold"
                : "border-ink-700 bg-ink-900 text-stone-400 hover:text-stone-200"
            }`}
            onClick={() => setShowEnemyThreat(!showEnemyThreat)}
            type="button"
          >
            👹 威胁: {showEnemyThreat ? "开" : "关"}
          </button>
        </div>
      </div>

      {/* 3D Perspective Stage Container */}
      <div className="perspective-stage overflow-hidden rounded-xl border border-ink-800/80 bg-[#06080d] p-2 py-3 flex items-center justify-center min-h-[320px] max-h-[390px]">
        <div
          className={`grid gap-0.5 min-w-[420px] mx-auto ${
            viewPerspective === "iso-3d"
              ? "grid-3d-iso"
              : viewPerspective === "high-3d"
                ? "grid-3d-high"
                : "grid-2d-flat"
          }`}
          style={{ gridTemplateColumns: `repeat(${width}, minmax(28px, 1fr))` }}
        >
          {Array.from({ length: height }, (_, r) =>
            Array.from({ length: width }, (_, c) => {
              const row = r + 1;
              const col = c + 1;
              const point = { row, col };
              const cellKey = `${row}:${col}`;
              const fighter = fighters.find((f) => positions[f.id]?.[0] === row && positions[f.id]?.[1] === col);
              const isSelected = selectedTokenId === fighter?.id;
              const isActive = activeFighterId === fighter?.id;
              const isTarget = selectedTargetId === fighter?.id;

              const isEnemyMeleeThreat = enemyThreatCells.meleeKeys.has(cellKey);
              const isEnemyRangedThreat = enemyThreatCells.rangedKeys.has(cellKey);

              const distFromSelected = selectedPos
                ? gridDistanceFt({ row: selectedPos[0], col: selectedPos[1] }, point, cellSizeFt)
                : null;
              const canMoveHere = interactionMode === "move" && selectedFighter && !fighter && distFromSelected !== null && distFromSelected <= selectedRemaining && selectedRemaining > 0;

              const inCastRange = targeting && activePosition
                ? isAimPointInRange(activePosition, point, targeting.rangeFt, cellSizeFt)
                : false;
              const isAreaAffected = areaKeys.has(cellKey);
              const hasPing = pings.some((p) => p.row === row && p.col === col);
              const activeVfx = vfxEvents.filter((v) => v.row === row && v.col === col);

              const fighterElevFt = fighter ? combatantElevationFt(fighter) : 0;

              let cellCls = "border border-ink-800/80 bg-ink-900/70 hover:bg-ink-800/60";
              if (canMoveHere) {
                cellCls = "!bg-emerald-950/90 !border-2 !border-emerald-400 shadow-[0_0_14px_rgba(16,185,129,0.7)] hover:!bg-emerald-800/90 ring-2 ring-emerald-400 cursor-pointer animate-pulse";
              } else if (isAreaAffected && interactionMode === "target") {
                cellCls = "!bg-fuchsia-950/90 !border-2 !border-fuchsia-400 !shadow-[0_0_16px_rgba(217,70,239,0.8)] ring-2 ring-fuchsia-400";
              } else if (inCastRange && interactionMode === "target") {
                cellCls = "!bg-sky-950/70 !border-sky-400/80 ring-1 ring-sky-400/60";
              } else if (isEnemyMeleeThreat) {
                cellCls = "bg-rose-950/40 border-rose-700/60 shadow-[inset_0_0_8px_rgba(225,29,72,0.4)]";
              } else if (isEnemyRangedThreat) {
                cellCls = "bg-amber-950/20 border-amber-800/30";
              }

              return (
                <button
                  className={`relative aspect-square rounded border p-0.5 text-2xs transition-all duration-200 ${cellCls} ${fighter ? "cursor-pointer" : ""}`}
                  key={`${row}-${col}`}
                  onClick={() => {
                    if (fighter) {
                      setSelectedTokenId(fighter.id);
                      onTargetSelect(fighter.id);
                    } else if (canMoveHere && selectedFighter && distFromSelected !== null) {
                      moveMutation.mutate({
                        fighter: selectedFighter,
                        newRow: row,
                        newCol: col,
                        spentFt: distFromSelected,
                      });
                    }
                    if (interactionMode === "target" && inCastRange) {
                      onAimPointChange(point);
                    }
                  }}
                  onDoubleClick={(e) => {
                    e.preventDefault();
                    triggerPing(row, col);
                  }}
                  style={{
                    transform: viewPerspective !== "flat-2d" && fighterElevFt > 0 ? `translateY(-${fighterElevFt * 1.8}px)` : undefined,
                  }}
                  title={
                    fighter
                      ? `${fighter.display_name} (HP: ${fighter.hp}/${fighter.max_hp}, 高度: ${fighterElevFt}尺)`
                      : canMoveHere
                        ? `坐标 (${row}, ${col}) · 移动距离: ${distFromSelected} 尺 (点击位移并消耗 ${distFromSelected} 尺移动力)`
                        : isEnemyMeleeThreat
                          ? `坐标 (${row}, ${col}) · ⚠️ 敌方近战借机区 (5尺)`
                          : `坐标 (${row}, ${col})`
                  }
                  type="button"
                >
                  {/* 3D Volumetric Area of Effect (AoE) Extrusion Column */}
                  {isAreaAffected && interactionMode === "target" ? (
                    <div className="aoe-3d-volume flex items-center justify-center">
                      <span className="font-bold text-[8px] text-fuchsia-200 drop-shadow">3D AOE</span>
                    </div>
                  ) : null}

                  {/* Ping Animation Waves */}
                  {hasPing ? (
                    <span className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center">
                      <span className="absolute h-8 w-8 rounded-full border-2 border-amber-400 bg-amber-400/30 animate-ping" />
                      <span className="absolute h-3 w-3 rounded-full bg-amber-300 shadow-[0_0_8px_rgba(251,191,36,1)]" />
                    </span>
                  ) : null}

                  {/* Combat Visual Effects */}
                  {activeVfx.map((vfx) => (
                    <span className="pointer-events-none absolute inset-0 z-40 flex items-center justify-center overflow-visible" key={vfx.id}>
                      {vfx.type === "slash" ? (
                        <span className="absolute h-10 w-2.5 rounded-full bg-gradient-to-t from-red-600 via-amber-400 to-white animate-vfx-slash shadow-[0_0_15px_#f59e0b]" />
                      ) : null}

                      {vfx.type === "arcane" ? (
                        <span className="absolute h-8 w-8 rounded-full bg-gradient-to-r from-fuchsia-500 to-purple-600 animate-vfx-arcane-dart shadow-[0_0_20px_#d946ef]" />
                      ) : null}

                      {vfx.type === "shockwave" ? (
                        <span className="absolute h-12 w-12 rounded-full border-4 border-sky-400 bg-sky-500/20 animate-vfx-shockwave" />
                      ) : null}

                      {vfx.type === "smite" ? (
                        <span className="absolute h-16 w-3 rounded bg-gradient-to-b from-amber-200 via-yellow-400 to-amber-600 animate-vfx-smite shadow-[0_0_25px_#fef08a]" />
                      ) : null}

                      {vfx.type === "dust" ? (
                        <span className="absolute h-8 w-8 rounded-full border border-emerald-400/60 bg-emerald-400/20 animate-token-dust" />
                      ) : null}

                      {vfx.text ? (
                        <span
                          className={`absolute font-black font-mono text-xs drop-shadow-[0_2px_4px_rgba(0,0,0,1)] animate-float-combat-text ${
                            vfx.isCrit
                              ? "text-amber-300 text-sm scale-125"
                              : vfx.isMiss
                                ? "text-stone-400"
                                : "text-rose-400"
                          }`}
                        >
                          {vfx.text}
                        </span>
                      ) : null}
                    </span>
                  ))}

                  {/* Move Range Highlight Dot & High Visibility Distance Tag */}
                  {canMoveHere && !fighter ? (
                    <span className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                      <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" />
                      <span className="mt-0.5 text-[8px] font-mono text-emerald-200 font-bold bg-emerald-950/90 px-1 rounded border border-emerald-500/60">
                        {distFromSelected}尺
                      </span>
                    </span>
                  ) : null}

                  {/* 3D Elevated Token with Drop Shadow */}
                  {fighter ? (
                    <>
                      {fighterElevFt > 0 && viewPerspective !== "flat-2d" ? (
                        <div className="token-shadow" style={{ transform: `scale(${Math.max(0.4, 1 - fighterElevFt * 0.02)})` }} />
                      ) : null}

                      <div
                        className={`token-smooth-move relative flex h-full w-full flex-col items-center justify-center rounded-lg p-0.5 text-center leading-none shadow-lg transition-all ${
                          isActive
                            ? "ring-2 ring-amber-400 bg-gradient-to-br from-amber-500/40 to-ink-900"
                            : isTarget
                              ? "ring-2 ring-emerald-400 bg-emerald-950/70"
                              : isSelected
                                ? "ring-1 ring-sky-400 bg-sky-950/50"
                                : fighter.entity_type === "character"
                                  ? "bg-sky-950/70 border border-sky-600/60"
                                  : fighter.entity_type === "npc"
                                    ? "bg-violet-950/70 border border-violet-600/60"
                                    : "bg-red-950/70 border border-red-600/60"
                        }`}
                        style={{
                          transform: viewPerspective !== "flat-2d" && fighterElevFt > 0 ? `translateY(-${fighterElevFt * 1.5}px)` : undefined,
                        }}
                      >
                        <span className="truncate font-bold text-[10px] text-parchment-100 drop-shadow">
                          {fighter.display_name?.slice(0, 3)}
                        </span>
                        <span className="mt-0.5 text-[8px] font-mono text-stone-300">
                          {fighter.hp}/{fighter.max_hp}
                        </span>
                        {fighterElevFt > 0 ? (
                          <span className="mt-0.5 rounded bg-amber-400/90 px-1 text-[7px] font-black text-amber-950">
                            ▲{fighterElevFt}尺
                          </span>
                        ) : null}
                        {fighter.conditions && fighter.conditions.length > 0 ? (
                          <span className="mt-0.5 text-[7px] text-amber-300 font-bold">
                            {fighter.conditions[0].slice(0, 2)}
                          </span>
                        ) : null}
                      </div>
                    </>
                  ) : null}
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3. BG3 Floating Target Inspector Card
// ---------------------------------------------------------------------------
function BG3TargetInspector({
  target,
  activeFighter,
  positions,
  onQuickDamage,
}: {
  target: Combatant | null;
  activeFighter: Combatant | null;
  positions: Record<string, [number, number]>;
  onQuickDamage: (delta: number) => void;
}): ReactElement | null {
  if (!target) return null;

  const targetPos = positions[target.id];
  const activePos = activeFighter ? positions[activeFighter.id] : null;
  const distFt = targetPos && activePos ? gridDistanceFt({ row: activePos[0], col: activePos[1] }, { row: targetPos[0], col: targetPos[1] }, 5) : 0;
  const hpPercent = Math.max(0, Math.min(100, ((target.hp ?? 0) / (target.max_hp || 1)) * 100));

  return (
    <div className="bg3-panel flex flex-col justify-between rounded-2xl p-3 text-xs shadow-2xl border-amber-500/30">
      <div className="flex items-start justify-between gap-2 border-b border-ink-800 pb-2">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-rose-900 to-ink-950 border border-rose-600/60 font-bold text-rose-200">
            {target.display_name?.slice(0, 1)}
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <strong className="font-bold text-parchment-100">{target.display_name}</strong>
              <Badge tone={target.entity_type === "monster" ? "warn" : "ok"}>
                {target.entity_type === "monster" ? "敌方怪物" : target.entity_type === "character" ? "玩家" : "NPC"}
              </Badge>
            </div>
            <span className="text-[10px] text-stone-400">距离: <strong className="text-amber-300 font-mono">{distFt} 尺</strong></span>
          </div>
        </div>

        <div className="flex items-center gap-1 rounded-xl bg-ink-950 px-2 py-1 border border-ink-800">
          <span className="text-stone-400 text-2xs">护甲 AC</span>
          <strong className="text-amber-300 font-bold text-sm">{target.armor_class ?? 10}</strong>
        </div>
      </div>

      {/* HP Bar */}
      <div className="my-2 space-y-1">
        <div className="flex justify-between text-[10px] font-mono">
          <span className="text-stone-400">生命值 (HP)</span>
          <strong className="text-emerald-300">{target.hp} / {target.max_hp}</strong>
        </div>
        <div className="h-2 w-full overflow-hidden rounded-full bg-ink-950 border border-ink-800">
          <div
            className={`h-full transition-all duration-300 ${
              hpPercent > 50 ? "bg-emerald-500" : hpPercent > 20 ? "bg-amber-500" : "bg-rose-500"
            }`}
            style={{ width: `${hpPercent}%` }}
          />
        </div>
      </div>

      {/* Conditions & Resistances */}
      <div className="flex flex-wrap items-center gap-1 text-[9px]">
        {target.conditions && target.conditions.length > 0 ? (
          target.conditions.map((c) => (
            <span className="rounded bg-rose-950 border border-rose-700/60 px-1.5 py-0.2 text-rose-300 font-bold" key={c}>
              ⚠️ {c}
            </span>
          ))
        ) : (
          <span className="text-stone-500 text-[10px]">无负面状态</span>
        )}
      </div>

      {/* Quick HP adjustment buttons */}
      <div className="mt-2 flex items-center justify-between border-t border-ink-800/60 pt-1.5">
        <span className="text-[10px] text-stone-400">快速结算:</span>
        <div className="flex gap-1">
          <button className="rounded border border-rose-900 bg-rose-950/60 px-1.5 py-0.5 text-[10px] text-rose-300 hover:bg-rose-900" onClick={() => onQuickDamage(-5)}>-5</button>
          <button className="rounded border border-rose-900 bg-rose-950/60 px-1.5 py-0.5 text-[10px] text-rose-300 hover:bg-rose-900" onClick={() => onQuickDamage(-1)}>-1</button>
          <button className="rounded border border-emerald-900 bg-emerald-950/60 px-1.5 py-0.5 text-[10px] text-emerald-300 hover:bg-emerald-900" onClick={() => onQuickDamage(1)}>+1</button>
          <button className="rounded border border-emerald-900 bg-emerald-950/60 px-1.5 py-0.5 text-[10px] text-emerald-300 hover:bg-emerald-900" onClick={() => onQuickDamage(5)}>+5</button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 4. BG3 Classic Action Hotbar (Bottom Dock)
// ---------------------------------------------------------------------------
function BG3Hotbar({
  activeFighter,
  activeCharacter,
  selectedRemaining,
  selectedMaxSpeed,
  onResetSpeed,
  activeTab,
  onTabChange,
  spells,
  selectedSpell,
  selectedSpellLevel,
  onSelectSpell,
  onSelectSpellLevel,
  onCastSpell,
  isCasting,
  targetingValidity,
  onOpenMeleeAttack,
  onOpenRangedAttack,
  onOpenOpportunityAttack,
  onAdvanceTurn,
  isAdvancingTurn,
  onOpenMagicMissileModal,
  orderedFighters,
  campaignId,
  combatId,
  actions,
  autoEnemies,
  onAutoEnemiesChange,
  handleRangeChange,
  handleTargetChange,
  selectedTargetId,
  activeCombatRound,
  activeCombatIndex,
  onQuickHpAdjust,
  onLongRest,
  onExecuteMonsterAiAttack,
  isMonsterAiExecuting,
}: {
  activeFighter: Combatant | null;
  activeCharacter: any;
  selectedRemaining: number;
  selectedMaxSpeed: number;
  onResetSpeed: () => void;
  activeTab: "common" | "spells" | "weapons" | "features" | "skills" | "conditions" | "rules" | "monster";
  onTabChange: (tab: "common" | "spells" | "weapons" | "features" | "skills" | "conditions" | "rules" | "monster") => void;
  spells: CombatSpellOption[];
  selectedSpell: CombatSpellOption | null;
  selectedSpellLevel: number;
  onSelectSpell: (spell: CombatSpellOption) => void;
  onSelectSpellLevel: (lvl: number) => void;
  onCastSpell: () => void;
  isCasting: boolean;
  targetingValidity: CombatTargetingValidity;
  onOpenMeleeAttack: () => void;
  onOpenRangedAttack: () => void;
  onOpenOpportunityAttack: () => void;
  onAdvanceTurn: () => void;
  isAdvancingTurn: boolean;
  onOpenMagicMissileModal: () => void;
  orderedFighters: Combatant[];
  campaignId: string;
  combatId: string;
  actions: CombatAction[];
  autoEnemies: boolean;
  onAutoEnemiesChange: (auto: boolean) => void;
  handleRangeChange: (range: CombatTargeting | null, actorId?: string | null) => void;
  handleTargetChange: (id: string) => void;
  selectedTargetId: string;
  activeCombatRound: number;
  activeCombatIndex: number;
  onQuickHpAdjust: (fighter: Combatant, delta: number) => void;
  onLongRest: () => void;
  onExecuteMonsterAiAttack: () => void;
  isMonsterAiExecuting: boolean;
}): ReactElement {
  const [spellFilter, setSpellFilter] = useState<"all" | 0 | 1 | 2 | 3>("all");

  const isMonster = activeFighter?.entity_type === "monster";
  const spellSlots = useMemo(() => getCombatantSpellSlots(activeFighter), [activeFighter]);
  const turnResources = useMemo(() => getCombatantTurnResources(activeFighter), [activeFighter]);

  const filteredSpells = useMemo(() => {
    if (spellFilter === "all") return spells;
    return spells.filter((s) => s.level === spellFilter);
  }, [spells, spellFilter]);

  const movePercent = Math.max(0, Math.min(100, (selectedRemaining / (selectedMaxSpeed || 1)) * 100));

  const hasSlotForCurrent = selectedSpellLevel === 0 || (spellSlots[selectedSpellLevel] ?? 0) > 0;
  const hasActionForCurrent = selectedSpell?.castTime.includes("附赠")
    ? turnResources.bonus_action
    : turnResources.action;

  const upcastPreview = selectedSpell ? getSpellUpcastPreview(selectedSpell, selectedSpellLevel) : null;

  return (
    <div className="bg3-hotbar-dock rounded-2xl p-3 shadow-2xl">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12 items-center">
        {/* Left Wing: Character Profile & Action Economy (3 Cols) */}
        <div className="flex items-center gap-3 lg:col-span-3 border-b lg:border-b-0 lg:border-r border-ink-800/80 pb-2 lg:pb-0 pr-2">
          {/* Avatar & Class */}
          <div className={`relative flex h-14 w-14 shrink-0 flex-col items-center justify-center rounded-2xl border-2 shadow-lg ${
            isMonster
              ? "bg-gradient-to-b from-rose-900/60 via-ink-900 to-ink-950 border-rose-500/70"
              : "bg-gradient-to-b from-amber-700/40 via-ink-900 to-ink-950 border-amber-500/70"
          }`}>
            <span className="text-xl">{isMonster ? "👹" : "🛡️"}</span>
            <span className="absolute -bottom-1 rounded bg-ink-950 px-1 text-[8px] font-mono font-bold text-amber-300 border border-amber-500/50">
              AC {activeFighter?.armor_class ?? 10}
            </span>
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between">
              <strong className={`truncate text-xs font-bold ${isMonster ? "text-rose-200" : "text-parchment-100"}`}>
                {activeFighter?.display_name ?? "行动者"}
              </strong>
              <span className="text-[10px] text-amber-300 font-mono">
                HP {activeFighter?.hp}/{activeFighter?.max_hp}
              </span>
            </div>

            {/* Movement Speed Gauge */}
            <div className="mt-1.5 space-y-0.5">
              <div className="flex items-center justify-between text-[9px] text-stone-400">
                <span>🏃 移动力: <strong className={`font-mono ${selectedRemaining > 0 ? "text-emerald-300" : "text-rose-400"}`}>{selectedRemaining}</strong>/{selectedMaxSpeed}尺</span>
                <button
                  className="text-[8px] text-emerald-400 hover:underline"
                  onClick={onResetSpeed}
                  type="button"
                >
                  重置满速
                </button>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-ink-950 border border-ink-800">
                <div
                  className={`h-full transition-all duration-300 ${
                    selectedRemaining > 0 ? "bg-gradient-to-r from-emerald-600 to-emerald-400" : "bg-rose-900"
                  }`}
                  style={{ width: `${movePercent}%` }}
                />
              </div>
            </div>

            {/* Action Economy Gems & Spell Slots */}
            <div className="mt-1.5 flex flex-wrap items-center justify-between gap-1 text-[9px]">
              <div className="flex items-center gap-1.5">
                <span className="flex items-center gap-0.5" title={`标准动作: ${turnResources.action ? "可用" : "已耗尽"}`}>
                  <span className={`h-2.5 w-2.5 rounded-full inline-block ${turnResources.action ? "bg3-gem-action" : "bg3-gem-empty"}`} />
                  <span className={turnResources.action ? "text-emerald-300" : "text-stone-500 line-through"}>动作</span>
                </span>
                <span className="flex items-center gap-0.5" title={`附赠动作: ${turnResources.bonus_action ? "可用" : "已耗尽"}`}>
                  <span className={`h-2.5 w-2.5 rounded-full inline-block ${turnResources.bonus_action ? "bg3-gem-bonus" : "bg3-gem-empty"}`} />
                  <span className={turnResources.bonus_action ? "text-orange-300" : "text-stone-500 line-through"}>附赠</span>
                </span>
                <span className="flex items-center gap-0.5" title={`反应: ${turnResources.reaction ? "可用" : "已耗尽"}`}>
                  <span className={`h-2.5 w-2.5 rounded-full inline-block ${turnResources.reaction ? "bg3-gem-reaction" : "bg3-gem-empty"}`} />
                  <span className={turnResources.reaction ? "text-purple-300" : "text-stone-500 line-through"}>反应</span>
                </span>
              </div>

              {/* Spell slot indicator */}
              {!isMonster ? (
                <span className="text-[8px] font-mono text-fuchsia-300" title="1环/2环/3环 剩余法术位">
                  🔮 {spellSlots[1]}·{spellSlots[2]}·{spellSlots[3]}位
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {/* Center Deck: Multi-Drawer Action Hotbar (6 Cols) */}
        <div className="lg:col-span-6 flex flex-col justify-between">
          {/* Drawer Category Tabs */}
          <div className="flex flex-wrap items-center gap-1 border-b border-ink-800/80 pb-1.5 text-2xs font-bold">
            {isMonster ? (
              <button
                className={`rounded-lg px-2.5 py-1 transition ${activeTab === "monster" || activeTab === "common" ? "bg-rose-600 text-rose-950 shadow" : "text-stone-400 hover:text-white"}`}
                onClick={() => onTabChange("monster")}
                type="button"
              >
                👹 怪物战术动作
              </button>
            ) : null}
            <button
              className={`rounded-lg px-2.5 py-1 transition ${activeTab === "common" && !isMonster ? "bg-emerald-600 text-emerald-950 shadow" : "text-stone-400 hover:text-white"}`}
              onClick={() => onTabChange("common")}
              type="button"
            >
              🏃 常用动作
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${activeTab === "spells" ? "bg-fuchsia-600 text-fuchsia-950 shadow" : "text-stone-400 hover:text-white"}`}
              onClick={() => onTabChange("spells")}
              type="button"
            >
              🔮 法术书 (0~3环)
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${activeTab === "weapons" ? "bg-amber-600 text-amber-950 shadow" : "text-stone-400 hover:text-white"}`}
              onClick={() => onTabChange("weapons")}
              type="button"
            >
              ⚔️ 武器攻击
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${activeTab === "features" ? "bg-purple-600 text-purple-950 shadow" : "text-stone-400 hover:text-white"}`}
              onClick={() => onTabChange("features")}
              type="button"
            >
              🛡️ 职业特技
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${activeTab === "skills" ? "bg-sky-600 text-sky-950 shadow" : "text-stone-400 hover:text-white"}`}
              onClick={() => onTabChange("skills")}
              type="button"
            >
              🎯 技能
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${activeTab === "conditions" ? "bg-rose-600 text-rose-950 shadow" : "text-stone-400 hover:text-white"}`}
              onClick={() => onTabChange("conditions")}
              type="button"
            >
              🏷️ 状态
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${activeTab === "rules" ? "bg-amber-700 text-amber-100 shadow" : "text-stone-400 hover:text-white"}`}
              onClick={() => onTabChange("rules")}
              type="button"
            >
              📦 规则积木
            </button>
          </div>

          {/* Drawer Content Area */}
          <div className="mt-2 min-h-[68px] flex items-center">
            {/* Monster AI Action Tab */}
            {isMonster || activeTab === "monster" ? (
              <div className="flex flex-wrap items-center gap-2 w-full">
                <button
                  className="bg3-btn-slot flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold text-rose-200 border-rose-500 bg-rose-950/80 hover:bg-rose-900 shadow-[0_0_12px_rgba(244,63,94,0.5)]"
                  disabled={isMonsterAiExecuting}
                  onClick={onExecuteMonsterAiAttack}
                  type="button"
                >
                  <span>👹 自动执行怪物 AI 战术攻击</span>
                  <span className="text-[9px] text-amber-300">智能索敌·移动·命中检定</span>
                </button>
                <button
                  className="bg3-btn-slot flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold text-amber-200"
                  onClick={onOpenMeleeAttack}
                  type="button"
                >
                  <span>🗡️ 爪抓/撕咬攻击 (1d6+2 挥砍)</span>
                </button>
                <button
                  className="bg3-btn-slot flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold text-sky-200"
                  onClick={onOpenRangedAttack}
                  type="button"
                >
                  <span>🏹 短弓远程射击 (1d6+2 穿刺)</span>
                </button>
              </div>
            ) : null}

            {/* 1. Common Actions */}
            {activeTab === "common" && !isMonster ? (
              <div className="flex flex-wrap items-center gap-1.5 w-full">
                <button
                  className="bg3-btn-slot flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold text-emerald-200"
                  onClick={onResetSpeed}
                  type="button"
                >
                  <span>⚡ 疾走 (Dash)</span>
                  <span className="text-[9px] text-stone-400">+30尺</span>
                </button>
                <button
                  className="bg3-btn-slot flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold text-sky-200"
                  onClick={() => soundboard.playDiceRoll()}
                  type="button"
                >
                  <span>🛡️ 撤退 (Disengage)</span>
                </button>
                <button
                  className="bg3-btn-slot flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold text-amber-200"
                  onClick={() => soundboard.playDiceRoll()}
                  type="button"
                >
                  <span>🤝 协助 (Help)</span>
                </button>
                <button
                  className="bg3-btn-slot flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold text-stone-300"
                  onClick={() => soundboard.playDiceRoll()}
                  type="button"
                >
                  <span>🌫️ 躲藏 (Hide)</span>
                </button>
                <button
                  className="bg3-btn-slot flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-xs font-bold text-rose-300"
                  onClick={() => soundboard.playAttackHit()}
                  type="button"
                >
                  <span>💥 推撞 (Shove)</span>
                </button>
              </div>
            ) : null}

            {/* 2. Spells & Upcast Selector with Live Slot Tracking & Upcast Bonus Preview */}
            {activeTab === "spells" && !isMonster ? (
              <div className="w-full space-y-1.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-1 text-[9px]">
                    <button className={`rounded px-1.5 py-0.2 ${spellFilter === "all" ? "bg-fuchsia-600 font-bold text-white" : "bg-ink-950 text-stone-400"}`} onClick={() => setSpellFilter("all")}>全部</button>
                    <button className={`rounded px-1.5 py-0.2 ${spellFilter === 0 ? "bg-fuchsia-600 font-bold text-white" : "bg-ink-950 text-stone-400"}`} onClick={() => setSpellFilter(0)}>戏法 (无限)</button>
                    <button className={`rounded px-1.5 py-0.2 ${spellFilter === 1 ? "bg-fuchsia-600 font-bold text-white" : "bg-ink-950 text-stone-400"}`} onClick={() => setSpellFilter(1)}>1环 ({spellSlots[1]}位)</button>
                    <button className={`rounded px-1.5 py-0.2 ${spellFilter === 2 ? "bg-fuchsia-600 font-bold text-white" : "bg-ink-950 text-stone-400"}`} onClick={() => setSpellFilter(2)}>2环 ({spellSlots[2]}位)</button>
                    <button className={`rounded px-1.5 py-0.2 ${spellFilter === 3 ? "bg-fuchsia-600 font-bold text-white" : "bg-ink-950 text-stone-400"}`} onClick={() => setSpellFilter(3)}>3环 ({spellSlots[3]}位)</button>
                    <button
                      className="rounded border border-fuchsia-800/60 bg-fuchsia-950/60 px-1.5 py-0.2 text-[9px] text-fuchsia-300 hover:bg-fuchsia-900 ml-1"
                      onClick={onLongRest}
                      title="恢复全部法术位与动作"
                      type="button"
                    >
                      🌙 长休恢复
                    </button>
                  </div>

                  {/* Upcast Level Picker */}
                  {selectedSpell ? (
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] text-fuchsia-300 font-bold">升环选择:</span>
                      <div className="flex rounded-lg border border-fuchsia-700 bg-ink-950 p-0.5 text-[9px] font-bold">
                        {selectedSpell.level === 0 ? (
                          <span className="px-2 py-0.2 text-fuchsia-300">0环戏法</span>
                        ) : (
                          Array.from({ length: 4 - selectedSpell.level }, (_, idx) => {
                            const slotLvl = selectedSpell.level + idx;
                            const slotCount = spellSlots[slotLvl] ?? 0;
                            const isPicked = selectedSpellLevel === slotLvl;
                            return (
                              <button
                                className={`rounded px-1.5 py-0.2 transition ${
                                  isPicked
                                    ? "bg-fuchsia-600 text-white shadow"
                                    : slotCount > 0
                                      ? "text-stone-300 hover:text-white"
                                      : "text-stone-600 opacity-40"
                                }`}
                                key={slotLvl}
                                onClick={() => onSelectSpellLevel(slotLvl)}
                                type="button"
                              >
                                {slotLvl}环 ({slotCount}位)
                              </button>
                            );
                          })
                        )}
                      </div>
                    </div>
                  ) : null}
                </div>

                {/* Upcast Bonus Live Preview Banner */}
                {upcastPreview && selectedSpell ? (
                  <div className="flex items-center justify-between rounded-xl border border-fuchsia-500/40 bg-fuchsia-950/40 px-2.5 py-1 text-2xs">
                    <div className="flex items-center gap-1.5">
                      <span className="font-bold text-fuchsia-300">🔮 升环效果:</span>
                      <span className="text-stone-200">{upcastPreview.bonusText}</span>
                    </div>
                    <div className="flex items-center gap-1.5 font-mono">
                      <span className="rounded bg-fuchsia-900/80 px-2 py-0.2 text-fuchsia-200 font-bold border border-fuchsia-500/50">
                        {upcastPreview.diceText}
                      </span>
                      <span className="text-amber-300 font-bold">
                        {selectedSpell.damageType === "healing" ? "💚 治疗" : `⚡ ${selectedSpell.damageType} 效果`}
                      </span>
                    </div>
                  </div>
                ) : null}

                {/* Spell Cards List */}
                <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar py-0.5">
                  {filteredSpells.map((s) => {
                    const isPicked = selectedSpell?.id === s.id;
                    const slotCount = s.level === 0 ? 99 : (spellSlots[s.level] ?? 0);
                    return (
                      <button
                        className={`bg3-btn-slot shrink-0 rounded-xl px-2.5 py-1 text-left ${
                          isPicked ? "border-fuchsia-400 bg-fuchsia-950/80 ring-1 ring-fuchsia-400" : ""
                        } ${slotCount === 0 ? "opacity-40" : ""}`}
                        key={s.id}
                        onClick={() => onSelectSpell(s)}
                        type="button"
                      >
                        <div className="flex items-center justify-between gap-1.5">
                          <strong className="text-2xs font-bold text-parchment-100">{s.name}</strong>
                          <span className="text-[8px] font-mono text-fuchsia-300">{s.level === 0 ? "0环" : `${s.level}环`}</span>
                        </div>
                        <span className="text-[8px] font-mono text-amber-300 block">{s.damageDiceBase}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}

            {/* 3. Weapons */}
            {activeTab === "weapons" ? (
              <div className="flex flex-wrap items-center gap-2 w-full">
                <button
                  className="bg3-btn-slot flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-bold text-amber-200"
                  onClick={onOpenMeleeAttack}
                  type="button"
                >
                  <span>🗡️ 主手近战重击</span>
                  <span className="text-[9px] text-stone-400">1d8+3 挥砍</span>
                </button>
                <button
                  className="bg3-btn-slot flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-bold text-sky-200"
                  onClick={onOpenRangedAttack}
                  type="button"
                >
                  <span>🏹 远程精准射击</span>
                  <span className="text-[9px] text-stone-400">1d8+3 穿刺 (150尺)</span>
                </button>
                <button
                  className="bg3-btn-slot flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-bold text-rose-200"
                  onClick={onOpenOpportunityAttack}
                  type="button"
                >
                  <span>⚡ 借机攻击 (反应)</span>
                </button>
              </div>
            ) : null}

            {/* 4. Features */}
            {activeTab === "features" ? (
              <div className="flex flex-wrap items-center gap-2 w-full">
                <button
                  className="bg3-btn-slot flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-bold text-emerald-200"
                  onClick={() => {
                    if (!activeFighter) return;
                    const heal = Math.floor(Math.random() * 10) + 1 + 3;
                    onQuickHpAdjust(activeFighter, heal);
                    soundboard.playNat20();
                  }}
                  type="button"
                >
                  <span>🛡️ 战士回气 (Second Wind)</span>
                  <span className="text-[9px] text-stone-400">+1d10+3 HP</span>
                </button>
                <button
                  className="bg3-btn-slot flex items-center gap-2 rounded-xl px-3 py-1.5 text-xs font-bold text-amber-200"
                  onClick={() => soundboard.playNat20()}
                  type="button"
                >
                  <span>⚖️ 至圣斩 (Divine Smite)</span>
                  <span className="text-[9px] text-stone-400">+2d8 光耀</span>
                </button>
              </div>
            ) : null}

            {/* 5. Skills */}
            {activeTab === "skills" ? (
              <div className="flex items-center gap-1 overflow-x-auto no-scrollbar py-1 w-full">
                {DND_SKILLS.slice(0, 8).map((skill) => (
                  <button
                    className="bg3-btn-slot shrink-0 rounded-xl px-2.5 py-1 text-2xs font-bold text-sky-200"
                    key={skill.id}
                    onClick={() => soundboard.playDiceRoll()}
                    type="button"
                  >
                    🎲 {skill.name.split(" ")[0]}
                  </button>
                ))}
              </div>
            ) : null}

            {/* 6. Conditions */}
            {activeTab === "conditions" ? (
              <div className="flex items-center gap-1 overflow-x-auto no-scrollbar py-1 w-full">
                {DND_CONDITIONS.slice(0, 8).map((cond) => (
                  <button
                    className="bg3-btn-slot shrink-0 rounded-xl px-2 py-1 text-2xs font-bold text-rose-200"
                    key={cond.id}
                    onClick={() => soundboard.playHandout()}
                    type="button"
                  >
                    {cond.icon} {cond.name.split(" ")[0]}
                  </button>
                ))}
              </div>
            ) : null}

            {/* 7. Rules Console */}
            {activeTab === "rules" && activeFighter ? (
              <div className="w-full overflow-y-auto max-h-24">
                <TurnCommandConsole
                  active={activeFighter}
                  activeCharacter={activeCharacter}
                  autoEnemies={autoEnemies}
                  automationReady={true}
                  campaignId={campaignId}
                  combatActions={actions}
                  combatId={combatId}
                  fighters={orderedFighters}
                  key={`${combatId}:${activeFighter.id}`}
                  onAutoEnemiesChange={onAutoEnemiesChange}
                  onEnemyTurnComplete={onAdvanceTurn}
                  onRangeChange={handleRangeChange}
                  onTargetChange={handleTargetChange}
                  selectedTargetId={selectedTargetId}
                  targetingValidity={targetingValidity}
                  turnKey={`${activeCombatRound}:${activeCombatIndex}:${activeFighter.id}`}
                />
              </div>
            ) : null}
          </div>
        </div>

        {/* Right Wing: Turn End Gold Button & Cast Action (3 Cols) */}
        <div className="flex items-center justify-end gap-2 lg:col-span-3 border-t lg:border-t-0 lg:border-l border-ink-800/80 pt-2 lg:pt-0 pl-2">
          {activeTab === "spells" && selectedSpell && !isMonster ? (
            selectedSpell.id === "magic_missile" ? (
              <button
                className="rounded-xl border border-fuchsia-500 bg-fuchsia-600 px-4 py-2.5 text-xs font-bold text-white shadow hover:brightness-110 disabled:opacity-50"
                disabled={!hasSlotForCurrent || !hasActionForCurrent}
                onClick={onOpenMagicMissileModal}
                type="button"
              >
                {!hasActionForCurrent ? "⚠️ 动作已用" : !hasSlotForCurrent ? "⚠️ 环位已空" : `🚀 分配飞弹 (${3 + Math.max(0, selectedSpellLevel - 1)}枚)`}
              </button>
            ) : (
              <button
                className="rounded-xl border border-fuchsia-500 bg-gradient-to-r from-fuchsia-600 to-purple-600 px-4 py-2.5 text-xs font-bold text-white shadow hover:brightness-110 disabled:opacity-50"
                disabled={isCasting || !hasSlotForCurrent || !hasActionForCurrent}
                onClick={onCastSpell}
                type="button"
              >
                {isCasting
                  ? "施法中…"
                  : !hasActionForCurrent
                    ? "⚠️ 动作已耗尽"
                    : !hasSlotForCurrent
                      ? `⚠️ ${selectedSpellLevel}环位耗尽`
                      : `✨ 施放【${selectedSpell.name}】(${selectedSpellLevel}环)`}
              </button>
            )
          ) : isMonster ? (
            <button
              className="rounded-2xl border border-rose-500 bg-gradient-to-r from-rose-600 to-amber-600 px-5 py-3 text-xs font-black text-white shadow-2xl active:scale-95 transition"
              disabled={isMonsterAiExecuting}
              onClick={onExecuteMonsterAiAttack}
              type="button"
            >
              {isMonsterAiExecuting ? "🤖 怪物执行中…" : "👹 怪物 AI 攻击"}
            </button>
          ) : (
            <button
              className="bg3-end-turn-btn flex items-center justify-center gap-2 rounded-2xl px-5 py-3 text-xs font-black text-amber-950 shadow-2xl active:scale-95 transition"
              disabled={isAdvancingTurn}
              onClick={onAdvanceTurn}
              type="button"
            >
              <span>⏭️ 结束回合</span>
              <span className="rounded bg-amber-950/40 px-1 text-[9px] text-amber-200">Space</span>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Quick Combat Cockpit Page with Baldur's Gate 3 (BG3) UI Layout
// ---------------------------------------------------------------------------
function QuickCombatCockpit({ campaignId }: { campaignId: string }): ReactElement {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { selectCampaign } = useCurrentCampaign();

  const [selectedCombatId, setSelectedCombatId] = useState<string>("");
  const [selectedMapTargetId, setSelectedMapTargetId] = useState<string>("");
  const [gridInteractionMode, setGridInteractionMode] = useState<"move" | "target">("move");
  const [aimPoint, setAimPoint] = useState<GridPoint | null>(null);

  const [targetingRange, setTargetingRange] = useState<CombatTargeting | null>(null);
  const [targetingActorId, setTargetingActorId] = useState<string | null>(null);
  const [autoEnemies, setAutoEnemies] = useState<boolean>(false);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const [showAddCombatantModal, setShowAddCombatantModal] = useState<boolean>(false);

  // Visual Effects (VFX) Queue
  const [vfxEvents, setVfxEvents] = useState<VfxEvent[]>([]);

  const spawnVfx = useCallback((event: Omit<VfxEvent, "id">) => {
    const id = `${Date.now()}-${Math.random()}`;
    setVfxEvents((prev) => [...prev, { ...event, id }]);
    setTimeout(() => {
      setVfxEvents((prev) => prev.filter((e) => e.id !== id));
    }, 1200);
  }, []);

  // BG3 Hotbar Active Tab
  const [activeHotbarTab, setActiveHotbarTab] = useState<"common" | "spells" | "weapons" | "features" | "skills" | "conditions" | "rules" | "monster">("common");

  // Spell Casting Engine States
  const [selectedSpell, setSelectedSpell] = useState<CombatSpellOption | null>(DND_TEST_SPELLS[0]);
  const [selectedSpellLevel, setSelectedSpellLevel] = useState<number>(0);

  // Quick Dice Box
  const [customDiceMod, setCustomDiceMod] = useState<string>("3");
  const [diceHistory, setDiceHistory] = useState<Array<{ id: string; formula: string; result: number; rolls: number[]; isCrit?: boolean }>>([]);

  // New combatant form
  const [newCombatantName, setNewCombatantName] = useState<string>("");
  const [newCombatantType, setNewCombatantType] = useState<"character" | "monster" | "npc">("monster");
  const [newCombatantHp, setNewCombatantHp] = useState<string>("12");
  const [newCombatantAc, setNewCombatantAc] = useState<string>("14");
  const [newCombatantInit, setNewCombatantInit] = useState<string>("10");

  // Interactive Dice Prompt / Action HUD States
  const [actionPromptOpen, setActionPromptOpen] = useState<boolean>(false);
  const [promptActionName, setPromptActionName] = useState<string>("近战武器攻击");
  const [promptTargetId, setPromptTargetId] = useState<string>("");
  const [promptAttackMod, setPromptAttackMod] = useState<string>("4");
  const [promptDamageDice, setPromptDamageDice] = useState<string>("1d8+2");
  const [promptDamageType, setPromptDamageType] = useState<string>("slashing");
  const [isMeleeAttack, setIsMeleeAttack] = useState<boolean>(true);
  const [manualAttackRoll, setManualAttackRoll] = useState<string>("");
  const [manualDamageRoll, setManualDamageRoll] = useState<string>("");
  const [isManualCrit, setIsManualCrit] = useState<boolean>(false);

  // Magic Missile Multi-Target Distribution state
  const [magicMissileModalOpen, setMagicMissileModalOpen] = useState<boolean>(false);
  const [dartAllocations, setDartAllocations] = useState<Record<string, number>>({});

  // AI Guidance states
  const [aiAnalysis, setAiAnalysis] = useState<string>("");

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

  // Ordered combatants
  const ordered = useMemo(() => {
    const items = [...(combatantsQuery.data ?? [])];
    return items.sort((a, b) => (b.initiative ?? 0) - (a.initiative ?? 0));
  }, [combatantsQuery.data]);

  // Positions map
  const positions = useMemo(() => {
    const map: Record<string, [number, number]> = {};
    ordered.forEach((f, i) => {
      const pos = combatantGridPosition(f);
      if (pos) {
        map[f.id] = pos;
      } else {
        const isPlayer = f.entity_type === "character";
        const row = isPlayer ? Math.floor(i / 3) + 2 : Math.floor(i / 3) + 2;
        const col = isPlayer ? (i % 3) + 2 : 11 - (i % 3);
        map[f.id] = [row, col];
      }
    });
    return map;
  }, [ordered]);

  // Active Fighter
  const activeFighter = useMemo(() => {
    if (!ordered.length) return null;
    const index = (activeCombat?.current_turn_index ?? activeCombat?.active_combatant_index ?? 0) % ordered.length;
    return ordered[index] ?? ordered[0] ?? null;
  }, [ordered, activeCombat?.current_turn_index, activeCombat?.active_combatant_index]);

  const activePos = activeFighter ? positions[activeFighter.id] : null;
  const activePosition: GridPoint | null = useMemo(() => (activePos ? { row: activePos[0], col: activePos[1] } : null), [activePos]);

  const activeCharacter = useMemo(() => {
    if (!activeFighter || activeFighter.entity_type !== "character") return undefined;
    return (charactersQuery.data ?? []).find((c) => c.id === activeFighter.entity_id);
  }, [activeFighter, charactersQuery.data]);

  // Target Combatant for Action Prompt
  const promptTargetCombatant = useMemo(() => {
    return ordered.find((f) => f.id === (promptTargetId || selectedMapTargetId)) ?? ordered.find((f) => f.id !== activeFighter?.id) ?? null;
  }, [ordered, promptTargetId, selectedMapTargetId, activeFighter]);

  // Calculate targeting area cells purely
  const areaCells = useMemo(() => {
    if (!targetingRange || !activePosition) return [];
    const tacticalGrid: SceneGrid = { width: 12, height: 10, cell_size_ft: 5, cells: [], spawn_zones: [], theme: "dungeon" };
    return getTargetingCells(tacticalGrid, activePosition, aimPoint ?? activePosition, targetingRange);
  }, [targetingRange, activePosition, aimPoint]);

  const areaKeys = useMemo(() => new Set(areaCells.map((c) => `${c.row}:${c.col}`)), [areaCells]);

  // Pure derived targeting validity
  const targetingValidity = useMemo<CombatTargetingValidity>(() => {
    if (!targetingRange || !activePosition) {
      return {
        anchorPoint: null,
        horizontalTargetIds: new Set(),
        validTargetIds: new Set(),
        missingElevationTargetIds: new Set(),
      };
    }
    const horizontalTargetIds = new Set<string>();
    const validTargetIds = new Set<string>();
    const missingElevationTargetIds = new Set<string>();

    ordered.forEach((f) => {
      if (f.id === (targetingActorId ?? activeFighter?.id) || (f.hp ?? 0) <= 0) return;
      const pos = positions[f.id];
      if (!pos) return;
      const key = `${pos[0]}:${pos[1]}`;
      const inArea = targetingRange.shape === "single"
        ? isAimPointInRange(activePosition, { row: pos[0], col: pos[1] }, targetingRange.rangeFt, 5)
        : areaKeys.has(key);

      if (!inArea) return;
      horizontalTargetIds.add(f.id);
      validTargetIds.add(f.id);
    });

    return {
      anchorPoint: aimPoint ?? (targetingRange.originSelf ? activePosition : null),
      horizontalTargetIds,
      validTargetIds,
      missingElevationTargetIds,
    };
  }, [targetingRange, activePosition, aimPoint, ordered, positions, targetingActorId, activeFighter?.id, areaKeys]);

  const handleRangeChange = useCallback((range: CombatTargeting | null, actorId?: string | null) => {
    setTargetingRange((prev) => {
      if (!range && !prev) return prev;
      if (
        range &&
        prev &&
        range.label === prev.label &&
        range.rangeFt === prev.rangeFt &&
        range.shape === prev.shape &&
        range.sizeFt === prev.sizeFt &&
        range.originSelf === prev.originSelf
      ) {
        return prev;
      }
      return range;
    });
    setTargetingActorId((prev) => (prev === (actorId ?? null) ? prev : (actorId ?? null)));
  }, []);

  const handleTargetChange = useCallback((id: string) => {
    setSelectedMapTargetId((prev) => (prev === id ? prev : id));
    setPromptTargetId((prev) => (prev === id ? prev : id));
  }, []);

  // When a spell is picked, auto-update 3D grid targeting range and area
  const handleSelectSpell = useCallback((spell: CombatSpellOption) => {
    setSelectedSpell(spell);
    setSelectedSpellLevel(spell.level);
    setGridInteractionMode("target");
    setTargetingRange({
      label: spell.name,
      rangeFt: spell.rangeFt,
      shape: spell.shape,
      sizeFt: spell.sizeFt,
      originSelf: spell.originSelf,
    });
    setTargetingActorId(activeFighter?.id ?? null);
    showToast(`🔮 已选择「${spell.name}」：请在 3D 地图上选定目标并查看范围！`, "info");
  }, [activeFighter, showToast]);

  // Advance Turn mutation (Restores movement & turn actions for the next fighter!)
  const advanceTurnMutation = useMutation({
    mutationFn: async () => {
      if (!activeCombat) throw new Error("没有活跃的战斗");

      // Advance turn in server
      const res = await advanceCombatTurn(campaignId, activeCombat.id, activeCombat.version);

      // Reset movement & turn actions for next active fighter
      const nextIndex = (res.current_turn_index ?? res.active_combatant_index ?? 0) % (ordered.length || 1);
      const nextFighter = ordered[nextIndex];
      if (nextFighter) {
        const snap = {
          ...(nextFighter.snapshot_json as Record<string, unknown> | undefined),
          turn_resources: { action: true, bonus_action: true, reaction: true },
        };
        await updateCombatant(
          campaignId,
          activeCombat.id,
          nextFighter.id,
          {
            movement_remaining_ft: nextFighter.speed_ft ?? 30,
            snapshot_json: snap,
          },
          nextFighter.version,
        );
      }

      return res;
    },
    onSuccess: () => {
      soundboard.playDiceRoll();
      void queryClient.invalidateQueries({ queryKey: ["combats", campaignId] });
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      showToast("⏭️ 已进入下一战斗员回合！移动力与动作已恢复！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "推进回合失败", "error");
    },
  });

  // Monster AI Auto Attack Mutation
  const monsterAiAttackMutation = useMutation({
    mutationFn: async () => {
      if (!activeFighter || activeFighter.entity_type !== "monster") return;
      // 1. Find alive player characters
      const alivePcs = ordered.filter((f) => f.entity_type === "character" && (f.hp ?? 0) > 0);
      if (!alivePcs.length) {
        showToast("场上没有存活的玩家角色", "info");
        return;
      }

      // Find nearest PC
      const monsterPos = positions[activeFighter.id] ?? [3, 7];
      let nearestPc = alivePcs[0];
      let minDistance = 999;
      for (const pc of alivePcs) {
        const pcPos = positions[pc.id] ?? [3, 3];
        const dist = gridDistanceFt({ row: monsterPos[0], col: monsterPos[1] }, { row: pcPos[0], col: pcPos[1] }, 5);
        if (dist < minDistance) {
          minDistance = dist;
          nearestPc = pc;
        }
      }

      const targetPos = positions[nearestPc.id] ?? [3, 3];

      // 2. If farther than 5ft, move closer
      let updatedActor = activeFighter;
      if (minDistance > 5) {
        const dRow = Math.sign(targetPos[0] - monsterPos[0]);
        const dCol = Math.sign(targetPos[1] - monsterPos[1]);
        const newRow = Math.max(1, Math.min(10, monsterPos[0] + dRow));
        const newCol = Math.max(1, Math.min(12, monsterPos[1] + dCol));
        
        spawnVfx({ row: newRow, col: newCol, type: "dust", text: "-5尺" });
        updatedActor = await updateCombatant(campaignId, combatId, activeFighter.id, {
          movement_remaining_ft: Math.max(0, (activeFighter.movement_remaining_ft ?? 30) - 5),
          snapshot_json: {
            ...(activeFighter.snapshot_json as Record<string, unknown> | undefined),
            row: newRow,
            col: newCol,
            grid_position: { row: newRow, col: newCol },
          },
        }, activeFighter.version);
      }

      // 3. Roll Attack (d20 + 4 vs AC)
      const d20 = Math.floor(Math.random() * 20) + 1;
      const attackMod = 4;
      const attackTotal = d20 + attackMod;
      const targetAc = nearestPc.armor_class ?? 10;
      const isHit = attackTotal >= targetAc || d20 === 20;
      const isCrit = d20 === 20;

      const dmg = isHit
        ? (isCrit ? (Math.floor(Math.random() * 6) + 1) * 2 + 2 : Math.floor(Math.random() * 6) + 1 + 2)
        : 0;

      // 4. Apply damage if hit
      if (isHit) {
        const nextHp = Math.max(0, (nearestPc.hp ?? 10) - dmg);
        spawnVfx({
          row: targetPos[0],
          col: targetPos[1],
          type: "slash",
          text: `-${dmg}`,
          isCrit,
        });
        const updatedPc = await updateCombatant(campaignId, combatId, nearestPc.id, { hp: nextHp }, nearestPc.version);

        const command: CombatActionCommand = {
          action_type: "damage",
          target_combatant_id: nearestPc.id,
          target_version: updatedPc.version,
          actor_combatant_id: updatedActor.id,
          actor_version: updatedActor.version,
          action_cost: "action",
          action_name: `${activeFighter.display_name} 猛击/射击`,
          amount: dmg,
          damage_type: "slashing",
          is_attack: true,
          attack_roll_total: attackTotal,
          resolution_note: `👹【${activeFighter.display_name}】对【${nearestPc.display_name}】发动攻击：d20(${d20})+${attackMod}=${attackTotal} ➔ 命中！造成 ${dmg} 点伤害！`,
        };
        await confirmCombatAction(campaignId, combatId, command);
      } else {
        spawnVfx({
          row: targetPos[0],
          col: targetPos[1],
          type: "dust",
          text: "未命中",
          isMiss: true,
        });
        const command: CombatActionCommand = {
          action_type: "action",
          actor_combatant_id: updatedActor.id,
          actor_version: updatedActor.version,
          action_cost: "action",
          action_name: `${activeFighter.display_name} 攻击未命中`,
          resolution_note: `👹【${activeFighter.display_name}】对【${nearestPc.display_name}】发动攻击：d20(${d20})+${attackMod}=${attackTotal} ➔ 未命中 (目标 AC ${targetAc})`,
        };
        await confirmCombatAction(campaignId, combatId, command);
      }
    },
    onSuccess: () => {
      soundboard.playAttackHit();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      void queryClient.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
      showToast("👹 敌方 AI 战术行动已执行完毕！", "info");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "怪物行动执行失败", "error");
    },
  });

  // Auto Enemy Turns trigger
  useEffect(() => {
    if (autoEnemies && activeFighter?.entity_type === "monster" && !monsterAiAttackMutation.isPending && !advanceTurnMutation.isPending) {
      const timer = setTimeout(() => {
        monsterAiAttackMutation.mutate();
      }, 1200);
      return () => clearTimeout(timer);
    }
  }, [autoEnemies, activeFighter?.id, activeFighter?.entity_type]);

  // Long rest mutation: restore all spell slots and actions for current actor
  const handleLongRest = async () => {
    if (!activeFighter) return;
    const snap = {
      ...(activeFighter.snapshot_json as Record<string, unknown> | undefined),
      spell_slots: { 1: 4, 2: 3, 3: 2 },
      turn_resources: { action: true, bonus_action: true, reaction: true },
    };
    await updateCombatant(
      campaignId,
      combatId,
      activeFighter.id,
      {
        movement_remaining_ft: activeFighter.speed_ft ?? 30,
        snapshot_json: snap,
      },
      activeFighter.version,
    );
    soundboard.playNat20();
    void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
    showToast("🌙 长休完成：法术位、移动力与动作已全部恢复为满额！", "success");
  };

  // Quick Roll All Initiatives
  const rollInitiativesMutation = useMutation({
    mutationFn: async () => {
      if (!ordered.length) return;
      for (const combatant of ordered) {
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

  // Quick HP adjust mutation
  const quickHpAdjustMutation = useMutation({
    mutationFn: async ({ combatant, delta }: { combatant: Combatant; delta: number }) => {
      const currentHp = combatant.hp ?? 0;
      const maxHp = combatant.max_hp ?? 10;
      const newHp = Math.max(0, Math.min(maxHp, currentHp + delta));
      const pos = combatantGridPosition(combatant) ?? [3, 3];

      spawnVfx({
        row: pos[0],
        col: pos[1],
        type: delta < 0 ? "slash" : "dust",
        text: delta > 0 ? `+${delta}` : `${delta}`,
      });

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

  // Cast Selected Spell with Spell Slot & Action Deduction
  const castSelectedSpellMutation = useMutation({
    mutationFn: async () => {
      if (!selectedSpell || !activeFighter) throw new Error("请选定施法者与法术");

      const spellSlots = getCombatantSpellSlots(activeFighter);
      const turnRes = getCombatantTurnResources(activeFighter);
      const isBonus = selectedSpell.castTime.includes("附赠");

      // Check action economy
      if (isBonus && !turnRes.bonus_action) {
        throw new Error("⚠️ 当前回合附赠动作已耗尽！");
      }
      if (!isBonus && !turnRes.action) {
        throw new Error("⚠️ 当前回合标准动作已耗尽！");
      }

      // Check spell slots
      if (selectedSpellLevel > 0) {
        const available = spellSlots[selectedSpellLevel] ?? 0;
        if (available <= 0) {
          throw new Error(`⚠️ ${selectedSpellLevel} 环法术位已耗尽，无法施法！`);
        }
      }

      const upcastDelta = Math.max(0, selectedSpellLevel - selectedSpell.level);
      const isAoE = selectedSpell.shape !== "single";
      const affectedTargets = isAoE
        ? ordered.filter((f) => targetingValidity.validTargetIds.has(f.id) && f.id !== activeFighter.id)
        : (promptTargetCombatant ? [promptTargetCombatant] : []);

      if (!affectedTargets.length && selectedSpell.shape === "single") {
        throw new Error("请在地图或列表中选定施法目标");
      }

      let baseDiceCount = 1;
      let dieSides = 8;
      if (selectedSpell.damageDiceBase.includes("8d6")) {
        baseDiceCount = 8 + upcastDelta;
        dieSides = 6;
      } else if (selectedSpell.damageDiceBase.includes("3d6")) {
        baseDiceCount = 3 + upcastDelta;
        dieSides = 6;
      } else if (selectedSpell.damageDiceBase.includes("2d8")) {
        baseDiceCount = 2 + upcastDelta;
        dieSides = 8;
      } else if (selectedSpell.damageDiceBase.includes("3d8")) {
        baseDiceCount = 3 + upcastDelta;
        dieSides = 8;
      } else if (selectedSpell.damageDiceBase.includes("1d10")) {
        baseDiceCount = 1;
        dieSides = 10;
      }

      let rollSum = 0;
      for (let i = 0; i < baseDiceCount; i++) {
        const r = Math.floor(Math.random() * dieSides) + 1;
        rollSum += r;
      }

      for (const target of affectedTargets) {
        const pos = combatantGridPosition(target) ?? [3, 5];
        let dmg = rollSum;
        if (selectedSpell.damageType === "healing") {
          const heal = rollSum + 3;
          const nextHp = Math.min(target.max_hp ?? 20, (target.hp ?? 0) + heal);
          spawnVfx({ row: pos[0], col: pos[1], type: "smite", text: `+${heal}` });
          const updated = await updateCombatant(campaignId, combatId, target.id, { hp: nextHp }, target.version);
          target.version = updated.version;
        } else {
          if ((target.damage_immunities ?? []).includes(selectedSpell.damageType)) dmg = 0;
          else if ((target.damage_resistances ?? []).includes(selectedSpell.damageType)) dmg = Math.floor(dmg / 2);

          const nextHp = Math.max(0, (target.hp ?? 10) - dmg);
          spawnVfx({
            row: pos[0],
            col: pos[1],
            type: selectedSpell.vfx,
            text: `-${dmg} (${selectedSpell.damageType})`,
          });
          const updated = await updateCombatant(campaignId, combatId, target.id, { hp: nextHp }, target.version);
          target.version = updated.version;
        }
      }

      // Deduct spell slots and action
      const nextSlots = { ...spellSlots };
      if (selectedSpellLevel > 0) {
        nextSlots[selectedSpellLevel] = Math.max(0, (nextSlots[selectedSpellLevel] ?? 1) - 1);
      }
      const nextTurnRes = {
        ...turnRes,
        action: isBonus ? turnRes.action : false,
        bonus_action: isBonus ? false : turnRes.bonus_action,
      };

      const updatedSnap = {
        ...(activeFighter.snapshot_json as Record<string, unknown> | undefined),
        spell_slots: nextSlots,
        turn_resources: nextTurnRes,
      };

      const updatedActor = await updateCombatant(
        campaignId,
        combatId,
        activeFighter.id,
        { snapshot_json: updatedSnap },
        activeFighter.version,
      );

      const note = `${activeFighter.display_name} 施放【${selectedSpell.name}】(${selectedSpellLevel === 0 ? "戏法" : `${selectedSpellLevel}环，消耗1个${selectedSpellLevel}环法术位`}) ➔ 覆盖 ${affectedTargets.length} 个目标，造成 ${rollSum} 点 ${selectedSpell.damageType} 效果！`;

      const command: CombatActionCommand = {
        action_type: "spell",
        actor_combatant_id: updatedActor.id,
        actor_version: updatedActor.version,
        action_cost: selectedSpell.castTime.includes("附赠") ? "bonus" : "action",
        action_name: `${selectedSpell.name} (${selectedSpellLevel}环)`,
        amount: rollSum,
        damage_type: selectedSpell.damageType,
        resolution_note: note,
      };

      return confirmCombatAction(campaignId, combatId, command);
    },
    onSuccess: () => {
      soundboard.playAttackHit();
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      void queryClient.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
      showToast(`✨ 法术【${selectedSpell?.name}】(${selectedSpellLevel}环) 已成功施展！`, "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "施法失败", "error");
    },
  });

  // Magic Missile Multi-Target Split Execution
  const executeMagicMissileMutation = useMutation({
    mutationFn: async () => {
      if (!activeFighter) throw new Error("无有效施法者");
      const spellSlots = getCombatantSpellSlots(activeFighter);
      const turnRes = getCombatantTurnResources(activeFighter);

      if (!turnRes.action) {
        throw new Error("⚠️ 当前回合标准动作已耗尽！");
      }
      if (selectedSpellLevel > 0 && (spellSlots[selectedSpellLevel] ?? 0) <= 0) {
        throw new Error(`⚠️ ${selectedSpellLevel} 环法术位已耗尽！`);
      }

      const targetEntries = Object.entries(dartAllocations).filter(([, count]) => count > 0);
      if (!targetEntries.length) throw new Error("请为至少一个目标分配飞弹");

      let currentActorVersion = activeFighter.version;

      for (const [targetId, dartCount] of targetEntries) {
        const target = ordered.find((f) => f.id === targetId);
        if (!target) continue;

        let targetTotalDamage = 0;
        const rolls: number[] = [];
        for (let i = 0; i < dartCount; i++) {
          const dmg = Math.floor(Math.random() * 4) + 1 + 1; // 1d4+1
          targetTotalDamage += dmg;
          rolls.push(dmg);
        }

        const nextHp = Math.max(0, (target.hp ?? 10) - targetTotalDamage);
        const pos = combatantGridPosition(target) ?? [3, 5];

        spawnVfx({ row: pos[0], col: pos[1], type: "arcane", text: `-${targetTotalDamage}` });

        // Update target HP and obtain FRESH target version
        const updatedTarget = await updateCombatant(
          campaignId,
          combatId,
          target.id,
          { hp: nextHp },
          target.version,
        );

        const command: CombatActionCommand = {
          action_type: "damage",
          target_combatant_id: target.id,
          target_version: updatedTarget.version,
          actor_combatant_id: activeFighter.id,
          actor_version: currentActorVersion,
          action_cost: "action",
          action_name: "魔法飞弹 (Magic Missile)",
          amount: targetTotalDamage,
          damage_type: "force",
          resolution_note: `${activeFighter.display_name} 射出 ${dartCount} 枚「魔法飞弹」击中 ${target.display_name}（自动必中，各 ${rolls.join("+")} 点）➔ 造成 ${targetTotalDamage} 点力场伤害！`,
        };

        await confirmCombatAction(campaignId, combatId, command);
      }

      // Deduct slot & action
      const nextSlots = { ...spellSlots };
      if (selectedSpellLevel > 0) {
        nextSlots[selectedSpellLevel] = Math.max(0, (nextSlots[selectedSpellLevel] ?? 1) - 1);
      }
      const updatedSnap = {
        ...(activeFighter.snapshot_json as Record<string, unknown> | undefined),
        spell_slots: nextSlots,
        turn_resources: { ...turnRes, action: false },
      };

      await updateCombatant(
        campaignId,
        combatId,
        activeFighter.id,
        { snapshot_json: updatedSnap },
        currentActorVersion,
      );
    },
    onSuccess: () => {
      soundboard.playAttackHit();
      setMagicMissileModalOpen(false);
      setDartAllocations({});
      void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
      void queryClient.invalidateQueries({ queryKey: ["combat-actions", campaignId, combatId] });
      showToast("🚀 魔法飞弹已发射并分别对目标结算必中力场伤害！", "success");
    },
    onError: (err) => {
      showToast(err instanceof Error ? err.message : "施法失败", "error");
    },
  });

  // AI Guidance
  const aiTacticsMutation = useMutation({
    mutationFn: async () => {
      const summary = ordered
        .map((c) => `- ${c.display_name} (${c.entity_type}): HP ${c.hp}/${c.max_hp}, AC ${c.armor_class}, 先攻 ${c.initiative}`)
        .join("\n");
      const prompt = `当前战斗第 ${activeCombat?.round_number ?? 1} 轮，轮到 [${activeFighter?.display_name ?? "当前行动者"}] 行动。\n参战人员状态如下：\n${summary}\n\n请作为资深 D&D 5e 战术军师，给出简明扼要的战术决策建议（包括推荐攻击目标、走位、法术使用与附赠动作搭配，100字左右）。`;
      const res = await runAssistantTurn(campaignId, prompt, { mode: "combat" });
      return res.dm_hint?.text ?? "未能生成战术建议";
    },
    onSuccess: (text) => {
      setAiAnalysis(text);
      soundboard.playHandout();
      showToast("🤖 AI 战术建议已生成！", "success");
    },
  });

  const rollDice = (sides: number) => {
    soundboard.playDiceRoll();
    const mod = Number(customDiceMod) || 0;
    const r = Math.floor(Math.random() * sides) + 1;
    const total = r + mod;
    const isCrit = sides === 20 && r === 20;
    if (isCrit) soundboard.playNat20();
    const entry = { id: `${Date.now()}`, formula: `1d${sides}${mod ? `+${mod}` : ""}`, result: total, rolls: [r], isCrit };
    setDiceHistory((prev) => [entry, ...prev.slice(0, 4)]);
  };

  if (combatsQuery.isLoading) {
    return <LoadingBlock label="正在载入战役战斗数据…" />;
  }

  // Fallback when no combat exists
  if (!activeCombat || (combatsQuery.data ?? []).length === 0) {
    return (
      <div className="mx-auto max-w-4xl p-6">
        <div className="rounded-2xl border border-amber-500/40 bg-gradient-to-b from-ink-900 via-ink-950 to-ink-950 p-8 shadow-2xl text-center">
          <span className="text-5xl">⚡</span>
          <h2 className="mt-4 font-display text-2xl font-bold text-parchment-100">快捷战斗座舱 (Quick Combat)</h2>
          <p className="mt-2 text-sm text-stone-400">
            您可以一键快速发起标准新手遭遇，或手动新建一场遭遇战并导入玩家与怪物。
          </p>

          <div className="mt-8 flex flex-wrap justify-center gap-4">
            <button
              className="rounded-xl border border-amber-500/70 bg-gradient-to-r from-amber-600 to-amber-700 px-6 py-3 text-sm font-bold text-amber-950 shadow-lg shadow-amber-600/30 transition hover:brightness-110 active:scale-95"
              onClick={async () => {
                const combat = await createCombat(campaignId, { name: "红落避难所前厅突袭", round_number: 1, status: "active" });
                await createCombatant(campaignId, combat.id, { display_name: "圣骑士 瓦伦丁", entity_type: "character", hp: 28, max_hp: 28, armor_class: 18, initiative: 17, conditions: [], snapshot_json: { actions: [], row: 3, col: 3, elevation_ft: 0 } });
                await createCombatant(campaignId, combat.id, { display_name: "游侠 艾拉", entity_type: "character", hp: 20, max_hp: 20, armor_class: 15, initiative: 15, conditions: [], snapshot_json: { actions: [], row: 4, col: 2, elevation_ft: 10 } });
                await createCombatant(campaignId, combat.id, { display_name: "地精头目·裂齿", entity_type: "monster", hp: 21, max_hp: 21, armor_class: 15, initiative: 14, conditions: [], snapshot_json: { actions: [], row: 3, col: 7, elevation_ft: 0 } });
                await createCombatant(campaignId, combat.id, { display_name: "地精射手 A", entity_type: "monster", hp: 7, max_hp: 7, armor_class: 13, initiative: 11, conditions: [], snapshot_json: { actions: [], row: 2, col: 8, elevation_ft: 0 } });
                soundboard.playNat20();
                setSelectedCombatId(combat.id);
                void queryClient.invalidateQueries({ queryKey: ["combats", campaignId] });
                showToast("🚀 预设遭遇已创建并载入参战人员！", "success");
              }}
              type="button"
            >
              🚀 一键发起《红落避难所前厅突袭》（4名参战者）
            </button>
          </div>
        </div>
      </div>
    );
  }

  const moverRemaining = (activeFighter?.movement_remaining_ft !== undefined && activeFighter?.movement_remaining_ft !== null)
    ? activeFighter.movement_remaining_ft
    : (activeFighter?.speed_ft ?? 30);
  const moverMaxSpeed = activeFighter?.speed_ft ?? 30;

  return (
    <div className={`flex min-h-screen flex-col justify-between bg-[#080b11] p-3 text-stone-200 ${isFullscreen ? "fixed inset-0 z-50 overflow-y-auto" : ""}`}>
      {/* 1. Top Section: BG3 Floating Initiative Carousel */}
      <header className="mb-2">
        <BG3InitiativeTrack
          activeFighterId={activeFighter?.id ?? null}
          autoEnemies={autoEnemies}
          campaignId={campaignId}
          campaigns={campaignsQuery.data ?? []}
          combatId={combatId}
          combats={combatsQuery.data ?? []}
          fighters={ordered}
          isFullscreen={isFullscreen}
          onAddCombatant={() => setShowAddCombatantModal(true)}
          onRollInitiatives={() => rollInitiativesMutation.mutate()}
          onSelectCampaign={(id) => selectCampaign(id)}
          onSelectCombat={(id) => setSelectedCombatId(id)}
          onSelectCombatant={(id) => {
            setSelectedMapTargetId(id);
            setPromptTargetId(id);
          }}
          onToggleAutoEnemies={() => {
            setAutoEnemies(!autoEnemies);
            showToast(`🤖 怪物自动回合已${!autoEnemies ? "开启" : "关闭"}`, "info");
          }}
          onToggleFullscreen={() => setIsFullscreen(!isFullscreen)}
          roundNumber={activeCombat.round_number}
          selectedTargetId={selectedMapTargetId}
        />
      </header>

      {/* 2. Center Section: 3D Tactical Battlefield + Floating Target Card & Quick Widgets */}
      <main className="relative mb-2 flex-1">
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
          {/* Main 3D Tactical Grid Viewport (8 Cols) */}
          <div className="lg:col-span-8">
            <BG3BattleGrid
              activeFighterId={activeFighter?.id ?? null}
              aimPoint={aimPoint}
              areaKeys={areaKeys}
              campaignId={campaignId}
              combatId={combatId}
              fighters={ordered}
              interactionMode={gridInteractionMode}
              onAimPointChange={setAimPoint}
              onInteractionModeChange={setGridInteractionMode}
              onSpawnVfx={spawnVfx}
              onTargetSelect={(id) => {
                setSelectedMapTargetId(id);
                setPromptTargetId(id);
              }}
              positions={positions}
              selectedTargetId={selectedMapTargetId}
              targeting={targetingRange}
              vfxEvents={vfxEvents}
            />
          </div>

          {/* Right Inspection & Widget Column (4 Cols) */}
          <div className="flex flex-col gap-2 lg:col-span-4">
            {/* Quick HP Adjustment Strip for All Combatants */}
            <div className="bg3-panel rounded-2xl p-2.5 shadow-xl">
              <span className="text-[10px] font-bold text-parchment-200">
                ⚡ 快速生命微调
              </span>
              <div className="mt-1 space-y-1 max-h-24 overflow-y-auto pr-1">
                {ordered.map((f) => (
                  <div className="flex items-center justify-between rounded border border-ink-800 bg-ink-950/70 p-1 text-2xs" key={f.id}>
                    <span className="truncate font-bold text-stone-200">{f.display_name} ({f.hp}/{f.max_hp})</span>
                    <div className="flex gap-1 shrink-0">
                      <button className="rounded border border-rose-900 bg-rose-950/60 px-1 py-0.2 text-[10px] text-rose-300 hover:bg-rose-900" onClick={() => quickHpAdjustMutation.mutate({ combatant: f, delta: -5 })}>-5</button>
                      <button className="rounded border border-rose-900 bg-rose-950/60 px-1 py-0.2 text-[10px] text-rose-300 hover:bg-rose-900" onClick={() => quickHpAdjustMutation.mutate({ combatant: f, delta: -1 })}>-1</button>
                      <button className="rounded border border-emerald-900 bg-emerald-950/60 px-1 py-0.2 text-[10px] text-emerald-300 hover:bg-emerald-900" onClick={() => quickHpAdjustMutation.mutate({ combatant: f, delta: 1 })}>+1</button>
                      <button className="rounded border border-emerald-900 bg-emerald-950/60 px-1 py-0.2 text-[10px] text-emerald-300 hover:bg-emerald-900" onClick={() => quickHpAdjustMutation.mutate({ combatant: f, delta: 5 })}>+5</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Target Inspector Card */}
            <BG3TargetInspector
              activeFighter={activeFighter}
              onQuickDamage={(delta) => {
                if (promptTargetCombatant) {
                  quickHpAdjustMutation.mutate({ combatant: promptTargetCombatant, delta });
                }
              }}
              positions={positions}
              target={promptTargetCombatant}
            />

            {/* Quick Dice Roller & AI Copilot Widget */}
            <div className="grid grid-cols-2 gap-2">
              {/* Quick Dice Roller */}
              <div className="bg3-panel rounded-2xl p-2 shadow-xl flex flex-col justify-between">
                <div className="flex items-center justify-between border-b border-ink-800 pb-1">
                  <span className="text-[10px] font-bold text-parchment-200">🎲 极速骰盘</span>
                  <input
                    className="w-7 rounded border border-ink-700 bg-ink-950 px-1 text-center font-mono text-[10px] text-amber-200"
                    onChange={(e) => setCustomDiceMod(e.target.value)}
                    type="number"
                    value={customDiceMod}
                  />
                </div>
                <div className="mt-1.5 grid grid-cols-3 gap-1">
                  {[20, 12, 10, 8, 6, 4].map((d) => (
                    <button
                      className="rounded border border-ink-700 bg-ink-950/80 py-0.5 text-2xs font-bold text-stone-300 hover:text-amber-200"
                      key={d}
                      onClick={() => rollDice(d)}
                      type="button"
                    >
                      d{d}
                    </button>
                  ))}
                </div>
                {diceHistory.length > 0 ? (
                  <span className="mt-1 text-[9px] font-mono text-amber-300 truncate">
                    {diceHistory[0].formula}➔<strong>{diceHistory[0].result}</strong>
                  </span>
                ) : null}
              </div>

              {/* AI Tactical Copilot */}
              <div className="bg3-panel rounded-2xl p-2 shadow-xl flex flex-col justify-between">
                <div className="flex items-center justify-between border-b border-ink-800 pb-1">
                  <span className="text-[10px] font-bold text-parchment-200">🤖 AI 战术军师</span>
                  <button
                    className="rounded border border-amber-700/60 bg-amber-950/30 px-1.5 py-0.2 text-[9px] text-amber-300 hover:bg-amber-900/40"
                    disabled={aiTacticsMutation.isPending}
                    onClick={() => aiTacticsMutation.mutate()}
                    type="button"
                  >
                    {aiTacticsMutation.isPending ? "思考…" : "战术"}
                  </button>
                </div>
                <div className="mt-1 min-h-[32px] max-h-16 overflow-y-auto text-[9px] text-stone-300">
                  {aiAnalysis ? <p className="text-amber-200/90 leading-tight">{aiAnalysis}</p> : <span className="text-stone-500">点击生成建议</span>}
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* 3. Bottom Section: BG3 Integrated Action Hotbar */}
      <footer>
        <BG3Hotbar
          actions={actionsQuery.data ?? []}
          activeCharacter={activeCharacter}
          activeCombatIndex={activeCombat.current_turn_index ?? 0}
          activeCombatRound={activeCombat.round_number}
          activeFighter={activeFighter}
          activeTab={activeHotbarTab}
          autoEnemies={autoEnemies}
          campaignId={campaignId}
          combatId={combatId}
          handleRangeChange={handleRangeChange}
          handleTargetChange={handleTargetChange}
          isAdvancingTurn={advanceTurnMutation.isPending}
          isCasting={castSelectedSpellMutation.isPending}
          isMonsterAiExecuting={monsterAiAttackMutation.isPending}
          onAdvanceTurn={() => advanceTurnMutation.mutate()}
          onAutoEnemiesChange={setAutoEnemies}
          onCastSpell={() => castSelectedSpellMutation.mutate()}
          onExecuteMonsterAiAttack={() => monsterAiAttackMutation.mutate()}
          onLongRest={handleLongRest}
          onOpenMagicMissileModal={() => {
            const initAlloc: Record<string, number> = {};
            const allowed = 3 + Math.max(0, selectedSpellLevel - 1);
            if (promptTargetCombatant) initAlloc[promptTargetCombatant.id] = allowed;
            else if (ordered[0]) initAlloc[ordered[0].id] = allowed;
            setDartAllocations(initAlloc);
            setMagicMissileModalOpen(true);
          }}
          onOpenMeleeAttack={() => {
            setPromptActionName("近战武器重击 (Melee Attack)");
            setPromptAttackMod("5");
            setPromptDamageDice("1d8+3");
            setPromptDamageType("slashing");
            setIsMeleeAttack(true);
            setActionPromptOpen(true);
          }}
          onOpenOpportunityAttack={() => {
            setPromptActionName("借机攻击 (Opportunity Attack)");
            setPromptAttackMod("5");
            setPromptDamageDice("1d8+3");
            setPromptDamageType("slashing");
            setIsMeleeAttack(true);
            setActionPromptOpen(true);
          }}
          onOpenRangedAttack={() => {
            setPromptActionName("远程射击 (Ranged Attack)");
            setPromptAttackMod("6");
            setPromptDamageDice("1d8+3");
            setPromptDamageType("piercing");
            setIsMeleeAttack(false);
            setActionPromptOpen(true);
          }}
          onQuickHpAdjust={(fighter, delta) => quickHpAdjustMutation.mutate({ combatant: fighter, delta })}
          onResetSpeed={() => {
            if (activeFighter) {
              const maxSpd = activeFighter.speed_ft ?? 30;
              void updateCombatant(campaignId, combatId, activeFighter.id, { movement_remaining_ft: maxSpd }, activeFighter.version)
                .then(() => queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] }));
            }
          }}
          onSelectSpell={handleSelectSpell}
          onSelectSpellLevel={setSelectedSpellLevel}
          onTabChange={setActiveHotbarTab}
          orderedFighters={ordered}
          selectedMaxSpeed={moverMaxSpeed}
          selectedRemaining={moverRemaining}
          selectedSpell={selectedSpell}
          selectedSpellLevel={selectedSpellLevel}
          selectedTargetId={selectedMapTargetId}
          spells={DND_TEST_SPELLS}
          targetingValidity={targetingValidity}
        />
      </footer>

      {/* Magic Missile Multi-Target Allocation Modal */}
      {magicMissileModalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-fuchsia-500 bg-ink-950 p-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-ink-800 pb-2.5">
              <div className="flex items-center gap-2">
                <span className="text-lg">🚀</span>
                <strong className="text-sm text-fuchsia-200">
                  【{selectedSpellLevel} 环】魔法飞弹多目标分配（当前已分配：{Object.values(dartAllocations).reduce((a, b) => a + b, 0)}/{3 + Math.max(0, selectedSpellLevel - 1)} 枚）
                </strong>
              </div>
              <button
                className="text-stone-400 hover:text-stone-200 text-xs"
                onClick={() => setMagicMissileModalOpen(false)}
                type="button"
              >
                ✕ 关闭
              </button>
            </div>

            <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-60 overflow-y-auto">
              {ordered.map((f) => {
                const count = dartAllocations[f.id] ?? 0;
                return (
                  <div className="flex items-center justify-between rounded-xl border border-ink-800 bg-ink-900/80 p-2 text-2xs" key={f.id}>
                    <div className="min-w-0 pr-2">
                      <strong className="truncate block text-stone-200">{f.display_name}</strong>
                      <span className="text-stone-500 font-mono">HP: {f.hp}/{f.max_hp}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button
                        className="h-6 w-6 rounded-lg border border-ink-700 bg-ink-950 text-xs font-bold text-stone-300 hover:bg-ink-800"
                        onClick={() => setDartAllocations((prev) => ({ ...prev, [f.id]: Math.max(0, (prev[f.id] ?? 0) - 1) }))}
                        type="button"
                      >
                        -
                      </button>
                      <span className="w-5 text-center font-bold text-fuchsia-300 font-mono">{count}</span>
                      <button
                        className="h-6 w-6 rounded-lg border border-fuchsia-700 bg-fuchsia-950/60 text-xs font-bold text-fuchsia-200 hover:bg-fuchsia-900"
                        onClick={() => {
                          const total = Object.values(dartAllocations).reduce((a, b) => a + b, 0);
                          const maxAllowed = 3 + Math.max(0, selectedSpellLevel - 1);
                          if (total >= maxAllowed) {
                            showToast(`${selectedSpellLevel}环魔法飞弹最多分配 ${maxAllowed} 枚`, "info");
                            return;
                          }
                          setDartAllocations((prev) => ({ ...prev, [f.id]: (prev[f.id] ?? 0) + 1 }));
                        }}
                        type="button"
                      >
                        +
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="mt-4 flex justify-end gap-2">
              <Button onClick={() => setMagicMissileModalOpen(false)} variant="ghost">取消</Button>
              <Button
                disabled={executeMagicMissileMutation.isPending || Object.values(dartAllocations).reduce((a, b) => a + b, 0) === 0}
                onClick={() => executeMagicMissileMutation.mutate()}
                variant="primary"
              >
                {executeMagicMissileMutation.isPending ? "正在发射…" : "🚀 全数发射并分别扣除必中伤害"}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Add Combatant Modal */}
      {showAddCombatantModal ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-amber-500/50 bg-ink-950 p-6 shadow-2xl">
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
                onClick={async () => {
                  if (!newCombatantName.trim()) return;
                  await createCombatant(campaignId, combatId, {
                    display_name: newCombatantName.trim(),
                    entity_type: newCombatantType,
                    hp: Number(newCombatantHp) || 10,
                    max_hp: Number(newCombatantHp) || 10,
                    armor_class: Number(newCombatantAc) || 10,
                    initiative: Number(newCombatantInit) || 10,
                    conditions: [],
                    snapshot_json: {
                      actions: [],
                      row: Math.floor(Math.random() * 5) + 2,
                      col: Math.floor(Math.random() * 8) + 2,
                      elevation_ft: 0,
                    },
                  });
                  setShowAddCombatantModal(false);
                  setNewCombatantName("");
                  void queryClient.invalidateQueries({ queryKey: ["combatants", campaignId, combatId] });
                  showToast("👥 战斗员已加入战场！", "success");
                }}
                variant="primary"
              >
                加入战场
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {/* Action Prompt / Manual Dice Modal */}
      {actionPromptOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl border border-amber-500 bg-ink-950 p-5 shadow-2xl">
            <div className="flex items-center justify-between border-b border-ink-800 pb-2.5">
              <div className="flex items-center gap-2">
                <span className="text-lg">🎲</span>
                <strong className="text-sm text-parchment-100">
                  {promptActionName} ➔ {promptTargetCombatant?.display_name ?? "目标"}
                </strong>
              </div>
              <button
                className="text-stone-400 hover:text-stone-200 text-xs"
                onClick={() => setActionPromptOpen(false)}
                type="button"
              >
                ✕ 关闭
              </button>
            </div>

            <div className="mt-4 flex flex-col gap-3">
              <button
                className="rounded-xl border border-emerald-600 bg-emerald-600/40 py-2.5 text-xs font-bold text-emerald-200 hover:bg-emerald-600/60 shadow"
                onClick={async () => {
                  if (!activeFighter || !promptTargetCombatant) return;
                  const roll = Math.floor(Math.random() * 20) + 1;
                  const total = roll + Number(promptAttackMod);
                  const isHit = total >= (promptTargetCombatant.armor_class ?? 10);
                  const dmg = Math.floor(Math.random() * 8) + 1 + 3;

                  if (isHit) {
                    quickHpAdjustMutation.mutate({ combatant: promptTargetCombatant, delta: -dmg });
                  }

                  const cmd: CombatActionCommand = {
                    action_type: "damage",
                    target_combatant_id: promptTargetCombatant.id,
                    target_version: promptTargetCombatant.version,
                    actor_combatant_id: activeFighter.id,
                    actor_version: activeFighter.version,
                    action_cost: "action",
                    action_name: promptActionName,
                    amount: isHit ? dmg : 0,
                    damage_type: promptDamageType,
                    is_attack: true,
                    attack_roll_total: total,
                    resolution_note: `${activeFighter.display_name} 发动「${promptActionName}」命中检定 d20(${roll})+${promptAttackMod}=${total} ➔ ${isHit ? `命中！造成 ${dmg} 点伤害` : "未命中"}`,
                  };
                  await confirmCombatAction(campaignId, combatId, cmd);
                  setActionPromptOpen(false);
                  showToast(isHit ? `✅ 命中！造成 ${dmg} 伤害` : "❌ 未命中", isHit ? "success" : "info");
                }}
                type="button"
              >
                🤖 一键自动投骰与智能结算 (推荐)
              </button>

              <div className="rounded-xl border border-amber-800/60 bg-amber-950/20 p-3">
                <span className="text-[10px] text-amber-300 font-bold">✍️ 实体骰录入</span>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  <input
                    className={`${inputCls} font-mono text-xs`}
                    onChange={(e) => setManualAttackRoll(e.target.value)}
                    placeholder="命中点数 (如: 18)"
                    type="number"
                    value={manualAttackRoll}
                  />
                  <input
                    className={`${inputCls} font-mono text-xs`}
                    onChange={(e) => setManualDamageRoll(e.target.value)}
                    placeholder="伤害点数 (如: 7)"
                    type="number"
                    value={manualDamageRoll}
                  />
                </div>
                <button
                  className="mt-2.5 w-full rounded-xl border border-amber-600 bg-amber-600/40 py-2 text-xs font-bold text-amber-200 hover:bg-amber-600/60"
                  onClick={async () => {
                    if (!activeFighter || !promptTargetCombatant) return;
                    const dmg = Number(manualDamageRoll) || 0;
                    if (dmg > 0) {
                      quickHpAdjustMutation.mutate({ combatant: promptTargetCombatant, delta: -dmg });
                    }
                    setActionPromptOpen(false);
                    showToast("✅ 实体骰点数已成功结算！", "success");
                  }}
                  type="button"
                >
                  确认录入实体骰
                </button>
              </div>
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
