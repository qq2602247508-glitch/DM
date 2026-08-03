import type { ReactElement } from "react";

import type { SceneGrid } from "../api/types";
import type { SceneToken } from "../api/world";
import { getDoorOrientation, terrainCellClass } from "../ui/mapPresentation";

export function SceneGridPreview({
  grid,
  tokens = [],
  compact = false,
}: {
  grid: SceneGrid;
  tokens?: SceneToken[];
  compact?: boolean;
}): ReactElement {
  const cells = new Map(grid.cells.map((cell) => [`${cell.row}:${cell.col}`, cell]));
  const tokenCells = new Map(tokens.map((token) => [`${token.row}:${token.col}`, token]));
  return (
    <div className="mt-3">
      <p className="mb-2 text-2xs text-stone-500">
        {grid.theme} · {grid.width}×{grid.height} · 每格 {grid.cell_size_ft} 尺
      </p>
      <div
        aria-label={`${grid.width}×${grid.height} Scene 网格预览`}
        className={`grid gap-px overflow-hidden rounded border border-ink-700 bg-ink-700 ${compact ? "max-w-[380px]" : "max-w-[600px]"}`}
        style={{ gridTemplateColumns: `repeat(${grid.width}, minmax(0, 1fr))` }}
      >
        {Array.from({ length: grid.width * grid.height }, (_, index) => {
          const row = Math.floor(index / grid.width) + 1;
          const col = (index % grid.width) + 1;
          const cell = cells.get(`${row}:${col}`);
          const token = tokenCells.get(`${row}:${col}`);
          const orientation = cell?.kind === "door" ? getDoorOrientation(grid.cells, row, col) : null;
          return (
            <div
              className={`relative aspect-square ${compact ? "min-h-2" : "min-h-4"} ${terrainCellClass(cell, grid.theme)}`}
              key={`${row}-${col}`}
              title={token ? `${token.label} · ${row},${col}` : cell?.label ?? `地面 · ${row},${col}`}
            >
              {cell?.kind === "door" ? (
                <span className={`absolute rounded bg-amber-400 ${orientation === "vertical" ? "inset-y-[15%] left-1/2 w-px -translate-x-1/2" : "inset-x-[15%] top-1/2 h-px -translate-y-1/2"}`} />
              ) : null}
              {token ? <span className="absolute inset-[18%] rounded-full border border-sky-100 bg-sky-500 shadow" /> : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
