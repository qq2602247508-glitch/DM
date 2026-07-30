import type { SceneGrid } from "../api/types";
import type { PersistentSceneObject, SceneToken } from "../api/world";

type PersistentGridData = {
  grid: {
    width: number;
    height: number;
    cell_size_ft: number;
    public_description: string | null;
    layers_json: Record<string, unknown>;
  };
  tokens: SceneToken[];
  objects: PersistentSceneObject[];
};

function objectKind(kind: string): SceneGrid["cells"][number]["kind"] {
  if (["wall", "door", "cover", "terrain", "light", "trap", "treasure", "portal"].includes(kind)) {
    return kind as SceneGrid["cells"][number]["kind"];
  }
  return "object";
}

export function persistentGridAsSceneGrid(data: PersistentGridData, fallbackTheme: string): SceneGrid {
  const layers = data.grid.layers_json as { theme?: unknown; cells?: unknown };
  const layerCells = Array.isArray(layers.cells)
    ? layers.cells.filter((cell): cell is SceneGrid["cells"][number] => Boolean(
      cell && typeof cell === "object" && "row" in cell && "col" in cell && "kind" in cell,
    ))
    : [];
  const occupied = new Set(layerCells.map((cell) => `${cell.row}:${cell.col}`));
  const objectCells: SceneGrid["cells"] = data.objects
    .filter((object) => !occupied.has(`${object.row}:${object.col}`))
    .map((object) => ({
      row: object.row,
      col: object.col,
      kind: objectKind(object.object_type),
      label: object.label,
    }));
  return {
    width: data.grid.width,
    height: data.grid.height,
    cell_size_ft: data.grid.cell_size_ft,
    theme: typeof layers.theme === "string"
      ? layers.theme
      : data.grid.public_description ?? fallbackTheme,
    cells: [...layerCells, ...objectCells],
  };
}
