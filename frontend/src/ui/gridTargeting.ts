import type { SceneGrid } from "../api/types";

export type GridPoint = { row: number; col: number };
export type TargetShape = "single" | "circle" | "cone" | "line";

export type TargetingTemplate = {
  shape: TargetShape;
  /** Maximum distance from caster to the selected aim point. */
  rangeFt: number;
  /** Circle radius, cone length, or line length. Defaults to rangeFt. */
  sizeFt?: number;
  /** Line width in feet. Defaults to one grid cell. */
  widthFt?: number;
};

function cellsForGrid(grid: Pick<SceneGrid, "width" | "height">): GridPoint[] {
  return Array.from({ length: grid.height }, (_, row) => (
    Array.from({ length: grid.width }, (_, col) => ({ row: row + 1, col: col + 1 }))
  )).flat();
}

export function gridDistanceFt(
  from: GridPoint,
  to: GridPoint,
  cellSizeFt = 5,
): number {
  // 5e treats diagonal movement as one square unless the optional alternating
  // diagonal rule is enabled, so Chebyshev distance is the useful UI default.
  return Math.max(Math.abs(to.row - from.row), Math.abs(to.col - from.col)) * cellSizeFt;
}

export function isAimPointInRange(
  origin: GridPoint,
  aim: GridPoint,
  rangeFt: number,
  cellSizeFt = 5,
): boolean {
  return gridDistanceFt(origin, aim, cellSizeFt) <= rangeFt;
}

function vector(from: GridPoint, to: GridPoint): [number, number] {
  return [to.col - from.col, to.row - from.row];
}

function vectorLength([x, y]: [number, number]): number {
  return Math.hypot(x, y);
}

function distanceToSegment(point: GridPoint, start: GridPoint, end: GridPoint): number {
  const [segmentX, segmentY] = vector(start, end);
  const [pointX, pointY] = vector(start, point);
  const lengthSquared = segmentX * segmentX + segmentY * segmentY;
  if (lengthSquared === 0) return Math.hypot(pointX, pointY);
  const projection = Math.max(0, Math.min(1, (pointX * segmentX + pointY * segmentY) / lengthSquared));
  return Math.hypot(pointX - projection * segmentX, pointY - projection * segmentY);
}

export function getTargetingCells(
  grid: Pick<SceneGrid, "width" | "height" | "cell_size_ft">,
  origin: GridPoint,
  aim: GridPoint,
  template: TargetingTemplate,
): GridPoint[] {
  const cellSizeFt = grid.cell_size_ft;
  if (!isAimPointInRange(origin, aim, template.rangeFt, cellSizeFt)) return [];
  if (template.shape === "single") return [aim];

  const cells = cellsForGrid(grid);
  const sizeCells = Math.max(0, (template.sizeFt ?? template.rangeFt) / cellSizeFt);
  if (template.shape === "circle") {
    return cells.filter((cell) => vectorLength(vector(aim, cell)) <= sizeCells + 0.01);
  }

  const [directionX, directionY] = vector(origin, aim);
  const directionLength = Math.hypot(directionX, directionY);
  if (directionLength === 0) return [origin];
  const normalizedX = directionX / directionLength;
  const normalizedY = directionY / directionLength;
  const end: GridPoint = {
    row: origin.row + normalizedY * sizeCells,
    col: origin.col + normalizedX * sizeCells,
  };

  if (template.shape === "line") {
    const halfWidthCells = Math.max(0.5, (template.widthFt ?? cellSizeFt) / cellSizeFt / 2);
    return cells.filter((cell) => {
      const [cellX, cellY] = vector(origin, cell);
      const forward = cellX * normalizedX + cellY * normalizedY;
      return forward >= 0 && forward <= sizeCells + 0.01
        && distanceToSegment(cell, origin, end) <= halfWidthCells + 0.01;
    });
  }

  // A 5e cone is as wide as the distance from its origin. This is equivalent
  // to a 90-degree sector (45 degrees on either side of the chosen direction).
  return cells.filter((cell) => {
    const [cellX, cellY] = vector(origin, cell);
    const distance = Math.hypot(cellX, cellY);
    if (distance > sizeCells + 0.01) return false;
    if (distance === 0) return true;
    const forward = cellX * normalizedX + cellY * normalizedY;
    return forward >= 0 && forward / distance >= Math.SQRT1_2 - 0.01;
  });
}

export function isBlockedCell(grid: SceneGrid, point: GridPoint): boolean {
  return grid.cells.some(
    (cell) => cell.row === point.row && cell.col === point.col && cell.kind === "wall",
  );
}
