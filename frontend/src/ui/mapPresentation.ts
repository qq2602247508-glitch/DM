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

const GENERIC_GROUND_LABEL = /^(地板|木地板|石地板|洞窟地面|地面|泥地|草地|道路|通道|走廊|可见|旅店木地板|湿润林地|暮色草地|泥土地院落|地下石地板|林间旧路)$/;

export function shouldShowTerrainLabel(cell: PresentableMapCell | undefined): boolean {
  if (!cell?.label || /出生区/.test(cell.label)) return false;
  if (["room", "stairs", "marker", "lever", "fire"].includes(cell.kind)) return true;
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

const THEME_CELL_CLASSES: Record<string, Partial<Record<string, string>>> = {
  "lantern-tavern": { wall: "bg-stone-800", floor: "bg-amber-950/45", room: "bg-orange-950/70", cover: "bg-amber-900/55", door: "bg-yellow-950/85", fire: "bg-red-950/80" },
  "lantern-tavern-celebration": { wall: "bg-stone-800", floor: "bg-amber-950/45", room: "bg-orange-950/70", cover: "bg-rose-950/65", door: "bg-yellow-950/85", marker: "bg-violet-950/70", fire: "bg-red-950/80" },
  "rainy-forest-crossing": { floor: "bg-green-950/45", room: "bg-emerald-950/60", cover: "bg-emerald-950/90", water: "bg-sky-950/80", difficult: "bg-stone-800/80", marker: "bg-amber-950/75" },
  "dusk-mill-yard": { wall: "bg-stone-800", floor: "bg-lime-950/35", room: "bg-amber-950/65", cover: "bg-amber-950/80", water: "bg-sky-950/75", difficult: "bg-stone-800/80", door: "bg-yellow-950/85", stairs: "bg-violet-950/75" },
  "brass-gear-undercroft": { wall: "bg-stone-950", floor: "bg-zinc-900/75", room: "bg-amber-950/75", cover: "bg-stone-800", door: "bg-yellow-950/85", difficult: "bg-orange-950/65", lever: "bg-emerald-950/70" },
  ocean: { wall: "bg-slate-900", floor: "bg-cyan-950/70", room: "bg-blue-950/70", cover: "bg-teal-950/80", door: "bg-sky-950/80", stairs: "bg-indigo-950/80" },
  ember: { wall: "bg-stone-950", floor: "bg-red-950/60", room: "bg-orange-950/70", cover: "bg-red-950/90", door: "bg-orange-950/80" },
  ice: { wall: "bg-slate-900", floor: "bg-sky-950/50", room: "bg-blue-950/70", cover: "bg-cyan-950/80", door: "bg-blue-950/80" },
  ashen: { wall: "bg-zinc-950", floor: "bg-zinc-900/70", room: "bg-zinc-950/80", cover: "bg-stone-800", door: "bg-stone-900" },
  moss: { wall: "bg-stone-900", floor: "bg-lime-950/40", room: "bg-emerald-950/70", cover: "bg-green-950/90", door: "bg-amber-950/80" },
  violet: { wall: "bg-slate-950", floor: "bg-purple-950/50", room: "bg-purple-950/75", cover: "bg-violet-950/90", door: "bg-fuchsia-950/80" },
  toxic: { wall: "bg-stone-950", floor: "bg-lime-950/60", room: "bg-emerald-950/75", cover: "bg-green-950/90", door: "bg-emerald-950/85" },
  crystal: { wall: "bg-indigo-950", floor: "bg-purple-950/50", room: "bg-indigo-950/75", cover: "bg-fuchsia-950/85", door: "bg-violet-950/85" },
  brass: { wall: "bg-stone-950", floor: "bg-amber-950/60", room: "bg-amber-950/75", cover: "bg-stone-800", door: "bg-yellow-950/85" },
  sandstone: { wall: "bg-stone-900", floor: "bg-yellow-950/50", room: "bg-orange-950/70", cover: "bg-amber-950/90", door: "bg-orange-950/85" },
  fungal: { wall: "bg-stone-950", floor: "bg-emerald-950/50", room: "bg-purple-950/75", cover: "bg-fuchsia-950/85", door: "bg-purple-950/85" },
  shadow: { wall: "bg-black", floor: "bg-slate-950", room: "bg-slate-950/90", cover: "bg-black", door: "bg-indigo-950/90" },
  radiant: { wall: "bg-stone-900", floor: "bg-amber-950/40", room: "bg-yellow-950/70", cover: "bg-amber-900/80", door: "bg-yellow-950/80" },
  forest: { wall: "bg-stone-950", floor: "bg-green-950/50", room: "bg-green-950/75", cover: "bg-emerald-950/90", door: "bg-amber-950/85" },
  storm: { wall: "bg-slate-950", floor: "bg-slate-900/70", room: "bg-slate-950/85", cover: "bg-indigo-950/90", door: "bg-blue-950/85" },
};

export function terrainCellClass(
  cell: PresentableMapCell | undefined,
  theme?: string | null,
): string {
  if (isMapVoidCell(cell)) return "bg-black/80 border-black/70";
  const themed = theme ? THEME_CELL_CLASSES[theme]?.[cell?.kind ?? "floor"] : undefined;
  if (themed) return themed;
  if (cell?.kind === "wall") return "bg-stone-800";
  if (cell?.kind === "cover") return "bg-emerald-950/70";
  if (cell?.kind === "room") return "bg-cyan-950/55";
  if (cell?.kind === "stairs") return "bg-violet-950/70";
  if (cell?.kind === "water") return "bg-sky-950/60";
  if (cell?.kind === "difficult") return "bg-amber-950/55";
  if (cell?.kind === "door") return "bg-amber-950/80";
  if (cell?.kind === "fire") return "bg-red-950/75";
  if (cell?.kind === "lever" || cell?.kind === "marker") return "bg-violet-950/60";
  if (cell?.kind === "object") return "bg-violet-950/60";
  return "bg-ink-900";
}
