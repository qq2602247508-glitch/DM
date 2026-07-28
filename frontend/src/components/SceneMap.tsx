import type { ReactElement } from "react";

export type SceneMapGrid = {
  width: number;
  height: number;
  cell_size_ft: number;
  theme?: string | null;
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

export function SceneMap({
  grid,
  tokens,
  objects,
  selectedTargetKey,
  selectedTargetKeys,
  selectableTargetKeys = new Set(),
  affectedCellKeys = new Set(),
  movementCellKeys = new Set(),
  rangeCellKeys = new Set(),
  onTargetSelect,
  onCellSelect,
  canSelectCell,
  title = "统一场景地图",
  compactCells = false,
}: {
  grid: SceneMapGrid;
  tokens: SceneMapToken[];
  objects: SceneMapObject[];
  selectedTargetKey?: string;
  selectedTargetKeys?: ReadonlySet<string>;
  selectableTargetKeys?: ReadonlySet<string>;
  affectedCellKeys?: ReadonlySet<string>;
  movementCellKeys?: ReadonlySet<string>;
  rangeCellKeys?: ReadonlySet<string>;
  onTargetSelect?: (targetKey: string) => void;
  onCellSelect?: (row: number, col: number) => void;
  canSelectCell?: (row: number, col: number) => boolean;
  title?: string;
  compactCells?: boolean;
}): ReactElement {
  const tokensByCell = new Map(tokens.map((item) => [`${item.row}:${item.col}`, item]));
  const objectsByCell = new Map(objects.map((item) => [`${item.row}:${item.col}`, item]));
  const terrainByCell = new Map((grid.cells ?? []).map((item) => [`${item.row}:${item.col}`, item]));
  return (
    <div className="overflow-auto rounded border border-ink-700 bg-ink-950 p-2">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-2xs text-stone-500">
        <strong className="text-stone-300">{title}</strong>
        <span>{grid.width}×{grid.height} · 每格 {grid.cell_size_ft} 尺</span>
        {selectableTargetKeys.size ? <span className="text-emerald-300">绿色虚线：可以点击的目标</span> : null}
        {selectedTargetKey ? <span className="text-emerald-200">绿色实框：当前目标</span> : null}
        {movementCellKeys.size ? <span className="text-lime-300">绿色格：本回合剩余可移动范围</span> : null}
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
          const targetKey = token?.targetKey ?? object?.targetKey;
          const selectable = Boolean(targetKey && selectableTargetKeys.has(targetKey));
          const selected = Boolean(
            targetKey
            && (targetKey === selectedTargetKey || selectedTargetKeys?.has(targetKey)),
          );
          const affected = affectedCellKeys.has(key);
          const movable = movementCellKeys.has(key);
          const inRange = rangeCellKeys.has(key);
          const blocked = terrain?.kind === "wall"
            || object?.object_type === "wall"
            || (object?.object_type === "door" && object.state !== "open");
          const cellSelectable = Boolean(
            !token && !object && onCellSelect && canSelectCell?.(row, col),
          );
          const terrainClass = terrain?.kind === "wall"
            ? "bg-stone-800"
            : terrain?.kind === "cover"
              ? "bg-emerald-950/70"
              : terrain?.kind === "water"
                ? "bg-sky-950/60"
                : terrain?.kind === "door"
                  ? "bg-amber-950/70"
                  : "bg-ink-900";
          return (
            <button
              aria-label={`格子 ${row},${col}${token ? ` · ${token.label}` : object ? ` · ${object.label}` : ""}`}
              className={`relative aspect-square border border-ink-800 text-[9px] transition duration-200 ${terrainClass} ${movable ? "bg-emerald-950/75 ring-1 ring-inset ring-emerald-400/75" : ""} ${inRange ? "bg-sky-950/60 ring-1 ring-inset ring-sky-500/50" : ""} ${affected ? "bg-fuchsia-900/70 ring-2 ring-inset ring-fuchsia-400/80" : ""} ${selectable ? "cursor-pointer outline outline-2 outline-dashed outline-emerald-500/70 hover:bg-emerald-950/60" : ""} ${selected ? "z-10 ring-4 ring-inset ring-emerald-300 shadow-[0_0_12px_rgba(110,231,183,.8)]" : ""} ${cellSelectable ? "cursor-pointer hover:bg-emerald-950/70" : ""}`}
              disabled={blocked || (!selectable && !cellSelectable)}
              key={key}
              onClick={() => {
                if (selectable && targetKey) onTargetSelect?.(targetKey);
                else if (cellSelectable) onCellSelect?.(row, col);
              }}
              title={token?.label ?? object?.label ?? terrain?.label ?? `${row},${col}`}
              type="button"
            >
              {object ? <span className="absolute left-0 top-0 max-w-full truncate text-stone-500">{object.label.slice(0, 2)}</span> : null}
              {token ? (
                <span className={`flex h-full items-center justify-center rounded-full px-1 text-center ${token.isOwn ? "bg-amber-500/35 text-amber-100" : token.entity_type === "monster" ? "bg-red-500/30 text-red-100" : token.entity_type === "npc" ? "bg-violet-500/25 text-violet-100" : "bg-blue-500/25 text-blue-100"}`}>
                  {token.label.slice(0, 4)}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
