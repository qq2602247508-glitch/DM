export type PresentableMapCell = {
  row: number;
  col: number;
  kind: string;
  label?: string;
};

export type DoorOrientation = "horizontal" | "vertical";

export function isMapVoidCell(cell: PresentableMapCell | undefined): boolean {
  return cell?.kind === "wall" && cell.label === "地图外区域";
}

const GENERIC_GROUND_LABEL = /^(地板|木地板|石地板|洞窟地面|地面|泥地|草地|道路|通道|走廊|可见)$/;

export function shouldShowTerrainLabel(cell: PresentableMapCell | undefined): boolean {
  if (!cell?.label || /出生区/.test(cell.label)) return false;
  if (cell.kind === "room" || cell.kind === "stairs") return true;
  return cell.kind === "floor" && !GENERIC_GROUND_LABEL.test(cell.label.trim());
}

export function getDoorOrientation(
  cells: readonly PresentableMapCell[],
  row: number,
  col: number,
): DoorOrientation {
  const blocking = new Set(
    cells
      .filter((cell) => cell.kind === "wall")
      .map((cell) => `${cell.row}:${cell.col}`),
  );
  const verticalWall = blocking.has(`${row - 1}:${col}`) || blocking.has(`${row + 1}:${col}`);
  const horizontalWall = blocking.has(`${row}:${col - 1}`) || blocking.has(`${row}:${col + 1}`);
  return verticalWall && !horizontalWall ? "vertical" : "horizontal";
}

export function terrainCellClass(cell: PresentableMapCell | undefined): string {
  if (isMapVoidCell(cell)) return "bg-black/80 border-black/70";
  if (cell?.kind === "wall") return "bg-stone-800";
  if (cell?.kind === "cover") return "bg-emerald-950/70";
  if (cell?.kind === "room") return "bg-cyan-950/55";
  if (cell?.kind === "stairs") return "bg-violet-950/70";
  if (cell?.kind === "water") return "bg-sky-950/60";
  if (cell?.kind === "door") return "bg-amber-950/80";
  if (cell?.kind === "object") return "bg-violet-950/60";
  return "bg-ink-900";
}
