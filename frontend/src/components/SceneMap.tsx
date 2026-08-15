import { useState, useEffect, type ReactElement } from "react";

import {
  getDoorOrientation,
  isMapVoidCell,
  shouldShowTerrainLabel,
  terrainCellClass,
} from "../ui/mapPresentation";
import { soundboard } from "../ui/soundboard";

export type SceneMapGrid = {
  width: number;
  height: number;
  cell_size_ft: number;
  theme?: string | null;
  fog_of_war?: boolean;
  explored_cells?: Array<{ row: number; col: number }>;
  visible_cells?: Array<{ row: number; col: number }>;
  cells?: Array<{ row: number; col: number; kind: string; label?: string }>;
};

export type SceneMapToken = {
  id: string;
  entity_id?: string | null;
  entity_type: string;
  label: string;
  row: number;
  col: number;
  targetKey?: string;
  isOwn?: boolean;
  avatar_url?: string | null;
  conditions?: Array<string | { condition_name?: string; name?: string }>;
  isConcentrating?: boolean;
  hp?: number;
  max_hp?: number;
};

export type MapPing = {
  id: string;
  row: number;
  col: number;
  label?: string;
  color?: string;
  timestamp: number;
};

export type SceneMapObject = {
  id: string;
  object_type: string;
  label: string;
  row: number;
  col: number;
  state: string;
  targetKey?: string;
};

function conditionBadge(cond: string | { condition_name?: string; name?: string }): string | null {
  const name = typeof cond === "string" ? cond.toLowerCase() : (cond.condition_name ?? cond.name ?? "").toLowerCase();
  if (name.includes("prone") || name.includes("倒地")) return "🛌";
  if (name.includes("stun") || name.includes("震慑") || name.includes("眩晕")) return "💫";
  if (name.includes("blind") || name.includes("目盲")) return "👁️";
  if (name.includes("paralyz") || name.includes("麻痹")) return "⚡";
  if (name.includes("poison") || name.includes("中毒")) return "🧪";
  if (name.includes("unconscious") || name.includes("昏迷")) return "💤";
  if (name.includes("fright") || name.includes("恐慌") || name.includes("恐惧")) return "😱";
  if (name.includes("grapple") || name.includes("擒抱") || name.includes("restrain") || name.includes("束缚")) return "🕸️";
  if (name.includes("charm") || name.includes("魅惑")) return "💖";
  if (name.includes("invisible") || name.includes("隐形")) return "👻";
  if (name.includes("dying") || name.includes("濒死")) return "💀";
  if (name.includes("concentrat") || name.includes("专注")) return "🔮";
  return "⚠️";
}

export function SceneMap({
  grid,
  tokens,
  objects,
  pings = [],
  selectedTargetKey,
  selectedTargetKeys,
  selectableTargetKeys = new Set(),
  affectedCellKeys = new Set(),
  dangerCellKeys = new Set(),
  movementCellKeys = new Set(),
  rangeCellKeys = new Set(),
  enemyRangeCellKeys = new Set(),
  onTargetSelect,
  onAimSelect,
  onCellSelect,
  onPing,
  canSelectAimCell,
  canSelectCell,
  title = "统一场景地图",
  compactCells = false,
}: {
  grid: SceneMapGrid;
  tokens: SceneMapToken[];
  objects: SceneMapObject[];
  pings?: MapPing[];
  selectedTargetKey?: string;
  selectedTargetKeys?: ReadonlySet<string>;
  selectableTargetKeys?: ReadonlySet<string>;
  affectedCellKeys?: ReadonlySet<string>;
  dangerCellKeys?: ReadonlySet<string>;
  movementCellKeys?: ReadonlySet<string>;
  rangeCellKeys?: ReadonlySet<string>;
  enemyRangeCellKeys?: ReadonlySet<string>;
  onTargetSelect?: (targetKey: string) => void;
  onAimSelect?: (row: number, col: number) => void;
  onCellSelect?: (row: number, col: number) => void;
  onPing?: (row: number, col: number) => void;
  canSelectAimCell?: (row: number, col: number) => boolean;
  canSelectCell?: (row: number, col: number) => boolean;
  title?: string;
  compactCells?: boolean;
}): ReactElement {
  const [localPings, setLocalPings] = useState<MapPing[]>([]);
  const tokensByCell = new Map(tokens.map((item) => [`${item.row}:${item.col}`, item]));
  const objectsByCell = new Map(objects.map((item) => [`${item.row}:${item.col}`, item]));
  const terrainByCell = new Map((grid.cells ?? []).map((item) => [`${item.row}:${item.col}`, item]));
  const exploredKeys = new Set(
    (grid.explored_cells ?? []).map((item) => `${item.row}:${item.col}`),
  );
  const visibleKeys = new Set(
    (grid.visible_cells ?? []).map((item) => `${item.row}:${item.col}`),
  );

  // Clean up expired local pings
  useEffect(() => {
    if (localPings.length === 0) return;
    const timer = window.setInterval(() => {
      const now = Date.now();
      setLocalPings((prev) => prev.filter((p) => now - p.timestamp < 3500));
    }, 500);
    return () => window.clearInterval(timer);
  }, [localPings.length]);

  const allPings = [...pings, ...localPings];
  const pingsByCell = new Map<string, MapPing[]>();
  allPings.forEach((p) => {
    const k = `${p.row}:${p.col}`;
    pingsByCell.set(k, [...(pingsByCell.get(k) ?? []), p]);
  });

  const triggerPing = (row: number, col: number) => {
    soundboard.playPing();
    const newPing: MapPing = {
      id: `${Date.now()}-${Math.random()}`,
      row,
      col,
      timestamp: Date.now(),
      color: "#f59e0b",
    };
    setLocalPings((prev) => [...prev, newPing]);
    onPing?.(row, col);
  };

  return (
    <div className="overflow-auto rounded border border-ink-700 bg-ink-950 p-2">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-2xs text-stone-500">
        <div className="flex flex-wrap items-center gap-2">
          <strong className="text-stone-300">{title}</strong>
          <span>{grid.width}×{grid.height} · 每格 {grid.cell_size_ft} 尺</span>
          {grid.fog_of_war ? <span className="text-violet-300">战争迷雾：黑色为未探索，暗色为已探索但当前不可见</span> : null}
          {rangeCellKeys.size ? <span className="text-sky-300">蓝色格：法术瞄准</span> : null}
          {enemyRangeCellKeys.size ? <span className="text-orange-300">橙色格：敌方可达</span> : null}
          {selectableTargetKeys.size ? <span className="text-emerald-300">绿色虚线：可选目标</span> : null}
          {selectedTargetKey ? <span className="text-emerald-200">绿色实框：当前目标</span> : null}
          {movementCellKeys.size ? <span className="text-lime-300">绿色格：可移动</span> : null}
        </div>
        <span className="text-stone-400">💡 提示：双击或 Alt+点击 地图任意位置可发送即时 Ping 信号</span>
      </div>
      <div
        className={`grid gap-px bg-ink-700 ${compactCells ? "w-max max-w-none" : "min-w-[560px]"}`}
        style={{
          gridTemplateColumns: compactCells
            ? `repeat(${grid.width}, minmax(28px, 48px))`
            : `repeat(${grid.width}, minmax(28px, 1fr))`,
        }}
      >
        {Array.from({ length: grid.width * grid.height }, (_, index) => {
          const row = Math.floor(index / grid.width) + 1;
          const col = index % grid.width + 1;
          const key = `${row}:${col}`;
          const token = tokensByCell.get(key);
          const object = objectsByCell.get(key);
          const terrain = terrainByCell.get(key);
          const cellPings = pingsByCell.get(key) ?? [];
          const fogEnabled = Boolean(grid.fog_of_war);
          const explored = !fogEnabled || exploredKeys.has(key);
          const visible = !fogEnabled || visibleKeys.has(key);
          const unexplored = fogEnabled && !explored;
          const obscured = fogEnabled && explored && !visible;
          const targetKey = token?.targetKey ?? object?.targetKey;
          const selectable = Boolean(targetKey && selectableTargetKeys.has(targetKey));
          const selected = Boolean(
            targetKey
            && (targetKey === selectedTargetKey || selectedTargetKeys?.has(targetKey)),
          );
          const affected = affectedCellKeys.has(key);
          const dangerous = dangerCellKeys.has(key);
          const movable = movementCellKeys.has(key);
          const inRange = rangeCellKeys.has(key);
          const enemyInRange = enemyRangeCellKeys.has(key);
          const blocked = terrain?.kind === "wall"
            || object?.object_type === "wall"
            || (object?.object_type === "door" && object.state !== "open");
          const cellSelectable = Boolean(
            !unexplored && !token && !object && onCellSelect && canSelectCell?.(row, col),
          );
          const aimCellSelectable = Boolean(
            !unexplored && !blocked && onAimSelect && canSelectAimCell?.(row, col),
          );
          const terrainClass = unexplored
            ? "bg-black border-black/90"
            : `${terrainCellClass(terrain, grid.theme)} ${obscured ? "brightness-[.35] saturate-50" : ""}`;
          const isVoid = isMapVoidCell(terrain);
          const isDoor = terrain?.kind === "door" || object?.object_type === "door";
          const doorOrientation = isDoor
            ? getDoorOrientation(grid.cells ?? [], row, col)
            : null;
          const interactive = selectable || cellSelectable || aimCellSelectable;
          const cellClass = `relative aspect-square border border-ink-800 text-[9px] transition duration-200 ${terrainClass} ${movable ? "bg-emerald-950/75 ring-1 ring-inset ring-emerald-400/75" : ""} ${inRange ? "bg-sky-950/60 ring-1 ring-inset ring-sky-500/50" : ""} ${enemyInRange ? "bg-orange-950/55 ring-1 ring-inset ring-orange-400/60" : ""} ${affected ? "bg-fuchsia-900/70 ring-2 ring-inset ring-fuchsia-400/80" : ""} ${dangerous ? "bg-red-950/65 outline outline-2 outline-inset outline-red-500 shadow-[inset_0_0_10px_rgba(239,68,68,.35)]" : ""} ${selectable ? "cursor-pointer outline outline-2 outline-dashed outline-emerald-500/70 hover:bg-emerald-950/60" : ""} ${selected ? "z-10 ring-4 ring-inset ring-emerald-300 shadow-[0_0_12px_rgba(110,231,183,.8)]" : ""} ${cellSelectable || aimCellSelectable ? "cursor-pointer hover:bg-emerald-950/70" : ""}`;

          // Condition Badges
          const rawConditions = token?.conditions ?? [];
          const badges = rawConditions
            .map(conditionBadge)
            .filter((b): b is string => b !== null)
            .slice(0, 3);
          const isConcentrating = token?.isConcentrating;

          const cellContent = explored ? (
            <>
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
              {object && object.object_type !== "wall" && !isVoid && !isDoor ? <span className="absolute left-0 top-0 max-w-full truncate text-stone-500">{object.label.slice(0, 2)}</span> : null}
              {!token && shouldShowTerrainLabel(terrain) ? (
                <span className="absolute inset-x-0 bottom-0 truncate px-0.5 text-[8px] text-stone-500">{terrain?.label?.slice(0, 5)}</span>
              ) : null}
              {token ? (
                <div className="relative flex h-full w-full items-center justify-center p-0.5">
                  {/* Token Avatar / Body */}
                  <span
                    className={`flex h-full w-full items-center justify-center overflow-hidden rounded-full border text-center font-semibold shadow-md transition-transform ${
                      token.isOwn
                        ? "border-amber-400 bg-amber-500/40 text-amber-100 ring-1 ring-amber-300/60"
                        : token.entity_type === "monster"
                          ? "border-red-500 bg-red-900/60 text-red-100 ring-1 ring-red-400/50"
                          : token.entity_type === "npc"
                            ? "border-violet-500 bg-violet-900/50 text-violet-100 ring-1 ring-violet-400/40"
                            : "border-sky-500 bg-sky-900/50 text-sky-100 ring-1 ring-sky-400/40"
                    } ${isConcentrating ? "ring-2 ring-cyan-400 ring-offset-1 ring-offset-ink-950 shadow-[0_0_8px_rgba(34,211,238,0.8)]" : ""}`}
                  >
                    {token.avatar_url ? (
                      <img alt={token.label} className="h-full w-full object-cover" src={token.avatar_url} />
                    ) : (
                      <span className="truncate px-0.5">{token.label.slice(0, 3)}</span>
                    )}
                  </span>

                  {/* Status Condition Badges */}
                  {badges.length > 0 ? (
                    <span className="absolute -right-1 -top-1 z-20 flex gap-0.5 rounded-full bg-ink-950/90 px-0.5 text-[9px] shadow-sm">
                      {badges.map((icon, i) => (
                        <span key={i}>{icon}</span>
                      ))}
                    </span>
                  ) : null}

                  {/* Concentration Aura Indicator */}
                  {isConcentrating ? (
                    <span
                      className="absolute -bottom-1 -left-1 z-20 rounded-full bg-cyan-950/90 px-0.5 text-[8px] text-cyan-300 shadow-sm"
                      title="维持专注中"
                    >
                      🔮
                    </span>
                  ) : null}

                  {/* Mini HP bar if recorded */}
                  {token.hp !== undefined && token.max_hp !== undefined && token.max_hp > 0 ? (
                    <div className="absolute inset-x-1 bottom-0 z-10 h-0.5 overflow-hidden rounded-full bg-black/80">
                      <div
                        className={`h-full ${
                          token.hp / token.max_hp > 0.5
                            ? "bg-emerald-400"
                            : token.hp / token.max_hp > 0.2
                              ? "bg-amber-400"
                              : "bg-rose-500"
                        }`}
                        style={{ width: `${Math.max(0, Math.min(100, (token.hp / token.max_hp) * 100))}%` }}
                      />
                    </div>
                  ) : null}
                </div>
              ) : null}
              {/* Map Ping Animation Overlay */}
              {cellPings.map((p) => (
                <span
                  className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center"
                  key={p.id}
                >
                  <span
                    className="absolute h-10 w-10 animate-ping rounded-full opacity-80"
                    style={{ backgroundColor: p.color || "#f59e0b" }}
                  />
                  <span
                    className="relative h-3 w-3 rounded-full border border-white/80 shadow-md"
                    style={{ backgroundColor: p.color || "#f59e0b" }}
                  />
                </span>
              ))}
            </>
          ) : null;
          const fogLayer = unexplored ? (
            <span aria-hidden className="pointer-events-none absolute inset-0 bg-black/95 shadow-[inset_0_0_8px_rgba(0,0,0,.95)]" />
          ) : obscured ? (
            <span aria-hidden className="pointer-events-none absolute inset-0 bg-black/55 shadow-[inset_0_0_8px_rgba(0,0,0,.75)]" />
          ) : null;
          if (!interactive) {
            return (
              <div
                aria-hidden={!token && !object ? "true" : undefined}
                aria-label={token || object ? `格子 ${row},${col}${token ? ` · ${token.label}` : ` · ${object?.label}`}` : undefined}
                className={cellClass}
                data-grid-col={col}
                data-grid-row={row}
                data-token-id={token?.id}
                key={key}
                onDoubleClick={() => triggerPing(row, col)}
                role={token || object ? "img" : "presentation"}
                title={token?.label ?? object?.label ?? terrain?.label ?? `${row},${col} (双击发送Ping)`}
              >
                {cellContent}
                {fogLayer}
              </div>
            );
          }
          return (
            <button
              aria-label={`格子 ${row},${col}${token ? ` · ${token.label}` : object ? ` · ${object.label}` : ""}`}
              className={cellClass}
              data-grid-col={col}
              data-grid-row={row}
              data-token-id={token?.id}
              disabled={blocked}
              key={key}
              onClick={(e) => {
                if (e.altKey || e.shiftKey) {
                  triggerPing(row, col);
                  return;
                }
                if (aimCellSelectable) onAimSelect?.(row, col);
                else if (selectable && targetKey) onTargetSelect?.(targetKey);
                else if (cellSelectable) onCellSelect?.(row, col);
              }}
              onDoubleClick={() => triggerPing(row, col)}
              title={token?.label ?? object?.label ?? terrain?.label ?? `${row},${col} (双击发送Ping)`}
              type="button"
            >
              {cellContent}
              {fogLayer}
            </button>
          );
        })}
      </div>
    </div>
  );
}

